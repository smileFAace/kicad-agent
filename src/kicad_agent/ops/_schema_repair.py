"""Repair operation schemas -- repair, convert, snap, power flag, rebuild root sheet, swap symbol."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import (
    TargetFile,
    _validate_safe_identifier,
)


class RepairSchematicOp(BaseModel):
    """Auto-repair common ERC errors in a schematic.

    Runs wire snapping, orphaned label removal, and no-connect placement
    based on the enabled flags.

    Attributes:
        op_type: Discriminator literal ``"repair_schematic"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        snap_wires: Snap wire endpoints to nearest pin positions (default True).
        remove_orphans: Remove labels not connected to any wire or pin (default True).
        place_no_connects: Place no-connect markers on unconnected pins (default True).
        snap_to_grid: Snap off-grid wire endpoints to nearest grid point (default False).
    """

    op_type: Literal["repair_schematic"] = "repair_schematic"
    target_file: TargetFile
    snap_wires: bool = Field(default=True, description="Snap wire endpoints to pins")
    remove_orphans: bool = Field(default=True, description="Remove orphaned labels")
    place_no_connects: bool = Field(default=True, description="Place no-connect markers")
    snap_to_grid: bool = Field(default=False, description="Snap off-grid wire endpoints to grid")


class ConvertKicad6To10Op(BaseModel):
    """Convert a KiCad 5/6 format schematic to KiCad 10 format.

    SCHREPAIR-04: Multi-pass format conversion using section-based reassembly.

    Attributes:
        op_type: Discriminator literal ``"convert_kicad6_to_10"``.
        target_file: Relative path to the KiCad 5/6 schematic file (H-01 validated).
    """

    op_type: Literal["convert_kicad6_to_10"] = "convert_kicad6_to_10"
    target_file: TargetFile


class SnapToGridOp(BaseModel):
    """Snap off-grid wire endpoints to the nearest grid point.

    SCHREPAIR-05: Grid-snapping with connectivity preservation.

    Attributes:
        op_type: Discriminator literal ``"snap_to_grid"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        grid_mm: Grid spacing in mm. Default 0.01mm for KiCad 8+.
    """

    op_type: Literal["snap_to_grid"] = "snap_to_grid"
    target_file: TargetFile
    grid_mm: float = Field(
        default=0.01, gt=0, le=100,
        description="Grid spacing in mm. Default 0.01mm for KiCad 8+.",
    )


class AddPowerFlagOp(BaseModel):
    """Place PWR_FLAG symbols at power_pin_not_driven ERC violation positions.

    SCHREPAIR-06: ERC-driven power flag placement.

    Attributes:
        op_type: Discriminator literal ``"add_power_flag"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
    """

    op_type: Literal["add_power_flag"] = "add_power_flag"
    target_file: TargetFile


class RebuildRootSheetOp(BaseModel):
    """Rebuild root schematic sheet pins from sub-sheet hierarchical labels.

    SCHREPAIR-08: Reads all sub-sheets, extracts hierarchical labels,
    and regenerates sheet pins with correct positioning.

    Attributes:
        op_type: Discriminator literal ``"rebuild_root_sheet"``.
        target_file: Relative path to the root KiCad schematic file (H-01 validated).
    """

    op_type: Literal["rebuild_root_sheet"] = "rebuild_root_sheet"
    target_file: TargetFile


class SwapSymbolOp(BaseModel):
    """Swap a component's symbol (lib_id) in-place, preserving position and properties.

    Replaces the component's lib_id reference with a new one. Optionally embeds
    the new symbol definition from the library into the schematic's lib_symbols
    section if it's not already present.

    The component's Reference, Value, position, and other properties are preserved.
    Wire connections are not affected (they reference UUIDs, not symbol types).

    Attributes:
        op_type: Discriminator literal ``"swap_symbol"``.
        target_file: Relative path to the .kicad_sch file.
        reference: Reference designator of the component to swap (e.g. ``"U1"``).
        new_lib_id: New library:symbol ID (e.g. ``"Analog-Ecosystem-SMD:RP2350B"``).
        library_path: Optional path to .kicad_sym for auto-embedding. If provided,
            the symbol definition will be embedded into lib_symbols if missing.
        preserve_position: Keep the component's current (at X Y) coordinates.
        preserve_properties: Keep the component's current properties (Value, Footprint, etc.).
    """

    op_type: Literal["swap_symbol"] = "swap_symbol"
    target_file: TargetFile
    reference: str = Field(min_length=1, max_length=64)
    new_lib_id: str = Field(
        min_length=1, max_length=256,
        description="New library:symbol ID (e.g. 'Library:SymbolName')",
    )
    library_path: Optional[str] = Field(
        default=None, max_length=512,
        description="Optional path to .kicad_sym for auto-embedding",
    )
    preserve_position: bool = Field(
        default=True,
        description="Keep the component's current position",
    )
    preserve_properties: bool = Field(
        default=True,
        description="Keep the component's current properties",
    )

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")

    @field_validator("new_lib_id")
    @classmethod
    def _validate_new_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "new_lib_id")
