"""Symbol library (.kicad_sym) file serializer.

Serializes parsed KiCad symbol library files back to disk via kiutils.
Symbol libraries do NOT need UUID re-injection.

Usage:
    from kicad_agent.serializer.symbol_ser import serialize_symbol_lib

    output_path = serialize_symbol_lib(parse_result, Path("output.kicad_sym"))
"""

from pathlib import Path

from kicad_agent.parser.symbol_parser import ParseResult


def serialize_symbol_lib(parse_result: ParseResult, output_path: Path) -> Path:
    """Serialize a parsed symbol library back to a .kicad_sym file.

    Uses kiutils' to_file() for serialization. No UUID re-injection needed
    for symbol libraries.

    Args:
        parse_result: ParseResult from parse_symbol_lib().
        output_path: Target file path for the serialized symbol library.

    Returns:
        The output path (same as input output_path).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parse_result.kiutils_obj.to_file(str(output_path))
    return output_path
