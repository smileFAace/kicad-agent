"""Tests for library reference propagation -- XFILE-02, XFILE-03.

Covers:
- propagate_symbol_ref updates matching components in Arduino_Mega schematic
- propagate_symbol_ref returns correct matched_count and updated_count
- propagate_symbol_ref sets dirty flag on SchematicIR
- propagate_symbol_ref records mutation in mutation_log
- propagate_symbol_ref with non-matching old_lib_id returns count=0
- propagate_symbol_ref with identical old/new returns count=0
- propagate_symbol_ref with empty string raises ValueError
- propagate_footprint_ref updates matching footprints in Arduino_Mega PCB
- propagate_footprint_ref returns correct counts
- propagate_footprint_ref sets dirty flag on PcbIR
- propagate_footprint_ref records mutation in mutation_log
- propagate_footprint_ref with non-matching ref returns count=0
- propagate_footprint_ref with empty string raises ValueError
"""

from pathlib import Path

import pytest

from kicad_agent.crossfile.propagation import (
    PropagationResult,
    propagate_footprint_ref,
    propagate_symbol_ref,
)
from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.parser import parse_pcb, parse_schematic
from kicad_agent.parser.uuid_extractor import extract_uuids


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the IR registry before and after each test to avoid collisions."""
    _clear_registry()
    yield
    _clear_registry()


@pytest.fixture
def schematic_ir(arduino_mega_sch: Path) -> SchematicIR:
    """Parse the Arduino Mega schematic and return a SchematicIR."""
    result = parse_schematic(arduino_mega_sch)
    return SchematicIR(_parse_result=result)


@pytest.fixture
def pcb_ir(arduino_mega_pcb: Path) -> PcbIR:
    """Parse the Arduino Mega PCB and return a PcbIR."""
    result = parse_pcb(arduino_mega_pcb)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    return PcbIR(_parse_result=result, _uuid_map=uuid_map)


# ---------------------------------------------------------------------------
# Symbol Propagation Tests
# ---------------------------------------------------------------------------


class TestSymbolPropagation:
    """Tests for propagate_symbol_ref on SchematicIR."""

    def test_updates_matching_components(self, schematic_ir: SchematicIR) -> None:
        """propagate_symbol_ref updates libId on matching components."""
        # Arduino_Mega has Connector_Generic:Conn_01x08 components
        old_id = "Connector_Generic:Conn_01x08"
        new_id = "MyConnector:Conn_01x08"
        result = propagate_symbol_ref(schematic_ir, old_id, new_id)

        # Verify libId was changed on matching components
        for comp in schematic_ir.components:
            if comp.libId == new_id:
                pass  # Good -- it was updated
            elif comp.libId == old_id:
                pytest.fail(f"Component with libId={old_id} was not updated")
            # else: unrelated component, fine

    def test_returns_correct_counts(self, schematic_ir: SchematicIR) -> None:
        """propagate_symbol_ref returns accurate matched_count and updated_count."""
        old_id = "Connector_Generic:Conn_01x08"
        new_id = "MyConnector:Conn_01x08"

        # Count expected matches
        expected = sum(1 for c in schematic_ir.components if c.libId == old_id)
        assert expected > 0, "Precondition: at least one matching component"

        result = propagate_symbol_ref(schematic_ir, old_id, new_id)
        assert isinstance(result, PropagationResult)
        assert result.matched_count == expected
        assert result.updated_count == expected

    def test_sets_dirty_flag(self, schematic_ir: SchematicIR) -> None:
        """propagate_symbol_ref sets dirty flag on SchematicIR."""
        assert not schematic_ir.dirty  # precondition
        old_id = "Connector_Generic:Conn_01x08"
        new_id = "MyConnector:Conn_01x08"
        propagate_symbol_ref(schematic_ir, old_id, new_id)
        assert schematic_ir.dirty

    def test_records_mutation(self, schematic_ir: SchematicIR) -> None:
        """propagate_symbol_ref records mutation in mutation_log."""
        assert len(schematic_ir.mutation_log) == 0  # precondition
        old_id = "Connector_Generic:Conn_01x08"
        new_id = "MyConnector:Conn_01x08"
        propagate_symbol_ref(schematic_ir, old_id, new_id)
        assert len(schematic_ir.mutation_log) == 1
        entry = schematic_ir.mutation_log[0]
        assert entry["description"] == "propagate_symbol_ref"
        assert entry["old_lib_id"] == old_id
        assert entry["new_lib_id"] == new_id
        assert entry["updated_count"] > 0

    def test_non_matching_returns_zero(self, schematic_ir: SchematicIR) -> None:
        """propagate_symbol_ref with non-matching old_lib_id returns count=0."""
        result = propagate_symbol_ref(
            schematic_ir, "NonExistent:Symbol", "NewLib:Symbol"
        )
        assert result.matched_count == 0
        assert result.updated_count == 0
        assert not schematic_ir.dirty

    def test_identical_old_new_returns_zero(self, schematic_ir: SchematicIR) -> None:
        """propagate_symbol_ref with identical old/new returns count=0."""
        result = propagate_symbol_ref(
            schematic_ir,
            "Connector_Generic:Conn_01x08",
            "Connector_Generic:Conn_01x08",
        )
        assert result.matched_count == 0
        assert result.updated_count == 0
        assert not schematic_ir.dirty

    def test_empty_string_raises_valueerror(self, schematic_ir: SchematicIR) -> None:
        """propagate_symbol_ref with empty string raises ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            propagate_symbol_ref(schematic_ir, "", "NewLib:Symbol")

        with pytest.raises(ValueError, match="non-empty"):
            propagate_symbol_ref(schematic_ir, "OldLib:Symbol", "")

    def test_file_path_in_result(
        self, schematic_ir: SchematicIR, arduino_mega_sch: Path
    ) -> None:
        """PropagationResult contains the file_path from the IR."""
        old_id = "Connector_Generic:Conn_01x08"
        new_id = "MyConnector:Conn_01x08"
        result = propagate_symbol_ref(schematic_ir, old_id, new_id)
        assert result.file_path == arduino_mega_sch


# ---------------------------------------------------------------------------
# Footprint Propagation Tests
# ---------------------------------------------------------------------------


class TestFootprintPropagation:
    """Tests for propagate_footprint_ref on PcbIR."""

    def test_updates_matching_footprints(self, pcb_ir: PcbIR) -> None:
        """propagate_footprint_ref updates libraryNickname/entryName on matching footprints."""
        # Arduino_Mega has Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical
        old_ref = "Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical"
        new_ref = "MySocket:PinSocket_1x08_P2.54mm_Vertical"
        result = propagate_footprint_ref(pcb_ir, old_ref, new_ref)

        # Verify the footprints were updated
        for fp in pcb_ir.footprints:
            combined = f"{fp.libraryNickname}:{fp.entryName}"
            assert combined != old_ref, f"Footprint still has old ref: {combined}"

    def test_returns_correct_counts(self, pcb_ir: PcbIR) -> None:
        """propagate_footprint_ref returns accurate counts."""
        old_ref = "Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical"
        new_ref = "MySocket:PinSocket_1x08_P2.54mm_Vertical"

        # Count expected matches
        expected = sum(
            1
            for fp in pcb_ir.footprints
            if f"{fp.libraryNickname}:{fp.entryName}" == old_ref
        )
        assert expected > 0, "Precondition: at least one matching footprint"

        result = propagate_footprint_ref(pcb_ir, old_ref, new_ref)
        assert isinstance(result, PropagationResult)
        assert result.matched_count == expected
        assert result.updated_count == expected

    def test_sets_dirty_flag(self, pcb_ir: PcbIR) -> None:
        """propagate_footprint_ref sets dirty flag on PcbIR."""
        assert not pcb_ir.dirty  # precondition
        old_ref = "Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical"
        new_ref = "MySocket:PinSocket_1x08_P2.54mm_Vertical"
        propagate_footprint_ref(pcb_ir, old_ref, new_ref)
        assert pcb_ir.dirty

    def test_records_mutation(self, pcb_ir: PcbIR) -> None:
        """propagate_footprint_ref records mutation in mutation_log."""
        assert len(pcb_ir.mutation_log) == 0  # precondition
        old_ref = "Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical"
        new_ref = "MySocket:PinSocket_1x08_P2.54mm_Vertical"
        propagate_footprint_ref(pcb_ir, old_ref, new_ref)
        assert len(pcb_ir.mutation_log) == 1
        entry = pcb_ir.mutation_log[0]
        assert entry["description"] == "propagate_footprint_ref"
        assert entry["old_lib_ref"] == old_ref
        assert entry["new_lib_ref"] == new_ref
        assert entry["updated_count"] > 0

    def test_non_matching_returns_zero(self, pcb_ir: PcbIR) -> None:
        """propagate_footprint_ref with non-matching ref returns count=0."""
        result = propagate_footprint_ref(
            pcb_ir, "NonExistent:Footprint", "NewLib:Footprint"
        )
        assert result.matched_count == 0
        assert result.updated_count == 0
        assert not pcb_ir.dirty

    def test_empty_string_raises_valueerror(self, pcb_ir: PcbIR) -> None:
        """propagate_footprint_ref with empty string raises ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            propagate_footprint_ref(pcb_ir, "", "NewLib:Footprint")

        with pytest.raises(ValueError, match="non-empty"):
            propagate_footprint_ref(pcb_ir, "OldLib:Footprint", "")

    def test_file_path_in_result(
        self, pcb_ir: PcbIR, arduino_mega_pcb: Path
    ) -> None:
        """PropagationResult contains the file_path from the IR."""
        old_ref = "Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical"
        new_ref = "MySocket:PinSocket_1x08_P2.54mm_Vertical"
        result = propagate_footprint_ref(pcb_ir, old_ref, new_ref)
        assert result.file_path == arduino_mega_pcb

    def test_identical_old_new_returns_zero(self, pcb_ir: PcbIR) -> None:
        """propagate_footprint_ref with identical old/new returns count=0."""
        old_ref = "Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical"
        result = propagate_footprint_ref(pcb_ir, old_ref, old_ref)
        assert result.matched_count == 0
        assert result.updated_count == 0
        assert not pcb_ir.dirty
