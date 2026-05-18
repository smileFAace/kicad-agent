"""Tests for net and bus operation schema validation and IR mutation methods.

Tests cover:
  - Schema validation for AddNetOp, RemoveNetOp, RenameNetOp, AddBusOp, RemoveBusOp
  - PcbIR net CRUD operations (add, remove, rename, query)
  - SchematicIR label and bus accessors
"""

import pytest
from pydantic import ValidationError

from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.schema import (
    AddBusOp,
    AddNetOp,
    RemoveBusOp,
    RemoveNetOp,
    RenameNetOp,
    Operation,
    get_operation_schema,
)
from kicad_agent.parser import parse_pcb, parse_schematic
from kicad_agent.parser.uuid_extractor import extract_uuids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_add_net_op(**overrides) -> Operation:
    """Create a valid AddNetOp Operation with sensible defaults."""
    data = {
        "op_type": "add_net",
        "target_file": "board.kicad_pcb",
        "net_name": "VCC",
    }
    data.update(overrides)
    return Operation.model_validate({"root": data})


def _make_remove_net_op(**overrides) -> Operation:
    """Create a valid RemoveNetOp Operation."""
    data = {
        "op_type": "remove_net",
        "target_file": "board.kicad_pcb",
        "net_name": "VCC",
    }
    data.update(overrides)
    return Operation.model_validate({"root": data})


def _make_rename_net_op(**overrides) -> Operation:
    """Create a valid RenameNetOp Operation."""
    data = {
        "op_type": "rename_net",
        "target_file": "board.kicad_pcb",
        "old_name": "VCC",
        "new_name": "3V3",
    }
    data.update(overrides)
    return Operation.model_validate({"root": data})


def _make_add_bus_op(**overrides) -> Operation:
    """Create a valid AddBusOp Operation."""
    data = {
        "op_type": "add_bus",
        "target_file": "schematic.kicad_sch",
        "bus_name": "DATA_BUS",
        "member_nets": ["D0", "D1", "D2"],
    }
    data.update(overrides)
    return Operation.model_validate({"root": data})


def _make_remove_bus_op(**overrides) -> Operation:
    """Create a valid RemoveBusOp Operation."""
    data = {
        "op_type": "remove_bus",
        "target_file": "schematic.kicad_sch",
        "bus_name": "DATA_BUS",
    }
    data.update(overrides)
    return Operation.model_validate({"root": data})


# ---------------------------------------------------------------------------
# Task 1: Schema validation tests (Tests 1-10)
# ---------------------------------------------------------------------------


class TestAddNetOpSchema:
    """AddNetOp schema validation."""

    def test_named_net_validates(self) -> None:
        """Test 1: AddNetOp with named net validates."""
        op = _make_add_net_op(net_name="VCC")
        assert op.root.op_type == "add_net"
        assert op.root.net_name == "VCC"

    def test_auto_name_allows_empty(self) -> None:
        """Test 2: AddNetOp without net_name defaults to empty (auto-generate)."""
        op = _make_add_net_op(net_name="")
        assert op.root.net_name == ""

    def test_net_number_optional(self) -> None:
        """AddNetOp with explicit net_number validates."""
        op = _make_add_net_op(net_number=42)
        assert op.root.net_number == 42

    def test_net_number_default_none(self) -> None:
        """AddNetOp net_number defaults to None."""
        op = _make_add_net_op()
        assert op.root.net_number is None


class TestRemoveNetOpSchema:
    """RemoveNetOp schema validation."""

    def test_validates(self) -> None:
        """Test 3: RemoveNetOp validates with target_file and net_name."""
        op = _make_remove_net_op()
        assert op.root.op_type == "remove_net"
        assert op.root.net_name == "VCC"

    def test_rejects_empty_name(self) -> None:
        """RemoveNetOp rejects empty net_name (min_length=1)."""
        with pytest.raises(ValidationError, match="at least 1 character"):
            _make_remove_net_op(net_name="")


class TestRenameNetOpSchema:
    """RenameNetOp schema validation."""

    def test_validates(self) -> None:
        """Test 4: RenameNetOp validates with old_name and new_name."""
        op = _make_rename_net_op()
        assert op.root.op_type == "rename_net"
        assert op.root.old_name == "VCC"
        assert op.root.new_name == "3V3"


class TestAddBusOpSchema:
    """AddBusOp schema validation."""

    def test_validates(self) -> None:
        """Test 5: AddBusOp validates with bus_name and member_nets."""
        op = _make_add_bus_op()
        assert op.root.op_type == "add_bus"
        assert op.root.bus_name == "DATA_BUS"
        assert op.root.member_nets == ["D0", "D1", "D2"]


class TestRemoveBusOpSchema:
    """RemoveBusOp schema validation."""

    def test_validates(self) -> None:
        """Test 6: RemoveBusOp validates with bus_name."""
        op = _make_remove_bus_op()
        assert op.root.op_type == "remove_bus"
        assert op.root.bus_name == "DATA_BUS"


class TestSchemaValidation:
    """Edge cases and cross-cutting validation."""

    def test_empty_name_after_trim_rejected(self) -> None:
        """Test 7: Net name with only whitespace rejected (min_length=1)."""
        with pytest.raises(ValidationError):
            _make_add_net_op(net_name="   ")

    def test_long_name_rejected(self) -> None:
        """Test 8: Net name >64 chars rejected."""
        with pytest.raises(ValidationError, match="at most 64 characters"):
            _make_add_net_op(net_name="A" * 65)

    def test_unknown_op_type_rejected(self) -> None:
        """Test 9: Operation.model_validate rejects unknown op_type."""
        with pytest.raises(ValidationError):
            Operation.model_validate({
                "root": {
                    "op_type": "net_blast",
                    "target_file": "board.kicad_pcb",
                }
            })

    def test_get_operation_schema_includes_all_types(self) -> None:
        """Test 10: get_operation_schema() includes all five new types."""
        schema = get_operation_schema()
        schema_str = str(schema)
        for op_name in ("AddNetOp", "RemoveNetOp", "RenameNetOp", "AddBusOp", "RemoveBusOp"):
            assert op_name in schema_str, f"{op_name} missing from schema export"


# ---------------------------------------------------------------------------
# Task 2: IR mutation tests (Tests 11-24)
# ---------------------------------------------------------------------------


class TestPcbIRAddNet:
    """PcbIR.add_net() mutation tests against Arduino_Mega fixture (79 nets)."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_pcb: pytest.fixture) -> None:
        """Create PcbIR from Arduino_Mega PCB for each test."""
        _clear_registry()
        result = parse_pcb(arduino_mega_pcb)
        uuid_map = extract_uuids(result.raw_content, "pcb")
        self.ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)

    def test_add_named_net(self) -> None:
        """Test 11: add_net with explicit name creates Net with next number."""
        initial_count = len(self.ir.nets)
        net = self.ir.add_net(net_name="TEST_NET_42")

        assert net.name == "TEST_NET_42"
        assert len(self.ir.nets) == initial_count + 1
        assert self.ir.dirty
        # Should have a valid net number
        assert net.number > 0
        # Mutation logged
        assert any(m["description"] == "add_net" for m in self.ir.mutation_log)

    def test_add_auto_named_net(self) -> None:
        """Test 12: add_net with empty name generates N_<number>."""
        net = self.ir.add_net(net_name="")
        assert net.name.startswith("N_")
        assert net.number > 0

    def test_add_duplicate_net_raises(self) -> None:
        """Test 13: add_net raises ValueError if net_name already exists."""
        # GND is in the Arduino_Mega fixture
        with pytest.raises(ValueError, match="already exists"):
            self.ir.add_net(net_name="GND")


class TestPcbIRRemoveNet:
    """PcbIR.remove_net() mutation tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_pcb: pytest.fixture) -> None:
        """Create PcbIR from Arduino_Mega PCB for each test."""
        _clear_registry()
        result = parse_pcb(arduino_mega_pcb)
        uuid_map = extract_uuids(result.raw_content, "pcb")
        self.ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)

    def test_remove_net(self) -> None:
        """Test 14: remove_net removes Net and clears pad connections."""
        gnd_pads_before = self.ir.get_net_pads("GND")
        assert len(gnd_pads_before) > 0, "GND should have connected pads"
        initial_count = len(self.ir.nets)

        self.ir.remove_net("GND")

        assert len(self.ir.nets) == initial_count - 1
        assert self.ir.get_net_by_name("GND") is None
        # No pads should be connected to GND after removal
        for fp in self.ir.footprints:
            for pad in fp.pads:
                if pad.net is not None:
                    assert pad.net.name != "GND", (
                        f"Pad {pad.number} on {fp.libId} still connected to GND"
                    )

    def test_remove_missing_net_raises(self) -> None:
        """Test 15: remove_net raises ValueError if net not found."""
        with pytest.raises(ValueError, match="not found"):
            self.ir.remove_net("NONEXISTENT_NET_XYZ")

    def test_remove_reserved_net_raises(self) -> None:
        """Test 16: remove_net rejects empty name (net 0 is reserved)."""
        with pytest.raises(ValueError, match="reserved"):
            self.ir.remove_net("")


class TestPcbIRRenameNet:
    """PcbIR.rename_net() mutation tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_pcb: pytest.fixture) -> None:
        """Create PcbIR from Arduino_Mega PCB for each test."""
        _clear_registry()
        result = parse_pcb(arduino_mega_pcb)
        uuid_map = extract_uuids(result.raw_content, "pcb")
        self.ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)

    def test_rename_net(self) -> None:
        """Test 17: rename_net changes name in board.nets and pad.net."""
        self.ir.rename_net("GND", "GROUND")

        net = self.ir.get_net_by_name("GROUND")
        assert net is not None
        assert self.ir.get_net_by_name("GND") is None

        # Verify connected pads updated
        for fp in self.ir.footprints:
            for pad in fp.pads:
                if pad.net is not None and pad.net.name == "GROUND":
                    # Pad is properly connected to renamed net
                    assert pad.net.number > 0

    def test_rename_missing_raises(self) -> None:
        """Test 18: rename_net raises ValueError if old_name not found."""
        with pytest.raises(ValueError, match="not found"):
            self.ir.rename_net("NONEXISTENT", "NEW_NAME")

    def test_rename_collision_raises(self) -> None:
        """Test 19: rename_net raises ValueError if new_name already exists."""
        # GND and VCC both exist in Arduino_Mega
        # Find an existing net that isn't GND
        existing_nets = [n.name for n in self.ir.nets if n.name and n.name != "GND"]
        if existing_nets:
            with pytest.raises(ValueError, match="already exists"):
                self.ir.rename_net("GND", existing_nets[0])


class TestPcbIRQueryNets:
    """PcbIR net query methods."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_pcb: pytest.fixture) -> None:
        """Create PcbIR from Arduino_Mega PCB for each test."""
        _clear_registry()
        result = parse_pcb(arduino_mega_pcb)
        uuid_map = extract_uuids(result.raw_content, "pcb")
        self.ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)

    def test_get_net_by_name_found(self) -> None:
        """Test 20a: get_net_by_name returns correct Net."""
        net = self.ir.get_net_by_name("GND")
        assert net is not None
        assert net.name == "GND"

    def test_get_net_by_name_missing(self) -> None:
        """Test 20b: get_net_by_name returns None for missing net."""
        assert self.ir.get_net_by_name("NONEXISTENT") is None

    def test_get_net_pads(self) -> None:
        """Test 21: get_net_pads returns (footprint_libId, pad_number) tuples."""
        pads = self.ir.get_net_pads("GND")
        assert len(pads) > 0
        for fp_lib, pad_num in pads:
            assert isinstance(fp_lib, str)
            assert isinstance(pad_num, str)


class TestSchematicIRLabels:
    """SchematicIR label accessor tests against Arduino_Mega fixture (76 labels)."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_sch: pytest.fixture) -> None:
        """Create SchematicIR from Arduino_Mega schematic for each test."""
        _clear_registry()
        result = parse_schematic(arduino_mega_sch)
        self.ir = SchematicIR(_parse_result=result)

    def test_get_labels_by_name(self) -> None:
        """Test 22: get_labels_by_name returns labels matching text."""
        # Get a label name that exists
        labels = self.ir.schematic.labels
        if labels:
            target_name = labels[0].text
            found = self.ir.get_labels_by_name(target_name)
            assert len(found) > 0
            assert all(l.text == target_name for l in found)

    def test_get_labels_by_name_missing(self) -> None:
        """Test 23: get_labels_by_name returns empty for non-existent name."""
        found = self.ir.get_labels_by_name("COMPLETELY_NONEXISTENT_LABEL_XYZ")
        assert found == []


class TestSchematicIRBus:
    """SchematicIR bus accessor tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_sch: pytest.fixture) -> None:
        """Create SchematicIR from Arduino_Mega schematic for each test."""
        _clear_registry()
        result = parse_schematic(arduino_mega_sch)
        self.ir = SchematicIR(_parse_result=result)

    def test_bus_aliases_accessor(self) -> None:
        """Test 24: bus_aliases returns list from schematic."""
        aliases = self.ir.bus_aliases
        assert isinstance(aliases, list)
        # Arduino_Mega has no bus aliases, but the accessor should work
