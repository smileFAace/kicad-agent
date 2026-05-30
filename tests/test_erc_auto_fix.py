"""Tests for ERC auto-fix operations (Phase 35).

Covers:
- update_symbols_from_library
- fix_shorted_nets
- fix_pin_type_mismatches
- place_missing_units
- remove_dangling_wires
- break_wire_shorts
"""

import pytest
from pathlib import Path

from kicad_agent.ops._schema_repair import (
    UpdateSymbolsFromLibraryOp,
    FixShortedNetsOp,
    FixPinTypeMismatchesOp,
    PlaceMissingUnitsOp,
    RemoveDanglingWiresOp,
    BreakWireShortsOp,
)
from kicad_agent.ir.schematic_ir import SchematicIR


FIXTURE_DIR = Path(__file__).parent / "fixtures"
ARDUINO_SCH = FIXTURE_DIR / "Arduino_Mega" / "Arduino_Mega.kicad_sch"


@pytest.fixture
def arduino_ir():
    """Load Arduino Mega schematic as IR."""
    if not ARDUINO_SCH.exists():
        pytest.skip("Arduino_Mega fixture not found")
    from kicad_agent.parser import parse_schematic
    result = parse_schematic(ARDUINO_SCH)
    return SchematicIR(_parse_result=result)


# --- Schema validation tests ---

class TestSchemas:
    def test_update_symbols_defaults(self):
        op = UpdateSymbolsFromLibraryOp(target_file="test.kicad_sch")
        assert op.op_type == "update_symbols_from_library"
        assert op.references is None
        assert op.dry_run is False

    def test_fix_shorted_nets_defaults(self):
        op = FixShortedNetsOp(target_file="test.kicad_sch")
        assert op.strategy == "keep_first"
        assert op.keep_nets is None

    def test_fix_pin_types_defaults(self):
        op = FixPinTypeMismatchesOp(target_file="test.kicad_sch")
        assert op.pin_type_map is None  # Defaults to {"unspecified": "passive"}

    def test_place_missing_units_defaults(self):
        op = PlaceMissingUnitsOp(target_file="test.kicad_sch")
        assert op.offset_x == 25.4
        assert op.offset_y == 0.0

    def test_remove_dangling_wires_defaults(self):
        op = RemoveDanglingWiresOp(target_file="test.kicad_sch")
        assert op.max_length_mm is None

    def test_dry_run_flags(self):
        for Schema in [
            UpdateSymbolsFromLibraryOp,
            FixShortedNetsOp,
            FixPinTypeMismatchesOp,
            PlaceMissingUnitsOp,
            RemoveDanglingWiresOp,
            BreakWireShortsOp,
        ]:
            op = Schema(target_file="test.kicad_sch", dry_run=True)
            assert op.dry_run is True

    def test_update_symbols_with_references(self):
        op = UpdateSymbolsFromLibraryOp(
            target_file="test.kicad_sch",
            references=["U1", "U2"],
        )
        assert op.references == ["U1", "U2"]

    def test_fix_shorted_nets_manual_strategy(self):
        op = FixShortedNetsOp(
            target_file="test.kicad_sch",
            strategy="manual",
            keep_nets=["GND", "VCC"],
        )
        assert op.strategy == "manual"
        assert op.keep_nets == ["GND", "VCC"]

    def test_fix_pin_types_custom_map(self):
        op = FixPinTypeMismatchesOp(
            target_file="test.kicad_sch",
            pin_type_map={"unspecified": "bidirectional"},
        )
        assert op.pin_type_map == {"unspecified": "bidirectional"}

    def test_remove_dangling_max_length(self):
        op = RemoveDanglingWiresOp(
            target_file="test.kicad_sch",
            max_length_mm=5.0,
        )
        assert op.max_length_mm == 5.0

    def test_break_wire_shorts_defaults(self):
        op = BreakWireShortsOp(target_file="test.kicad_sch")
        assert op.op_type == "break_wire_shorts"
        assert op.net_pairs is None
        assert op.strategy == "shortest_path"
        assert op.dry_run is False

    def test_break_wire_shorts_with_pairs(self):
        op = BreakWireShortsOp(
            target_file="test.kicad_sch",
            net_pairs=[["ADC_IN_1", "GND"], ["+3.3V", "VCC_5V"]],
        )
        assert op.net_pairs == [["ADC_IN_1", "GND"], ["+3.3V", "VCC_5V"]]

    def test_break_wire_shorts_all_bridges_strategy(self):
        op = BreakWireShortsOp(
            target_file="test.kicad_sch",
            strategy="all_bridges",
        )
        assert op.strategy == "all_bridges"


# --- Handler integration tests (dry_run) ---

class TestUpdateSymbolsFromLibrary:
    def test_dry_run_no_crash(self, arduino_ir):
        from kicad_agent.ops.repair import update_symbols_from_library
        result = update_symbols_from_library(
            arduino_ir, ARDUINO_SCH,
            dry_run=True,
        )
        assert "updated" in result
        assert "skipped" in result
        assert isinstance(result["updated"], list)
        assert isinstance(result["skipped"], list)


class TestFixPinTypeMismatches:
    def test_dry_run_default_map(self, arduino_ir):
        from kicad_agent.ops.repair import fix_pin_type_mismatches
        result = fix_pin_type_mismatches(
            arduino_ir, ARDUINO_SCH,
            dry_run=True,
        )
        assert "pins_changed" in result
        assert isinstance(result["pins_changed"], list)
        # dry_run should not modify IR
        for p in result["pins_changed"]:
            assert p.get("dry_run") is True

    def test_custom_map_no_match(self, arduino_ir):
        from kicad_agent.ops.repair import fix_pin_type_mismatches
        result = fix_pin_type_mismatches(
            arduino_ir, ARDUINO_SCH,
            pin_type_map={"nonexistent_type": "passive"},
            dry_run=True,
        )
        assert result["total"] == 0


class TestFixShortedNets:
    def test_dry_run_no_crash(self, arduino_ir):
        from kicad_agent.ops.repair import fix_shorted_nets
        result = fix_shorted_nets(
            arduino_ir, ARDUINO_SCH,
            dry_run=True,
        )
        assert "shorts_found" in result
        assert "labels_removed" in result


class TestPlaceMissingUnits:
    def test_dry_run_no_crash(self, arduino_ir):
        from kicad_agent.ops.repair import place_missing_units
        result = place_missing_units(
            arduino_ir, ARDUINO_SCH,
            dry_run=True,
        )
        assert "units_placed" in result
        assert isinstance(result["units_placed"], list)


class TestRemoveDanglingWires:
    def test_dry_run_no_crash(self, arduino_ir):
        from kicad_agent.ops.repair import remove_dangling_wires
        result = remove_dangling_wires(
            arduino_ir, ARDUINO_SCH,
            dry_run=True,
        )
        assert "removed_count" in result
        assert isinstance(result["removed_count"], int)

    def test_with_max_length(self, arduino_ir):
        from kicad_agent.ops.repair import remove_dangling_wires
        result = remove_dangling_wires(
            arduino_ir, ARDUINO_SCH,
            max_length_mm=1.0,
            dry_run=True,
        )
        assert result["removed_count"] >= 0


class TestBreakWireShorts:
    def test_dry_run_no_crash(self, arduino_ir):
        from kicad_agent.ops.repair import break_wire_shorts
        result = break_wire_shorts(
            arduino_ir, ARDUINO_SCH,
            dry_run=True,
        )
        assert "shorts_found" in result
        assert "wires_removed" in result
        assert "details" in result
        assert isinstance(result["shorts_found"], int)
        assert isinstance(result["details"], list)

    def test_no_shorts_returns_clean(self, arduino_ir):
        """With a non-existent pair, should find 0 target shorts."""
        from kicad_agent.ops.repair import break_wire_shorts
        result = break_wire_shorts(
            arduino_ir, ARDUINO_SCH,
            net_pairs=[["NONEXISTENT_A", "NONEXISTENT_B"]],
            dry_run=True,
        )
        assert result["shorts_found"] == 0
        assert result["wires_removed"] == 0

    def test_find_bridge_wires_no_match(self, arduino_ir):
        """find_bridge_wires returns empty for non-existent net pair."""
        from kicad_agent.ops.repair import find_bridge_wires
        result = find_bridge_wires(arduino_ir, "FAKE_NET_A", "FAKE_NET_B")
        assert result == []


# --- Executor dispatch tests ---

class TestExecutorDispatch:
    def test_all_registered(self):
        from kicad_agent.ops.executor import _SCHEMATIC_HANDLERS
        ops = [
            "update_symbols_from_library",
            "fix_shorted_nets",
            "fix_pin_type_mismatches",
            "place_missing_units",
            "remove_dangling_wires",
            "break_wire_shorts",
        ]
        for op_type in ops:
            assert op_type in _SCHEMATIC_HANDLERS, f"{op_type} not registered"
