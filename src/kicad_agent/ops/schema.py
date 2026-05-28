"""Pydantic v2 operation schema -- the JSON contract the LLM uses to express edit intents.

Design decisions (from CONTEXT.md):
  D-01: One Pydantic model per operation type (not a generic dict).
  D-02: Atomic operations -- one mutation per operation, no compound ops.
  D-03: Single file per operation via ``target_file`` field.
  D-04: Export full JSON Schema via ``model_json_schema()`` for LLM consumption.

Security mitigations (Council review):
  H-01: TargetFile type rejects path traversal (``..``), absolute paths,
        null bytes, and non-KiCad extensions.
  M-04: All string fields enforce min_length / max_length to prevent abuse.

Usage::

    from kicad_agent.ops import Operation

    op = Operation.model_validate({
        "root": {
            "op_type": "add_component",
            "target_file": "motor-driver.kicad_sch",
            "library_id": "Device:R_Small_US",
            "position": {"x": 50.0, "y": 30.0},
        }
    })

    # Export schema for LLM tool contract
    schema = op.model_json_schema()
"""

from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, BeforeValidator, Field, field_validator


# ---------------------------------------------------------------------------
# Shared validators (Council H-1, H-2: S-expression safety constraints)
# ---------------------------------------------------------------------------

# Safe characters for KiCad identifiers: alphanumeric, underscore, dash, colon, dot, hash
_SAFE_ID_PATTERN = r'^[A-Za-z0-9_\-:.#/]+$'


def _validate_safe_identifier(v: str, field_name: str) -> str:
    """Reject strings containing characters unsafe for S-expression output."""
    import re
    if not re.match(_SAFE_ID_PATTERN, v):
        raise ValueError(
            f"{field_name} contains unsafe characters. "
            f"Allowed: alphanumeric, underscore, dash, colon, dot, hash, forward slash."
        )
    return v


# ---------------------------------------------------------------------------
# Shared field types
# ---------------------------------------------------------------------------


class PositionSpec(BaseModel):
    """Position specification for place operations.

    Attributes:
        x: X coordinate in mm.
        y: Y coordinate in mm.
        angle: Rotation angle in degrees (default 0).
    """

    x: float
    y: float
    angle: float = 0.0

    @field_validator("x", "y", "angle")
    @classmethod
    def _reject_non_finite(cls, v: float) -> float:
        import math
        if math.isnan(v) or math.isinf(v):
            raise ValueError("Coordinate values must be finite (not NaN or Infinity)")
        return v


class PropertySpec(BaseModel):
    """A named property with a string value.

    Attributes:
        name: Property key (e.g. ``"Value"``, ``"Footprint"``).
        value: Property value string.
    """

    name: str = Field(min_length=1, max_length=128)
    value: str = Field(max_length=1024)


class PinSpec(BaseModel):
    """Pin definition for symbol creation.

    Attributes:
        number: Pin number (e.g. ``"1"``, ``"A1"``).
        name: Pin name (e.g. ``"VCC"``, ``"DOUT"``).
        electrical_type: KiCad pin electrical type.
        position: Pin position relative to symbol origin.
        length: Pin length in mm (default 2.54).
        graphical_style: Pin graphical style.
        hide: Whether the pin is hidden.
    """

    number: str = Field(min_length=1, max_length=32, description="Pin number")
    name: str = Field(min_length=1, max_length=128, description="Pin name")
    electrical_type: Literal[
        "input", "output", "bidirectional", "tri_state", "passive",
        "free", "unspecified", "power_in", "power_out",
        "open_collector", "open_emitter", "no_connect",
    ] = Field(default="passive", description="Pin electrical type")
    position: PositionSpec
    length: float = Field(default=2.54, gt=0, le=50, description="Pin length in mm")
    graphical_style: Literal[
        "line", "inverted", "clock", "inverted_clock",
        "input_low", "clock_low", "output_low", "edge_clock_high",
        "non_logic",
    ] = Field(default="line", description="Pin graphical style")
    hide: bool = Field(default=False, description="Whether pin is hidden")


# ---------------------------------------------------------------------------
# TargetFile -- path-safe type (Council H-01)
# ---------------------------------------------------------------------------


def _validate_target_file(v: str) -> str:
    """Reject path traversal, absolute paths, null bytes, and non-KiCad extensions."""
    if "\x00" in v:
        raise ValueError("target_file contains null bytes")
    if v.startswith("/"):
        raise ValueError("target_file must be a relative path")
    parts = Path(v).parts
    if ".." in parts:
        raise ValueError("target_file must not contain '..' path traversal")
    valid_extensions = (
        ".kicad_sch", ".kicad_pcb", ".kicad_sym", ".kicad_mod",
        ".kicad_dru", ".kicad_pro",
    )
    valid_names = ("sym-lib-table", "fp-lib-table")
    if not v.endswith(valid_extensions) and Path(v).name not in valid_names:
        raise ValueError("target_file must be a KiCad file type")
    return v


TargetFile = Annotated[
    str,
    Field(min_length=1, max_length=512),
    BeforeValidator(_validate_target_file),
]


# ---------------------------------------------------------------------------
# Operation type models (D-01)
# ---------------------------------------------------------------------------


class AddComponentOp(BaseModel):
    """Add a component to a schematic or PCB.

    Attributes:
        op_type: Discriminator literal ``"add_component"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        library_id: Library reference, e.g. ``"Device:R_Small_US"``.
        reference: Reference designator (default ``"R?"``).
        value: Component value string (default empty).
        position: Placement coordinates.
    """

    op_type: Literal["add_component"] = "add_component"
    target_file: TargetFile
    library_id: str = Field(
        min_length=1,
        max_length=256,
        description="Library reference, e.g. 'Device:R_Small_US'",
    )
    reference: str = Field(
        default="R?",
        min_length=1,
        max_length=64,
        description="Reference designator",
    )
    value: str = Field(
        default="",
        max_length=256,
        description="Component value",
    )
    position: PositionSpec

    @field_validator("library_id")
    @classmethod
    def _validate_library_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "library_id")

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")


class RemoveComponentOp(BaseModel):
    """Remove a component by reference designator.

    Attributes:
        op_type: Discriminator literal ``"remove_component"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        reference: Reference designator to remove.
    """

    op_type: Literal["remove_component"] = "remove_component"
    target_file: TargetFile
    reference: str = Field(
        min_length=1,
        max_length=64,
        description="Reference designator to remove",
    )

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")


class MoveComponentOp(BaseModel):
    """Move a component to a new position.

    Attributes:
        op_type: Discriminator literal ``"move_component"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        reference: Reference designator of the component to move.
        position: Target placement coordinates.
    """

    op_type: Literal["move_component"] = "move_component"
    target_file: TargetFile
    reference: str = Field(min_length=1, max_length=64)
    position: PositionSpec

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")


class ModifyPropertyOp(BaseModel):
    """Modify a component property (value, footprint, reference, custom field).

    Attributes:
        op_type: Discriminator literal ``"modify_property"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        reference: Reference designator of the target component.
        property_name: Name of the property to modify.
        new_value: New value for the property.
    """

    op_type: Literal["modify_property"] = "modify_property"
    target_file: TargetFile
    reference: str = Field(min_length=1, max_length=64)
    property_name: str = Field(min_length=1, max_length=128)
    new_value: str = Field(max_length=1024)

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")

    @field_validator("property_name")
    @classmethod
    def _validate_property_name(cls, v: str) -> str:
        return _validate_safe_identifier(v, "property_name")


class DuplicateComponentOp(BaseModel):
    """Duplicate a component with fresh UUID and incremented reference.

    Attributes:
        op_type: Discriminator literal ``"duplicate_component"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        source_reference: Reference designator of the component to duplicate.
        offset: Optional position offset from source (x, y; angle is ignored).
        count: Number of copies to create (default 1, must be >= 1).
    """

    op_type: Literal["duplicate_component"] = "duplicate_component"
    target_file: TargetFile
    source_reference: str = Field(
        min_length=1,
        max_length=64,
        description="Reference designator of the component to duplicate",
    )
    offset: PositionSpec | None = None
    count: int = Field(default=1, ge=1, le=100, description="Number of copies (1-100)")

    @field_validator("source_reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "source_reference")


class ArrayReplicateOp(BaseModel):
    """Replicate a component in a linear, circular, or matrix array pattern.

    Attributes:
        op_type: Discriminator literal ``"array_replicate"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        source_reference: Reference designator of the component to replicate.
        pattern: Array pattern type (linear, circular, or matrix).
        count: Number of replications (for matrix: rows * cols).
        spacing: Position spacing specification.
        angle_step: Degrees per step (circular pattern only).
        center: Center point (circular pattern only).
        rows: Number of rows (matrix pattern only).
        cols: Number of columns (matrix pattern only).
    """

    op_type: Literal["array_replicate"] = "array_replicate"
    target_file: TargetFile
    source_reference: str = Field(
        min_length=1,
        max_length=64,
        description="Reference designator of the component to replicate",
    )
    pattern: Literal["linear", "circular", "matrix"]
    count: int = Field(
        default=1,
        ge=1,
        le=100,
        description="Number of replications (1-100)",
    )
    spacing: PositionSpec
    angle_step: float | None = None
    center: PositionSpec | None = None
    rows: int | None = Field(default=None, ge=1, le=100)
    cols: int | None = Field(default=None, ge=1, le=100)

    @field_validator("source_reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "source_reference")


class AddNetOp(BaseModel):
    """Add a net to a PCB.

    Attributes:
        op_type: Discriminator literal ``"add_net"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        net_name: Net name. Empty string triggers auto-generation as ``"N_<number>"``.
        net_number: Explicit net number. None triggers auto-assignment.
    """

    op_type: Literal["add_net"] = "add_net"
    target_file: TargetFile
    net_name: str = Field(
        default="",
        max_length=64,
        description="Net name. Empty triggers auto-generation.",
    )
    net_number: Optional[int] = Field(
        default=None,
        description="Explicit net number. None = auto-assign.",
    )

    @field_validator("net_name")
    @classmethod
    def _reject_whitespace_only(cls, v: str) -> str:
        if v.strip() == "" and len(v) > 0:
            raise ValueError("Net name must not be whitespace-only")
        return v


class RemoveNetOp(BaseModel):
    """Remove a net from a PCB, disconnecting all pads.

    Attributes:
        op_type: Discriminator literal ``"remove_net"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        net_name: Name of the net to remove.
    """

    op_type: Literal["remove_net"] = "remove_net"
    target_file: TargetFile
    net_name: str = Field(
        min_length=1,
        max_length=64,
        description="Name of the net to remove",
    )

    @field_validator("net_name")
    @classmethod
    def _reject_whitespace_only(cls, v: str) -> str:
        if v.strip() == "":
            raise ValueError("Net name must not be whitespace-only")
        return v


class RenameNetOp(BaseModel):
    """Rename a net, propagating to all connected pads.

    Attributes:
        op_type: Discriminator literal ``"rename_net"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        old_name: Current net name.
        new_name: Desired new net name.
    """

    op_type: Literal["rename_net"] = "rename_net"
    target_file: TargetFile
    old_name: str = Field(min_length=1, max_length=64)
    new_name: str = Field(min_length=1, max_length=64)

    @field_validator("old_name", "new_name")
    @classmethod
    def _reject_whitespace_only(cls, v: str) -> str:
        if v.strip() == "":
            raise ValueError("Net name must not be whitespace-only")
        return v


class AddBusOp(BaseModel):
    """Add a bus to a schematic with member nets.

    Attributes:
        op_type: Discriminator literal ``"add_bus"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        bus_name: Bus name.
        member_nets: List of net names that belong to this bus.
    """

    op_type: Literal["add_bus"] = "add_bus"
    target_file: TargetFile
    bus_name: str = Field(
        min_length=1,
        max_length=64,
        description="Bus name",
    )
    member_nets: list[str] = Field(
        min_length=1,
        max_length=32,
        description="Member net names (1-32 members)",
    )

    @field_validator("bus_name")
    @classmethod
    def _reject_whitespace_only(cls, v: str) -> str:
        if v.strip() == "":
            raise ValueError("Bus name must not be whitespace-only")
        return v

    @field_validator("member_nets")
    @classmethod
    def _validate_member_nets(cls, v: list[str]) -> list[str]:
        for i, net in enumerate(v):
            if len(net) > 64:
                raise ValueError(
                    f"Member net at index {i} exceeds 64 characters"
                )
            if net.strip() == "" and len(net) > 0:
                raise ValueError(
                    f"Member net at index {i} must not be whitespace-only"
                )
        return v


class RemoveBusOp(BaseModel):
    """Remove a bus from a schematic.

    Attributes:
        op_type: Discriminator literal ``"remove_bus"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        bus_name: Bus name to remove.
    """

    op_type: Literal["remove_bus"] = "remove_bus"
    target_file: TargetFile
    bus_name: str = Field(
        min_length=1,
        max_length=64,
        description="Bus name to remove",
    )

    @field_validator("bus_name")
    @classmethod
    def _reject_whitespace_only(cls, v: str) -> str:
        if v.strip() == "":
            raise ValueError("Bus name must not be whitespace-only")
        return v


class RenumberRefsOp(BaseModel):
    """Renumber component references with configurable prefix and sequencing.

    Attributes:
        op_type: Discriminator literal ``"renumber_refs"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        prefix: Only renumber components with this prefix. Empty means all (default).
        start_index: Starting index for numbering (default 1, must be >= 1).
        step: Step between indices (default 1, must be >= 1).
    """

    op_type: Literal["renumber_refs"] = "renumber_refs"
    target_file: TargetFile
    prefix: str = Field(
        default="",
        max_length=16,
        description="Prefix filter. Empty means renumber all prefixes.",
    )
    start_index: int = Field(
        default=1,
        ge=1,
        description="Starting index for numbering",
    )
    step: int = Field(
        default=1,
        ge=1,
        description="Step between sequential indices",
    )


class ValidateRefsOp(BaseModel):
    """Validate that all component references are unique.

    Attributes:
        op_type: Discriminator literal ``"validate_refs"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
    """

    op_type: Literal["validate_refs"] = "validate_refs"
    target_file: TargetFile


class AnnotateOp(BaseModel):
    """Auto-assign references to unannotated components (refs ending in '?').

    Attributes:
        op_type: Discriminator literal ``"annotate"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        prefix_filter: Only annotate components matching this prefix. Empty means all.
    """

    op_type: Literal["annotate"] = "annotate"
    target_file: TargetFile
    prefix_filter: str = Field(
        default="",
        max_length=16,
        description="Prefix filter for annotation. Empty means annotate all.",
    )


class CrossRefCheckOp(BaseModel):
    """Verify all symbol libIds resolve to entries in the embedded libSymbols.

    Attributes:
        op_type: Discriminator literal ``"cross_ref_check"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
    """

    op_type: Literal["cross_ref_check"] = "cross_ref_check"
    target_file: TargetFile


class AssignFootprintOp(BaseModel):
    """Assign a footprint to a schematic component.

    Attributes:
        op_type: Discriminator literal ``"assign_footprint"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        reference: Component reference designator (e.g. ``"U1"``).
        footprint_lib_id: Footprint library reference (e.g. ``"Package_DIP:DIP-8_W7.62mm"``).
    """

    op_type: Literal["assign_footprint"] = "assign_footprint"
    target_file: TargetFile
    reference: str = Field(
        min_length=1,
        max_length=64,
        description="Component reference designator",
    )
    footprint_lib_id: str = Field(
        min_length=1,
        max_length=256,
        description="Footprint library reference, e.g. 'Package_DIP:DIP-8_W7.62mm'",
    )

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")

    @field_validator("footprint_lib_id")
    @classmethod
    def _validate_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "footprint_lib_id")


class SwapFootprintOp(BaseModel):
    """Swap a PCB footprint while preserving pad-to-net connections.

    Attributes:
        op_type: Discriminator literal ``"swap_footprint"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        reference: Reference designator of the footprint to swap.
        new_footprint_lib_id: New footprint library reference.
    """

    op_type: Literal["swap_footprint"] = "swap_footprint"
    target_file: TargetFile
    reference: str = Field(
        min_length=1,
        max_length=64,
        description="Reference designator of the footprint to swap",
    )
    new_footprint_lib_id: str = Field(
        min_length=1,
        max_length=256,
        description="New footprint library reference",
    )

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")

    @field_validator("new_footprint_lib_id")
    @classmethod
    def _validate_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "new_footprint_lib_id")


class ValidateFootprintOp(BaseModel):
    """Validate that a footprint exists in the available libraries.

    Attributes:
        op_type: Discriminator literal ``"validate_footprint"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        footprint_lib_id: Footprint library reference to validate.
    """

    op_type: Literal["validate_footprint"] = "validate_footprint"
    target_file: TargetFile
    footprint_lib_id: str = Field(
        min_length=1,
        max_length=256,
        description="Footprint library reference to validate",
    )

    @field_validator("footprint_lib_id")
    @classmethod
    def _validate_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "footprint_lib_id")


class VerifyPinMapOp(BaseModel):
    """Verify that symbol pin numbers match footprint pad numbers.

    Attributes:
        op_type: Discriminator literal ``"verify_pin_map"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        reference: Component reference designator.
        footprint_lib_id: Footprint library reference to verify against.
    """

    op_type: Literal["verify_pin_map"] = "verify_pin_map"
    target_file: TargetFile
    reference: str = Field(
        min_length=1,
        max_length=64,
        description="Component reference designator",
    )
    footprint_lib_id: str = Field(
        min_length=1,
        max_length=256,
        description="Footprint library reference to verify against",
    )

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")

    @field_validator("footprint_lib_id")
    @classmethod
    def _validate_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "footprint_lib_id")


class UpdateFootprintFromLibraryOp(BaseModel):
    """Reload a PCB footprint's geometry from the library, preserving placement.

    Reads the fresh footprint definition from the library ``.kicad_mod`` file
    and replaces the geometry in the PCB while preserving position, rotation,
    reference designator, value, and pad-to-net connections.

    This is the programmatic equivalent of KiCad's GUI
    ``Tools > Update Footprints from Library`` command.

    Attributes:
        op_type: Discriminator literal ``"update_footprint_from_library"``.
        target_file: Relative path to the KiCad PCB file (H-01 validated).
        reference: Reference designator of the footprint to update (e.g. ``"U2"``).
        footprint_lib_id: Optional override footprint library reference.
            If omitted, uses the footprint's existing ``libId`` (refresh from same library).
            If provided, also swaps to a different footprint (swap + update combined).
    """

    op_type: Literal["update_footprint_from_library"] = "update_footprint_from_library"
    target_file: TargetFile
    reference: str = Field(
        min_length=1,
        max_length=64,
        description="Reference designator of the footprint to update",
    )
    footprint_lib_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="Optional override lib_id. None = refresh from existing library.",
    )

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")

    @field_validator("footprint_lib_id")
    @classmethod
    def _validate_lib_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_safe_identifier(v, "footprint_lib_id")
        return v


class AddWireOp(BaseModel):
    """Add a wire segment between two points in a schematic.

    Attributes:
        op_type: Discriminator literal ``"add_wire"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        start_x: Start X coordinate in mm.
        start_y: Start Y coordinate in mm.
        end_x: End X coordinate in mm.
        end_y: End Y coordinate in mm.
    """

    op_type: Literal["add_wire"] = "add_wire"
    target_file: TargetFile
    start_x: float = Field(description="Start X coordinate in mm")
    start_y: float = Field(description="Start Y coordinate in mm")
    end_x: float = Field(description="End X coordinate in mm")
    end_y: float = Field(description="End Y coordinate in mm")

    @field_validator("start_x", "start_y", "end_x", "end_y")
    @classmethod
    def _reject_non_finite(cls, v: float) -> float:
        import math
        if math.isnan(v) or math.isinf(v):
            raise ValueError("Coordinate values must be finite (not NaN or Infinity)")
        return v


class AddLabelOp(BaseModel):
    """Add a net label to a schematic (local, global, or hierarchical).

    Attributes:
        op_type: Discriminator literal ``"add_label"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        name: Label text (e.g. ``"SDA"``, ``"+5V"``).
        label_type: Label scope — ``"local"``, ``"global"``, or ``"hierarchical"``.
        position: Placement coordinates (x, y, angle).
        shape: Graphical shape for global/hierarchical labels (e.g. ``"input"``,
               ``"output"``, ``"bidirectional"``, ``"tri_state"``, ``"passive"``).
    """

    op_type: Literal["add_label"] = "add_label"
    target_file: TargetFile
    name: str = Field(
        min_length=1,
        max_length=128,
        description="Label text (e.g. 'SDA', '+5V')",
    )
    label_type: Literal["local", "global", "hierarchical"] = Field(
        default="local",
        description="Label scope: local, global, or hierarchical",
    )
    position: PositionSpec
    shape: str = Field(
        default="input",
        description="Shape for global/hierarchical labels (input, output, bidirectional, tri_state, passive)",
    )


class AddPowerOp(BaseModel):
    """Add a power symbol to a schematic (e.g. +5V, GND, +3V3).

    Places a power library symbol (``power:<name>``) at the specified position.
    Power symbols have a single pin that connects to the named net.

    Attributes:
        op_type: Discriminator literal ``"add_power"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        name: Power net name (e.g. ``"+5V"``, ``"GND"``, ``"+3V3"``).
        position: Placement coordinates.
    """

    op_type: Literal["add_power"] = "add_power"
    target_file: TargetFile
    name: str = Field(
        min_length=1,
        max_length=64,
        description="Power net name (e.g. '+5V', 'GND', '+3V3')",
    )
    position: PositionSpec


class AddNoConnectOp(BaseModel):
    """Add a no-connect flag to a schematic pin.

    Attributes:
        op_type: Discriminator literal ``"add_no_connect"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        position: Placement coordinates (x, y; angle is ignored).
    """

    op_type: Literal["add_no_connect"] = "add_no_connect"
    target_file: TargetFile
    position: PositionSpec


class AddJunctionOp(BaseModel):
    """Add a junction dot at a wire intersection in a schematic.

    Attributes:
        op_type: Discriminator literal ``"add_junction"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        position: Placement coordinates (x, y; angle is ignored).
    """

    op_type: Literal["add_junction"] = "add_junction"
    target_file: TargetFile
    position: PositionSpec


class AddLibEntryOp(BaseModel):
    """Add a library entry to sym-lib-table or fp-lib-table.

    Attributes:
        op_type: Discriminator literal ``"add_lib_entry"``.
        target_file: Relative path to sym-lib-table or fp-lib-table.
        lib_name: Library name (e.g. ``"Device"``, ``"MyLib"``).
        lib_type: Library type (``"KiCad"`` or ``"Legacy"``).
        uri: Library URI path, may contain variables like ``${KIPRJMOD}``.
        options: Library options string (usually empty).
        description: Library description.
    """

    op_type: Literal["add_lib_entry"] = "add_lib_entry"
    target_file: TargetFile
    lib_name: str = Field(
        min_length=1,
        max_length=128,
        description="Library name",
    )
    lib_type: Literal["KiCad", "Legacy"] = "KiCad"
    uri: str = Field(
        min_length=1,
        max_length=512,
        description="Library URI path",
    )
    options: str = Field(default="", max_length=256)
    description: str = Field(default="", max_length=512)

    @field_validator("lib_name")
    @classmethod
    def _validate_lib_name(cls, v: str) -> str:
        return _validate_safe_identifier(v, "lib_name")


class RemoveLibEntryOp(BaseModel):
    """Remove a library entry from sym-lib-table or fp-lib-table.

    Attributes:
        op_type: Discriminator literal ``"remove_lib_entry"``.
        target_file: Relative path to sym-lib-table or fp-lib-table.
        lib_name: Library name to remove.
    """

    op_type: Literal["remove_lib_entry"] = "remove_lib_entry"
    target_file: TargetFile
    lib_name: str = Field(
        min_length=1,
        max_length=128,
        description="Library name to remove",
    )

    @field_validator("lib_name")
    @classmethod
    def _validate_lib_name(cls, v: str) -> str:
        return _validate_safe_identifier(v, "lib_name")


class AddNetClassOp(BaseModel):
    """Add a net class with track/via/clearance dimensions.

    Attributes:
        op_type: Discriminator literal ``"add_net_class"``.
        target_file: Relative path to the .kicad_dru file.
        name: Net class name.
        clearance: Clearance in mm (must be > 0).
        track_width: Track width in mm (must be > 0).
        via_diameter: Via diameter in mm (must be > 0).
        via_drill: Via drill in mm (must be > 0).
    """

    op_type: Literal["add_net_class"] = "add_net_class"
    target_file: TargetFile
    name: str = Field(
        min_length=1,
        max_length=64,
        description="Net class name",
    )
    clearance: float = Field(gt=0, description="Clearance in mm")
    track_width: float = Field(gt=0, description="Track width in mm")
    via_diameter: float = Field(gt=0, description="Via diameter in mm")
    via_drill: float = Field(gt=0, description="Via drill in mm")


class AddDesignRuleOp(BaseModel):
    """Add a custom DRC rule to .kicad_dru.

    Attributes:
        op_type: Discriminator literal ``"add_design_rule"``.
        target_file: Relative path to the .kicad_dru file.
        name: Rule name.
        constraint_type: Constraint type (e.g. ``"clearance"``, ``"width"``).
        constraint_values: Key-value constraint parameters.
        condition: KiCad condition expression string.
    """

    op_type: Literal["add_design_rule"] = "add_design_rule"
    target_file: TargetFile
    name: str = Field(
        min_length=1,
        max_length=128,
        description="Rule name",
    )
    constraint_type: str = Field(
        min_length=1,
        max_length=64,
        description="Constraint type (e.g. 'clearance', 'width')",
    )
    constraint_values: dict[str, str] = Field(default_factory=dict)
    condition: str = Field(default="", max_length=512)


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


class ValidatePowerNetsOp(BaseModel):
    """Check all power pins have connected power symbols.

    Validates that every power pin (power_in, power_out) in the schematic
    is connected to a power symbol (power:* library reference).

    Attributes:
        op_type: Discriminator literal ``"validate_power_nets"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
    """

    op_type: Literal["validate_power_nets"] = "validate_power_nets"
    target_file: TargetFile


class ValidateSchematicOp(BaseModel):
    """Comprehensive schematic validation combining multiple checks.

    Runs KiCad 10 format validation, symbol resolution, power net checks,
    and annotation completeness in a single operation. Returns structured
    results for each check category.

    Attributes:
        op_type: Discriminator literal ``"validate_schematic"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        check_symbol_resolution: Verify all lib_ids resolve to symbol definitions (default True).
        check_format: Validate KiCad 10 S-expression format rules (default True).
        check_power_nets: Check power pin connectivity (default True).
        check_annotation: Check for unannotated components (default True).
    """

    op_type: Literal["validate_schematic"] = "validate_schematic"
    target_file: TargetFile
    check_symbol_resolution: bool = Field(default=True, description="Check all lib_ids resolve to symbol definitions")
    check_format: bool = Field(default=True, description="Validate KiCad 10 format rules")
    check_power_nets: bool = Field(default=True, description="Check power pin connectivity")
    check_annotation: bool = Field(default=True, description="Check for unannotated components")


class ParseErcOp(BaseModel):
    """Parse ERC results for a schematic file.

    SCHREPAIR-01: Returns structured violation data from kicad-cli ERC JSON output.

    Attributes:
        op_type: Discriminator literal ``"parse_erc"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
    """

    op_type: Literal["parse_erc"] = "parse_erc"
    target_file: TargetFile


class ExtractViolationPositionsOp(BaseModel):
    """Extract positions for a specific ERC violation type.

    SCHREPAIR-02: Filters violations by type and returns (x,y) positions.

    Attributes:
        op_type: Discriminator literal ``"extract_violation_positions"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        violation_type: Violation type to filter for (e.g. "pin_not_connected").
    """

    op_type: Literal["extract_violation_positions"] = "extract_violation_positions"
    target_file: TargetFile
    violation_type: str = Field(
        min_length=1,
        max_length=128,
        description="Violation type to filter for (e.g. 'pin_not_connected')",
    )


class ValidateHlabelsOp(BaseModel):
    """Validate hierarchical labels in a schematic.

    SCHREPAIR-03: Compares actual hlabels against expected set.

    Attributes:
        op_type: Discriminator literal ``"validate_hlabels"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        expected_labels: List of expected hierarchical label names. Empty means count only.
    """

    op_type: Literal["validate_hlabels"] = "validate_hlabels"
    target_file: TargetFile
    expected_labels: list[str] = Field(
        default_factory=list,
        max_length=200,
        description="Expected hierarchical label names. Empty = count only.",
    )


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


class AddCopperZoneOp(BaseModel):
    """Add a copper zone/ground pour to a PCB.

    Attributes:
        op_type: Discriminator literal ``"add_copper_zone"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        net_name: Net name for the zone (e.g. "GND").
        layer: Copper layer (e.g. "F.Cu", "B.Cu").
        clearance: Zone clearance in mm.
        min_width: Minimum fill width in mm.
        priority: Zone priority (higher = filled first).
    """

    op_type: Literal["add_copper_zone"] = "add_copper_zone"
    target_file: TargetFile
    net_name: str = Field(min_length=1, max_length=64, description="Net name for the zone")
    layer: str = Field(default="F.Cu", max_length=32, description="Copper layer")
    clearance: float = Field(default=0.5, gt=0, description="Clearance in mm")
    min_width: float = Field(default=0.25, gt=0, description="Minimum fill width in mm")
    priority: int = Field(default=0, ge=0, description="Zone priority")


class SetBoardOutlineOp(BaseModel):
    """Define PCB board shape as a rectangle on Edge.Cuts.

    Attributes:
        op_type: Discriminator literal ``"set_board_outline"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        width: Board width in mm.
        height: Board height in mm.
    """

    op_type: Literal["set_board_outline"] = "set_board_outline"
    target_file: TargetFile
    width: float = Field(gt=0, le=1000, description="Board width in mm")
    height: float = Field(gt=0, le=1000, description="Board height in mm")


class AssignNetClassOp(BaseModel):
    """Assign a net class to a specific net in the PCB.

    Attributes:
        op_type: Discriminator literal ``"assign_net_class"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        net_name: Name of the net to assign.
        net_class_name: Name of the net class to assign.
    """

    op_type: Literal["assign_net_class"] = "assign_net_class"
    target_file: TargetFile
    net_name: str = Field(min_length=1, max_length=64, description="Net name")
    net_class_name: str = Field(min_length=1, max_length=64, description="Net class name")


class AutoRouteOp(BaseModel):
    """Auto-route nets on a PCB using A* pathfinding.

    Attributes:
        op_type: Discriminator literal ``"auto_route"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        nets: Optional list of specific net names to route. Routes all nets if empty.
        layer: Copper layer for routed traces. Default "F.Cu".
    """

    op_type: Literal["auto_route"] = "auto_route"
    target_file: TargetFile
    nets: list[str] = Field(default_factory=list, description="Net names to route (empty = all)")
    layer: str = Field(default="F.Cu", pattern=r"^[FB]\.Cu|In[1-9]\d*\.Cu$", description="Target copper layer")


# ---------------------------------------------------------------------------
# File creation operations
# ---------------------------------------------------------------------------


class CreateSchematicOp(BaseModel):
    """Create a new empty .kicad_sch file.

    Attributes:
        op_type: Discriminator literal ``"create_schematic"``.
        target_file: Relative path for the new .kicad_sch file (must not exist).
        paper: Paper size (default ``"A4"``).
        title: Optional title block title.
    """

    op_type: Literal["create_schematic"] = "create_schematic"
    target_file: TargetFile
    paper: str = Field(default="A4", max_length=16, description="Paper size (A4, A3, etc.)")
    title: str = Field(default="", max_length=256, description="Schematic title")


class CreatePcbOp(BaseModel):
    """Create a new empty .kicad_pcb file.

    Attributes:
        op_type: Discriminator literal ``"create_pcb"``.
        target_file: Relative path for the new .kicad_pcb file (must not exist).
        title: Optional title block title.
    """

    op_type: Literal["create_pcb"] = "create_pcb"
    target_file: TargetFile
    title: str = Field(default="", max_length=256, description="PCB title")


class CreateProjectOp(BaseModel):
    """Create a new empty .kicad_pro project file.

    Attributes:
        op_type: Discriminator literal ``"create_project"``.
        target_file: Relative path for the new .kicad_pro file (must not exist).
    """

    op_type: Literal["create_project"] = "create_project"
    target_file: TargetFile


class CreateSymbolOp(BaseModel):
    """Create a new symbol definition in a .kicad_sym library file.

    If the library file does not exist, it is created. If it exists, the
    symbol is appended. Duplicate symbol names are rejected.

    Attributes:
        op_type: Discriminator literal ``"create_symbol"``.
        target_file: Relative path to the .kicad_sym library file.
        symbol_name: Name of the new symbol.
        reference_prefix: Reference prefix (e.g. ``"R"``, ``"U"``, ``"C"``).
        value: Default value for the symbol.
        pins: List of pin definitions.
        properties: Additional custom properties.
        body_width: Width of the default rectangle body in mm.
        body_height: Height of the default rectangle body in mm.
    """

    op_type: Literal["create_symbol"] = "create_symbol"
    target_file: TargetFile
    symbol_name: str = Field(min_length=1, max_length=128, description="Symbol name")
    reference_prefix: str = Field(
        default="U", min_length=1, max_length=8,
        description="Reference prefix (e.g. R, U, C)",
    )
    value: str = Field(default="", max_length=256, description="Default symbol value")
    pins: list[PinSpec] = Field(
        default_factory=list,
        max_length=200,
        description="Pin definitions",
    )
    properties: list[PropertySpec] = Field(
        default_factory=list,
        max_length=50,
        description="Additional custom properties",
    )
    body_width: float = Field(
        default=10.16, gt=0, le=200,
        description="Body rectangle width in mm",
    )
    body_height: float = Field(
        default=10.16, gt=0, le=200,
        description="Body rectangle height in mm",
    )

    @field_validator("symbol_name")
    @classmethod
    def _validate_symbol_name(cls, v: str) -> str:
        return _validate_safe_identifier(v, "symbol_name")

    @field_validator("reference_prefix")
    @classmethod
    def _validate_reference_prefix(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference_prefix")


class EmbedSymbolOp(BaseModel):
    """Embed a symbol definition from a .kicad_sym library into a schematic's lib_symbols.

    Extracts the symbol definition from the specified library file and injects it
    into the schematic's embedded lib_symbols section. This is required before a
    symbol can be used in the schematic (KiCad resolves symbols from lib_symbols first).

    If the symbol already exists in the schematic's lib_symbols (same libId), the
    operation is a no-op and returns success.

    Attributes:
        op_type: Discriminator literal ``"embed_symbol"``.
        target_file: Relative path to the .kicad_sch file.
        lib_id: Library ID of the symbol to embed (e.g. ``"Analog-Ecosystem-SMD:RP2350B"``).
        library_path: Relative path to the .kicad_sym library file containing the symbol.
    """

    op_type: Literal["embed_symbol"] = "embed_symbol"
    target_file: TargetFile
    lib_id: str = Field(
        min_length=1, max_length=256,
        description="Library:symbol ID to embed (e.g. 'Library:SymbolName')",
    )
    library_path: str = Field(
        min_length=1, max_length=512,
        description="Relative path to .kicad_sym library file",
    )

    @field_validator("lib_id")
    @classmethod
    def _validate_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "lib_id")


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


# ---------------------------------------------------------------------------
# Discriminated union (D-01, D-02, D-03)
# ---------------------------------------------------------------------------


class Operation(BaseModel):
    """Discriminated union of all operation types.

    Per D-02: each operation is atomic (one mutation).
    Per D-03: each operation targets one file via ``target_file``.
    Per D-04: export full JSON Schema via ``model_json_schema()``.
    """

    root: Annotated[
        AddComponentOp
        | RemoveComponentOp
        | MoveComponentOp
        | ModifyPropertyOp
        | DuplicateComponentOp
        | ArrayReplicateOp
        | AddNetOp
        | RemoveNetOp
        | RenameNetOp
        | AddBusOp
        | RemoveBusOp
        | RenumberRefsOp
        | ValidateRefsOp
        | AnnotateOp
        | CrossRefCheckOp
        | AssignFootprintOp
        | SwapFootprintOp
        | ValidateFootprintOp
        | VerifyPinMapOp
        | UpdateFootprintFromLibraryOp
        | AddWireOp
        | AddLabelOp
        | AddPowerOp
        | AddNoConnectOp
        | AddJunctionOp
        | AddLibEntryOp
        | RemoveLibEntryOp
        | AddNetClassOp
        | AddDesignRuleOp
        | RepairSchematicOp
        | ValidatePowerNetsOp
        | ValidateSchematicOp
        | ParseErcOp
        | ExtractViolationPositionsOp
        | ValidateHlabelsOp
        | ConvertKicad6To10Op
        | SnapToGridOp
        | AddPowerFlagOp
        | RebuildRootSheetOp
        | AddCopperZoneOp
        | SetBoardOutlineOp
        | AssignNetClassOp
        | AutoRouteOp
        | CreateSchematicOp
        | CreatePcbOp
        | CreateProjectOp
        | CreateSymbolOp
        | EmbedSymbolOp
        | SwapSymbolOp,
        Field(discriminator="op_type"),
    ]


# ---------------------------------------------------------------------------
# Schema export helper (D-04)
# ---------------------------------------------------------------------------


def get_operation_schema() -> dict:
    """Export the full JSON Schema for LLM consumption (D-04)."""
    return Operation.model_json_schema()
