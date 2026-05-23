"""Project-level KiCad file parsers and editors.

Provides parsers for sym-lib-table, fp-lib-table, .kicad_dru, and .kicad_pro
files, with structured data models for programmatic editing.
"""

from kicad_agent.project.lib_table import (
    LibEntry,
    LibTable,
    parse_lib_table,
    serialize_lib_table,
)

__all__ = [
    "LibEntry",
    "LibTable",
    "parse_lib_table",
    "serialize_lib_table",
]
