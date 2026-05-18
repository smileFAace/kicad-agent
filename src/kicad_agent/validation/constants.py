"""Shared constants for KiCad file type mapping.

Centralizes the suffix-to-file-type mapping used by roundtrip validation
and regression testing to avoid duplication across modules.
"""

# Map file suffix to (file_type, needs_uuid)
SUFFIX_MAP: dict[str, tuple[str, bool]] = {
    ".kicad_sch": ("schematic", False),
    ".kicad_pcb": ("pcb", True),
    ".kicad_sym": ("symbol_lib", False),
    ".kicad_mod": ("footprint", True),
}

# Map file suffix to display name (for regression reporting)
FILE_TYPE_NAMES: dict[str, str] = {
    ".kicad_sch": "schematic",
    ".kicad_pcb": "pcb",
    ".kicad_sym": "symbol_lib",
    ".kicad_mod": "footprint",
}
