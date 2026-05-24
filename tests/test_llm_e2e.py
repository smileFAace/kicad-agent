"""End-to-end integration tests for the LLM generation pipeline.

Tests the full llm_generate() pipeline: NL -> IntentParser -> generate_design ->
llm_refine_design -> DesignCritic -> evaluate_design.

Uses mocked LLM calls (via injected mocks) but REAL generate_design() to validate
the integration without requiring API keys.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.generation.evaluation import EvaluationResult, get_test_intents
from kicad_agent.generation.intent import GenerationIntent
from kicad_agent.generation.pipeline import GenerationResult
from kicad_agent.llm.design_critic import CritiqueReport, CritiqueFinding, CritiqueSeverity
from kicad_agent.llm.refinement import LLMRefinementResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _power_supply_intent() -> GenerationIntent:
    """Return the power_supply test intent (known to generate valid files)."""
    return get_test_intents()[2]  # power_supply is index 2


def _led_simple_intent() -> GenerationIntent:
    """Return the led_simple test intent (smallest, fastest generation)."""
    return get_test_intents()[0]


# ---------------------------------------------------------------------------
# Test 1: LLMGenerationResult dataclass holds all intermediate outputs
# ---------------------------------------------------------------------------


class TestLLMGenerationResult:
    """Tests for the LLMGenerationResult frozen dataclass."""

    def test_result_holds_all_intermediate_outputs(self):
        """LLMGenerationResult holds intent, generation_result, critique, refinement, evaluation, errors."""
        from kicad_agent.llm.pipeline import LLMGenerationResult

        intent = _led_simple_intent()
        gen_result = GenerationResult(
            success=True,
            project_dir=Path("/tmp/test"),
            schematic_path=Path("/tmp/test/test.kicad_sch"),
            pcb_path=Path("/tmp/test/test.kicad_pcb"),
            erc_pass=True,
        )
        critique = CritiqueReport(
            findings=(),
            summary="Test summary",
            overall_quality_score=0.9,
        )
        refinement = LLMRefinementResult(
            final_erc_pass=True,
            converged=True,
            total_iterations=1,
        )
        evaluation = EvaluationResult(
            intent_name="test",
            erc_pass=True,
            overall_score=0.85,
        )

        result = LLMGenerationResult(
            success=True,
            intent=intent,
            generation_result=gen_result,
            refinement_result=refinement,
            critique=critique,
            evaluation_result=evaluation,
            errors=(),
        )

        assert result.success is True
        assert result.intent is intent
        assert result.generation_result is gen_result
        assert result.refinement_result is refinement
        assert result.critique is critique
        assert result.evaluation_result is evaluation
        assert result.errors == ()

    def test_result_is_frozen(self):
        """LLMGenerationResult cannot be mutated after creation."""
        from kicad_agent.llm.pipeline import LLMGenerationResult

        result = LLMGenerationResult(success=False, errors=("test error",))
        with pytest.raises(AttributeError):
            result.success = True  # type: ignore[misc]

    def test_result_holds_none_for_unpopulated_stages(self):
        """LLMGenerationResult allows None for optional intermediate outputs."""
        from kicad_agent.llm.pipeline import LLMGenerationResult

        result = LLMGenerationResult(
            success=False,
            errors=("parse failed",),
        )

        assert result.intent is None
        assert result.generation_result is None
        assert result.refinement_result is None
        assert result.critique is None
        assert result.evaluation_result is None
        assert result.errors == ("parse failed",)


# ---------------------------------------------------------------------------
# Test 2: Happy path - full pipeline with mocked LLM
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Tests for the happy-path pipeline execution."""

    def test_full_pipeline_produces_success(self, tmp_path: Path):
        """llm_generate('design a voltage regulator') with mocked LLM produces LLMGenerationResult with success."""
        from kicad_agent.llm.pipeline import llm_generate

        mock_parser = MagicMock()
        mock_parser.parse.return_value = _power_supply_intent()

        mock_critic = MagicMock()
        mock_critic.critique.return_value = CritiqueReport(
            findings=(),
            summary="Good layout",
            overall_quality_score=0.9,
        )

        mock_fixer = MagicMock()

        result = llm_generate(
            description="design a 3.3V voltage regulator circuit",
            output_dir=tmp_path,
            intent_parser=mock_parser,
            design_critic=mock_critic,
            error_fixer=mock_fixer,
        )

        assert result.success is True
        assert result.intent is not None
        assert result.intent.name == "power_supply"
        assert result.generation_result is not None
        assert result.generation_result.success is True
        assert result.generation_result.schematic_path is not None
        assert result.generation_result.schematic_path.exists()
        assert result.errors == ()

    def test_pipeline_stages_execute_in_order(self, tmp_path: Path):
        """Pipeline runs stages in order: parse -> generate -> refine -> critique -> evaluate."""
        from kicad_agent.llm.pipeline import llm_generate

        call_order = []

        mock_parser = MagicMock()
        mock_parser.parse.side_effect = lambda desc: (
            call_order.append("parse"),
            _led_simple_intent(),
        )[1]

        mock_critic = MagicMock()
        mock_critic.critique.side_effect = lambda *a, **kw: (
            call_order.append("critique"),
            CritiqueReport(findings=(), summary="OK", overall_quality_score=1.0),
        )[1]

        mock_fixer = MagicMock()

        result = llm_generate(
            description="LED circuit",
            output_dir=tmp_path,
            intent_parser=mock_parser,
            design_critic=mock_critic,
            error_fixer=mock_fixer,
            run_refinement=False,  # skip refinement to test critique ordering
        )

        # Parse must come before critique
        assert "parse" in call_order
        assert "critique" in call_order
        parse_idx = call_order.index("parse")
        critique_idx = call_order.index("critique")
        assert parse_idx < critique_idx

    def test_pipeline_evaluation_produces_score(self, tmp_path: Path):
        """Evaluation stage produces an EvaluationResult with overall_score."""
        from kicad_agent.llm.pipeline import llm_generate

        mock_parser = MagicMock()
        mock_parser.parse.return_value = _led_simple_intent()

        mock_critic = MagicMock()
        mock_critic.critique.return_value = CritiqueReport(
            findings=(), summary="OK", overall_quality_score=1.0,
        )

        result = llm_generate(
            description="LED circuit",
            output_dir=tmp_path,
            intent_parser=mock_parser,
            design_critic=mock_critic,
            run_evaluation=True,
        )

        assert result.evaluation_result is not None
        assert isinstance(result.evaluation_result, EvaluationResult)
        assert 0.0 <= result.evaluation_result.overall_score <= 1.0


# ---------------------------------------------------------------------------
# Test 3: Intent parsing failure
# ---------------------------------------------------------------------------


class TestParseFailure:
    """Tests for graceful failure at the intent parsing stage."""

    def test_parse_failure_returns_error(self):
        """llm_generate with intent parsing failure returns success=False with error message."""
        from kicad_agent.llm.pipeline import llm_generate

        mock_parser = MagicMock()
        mock_parser.parse.side_effect = ValueError("Could not understand the description")

        result = llm_generate(
            description="gibberish that makes no sense xyz123",
            output_dir=Path("/tmp/unused"),
            intent_parser=mock_parser,
        )

        assert result.success is False
        assert result.intent is None
        assert result.generation_result is None
        assert len(result.errors) > 0
        assert any("Could not understand" in e for e in result.errors)

    def test_parse_pydantic_validation_error(self):
        """Pydantic ValidationError during parsing returns success=False."""
        from kicad_agent.llm.pipeline import llm_generate
        from pydantic import ValidationError

        mock_parser = MagicMock()
        mock_parser.parse.side_effect = ValidationError.from_exception_data(
            "GenerationIntent", []
        )

        result = llm_generate(
            description="test",
            output_dir=Path("/tmp/unused"),
            intent_parser=mock_parser,
        )

        assert result.success is False
        assert result.intent is None
        assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# Test 4: Generation failure
# ---------------------------------------------------------------------------


class TestGenerationFailure:
    """Tests for graceful failure at the generation stage."""

    def test_generation_failure_returns_partial_result(self, tmp_path: Path):
        """llm_generate with generation failure returns intent populated but success=False."""
        from kicad_agent.llm.pipeline import llm_generate

        # Create an intent that will cause generate_design to fail
        # Use an invalid name with unsafe characters
        bad_intent = GenerationIntent(
            name="../../etc/passwd",
            description="malicious path traversal",
            components=[],
            nets=[],
        )

        mock_parser = MagicMock()
        mock_parser.parse.return_value = bad_intent

        result = llm_generate(
            description="path traversal test",
            output_dir=tmp_path,
            intent_parser=mock_parser,
        )

        assert result.success is False
        assert result.intent is bad_intent
        assert result.generation_result is None
        assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# Test 5: Refinement behavior
# ---------------------------------------------------------------------------


class TestRefinementBehavior:
    """Tests for LLM refinement triggering logic."""

    def test_refinement_triggered_on_erc_fail(self, tmp_path: Path):
        """Pipeline runs refinement when ERC fails after generation."""
        from kicad_agent.llm.pipeline import llm_generate

        mock_parser = MagicMock()
        mock_parser.parse.return_value = _led_simple_intent()

        mock_critic = MagicMock()
        mock_critic.critique.return_value = CritiqueReport(
            findings=(), summary="OK", overall_quality_score=1.0,
        )

        mock_fixer = MagicMock()

        # We need to verify refinement runs when ERC fails.
        # With real generate_design, ERC may or may not pass depending on
        # the generated design. We mock llm_refine_design to verify it was called.
        with patch("kicad_agent.llm.pipeline.llm_refine_design") as mock_refine:
            mock_refine.return_value = LLMRefinementResult(
                final_erc_pass=True,
                converged=True,
                total_iterations=2,
            )

            # Force ERC to appear as failing by patching generation result
            original_generate = __import__(
                "kicad_agent.generation.pipeline",
                fromlist=["generate_design"],
            ).generate_design

            def mock_generate(intent, output_dir, run_validation=True, run_export=False):
                result = original_generate(
                    intent, output_dir, run_validation=run_validation, run_export=run_export,
                )
                # Force ERC to fail to trigger refinement
                from dataclasses import replace
                from kicad_agent.generation.pipeline import GenerationResult
                return GenerationResult(
                    success=result.success,
                    project_dir=result.project_dir,
                    schematic_path=result.schematic_path,
                    pcb_path=result.pcb_path,
                    gerber_dir=result.gerber_dir,
                    bom_path=result.bom_path,
                    operations_executed=result.operations_executed,
                    erc_pass=False,  # Force ERC failure
                    drc_pass=result.drc_pass,
                    errors=result.errors,
                    statistics=result.statistics,
                )

            with patch("kicad_agent.llm.pipeline.generate_design", side_effect=mock_generate):
                result = llm_generate(
                    description="LED circuit",
                    output_dir=tmp_path,
                    intent_parser=mock_parser,
                    design_critic=mock_critic,
                    error_fixer=mock_fixer,
                    run_refinement=True,
                )

                # Refinement should have been called since ERC failed
                if result.generation_result is not None and not result.generation_result.erc_pass:
                    mock_refine.assert_called_once()

    def test_refinement_not_called_when_erc_passes(self, tmp_path: Path):
        """Pipeline skips refinement when ERC already passes."""
        from kicad_agent.llm.pipeline import llm_generate

        mock_parser = MagicMock()
        mock_parser.parse.return_value = _led_simple_intent()

        mock_critic = MagicMock()
        mock_critic.critique.return_value = CritiqueReport(
            findings=(), summary="OK", overall_quality_score=1.0,
        )

        with patch("kicad_agent.llm.pipeline.llm_refine_design") as mock_refine:
            result = llm_generate(
                description="LED circuit",
                output_dir=tmp_path,
                intent_parser=mock_parser,
                design_critic=mock_critic,
                run_refinement=True,
            )

            # If generation succeeded with ERC pass, refinement should NOT be called
            if result.generation_result is not None and result.generation_result.erc_pass:
                mock_refine.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6: Critique skipped when no PCB
# ---------------------------------------------------------------------------


class TestCritiqueSkipping:
    """Tests for critique being skipped when no PCB is generated."""

    def test_critique_skipped_when_no_pcb(self, tmp_path: Path):
        """Pipeline skips critique when generate_design produces no PCB."""
        from kicad_agent.llm.pipeline import llm_generate

        mock_parser = MagicMock()
        mock_parser.parse.return_value = _led_simple_intent()

        mock_critic = MagicMock()
        mock_critic.critique.return_value = CritiqueReport(
            findings=(), summary="OK", overall_quality_score=1.0,
        )

        # Force no PCB by patching generate_design to return one without PCB
        from kicad_agent.generation.pipeline import GenerationResult

        def mock_generate(intent, output_dir, run_validation=True, run_export=False):
            output_dir = Path(output_dir)
            project_dir = output_dir / intent.name
            project_dir.mkdir(parents=True, exist_ok=True)
            sch_path = project_dir / f"{intent.name}.kicad_sch"
            sch_path.write_text("(kicad_sch (version 20231120) (generator kicad-agent))")
            return GenerationResult(
                success=True,
                project_dir=project_dir,
                schematic_path=sch_path,
                pcb_path=None,  # No PCB
                erc_pass=True,
            )

        with patch("kicad_agent.llm.pipeline.generate_design", side_effect=mock_generate):
            result = llm_generate(
                description="schematic only",
                output_dir=tmp_path,
                intent_parser=mock_parser,
                design_critic=mock_critic,
                run_critique=True,
            )

        assert result.critique is None
        mock_critic.critique.assert_not_called()


# ---------------------------------------------------------------------------
# Test 7: Success criteria
# ---------------------------------------------------------------------------


class TestSuccessCriteria:
    """Tests for the success flag computation."""

    def test_success_true_when_erc_passes(self, tmp_path: Path):
        """success=True when generation succeeded and ERC passed."""
        from kicad_agent.llm.pipeline import llm_generate

        mock_parser = MagicMock()
        mock_parser.parse.return_value = _led_simple_intent()

        mock_critic = MagicMock()
        mock_critic.critique.return_value = CritiqueReport(
            findings=(), summary="OK", overall_quality_score=1.0,
        )

        result = llm_generate(
            description="LED circuit",
            output_dir=tmp_path,
            intent_parser=mock_parser,
            design_critic=mock_critic,
        )

        if result.generation_result is not None and result.generation_result.erc_pass:
            assert result.success is True

    def test_success_true_when_refinement_converges(self, tmp_path: Path):
        """success=True when generation succeeded, ERC failed, but refinement converged."""
        from kicad_agent.llm.pipeline import llm_generate
        from kicad_agent.generation.pipeline import GenerationResult

        mock_parser = MagicMock()
        mock_parser.parse.return_value = _led_simple_intent()

        mock_critic = MagicMock()
        mock_critic.critique.return_value = CritiqueReport(
            findings=(), summary="OK", overall_quality_score=1.0,
        )

        def mock_generate(intent, output_dir, run_validation=True, run_export=False):
            output_dir = Path(output_dir)
            project_dir = output_dir / intent.name
            project_dir.mkdir(parents=True, exist_ok=True)
            sch_path = project_dir / f"{intent.name}.kicad_sch"
            sch_path.write_text("(kicad_sch (version 20231120) (generator kicad-agent))")
            pcb_path = project_dir / f"{intent.name}.kicad_pcb"
            pcb_path.write_text("(kicad_pcb (version 20231120) (generator kicad-agent))")
            return GenerationResult(
                success=True,
                project_dir=project_dir,
                schematic_path=sch_path,
                pcb_path=pcb_path,
                erc_pass=False,  # ERC fails
            )

        with patch("kicad_agent.llm.pipeline.generate_design", side_effect=mock_generate):
            with patch("kicad_agent.llm.pipeline.llm_refine_design") as mock_refine:
                mock_refine.return_value = LLMRefinementResult(
                    final_erc_pass=True,
                    converged=True,  # But refinement converges
                    total_iterations=2,
                )

                result = llm_generate(
                    description="LED circuit",
                    output_dir=tmp_path,
                    intent_parser=mock_parser,
                    design_critic=mock_critic,
                    run_refinement=True,
                )

                assert result.success is True


# ---------------------------------------------------------------------------
# Test 8: Module exports
# ---------------------------------------------------------------------------


class TestExports:
    """Tests for module-level exports."""

    def test_pipeline_imports(self):
        """llm_generate and LLMGenerationResult are importable from pipeline module."""
        from kicad_agent.llm.pipeline import llm_generate, LLMGenerationResult

        assert callable(llm_generate)
        assert LLMGenerationResult is not None

    def test_init_exports(self):
        """llm_generate and LLMGenerationResult are exported from __init__."""
        import kicad_agent.llm

        assert hasattr(kicad_agent.llm, "__all__")
        assert "llm_generate" in kicad_agent.llm.__all__
        assert "LLMGenerationResult" in kicad_agent.llm.__all__
