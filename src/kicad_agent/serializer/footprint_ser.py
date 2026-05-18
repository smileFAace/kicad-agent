"""Footprint (.kicad_mod) file serializer with UUID re-injection.

Serializes parsed KiCad footprint files back to disk via kiutils, then
re-injects UUIDs that kiutils drops during serialization.

Usage:
    from kicad_agent.serializer.footprint_ser import serialize_footprint

    output_path = serialize_footprint(parse_result, Path("output.kicad_mod"), uuid_map=uuid_map)
"""

from pathlib import Path
from typing import Optional

from kicad_agent.parser.footprint_parser import ParseResult
from kicad_agent.parser.uuid_extractor import UUIDMap
from kicad_agent.serializer.uuid_reinjector import reinject_uuids


def serialize_footprint(
    parse_result: ParseResult,
    output_path: Path,
    uuid_map: Optional[UUIDMap] = None,
) -> Path:
    """Serialize a parsed footprint back to a .kicad_mod file.

    Uses kiutils' to_file() for serialization. If a UUIDMap is provided,
    reads the serialized output and re-injects UUIDs that kiutils dropped.

    Args:
        parse_result: ParseResult from parse_footprint().
        output_path: Target file path for the serialized footprint.
        uuid_map: Optional UUIDMap for re-injecting dropped UUIDs.

    Returns:
        The output path (same as input output_path).
    """
    if parse_result.file_type != "footprint":
        raise ValueError(
            f"Expected file_type='footprint', got file_type={parse_result.file_type!r}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    parse_result.kiutils_obj.to_file(str(output_path))

    if uuid_map is not None and uuid_map.entries:
        serialized = output_path.read_text(encoding="utf-8")
        restored = reinject_uuids(serialized, uuid_map)
        output_path.write_text(restored, encoding="utf-8")

    return output_path
