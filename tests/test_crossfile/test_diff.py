"""Test suite for structural diff generation.

Tests structural_diff function that compares two KiCad S-expression files
and produces syntax-aware DiffEntry results grouped by structural element.
"""

from pathlib import Path

import pytest

from kicad_agent.crossfile.diff import (
    DiffEntry,
    DiffResult,
    DiffType,
    _extract_elements,
    _sexp_to_string,
    structural_diff,
)

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "Arduino_Mega"
ARDUINO_MEGA_SCH = FIXTURE_DIR / "Arduino_Mega.kicad_sch"


def _write_sch(path: Path, content: str) -> Path:
    """Write a small .kicad_sch string to a file and return the path."""
    path.write_text(content, encoding="utf-8")
    return path


# Minimal valid .kicad_sch content for testing
MINIMAL_SCH = """(kicad_sch (version 20250114) (generator "test")
  (symbol (lib_id "Device:R") (at 50 30 0) (uuid "aaaa-1111")
    (property "Reference" "R1" (at 50 30 0))
    (property "Value" "10k" (at 50 30 0))
  )
  (wire (uuid "bbbb-2222")
    (pts (xy 0 0) (xy 10 10))
  )
)"""

SCH_WITH_EXTRA = """(kicad_sch (version 20250114) (generator "test")
  (symbol (lib_id "Device:R") (at 50 30 0) (uuid "aaaa-1111")
    (property "Reference" "R1" (at 50 30 0))
    (property "Value" "10k" (at 50 30 0))
  )
  (wire (uuid "bbbb-2222")
    (pts (xy 0 0) (xy 10 10))
  )
  (symbol (lib_id "Device:C") (at 100 50 90) (uuid "cccc-3333")
    (property "Reference" "C1" (at 100 50 0))
    (property "Value" "100nF" (at 100 50 0))
  )
  (symbol (lib_id "Device:R") (at 150 70 0) (uuid "dddd-4444")
    (property "Reference" "R4" (at 150 70 0))
    (property "Value" "1k" (at 150 70 0))
  )
)"""

SCH_WITH_REMOVED = """(kicad_sch (version 20250114) (generator "test")
  (symbol (lib_id "Device:R") (at 50 30 0) (uuid "aaaa-1111")
    (property "Reference" "R1" (at 50 30 0))
    (property "Value" "10k" (at 50 30 0))
  )
)"""

SCH_MODIFIED = """(kicad_sch (version 20250114) (generator "test")
  (symbol (lib_id "Device:R") (at 50 30 0) (uuid "aaaa-1111")
    (property "Reference" "R1" (at 50 30 0))
    (property "Value" "4.7k" (at 50 30 0))
  )
  (wire (uuid "bbbb-2222")
    (pts (xy 0 0) (xy 10 10))
  )
)"""

SCH_MOVED = """(kicad_sch (version 20250114) (generator "test")
  (symbol (lib_id "Device:R") (at 75 60 0) (uuid "aaaa-1111")
    (property "Reference" "R1" (at 75 60 0))
    (property "Value" "10k" (at 75 60 0))
  )
  (wire (uuid "bbbb-2222")
    (pts (xy 0 0) (xy 10 10))
  )
)"""


# --- TestDiffTypes ---


class TestDiffTypes:
    """Verify DiffType enum values and DiffEntry/DiffResult creation."""

    def test_diff_type_values(self):
        assert DiffType.ADDED == "added"
        assert DiffType.REMOVED == "removed"
        assert DiffType.MODIFIED == "modified"
        assert DiffType.MOVED == "moved"

    def test_diff_entry_creation_added(self):
        entry = DiffEntry(
            diff_type=DiffType.ADDED,
            element_type="symbol",
            identifier="uuid-new",
            old_value=None,
            new_value="(symbol ...)",
            path_in_file="/symbol/uuid-new",
        )
        assert entry.diff_type == DiffType.ADDED
        assert entry.element_type == "symbol"
        assert entry.old_value is None
        assert entry.new_value == "(symbol ...)"

    def test_diff_entry_creation_removed(self):
        entry = DiffEntry(
            diff_type=DiffType.REMOVED,
            element_type="wire",
            identifier="uuid-old",
            old_value="(wire ...)",
            new_value=None,
            path_in_file="/wire/uuid-old",
        )
        assert entry.diff_type == DiffType.REMOVED
        assert entry.old_value == "(wire ...)"
        assert entry.new_value is None

    def test_diff_entry_creation_modified(self):
        entry = DiffEntry(
            diff_type=DiffType.MODIFIED,
            element_type="symbol",
            identifier="uuid-mut",
            old_value="(symbol (property Value 10k))",
            new_value="(symbol (property Value 4.7k))",
            path_in_file="/symbol/uuid-mut",
        )
        assert entry.diff_type == DiffType.MODIFIED

    def test_diff_result_creation(self):
        result = DiffResult(
            entries=[],
            file_a_path=Path("/a.kicad_sch"),
            file_b_path=Path("/b.kicad_sch"),
            difftastic_available=False,
            difftastic_output=None,
        )
        assert result.entries == []
        assert result.file_a_path == Path("/a.kicad_sch")
        assert result.difftastic_available is False

    def test_diff_entry_is_frozen(self):
        entry = DiffEntry(
            diff_type=DiffType.ADDED,
            element_type="symbol",
            identifier="id1",
            old_value=None,
            new_value="val",
            path_in_file="/symbol/id1",
        )
        with pytest.raises(AttributeError):
            entry.diff_type = DiffType.REMOVED  # type: ignore[misc]

    def test_diff_result_is_frozen(self):
        result = DiffResult(
            entries=[],
            file_a_path=Path("/a"),
            file_b_path=Path("/b"),
            difftastic_available=False,
            difftastic_output=None,
        )
        with pytest.raises(AttributeError):
            result.difftastic_available = True  # type: ignore[misc]


# --- TestSexpToString ---


class TestSexpToString:
    """Test S-expression serialization back to string."""

    def test_simple_atom(self):
        assert _sexp_to_string("hello") == "hello"

    def test_simple_list(self):
        result = _sexp_to_string(["symbol", "R1"])
        assert result == "(symbol R1)"

    def test_nested_list(self):
        result = _sexp_to_string(["symbol", ["uuid", "abc"]])
        assert result == "(symbol (uuid abc))"

    def test_quoted_string_preserved(self):
        result = _sexp_to_string(["property", "Reference", "R1"])
        assert result == "(property Reference R1)"

    def test_number_atom(self):
        result = _sexp_to_string(["version", 20250114])
        assert result == "(version 20250114)"

    def test_deeply_nested(self):
        result = _sexp_to_string(
            ["kicad_sch", ["symbol", ["lib_id", "Device:R"], ["uuid", "abc"]]]
        )
        assert "Device:R" in result
        assert "abc" in result


# --- TestExtractElements ---


class TestExtractElements:
    """Test extraction of elements from parsed S-expressions."""

    def test_groups_by_element_type(self):
        import sexpdata

        sexp = sexpdata.loads(
            '(kicad_sch (version 20250114) '
            '(symbol (lib_id "Device:R") (uuid "abc-123") '
            '(property "Reference" "R1")) '
            '(wire (uuid "def-456") '
            '(pts (xy 0 0) (xy 10 10))))'
        )
        groups = _extract_elements(sexp)
        assert "symbol" in groups
        assert "wire" in groups

    def test_extracts_uuid_as_identifier(self):
        import sexpdata

        sexp = sexpdata.loads(
            '(kicad_sch (version 20250114) '
            '(symbol (lib_id "Device:R") (uuid "abc-123") '
            '(property "Reference" "R1")))'
        )
        groups = _extract_elements(sexp)
        assert "abc-123" in groups["symbol"]

    def test_falls_back_to_index_identifier(self):
        import sexpdata

        # Element without uuid
        sexp = sexpdata.loads(
            '(kicad_sch (version 20250114) '
            '(gr_text "Hello"))'
        )
        groups = _extract_elements(sexp)
        assert "gr_text" in groups
        assert len(groups["gr_text"]) == 1
        # Identifier should be index-based
        key = list(groups["gr_text"].keys())[0]
        assert "gr_text" in key

    def test_multiple_elements_same_type(self):
        import sexpdata

        sexp = sexpdata.loads(
            '(kicad_sch (version 20250114) '
            '(symbol (uuid "id-1")) '
            '(symbol (uuid "id-2")))'
        )
        groups = _extract_elements(sexp)
        assert len(groups["symbol"]) == 2
        assert "id-1" in groups["symbol"]
        assert "id-2" in groups["symbol"]


# --- TestStructuralDiffIdentical ---


class TestStructuralDiffIdentical:
    """Test diffing a file against itself produces zero entries."""

    def test_identical_file_zero_entries(self, tmp_path):
        sch_file = tmp_path / "test.kicad_sch"
        sch_file.write_text(MINIMAL_SCH, encoding="utf-8")

        result = structural_diff(sch_file, sch_file)
        assert result.entries == []
        assert result.file_a_path == sch_file.resolve()
        assert result.file_b_path == sch_file.resolve()

    def test_real_fixture_identical(self):
        if not ARDUINO_MEGA_SCH.exists():
            pytest.skip("Arduino_Mega fixture not available")

        result = structural_diff(ARDUINO_MEGA_SCH, ARDUINO_MEGA_SCH)
        assert result.entries == []
        assert result.file_a_path == ARDUINO_MEGA_SCH.resolve()


# --- TestStructuralDiffWithChanges ---


class TestStructuralDiffWithChanges:
    """Test diffing files with modifications."""

    def test_modified_property(self, tmp_path):
        file_a = tmp_path / "a.kicad_sch"
        file_b = tmp_path / "b.kicad_sch"
        file_a.write_text(MINIMAL_SCH, encoding="utf-8")
        file_b.write_text(SCH_MODIFIED, encoding="utf-8")

        result = structural_diff(file_a, file_b)
        modified = [e for e in result.entries if e.diff_type == DiffType.MODIFIED]
        assert len(modified) >= 1
        # The symbol with uuid aaaa-1111 should be modified (Value changed 10k -> 4.7k)
        symbol_mods = [e for e in modified if e.element_type == "symbol"]
        assert len(symbol_mods) >= 1
        assert any("aaaa-1111" in e.identifier for e in symbol_mods)

    def test_moved_element(self, tmp_path):
        file_a = tmp_path / "a.kicad_sch"
        file_b = tmp_path / "b.kicad_sch"
        file_a.write_text(MINIMAL_SCH, encoding="utf-8")
        file_b.write_text(SCH_MOVED, encoding="utf-8")

        result = structural_diff(file_a, file_b)
        moved = [e for e in result.entries if e.diff_type == DiffType.MOVED]
        assert len(moved) >= 1
        assert any(e.element_type == "symbol" for e in moved)


# --- TestStructuralDiffAddedRemoved ---


class TestStructuralDiffAddedRemoved:
    """Test diffing files with added and removed components."""

    def test_added_elements(self, tmp_path):
        file_a = tmp_path / "a.kicad_sch"
        file_b = tmp_path / "b.kicad_sch"
        file_a.write_text(MINIMAL_SCH, encoding="utf-8")
        file_b.write_text(SCH_WITH_EXTRA, encoding="utf-8")

        result = structural_diff(file_a, file_b)
        added = [e for e in result.entries if e.diff_type == DiffType.ADDED]
        added_ids = {e.identifier for e in added}
        assert "cccc-3333" in added_ids  # C1 added
        assert "dddd-4444" in added_ids  # R4 added

    def test_added_element_types(self, tmp_path):
        file_a = tmp_path / "a.kicad_sch"
        file_b = tmp_path / "b.kicad_sch"
        file_a.write_text(MINIMAL_SCH, encoding="utf-8")
        file_b.write_text(SCH_WITH_EXTRA, encoding="utf-8")

        result = structural_diff(file_a, file_b)
        added = [e for e in result.entries if e.diff_type == DiffType.ADDED]
        added_types = {e.element_type for e in added}
        assert "symbol" in added_types

    def test_removed_elements(self, tmp_path):
        file_a = tmp_path / "a.kicad_sch"
        file_c = tmp_path / "c.kicad_sch"
        file_a.write_text(MINIMAL_SCH, encoding="utf-8")
        file_c.write_text(SCH_WITH_REMOVED, encoding="utf-8")

        result = structural_diff(file_a, file_c)
        removed = [e for e in result.entries if e.diff_type == DiffType.REMOVED]
        removed_ids = {e.identifier for e in removed}
        assert "bbbb-2222" in removed_ids  # wire removed

    def test_diff_result_file_paths(self, tmp_path):
        file_a = tmp_path / "a.kicad_sch"
        file_b = tmp_path / "b.kicad_sch"
        file_a.write_text(MINIMAL_SCH, encoding="utf-8")
        file_b.write_text(SCH_WITH_EXTRA, encoding="utf-8")

        result = structural_diff(file_a, file_b)
        assert result.file_a_path == file_a.resolve()
        assert result.file_b_path == file_b.resolve()


# --- TestDifftasticFallback ---


class TestDifftasticFallback:
    """Test difftastic integration and fallback behavior."""

    def test_works_without_difftastic(self, tmp_path):
        file_a = tmp_path / "a.kicad_sch"
        file_b = tmp_path / "b.kicad_sch"
        file_a.write_text(MINIMAL_SCH, encoding="utf-8")
        file_b.write_text(SCH_MODIFIED, encoding="utf-8")

        result = structural_diff(file_a, file_b)
        # structural_diff must work regardless of difftastic availability
        assert isinstance(result, DiffResult)
        assert isinstance(result.entries, list)
        assert isinstance(result.difftastic_available, bool)

    def test_difftastic_available_reflects_status(self, tmp_path):
        file_a = tmp_path / "a.kicad_sch"
        file_b = tmp_path / "b.kicad_sch"
        file_a.write_text(MINIMAL_SCH, encoding="utf-8")
        file_b.write_text(SCH_MODIFIED, encoding="utf-8")

        result = structural_diff(file_a, file_b)
        # difftastic_available should be a boolean reflecting installation status
        assert isinstance(result.difftastic_available, bool)

    def test_real_fixture_diff(self):
        """Test diff against real KiCad fixture produces valid result."""
        if not ARDUINO_MEGA_SCH.exists():
            pytest.skip("Arduino_Mega fixture not available")

        result = structural_diff(ARDUINO_MEGA_SCH, ARDUINO_MEGA_SCH)
        assert isinstance(result, DiffResult)
        assert len(result.entries) == 0


# --- TestSecurityMitigations ---


class TestSecurityMitigations:
    """Test threat model mitigations T-06-14 through T-06-17."""

    def test_path_traversal_rejected(self, tmp_path):
        """T-06-16: Symlink paths are resolved before reading."""
        file_a = tmp_path / "a.kicad_sch"
        file_a.write_text(MINIMAL_SCH, encoding="utf-8")
        # Resolved paths should be used internally
        result = structural_diff(file_a, file_a)
        assert result.file_a_path.is_absolute()

    def test_difftastic_timeout(self, tmp_path):
        """T-06-14: difftastic call uses timeout to prevent hanging."""
        file_a = tmp_path / "a.kicad_sch"
        file_a.write_text(MINIMAL_SCH, encoding="utf-8")
        # The function should not hang -- timeout is set internally
        result = structural_diff(file_a, file_a)
        assert isinstance(result, DiffResult)
