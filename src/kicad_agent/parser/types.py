"""Shared type definitions for KiCad file parsers.

Centralizes the ParseResult dataclass used by all four typed parsers
(schematic, PCB, symbol library, footprint) to eliminate duplication.
"""

from pathlib import Path
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParseResult:
    """Generic container for parsed KiCad file content.

    Attributes:
        kiutils_obj: The typed kiutils object (Schematic, Board, SymbolLib, Footprint).
        raw_content: Original file text preserved for UUID extraction and fallback processing.
        file_path: Source file path.
        file_type: One of: 'schematic', 'pcb', 'symbol_lib', 'footprint'.
    """

    kiutils_obj: Any
    raw_content: str
    file_path: Path
    file_type: str
