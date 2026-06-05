"""Wire/label/power operation schemas -- wire, label, power, no-connect, junction."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import (
    PositionSpec,
    TargetFile,
    _validate_sexpr_safe_string,
)


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


class ConnectPinsOp(BaseModel):
    """Connect two schematic pins by reference and pin number/name.

    This is the semantic counterpart to ``add_wire``. Instead of requiring
    callers to hand-compute coordinates, it resolves real pin endpoints from
    embedded library symbols and adds a wire between them.

    Pin references use ``REF.PIN`` format, e.g. ``U1.34`` or ``J3.Pin_2``.
    """

    op_type: Literal["connect_pins"] = "connect_pins"
    target_file: TargetFile
    source: str = Field(min_length=3, max_length=128, description="Source pin as REF.PIN")
    target: str = Field(min_length=3, max_length=128, description="Target pin as REF.PIN")

    @field_validator("source", "target")
    @classmethod
    def _validate_pin_ref(cls, v: str) -> str:
        v = _validate_sexpr_safe_string(v.strip())
        if "." not in v:
            raise ValueError("Pin reference must use REF.PIN format, e.g. U1.34")
        ref, pin = v.split(".", 1)
        if not ref or not pin:
            raise ValueError("Pin reference must include both reference and pin")
        return v


class AddLabelOp(BaseModel):
    """Add a net label to a schematic (local, global, or hierarchical).

    Attributes:
        op_type: Discriminator literal ``"add_label"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        name: Label text (e.g. ``"SDA"``, ``"+5V"``).
        label_type: Label scope -- ``"local"``, ``"global"``, or ``"hierarchical"``.
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

    @field_validator("name")
    @classmethod
    def _validate_name_sexpr(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


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

    @field_validator("name")
    @classmethod
    def _validate_name_sexpr(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


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
