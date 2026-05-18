"""Schematic (.kicad_sch) file serializer.

Serializes parsed KiCad schematic files back to disk via kiutils.
Schematics do NOT need UUID re-injection -- kiutils preserves schematic UUIDs.

Usage:
    from kicad_agent.serializer.schematic_ser import serialize_schematic

    output_path = serialize_schematic(parse_result, Path("output.kicad_sch"))
"""

from pathlib import Path

from kicad_agent.parser.schematic_parser import ParseResult


def serialize_schematic(parse_result: ParseResult, output_path: Path) -> Path:
    """Serialize a parsed schematic back to a .kicad_sch file.

    Uses kiutils' to_file() for serialization. Schematic UUIDs are preserved
    by kiutils, so no UUID re-injection is needed.

    Args:
        parse_result: ParseResult from parse_schematic().
        output_path: Target file path for the serialized schematic.

    Returns:
        The output path (same as input output_path).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parse_result.kiutils_obj.to_file(str(output_path))
    return output_path
