"""Structural diff generation for KiCad S-expression files.

Compares two KiCad files and produces syntax-aware differences grouped
by structural element (component, net, footprint, etc.). Falls back to
difftastic when installed for enhanced text diff, pure-Python when not.

Architecture:
  structural_diff(file_a, file_b) -> DiffResult
    1. Parse both files with parse_raw_sexp
    2. Extract elements by type using _extract_elements
    3. Compare element groups with _diff_element_groups
    4. Optionally call difftastic for text diff
    5. Return structured DiffResult with machine-readable entries
"""

import logging
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from kicad_agent.parser.raw_parser import parse_raw_sexp_file

logger = logging.getLogger(__name__)

# Reuse 50MB limit from parser (T-06-15: DoS mitigation)
_MAX_FILE_SIZE = 50 * 1024 * 1024

# difftastic subprocess timeout (T-06-14: prevent hanging)
_DIFFTASTIC_TIMEOUT = 10


class DiffType(str, Enum):
    """Type of structural difference detected."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    MOVED = "moved"


@dataclass(frozen=True)
class DiffEntry:
    """A single structural difference between two KiCad files.

    Attributes:
        diff_type: Whether the element was added, removed, modified, or moved.
        element_type: S-expression element type (symbol, wire, footprint, etc.).
        identifier: UUID or reference designator identifying this element.
        old_value: Serialized form in file_a (None for ADDED).
        new_value: Serialized form in file_b (None for REMOVED).
        path_in_file: Structural path like "/symbol/uuid-abc".
    """

    diff_type: DiffType
    element_type: str
    identifier: str
    old_value: Optional[str]
    new_value: Optional[str]
    path_in_file: str


@dataclass(frozen=True)
class DiffResult:
    """Complete structural diff result between two KiCad files.

    Attributes:
        entries: List of DiffEntry instances describing all differences.
        file_a_path: Resolved path to the original file.
        file_b_path: Resolved path to the modified file.
        difftastic_available: Whether difftastic was found on the system.
        difftastic_output: Raw difftastic text output, if available.
    """

    entries: list
    file_a_path: Path
    file_b_path: Path
    difftastic_available: bool
    difftastic_output: Optional[str]


def _sexp_to_string(sexp) -> str:
    """Serialize a parsed S-expression back to string form.

    Recursively walks the nested list structure from parse_raw_sexp
    and produces valid S-expression text.

    Args:
        sexp: An atom (str, int, float, Symbol) or a nested list.

    Returns:
        S-expression string representation.
    """
    # Handle sexpdata.Symbol objects
    if hasattr(sexp, "value"):
        return str(sexp.value())
    # Handle plain atoms
    if not isinstance(sexp, list):
        return str(sexp)
    # Handle nested lists
    parts = [_sexp_to_string(item) for item in sexp]
    return f"({' '.join(parts)})"


def _extract_identifier(element: list) -> str:
    """Extract an identifier from a parsed S-expression element.

    Priority:
      1. UUID from (uuid "...") child
      2. Reference from (property "Reference" "...") for symbols
      3. Index-based fallback

    Args:
        element: Parsed S-expression list (e.g., [Symbol('symbol'), ...]).

    Returns:
        String identifier for this element.
    """
    for i, child in enumerate(element):
        if isinstance(child, list) and len(child) >= 2:
            tag = child[0]
            tag_str = str(tag.value()) if hasattr(tag, "value") else str(tag)
            if tag_str == "uuid":
                val = child[1]
                return str(val.value()) if hasattr(val, "value") else str(val)

    # Fallback: reference designator for symbols
    for i, child in enumerate(element):
        if isinstance(child, list) and len(child) >= 3:
            tag = child[0]
            tag_str = str(tag.value()) if hasattr(tag, "value") else str(tag)
            if tag_str == "property":
                prop_name = child[1]
                prop_name_str = (
                    str(prop_name.value())
                    if hasattr(prop_name, "value")
                    else str(prop_name)
                )
                if prop_name_str == "Reference":
                    val = child[2]
                    return str(val.value()) if hasattr(val, "value") else str(val)

    # Final fallback: index-based
    tag = element[0] if element else "unknown"
    tag_str = str(tag.value()) if hasattr(tag, "value") else str(tag)
    return f"{tag_str}_0"


def _extract_elements(sexp: list) -> dict[str, dict[str, str]]:
    """Extract top-level elements from a parsed KiCad S-expression.

    Finds the top-level container (kicad_sch or kicad_pcb), iterates
    its children, and groups them by element type with identifiers.

    Args:
        sexp: Parsed S-expression from parse_raw_sexp.

    Returns:
        Dict mapping element_type -> {identifier: serialized_form}.
    """
    # The top-level container is the first element
    # sexpdata wraps the entire expression in a top-level list
    # e.g., [Symbol('kicad_sch'), [Symbol('version'), 20250114], ...]
    # We need to iterate children starting from index 1

    # Find top-level container children
    children = []
    if isinstance(sexp, list):
        # Check if this is the container itself (first item is kicad_sch/kicad_pcb)
        if len(sexp) > 0:
            first = sexp[0]
            first_str = str(first.value()) if hasattr(first, "value") else str(first)
            if first_str in ("kicad_sch", "kicad_pcb"):
                children = sexp[1:]
            else:
                # sexpdata may return the container as a single-element list
                # e.g., [[Symbol('kicad_sch'), ...]]
                for item in sexp:
                    if isinstance(item, list) and len(item) > 0:
                        inner_first = item[0]
                        inner_str = (
                            str(inner_first.value())
                            if hasattr(inner_first, "value")
                            else str(inner_first)
                        )
                        if inner_str in ("kicad_sch", "kicad_pcb"):
                            children = item[1:]
                            break

    # Group children by their element type
    groups: dict[str, dict[str, str]] = {}
    element_counters: dict[str, int] = {}

    for child in children:
        if not isinstance(child, list) or len(child) == 0:
            continue

        # Get element type from first atom
        first = child[0]
        element_type = str(first.value()) if hasattr(first, "value") else str(first)

        # Skip non-element tokens (version, generator, etc.)
        if element_type in (
            "version",
            "generator",
            "generator_version",
            "uuid",
            "paper",
            "title_block",
            "lib_symbols",
            "sheet_instances",
            "symbol_instances",
            "general",
            "setup",
            "nets",
            "net_class",
            "modules",
            "kicad_sch",
            "kicad_pcb",
        ):
            continue

        # Extract identifier
        identifier = _extract_identifier(child)

        # Handle duplicate identifiers by appending counter
        if identifier in element_counters:
            element_counters[identifier] += 1
            identifier = f"{identifier}_{element_counters[identifier]}"
        else:
            element_counters[identifier] = 0

        # Serialize element back to string
        serialized = _sexp_to_string(child)

        if element_type not in groups:
            groups[element_type] = {}
        groups[element_type][identifier] = serialized

    return groups


def _has_at_change(old_serialized: str, new_serialized: str) -> bool:
    """Check if the (at x y rotation) field changed between two serialized elements.

    This is a heuristic check -- it looks for (at ...) patterns in both
    strings and compares them. Returns True only if the at field differs
    while other meaningful content may be the same or the only change is position.
    """
    import re

    at_pattern = re.compile(r"\(at\s+[^)]+\)")

    old_ats = at_pattern.findall(old_serialized)
    new_ats = at_pattern.findall(new_serialized)

    if old_ats != new_ats and old_ats and new_ats:
        return True
    return False


def _diff_element_groups(
    groups_a: dict[str, dict[str, str]], groups_b: dict[str, dict[str, str]]
) -> list:
    """Compare two element group dicts and produce DiffEntry list.

    For each element type present in either group:
      - Identifiers only in A -> REMOVED
      - Identifiers only in B -> ADDED
      - Identifiers in both -> compare serialized forms -> MODIFIED or MOVED

    Args:
        groups_a: Elements from file A (element_type -> {identifier: serialized}).
        groups_b: Elements from file B (element_type -> {identifier: serialized}).

    Returns:
        Sorted list of DiffEntry instances.
    """
    entries: list[DiffEntry] = []
    all_types = set(groups_a.keys()) | set(groups_b.keys())

    for element_type in sorted(all_types):
        a_elements = groups_a.get(element_type, {})
        b_elements = groups_b.get(element_type, {})

        a_ids = set(a_elements.keys())
        b_ids = set(b_elements.keys())

        # REMOVED: in A but not in B
        for identifier in sorted(a_ids - b_ids):
            entries.append(
                DiffEntry(
                    diff_type=DiffType.REMOVED,
                    element_type=element_type,
                    identifier=identifier,
                    old_value=a_elements[identifier],
                    new_value=None,
                    path_in_file=f"/{element_type}/{identifier}",
                )
            )

        # ADDED: in B but not in A
        for identifier in sorted(b_ids - a_ids):
            entries.append(
                DiffEntry(
                    diff_type=DiffType.ADDED,
                    element_type=element_type,
                    identifier=identifier,
                    old_value=None,
                    new_value=b_elements[identifier],
                    path_in_file=f"/{element_type}/{identifier}",
                )
            )

        # MODIFIED or MOVED: in both, compare content
        for identifier in sorted(a_ids & b_ids):
            old_val = a_elements[identifier]
            new_val = b_elements[identifier]

            if old_val != new_val:
                # Check if it's just a position change
                if _has_at_change(old_val, new_val):
                    # Determine if it's purely a move or also modified
                    # Strip (at ...) fields and compare the rest
                    import re

                    at_pattern = re.compile(r"\(at\s+[^)]+\)\s*")
                    old_stripped = at_pattern.sub("", old_val)
                    new_stripped = at_pattern.sub("", new_val)

                    if old_stripped == new_stripped:
                        diff_type = DiffType.MOVED
                    else:
                        diff_type = DiffType.MODIFIED
                else:
                    diff_type = DiffType.MODIFIED

                entries.append(
                    DiffEntry(
                        diff_type=diff_type,
                        element_type=element_type,
                        identifier=identifier,
                        old_value=old_val,
                        new_value=new_val,
                        path_in_file=f"/{element_type}/{identifier}",
                    )
                )

    return entries


def _try_difftastic(file_a: Path, file_b: Path) -> tuple[bool, Optional[str]]:
    """Call difftastic subprocess for enhanced text diff.

    Uses explicit args list (no shell=True) and 10-second timeout
    for security (T-06-14: subprocess injection prevention).

    Args:
        file_a: Path to first file.
        file_b: Path to second file.

    Returns:
        Tuple of (available: bool, output: Optional[str]).
    """
    try:
        result = subprocess.run(
            ["difft", str(file_a), str(file_b)],
            capture_output=True,
            text=True,
            timeout=_DIFFTASTIC_TIMEOUT,
        )
        return (True, result.stdout)
    except FileNotFoundError:
        logger.debug("difftastic not found, using pure-Python diff only")
        return (False, None)
    except subprocess.TimeoutExpired:
        logger.warning("difftastic timed out after %d seconds", _DIFFTASTIC_TIMEOUT)
        return (False, None)


def structural_diff(file_a: Path, file_b: Path) -> DiffResult:
    """Compare two KiCad files and produce structural differences.

    Parses both files as S-expressions, extracts elements grouped by type,
    compares identifiers and content, and optionally calls difftastic
    for enhanced text diff.

    Security mitigations:
      - T-06-14: subprocess with explicit args, no shell=True, 10s timeout
      - T-06-15: 50MB file size limit inherited from parser
      - T-06-16: paths resolved before reading

    Args:
        file_a: Path to the first (original) KiCad file.
        file_b: Path to the second (modified) KiCad file.

    Returns:
        DiffResult with structured diff entries and difftastic status.

    Raises:
        FileNotFoundError: If either file does not exist.
        ValueError: If file content exceeds size limit.
    """
    resolved_a = file_a.resolve()
    resolved_b = file_b.resolve()

    # Parse both files (size limit enforced by parse_raw_sexp_file)
    sexp_a = parse_raw_sexp_file(resolved_a)
    sexp_b = parse_raw_sexp_file(resolved_b)

    # Extract elements by type
    groups_a = _extract_elements(sexp_a)
    groups_b = _extract_elements(sexp_b)

    # Compare and produce diff entries
    entries = _diff_element_groups(groups_a, groups_b)

    # Try difftastic for enhanced text diff
    difftastic_available, difftastic_output = _try_difftastic(resolved_a, resolved_b)

    return DiffResult(
        entries=entries,
        file_a_path=resolved_a,
        file_b_path=resolved_b,
        difftastic_available=difftastic_available,
        difftastic_output=difftastic_output,
    )
