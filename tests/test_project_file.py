"""Unit tests for project file parsing and project-level operations.

Tests .kicad_pro parsing, operation schema for library/net class/rule operations,
and executor dispatch for project file types.
"""

import json
from pathlib import Path

import pytest

from kicad_agent.ops.executor import OperationExecutor
from kicad_agent.ops.schema import (
    AddDesignRuleOp,
    AddLibEntryOp,
    AddNetClassOp,
    ListDesignRulesOp,
    ListLibEntriesOp,
    ListNetClassesOp,
    ModifyDesignRuleOp,
    ModifyNetClassOp,
    ModifyProjectSettingsOp,
    Operation,
    RemoveDesignRuleOp,
    RemoveLibEntryOp,
    RemoveNetClassOp,
)
from kicad_agent.project.project_file import (
    ProjectFile,
    get_project_settings,
    parse_project_file,
    write_project_settings,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

PRO_CONTENT = json.dumps({
    "version": "20240517",
    "general": {
        "links": 0,
        "no_connects": 0,
    },
    "pcbnew": {
        "last_paths": {},
        "page_layout_descr_file": "",
    },
    "schematic": {
        "legacy_lib_dir": "",
        "legacy_lib_list": [],
    },
}, indent=2)

SYM_LIB_TABLE_CONTENT = """(sym_lib_table
  (version 7)
  (lib (name "Device")(type "KiCad")(uri "${KICAD8_SYMBOL_DIR}/Device.kicad_sym")(options "")(descr "Device symbols"))
  (lib (name "power")(type "KiCad")(uri "${KICAD8_SYMBOL_DIR}/power.kicad_sym")(options "")(descr "Power symbols"))
)"""

FP_LIB_TABLE_CONTENT = """(fp_lib_table
  (version 7)
  (lib (name "tile")(type "KiCad")(uri "${KIPRJMOD}/tile.pretty")(options "")(descr "Tile footprints"))
)"""

DRU_CONTENT = """(version 20240517)
(net_class "Default" ""
  (clearance 0.2)
  (trace_width 0.25)
  (via_dia 0.8)
  (via_drill 0.4)
)
"""


@pytest.fixture
def pro_file(tmp_path: Path) -> Path:
    """Create a temporary .kicad_pro file."""
    path = tmp_path / "board.kicad_pro"
    path.write_text(PRO_CONTENT, encoding="utf-8")
    return path


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a temporary project directory with all project files."""
    (tmp_path / "board.kicad_pro").write_text(PRO_CONTENT, encoding="utf-8")
    (tmp_path / "sym-lib-table").write_text(SYM_LIB_TABLE_CONTENT, encoding="utf-8")
    (tmp_path / "fp-lib-table").write_text(FP_LIB_TABLE_CONTENT, encoding="utf-8")
    (tmp_path / "board.kicad_dru").write_text(DRU_CONTENT, encoding="utf-8")
    return tmp_path


@pytest.fixture
def sym_lib_file(tmp_path: Path) -> Path:
    """Create a temporary sym-lib-table file."""
    path = tmp_path / "sym-lib-table"
    path.write_text(SYM_LIB_TABLE_CONTENT, encoding="utf-8")
    return path


@pytest.fixture
def fp_lib_file(tmp_path: Path) -> Path:
    """Create a temporary fp-lib-table file."""
    path = tmp_path / "fp-lib-table"
    path.write_text(FP_LIB_TABLE_CONTENT, encoding="utf-8")
    return path


@pytest.fixture
def dru_file(tmp_path: Path) -> Path:
    """Create a temporary .kicad_dru file."""
    path = tmp_path / "board.kicad_dru"
    path.write_text(DRU_CONTENT, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProjectFileParsing:
    """Tests for .kicad_pro file parsing."""

    def test_parse_project_file(self, pro_file: Path) -> None:
        """Parse .kicad_pro, verify version and sections present."""
        proj = parse_project_file(pro_file)
        assert proj.version == "20240517"
        assert isinstance(proj.general, dict)
        assert isinstance(proj.pcbnew, dict)
        assert isinstance(proj.schematic, dict)
        assert proj.general.get("no_connects") == 0

    def test_parse_nonexistent_raises(self, tmp_path: Path) -> None:
        """Parsing a non-existent .kicad_pro raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            parse_project_file(tmp_path / "nonexistent.kicad_pro")

    def test_get_project_settings(self, project_dir: Path) -> None:
        """get_project_settings discovers all project files."""
        settings = get_project_settings(project_dir)
        assert "project" in settings
        assert settings["project"]["version"] == "20240517"
        assert "symbol_libraries" in settings
        assert len(settings["symbol_libraries"]) == 2
        assert "footprint_libraries" in settings
        assert len(settings["footprint_libraries"]) == 1


class TestAddLibEntryOp:
    """Tests for add_lib_entry operation via executor."""

    def test_add_lib_entry_op(self, sym_lib_file: Path) -> None:
        """Execute add_lib_entry, verify entry added."""
        executor = OperationExecutor(base_dir=sym_lib_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "add_lib_entry",
                "target_file": "sym-lib-table",
                "lib_name": "MyCustom",
                "lib_type": "KiCad",
                "uri": "${KIPRJMOD}/custom.kicad_sym",
                "description": "Custom symbols",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["lib_name"] == "MyCustom"

        # Verify on disk
        from kicad_agent.project.lib_table import parse_lib_table
        table = parse_lib_table(sym_lib_file)
        assert len(table.entries) == 3
        assert table.get("MyCustom").uri == "${KIPRJMOD}/custom.kicad_sym"


class TestRemoveLibEntryOp:
    """Tests for remove_lib_entry operation via executor."""

    def test_remove_lib_entry_op(self, fp_lib_file: Path) -> None:
        """Execute remove_lib_entry on fp-lib-table, verify removed."""
        executor = OperationExecutor(base_dir=fp_lib_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "remove_lib_entry",
                "target_file": "fp-lib-table",
                "lib_name": "tile",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["lib_name"] == "tile"

        # Verify on disk
        from kicad_agent.project.lib_table import parse_lib_table
        table = parse_lib_table(fp_lib_file)
        assert len(table.entries) == 0


class TestAddNetClassOp:
    """Tests for add_net_class operation via executor."""

    def test_add_net_class_op(self, dru_file: Path) -> None:
        """Execute add_net_class, verify net class added."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "add_net_class",
                "target_file": "board.kicad_dru",
                "name": "Power",
                "clearance": 0.3,
                "track_width": 0.5,
                "via_diameter": 1.0,
                "via_drill": 0.6,
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["net_class"] == "Power"

        # Verify on disk
        from kicad_agent.project.design_rules import parse_design_rules
        dru = parse_design_rules(dru_file)
        names = [nc.name for nc in dru.net_classes]
        assert "Power" in names
        power = next(nc for nc in dru.net_classes if nc.name == "Power")
        assert power.clearance == 0.3


class TestAddDesignRuleOp:
    """Tests for add_design_rule operation via executor."""

    def test_add_design_rule_op(self, dru_file: Path) -> None:
        """Execute add_design_rule, verify rule added."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "add_design_rule",
                "target_file": "board.kicad_dru",
                "name": "HV_clearance",
                "constraint_type": "clearance",
                "constraint_values": {"min": "0.5"},
                "condition": "A.NetClass == 'HV'",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["rule_name"] == "HV_clearance"

        # Verify on disk
        from kicad_agent.project.design_rules import parse_design_rules
        dru = parse_design_rules(dru_file)
        assert len(dru.custom_rules) == 1
        assert dru.custom_rules[0].name == "HV_clearance"


class TestTargetFileValidation:
    """Tests for TargetFile validator with project file types."""

    def test_sym_lib_table_accepted(self) -> None:
        """sym-lib-table is a valid TargetFile."""
        op = Operation.model_validate({
            "root": {
                "op_type": "add_lib_entry",
                "target_file": "sym-lib-table",
                "lib_name": "Test",
                "uri": "/path/to/test.kicad_sym",
            }
        })
        assert op.root.target_file == "sym-lib-table"

    def test_fp_lib_table_accepted(self) -> None:
        """fp-lib-table is a valid TargetFile."""
        op = Operation.model_validate({
            "root": {
                "op_type": "add_lib_entry",
                "target_file": "fp-lib-table",
                "lib_name": "Test",
                "uri": "/path/to/test.pretty",
            }
        })
        assert op.root.target_file == "fp-lib-table"

    def test_dru_file_accepted(self) -> None:
        """kicad_dru is a valid TargetFile."""
        op = Operation.model_validate({
            "root": {
                "op_type": "add_net_class",
                "target_file": "board.kicad_dru",
                "name": "Power",
                "clearance": 0.3,
                "track_width": 0.5,
                "via_diameter": 1.0,
                "via_drill": 0.6,
            }
        })
        assert op.root.target_file == "board.kicad_dru"

    def test_invalid_extension_rejected(self) -> None:
        """Non-KiCad extension is rejected by TargetFile."""
        with pytest.raises(Exception):
            Operation.model_validate({
                "root": {
                    "op_type": "add_lib_entry",
                    "target_file": "random.txt",
                    "lib_name": "Test",
                    "uri": "/path",
                }
            })


# ---------------------------------------------------------------------------
# Phase 35: New operation tests (list, modify, remove for lib tables,
# net classes, design rules, and modify_project_settings)
# ---------------------------------------------------------------------------


class TestListLibEntries:
    """Tests for list_lib_entries operation via executor."""

    def test_list_lib_entries_returns_all(self, sym_lib_file: Path) -> None:
        """list_lib_entries returns all entries from a sym-lib-table."""
        executor = OperationExecutor(base_dir=sym_lib_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "list_lib_entries",
                "target_file": "sym-lib-table",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        entries = result["details"]["entries"]
        assert result["details"]["count"] == 2
        assert len(entries) == 2
        # Verify entry fields
        device = next(e for e in entries if e["name"] == "Device")
        assert device["type"] == "KiCad"
        assert "Device.kicad_sym" in device["uri"]

    def test_list_lib_entries_fp_table(self, fp_lib_file: Path) -> None:
        """list_lib_entries works on fp-lib-table."""
        executor = OperationExecutor(base_dir=fp_lib_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "list_lib_entries",
                "target_file": "fp-lib-table",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["count"] == 1
        assert result["details"]["entries"][0]["name"] == "tile"

    def test_list_lib_entries_read_only(self, sym_lib_file: Path) -> None:
        """list_lib_entries does not modify the file."""
        import os
        executor = OperationExecutor(base_dir=sym_lib_file.parent)
        original_mtime = os.path.getmtime(sym_lib_file)
        op = Operation.model_validate({
            "root": {
                "op_type": "list_lib_entries",
                "target_file": "sym-lib-table",
            }
        })
        # Small delay to ensure mtime would differ if file were written
        import time
        time.sleep(0.05)
        executor.execute(op)
        assert os.path.getmtime(sym_lib_file) == original_mtime


class TestListNetClasses:
    """Tests for list_net_classes operation via executor."""

    def test_list_net_classes_returns_all(self, dru_file: Path) -> None:
        """list_net_classes returns all net classes from .kicad_dru."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "list_net_classes",
                "target_file": "board.kicad_dru",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        classes = result["details"]["net_classes"]
        assert result["details"]["count"] == 1
        assert len(classes) == 1
        assert classes[0]["name"] == "Default"
        assert classes[0]["clearance"] == 0.2
        assert classes[0]["track_width"] == 0.25

    def test_list_net_classes_multiple(self, dru_file: Path) -> None:
        """list_net_classes returns all after adding a second class."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        # Add a Power net class first
        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_net_class",
                "target_file": "board.kicad_dru",
                "name": "Power",
                "clearance": 0.3,
                "track_width": 0.5,
                "via_diameter": 1.0,
                "via_drill": 0.6,
            }
        })
        executor.execute(add_op)
        # Now list
        list_op = Operation.model_validate({
            "root": {
                "op_type": "list_net_classes",
                "target_file": "board.kicad_dru",
            }
        })
        result = executor.execute(list_op)
        assert result["success"] is True
        assert result["details"]["count"] == 2
        names = [nc["name"] for nc in result["details"]["net_classes"]]
        assert "Default" in names
        assert "Power" in names


class TestListDesignRules:
    """Tests for list_design_rules operation via executor."""

    def test_list_design_rules_empty(self, dru_file: Path) -> None:
        """list_design_rules returns empty when no rules defined."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "list_design_rules",
                "target_file": "board.kicad_dru",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["count"] == 0
        assert result["details"]["rules"] == []

    def test_list_design_rules_returns_all(self, dru_file: Path) -> None:
        """list_design_rules returns all rules after adding one."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        # Add a rule first
        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_design_rule",
                "target_file": "board.kicad_dru",
                "name": "HV_clearance",
                "constraint_type": "clearance",
                "constraint_values": {"min": "0.5"},
                "condition": "A.NetClass == 'HV'",
            }
        })
        executor.execute(add_op)
        # Now list
        list_op = Operation.model_validate({
            "root": {
                "op_type": "list_design_rules",
                "target_file": "board.kicad_dru",
            }
        })
        result = executor.execute(list_op)
        assert result["success"] is True
        assert result["details"]["count"] == 1
        rule = result["details"]["rules"][0]
        assert rule["name"] == "HV_clearance"
        assert rule["constraint_type"] == "clearance"
        assert rule["constraint_values"] == {"min": "0.5"}


class TestModifyNetClass:
    """Tests for modify_net_class operation via executor."""

    def test_modify_net_class_updates_clearance(self, dru_file: Path) -> None:
        """modify_net_class updates clearance on existing class."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "modify_net_class",
                "target_file": "board.kicad_dru",
                "name": "Default",
                "clearance": 0.5,
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["net_class"] == "Default"
        assert result["details"]["updated_fields"] == ["clearance"]

        # Verify on disk
        from kicad_agent.project.design_rules import parse_design_rules
        dru = parse_design_rules(dru_file)
        default = next(nc for nc in dru.net_classes if nc.name == "Default")
        assert default.clearance == 0.5
        # Other fields unchanged
        assert default.track_width == 0.25

    def test_modify_net_class_updates_track_width(self, dru_file: Path) -> None:
        """modify_net_class updates track_width on existing class."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "modify_net_class",
                "target_file": "board.kicad_dru",
                "name": "Default",
                "track_width": 0.4,
            }
        })
        result = executor.execute(op)
        assert result["success"] is True

        # Verify on disk
        from kicad_agent.project.design_rules import parse_design_rules
        dru = parse_design_rules(dru_file)
        default = next(nc for nc in dru.net_classes if nc.name == "Default")
        assert default.track_width == 0.4
        # Clearance unchanged
        assert default.clearance == 0.2

    def test_modify_net_class_nonexistent_raises(self, dru_file: Path) -> None:
        """modify_net_class raises KeyError for non-existent net class."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "modify_net_class",
                "target_file": "board.kicad_dru",
                "name": "NonExistent",
                "clearance": 0.5,
            }
        })
        with pytest.raises(KeyError, match="not found"):
            executor.execute(op)


class TestRemoveNetClass:
    """Tests for remove_net_class operation via executor."""

    def test_remove_net_class_deletes(self, dru_file: Path) -> None:
        """remove_net_class deletes a named class from .kicad_dru."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "remove_net_class",
                "target_file": "board.kicad_dru",
                "name": "Default",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["net_class"] == "Default"
        assert result["details"]["action"] == "removed"

        # Verify on disk
        from kicad_agent.project.design_rules import parse_design_rules
        dru = parse_design_rules(dru_file)
        assert len(dru.net_classes) == 0

    def test_remove_net_class_nonexistent_raises(self, dru_file: Path) -> None:
        """remove_net_class raises KeyError for non-existent name."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "remove_net_class",
                "target_file": "board.kicad_dru",
                "name": "Ghost",
            }
        })
        with pytest.raises(KeyError, match="not found"):
            executor.execute(op)


class TestModifyDesignRule:
    """Tests for modify_design_rule operation via executor."""

    def test_modify_design_rule_updates_constraint_values(self, dru_file: Path) -> None:
        """modify_design_rule updates constraint_values on existing rule."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        # Add a rule first
        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_design_rule",
                "target_file": "board.kicad_dru",
                "name": "HV_clearance",
                "constraint_type": "clearance",
                "constraint_values": {"min": "0.5"},
                "condition": "A.NetClass == 'HV'",
            }
        })
        executor.execute(add_op)
        # Modify it
        mod_op = Operation.model_validate({
            "root": {
                "op_type": "modify_design_rule",
                "target_file": "board.kicad_dru",
                "name": "HV_clearance",
                "constraint_values": {"min": "1.0"},
            }
        })
        result = executor.execute(mod_op)
        assert result["success"] is True
        assert result["details"]["rule_name"] == "HV_clearance"

        # Verify on disk
        from kicad_agent.project.design_rules import parse_design_rules
        dru = parse_design_rules(dru_file)
        rule = next(r for r in dru.custom_rules if r.name == "HV_clearance")
        assert rule.constraint_values == {"min": "1.0"}
        # constraint_type unchanged
        assert rule.constraint_type == "clearance"

    def test_modify_design_rule_nonexistent_raises(self, dru_file: Path) -> None:
        """modify_design_rule raises KeyError for non-existent rule."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "modify_design_rule",
                "target_file": "board.kicad_dru",
                "name": "NoSuchRule",
                "constraint_values": {"min": "1.0"},
            }
        })
        with pytest.raises(KeyError, match="not found"):
            executor.execute(op)


class TestRemoveDesignRule:
    """Tests for remove_design_rule operation via executor."""

    def test_remove_design_rule_deletes(self, dru_file: Path) -> None:
        """remove_design_rule deletes a named rule from .kicad_dru."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        # Add a rule first
        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_design_rule",
                "target_file": "board.kicad_dru",
                "name": "HV_clearance",
                "constraint_type": "clearance",
                "constraint_values": {"min": "0.5"},
                "condition": "A.NetClass == 'HV'",
            }
        })
        executor.execute(add_op)
        # Remove it
        rm_op = Operation.model_validate({
            "root": {
                "op_type": "remove_design_rule",
                "target_file": "board.kicad_dru",
                "name": "HV_clearance",
            }
        })
        result = executor.execute(rm_op)
        assert result["success"] is True
        assert result["details"]["rule_name"] == "HV_clearance"
        assert result["details"]["action"] == "removed"

        # Verify on disk
        from kicad_agent.project.design_rules import parse_design_rules
        dru = parse_design_rules(dru_file)
        assert len(dru.custom_rules) == 0


class TestModifyProjectSettings:
    """Tests for modify_project_settings operation via executor."""

    def test_modify_project_settings_merges(self, pro_file: Path) -> None:
        """modify_project_settings merges updates into .kicad_pro JSON."""
        executor = OperationExecutor(base_dir=pro_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "modify_project_settings",
                "target_file": "board.kicad_pro",
                "updates": {
                    "general": {"no_connects": 5},
                    "pcbnew": {"new_key": "new_value"},
                },
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["updated_sections"] == ["general", "pcbnew"]

        # Verify on disk
        data = json.loads(pro_file.read_text(encoding="utf-8"))
        assert data["general"]["no_connects"] == 5
        assert data["general"]["links"] == 0  # preserved
        assert data["pcbnew"]["new_key"] == "new_value"
        assert data["schematic"]["legacy_lib_dir"] == ""  # preserved

    def test_modify_project_settings_preserves_unknown_keys(self, pro_file: Path) -> None:
        """modify_project_settings does not lose unknown keys."""
        # Add an unknown key to the file
        data = json.loads(pro_file.read_text(encoding="utf-8"))
        data["custom_section"] = {"my_key": "my_value"}
        pro_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        executor = OperationExecutor(base_dir=pro_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "modify_project_settings",
                "target_file": "board.kicad_pro",
                "updates": {
                    "general": {"links": 10},
                },
            }
        })
        executor.execute(op)

        # Verify unknown key preserved
        updated = json.loads(pro_file.read_text(encoding="utf-8"))
        assert updated["custom_section"]["my_key"] == "my_value"
        assert updated["general"]["links"] == 10


class TestWriteProjectSettings:
    """Tests for write_project_settings function directly."""

    def test_write_project_settings_atomic(self, tmp_path: Path) -> None:
        """write_project_settings uses atomic write (file always valid)."""
        pro = tmp_path / "test.kicad_pro"
        pro.write_text(json.dumps({"version": "1", "key": "value"}), encoding="utf-8")

        write_project_settings(pro, {"key": "updated"})
        data = json.loads(pro.read_text(encoding="utf-8"))
        assert data["key"] == "updated"
        assert data["version"] == "1"

    def test_write_project_settings_deep_merge(self, tmp_path: Path) -> None:
        """write_project_settings deep-merges nested dicts."""
        pro = tmp_path / "test.kicad_pro"
        pro.write_text(json.dumps({
            "section": {"a": 1, "b": 2, "nested": {"x": 10}},
        }), encoding="utf-8")

        write_project_settings(pro, {"section": {"b": 20, "nested": {"y": 30}}})
        data = json.loads(pro.read_text(encoding="utf-8"))
        assert data["section"]["a"] == 1  # preserved
        assert data["section"]["b"] == 20  # updated
        assert data["section"]["nested"]["x"] == 10  # deep preserved
        assert data["section"]["nested"]["y"] == 30  # deep added


class TestNewOpTypeValidation:
    """Test Operation.model_validate accepts each new op_type string."""

    @pytest.mark.parametrize("op_type,extra", [
        ("list_lib_entries", {"target_file": "sym-lib-table"}),
        ("modify_net_class", {"target_file": "b.kicad_dru", "name": "Default", "clearance": 0.5}),
        ("remove_net_class", {"target_file": "b.kicad_dru", "name": "Default"}),
        ("list_net_classes", {"target_file": "b.kicad_dru"}),
        ("modify_design_rule", {"target_file": "b.kicad_dru", "name": "Rule1", "constraint_values": {"min": "1.0"}}),
        ("remove_design_rule", {"target_file": "b.kicad_dru", "name": "Rule1"}),
        ("list_design_rules", {"target_file": "b.kicad_dru"}),
        ("modify_project_settings", {"target_file": "b.kicad_pro", "updates": {"general": {}}}),
    ])
    def test_op_type_validates(self, op_type: str, extra: dict) -> None:
        """Each new op_type validates through Operation.model_validate."""
        op = Operation.model_validate({"root": {"op_type": op_type, **extra}})
        assert op.root.op_type == op_type
