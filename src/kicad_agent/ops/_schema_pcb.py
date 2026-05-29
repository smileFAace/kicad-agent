"""PCB-specific operation schemas -- net class, design rule, copper zone, board outline, auto-route."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import (
    TargetFile,
    _validate_sexpr_safe_string,
)


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

    @field_validator("condition")
    @classmethod
    def _validate_condition_sexpr(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


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
