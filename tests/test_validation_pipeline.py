"""Validation pipeline integration tests with rollback verification.

VAL-03: Net consistency verification between schematic and PCB.
VAL-06: Automated error recovery with rollback on validation failure.

Tests verify the full pipeline cycle:
  1. Pre-mutation structural validation (blocks invalid operations)
  2. Mutation within Transaction context (snapshot-based rollback)
  3. Post-mutation UUID uniqueness check (detects corruption)
  4. Post-mutation ERC/DRC checks (catches electrical/physical errors)
  5. Automatic rollback on any stage failure

The pipeline enforces: "no invalid file ever reaches disk."
"""

import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from kicad_agent.validation.pipeline import (
    ValidationPipeline,
    PipelineResult,
    PipelineStage,
    StageResult,
)
from kicad_agent.validation.erc_drc import ErcResult, DrcResult, Violation, Severity
from kicad_agent.validation.structural import (
    StructuralResult,
    StructuralViolation,
    ViolationKind,
)
from kicad_agent.ops.schema import (
    Operation,
    AddComponentOp,
    ModifyPropertyOp,
    PositionSpec,
)
from kicad_agent.parser import parse_schematic
from kicad_agent.ir import SchematicIR
from kicad_agent.ir.base import _clear_registry


@pytest.fixture(autouse=True)
def _cleanup_ir_registry():
    """Clear IR registry between tests to prevent one-IR-per-ParseResult conflicts."""
    _clear_registry()
    yield
    _clear_registry()


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestPipelineResultTypes:
    """Verify pipeline result dataclass types are correct and frozen."""

    def test_pipeline_result_passed(self):
        result = PipelineResult(passed=True)
        assert result.passed
        assert result.stage_count == 0
        assert result.failure_reason == ""
        assert result.failure_stage is None
        assert not result.rolled_back

    def test_pipeline_result_failed(self):
        stages = (
            StageResult(
                stage=PipelineStage.STRUCTURAL_PRE,
                passed=False,
                detail="Structural validation failed: 1 violation(s)",
            ),
        )
        result = PipelineResult(
            passed=False,
            stages=stages,
            failure_stage=PipelineStage.STRUCTURAL_PRE,
        )
        assert not result.passed
        assert result.stage_count == 1
        assert result.failure_reason == "Structural validation failed: 1 violation(s)"

    def test_pipeline_result_frozen(self):
        result = PipelineResult(passed=True)
        with pytest.raises(AttributeError):
            result.passed = False

    def test_stage_result_frozen(self):
        stage = StageResult(stage=PipelineStage.ERC, passed=True, detail="ok")
        with pytest.raises(AttributeError):
            stage.passed = False

    def test_pipeline_stage_enum(self):
        assert PipelineStage.STRUCTURAL_PRE == "structural_pre"
        assert PipelineStage.MUTATION == "mutation"
        assert PipelineStage.UUID_UNIQUENESS == "uuid_uniqueness"
        assert PipelineStage.ERC == "erc"
        assert PipelineStage.DRC == "drc"
        assert PipelineStage.COMMIT == "commit"


class TestStructuralPreCheckFails:
    """Verify pipeline blocks on structural failure before mutation."""

    def test_structural_failure_blocks_mutation(self, arduino_mega_sch):
        parse_result = parse_schematic(arduino_mega_sch)
        ir = SchematicIR(_parse_result=parse_result)

        # Target a non-existent component reference
        operation = Operation(
            root=ModifyPropertyOp(
                target_file="Arduino_Mega.kicad_sch",
                reference="NONEXISTENT999",
                property_name="Value",
                new_value="test",
            )
        )

        pipeline = ValidationPipeline()
        result = pipeline.validate_and_apply(
            operation,
            ir,
            mutation_fn=lambda op, ir: None,
        )

        assert not result.passed
        assert result.failure_stage == PipelineStage.STRUCTURAL_PRE
        assert not result.rolled_back  # No transaction created for pre-check failures
        assert result.structural_result is not None
        assert result.structural_result.error_count > 0


class TestSuccessfulPipeline:
    """Verify pipeline succeeds on a valid operation with no-op mutation."""

    def test_successful_pipeline_no_erc(self, arduino_mega_sch):
        parse_result = parse_schematic(arduino_mega_sch)
        ir = SchematicIR(_parse_result=parse_result)

        # Find a real component reference from the schematic
        real_ref = None
        for sym in ir.components:
            for prop in sym.properties:
                if prop.key == "Reference" and prop.value.strip():
                    real_ref = prop.value
                    break
            if real_ref:
                break

        assert real_ref is not None, "No component references found in test fixture"

        operation = Operation(
            root=ModifyPropertyOp(
                target_file="Arduino_Mega.kicad_sch",
                reference=real_ref,
                property_name="Value",
                new_value="modified_value",
            )
        )

        pipeline = ValidationPipeline()
        result = pipeline.validate_and_apply(
            operation,
            ir,
            mutation_fn=lambda op, ir: None,
        )

        assert result.passed
        assert result.failure_stage is None
        assert result.stage_count >= 3  # structural_pre, uuid_uniqueness, commit
        assert not result.rolled_back
        assert result.structural_result is not None
        assert result.structural_result.passed
        assert result.uuid_uniqueness_result is not None
        assert result.uuid_uniqueness_result.passed

    def test_successful_pipeline_stage_names(self, arduino_mega_sch):
        parse_result = parse_schematic(arduino_mega_sch)
        ir = SchematicIR(_parse_result=parse_result)

        # Find a real reference
        real_ref = None
        for sym in ir.components:
            for prop in sym.properties:
                if prop.key == "Reference" and prop.value.strip():
                    real_ref = prop.value
                    break
            if real_ref:
                break

        operation = Operation(
            root=ModifyPropertyOp(
                target_file="Arduino_Mega.kicad_sch",
                reference=real_ref,
                property_name="Value",
                new_value="test",
            )
        )

        pipeline = ValidationPipeline()
        result = pipeline.validate_and_apply(
            operation,
            ir,
            mutation_fn=lambda op, ir: None,
        )

        stage_names = [s.stage for s in result.stages]
        assert PipelineStage.STRUCTURAL_PRE in stage_names
        assert PipelineStage.UUID_UNIQUENESS in stage_names
        assert PipelineStage.COMMIT in stage_names


class TestRollbackOnUuidViolation:
    """Verify rollback triggers on UUID uniqueness failure."""

    def test_uuid_violation_triggers_rollback(self, arduino_mega_sch, tmp_output_dir):
        temp_sch = tmp_output_dir / "test.kicad_sch"
        shutil.copy2(arduino_mega_sch, temp_sch)

        parse_result = parse_schematic(temp_sch)
        ir = SchematicIR(_parse_result=parse_result)

        # Find a real reference
        real_ref = None
        for sym in ir.components:
            for prop in sym.properties:
                if prop.key == "Reference" and prop.value.strip():
                    real_ref = prop.value
                    break
            if real_ref:
                break

        operation = Operation(
            root=ModifyPropertyOp(
                target_file="test.kicad_sch",
                reference=real_ref,
                property_name="Value",
                new_value="test",
            )
        )

        # Mock validate_uuid_uniqueness to return a failure
        failed_uuid_result = StructuralResult(
            passed=False,
            violations=(
                StructuralViolation(
                    kind=ViolationKind.DUPLICATE_UUID,
                    description="Duplicate UUID 'abc123' found 2 times",
                    detail="uuid=abc123, count=2",
                ),
            ),
            operation_type="uuid_uniqueness",
            target_file=str(temp_sch),
        )

        pipeline = ValidationPipeline()
        with patch(
            "kicad_agent.validation.pipeline.validate_uuid_uniqueness",
            return_value=failed_uuid_result,
        ):
            result = pipeline.validate_and_apply(
                operation,
                ir,
                mutation_fn=lambda op, ir: None,
            )

        assert not result.passed
        assert result.failure_stage == PipelineStage.UUID_UNIQUENESS
        assert result.rolled_back
        assert result.uuid_uniqueness_result is not None
        assert not result.uuid_uniqueness_result.passed


class TestRollbackOnErcFailure:
    """Verify rollback triggers on ERC failure."""

    def test_erc_failure_triggers_rollback(self, arduino_mega_sch, tmp_output_dir):
        temp_sch = tmp_output_dir / "test.kicad_sch"
        shutil.copy2(arduino_mega_sch, temp_sch)

        parse_result = parse_schematic(temp_sch)
        ir = SchematicIR(_parse_result=parse_result)

        # Find a real reference
        real_ref = None
        for sym in ir.components:
            for prop in sym.properties:
                if prop.key == "Reference" and prop.value.strip():
                    real_ref = prop.value
                    break
            if real_ref:
                break

        operation = Operation(
            root=ModifyPropertyOp(
                target_file="test.kicad_sch",
                reference=real_ref,
                property_name="Value",
                new_value="test",
            )
        )

        # Mock run_erc to return a failure
        failed_erc_result = ErcResult(
            passed=False,
            file_path=temp_sch,
            violations=(
                Violation(
                    description="Pin not connected",
                    severity=Severity.ERROR,
                    type="pin_to_pin",
                ),
            ),
        )

        pipeline = ValidationPipeline()
        with patch(
            "kicad_agent.validation.pipeline.run_erc",
            return_value=failed_erc_result,
        ):
            result = pipeline.validate_and_apply(
                operation,
                ir,
                mutation_fn=lambda op, ir: None,
                run_erc_check=True,
            )

        assert not result.passed
        assert result.failure_stage == PipelineStage.ERC
        assert result.rolled_back
        assert result.erc_result is not None
        assert not result.erc_result.passed


class TestVerifyNetConsistency:
    """VAL-03: Net consistency verification between schematic and PCB."""

    @pytest.mark.skipif(
        not shutil.which("kicad-cli"),
        reason="kicad-cli not available",
    )
    def test_net_consistency_returns_drc_result(
        self, arduino_mega_sch, arduino_mega_pcb
    ):
        pipeline = ValidationPipeline()
        result = pipeline.verify_net_consistency(arduino_mega_sch, arduino_mega_pcb)

        assert isinstance(result, DrcResult)
        assert result.file_path == arduino_mega_pcb
        assert isinstance(result.schematic_parity, tuple)

    @pytest.mark.skipif(
        not shutil.which("kicad-cli"),
        reason="kicad-cli not available",
    )
    def test_net_consistency_captures_parity_issues(
        self, arduino_mega_sch, arduino_mega_pcb
    ):
        pipeline = ValidationPipeline()
        result = pipeline.verify_net_consistency(arduino_mega_sch, arduino_mega_pcb)

        # schematic_parity should be a tuple (may be empty for consistent fixtures)
        assert isinstance(result.schematic_parity, tuple)
        # Should not have an error_message for valid files
        assert result.error_message is None


class TestPipelineWithMutationException:
    """Verify pipeline handles mutation exceptions gracefully."""

    def test_mutation_exception_triggers_rollback(
        self, arduino_mega_sch, tmp_output_dir
    ):
        temp_sch = tmp_output_dir / "test.kicad_sch"
        shutil.copy2(arduino_mega_sch, temp_sch)

        parse_result = parse_schematic(temp_sch)
        ir = SchematicIR(_parse_result=parse_result)

        # Find a real reference
        real_ref = None
        for sym in ir.components:
            for prop in sym.properties:
                if prop.key == "Reference" and prop.value.strip():
                    real_ref = prop.value
                    break
            if real_ref:
                break

        operation = Operation(
            root=ModifyPropertyOp(
                target_file="test.kicad_sch",
                reference=real_ref,
                property_name="Value",
                new_value="test",
            )
        )

        def failing_mutation(op, ir):
            raise RuntimeError("Mutation failed: component locked")

        pipeline = ValidationPipeline()
        result = pipeline.validate_and_apply(
            operation,
            ir,
            mutation_fn=failing_mutation,
        )

        assert not result.passed
        assert result.failure_stage == PipelineStage.MUTATION
        assert result.rolled_back
        assert "Mutation failed" in result.failure_reason

    def test_mutation_exception_preserves_original_file(
        self, arduino_mega_sch, tmp_output_dir
    ):
        temp_sch = tmp_output_dir / "test.kicad_sch"
        shutil.copy2(arduino_mega_sch, temp_sch)

        original_content = temp_sch.read_text()

        parse_result = parse_schematic(temp_sch)
        ir = SchematicIR(_parse_result=parse_result)

        # Find a real reference
        real_ref = None
        for sym in ir.components:
            for prop in sym.properties:
                if prop.key == "Reference" and prop.value.strip():
                    real_ref = prop.value
                    break
            if real_ref:
                break

        operation = Operation(
            root=ModifyPropertyOp(
                target_file="test.kicad_sch",
                reference=real_ref,
                property_name="Value",
                new_value="test",
            )
        )

        def failing_mutation(op, ir):
            raise RuntimeError("Simulated failure")

        pipeline = ValidationPipeline()
        pipeline.validate_and_apply(
            operation,
            ir,
            mutation_fn=failing_mutation,
        )

        # After rollback, file should be identical to original
        assert temp_sch.read_text() == original_content
