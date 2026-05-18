"""Footprint (.kicad_mod) file parser.

Parses KiCad footprint files into kiutils Footprint objects with raw content
preservation. CRITICAL: kiutils drops all UUID tokens from footprint files
(only handles legacy tstamp). Raw content MUST be preserved for UUID extraction.

Usage:
    from kicad_agent.parser.footprint_parser import parse_footprint

    result = parse_footprint(Path("MountingHole_3.2mm.kicad_mod"))
    pads = result.kiutils_obj.pads
    raw_text = result.raw_content  # Essential for UUID extraction
"""

from pathlib import Path

from kiutils.footprint import Footprint

from kicad_agent.parser.types import ParseResult


def parse_footprint(path: Path) -> ParseResult:
    """Parse a .kicad_mod file into a kiutils Footprint object.

    Reads the file text for raw content preservation BEFORE parsing.
    This is critical because kiutils 1.4.8 drops all UUID tokens from
    footprint files -- the raw content is the only source for UUID extraction.

    Args:
        path: Path to a .kicad_mod file.

    Returns:
        ParseResult with kiutils_obj as Footprint, raw_content as file text,
        file_type as 'footprint'.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If file extension is not .kicad_mod.
    """
    if not path.exists():
        raise FileNotFoundError(f"Footprint file not found: {path}")

    if path.suffix != ".kicad_mod":
        raise ValueError(f"Expected .kicad_mod file, got {path.suffix}")

    raw_content = path.read_text(encoding="utf-8")
    footprint = Footprint.from_file(str(path))

    return ParseResult(
        kiutils_obj=footprint,
        raw_content=raw_content,
        file_path=path,
        file_type="footprint",
    )
