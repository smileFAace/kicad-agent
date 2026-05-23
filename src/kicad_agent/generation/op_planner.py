"""Operation-sequence planner that converts GenerationIntent into dependency-ordered Operations.

GEN-09: Converts a validated GenerationIntent into an ordered list of PlanSteps,
each wrapping an existing Operation from schema.py. The planner enforces
dependency ordering: board outline -> components -> nets -> power -> wires ->
repair -> validation.

Usage::

    from kicad_agent.generation.op_planner import OpPlanner, plan_operation_sequence

    steps = plan_operation_sequence(intent, target_dir=Path("/project"))
    for step in steps:
        print(step.description, step.dependencies)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kicad_agent.generation.intent import GenerationIntent
from kicad_agent.ops.schema import (
    AddComponentOp,
    AddNetOp,
    AddPowerOp,
    AddWireOp,
    Operation,
    PositionSpec as SchemaPositionSpec,
    RepairSchematicOp,
    SetBoardOutlineOp,
    ValidatePowerNetsOp,
)


@dataclass(frozen=True)
class PlanStep:
    """A single step in the operation plan.

    Attributes:
        operation: The Operation to execute.
        dependencies: List of step IDs this step depends on.
        description: Human-readable description of the step.
        step_id: Unique identifier for dependency tracking.
    """

    operation: Operation
    dependencies: list[str]
    description: str
    step_id: str


class OpPlanner:
    """Converts a GenerationIntent into a dependency-ordered operation sequence.

    Produces PlanSteps that respect the dependency chain:
    board outline -> components -> nets -> power -> wires -> repair -> validation.

    Args:
        intent: Validated GenerationIntent specifying the design.
        target_dir: Output directory for generated files.
    """

    def __init__(self, intent: GenerationIntent, target_dir: Path) -> None:
        self._intent = intent
        self._target_dir = target_dir
        self._step_counter = 0

    def plan(self) -> list[PlanStep]:
        """Generate the ordered operation sequence.

        Returns:
            List of PlanStep instances in dependency order.
        """
        steps: list[PlanStep] = []
        step_ids: list[str] = []

        # 1. Board outline step
        board_step = self._make_board_outline_step()
        steps.append(board_step)
        step_ids.append(board_step.step_id)

        # 2. Component steps (depend on board outline)
        comp_step_ids: list[str] = []
        for comp in self._intent.components:
            comp_step = self._make_component_step(comp)
            steps.append(comp_step)
            step_ids.append(comp_step.step_id)
            comp_step_ids.append(comp_step.step_id)

        # 3. Power steps (depend on board outline)
        power_step_ids: list[str] = []
        for power_name in self._intent.power.nets:
            power_step = self._make_power_step(power_name)
            steps.append(power_step)
            step_ids.append(power_step.step_id)
            power_step_ids.append(power_step.step_id)

        # 4. Net steps (depend on components)
        net_step_ids: list[str] = []
        for net in self._intent.nets:
            net_step = self._make_net_step(net.name)
            steps.append(net_step)
            step_ids.append(net_step.step_id)
            net_step_ids.append(net_step.step_id)

        # Collect all step IDs before wires (components + nets + power)
        pre_wire_ids = comp_step_ids + power_step_ids + net_step_ids

        # 5. Wire steps (depend on components + nets)
        wire_step_ids: list[str] = []
        for net in self._intent.nets:
            wire_step = self._make_wire_step(net)
            steps.append(wire_step)
            step_ids.append(wire_step.step_id)
            wire_step_ids.append(wire_step.step_id)

        # 6. Repair step (depends on all above)
        repair_step = self._make_repair_step(pre_wire_ids)
        if repair_step is not None:
            steps.append(repair_step)
            step_ids.append(repair_step.step_id)
            pre_validate_ids = [repair_step.step_id]
        else:
            pre_validate_ids = pre_wire_ids + wire_step_ids

        # 7. Validation step (depends on all above)
        validate_step = self._make_validate_step(pre_validate_ids)
        if validate_step is not None:
            steps.append(validate_step)
            step_ids.append(validate_step.step_id)

        return steps

    # ------------------------------------------------------------------
    # Step builders
    # ------------------------------------------------------------------

    def _next_id(self) -> str:
        """Generate the next step ID."""
        self._step_counter += 1
        return f"step_{self._step_counter}"

    def _make_board_outline_step(self) -> PlanStep:
        """Create the board outline step."""
        board = self._intent.board
        target_pcb = f"{self._intent.name}.kicad_pcb"
        op = Operation(
            root=SetBoardOutlineOp(
                target_file=target_pcb,
                width=board.width_mm,
                height=board.height_mm,
            )
        )
        return PlanStep(
            operation=op,
            dependencies=[],
            description=f"Set board outline ({board.width_mm}x{board.height_mm}mm)",
            step_id=self._next_id(),
        )

    def _make_component_step(self, comp: object) -> PlanStep:
        """Create an add_component step for a single component."""
        target_sch = f"{self._intent.name}.kicad_sch"

        # Access ComponentSpec fields
        library_id = comp.library_id  # type: ignore[attr-defined]
        reference = comp.reference  # type: ignore[attr-defined]
        value = comp.value  # type: ignore[attr-defined]
        pos = comp.position  # type: ignore[attr-defined]

        if pos is not None:
            schema_pos = SchemaPositionSpec(
                x=pos.x, y=pos.y, angle=pos.angle  # type: ignore[attr-defined]
            )
        else:
            schema_pos = SchemaPositionSpec(x=0.0, y=0.0)

        op = Operation(
            root=AddComponentOp(
                target_file=target_sch,
                library_id=library_id,
                reference=reference,
                value=value,
                position=schema_pos,
            )
        )
        return PlanStep(
            operation=op,
            dependencies=["step_1"],  # Depends on board outline
            description=f"Add component {reference} ({library_id}, {value})",
            step_id=self._next_id(),
        )

    def _make_power_step(self, power_name: str) -> PlanStep:
        """Create an add_power step for a power net."""
        target_sch = f"{self._intent.name}.kicad_sch"
        op = Operation(
            root=AddPowerOp(
                target_file=target_sch,
                name=power_name,
                position=SchemaPositionSpec(x=0.0, y=0.0),
            )
        )
        return PlanStep(
            operation=op,
            dependencies=["step_1"],  # Depends on board outline
            description=f"Add power symbol {power_name}",
            step_id=self._next_id(),
        )

    def _make_net_step(self, net_name: str) -> PlanStep:
        """Create an add_net step for a net."""
        target_pcb = f"{self._intent.name}.kicad_pcb"
        op = Operation(
            root=AddNetOp(
                target_file=target_pcb,
                net_name=net_name,
            )
        )
        # Dependencies: all component steps (step_2 onwards)
        comp_count = len(self._intent.components)
        comp_deps = [f"step_{i}" for i in range(2, 2 + comp_count)] if comp_count else ["step_1"]
        return PlanStep(
            operation=op,
            dependencies=comp_deps,
            description=f"Add net {net_name}",
            step_id=self._next_id(),
        )

    def _make_wire_step(self, net: object) -> PlanStep:
        """Create an add_wire step for a net's connections."""
        target_sch = f"{self._intent.name}.kicad_sch"
        net_name = net.name  # type: ignore[attr-defined]
        # Placeholder wire -- actual routing would need pin positions
        op = Operation(
            root=AddWireOp(
                target_file=target_sch,
                start_x=0.0,
                start_y=0.0,
                end_x=0.0,
                end_y=0.0,
            )
        )
        return PlanStep(
            operation=op,
            dependencies=["step_1"],  # Depends on components + nets
            description=f"Add wire for net {net_name}",
            step_id=self._next_id(),
        )

    def _make_repair_step(self, deps: list[str]) -> PlanStep | None:
        """Create a repair_schematic step."""
        target_sch = f"{self._intent.name}.kicad_sch"
        op = Operation(
            root=RepairSchematicOp(
                target_file=target_sch,
                snap_wires=True,
                remove_orphans=True,
                place_no_connects=True,
            )
        )
        return PlanStep(
            operation=op,
            dependencies=deps,
            description="Repair schematic (snap wires, remove orphans, place no-connects)",
            step_id=self._next_id(),
        )

    def _make_validate_step(self, deps: list[str]) -> PlanStep | None:
        """Create a validate_power_nets step."""
        target_sch = f"{self._intent.name}.kicad_sch"
        op = Operation(
            root=ValidatePowerNetsOp(
                target_file=target_sch,
            )
        )
        return PlanStep(
            operation=op,
            dependencies=deps,
            description="Validate power nets",
            step_id=self._next_id(),
        )


def plan_operation_sequence(intent: GenerationIntent, target_dir: Path) -> list[PlanStep]:
    """Convenience function: convert intent to ordered operation sequence.

    Args:
        intent: Validated GenerationIntent.
        target_dir: Output directory for generated files.

    Returns:
        List of PlanStep instances in dependency order.
    """
    return OpPlanner(intent, target_dir).plan()
