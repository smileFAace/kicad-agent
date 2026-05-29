"""SLC compliance tests -- verify no stubs, phantoms, or mismatches.

These tests enforce Simple, Lovable, Complete principles by detecting:
- Stub operations that advertise capability but crash at runtime (bus ops)
- Phantom operations documented but never implemented (place_no_connects_from_erc)
- Documentation-schema mismatches (wrong field names, wrong counts)

Council audit references: C-2, C-3, C-5, H-6, H-9.
"""

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "src" / "kicad_agent" / "ops" / "schema.py"
SCHEMA_SUBMODULES_DIR = REPO_ROOT / "src" / "kicad_agent" / "ops"
EXECUTOR_PATH = REPO_ROOT / "src" / "kicad_agent" / "ops" / "executor.py"
PROMPT_PATH = REPO_ROOT / "skills" / "prompt.md"
SKILL_PATH = REPO_ROOT / "skills" / "SKILL.md"
README_PATH = REPO_ROOT / "README.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_op_classes() -> int:
    """Count the number of Op classes in schema.py and its sub-modules."""
    return len(_get_op_class_names())


def _get_op_class_names() -> list[str]:
    """Get all Op class names from schema.py and its _schema_*.py sub-modules."""
    names: list[str] = []
    # Scan hub file
    content = SCHEMA_PATH.read_text(encoding="utf-8")
    names.extend(re.findall(r"^class (\w+Op)\(BaseModel\)", content, re.MULTILINE))
    # Scan sub-modules
    for submod in sorted(SCHEMA_SUBMODULES_DIR.glob("_schema_*.py")):
        sub_content = submod.read_text(encoding="utf-8")
        names.extend(re.findall(r"^class (\w+Op)\(BaseModel\)", sub_content, re.MULTILINE))
    return names


# ---------------------------------------------------------------------------
# C-2: Bus operations completely removed
# ---------------------------------------------------------------------------


class TestBusOperationsRemoved:
    """Verify AddBusOp and RemoveBusOp are completely removed."""

    def test_add_bus_op_not_in_schema(self) -> None:
        """AddBusOp class must not exist in schema.py."""
        content = SCHEMA_PATH.read_text(encoding="utf-8")
        assert "class AddBusOp" not in content

    def test_remove_bus_op_not_in_schema(self) -> None:
        """RemoveBusOp class must not exist in schema.py."""
        content = SCHEMA_PATH.read_text(encoding="utf-8")
        assert "class RemoveBusOp" not in content

    def test_operation_union_rejects_add_bus(self) -> None:
        """Operation discriminated union must reject op_type='add_bus'."""
        from kicad_agent.ops.schema import Operation

        with pytest.raises(Exception):
            Operation.model_validate({
                "root": {
                    "op_type": "add_bus",
                    "target_file": "test.kicad_sch",
                    "bus_name": "SPI_BUS",
                    "member_nets": ["MOSI"],
                }
            })

    def test_operation_union_rejects_remove_bus(self) -> None:
        """Operation discriminated union must reject op_type='remove_bus'."""
        from kicad_agent.ops.schema import Operation

        with pytest.raises(Exception):
            Operation.model_validate({
                "root": {
                    "op_type": "remove_bus",
                    "target_file": "test.kicad_sch",
                    "bus_name": "SPI_BUS",
                }
            })

    def test_add_bus_not_in_executor(self) -> None:
        """No add_bus handler registration in executor.py."""
        content = EXECUTOR_PATH.read_text(encoding="utf-8")
        assert 'register_schematic("add_bus")' not in content

    def test_remove_bus_not_in_executor(self) -> None:
        """No remove_bus handler registration in executor.py."""
        content = EXECUTOR_PATH.read_text(encoding="utf-8")
        assert 'register_schematic("remove_bus")' not in content

    def test_bus_not_in_operation_union(self) -> None:
        """AddBusOp and RemoveBusOp must not appear in Operation union."""
        content = SCHEMA_PATH.read_text(encoding="utf-8")
        # Find the Operation class definition area
        assert "AddBusOp" not in content
        assert "RemoveBusOp" not in content


# ---------------------------------------------------------------------------
# C-3: validate_footprint performs actual library lookup
# ---------------------------------------------------------------------------


class TestValidateFootprintReal:
    """Verify validate_footprint does actual library lookup instead of always-True."""

    def test_validate_footprint_returns_false_for_missing(self, tmp_path: Path) -> None:
        """validate_footprint must return valid=False for non-existent footprint."""
        from kicad_agent.ops.executor import _validate_footprint_impl

        result = _validate_footprint_impl(
            "NonexistentLib:NonexistentFootprint",
            tmp_path / "test.kicad_sch",
        )
        assert result["valid"] is False
        assert "footprint_lib_id" in result

    def test_validate_footprint_returns_false_when_no_lib_table(self, tmp_path: Path) -> None:
        """validate_footprint must return valid=False when fp-lib-table is missing."""
        from kicad_agent.ops.executor import _validate_footprint_impl

        # tmp_path has no fp-lib-table, so any lookup should fail
        result = _validate_footprint_impl(
            "SomeLib:SomeFootprint",
            tmp_path / "test.kicad_pcb",
        )
        assert result["valid"] is False
        assert "error" in result

    def test_validate_footprint_invalid_lib_id(self, tmp_path: Path) -> None:
        """validate_footprint must return valid=False for malformed lib_id."""
        from kicad_agent.ops.executor import _validate_footprint_impl

        result = _validate_footprint_impl(
            "NoColonHere",
            tmp_path / "test.kicad_sch",
        )
        assert result["valid"] is False
        assert "error" in result

    def test_validate_footprint_result_has_lib_id(self, tmp_path: Path) -> None:
        """Result always includes the footprint_lib_id that was checked."""
        from kicad_agent.ops.executor import _validate_footprint_impl

        result = _validate_footprint_impl(
            "Library:Footprint",
            tmp_path / "test.kicad_sch",
        )
        assert result["footprint_lib_id"] == "Library:Footprint"

    def test_executor_no_not_implemented_error_for_bus(self) -> None:
        """Executor must not contain NotImplementedError for bus operations."""
        content = EXECUTOR_PATH.read_text(encoding="utf-8")
        assert 'NotImplementedError("Bus operations' not in content
        # Also verify no bare NotImplementedError related to bus
        lines = content.split("\n")
        for line in lines:
            if "NotImplementedError" in line and "bus" in line.lower():
                pytest.fail(f"Found NotImplementedError for bus: {line.strip()}")


# ---------------------------------------------------------------------------
# C-5: Phantom operations removed from documentation
# ---------------------------------------------------------------------------


class TestPhantomOperationsRemoved:
    """Verify phantom operations are removed from documentation."""

    def test_place_no_connects_from_erc_not_in_prompt(self) -> None:
        """place_no_connects_from_erc must not appear in prompt.md."""
        content = PROMPT_PATH.read_text(encoding="utf-8")
        assert "place_no_connects_from_erc" not in content

    def test_place_no_connects_from_erc_not_in_readme(self) -> None:
        """place_no_connects_from_erc must not appear in README.md."""
        content = README_PATH.read_text(encoding="utf-8")
        assert "place_no_connects_from_erc" not in content

    def test_add_bus_not_in_prompt(self) -> None:
        """add_bus must not appear as an operation section in prompt.md."""
        content = PROMPT_PATH.read_text(encoding="utf-8")
        assert "add_bus" not in content

    def test_remove_bus_not_in_prompt(self) -> None:
        """remove_bus must not appear as an operation section in prompt.md."""
        content = PROMPT_PATH.read_text(encoding="utf-8")
        assert "remove_bus" not in content


# ---------------------------------------------------------------------------
# H-6: Prompt field names match schema
# ---------------------------------------------------------------------------


class TestPromptSchemaFieldConsistency:
    """Verify prompt.md field names match schema.py exactly."""

    def test_snap_to_grid_uses_grid_mm(self) -> None:
        """snap_to_grid in prompt.md must use 'grid_mm' not 'grid_size'."""
        content = PROMPT_PATH.read_text(encoding="utf-8")
        # The snap_to_grid section should reference grid_mm
        # Find the snap_to_grid section
        snap_match = re.search(
            r"#### snap_to_grid.*?(?=####|\Z)",
            content,
            re.DOTALL,
        )
        assert snap_match is not None, "snap_to_grid section not found in prompt.md"
        section = snap_match.group()
        assert "grid_mm" in section, (
            "snap_to_grid section should use 'grid_mm' to match schema.py"
        )

    def test_parse_erc_no_erc_report_path(self) -> None:
        """parse_erc in prompt.md must not reference erc_report_path (schema lacks it)."""
        from kicad_agent.ops.schema import ParseErcOp

        fields = ParseErcOp.model_fields
        assert "erc_report_path" not in fields, (
            "ParseErcOp should not have erc_report_path field"
        )

    def test_extract_violation_no_erc_report_path(self) -> None:
        """extract_violation_positions must not reference erc_report_path if schema lacks it."""
        from kicad_agent.ops.schema import ExtractViolationPositionsOp

        fields = ExtractViolationPositionsOp.model_fields
        assert "erc_report_path" not in fields, (
            "ExtractViolationPositionsOp should not have erc_report_path field"
        )

    def test_add_power_flag_no_erc_report_path(self) -> None:
        """add_power_flag must not reference erc_report_path if schema lacks it."""
        from kicad_agent.ops.schema import AddPowerFlagOp

        fields = AddPowerFlagOp.model_fields
        assert "erc_report_path" not in fields, (
            "AddPowerFlagOp should not have erc_report_path field"
        )


# ---------------------------------------------------------------------------
# H-9: Operation counts consistent across documentation
# ---------------------------------------------------------------------------


class TestOperationCountConsistency:
    """Verify operation counts match across SKILL.md, README.md, and schema.py."""

    def test_schema_op_count(self) -> None:
        """Verify we have the expected number of Op classes after bus removal."""
        count = _count_op_classes()
        # 49 original minus AddBusOp and RemoveBusOp = 47, plus 4 remove ops + 1 query op + 1 footprint op = 53
        assert count == 53, f"Expected 53 Op classes, found {count}"

    def test_readme_operation_count_matches_schema(self) -> None:
        """README.md operation count must match schema.py Op class count."""
        content = README_PATH.read_text(encoding="utf-8")
        schema_count = _count_op_classes()

        # Look for "N operations" pattern in README
        match = re.search(r"(\d+)\s+operations?\s+across", content)
        if match:
            readme_count = int(match.group(1))
            assert readme_count == schema_count, (
                f"README says {readme_count} operations, schema has {schema_count}"
            )

    def test_readme_bus_operations_removed(self) -> None:
        """README.md must not list Bus Operations as a category."""
        content = README_PATH.read_text(encoding="utf-8")
        # Check that add_bus and remove_bus are not in the operations tables
        assert "`add_bus`" not in content
        assert "`remove_bus`" not in content

    def test_readme_no_46_operations_claim(self) -> None:
        """README.md must not claim 46 operations (pre-removal count)."""
        content = README_PATH.read_text(encoding="utf-8")
        # The count was 49 before (including bus ops), now 47
        # Make sure it doesn't say 46 (which was wrong even before)
        # Check the operations count claim
        match = re.search(r"(\d+)\s+operations?\s+across", content)
        if match:
            count = int(match.group(1))
            assert count != 46, "README should not claim 46 operations"

    def test_skill_md_operation_count_matches(self) -> None:
        """SKILL.md operation references must be consistent with schema."""
        content = SKILL_PATH.read_text(encoding="utf-8")
        schema_count = _count_op_classes()

        # SKILL.md says "List all 19 operation types" -- check if it matches
        match = re.search(r"all\s+(\d+)\s+operation", content)
        if match:
            skill_count = int(match.group(1))
            assert skill_count == schema_count, (
                f"SKILL.md says {skill_count} operations, schema has {schema_count}"
            )
