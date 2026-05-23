"""LTspice .asc schematic file parser using SpiceLib AscEditor.

Provides parse_asc() to convert .asc files into structured LTspiceSchematic
frozen dataclasses with components, wires, flags, and directives.
"""

from __future__ import annotations

from pathlib import Path


ASY_STUBS_DIR: Path = Path(__file__).parent / "asy_stubs"


def parse_asc(asc_path: str | Path) -> "LTspiceSchematic":
    """Parse an LTspice .asc file into a structured LTspiceSchematic.

    Args:
        asc_path: Path to the .asc file to parse.

    Returns:
        LTspiceSchematic with components, wires, flags, and directives.

    Raises:
        FileNotFoundError: If the .asc file does not exist.
        ValueError: If the path contains traversal sequences.
    """
    raise NotImplementedError("parse_asc not yet implemented")
