"""Tests for UUID extraction, re-injection, and serialization (FND-05, FND-06).

Covers:
- UUID extraction from raw PCB/footprint S-expression content
- UUID extraction from schematic content (UUIDs exist but kiutils preserves them)
- Empty/edge cases for extraction
- UUID re-injection into kiutils serialized output
- All four file-type serializers produce valid, re-parseable output
"""

import re
from pathlib import Path

import pytest

from kicad_agent.parser.schematic_parser import parse_schematic
from kicad_agent.parser.pcb_parser import parse_pcb
from kicad_agent.parser.symbol_parser import parse_symbol_lib
from kicad_agent.parser.footprint_parser import parse_footprint
from kicad_agent.parser.uuid_extractor import (
    UUIDEntry,
    UUIDMap,
    extract_uuids,
    extract_uuids_from_file,
)
from kicad_agent.serializer.uuid_reinjector import reinject_uuids
from kicad_agent.serializer.schematic_ser import serialize_schematic
from kicad_agent.serializer.pcb_ser import serialize_pcb
from kicad_agent.serializer.symbol_ser import serialize_symbol_lib
from kicad_agent.serializer.footprint_ser import serialize_footprint


# ---------------------------------------------------------------------------
# Test 1-4: UUID extraction
# ---------------------------------------------------------------------------


class TestExtractUuids:
    """UUID extraction from raw KiCad S-expression content."""

    def test_extract_uuids_pcb_returns_entries(self, arduino_mega_pcb: Path) -> None:
        """Test 1: extract_uuids on PCB raw content returns a UUIDMap with entries."""
        raw_content = arduino_mega_pcb.read_text(encoding="utf-8")
        uuid_map = extract_uuids(raw_content, file_type="pcb")
        assert isinstance(uuid_map, UUIDMap)
        assert len(uuid_map.entries) > 0
        assert uuid_map.source_file_type == "pcb"

    def test_extract_uuids_schematic_returns_entries(
        self, arduino_mega_sch: Path
    ) -> None:
        """Test 2: extract_uuids on schematic raw content returns a UUIDMap with entries."""
        raw_content = arduino_mega_sch.read_text(encoding="utf-8")
        uuid_map = extract_uuids(raw_content, file_type="schematic")
        assert isinstance(uuid_map, UUIDMap)
        assert len(uuid_map.entries) > 0
        assert uuid_map.source_file_type == "schematic"

    def test_extract_uuids_no_uuids_returns_empty(self) -> None:
        """Test 3: extract_uuids on content with no UUIDs returns empty entries."""
        content = "(kicad_pcb (version 20241229) (generator pcbnew)\n  (general)\n)"
        uuid_map = extract_uuids(content, file_type="pcb")
        assert isinstance(uuid_map, UUIDMap)
        assert len(uuid_map.entries) == 0

    def test_extract_uuids_parses_uuid_format(self) -> None:
        """Test 4: extract_uuids correctly parses UUID values in standard format."""
        content = '(footprint "Resistor" (uuid "12345678-1234-1234-1234-123456789abc"))'
        uuid_map = extract_uuids(content, file_type="footprint")
        assert len(uuid_map.entries) == 1
        assert uuid_map.entries[0].uuid_value == "12345678-1234-1234-1234-123456789abc"

    def test_extract_uuids_from_file(self, arduino_mega_pcb: Path) -> None:
        """extract_uuids_from_file reads file and delegates to extract_uuids."""
        uuid_map = extract_uuids_from_file(arduino_mega_pcb, file_type="pcb")
        assert isinstance(uuid_map, UUIDMap)
        assert len(uuid_map.entries) > 0

    def test_extract_uuids_entries_have_parent_type(
        self, arduino_mega_pcb: Path
    ) -> None:
        """UUIDMap entries have populated parent_type fields."""
        raw_content = arduino_mega_pcb.read_text(encoding="utf-8")
        uuid_map = extract_uuids(raw_content, file_type="pcb")
        parent_types = {entry.parent_type for entry in uuid_map.entries}
        # PCB files have at least footprints with UUIDs
        assert len(parent_types) > 0
        assert all(isinstance(pt, str) for pt in parent_types)

    def test_extract_uuids_entries_have_line_numbers(
        self, arduino_mega_pcb: Path
    ) -> None:
        """UUIDMap entries have line numbers > 0."""
        raw_content = arduino_mega_pcb.read_text(encoding="utf-8")
        uuid_map = extract_uuids(raw_content, file_type="pcb")
        for entry in uuid_map.entries:
            assert entry.line_number > 0


# ---------------------------------------------------------------------------
# Test 5-6: UUID re-injection
# ---------------------------------------------------------------------------


class TestReinjectUuids:
    """UUID re-injection into kiutils serialized output."""

    def test_reinject_uuids_restores_tokens(self) -> None:
        """Test 5: reinject_uuids restores UUID tokens in serialized content."""
        # Simulate kiutils output (no UUIDs) and a UUIDMap to restore
        serialized = '  (footprint "Resistor"\n    (pad 1 thru_hole circle)\n  )'
        uuid_map = UUIDMap(
            entries=(
                UUIDEntry(
                    uuid_value="aaaa1111-2222-3333-4444-555566667777",
                    parent_type="footprint",
                    parent_index=0,
                    line_number=1,
                ),
                UUIDEntry(
                    uuid_value="bbbb1111-2222-3333-4444-555566667777",
                    parent_type="pad",
                    parent_index=0,
                    line_number=2,
                ),
            ),
            source_file_type="footprint",
        )
        result = reinject_uuids(serialized, uuid_map)
        assert "aaaa1111-2222-3333-4444-555566667777" in result
        assert "bbbb1111-2222-3333-4444-555566667777" in result

    def test_reinject_uuids_empty_map_returns_content(self) -> None:
        """Test 6: reinject_uuids with empty UUIDMap returns content unchanged."""
        content = "  (some content without uuids)\n"
        uuid_map = UUIDMap(entries=(), source_file_type="pcb")
        result = reinject_uuids(content, uuid_map)
        assert result == content


# ---------------------------------------------------------------------------
# Test 7-10: Serializers
# ---------------------------------------------------------------------------


class TestSerializers:
    """All four file-type serializers produce valid, re-parseable output."""

    def test_serialize_schematic_reparseable(
        self, arduino_mega_sch: Path, tmp_output_dir: Path
    ) -> None:
        """Test 7: serialize_schematic writes a file that kiutils can re-parse."""
        parse_result = parse_schematic(arduino_mega_sch)
        output_path = tmp_output_dir / "test_output.kicad_sch"
        result_path = serialize_schematic(parse_result, output_path)
        assert result_path == output_path
        assert output_path.exists()
        assert output_path.stat().st_size > 0

        # Verify re-parseable
        from kiutils.schematic import Schematic

        reparsed = Schematic.from_file(str(output_path))
        assert reparsed is not None

    def test_serialize_pcb_with_uuid_map(
        self, arduino_mega_pcb: Path, tmp_output_dir: Path
    ) -> None:
        """Test 8: serialize_pcb writes a file with UUIDs restored when UUIDMap provided."""
        parse_result = parse_pcb(arduino_mega_pcb)
        uuid_map = extract_uuids(parse_result.raw_content, file_type="pcb")
        output_path = tmp_output_dir / "test_output.kicad_pcb"
        result_path = serialize_pcb(parse_result, output_path, uuid_map=uuid_map)
        assert result_path == output_path
        assert output_path.exists()
        assert output_path.stat().st_size > 0

        # Verify re-parseable
        from kiutils.board import Board

        reparsed = Board.from_file(str(output_path))
        assert reparsed is not None

        # Verify UUIDs were restored
        output_content = output_path.read_text(encoding="utf-8")
        for entry in uuid_map.entries[:5]:  # Check a sample
            assert entry.uuid_value in output_content

    def test_serialize_pcb_without_uuid_map(
        self, arduino_mega_pcb: Path, tmp_output_dir: Path
    ) -> None:
        """serialize_pcb works without UUIDMap (UUIDs dropped)."""
        parse_result = parse_pcb(arduino_mega_pcb)
        output_path = tmp_output_dir / "test_no_uuid.kicad_pcb"
        result_path = serialize_pcb(parse_result, output_path)
        assert result_path == output_path
        assert output_path.exists()

    def test_serialize_footprint_with_uuid_map(
        self, arduino_mounting_hole_mod: Path, tmp_output_dir: Path
    ) -> None:
        """Test 9: serialize_footprint writes a file with UUIDs restored when UUIDMap provided."""
        parse_result = parse_footprint(arduino_mounting_hole_mod)
        uuid_map = extract_uuids(parse_result.raw_content, file_type="footprint")
        output_path = tmp_output_dir / "test_output.kicad_mod"
        result_path = serialize_footprint(
            parse_result, output_path, uuid_map=uuid_map
        )
        assert result_path == output_path
        assert output_path.exists()
        assert output_path.stat().st_size > 0

        # Verify re-parseable
        from kiutils.footprint import Footprint

        reparsed = Footprint.from_file(str(output_path))
        assert reparsed is not None

        # Verify UUIDs were restored
        if len(uuid_map.entries) > 0:
            output_content = output_path.read_text(encoding="utf-8")
            for entry in uuid_map.entries:
                assert entry.uuid_value in output_content

    def test_serialize_symbol_lib_reparseable(
        self, sample_sym_lib: Path, tmp_output_dir: Path
    ) -> None:
        """Test 10: serialize_symbol_lib writes a file that kiutils can re-parse."""
        parse_result = parse_symbol_lib(sample_sym_lib)
        output_path = tmp_output_dir / "test_output.kicad_sym"
        result_path = serialize_symbol_lib(parse_result, output_path)
        assert result_path == output_path
        assert output_path.exists()
        assert output_path.stat().st_size > 0

        # Verify re-parseable
        from kiutils.symbol import SymbolLib

        reparsed = SymbolLib.from_file(str(output_path))
        assert reparsed is not None
