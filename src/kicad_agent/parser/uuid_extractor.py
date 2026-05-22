"""UUID extraction from raw KiCad S-expression content.

kiutils 1.4.8 drops all UUID tokens from PCB and footprint files (board.py
and footprint.py have zero 'uuid' references). This module extracts UUIDs
from the raw file content before kiutils parsing, producing a structured
UUIDMap that can be used for re-injection after serialization.

Usage:
    from kicad_agent.parser.uuid_extractor import extract_uuids, UUIDMap

    raw = path.read_text()
    uuid_map = extract_uuids(raw, file_type="pcb")
    # uuid_map.entries -> tuple of UUIDEntry with structural context
"""

import re
from dataclasses import dataclass
from pathlib import Path


# UUID v4 format: 8-4-4-4-12 hex digits separated by hyphens
# KiCad PCBs/footprints use quoted UUIDs: (uuid "...")
# KiCad schematics use unquoted UUIDs: (uuid ...)
_UUID_PATTERN = re.compile(
    r'\(uuid\s+"?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"?\)',
    re.IGNORECASE,
)

# Valid file types for extraction
_VALID_FILE_TYPES = frozenset({"pcb", "footprint", "schematic", "symbol_lib"})

# Parent type patterns -- match enclosing S-expression types that can contain UUIDs
# Each pattern finds the opening token of the enclosing S-expression
_PARENT_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("footprint", re.compile(r'\(footprint\b', re.IGNORECASE)),
    ("pad", re.compile(r'\(pad\b', re.IGNORECASE)),
    ("gr_line", re.compile(r'\(gr_line\b', re.IGNORECASE)),
    ("gr_arc", re.compile(r'\(gr_arc\b', re.IGNORECASE)),
    ("gr_circle", re.compile(r'\(gr_circle\b', re.IGNORECASE)),
    ("gr_poly", re.compile(r'\(gr_poly\b', re.IGNORECASE)),
    ("gr_rect", re.compile(r'\(gr_rect\b', re.IGNORECASE)),
    ("graphical", re.compile(r'\(gr_(?!line\b|arc\b|circle\b|poly\b|rect\b)\w+', re.IGNORECASE)),
    ("zone", re.compile(r'\(zone\b', re.IGNORECASE)),
    ("via", re.compile(r'\(via\b', re.IGNORECASE)),
    ("segment", re.compile(r'\(segment\b', re.IGNORECASE)),
    ("arc", re.compile(r'\(arc\b', re.IGNORECASE)),
    ("dimension", re.compile(r'\(dimension\b', re.IGNORECASE)),
    ("group", re.compile(r'\(group\b', re.IGNORECASE)),
    ("schematic", re.compile(r'\(kicad_sch\b', re.IGNORECASE)),
    ("symbol", re.compile(r'\(symbol\b', re.IGNORECASE)),
    ("symbol_instance", re.compile(r'\(symbol_instance\b', re.IGNORECASE)),
    ("label", re.compile(r'\(label\b', re.IGNORECASE)),
    ("global_label", re.compile(r'\(global_label\b', re.IGNORECASE)),
    ("hierarchical_label", re.compile(r'\(hierarchical_label\b', re.IGNORECASE)),
    ("no_connect", re.compile(r'\(no_connect\b', re.IGNORECASE)),
    ("wire", re.compile(r'\(wire\b', re.IGNORECASE)),
    ("bus", re.compile(r'\(bus\b', re.IGNORECASE)),
    ("junction", re.compile(r'\(junction\b', re.IGNORECASE)),
    ("text", re.compile(r'\(text\b', re.IGNORECASE)),
    ("sheet", re.compile(r'\(sheet\b', re.IGNORECASE)),
    ("sheet_instance", re.compile(r'\(sheet_instance\b', re.IGNORECASE)),
    ("lib_symbols", re.compile(r'\(lib_symbols\b', re.IGNORECASE)),
]


@dataclass(frozen=True)
class UUIDEntry:
    """A single extracted UUID with its structural context.

    Attributes:
        uuid_value: The UUID string (e.g., '12345678-1234-1234-1234-123456789abc').
        parent_type: The type of the enclosing S-expression (e.g., 'footprint', 'pad').
        parent_index: Sequential index of the parent_type in the file (0-based).
        line_number: Line number in the original file where the UUID appears.
    """

    uuid_value: str
    parent_type: str
    parent_index: int
    line_number: int


@dataclass(frozen=True)
class UUIDMap:
    """Map of all UUIDs extracted from a KiCad file, keyed by structural position.

    Attributes:
        entries: Ordered tuple of UUIDEntry objects, in order of appearance in file.
        source_file_type: The file type ('pcb', 'footprint', 'schematic', 'symbol_lib').
    """

    entries: tuple[UUIDEntry, ...] = ()
    source_file_type: str = ""


def _determine_parent_type(
    content: str, match_start: int
) -> tuple[str, int]:
    """Determine the parent S-expression type for a UUID match.

    Scans backwards from the UUID match to find the enclosing S-expression.
    Returns (parent_type, parent_start_position).

    Args:
        content: The full file content.
        match_start: Start position of the (uuid ...) match.

    Returns:
        Tuple of (parent_type_str, start_position_of_parent).
    """
    # Search backwards for the nearest opening paren that starts an S-expression
    # We look for known parent types, checking from closest to furthest
    best_type = "unknown"
    best_pos = 0

    # Get the text before the UUID match (limit search range)
    search_start = max(0, match_start - 2000)
    prefix = content[search_start:match_start]

    for type_name, pattern in _PARENT_TYPE_PATTERNS:
        # Find all occurrences of this parent type in the prefix
        for parent_match in pattern.finditer(prefix):
            pos = search_start + parent_match.start()
            if pos > best_pos:
                best_pos = pos
                best_type = type_name

    return best_type, best_pos


_MAX_PARENT_COUNT_ENTRIES = 100_000  # Safety cap to prevent memory exhaustion


def _build_parent_count_map(content: str) -> dict[str, int]:
    """Pre-compute running counts of each parent type in a single pass.

    Returns a dict mapping "parent_type:position" to the count at that position.
    This avoids O(n) per-UUID lookups in _count_parent_index.

    Args:
        content: The full file content.

    Returns:
        Dict mapping (parent_type, position) to the sequential count.

    Raises:
        ValueError: If the number of parent entries exceeds the safety cap.
    """
    counts: dict[str, int] = {}
    running: dict[str, int] = {}

    for type_name, pattern in _PARENT_TYPE_PATTERNS:
        for match in pattern.finditer(content):
            running[type_name] = running.get(type_name, 0) + 1
            counts[(type_name, match.start())] = running[type_name] - 1
            if len(counts) > _MAX_PARENT_COUNT_ENTRIES:
                raise ValueError(
                    f"Parent count map exceeded {_MAX_PARENT_COUNT_ENTRIES} entries. "
                    "File may be malformed or maliciously large."
                )

    return counts


def _count_parent_index(
    parent_counts: dict[str, int], parent_type: str, parent_pos: int
) -> int:
    """Look up the pre-computed sequential index for a parent type.

    Args:
        parent_counts: Pre-computed count map from _build_parent_count_map.
        parent_type: The type string to look up.
        parent_pos: Position of the current parent.

    Returns:
        0-based index of this parent occurrence.
    """
    return parent_counts.get((parent_type, parent_pos), 0)


def extract_uuids(content: str, file_type: str) -> UUIDMap:
    """Extract all UUID tokens from raw KiCad S-expression content.

    Uses regex to find all (uuid "...") tokens. For each UUID, determines
    the enclosing parent S-expression type (footprint, pad, zone, etc.)
    and the sequential index of that parent type.

    Args:
        content: Raw S-expression file content.
        file_type: One of 'pcb', 'footprint', 'schematic', 'symbol_lib'.

    Returns:
        UUIDMap with all entries in order of appearance.

    Raises:
        ValueError: If file_type is not a recognized type.
    """
    if file_type not in _VALID_FILE_TYPES:
        raise ValueError(
            f"Invalid file_type: {file_type!r}. "
            f"Must be one of {sorted(_VALID_FILE_TYPES)}."
        )

    entries: list[UUIDEntry] = []

    # Pre-compute parent index counts in a single pass
    parent_counts = _build_parent_count_map(content)

    # Track line number incrementally since UUID matches appear in file order
    last_newline_pos = 0
    current_line = 1

    def _line_number(pos: int) -> int:
        """Compute line number by scanning forward from last scanned position."""
        nonlocal last_newline_pos, current_line
        # Scan from where we left off up to the target position
        scan_start = last_newline_pos
        while scan_start < pos:
            idx = content.find("\n", scan_start, pos)
            if idx == -1:
                break
            current_line += 1
            scan_start = idx + 1
        last_newline_pos = scan_start
        return current_line

    for match in _UUID_PATTERN.finditer(content):
        uuid_value = match.group(1)
        line_num = _line_number(match.start())
        parent_type, parent_pos = _determine_parent_type(content, match.start())
        parent_index = _count_parent_index(parent_counts, parent_type, parent_pos)

        entries.append(
            UUIDEntry(
                uuid_value=uuid_value,
                parent_type=parent_type,
                parent_index=parent_index,
                line_number=line_num,
            )
        )

    return UUIDMap(entries=tuple(entries), source_file_type=file_type)


def extract_uuids_from_file(path: Path, file_type: str) -> UUIDMap:
    """Read a KiCad file and extract all UUID tokens.

    Args:
        path: Path to a KiCad file (.kicad_pcb, .kicad_mod, etc.).
        file_type: One of 'pcb', 'footprint', 'schematic', 'symbol_lib'.

    Returns:
        UUIDMap with all entries in order of appearance.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file exceeds the 50MB size limit or file_type is invalid.
    """
    if file_type not in _VALID_FILE_TYPES:
        raise ValueError(
            f"Invalid file_type: {file_type!r}. "
            f"Must be one of {sorted(_VALID_FILE_TYPES)}."
        )

    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {path}")

    file_size = resolved.stat().st_size
    max_size = 50 * 1024 * 1024  # 50MB limit (DoS mitigation)
    if file_size > max_size:
        raise ValueError(
            f"File exceeds 50MB size limit ({file_size} bytes): {path}. "
            "File may be malformed or maliciously large."
        )

    content = resolved.read_text(encoding="utf-8")
    return extract_uuids(content, file_type)
