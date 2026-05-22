"""Structural validator tests -- VAL-05.

Verifies pre-mutation structural validation catches invalid operations
before they are executed, and UUID uniqueness checking detects duplicates
in file content.

Covers:
  - StructuralResult and StructuralViolation frozen dataclass behavior
  - ViolationKind enum values
  - validate_structural() for all 4 operation types
  - validate_uuid_uniqueness() with clean and duplicate UUID files
"""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.schema import (
    AddComponentOp,
    ModifyPropertyOp,
    MoveComponentOp,
    Operation,
    PositionSpec,
    RemoveComponentOp,
)
from kicad_agent.parser import parse_pcb, parse_schematic
from kicad_agent.parser.types import ParseResult
from kicad_agent.parser.uuid_extractor import extract_uuids
from kicad_agent.validation.structural import (
    StructuralResult,
    StructuralViolation,
    ViolationKind,
    validate_structural,
    validate_uuid_uniqueness,
)


@pytest.fixture(autouse=True)
def _clear_ir_registry():
    """Clear IR registry between tests to prevent id() collisions."""
    _clear_registry()
    yield
    _clear_registry()


# Helper: create a SchematicIR from Arduino_Mega fixture
@pytest.fixture
def arduino_schematic_ir(arduino_mega_sch: Path) -> SchematicIR:
    """Create a SchematicIR from the Arduino_Mega fixture."""
    result = parse_schematic(arduino_mega_sch)
    return SchematicIR(_parse_result=result)


# Helper: create a PcbIR from Arduino_Mega fixture
@pytest.fixture
def arduino_pcb_ir(arduino_mega_pcb: Path) -> PcbIR:
    """Create a PcbIR from the Arduino_Mega fixture."""
    result = parse_pcb(arduino_mega_pcb)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    return PcbIR(_parse_result=result, _uuid_map=uuid_map)


# Helper: find a real reference from the schematic
def _find_real_reference(ir: SchematicIR) -> str:
    """Extract the first reference designator from a SchematicIR."""
    for sym in ir.components:
        for prop in sym.properties:
            if prop.key == "Reference":
                return prop.value
    raise AssertionError("No reference designator found in fixture")


# ======================================================================
# TestStructuralResultTypes
# ======================================================================


class TestStructuralResultTypes:
    """Frozen dataclass behavior and type correctness for result types."""

    def test_result_passed(self) -> None:
        """StructuralResult(passed=True) has error_count=0."""
        result = StructuralResult(passed=True)
        assert result.passed is True
        assert result.error_count == 0
        assert result.violations == ()

    def test_result_with_violations(self) -> None:
        """StructuralResult with violations reports correct error_count and passed=False."""
        violations = (
            StructuralViolation(kind=ViolationKind.MISSING_COMPONENT, description="a"),
            StructuralViolation(kind=ViolationKind.DUPLICATE_UUID, description="b"),
            StructuralViolation(kind=ViolationKind.INVALID_POSITION, description="c"),
        )
        result = StructuralResult(
            passed=False, violations=violations, operation_type="test"
        )
        assert result.passed is False
        assert result.error_count == 3
        assert len(result.violations) == 3

    def test_result_frozen(self) -> None:
        """StructuralResult is frozen -- cannot set attributes."""
        result = StructuralResult(passed=True)
        with pytest.raises(FrozenInstanceError):
            result.passed = False  # type: ignore[misc]

    def test_violation_frozen(self) -> None:
        """StructuralViolation is frozen -- cannot set attributes."""
        violation = StructuralViolation(
            kind=ViolationKind.MISSING_COMPONENT, description="test"
        )
        with pytest.raises(FrozenInstanceError):
            violation.description = "changed"  # type: ignore[misc]

    def test_violation_kind_enum(self) -> None:
        """ViolationKind enum values match their string names."""
        assert ViolationKind.MISSING_COMPONENT == "missing_component"
        assert ViolationKind.FILE_TYPE_MISMATCH == "file_type_mismatch"
        assert ViolationKind.INVALID_LIBRARY_REF == "invalid_library_ref"
        assert ViolationKind.DUPLICATE_UUID == "duplicate_uuid"
        assert ViolationKind.INVALID_POSITION == "invalid_position"
        assert ViolationKind.EMPTY_REFERENCE == "empty_reference"


# ======================================================================
# TestValidateAddComponent
# ======================================================================


class TestValidateAddComponent:
    """Pre-mutation validation for add_component operations."""

    def test_add_component_valid(self, arduino_schematic_ir: SchematicIR) -> None:
        """Valid add_component operation passes structural validation."""
        op = Operation.model_validate({
            "root": {
                "op_type": "add_component",
                "target_file": "Arduino_Mega.kicad_sch",
                "library_id": "Device:R_Small_US",
                "reference": "R99",
                "position": {"x": 50.0, "y": 30.0},
            }
        })
        result = validate_structural(op, arduino_schematic_ir)
        assert result.passed
        assert result.error_count == 0
        assert result.operation_type == "add_component"

    def test_add_component_bad_library_ref(
        self, arduino_schematic_ir: SchematicIR
    ) -> None:
        """library_id without ':' produces INVALID_LIBRARY_REF violation."""
        # library_id validation happens in the structural validator, not Pydantic
        # (Pydantic only validates min_length/max_length). We need to bypass
        # Pydantic to test the structural check. Use model_construct to skip validation.
        op = Operation.model_construct(
            root=AddComponentOp(
                target_file="test.kicad_sch",
                library_id="NoColon",
                reference="R1",
                position=PositionSpec(x=10.0, y=20.0),
            )
        )
        result = validate_structural(op, arduino_schematic_ir)
        assert not result.passed
        assert any(
            v.kind == ViolationKind.INVALID_LIBRARY_REF for v in result.violations
        )

    def test_add_component_negative_position(
        self, arduino_schematic_ir: SchematicIR
    ) -> None:
        """Negative position coordinates produce INVALID_POSITION violation."""
        op = Operation.model_construct(
            root=AddComponentOp(
                target_file="test.kicad_sch",
                library_id="Device:R",
                reference="R1",
                position=PositionSpec(x=-10.0, y=20.0),
            )
        )
        result = validate_structural(op, arduino_schematic_ir)
        assert not result.passed
        assert any(
            v.kind == ViolationKind.INVALID_POSITION for v in result.violations
        )

    def test_add_component_wrong_file_type(self, arduino_pcb_ir: PcbIR) -> None:
        """add_component on a PCB file produces FILE_TYPE_MISMATCH violation."""
        op = Operation.model_validate({
            "root": {
                "op_type": "add_component",
                "target_file": "test.kicad_pcb",
                "library_id": "Device:R_Small_US",
                "position": {"x": 50.0, "y": 30.0},
            }
        })
        result = validate_structural(op, arduino_pcb_ir)
        assert not result.passed
        assert any(
            v.kind == ViolationKind.FILE_TYPE_MISMATCH for v in result.violations
        )


# ======================================================================
# TestValidateRemoveComponent
# ======================================================================


class TestValidateRemoveComponent:
    """Pre-mutation validation for remove_component operations."""

    def test_remove_existing_component(
        self, arduino_schematic_ir: SchematicIR
    ) -> None:
        """Removing an existing component passes structural validation."""
        ref = _find_real_reference(arduino_schematic_ir)
        op = Operation.model_validate({
            "root": {
                "op_type": "remove_component",
                "target_file": "Arduino_Mega.kicad_sch",
                "reference": ref,
            }
        })
        result = validate_structural(op, arduino_schematic_ir)
        assert result.passed
        assert result.operation_type == "remove_component"

    def test_remove_nonexistent_component(
        self, arduino_schematic_ir: SchematicIR
    ) -> None:
        """Removing a non-existent component produces MISSING_COMPONENT violation."""
        op = Operation.model_validate({
            "root": {
                "op_type": "remove_component",
                "target_file": "Arduino_Mega.kicad_sch",
                "reference": "NONEXISTENT999",
            }
        })
        result = validate_structural(op, arduino_schematic_ir)
        assert not result.passed
        assert any(
            v.kind == ViolationKind.MISSING_COMPONENT for v in result.violations
        )

    def test_remove_wrong_file_type(self, arduino_pcb_ir: PcbIR) -> None:
        """remove_component on a PCB file produces FILE_TYPE_MISMATCH violation."""
        op = Operation.model_validate({
            "root": {
                "op_type": "remove_component",
                "target_file": "test.kicad_pcb",
                "reference": "U1",
            }
        })
        result = validate_structural(op, arduino_pcb_ir)
        assert not result.passed
        assert any(
            v.kind == ViolationKind.FILE_TYPE_MISMATCH for v in result.violations
        )


# ======================================================================
# TestValidateMoveComponent
# ======================================================================


class TestValidateMoveComponent:
    """Pre-mutation validation for move_component operations."""

    def test_move_existing_component(
        self, arduino_schematic_ir: SchematicIR
    ) -> None:
        """Moving an existing component to valid position passes validation."""
        ref = _find_real_reference(arduino_schematic_ir)
        op = Operation.model_validate({
            "root": {
                "op_type": "move_component",
                "target_file": "Arduino_Mega.kicad_sch",
                "reference": ref,
                "position": {"x": 100.0, "y": 200.0},
            }
        })
        result = validate_structural(op, arduino_schematic_ir)
        assert result.passed
        assert result.operation_type == "move_component"

    def test_move_nonexistent_component(
        self, arduino_schematic_ir: SchematicIR
    ) -> None:
        """Moving a non-existent component produces MISSING_COMPONENT violation."""
        op = Operation.model_validate({
            "root": {
                "op_type": "move_component",
                "target_file": "Arduino_Mega.kicad_sch",
                "reference": "NONEXISTENT999",
                "position": {"x": 100.0, "y": 200.0},
            }
        })
        result = validate_structural(op, arduino_schematic_ir)
        assert not result.passed
        assert any(
            v.kind == ViolationKind.MISSING_COMPONENT for v in result.violations
        )

    def test_move_negative_position(
        self, arduino_schematic_ir: SchematicIR
    ) -> None:
        """Moving a valid component to negative position produces INVALID_POSITION."""
        ref = _find_real_reference(arduino_schematic_ir)
        op = Operation.model_construct(
            root=MoveComponentOp(
                target_file="test.kicad_sch",
                reference=ref,
                position=PositionSpec(x=-1.0, y=20.0),
            )
        )
        result = validate_structural(op, arduino_schematic_ir)
        assert not result.passed
        assert any(
            v.kind == ViolationKind.INVALID_POSITION for v in result.violations
        )


# ======================================================================
# TestValidateModifyProperty
# ======================================================================


class TestValidateModifyProperty:
    """Pre-mutation validation for modify_property operations."""

    def test_modify_existing_component(
        self, arduino_schematic_ir: SchematicIR
    ) -> None:
        """Modifying a property of an existing component passes validation."""
        ref = _find_real_reference(arduino_schematic_ir)
        op = Operation.model_validate({
            "root": {
                "op_type": "modify_property",
                "target_file": "Arduino_Mega.kicad_sch",
                "reference": ref,
                "property_name": "Value",
                "new_value": "10k",
            }
        })
        result = validate_structural(op, arduino_schematic_ir)
        assert result.passed
        assert result.operation_type == "modify_property"

    def test_modify_nonexistent_component(
        self, arduino_schematic_ir: SchematicIR
    ) -> None:
        """Modifying property of non-existent component produces MISSING_COMPONENT."""
        op = Operation.model_validate({
            "root": {
                "op_type": "modify_property",
                "target_file": "Arduino_Mega.kicad_sch",
                "reference": "NONEXISTENT999",
                "property_name": "Value",
                "new_value": "10k",
            }
        })
        result = validate_structural(op, arduino_schematic_ir)
        assert not result.passed
        assert any(
            v.kind == ViolationKind.MISSING_COMPONENT for v in result.violations
        )


# ======================================================================
# TestValidateUuidUniqueness
# ======================================================================


class TestValidateUuidUniqueness:
    """UUID uniqueness checking across file content."""

    def test_uuid_uniqueness_clean_file(
        self, arduino_schematic_ir: SchematicIR
    ) -> None:
        """Real KiCad files have unique UUIDs -- validate_uuid_uniqueness passes."""
        result = validate_uuid_uniqueness(arduino_schematic_ir)
        assert result.passed
        assert result.error_count == 0
        assert result.operation_type == "uuid_uniqueness"

    def test_uuid_uniqueness_detects_duplicate(
        self, arduino_mega_sch: Path
    ) -> None:
        """Duplicate UUIDs in raw_content are detected by validate_uuid_uniqueness."""
        # Read a real schematic and inject a duplicate UUID
        result = parse_schematic(arduino_mega_sch)
        original_content = result.raw_content

        # Find the first UUID in the content
        import re

        uuid_pattern = re.compile(
            r'\(uuid\s+"?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"?\)',
            re.IGNORECASE,
        )
        match = uuid_pattern.search(original_content)
        assert match is not None, "Fixture should contain at least one UUID"
        first_uuid = match.group(1)

        # Create content with a duplicated UUID by appending it
        duplicate_content = original_content + f'\n  (uuid "{first_uuid}")\n'

        # Create a new ParseResult with the duplicated content
        dup_result = ParseResult(
            kiutils_obj=result.kiutils_obj,
            raw_content=duplicate_content,
            file_path=result.file_path,
            file_type=result.file_type,
        )
        ir = SchematicIR(_parse_result=dup_result)

        uniqueness_result = validate_uuid_uniqueness(ir)
        assert not uniqueness_result.passed
        assert uniqueness_result.error_count > 0
        assert any(
            v.kind == ViolationKind.DUPLICATE_UUID for v in uniqueness_result.violations
        )
        # The duplicate UUID value should appear in the violation detail
        assert any(first_uuid in v.detail for v in uniqueness_result.violations)
