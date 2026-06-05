"""Code quality tests -- verify schema split, dead code removal, and quality fixes.

Tests for Plan 24-03: Council Audit Remediation code quality improvements.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "src" / "kicad_agent" / "ops" / "schema.py"
SCHEMA_DIR = REPO_ROOT / "src" / "kicad_agent" / "ops"
FORMAT_CONVERT_PATH = REPO_ROOT / "src" / "kicad_agent" / "ops" / "format_convert.py"
BEST_OF_N_PATH = REPO_ROOT / "src" / "kicad_agent" / "inference" / "best_of_n.py"
HANDLER_PATH = REPO_ROOT / "src" / "kicad_agent" / "handler.py"
EXECUTOR_PATH = REPO_ROOT / "src" / "kicad_agent" / "ops" / "executor.py"


# ---------------------------------------------------------------------------
# Task 1: Schema split tests
# ---------------------------------------------------------------------------


class TestSchemaSplit:
    """Verify schema.py was split into sub-modules with re-exports."""

    def test_schema_imports_add_component(self) -> None:
        """from kicad_agent.ops.schema import AddComponentOp still works."""
        from kicad_agent.ops.schema import AddComponentOp
        assert AddComponentOp is not None

    def test_schema_imports_operation(self) -> None:
        """from kicad_agent.ops.schema import Operation still works."""
        from kicad_agent.ops.schema import Operation
        assert Operation is not None

    def test_operation_union_includes_all_op_types(self) -> None:
        """Operation discriminated union includes all expected op_types."""
        from kicad_agent.ops.schema import Operation

        schema = Operation.model_json_schema()
        # Get the discriminator values from the schema
        op_types = set()
        for variant in schema.get("$defs", {}).values():
            if "properties" in variant and "op_type" in variant["properties"]:
                const = variant["properties"]["op_type"].get("const")
                if const:
                    op_types.add(const)

        # Verify all expected op types are present
        expected_ops = {
            "add_component", "remove_component", "move_component",
            "modify_property", "duplicate_component", "array_replicate",
            "add_net", "remove_net", "rename_net",
            "renumber_refs", "validate_refs", "annotate", "cross_ref_check",
            "assign_footprint", "swap_footprint", "validate_footprint",
            "verify_pin_map", "update_footprint_from_library",
            "add_wire", "add_label", "add_power", "add_no_connect", "add_junction",
            "add_lib_entry", "remove_lib_entry",
            "add_net_class", "add_design_rule",
            "repair_schematic", "validate_power_nets", "validate_schematic",
            "parse_erc", "extract_violation_positions", "validate_hlabels",
            "convert_kicad6_to_10", "snap_to_grid", "add_power_flag",
            "rebuild_root_sheet",
            "add_copper_zone", "set_board_outline", "assign_net_class",
            "auto_route",
            "create_schematic", "create_pcb", "create_project",
            "create_symbol", "embed_symbol", "swap_symbol",
            "add_sheet", "add_sheet_pin", "navigate_hierarchy",
        }
        assert expected_ops.issubset(op_types), (
            f"Missing op_types: {expected_ops - op_types}"
        )

    def test_get_operation_schema_works(self) -> None:
        """get_operation_schema() still works and returns correct schema."""
        from kicad_agent.ops.schema import get_operation_schema
        schema = get_operation_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema or "$defs" in schema

    def test_submodules_exist(self) -> None:
        """14 _schema_*.py sub-modules exist."""
        submods = sorted(SCHEMA_DIR.glob("_schema_*.py"))
        assert len(submods) == 14, (
            f"Expected 14 sub-modules, found {len(submods)}: "
            f"{[p.name for p in submods]}"
        )

    def test_submodule_classes(self) -> None:
        """Each sub-module has the expected classes."""
        from kicad_agent.ops._schema_component import (
            AddComponentOp, RemoveComponentOp, MoveComponentOp,
            ModifyPropertyOp, DuplicateComponentOp, ArrayReplicateOp,
        )
        from kicad_agent.ops._schema_net import AddNetOp, RemoveNetOp, RenameNetOp
        from kicad_agent.ops._schema_reference import (
            RenumberRefsOp, ValidateRefsOp, AnnotateOp, CrossRefCheckOp,
        )
        from kicad_agent.ops._schema_footprint import (
            AssignFootprintOp, SwapFootprintOp, ValidateFootprintOp,
            VerifyPinMapOp, UpdateFootprintFromLibraryOp,
        )
        from kicad_agent.ops._schema_wire import (
            AddWireOp, ConnectPinsOp, AddLabelOp, AddPowerOp, AddNoConnectOp, AddJunctionOp,
        )
        from kicad_agent.ops._schema_library import AddLibEntryOp, RemoveLibEntryOp
        from kicad_agent.ops._schema_pcb import (
            AddNetClassOp, AddDesignRuleOp, AddCopperZoneOp,
            SetBoardOutlineOp, AssignNetClassOp, AutoRouteOp,
        )
        from kicad_agent.ops._schema_validation import (
            ValidatePowerNetsOp, ValidateSchematicOp, ParseErcOp,
            ExtractViolationPositionsOp, ValidateHlabelsOp,
        )
        from kicad_agent.ops._schema_create import (
            CreateSchematicOp, CreatePcbOp, CreateProjectOp,
            CreateSymbolOp, EmbedSymbolOp,
        )
        from kicad_agent.ops._schema_repair import (
            RepairSchematicOp, ConvertKicad6To10Op, SnapToGridOp,
            AddPowerFlagOp, RebuildRootSheetOp, SwapSymbolOp,
        )
        from kicad_agent.ops._schema_remove import (
            RemoveWireOp, RemoveLabelOp, RemoveJunctionOp, RemoveNoConnectOp,
        )

    def test_safe_id_pattern_in_schema_only(self) -> None:
        """_SAFE_ID_PATTERN is defined in schema.py (canonical location)."""
        content = SCHEMA_PATH.read_text(encoding="utf-8")
        assert "_SAFE_ID_PATTERN" in content

    def test_external_import_compatibility(self) -> None:
        """External code can import all Op types from schema."""
        from kicad_agent.ops.schema import (
            AddComponentOp, RemoveComponentOp, MoveComponentOp,
            ModifyPropertyOp, DuplicateComponentOp, ArrayReplicateOp,
            AddNetOp, RemoveNetOp, RenameNetOp,
            RenumberRefsOp, ValidateRefsOp, AnnotateOp, CrossRefCheckOp,
            AssignFootprintOp, SwapFootprintOp, ValidateFootprintOp,
            VerifyPinMapOp, UpdateFootprintFromLibraryOp,
            AddWireOp, ConnectPinsOp, AddLabelOp, AddPowerOp, AddNoConnectOp, AddJunctionOp,
            AddLibEntryOp, RemoveLibEntryOp,
            AddNetClassOp, AddDesignRuleOp,
            RepairSchematicOp, ValidatePowerNetsOp, ValidateSchematicOp,
            ParseErcOp, ExtractViolationPositionsOp, ValidateHlabelsOp,
            ConvertKicad6To10Op, SnapToGridOp, AddPowerFlagOp,
            RebuildRootSheetOp,
            AddCopperZoneOp, SetBoardOutlineOp, AssignNetClassOp,
            AutoRouteOp,
            CreateSchematicOp, CreatePcbOp, CreateProjectOp,
            CreateSymbolOp, EmbedSymbolOp, SwapSymbolOp,
            Operation, get_operation_schema,
        )


# ---------------------------------------------------------------------------
# Task 2: Dead code removal and quality fix tests
# ---------------------------------------------------------------------------


class TestDeadCodeRemoval:
    """Verify dead code was removed."""

    def test_fix_sheet_instances_removed(self) -> None:
        """_fix_sheet_instances no longer exists in format_convert.py."""
        content = FORMAT_CONVERT_PATH.read_text(encoding="utf-8")
        assert "_fix_sheet_instances" not in content, (
            "_fix_sheet_instances should be removed from format_convert.py"
        )

    def test_n_complete_removed_from_best_of_n(self) -> None:
        """n_complete parameter removed from best_of_n_select."""
        content = BEST_OF_N_PATH.read_text(encoding="utf-8")
        assert "n_complete" not in content, (
            "n_complete should be removed from best_of_n.py"
        )

    def test_no_assert_in_best_of_n(self) -> None:
        """No assert in production logic in best_of_n.py."""
        content = BEST_OF_N_PATH.read_text(encoding="utf-8")
        assert "assert best is not None" not in content, (
            "assert should be replaced with ValueError in best_of_n.py"
        )

    def test_best_of_n_raises_valueerror(self) -> None:
        """best_of_n_select raises ValueError when no valid chain found."""
        from kicad_agent.inference.best_of_n import best_of_n_select
        with pytest.raises(ValueError, match="chains list must not be empty"):
            best_of_n_select([], None)

    def test_handler_docstring_accurate(self) -> None:
        """handler.py docstring does not say 'does NOT execute'."""
        content = HANDLER_PATH.read_text(encoding="utf-8")
        assert "does NOT execute" not in content, (
            "handler.py docstring should not say 'does NOT execute'"
        )

    def test_no_redundant_exception_catch(self) -> None:
        """No 'except (ValueError, Exception)' pattern exists anywhere."""
        import subprocess
        result = subprocess.run(
            ["grep", "-r", "except (ValueError, Exception)",
             str(REPO_ROOT / "src")],
            capture_output=True, text=True,
        )
        assert result.returncode != 0 or not result.stdout.strip(), (
            f"Found redundant 'except (ValueError, Exception)' pattern: "
            f"{result.stdout}"
        )

    def test_no_function_level_import_dataclasses_in_executor(self) -> None:
        """No function-level 'import dataclasses' in executor.py."""
        content = EXECUTOR_PATH.read_text(encoding="utf-8")
        lines = content.split("\n")
        in_function = False
        indent_level = 0
        for line in lines:
            stripped = line.lstrip()
            current_indent = len(line) - len(stripped)
            if stripped.startswith("def ") and stripped.endswith(":"):
                in_function = True
                indent_level = current_indent
            elif in_function and current_indent <= indent_level and stripped and not stripped.startswith("#"):
                in_function = False
            if in_function and "import dataclasses" in stripped:
                pytest.fail(
                    f"Found function-level 'import dataclasses' in executor.py: {line}"
                )
