"""GenerationIntent schema for converting natural language design parameters to operation sequences.

GEN-07: The GenerationIntent schema is the structured contract that an LLM (or user)
fills in to specify a design. The intent_to_operations() function converts a validated
GenerationIntent into a list of existing Operation objects that can be executed through
the standard OperationExecutor pipeline.

Security (threat model):
  T-10-12: Component list capped at 500, net list capped at 200 (DoS prevention).
  T-10-13: library_id values validated against safe identifier pattern.

Usage::

    from kicad_agent.generation.intent import GenerationIntent, intent_to_operations

    intent = GenerationIntent(
        name="Motor Driver",
        board=BoardSpec(width_mm=100, height_mm=80),
        components=[
            ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
        ],
        nets=[NetSpec(name="SDA", pins=["R1.1", "U1.3"])],
        power=PowerSpec(nets=["GND", "+3V3"]),
    )
    ops = intent_to_operations(intent)
    for op in ops:
        result = executor.execute(op)
"""

import re
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import (
    AddComponentOp,
    AddNetOp,
    AddPowerOp,
    Operation,
    PositionSpec as SchemaPositionSpec,
)


# ---------------------------------------------------------------------------
# Safe identifier validation (T-10-13)
# ---------------------------------------------------------------------------

_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.#/?]+$")


def _validate_safe_id(v: str) -> str:
    """Reject strings containing characters unsafe for KiCad identifiers."""
    if not _SAFE_ID_PATTERN.match(v):
        raise ValueError(
            f"Identifier contains unsafe characters: {v!r}. "
            "Allowed: alphanumeric, underscore, dash, colon, dot, hash, forward slash."
        )
    return v


# ---------------------------------------------------------------------------
# Intent sub-schemas
# ---------------------------------------------------------------------------


class PositionSpec(BaseModel):
    """Position specification for component placement.

    Attributes:
        x: X coordinate in mm.
        y: Y coordinate in mm.
        angle: Rotation angle in degrees (default 0).
    """

    x: float = Field(description="X coordinate in mm")
    y: float = Field(description="Y coordinate in mm")
    angle: float = Field(default=0.0, description="Rotation angle in degrees")


class ComponentSpec(BaseModel):
    """A component to place on the board/schematic.

    Attributes:
        library_id: Library reference, e.g. ``"Device:R_Small_US"``.
        reference: Reference designator. Auto-assigned if ends with ``"?"``.
        value: Component value string.
        position: Optional explicit position. None triggers auto-placement.
        footprint: Optional footprint lib_id override for PCB.
    """

    library_id: str = Field(
        min_length=1,
        max_length=256,
        description="Library reference, e.g. 'Device:R_Small_US'",
    )
    reference: str = Field(
        default="U?",
        min_length=1,
        max_length=64,
        description="Reference designator. Auto-assigned if '?' suffix.",
    )
    value: str = Field(default="", max_length=256, description="Component value")
    position: PositionSpec | None = Field(
        default=None,
        description="Explicit position. None = auto-place.",
    )
    footprint: str = Field(
        default="",
        max_length=256,
        description="Footprint lib_id override for PCB",
    )

    @field_validator("library_id")
    @classmethod
    def _validate_library_id(cls, v: str) -> str:
        return _validate_safe_id(v)

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_id(v)


class NetSpec(BaseModel):
    """A net connection specification.

    Attributes:
        name: Net name (1-64 characters).
        pins: List of ``"REF.PIN"`` connection descriptors.
    """

    name: str = Field(min_length=1, max_length=64, description="Net name")
    pins: list[str] = Field(
        default_factory=list,
        description="List of 'REF.PIN' connections",
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if v.strip() == "" and len(v) > 0:
            raise ValueError("Net name must not be whitespace-only")
        return v

    @field_validator("pins")
    @classmethod
    def _validate_pins(cls, v: list[str]) -> list[str]:
        for i, pin in enumerate(v):
            if "." not in pin:
                raise ValueError(
                    f"Pin at index {i} must be in 'REF.PIN' format, got: {pin!r}"
                )
        return v


class BoardSpec(BaseModel):
    """Board physical parameters.

    Attributes:
        width_mm: Board width in mm (0 < w <= 500).
        height_mm: Board height in mm (0 < h <= 500).
        layer_count: Number of copper layers (1-32).
        thickness_mm: Board thickness in mm.
        edge_connector: Whether board includes edge connector features.
    """

    width_mm: float = Field(gt=0, le=500, default=50.0, description="Board width in mm")
    height_mm: float = Field(
        gt=0, le=500, default=50.0, description="Board height in mm"
    )
    layer_count: int = Field(ge=1, le=32, default=2, description="Number of copper layers")
    thickness_mm: float = Field(default=1.6, description="Board thickness in mm")
    edge_connector: bool = Field(
        default=False, description="Include edge connector features"
    )


class PowerSpec(BaseModel):
    """Power supply requirements.

    Attributes:
        nets: Power net names (e.g. ``["GND", "+3V3"]``).
    """

    nets: list[str] = Field(
        default_factory=lambda: ["GND", "+3V3"],
        description="Power net names",
    )


class GenerationIntent(BaseModel):
    """Structured specification for generating a PCB design.

    This is the schema an LLM fills in from natural language. The
    intent_to_operations() function converts it to a list of executable
    Operation objects that flow through the existing Transaction-wrapped executor.

    Attributes:
        name: Design name (1-128 characters).
        description: Design description.
        board: Board physical parameters.
        components: Components to place (max 500).
        nets: Net connections (max 200).
        power: Power supply requirements.
        design_rules: Custom design rule overrides (clearances, widths).
    """

    name: str = Field(min_length=1, max_length=128, description="Design name")
    description: str = Field(default="", max_length=1024, description="Design description")
    board: BoardSpec = Field(default_factory=BoardSpec, description="Board parameters")
    components: list[ComponentSpec] = Field(
        default_factory=list, max_length=500, description="Components (max 500)"
    )
    nets: list[NetSpec] = Field(
        default_factory=list, max_length=200, description="Net connections (max 200)"
    )
    power: PowerSpec = Field(default_factory=PowerSpec, description="Power requirements")
    design_rules: dict[str, float] = Field(
        default_factory=dict, description="Custom clearances/widths"
    )


# ---------------------------------------------------------------------------
# Intent-to-operations converter
# ---------------------------------------------------------------------------


def intent_to_operations(
    intent: GenerationIntent,
    target_sch: str = "design.kicad_sch",
    target_pcb: str = "design.kicad_pcb",
) -> list[Operation]:
    """Convert a GenerationIntent into a sequence of Operation objects.

    Produces ordered operations for components, nets, and power symbols
    that can be executed through the existing OperationExecutor pipeline.

    Args:
        intent: Validated GenerationIntent.
        target_sch: Target schematic filename for operations.
        target_pcb: Target PCB filename for operations.

    Returns:
        Ordered list of Operation objects ready for sequential execution.
    """
    ops: list[Operation] = []

    # 1. Add components
    for comp in intent.components:
        pos = comp.position
        if pos is not None:
            schema_pos = SchemaPositionSpec(x=pos.x, y=pos.y, angle=pos.angle)
        else:
            # Default position for auto-placement (0, 0) -- template generator
            # will compute actual positions.
            schema_pos = SchemaPositionSpec(x=0.0, y=0.0)

        op = Operation(
            root=AddComponentOp(
                target_file=target_sch,
                library_id=comp.library_id,
                reference=comp.reference,
                value=comp.value,
                position=schema_pos,
            )
        )
        ops.append(op)

    # 2. Add nets
    for net in intent.nets:
        op = Operation(
            root=AddNetOp(
                target_file=target_pcb,
                net_name=net.name,
            )
        )
        ops.append(op)

    # 3. Add power symbols
    for power_name in intent.power.nets:
        op = Operation(
            root=AddPowerOp(
                target_file=target_sch,
                name=power_name,
                position=SchemaPositionSpec(x=0.0, y=0.0),
            )
        )
        ops.append(op)

    return ops
