"""Symbol library (.kicad_sym) file parser.

Parses KiCad symbol library files into kiutils SymbolLib objects with raw
content preservation. Note: kiutils silently drops exclude_from_sim tokens
from symbol definitions (semantically acceptable since default is 'no').

Usage:
    from kicad_agent.parser.symbol_parser import parse_symbol_lib

    result = parse_symbol_lib(Path("Device.kicad_sym"))
    symbols = result.kiutils_obj.symbols
    raw_text = result.raw_content
"""

from pathlib import Path

from kiutils.symbol import SymbolLib

from kicad_agent.parser.types import ParseResult


def parse_symbol_lib(path: Path) -> ParseResult:
    """Parse a .kicad_sym file into a kiutils SymbolLib object.

    Reads the file text for raw content preservation, then parses via
    kiutils for typed dataclass access. Each symbol in the library has
    pins, properties, graphic items, and unit definitions.

    Args:
        path: Path to a .kicad_sym file.

    Returns:
        ParseResult with kiutils_obj as SymbolLib, raw_content as file text,
        file_type as 'symbol_lib'.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If file extension is not .kicad_sym.
    """
    if not path.exists():
        raise FileNotFoundError(f"Symbol library file not found: {path}")

    if path.suffix != ".kicad_sym":
        raise ValueError(f"Expected .kicad_sym file, got {path.suffix}")

    raw_content = path.read_text(encoding="utf-8")
    symbol_lib = SymbolLib.from_file(str(path))

    return ParseResult(
        kiutils_obj=symbol_lib,
        raw_content=raw_content,
        file_path=path,
        file_type="symbol_lib",
    )
