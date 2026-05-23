"""Tests for GenerationIntent schema and intent_to_operations converter.

Covers:
- GenerationIntent creation with components and nets
- Default values for minimal intent
- intent_to_operations conversion for components, nets, and power
- JSON schema export for LLM consumption
- Auto-reference assignment for component specs
"""

from kicad_agent.generation.intent import (
    BoardSpec,
    ComponentSpec,
    GenerationIntent,
    NetSpec,
    PowerSpec,
    PositionSpec,
    intent_to_operations,
)
from kicad_agent.ops.schema import AddComponentOp, AddNetOp, AddPowerOp


class TestGenerationIntentCreation:
    """Test GenerationIntent model creation and field validation."""

    def test_generation_intent_with_components_and_nets(self):
        """Create GenerationIntent with components and nets, verify all fields."""
        intent = GenerationIntent(
            name="Motor Driver",
            description="Dual H-bridge motor driver",
            board=BoardSpec(width_mm=100.0, height_mm=80.0),
            components=[
                ComponentSpec(
                    library_id="Device:R_Small_US",
                    reference="R1",
                    value="10k",
                    position=PositionSpec(x=25.0, y=30.0),
                ),
                ComponentSpec(
                    library_id="Device:C_Small",
                    reference="C1",
                    value="100nF",
                ),
            ],
            nets=[
                NetSpec(name="SDA", pins=["R1.1", "U1.3"]),
                NetSpec(name="SCL", pins=["R1.2", "U1.4"]),
            ],
            power=PowerSpec(nets=["GND", "+3V3", "+5V"]),
            design_rules={"min_clearance": 0.2, "default_width": 0.25},
        )

        assert intent.name == "Motor Driver"
        assert intent.description == "Dual H-bridge motor driver"
        assert intent.board.width_mm == 100.0
        assert intent.board.height_mm == 80.0
        assert len(intent.components) == 2
        assert len(intent.nets) == 2
        assert len(intent.power.nets) == 3
        assert intent.design_rules["min_clearance"] == 0.2

        # Component details
        assert intent.components[0].library_id == "Device:R_Small_US"
        assert intent.components[0].reference == "R1"
        assert intent.components[0].value == "10k"
        assert intent.components[0].position is not None
        assert intent.components[0].position.x == 25.0

        # Net details
        assert intent.nets[0].name == "SDA"
        assert intent.nets[0].pins == ["R1.1", "U1.3"]

    def test_generation_intent_defaults(self):
        """Create minimal intent (just name), verify defaults."""
        intent = GenerationIntent(name="Test Board")

        assert intent.name == "Test Board"
        assert intent.description == ""
        assert intent.board.width_mm == 50.0
        assert intent.board.height_mm == 50.0
        assert intent.board.layer_count == 2
        assert intent.board.thickness_mm == 1.6
        assert intent.board.edge_connector is False
        assert intent.components == []
        assert intent.nets == []
        assert intent.power.nets == ["GND", "+3V3"]
        assert intent.design_rules == {}


class TestIntentToOperations:
    """Test intent_to_operations conversion function."""

    def test_intent_to_operations_components(self):
        """Intent with 3 components converts to 3 AddComponentOp."""
        intent = GenerationIntent(
            name="Test",
            components=[
                ComponentSpec(
                    library_id="Device:R_Small_US",
                    reference="R1",
                    value="10k",
                    position=PositionSpec(x=10.0, y=20.0),
                ),
                ComponentSpec(
                    library_id="Device:C_Small",
                    reference="C1",
                    value="100nF",
                    position=PositionSpec(x=30.0, y=20.0),
                ),
                ComponentSpec(
                    library_id="Device:LED",
                    reference="D1",
                    value="Red",
                    position=PositionSpec(x=50.0, y=20.0),
                ),
            ],
            power=PowerSpec(nets=[]),
        )

        ops = intent_to_operations(intent)
        assert len(ops) == 3

        for i, op in enumerate(ops):
            assert isinstance(op.root, AddComponentOp)
            assert op.root.op_type == "add_component"
            assert op.root.target_file == "design.kicad_sch"
            assert op.root.reference == intent.components[i].reference
            assert op.root.value == intent.components[i].value

        # Verify positions are preserved
        assert ops[0].root.position.x == 10.0
        assert ops[1].root.position.x == 30.0
        assert ops[2].root.position.x == 50.0

    def test_intent_to_operations_nets(self):
        """Intent with 2 nets produces AddNetOp operations."""
        intent = GenerationIntent(
            name="Test",
            nets=[
                NetSpec(name="SDA", pins=["R1.1", "U1.3"]),
                NetSpec(name="SCL", pins=["R1.2", "U1.4"]),
            ],
            power=PowerSpec(nets=[]),
        )

        ops = intent_to_operations(intent)
        assert len(ops) == 2

        for op in ops:
            assert isinstance(op.root, AddNetOp)
            assert op.root.op_type == "add_net"
            assert op.root.target_file == "design.kicad_pcb"

        assert ops[0].root.net_name == "SDA"
        assert ops[1].root.net_name == "SCL"

    def test_intent_to_operations_power(self):
        """Intent with power spec produces AddPowerOp for each power net."""
        intent = GenerationIntent(
            name="Test",
            power=PowerSpec(nets=["GND", "+5V", "+3V3"]),
        )

        ops = intent_to_operations(intent)
        assert len(ops) == 3

        for op in ops:
            assert isinstance(op.root, AddPowerOp)
            assert op.root.op_type == "add_power"

        assert ops[0].root.name == "GND"
        assert ops[1].root.name == "+5V"
        assert ops[2].root.name == "+3V3"

    def test_intent_to_operations_full(self):
        """Full intent with board, components, nets, power produces complete sequence."""
        intent = GenerationIntent(
            name="Full Test",
            components=[
                ComponentSpec(
                    library_id="Device:R_Small_US",
                    reference="R1",
                    value="10k",
                    position=PositionSpec(x=10.0, y=10.0),
                ),
            ],
            nets=[NetSpec(name="SDA", pins=["R1.1"])],
            power=PowerSpec(nets=["GND"]),
        )

        ops = intent_to_operations(intent)
        # 1 component + 1 net + 1 power = 3 operations
        assert len(ops) == 3

        # Order: components first, then nets, then power
        assert isinstance(ops[0].root, AddComponentOp)
        assert isinstance(ops[1].root, AddNetOp)
        assert isinstance(ops[2].root, AddPowerOp)

    def test_intent_to_operations_custom_targets(self):
        """intent_to_operations accepts custom target filenames."""
        intent = GenerationIntent(
            name="Custom",
            components=[
                ComponentSpec(
                    library_id="Device:R",
                    reference="R1",
                    position=PositionSpec(x=0.0, y=0.0),
                ),
            ],
        )

        ops = intent_to_operations(
            intent,
            target_sch="my_design.kicad_sch",
            target_pcb="my_design.kicad_pcb",
        )

        assert ops[0].root.target_file == "my_design.kicad_sch"

    def test_intent_to_operations_empty(self):
        """Empty intent (no components, nets, or power) produces empty operation list."""
        intent = GenerationIntent(name="Empty", power=PowerSpec(nets=[]))
        ops = intent_to_operations(intent)
        assert ops == []


class TestGenerationIntentSchema:
    """Test JSON schema export and validation."""

    def test_generation_intent_json_schema(self):
        """Export JSON schema, verify it's valid and contains all fields."""
        schema = GenerationIntent.model_json_schema()

        assert isinstance(schema, dict)
        assert "properties" in schema
        props = schema["properties"]

        # All top-level fields present
        assert "name" in props
        assert "description" in props
        assert "board" in props
        assert "components" in props
        assert "nets" in props
        assert "power" in props
        assert "design_rules" in props

        # BoardSpec sub-schema
        board_props = props["board"].get("properties", {})
        if not board_props:
            # May be a $ref
            assert "$ref" in props["board"] or "anyOf" in props["board"] or "allOf" in props["board"]

    def test_component_spec_auto_reference(self):
        """Component with reference='R?' verifies auto-assignable."""
        comp = ComponentSpec(library_id="Device:R_Small_US", reference="R?")
        assert comp.reference == "R?"
        assert comp.reference.endswith("?")

    def test_component_spec_default_reference(self):
        """Component without explicit reference gets default 'U?'."""
        comp = ComponentSpec(library_id="Device:R_Small_US")
        assert comp.reference == "U?"

    def test_board_spec_validation(self):
        """BoardSpec rejects out-of-bounds dimensions."""
        import pytest

        with pytest.raises(Exception):
            BoardSpec(width_mm=0.0)

        with pytest.raises(Exception):
            BoardSpec(width_mm=501.0)

        with pytest.raises(Exception):
            BoardSpec(height_mm=-10.0)

        with pytest.raises(Exception):
            BoardSpec(layer_count=0)

        with pytest.raises(Exception):
            BoardSpec(layer_count=33)

    def test_net_spec_pin_format_validation(self):
        """NetSpec rejects pins without dot separator."""
        import pytest

        with pytest.raises(Exception):
            NetSpec(name="SDA", pins=["invalid_no_dot"])

    def test_component_spec_unsafe_library_id(self):
        """ComponentSpec rejects unsafe characters in library_id."""
        import pytest

        with pytest.raises(Exception):
            ComponentSpec(library_id="Library; DROP TABLE", reference="R1")
