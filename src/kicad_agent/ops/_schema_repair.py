"""Repair operation schemas -- repair, convert, snap, power flag, rebuild root sheet, swap symbol,
update symbols from library, fix shorted nets, fix pin type mismatches, place missing units,
remove dangling wires, break wire shorts."""

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


class UpdateSymbolsFromLibraryOp(BaseModel):
    """Re-embed all mismatched symbols from their libraries.

    Equivalent to KiCad GUI's "Update Symbol from Library" for all symbols
    whose embedded lib_symbols definition diverges from the library version.

    Attributes:
        op_type: Discriminator literal ``"update_symbols_from_library"``.
        target_file: Relative path to the .kicad_sch file.
        references: Optional list of specific references to update. If None, updates all mismatches.
        dry_run: If True, report what would change without modifying the file.
    """

    op_type: Literal["update_symbols_from_library"] = "update_symbols_from_library"
    target_file: TargetFile
    references: Optional[list[str]] = Field(
        default=None,
        description="Specific references to update, or None for all mismatches",
    )
    dry_run: bool = Field(
        default=False,
        description="Report mismatches without modifying the file",
    )


class FixShortedNetsOp(BaseModel):
    """Fix positions where multiple net names connect to the same items.

    Detects short circuits where wires from different named nets overlap,
    then removes the "losing" label based on the chosen strategy.

    Attributes:
        op_type: Discriminator literal ``"fix_shorted_nets"``.
        target_file: Relative path to the .kicad_sch file.
        strategy: Which label to keep. "keep_first" keeps the first alphabetically,
            "keep_last" keeps the last, "manual" uses keep_nets list.
        keep_nets: For "manual" strategy, which net names to keep.
        dry_run: If True, report shorts without modifying the file.
    """

    op_type: Literal["fix_shorted_nets"] = "fix_shorted_nets"
    target_file: TargetFile
    strategy: Literal["keep_first", "keep_last", "manual"] = Field(
        default="keep_first",
        description="Which label to keep at short positions",
    )
    keep_nets: Optional[list[str]] = Field(
        default=None,
        description="For manual strategy, which net names to keep",
    )
    dry_run: bool = Field(
        default=False,
        description="Report shorts without modifying the file",
    )


class FixPinTypeMismatchesOp(BaseModel):
    """Fix pin electrical type mismatches in embedded lib_symbols.

    Updates pin electrical types in the embedded symbol definitions to resolve
    pin_to_pin ERC violations. Common fix: change "Unspecified" to "Passive"
    for analog switch pins connected to passive components.

    Attributes:
        op_type: Discriminator literal ``"fix_pin_type_mismatches"``.
        target_file: Relative path to the .kicad_sch file.
        pin_type_map: Override map from old type to new type. Defaults to {"unspecified": "passive"}.
        dry_run: If True, report what would change without modifying the file.
    """

    op_type: Literal["fix_pin_type_mismatches"] = "fix_pin_type_mismatches"
    target_file: TargetFile
    pin_type_map: Optional[dict[str, str]] = Field(
        default=None,
        description='Map from old type to new type, e.g. {"unspecified": "passive"}',
    )
    dry_run: bool = Field(
        default=False,
        description="Report mismatches without modifying the file",
    )


class PlaceMissingUnitsOp(BaseModel):
    """Place all unplaced units of multi-unit symbols.

    For multi-unit symbols like CD4066BE (quad bilateral switch), places all
    units that KiCad ERC reports as missing. Units are placed adjacent to the
    existing unit with configurable spacing.

    Attributes:
        op_type: Discriminator literal ``"place_missing_units"``.
        target_file: Relative path to the .kicad_sch file.
        references: Optional list of specific references. If None, fixes all.
        offset_x: Horizontal spacing between units in mm (default 25.4 = 1 inch).
        offset_y: Vertical spacing between units in mm.
        dry_run: If True, report what would be placed without modifying.
    """

    op_type: Literal["place_missing_units"] = "place_missing_units"
    target_file: TargetFile
    references: Optional[list[str]] = Field(
        default=None,
        description="Specific references to fix, or None for all",
    )
    offset_x: float = Field(
        default=25.4, gt=0, le=254,
        description="Horizontal spacing between units in mm",
    )
    offset_y: float = Field(
        default=0.0, ge=0, le=254,
        description="Vertical spacing between units in mm",
    )
    dry_run: bool = Field(
        default=False,
        description="Report placements without modifying the file",
    )


class RemoveDanglingWiresOp(BaseModel):
    """Remove wire segments with unconnected endpoints.

    Identifies and removes wires where at least one endpoint is not connected
    to any pin, label, junction, or other wire intersection.

    Attributes:
        op_type: Discriminator literal ``"remove_dangling_wires"``.
        target_file: Relative path to the .kicad_sch file.
        max_length_mm: Only remove wires shorter than this (safety). None = no limit.
        dry_run: If True, report what would be removed without modifying.
    """

    op_type: Literal["remove_dangling_wires"] = "remove_dangling_wires"
    target_file: TargetFile
    max_length_mm: Optional[float] = Field(
        default=None, gt=0, le=1000,
        description="Only remove wires shorter than this (mm). None = no limit.",
    )
    dry_run: bool = Field(
        default=False,
        description="Report removals without modifying the file",
    )


class BreakWireShortsOp(BaseModel):
    """Break wire segments that short different nets together.

    Detects wire-level shorts where a physical wire segment connects two nets
    that shouldn't be connected (e.g. ADC_IN_1 shorted to GND via a crossing
    wire). Uses BFS to find the bridge wire(s) on the path between shorted
    net labels and removes them.

    Attributes:
        op_type: Discriminator literal ``"break_wire_shorts"``.
        target_file: Relative path to the .kicad_sch file.
        net_pairs: Optional list of specific net pairs to break, e.g.
            ``[("ADC_IN_1", "GND")]``. If None, breaks all detected shorts.
        strategy: ``"shortest_path"`` removes the single wire on the shortest
            path between shorted nets. ``"all_bridges"`` removes all wires
            connecting the two nets.
        dry_run: If True, report what would be removed without modifying.
    """

    op_type: Literal["break_wire_shorts"] = "break_wire_shorts"
    target_file: TargetFile
    net_pairs: Optional[list[list[str]]] = Field(
        default=None,
        description='Specific net pairs to break, e.g. [["ADC_IN_1", "GND"]]. None = all shorts.',
    )
    strategy: Literal["shortest_path", "all_bridges"] = Field(
        default="shortest_path",
        description="shortest_path: remove one bridge wire. all_bridges: remove all connecting wires.",
    )
    dry_run: bool = Field(
        default=False,
        description="Report bridge wires without modifying the file",
    )
