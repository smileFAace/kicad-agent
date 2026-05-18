"""Tests for reference management operation schema validation and SchematicIR methods.

Tests cover:
  - Schema validation for RenumberRefsOp, ValidateRefsOp, AnnotateOp, CrossRefCheckOp
  - SchematicIR reference management: renumber, validate uniqueness, annotate, cross-ref check
"""

import pytest
from pydantic import ValidationError

from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.schema import (
    AnnotateOp,
    CrossRefCheckOp,
    Operation,
    RenumberRefsOp,
    ValidateRefsOp,
    get_operation_schema,
)
from kicad_agent.parser import parse_schematic


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_renumber_refs_op(**overrides) -> Operation:
    """Create a valid RenumberRefsOp Operation with sensible defaults."""
    data = {
        "op_type": "renumber_refs",
        "target_file": "schematic.kicad_sch",
    }
    data.update(overrides)
    return Operation.model_validate({"root": data})


def _make_validate_refs_op(**overrides) -> Operation:
    """Create a valid ValidateRefsOp Operation."""
    data = {
        "op_type": "validate_refs",
        "target_file": "schematic.kicad_sch",
    }
    data.update(overrides)
    return Operation.model_validate({"root": data})


def _make_annotate_op(**overrides) -> Operation:
    """Create a valid AnnotateOp Operation."""
    data = {
        "op_type": "annotate",
        "target_file": "schematic.kicad_sch",
    }
    data.update(overrides)
    return Operation.model_validate({"root": data})


def _make_cross_ref_check_op(**overrides) -> Operation:
    """Create a valid CrossRefCheckOp Operation."""
    data = {
        "op_type": "cross_ref_check",
        "target_file": "schematic.kicad_sch",
    }
    data.update(overrides)
    return Operation.model_validate({"root": data})


# ---------------------------------------------------------------------------
# Task 1: Schema validation tests (Tests 1-9)
# ---------------------------------------------------------------------------


class TestRefOpsSchema:
    """Reference management operation schema validation."""

    def test_renumber_refs_with_prefix_validates(self) -> None:
        """Test 1: RenumberRefsOp validates with prefix='R', start_index=1, step=1."""
        op = _make_renumber_refs_op(prefix="R", start_index=1, step=1)
        assert op.root.op_type == "renumber_refs"
        assert op.root.prefix == "R"
        assert op.root.start_index == 1
        assert op.root.step == 1

    def test_renumber_refs_defaults(self) -> None:
        """Test 2: RenumberRefsOp defaults: prefix='', start_index=1, step=1."""
        op = _make_renumber_refs_op()
        assert op.root.prefix == ""
        assert op.root.start_index == 1
        assert op.root.step == 1

    def test_renumber_refs_rejects_start_index_below_one(self) -> None:
        """Test 3: RenumberRefsOp rejects start_index < 1."""
        with pytest.raises(ValidationError):
            _make_renumber_refs_op(start_index=0)

    def test_renumber_refs_rejects_step_below_one(self) -> None:
        """Test 4: RenumberRefsOp rejects step < 1."""
        with pytest.raises(ValidationError):
            _make_renumber_refs_op(step=0)

    def test_validate_refs_validates(self) -> None:
        """Test 5: ValidateRefsOp validates with target_file."""
        op = _make_validate_refs_op()
        assert op.root.op_type == "validate_refs"

    def test_annotate_op_validates(self) -> None:
        """Test 6: AnnotateOp validates with target_file and optional prefix_filter."""
        op = _make_annotate_op()
        assert op.root.op_type == "annotate"
        assert op.root.prefix_filter == ""

    def test_annotate_op_with_prefix_filter(self) -> None:
        """AnnotateOp accepts prefix_filter."""
        op = _make_annotate_op(prefix_filter="R")
        assert op.root.prefix_filter == "R"

    def test_cross_ref_check_op_validates(self) -> None:
        """Test 7: CrossRefCheckOp validates with target_file."""
        op = _make_cross_ref_check_op()
        assert op.root.op_type == "cross_ref_check"

    def test_operation_routes_all_ref_types(self) -> None:
        """Test 8: Operation.model_validate routes all four new op_types correctly."""
        op_types = ["renumber_refs", "validate_refs", "annotate", "cross_ref_check"]
        for ot in op_types:
            op = Operation.model_validate({
                "root": {
                    "op_type": ot,
                    "target_file": "test.kicad_sch",
                }
            })
            assert op.root.op_type == ot

    def test_get_operation_schema_includes_all_ref_types(self) -> None:
        """Test 9: get_operation_schema() includes RenumberRefsOp, ValidateRefsOp, AnnotateOp, CrossRefCheckOp."""
        schema = get_operation_schema()
        schema_str = str(schema)
        for op_name in ("RenumberRefsOp", "ValidateRefsOp", "AnnotateOp", "CrossRefCheckOp"):
            assert op_name in schema_str, f"{op_name} missing from schema export"


# ---------------------------------------------------------------------------
# Task 2: SchematicIR reference management tests (Tests 10-22)
# ---------------------------------------------------------------------------


class TestSchematicIRGetAllReferences:
    """SchematicIR.get_all_references() tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_sch: pytest.fixture) -> None:
        """Create SchematicIR from Arduino_Mega schematic for each test."""
        _clear_registry()
        result = parse_schematic(arduino_mega_sch)
        self.ir = SchematicIR(_parse_result=result)

    def test_get_all_references_returns_tuples(self) -> None:
        """Test 10: get_all_references returns list of (reference, libId) tuples."""
        refs = self.ir.get_all_references()
        assert len(refs) > 0
        for ref, lib_id in refs:
            assert isinstance(ref, str)
            assert isinstance(lib_id, str)
            assert len(ref) > 0

    def test_get_all_references_includes_known_components(self) -> None:
        """Arduino_Mega fixture has J1-J7 and #PWR01-#PWR07 references."""
        refs = self.ir.get_all_references()
        ref_strs = [r for r, _ in refs]
        # Arduino_Mega has J1 through J7 and power symbols
        assert "J1" in ref_strs
        assert "J7" in ref_strs
        assert "#PWR01" in ref_strs


class TestSchematicIRRenumberReferences:
    """SchematicIR.renumber_references() mutation tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_sch: pytest.fixture) -> None:
        """Create SchematicIR from Arduino_Mega schematic for each test."""
        _clear_registry()
        result = parse_schematic(arduino_mega_sch)
        self.ir = SchematicIR(_parse_result=result)

    def test_renumber_with_prefix(self) -> None:
        """Test 11: renumber_references with prefix='J' renumbers only J-prefixed refs."""
        # First, scramble a J reference to test renumbering
        comp = self.ir.get_component_by_ref("J7")
        assert comp is not None
        self.ir._set_component_reference(comp, "J99")

        changes = self.ir.renumber_references(prefix="J", start_index=1, step=1)
        # Should have changes since J99 was out of sequence
        assert len(changes) > 0

        # After renumber, all J refs should be sequential from J1
        refs_after = self.ir.get_all_references()
        j_refs_after = sorted(
            [r for r, _ in refs_after if r.startswith("J") and not r.endswith("?")],
            key=lambda x: int(x[1:])
        )
        # Arduino_Mega has 7 J components (J1-J7)
        expected = ["J1", "J2", "J3", "J4", "J5", "J6", "J7"]
        assert j_refs_after == expected

    def test_renumber_all_prefixes(self) -> None:
        """Test 12: renumber_references with prefix='' renumbers ALL components grouped by prefix."""
        # Scramble some references to force changes
        comp_j = self.ir.get_component_by_ref("J5")
        assert comp_j is not None
        self.ir._set_component_reference(comp_j, "J88")

        changes = self.ir.renumber_references(prefix="", start_index=1, step=1)
        # Should have changes since J88 was out of sequence
        assert len(changes) > 0

        # After renumber, check that all references are sequential per prefix
        refs_after = self.ir.get_all_references()
        prefix_groups: dict[str, list[int]] = {}
        import re as _re
        for ref, _ in refs_after:
            m = _re.match(r"^([#A-Za-z]+)(\d+)$", ref)
            if m:
                prefix_groups.setdefault(m.group(1), []).append(int(m.group(2)))

        for prefix, nums in prefix_groups.items():
            assert sorted(nums) == list(range(1, len(nums) + 1)), (
                f"Prefix {prefix} numbers not sequential: {sorted(nums)}"
            )

    def test_renumber_records_mutation(self) -> None:
        """Test 13: renumber_references records mutation log entry for each renumbered component."""
        # Scramble to force a change
        comp = self.ir.get_component_by_ref("J3")
        assert comp is not None
        self.ir._set_component_reference(comp, "J50")

        self.ir.renumber_references(prefix="J", start_index=1, step=1)
        mutations = [m for m in self.ir.mutation_log if m["description"] == "renumber_reference"]
        assert len(mutations) > 0

    def test_renumber_sets_dirty(self) -> None:
        """Test 14: renumber_references sets dirty flag on SchematicIR."""
        assert not self.ir.dirty
        # Scramble to force a change
        comp = self.ir.get_component_by_ref("J2")
        assert comp is not None
        self.ir._set_component_reference(comp, "J99")

        self.ir.renumber_references(prefix="J", start_index=1, step=1)
        assert self.ir.dirty


class TestSchematicIRValidateRefs:
    """SchematicIR.validate_reference_uniqueness() tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_sch: pytest.fixture) -> None:
        """Create SchematicIR from Arduino_Mega schematic for each test."""
        _clear_registry()
        result = parse_schematic(arduino_mega_sch)
        self.ir = SchematicIR(_parse_result=result)

    def test_unique_refs_returns_empty(self) -> None:
        """Test 15: validate_reference_uniqueness returns empty list when all refs are unique."""
        # Arduino_Mega fixture has unique references
        duplicates = self.ir.validate_reference_uniqueness()
        # Filter out ?-suffixed refs (allowed duplicates)
        real_dupes = [d for d in duplicates if not d.endswith("?")]
        assert real_dupes == []

    def test_duplicate_refs_detected(self) -> None:
        """Test 16: validate_reference_uniqueness returns duplicate reference strings."""
        # Force a duplicate by renaming a component to match another
        comps = self.ir.components
        # Find two different components
        if len(comps) >= 2:
            # Set the second component's reference to match the first
            first_ref = None
            for prop in comps[0].properties:
                if prop.key == "Reference":
                    first_ref = prop.value
                    break
            if first_ref and not first_ref.endswith("?"):
                for prop in comps[1].properties:
                    if prop.key == "Reference":
                        prop.value = first_ref
                        break
                duplicates = self.ir.validate_reference_uniqueness()
                assert first_ref in duplicates


class TestSchematicIRAnnotate:
    """SchematicIR.annotate_components() tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_sch: pytest.fixture) -> None:
        """Create SchematicIR from Arduino_Mega schematic for each test."""
        _clear_registry()
        result = parse_schematic(arduino_mega_sch)
        self.ir = SchematicIR(_parse_result=result)

    def test_annotate_unannotated(self) -> None:
        """Test 17: annotate_components assigns sequential refs to '?' suffix components."""
        # First, create some unannotated components by setting refs to end with '?'
        comps = self.ir.components
        if len(comps) >= 2:
            # Set last two component references to R? and U?
            for prop in comps[-2].properties:
                if prop.key == "Reference":
                    prop.value = "R?"
                    break
            for prop in comps[-1].properties:
                if prop.key == "Reference":
                    prop.value = "U?"
                    break

            changes = self.ir.annotate_components()
            # Should have annotated at least the two we set up
            assert len(changes) >= 2
            # All old refs should end with '?'
            for old_ref, new_ref in changes:
                assert old_ref.endswith("?")
                assert not new_ref.endswith("?")

    def test_annotate_with_prefix_filter(self) -> None:
        """Test 18: annotate_components with prefix_filter only annotates matching prefix."""
        comps = self.ir.components
        if len(comps) >= 2:
            for prop in comps[-2].properties:
                if prop.key == "Reference":
                    prop.value = "R?"
                    break
            for prop in comps[-1].properties:
                if prop.key == "Reference":
                    prop.value = "U?"
                    break

            changes = self.ir.annotate_components(prefix_filter="R")
            # Should only annotate R?, not U?
            assert all(old.startswith("R") for old, _ in changes)

    def test_annotate_skips_already_annotated(self) -> None:
        """Test 19: annotate_components skips already-annotated components."""
        # All components in Arduino_Mega are already annotated (no '?' refs)
        changes = self.ir.annotate_components()
        assert changes == []


class TestSchematicIRCrossRefCheck:
    """SchematicIR.cross_reference_check() tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_sch: pytest.fixture) -> None:
        """Create SchematicIR from Arduino_Mega schematic for each test."""
        _clear_registry()
        result = parse_schematic(arduino_mega_sch)
        self.ir = SchematicIR(_parse_result=result)

    def test_all_valid_returns_empty(self) -> None:
        """Test 20: cross_reference_check returns empty list when all libIds resolve."""
        unresolved = self.ir.cross_reference_check()
        assert unresolved == []

    def test_unresolved_libids_detected(self) -> None:
        """Test 21: cross_reference_check returns unresolved (reference, libId) tuples."""
        # Corrupt a component's libId to something not in libSymbols
        comps = self.ir.components
        if comps:
            for prop in comps[0].properties:
                if prop.key == "Reference":
                    ref = prop.value
                    break
            else:
                ref = "UNKNOWN"
            original_lib_id = comps[0].libId
            comps[0].libId = "FakeLibrary:NonExistentSymbol"

            unresolved = self.ir.cross_reference_check()
            assert len(unresolved) > 0
            assert any(lib_id == "FakeLibrary:NonExistentSymbol" for _, lib_id in unresolved)

            # Restore
            comps[0].libId = original_lib_id


class TestSchematicIRSetComponentReference:
    """SchematicIR._set_component_reference() helper tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_sch: pytest.fixture) -> None:
        """Create SchematicIR from Arduino_Mega schematic for each test."""
        _clear_registry()
        result = parse_schematic(arduino_mega_sch)
        self.ir = SchematicIR(_parse_result=result)

    def test_set_component_reference_updates_property(self) -> None:
        """Test 22: _set_component_reference updates the 'Reference' property correctly."""
        comp = self.ir.components[0]
        # Get original reference
        original = None
        for prop in comp.properties:
            if prop.key == "Reference":
                original = prop.value
                break
        assert original is not None

        self.ir._set_component_reference(comp, "X99")
        # Verify the property was updated
        for prop in comp.properties:
            if prop.key == "Reference":
                assert prop.value == "X99"
                break
