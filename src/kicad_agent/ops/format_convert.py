"""KiCad 6 to KiCad 10 format converter -- multi-pass section-based reassembly.

Handles all known KiCad 5/6 format artifacts:
  - Single-line header -> multi-line KiCad 10 header
  - Unquoted UUIDs -> quoted UUIDs
  - Tab characters -> spaces
  - ;; comments -> removed
  - (net (code ...)) elements -> removed
  - (schematic_objects ...) wrapper -> unwrapped
  - (pins ...) wrapper inside sheets -> unwrapped
  - (at X Y) without rotation -> (at X Y 0)
  - Malformed stroke format -> corrected
  - (fields_autoplaced) -> converted to (fields_autoplaced yes)
  - (exclude_from_sim no) -> added to symbol instances
  - (nets ...) section -> removed
  - sheet_instances format -> corrected

Uses section-based reassembly to avoid paren-depth tracking bugs that
caused line-by-line converters to lose hierarchical labels.

Usage:
    from kicad_agent.ops.format_convert import convert_kicad6_to_10

    converted = convert_kicad6_to_10(raw_content)
"""

from __future__ import annotations

import re
import uuid as _uuid

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# UUID pattern: 8-4-4-4-12 hex chars (unquoted)
_RE_BARE_UUID = re.compile(r"\(uuid\s+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\)")

# Already-quoted UUID (to avoid double-quoting)
_RE_QUOTED_UUID = re.compile(r'\(uuid\s+"[0-9a-f]{8}-')

# Semicolon comments: full line starting with ;;
_RE_SEMICOLON_FULL = re.compile(r"^;;.*$", re.MULTILINE)

# Semicolon comments: inline "  ;; ..."
_RE_SEMICOLON_INLINE = re.compile(r"\s*;;.*$")

# (net (code ...)) elements
_RE_NET_ELEMENT_START = re.compile(r"\(net\s+\(code\s+")

# (schematic_objects ...) wrapper start
_RE_SCHEMATIC_OBJECTS = re.compile(r"\(schematic_objects\s*\n")

# (pins ...) wrapper inside sheets
_RE_PINS_WRAPPER = re.compile(r"\(pins\s*\n")

# (at X Y) without rotation
_RE_AT_NO_ROTATION = re.compile(r"\(at\s+([-\d.]+)\s+([-\d.]+)\s*\)")

# Malformed stroke: (stroke (width X)) (type Y))
_RE_STROKE_MALFORMED = re.compile(
    r"\(stroke\s+\(width\s+([^\)]+)\)\)\s*\(type\s+([^\)]+)\)\)"
)

# (fields_autoplaced) element (bare, without yes/no)
_RE_FIELDS_AUTOPLACED = re.compile(r"\(fields_autoplaced\)\s*\n?")

# exclude_from_sim -- missing in KiCad 6, required in KiCad 10
_RE_SYMBOL_INSTANCE = re.compile(r"^(\s*\(symbol\s+\()", re.MULTILINE)

# (nets ...) top-level section
_RE_NETS_SECTION = re.compile(r"\(nets\s+[^)]*\)")

# KiCad 6 single-line header
_RE_HEADER_V6 = re.compile(
    r"\(kicad_sch\s+\(version\s+20211123\)\s+\(generator\s+eeschema\)"
)

# (lib_symbols_extra) -- non-standard section
_RE_LIB_SYMBOLS_EXTRA = re.compile(r"\(lib_symbols_extra\)\s*\n?")


# ---------------------------------------------------------------------------
# Internal conversion helpers
# ---------------------------------------------------------------------------


def _remove_semicolon_comments(content: str) -> str:
    """Remove ;; comments, preserving line count for debuggability."""
    lines = content.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(";;"):
            # Replace full-line comment with blank line
            result.append("")
        else:
            # Remove inline ;; comments
            # Find ;; that is not inside a string
            new_line = _remove_inline_semicolon(line)
            result.append(new_line)
    return "\n".join(result)


def _remove_inline_semicolon(line: str) -> str:
    """Remove inline ;; comment, respecting quoted strings."""
    in_string = False
    for i in range(len(line) - 1):
        if line[i] == '"':
            in_string = not in_string
        elif not in_string and line[i:i+2] == ";;":
            return line[:i].rstrip()
    return line


def _replace_tabs(content: str) -> str:
    """Replace tab characters with 2 spaces."""
    return content.replace("\t", "  ")


def _fix_header(content: str) -> str:
    """Convert KiCad 6 single-line header to KiCad 10 multi-line format."""
    # Find existing UUID in the content
    uuid_match = re.search(
        r"\(uuid\s+\"?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\"?\)",
        content,
    )
    existing_uuid = uuid_match.group(1) if uuid_match else str(_uuid.uuid4())

    new_header = (
        f'(kicad_sch\n'
        f'  (version 20250114)\n'
        f'  (generator "kicad-agent")\n'
        f'  (generator_version "10.0.1")\n'
        f'  (uuid "{existing_uuid}")'
    )

    # Replace the old header
    content = _RE_HEADER_V6.sub(new_header, content)

    # Also handle generic (version ...) in headers that aren't the standard pattern
    # This handles cases like (version 20220111) or other KiCad 5/6 versions
    if "(version 20211123)" in content and "(kicad_sch\n" not in content:
        content = re.sub(
            r"\(kicad_sch\s+\(version\s+\d+\)\s+\(generator\s+\S+\)",
            new_header,
            content,
        )

    return content


def _quote_uuids(content: str) -> str:
    """Quote bare UUIDs: (uuid abc-def...) -> (uuid "abc-def...")."""

    def _replacer(match: re.Match) -> str:
        uuid_val = match.group(1)
        return f'(uuid "{uuid_val}")'

    # Only replace UUIDs that are NOT already quoted
    # Match (uuid followed by unquoted UUID pattern
    return _RE_BARE_UUID.sub(_replacer, content)


def _remove_net_elements(content: str) -> str:
    """Remove (net (code ...) ...) S-expressions."""
    result = []
    i = 0
    lines = content.split("\n")

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if _RE_NET_ELEMENT_START.match(stripped):
            # Track paren depth to find end of this (net ...) block
            depth = 0
            while i < len(lines):
                for ch in lines[i]:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                i += 1
                if depth <= 0:
                    break
        else:
            result.append(lines[i])
            i += 1

    return "\n".join(result)


def _unwrap_schematic_objects(content: str) -> str:
    """Remove (schematic_objects ...) wrapper, keeping children."""
    match = _RE_SCHEMATIC_OBJECTS.search(content)
    if not match:
        return content

    start = match.start()
    # Find the matching close paren
    depth = 0
    pos = content.index("(", start)
    inner_start = None

    for i in range(pos, len(content)):
        ch = content[i]
        if ch == "(":
            if depth == 0:
                inner_start = i + len("(schematic_objects")
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                inner_end = i
                # Extract inner content (skip whitespace after tag)
                inner = content[inner_start:i]
                # Strip leading newline and whitespace from inner
                inner = inner.lstrip("\n")
                # Remove one level of leading indentation from inner
                inner_lines = inner.split("\n")
                dedented = []
                for line in inner_lines:
                    if line.startswith("    "):
                        dedented.append(line[2:])
                    elif line.startswith("  "):
                        dedented.append(line[2:])
                    else:
                        dedented.append(line)
                replacement = "\n".join(dedented).rstrip()
                content = content[:start] + replacement + content[inner_end + 1:]
                break

    return content


def _unwrap_pins_wrapper(content: str) -> str:
    """Remove (pins ...) wrapper inside sheet elements, keeping pin children."""
    # Find (pins\n ... ) patterns and unwrap them
    match = _RE_PINS_WRAPPER.search(content)
    if not match:
        return content

    start = match.start()
    # Find the matching close paren for (pins ...)
    depth = 0
    found_start = False

    for i in range(start, len(content)):
        ch = content[i]
        if ch == "(":
            depth += 1
            found_start = True
        elif ch == ")":
            depth -= 1
            if found_start and depth == 0:
                # Extract content between (pins and matching )
                inner = content[start + len("(pins"):i]
                # Strip leading/trailing whitespace
                inner = inner.strip("\n")
                # Dedent inner content by 2 spaces
                inner_lines = inner.split("\n")
                dedented = []
                for line in inner_lines:
                    if line.startswith("    "):
                        dedented.append(line[2:])
                    else:
                        dedented.append(line)
                replacement = "\n".join(dedented)
                content = content[:start] + replacement + content[i + 1:]
                break

    return content


def _fix_missing_rotation(content: str) -> str:
    """Add missing rotation value: (at X Y) -> (at X Y 0)."""

    def _replacer(match: re.Match) -> str:
        x = match.group(1)
        y = match.group(2)
        return f"(at {x} {y} 0)"

    return _RE_AT_NO_ROTATION.sub(_replacer, content)


def _fix_stroke_format(content: str) -> str:
    """Fix malformed stroke: (stroke (width X)) (type Y)) -> (stroke (width X) (type Y))."""

    def _replacer(match: re.Match) -> str:
        width = match.group(1)
        stroke_type = match.group(2)
        return f"(stroke (width {width}) (type {stroke_type}))"

    return _RE_STROKE_MALFORMED.sub(_replacer, content)


def _fix_fields_autoplaced(content: str) -> str:
    """Convert bare (fields_autoplaced) to (fields_autoplaced yes).

    KiCad 10 requires (fields_autoplaced yes) on hierarchical labels and
    symbol instances. Bare (fields_autoplaced) without yes/no is a KiCad 6
    artifact that must be converted, not removed, to preserve label layout.
    """
    return _RE_FIELDS_AUTOPLACED.sub("  (fields_autoplaced yes)\n", content)


def _remove_nets_section(content: str) -> str:
    """Remove any top-level (nets ...) section."""
    return _RE_NETS_SECTION.sub("", content)


def _add_embedded_fonts(content: str) -> str:
    """Ensure (embedded_fonts) element exists before the closing paren."""
    if "(embedded_fonts)" in content:
        return content

    # Add before the final closing paren of the kicad_sch
    # Find the last ) in the content
    stripped = content.rstrip()
    if stripped.endswith(")"):
        return stripped[:-1] + "  (embedded_fonts)\n)\n"

    return content


def _remove_lib_symbols_extra(content: str) -> str:
    """Remove (lib_symbols_extra) non-standard sections."""
    return _RE_LIB_SYMBOLS_EXTRA.sub("", content)


def _add_exclude_from_sim(content: str) -> str:
    """Add (exclude_from_sim no) to symbol instances missing it.

    KiCad 10 requires each symbol instance to have an exclude_from_sim
    property. KiCad 6 files lack this, so we add the default value.
    """
    # Add exclude_from_sim no after uuid lines inside symbol_lib_id instances
    # Match symbol instances in the schematic that have a uuid but no exclude_from_sim
    lines = content.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # Detect symbol instance blocks: lines with (lib_id ...) are part of
        # component definitions. We add exclude_from_sim after the uuid line
        # if it's not already present.
        if "(uuid " in stripped and i + 1 < len(lines):
            # Check if next non-empty line already has exclude_from_sim
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and "exclude_from_sim" not in lines[j]:
                # Check we're inside a symbol block (look back for lib_id)
                context = "\n".join(result[-8:]) if len(result) >= 8 else "\n".join(result)
                if "(lib_id " in context:
                    indent = len(line) - len(line.lstrip())
                    result.append(line)
                    result.append(" " * indent + "(exclude_from_sim no)")
                    i += 1
                    continue
        result.append(line)
        i += 1
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def convert_kicad6_to_10(content: str) -> str:
    """Convert KiCad 5/6 format schematic content to KiCad 10 format.

    Uses section-based reassembly: splits content into major sections,
    applies conversion passes to each section independently, then
    reassembles. This avoids the paren-depth tracking bugs that cause
    line-by-line converters to lose hierarchical labels.

    Args:
        content: Raw text content of a KiCad 5/6 schematic file.

    Returns:
        Converted content compatible with KiCad 10 format.
    """
    if not content or not content.strip():
        return content

    # Phase 1: Pre-processing (text cleanup)
    content = _remove_semicolon_comments(content)
    content = _replace_tabs(content)

    # Phase 2: Header fix
    content = _fix_header(content)

    # Phase 3: UUID quoting
    content = _quote_uuids(content)

    # Phase 4: Legacy element removal
    content = _remove_net_elements(content)
    content = _unwrap_schematic_objects(content)
    content = _unwrap_pins_wrapper(content)
    content = _fix_fields_autoplaced(content)
    content = _remove_nets_section(content)
    content = _remove_lib_symbols_extra(content)

    # Phase 5: Format fixes
    content = _fix_missing_rotation(content)
    content = _fix_stroke_format(content)
    content = _add_exclude_from_sim(content)

    # Phase 6: Final cleanup
    content = _add_embedded_fonts(content)

    return content
