"""Tests for operation-sequence planner.

GEN-09: Validates that the OpPlanner converts GenerationIntent into
dependency-ordered PlanSteps with correct operation types and ordering.
"""

from pathlib import Path

import pytest

from kicad_agent.generation.intent import (
    BoardSpec,
    ComponentSpec,
    GenerationIntent,
    NetSpec,
    PowerSpec,
)
from kicad_agent.generation.op_planner import OpPlanner, PlanStep, plan_operation_sequence
from kicad_agent.ops.schema import Operation


def _make_intent(
    components: list[ComponentSpec] | None = None,
    nets: list[NetSpec] | None = None,
    power: PowerSpec | None = None,
    name: str = "TestBoard",
) -> GenerationIntent:
    """Helper to create a GenerationIntent with sensible defaults."""
    return GenerationIntent(
        name=name,
        board=BoardSpec(width_mm=50, height_mm=50),
        components=components or [],
        nets=nets or [],
        power=power or PowerSpec(nets=["GND", "+3V3"]),
    )


# ---------------------------------------------------------------------------
# Basic planning
# ---------------------------------------------------------------------------


class TestPlanBasic:
    """Tests for basic plan generation."""

    def test_plan_empty_intent(self):
        """Intent with no components -- board outline step present."""
        intent = _make_intent()
        steps = plan_operation_sequence(intent, Path("/tmp"))
        # Should have at minimum: board outline + power symbols + repair + validate
        assert len(steps) >= 1
        # First step is always board outline
        assert steps[0].description.startswith("Set board outline")
        assert steps[0].dependencies == []

    def test_plan_with_components(self):
        """Intent with 3 components -- add_component steps present."""
        components = [
            ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
            ComponentSpec(library_id="Device:C_Small", reference="C1", value="100nF"),
            ComponentSpec(library_id="MCU:ATmega328P", reference="U1", value="ATmega328"),
        ]
        intent = _make_intent(components=components)
        steps = plan_operation_sequence(intent, Path("/tmp"))

        comp_steps = [
            s for s in steps
            if s.operation.root.op_type == "add_component"
        ]
        assert len(comp_steps) == 3

    def test_plan_with_nets(self):
        """Intent with 2 nets -- add_net steps after components."""
        components = [
            ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
            ComponentSpec(library_id="Device:R_Small_US", reference="R2", value="4.7k"),
        ]
        nets = [
            NetSpec(name="SDA", pins=["R1.1", "R2.1"]),
            NetSpec(name="SCL", pins=["R1.2", "R2.2"]),
        ]
        intent = _make_intent(components=components, nets=nets)
        steps = plan_operation_sequence(intent, Path("/tmp"))

        net_steps = [
            s for s in steps
            if s.operation.root.op_type == "add_net"
        ]
        assert len(net_steps) == 2

        # Net steps should come after component steps
        comp_indices = [
            i for i, s in enumerate(steps)
            if s.operation.root.op_type == "add_component"
        ]
        net_indices = [
            i for i, s in enumerate(steps)
            if s.operation.root.op_type == "add_net"
        ]
        if comp_indices and net_indices:
            assert max(comp_indices) < min(net_indices)

    def test_plan_with_power(self):
        """Intent with power spec -- add_power steps present."""
        power = PowerSpec(nets=["GND", "+5V"])
        intent = _make_intent(power=power)
        steps = plan_operation_sequence(intent, Path("/tmp"))

        power_steps = [
            s for s in steps
            if s.operation.root.op_type == "add_power"
        ]
        assert len(power_steps) == 2
        # Verify power names
        power_names = {s.operation.root.name for s in power_steps}
        assert power_names == {"GND", "+5V"}


# ---------------------------------------------------------------------------
# Dependency ordering
# ---------------------------------------------------------------------------


class TestPlanDependencyOrder:
    """Tests for dependency ordering enforcement."""

    def test_plan_dependency_order(self):
        """Verify board outline < components < nets < wires < repair."""
        components = [
            ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
        ]
        nets = [
            NetSpec(name="SDA", pins=["R1.1"]),
        ]
        intent = _make_intent(components=components, nets=nets)
        steps = plan_operation_sequence(intent, Path("/tmp"))

        # Collect indices by operation type
        type_indices: dict[str, list[int]] = {}
        for i, step in enumerate(steps):
            op_type = step.operation.root.op_type
            type_indices.setdefault(op_type, []).append(i)

        # Verify ordering
        def first_index(op_type: str) -> float:
            return min(type_indices.get(op_type, [float("inf")]))

        # Board outline must come first
        assert first_index("set_board_outline") < first_index("add_component")
        # Components before nets
        assert first_index("add_component") < first_index("add_net")
        # Nets before wires
        if "add_wire" in type_indices:
            assert first_index("add_net") < first_index("add_wire")
        # Repair after wires
        if "add_wire" in type_indices and "repair_schematic" in type_indices:
            assert first_index("add_wire") < first_index("repair_schematic")

    def test_plan_step_has_operation(self):
        """Each PlanStep has a valid Operation object."""
        intent = _make_intent(
            components=[
                ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
            ],
            nets=[NetSpec(name="SDA", pins=["R1.1"])],
        )
        steps = plan_operation_sequence(intent, Path("/tmp"))

        for step in steps:
            assert isinstance(step, PlanStep)
            assert isinstance(step.operation, Operation)
            assert step.operation.root.op_type  # Has a valid op_type
            assert step.step_id  # Has a step ID
            assert isinstance(step.dependencies, list)
            assert isinstance(step.description, str)


# ---------------------------------------------------------------------------
# Repair and validation
# ---------------------------------------------------------------------------


class TestPlanRepairValidation:
    """Tests for repair and validation steps."""

    def test_plan_with_repair(self):
        """Repair step should be present at end of plan."""
        intent = _make_intent(
            components=[
                ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
            ],
        )
        steps = plan_operation_sequence(intent, Path("/tmp"))

        repair_steps = [
            s for s in steps
            if s.operation.root.op_type == "repair_schematic"
        ]
        assert len(repair_steps) == 1
        repair_step = repair_steps[0]
        # Repair should have dependencies on prior steps
        assert len(repair_step.dependencies) > 0

    def test_plan_full_intent(self):
        """Full GenerationIntent -- all step types present in correct order."""
        components = [
            ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
            ComponentSpec(library_id="MCU:ATmega328P", reference="U1", value="ATmega328"),
        ]
        nets = [
            NetSpec(name="SDA", pins=["R1.1", "U1.3"]),
            NetSpec(name="SCL", pins=["R1.2", "U1.4"]),
        ]
        power = PowerSpec(nets=["GND", "+3V3"])
        intent = _make_intent(components=components, nets=nets, power=power)
        steps = plan_operation_sequence(intent, Path("/tmp"))

        # Collect op types in order
        op_types = [s.operation.root.op_type for s in steps]

        # Must contain all expected step types
        assert "set_board_outline" in op_types
        assert "add_component" in op_types
        assert "add_net" in op_types
        assert "add_power" in op_types
        assert "repair_schematic" in op_types
        assert "validate_power_nets" in op_types

        # Board outline is first
        assert op_types[0] == "set_board_outline"
        # Validate is last
        assert op_types[-1] == "validate_power_nets"
