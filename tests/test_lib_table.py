"""Unit tests for library table parsing and editing.

Tests parse/serialize round-trip for sym-lib-table and fp-lib-table files,
plus add/remove/get operations on LibTable.
"""

from pathlib import Path

import pytest

from kicad_agent.project.lib_table import (
    LibEntry,
    LibTable,
    parse_lib_table,
    serialize_lib_table,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

SYM_LIB_TABLE_CONTENT = """(sym_lib_table
  (version 7)
  (lib (name "Device")(type "KiCad")(uri "${KICAD8_SYMBOL_DIR}/Device.kicad_sym")(options "")(descr "Device symbols"))
  (lib (name "power")(type "KiCad")(uri "${KICAD8_SYMBOL_DIR}/power.kicad_sym")(options "")(descr "Power symbols"))
)"""

FP_LIB_TABLE_CONTENT = """(fp_lib_table
  (version 7)
  (lib (name "tile")(type "KiCad")(uri "${KIPRJMOD}/tile.pretty")(options "")(descr "Tile footprints"))
  (lib (name "Package_DIP")(type "KiCad")(uri "/opt/kicad/footprints/Package_DIP.pretty")(options "")(descr "DIP packages"))
)"""


@pytest.fixture
def sym_lib_table_file(tmp_path: Path) -> Path:
    """Create a temporary sym-lib-table file."""
    path = tmp_path / "sym-lib-table"
    path.write_text(SYM_LIB_TABLE_CONTENT, encoding="utf-8")
    return path


@pytest.fixture
def fp_lib_table_file(tmp_path: Path) -> Path:
    """Create a temporary fp-lib-table file."""
    path = tmp_path / "fp-lib-table"
    path.write_text(FP_LIB_TABLE_CONTENT, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParseLibTable:
    """Tests for parsing library table files."""

    def test_parse_sym_lib_table(self, sym_lib_table_file: Path) -> None:
        """Parse sym-lib-table with 2 entries, verify correct fields."""
        table = parse_lib_table(sym_lib_table_file)
        assert table.table_type == "sym_lib_table"
        assert len(table.entries) == 2

        device = table.get("Device")
        assert device.type == "KiCad"
        assert device.uri == "${KICAD8_SYMBOL_DIR}/Device.kicad_sym"
        assert device.descr == "Device symbols"

        power = table.get("power")
        assert power.type == "KiCad"
        assert power.uri == "${KICAD8_SYMBOL_DIR}/power.kicad_sym"

    def test_parse_fp_lib_table(self, fp_lib_table_file: Path) -> None:
        """Parse fp-lib-table with 2 entries, verify correct fields."""
        table = parse_lib_table(fp_lib_table_file)
        assert table.table_type == "fp_lib_table"
        assert len(table.entries) == 2

        tile = table.get("tile")
        assert tile.type == "KiCad"
        assert tile.uri == "${KIPRJMOD}/tile.pretty"

        dip = table.get("Package_DIP")
        assert dip.descr == "DIP packages"


class TestLibTableEditing:
    """Tests for add/remove/get operations on LibTable."""

    def test_add_entry(self, sym_lib_table_file: Path) -> None:
        """Add an entry to a parsed table and verify it is retrievable."""
        table = parse_lib_table(sym_lib_table_file)
        initial_count = len(table.entries)

        new_entry = LibEntry(
            name="MyLib",
            type="KiCad",
            uri="${KIPRJMOD}/my.kicad_sym",
            descr="Custom library",
        )
        table.add(new_entry)

        assert len(table.entries) == initial_count + 1
        retrieved = table.get("MyLib")
        assert retrieved.uri == "${KIPRJMOD}/my.kicad_sym"

    def test_add_duplicate_name_raises(self, sym_lib_table_file: Path) -> None:
        """Adding an entry with an existing name raises ValueError."""
        table = parse_lib_table(sym_lib_table_file)

        duplicate = LibEntry(
            name="Device",
            type="KiCad",
            uri="/some/other/path.kicad_sym",
        )
        with pytest.raises(ValueError, match="already exists"):
            table.add(duplicate)

    def test_remove_entry(self, sym_lib_table_file: Path) -> None:
        """Remove an entry by name and verify count decreased."""
        table = parse_lib_table(sym_lib_table_file)
        initial_count = len(table.entries)

        removed = table.remove("Device")
        assert removed.name == "Device"
        assert len(table.entries) == initial_count - 1

        # Verify it is no longer retrievable
        with pytest.raises(KeyError):
            table.get("Device")

    def test_remove_nonexistent_raises(self, sym_lib_table_file: Path) -> None:
        """Removing a non-existent entry raises KeyError."""
        table = parse_lib_table(sym_lib_table_file)
        with pytest.raises(KeyError, match="not found"):
            table.remove("NonExistent")

    def test_get_entry(self, sym_lib_table_file: Path) -> None:
        """Get an entry by name and verify all fields match."""
        table = parse_lib_table(sym_lib_table_file)
        entry = table.get("Device")
        assert entry.name == "Device"
        assert entry.type == "KiCad"
        assert entry.uri == "${KICAD8_SYMBOL_DIR}/Device.kicad_sym"
        assert entry.options == ""
        assert entry.descr == "Device symbols"

    def test_get_nonexistent_raises(self, sym_lib_table_file: Path) -> None:
        """Getting a non-existent entry raises KeyError."""
        table = parse_lib_table(sym_lib_table_file)
        with pytest.raises(KeyError, match="not found"):
            table.get("NonExistent")


class TestRoundTrip:
    """Tests for parse -> serialize -> re-parse fidelity."""

    def test_round_trip(self, sym_lib_table_file: Path, tmp_path: Path) -> None:
        """Parse, serialize, re-parse and verify identical content."""
        table = parse_lib_table(sym_lib_table_file)

        output_path = tmp_path / "sym-lib-table-out"
        serialize_lib_table(table, output_path)

        re_parsed = parse_lib_table(output_path)
        assert re_parsed.table_type == table.table_type
        assert len(re_parsed.entries) == len(table.entries)

        for orig, reparsed in zip(table.entries, re_parsed.entries):
            assert orig.name == reparsed.name
            assert orig.type == reparsed.type
            assert orig.uri == reparsed.uri

    def test_empty_table(self, tmp_path: Path) -> None:
        """Create empty table, serialize, re-parse, verify 0 entries."""
        table = LibTable(table_type="sym_lib_table", entries=[])
        output_path = tmp_path / "sym-lib-table-empty"
        serialize_lib_table(table, output_path)

        re_parsed = parse_lib_table(output_path)
        assert re_parsed.table_type == "sym_lib_table"
        assert len(re_parsed.entries) == 0

    def test_uri_variables_preserved(self, tmp_path: Path) -> None:
        """Entry with ${KICAD8_SYMBOL_DIR} preserves the variable reference."""
        entry = LibEntry(
            name="Device",
            type="KiCad",
            uri="${KICAD8_SYMBOL_DIR}/Device.kicad_sym",
        )
        assert "${KICAD8_SYMBOL_DIR}" in entry.uri

        table = LibTable(table_type="sym_lib_table", entries=[entry])
        output_path = tmp_path / "sym-lib-table"
        serialize_lib_table(table, output_path)

        re_parsed = parse_lib_table(output_path)
        assert re_parsed.get("Device").uri == "${KICAD8_SYMBOL_DIR}/Device.kicad_sym"
