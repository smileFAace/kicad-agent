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


class PropertySpec(BaseModel):
    """A named property with a string value.

    Attributes:
        name: Property key (e.g. ``"Value"``, ``"Footprint"``).
        value: Property value string.
    """

    name: str = Field(min_length=1, max_length=128)
    value: str = Field(max_length=1024)


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
    if not v.endswith((".kicad_sch", ".kicad_pcb", ".kicad_sym", ".kicad_mod")):
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
    rows: int | None = None
    cols: int | None = None


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
        | VerifyPinMapOp,
        Field(discriminator="op_type"),
    ]


# ---------------------------------------------------------------------------
# Schema export helper (D-04)
# ---------------------------------------------------------------------------


def get_operation_schema() -> dict:
    """Export the full JSON Schema for LLM consumption (D-04)."""
    return Operation.model_json_schema()
