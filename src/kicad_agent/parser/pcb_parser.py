"""PCB (.kicad_pcb) file parser.

Parses KiCad PCB files into kiutils Board objects with raw content preservation.
CRITICAL: kiutils drops all UUID tokens from PCB files (only handles legacy tstamp).
Raw content MUST be preserved for UUID extraction via the raw_parser or regex.

Usage:
    from kicad_agent.parser.pcb_parser import parse_pcb

    result = parse_pcb(Path("my_board.kicad_pcb"))
    footprints = result.kiutils_obj.footprints
    raw_text = result.raw_content  # Essential for UUID extraction
"""

from pathlib import Path

from kiutils.board import Board

from kicad_agent.parser.types import ParseResult


def parse_pcb(path: Path) -> ParseResult:
    """Parse a .kicad_pcb file into a kiutils Board object.

    Reads the file text for raw content preservation BEFORE parsing.
    This is critical because kiutils 1.4.8 drops all UUID tokens from
    PCB files -- the raw content is the only source for UUID extraction.

    Args:
        path: Path to a .kicad_pcb file.

    Returns:
        ParseResult with kiutils_obj as Board, raw_content as file text,
        file_type as 'pcb'.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If file extension is not .kicad_pcb.
    """
    if not path.exists():
        raise FileNotFoundError(f"PCB file not found: {path}")

    if path.suffix != ".kicad_pcb":
        raise ValueError(f"Expected .kicad_pcb file, got {path.suffix}")

    raw_content = path.read_text(encoding="utf-8")
    board = Board.from_file(str(path))

    return ParseResult(
        kiutils_obj=board,
        raw_content=raw_content,
        file_path=path,
        file_type="pcb",
    )
