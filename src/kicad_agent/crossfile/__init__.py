"""Cross-file operations for maintaining schematic-to-PCB consistency.

XFILE-01: Atomic operations that coordinate mutations across multiple
KiCad files (schematic + PCB pairs) in a single all-or-nothing transaction.

XFILE-02/XFILE-03: Library reference propagation -- when a symbol or
footprint library reference changes, propagate to all instances.

XFILE-04: Project context detection and auto-discovery -- detect KiCad
project root, find library paths, and discover all project files.

VAL-04: Structural diff generation -- syntax-aware comparison of KiCad
S-expression files with difftastic integration.
"""

from kicad_agent.crossfile.atomic import AtomicOperation, AtomicResult
from kicad_agent.crossfile.diff import (
    DiffEntry,
    DiffResult,
    DiffType,
    structural_diff,
)
from kicad_agent.crossfile.propagation import (
    PropagationResult,
    propagate_footprint_ref,
    propagate_symbol_ref,
)
from kicad_agent.crossfile.project_context import (
    ProjectContext,
    detect_project_root,
    discover_project,
)

__all__ = [
    "AtomicOperation",
    "AtomicResult",
    "DiffEntry",
    "DiffResult",
    "DiffType",
    "ProjectContext",
    "PropagationResult",
    "detect_project_root",
    "discover_project",
    "propagate_footprint_ref",
    "propagate_symbol_ref",
    "structural_diff",
]
