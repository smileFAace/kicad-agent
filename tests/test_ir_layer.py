"""Tests for IR (Intermediate Representation) layer -- OPS-03.

Verifies IR creation, mutation tracking, file-type validation,
component access, UUID map requirements, and the one-IR-per-ParseResult
registry enforcement.
"""

from pathlib import Path

import pytest

from kicad_agent.ir import FootprintIR, PcbIR, SchematicIR, SymbolLibIR
from kicad_agent.ir.base import BaseIR, _clear_registry
from kicad_agent.parser import (
    parse_footprint,
    parse_pcb,
    parse_schematic,
    parse_symbol_lib,
)
from kicad_agent.parser.uuid_extractor import extract_uuids


@pytest.fixture(autouse=True)
def _reset_ir_registry():
    """Clear the IR registry before and after each test to prevent id() collisions."""
    _clear_registry()
    yield
    _clear_registry()


class TestBaseIRMutationTracking:
    """Mutation tracking: dirty flag, mutation log, copy-on-read, log cap."""

    @pytest.fixture
    def schematic_ir(self, arduino_mega_sch: Path) -> SchematicIR:
        """Create a SchematicIR for mutation tracking tests."""
        result = parse_schematic(arduino_mega_sch)
        return SchematicIR(_parse_result=result)

    def test_initial_state_not_dirty(self, schematic_ir: SchematicIR) -> None:
        """Newly created IR is not dirty."""
        assert not schematic_ir.dirty

    def test_record_mutation_sets_dirty(self, schematic_ir: SchematicIR) -> None:
        """_record_mutation sets the dirty flag."""
        schematic_ir._record_mutation("test mutation", {"field": "x"})
        assert schematic_ir.dirty is True

    def test_mutation_log_records_entries(self, schematic_ir: SchematicIR) -> None:
        """_record_mutation appends entries with description and details."""
        schematic_ir._record_mutation("first", {"field": "a"})
        schematic_ir._record_mutation("second", {"field": "b"})

        log = schematic_ir.mutation_log
        assert len(log) == 2
        assert log[0]["description"] == "first"
        assert log[0]["field"] == "a"
        assert log[1]["description"] == "second"
        assert log[1]["field"] == "b"

    def test_mutation_log_is_copy(self, schematic_ir: SchematicIR) -> None:
        """mutation_log returns a copy -- external mutations don't affect internal state."""
        schematic_ir._record_mutation("test", {"field": "x"})

        log = schematic_ir.mutation_log
        log.append({"description": "external"})

        assert len(schematic_ir.mutation_log) == 1

    def test_mutation_log_cap_eviction(self, schematic_ir: SchematicIR) -> None:
        """Mutation log evicts oldest entries when cap is reached (Council M-02)."""
        cap = BaseIR._MAX_MUTATION_LOG
        for i in range(cap + 10):
            schematic_ir._record_mutation(f"mutation_{i}", {"index": i})

        log = schematic_ir.mutation_log
        assert len(log) == cap
        # Oldest entries were evicted -- first entry should be mutation_10
        assert log[0]["description"] == "mutation_10"
        # Most recent entry should be the last one recorded
        assert log[-1]["description"] == f"mutation_{cap + 9}"


class TestOneIRPerParseResult:
    """Council HIGH: Registry enforces one-IR-per-ParseResult invariant."""

    def test_duplicate_ir_raises(self, arduino_mega_sch: Path) -> None:
        """Creating a second IR for the same ParseResult raises RuntimeError."""
        result = parse_schematic(arduino_mega_sch)
        SchematicIR(_parse_result=result)

        with pytest.raises(RuntimeError, match="ParseResult already has an IR wrapper"):
            SchematicIR(_parse_result=result)

    def test_different_parse_results_ok(self, arduino_mega_sch: Path) -> None:
        """Creating IRs from different ParseResults succeeds."""
        result1 = parse_schematic(arduino_mega_sch)
        result2 = parse_schematic(arduino_mega_sch)

        ir1 = SchematicIR(_parse_result=result1)
        ir2 = SchematicIR(_parse_result=result2)

        assert ir1 is not ir2
        assert id(ir1._parse_result) != id(ir2._parse_result)


class TestSchematicIR:
    """SchematicIR wraps kiutils Schematic with component access."""

    def test_create_from_parse_result(self, arduino_mega_sch: Path) -> None:
        """SchematicIR created from valid schematic ParseResult."""
        result = parse_schematic(arduino_mega_sch)
        ir = SchematicIR(_parse_result=result)

        assert ir.file_type == "schematic"
        assert len(ir.components) > 0

    def test_wrong_file_type_raises(self, arduino_mega_pcb: Path) -> None:
        """Creating SchematicIR from PCB ParseResult raises ValueError."""
        result = parse_pcb(arduino_mega_pcb)

        with pytest.raises(ValueError, match="schematic"):
            SchematicIR(_parse_result=result)

    def test_get_component_by_ref_found(self, arduino_mega_sch: Path) -> None:
        """get_component_by_ref finds a component by reference designator."""
        result = parse_schematic(arduino_mega_sch)
        ir = SchematicIR(_parse_result=result)

        # Get the first component's reference to search for
        first_ref = None
        for prop in ir.components[0].properties:
            if prop.key == "Reference":
                first_ref = prop.value
                break

        assert first_ref is not None
        component = ir.get_component_by_ref(first_ref)
        assert component is not None

    def test_get_component_by_ref_not_found(self, arduino_mega_sch: Path) -> None:
        """get_component_by_ref returns None for non-existent reference."""
        result = parse_schematic(arduino_mega_sch)
        ir = SchematicIR(_parse_result=result)

        assert ir.get_component_by_ref("NONEXISTENT999") is None

    def test_schematic_property(self, arduino_mega_sch: Path) -> None:
        """schematic property returns the kiutils Schematic object."""
        from kiutils.schematic import Schematic

        result = parse_schematic(arduino_mega_sch)
        ir = SchematicIR(_parse_result=result)

        assert isinstance(ir.schematic, Schematic)


class TestPcbIR:
    """PcbIR wraps kiutils Board with footprints and nets access."""

    def test_create_from_parse_result(self, arduino_mega_pcb: Path) -> None:
        """PcbIR created from valid PCB ParseResult with UUID map."""
        result = parse_pcb(arduino_mega_pcb)
        uuid_map = extract_uuids(result.raw_content, "pcb")
        ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)

        assert ir.file_type == "pcb"
        assert len(ir.footprints) > 0

    def test_requires_uuid_map(self, arduino_mega_pcb: Path) -> None:
        """PcbIR without uuid_map raises ValueError."""
        result = parse_pcb(arduino_mega_pcb)

        with pytest.raises(ValueError, match="UUID map"):
            PcbIR(_parse_result=result)

    def test_nets_property(self, arduino_mega_pcb: Path) -> None:
        """PcbIR exposes nets from the PCB."""
        result = parse_pcb(arduino_mega_pcb)
        uuid_map = extract_uuids(result.raw_content, "pcb")
        ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)

        assert len(ir.nets) > 0


class TestSymbolLibIR:
    """SymbolLibIR wraps kiutils SymbolLib with symbols access."""

    def test_create_from_parse_result(self, sample_sym_lib: Path) -> None:
        """SymbolLibIR created from valid symbol library ParseResult."""
        result = parse_symbol_lib(sample_sym_lib)
        ir = SymbolLibIR(_parse_result=result)

        assert ir.file_type == "symbol_lib"
        assert len(ir.symbols) > 0


class TestFootprintIR:
    """FootprintIR wraps kiutils Footprint with pads access."""

    def test_create_from_parse_result(self, arduino_mounting_hole_mod: Path) -> None:
        """FootprintIR created from valid footprint ParseResult with UUID map."""
        result = parse_footprint(arduino_mounting_hole_mod)
        uuid_map = extract_uuids(result.raw_content, "footprint")
        ir = FootprintIR(_parse_result=result, _uuid_map=uuid_map)

        assert ir.file_type == "footprint"
        assert len(ir.pads) > 0

    def test_requires_uuid_map(self, arduino_mounting_hole_mod: Path) -> None:
        """FootprintIR without uuid_map raises ValueError."""
        result = parse_footprint(arduino_mounting_hole_mod)

        with pytest.raises(ValueError, match="UUID map"):
            FootprintIR(_parse_result=result)
