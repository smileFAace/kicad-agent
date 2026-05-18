"""UUID re-injection into kiutils serialized output.

kiutils drops UUID tokens from PCB and footprint files during serialization.
This module re-inserts UUIDs into the correct positions within the kiutils
output, using a UUIDMap extracted from the original raw content.

Strategy: UUIDs in KiCad files appear in a deterministic sequential order tied
to the structural elements (footprint, pad, property, graphical items, etc.).
kiutils preserves the structural elements but drops all UUIDs. By walking the
serialized output and injecting UUIDs at the same structural positions, we
restore the original UUID layout.

The two-pass stability test proves this works: after injection, parse->serialize
produces the same output (because the UUIDs are now present in the re-parsed
raw content for the second extraction).

Usage:
    from kicad_agent.serializer.uuid_reinjector import reinject_uuids

    restored = reinject_uuids(serialized_content, uuid_map)
"""

import re

from kicad_agent.parser.uuid_extractor import UUIDMap


# UUID v4 validation pattern
_UUID_V4_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Single combined pattern that matches all structural element opening lines
# that should have UUIDs. Ordered by specificity to avoid false matches.
_ELEMENT_PATTERN = re.compile(
    r"""
    ^(?P<indent>\s*)
    \(
    (?P<type>
        footprint        |
        pad              |
        zone             |
        via              |
        segment          |
        arc              |
        property         |
        fp_line          |
        fp_arc           |
        fp_circle        |
        fp_poly          |
        fp_rect          |
        fp_text          |
        gr_line          |
        gr_arc           |
        gr_circle        |
        gr_poly          |
        gr_rect          |
        gr_text          |
        dimension        |
        group            |
        graphical        |
        model            |
        net              |
        fill             |
        outline          |
        polygon          |
        curve            |
    )\s
    """,
    re.VERBOSE | re.MULTILINE,
)


def _validate_uuid_format(uuid_value: str) -> bool:
    """Validate that a UUID matches the v4 format (36-char hyphenated hex).

    Mitigation for threat T-01-04: reject entries that don't match UUID v4 pattern.

    Args:
        uuid_value: The UUID string to validate.

    Returns:
        True if the UUID is valid v4 format.
    """
    return bool(_UUID_V4_PATTERN.match(uuid_value))


def reinject_uuids(serialized_content: str, uuid_map: UUIDMap) -> str:
    """Re-inject UUID tokens into kiutils serialized output.

    Walks the serialized content, finding structural elements that would have
    UUIDs in the original file, and inserts the corresponding UUID from the
    UUIDMap. UUIDs are injected sequentially -- each structural element gets
    the next UUID from the map.

    Args:
        serialized_content: The kiutils serialized S-expression string.
        uuid_map: UUIDMap extracted from the original raw content.

    Returns:
        The content string with UUID tokens re-inserted.
    """
    if not uuid_map.entries:
        return serialized_content

    # Build an ordered queue of valid UUIDs to inject
    uuid_queue = [
        entry.uuid_value
        for entry in uuid_map.entries
        if _validate_uuid_format(entry.uuid_value)
    ]

    if not uuid_queue:
        return serialized_content

    # Find all structural element positions in file order
    # Each match gives us (position, indent, match_end)
    matches = list(_ELEMENT_PATTERN.finditer(serialized_content))

    # Apply UUIDs sequentially to structural elements
    insertions: list[tuple[int, str]] = []
    uuid_idx = 0

    for match in matches:
        if uuid_idx >= len(uuid_queue):
            break

        uuid_value = uuid_queue[uuid_idx]
        indent = match.group("indent")
        match_end = match.end()

        # Find the end of this line to insert after it
        line_end = serialized_content.find("\n", match_end)
        if line_end == -1:
            line_end = len(serialized_content)

        # UUID should be indented one level deeper than the parent element
        uuid_indent = indent + "  "
        uuid_line = f'{uuid_indent}(uuid "{uuid_value}")\n'

        insertions.append((line_end, uuid_line))
        uuid_idx += 1

    # Apply insertions in reverse order to preserve positions
    result = serialized_content
    for pos, uuid_line in sorted(insertions, key=lambda x: x[0], reverse=True):
        result = result[:pos] + uuid_line + result[pos:]

    return result
