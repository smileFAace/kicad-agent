"""End-to-end LLM generation pipeline orchestration.

Wires IntentParser, generate_design(), llm_refine_design(), DesignCritic,
and evaluate_design() into a single llm_generate() function that takes
natural language and produces a complete, validated KiCad project.

Pipeline stages:
  1. Intent Parsing: NL -> GenerationIntent via IntentParser
  2. Design Generation: GenerationIntent -> KiCad files via generate_design
  3. LLM Refinement: ERC errors -> fixes via llm_refine_design (only when ERC fails)
  4. Design Critique: Spatial analysis via DesignCritic (only when PCB exists)
  5. Evaluation: Quality scoring via evaluate_design
  6. Manufacturing Export: Gerber + BOM (non-fatal failures)

Security (threat model):
  T-15-14: Total LLM calls bounded: 1 parse + 1 generate + max 10 refine + 1 critique.
  T-15-15: intent.name validated by _validate_name in generate_design (filesystem safety).
  T-15-16: All generated files stay local; no data sent externally except to Anthropic API.

Usage::

    from kicad_agent.llm.pipeline import llm_generate, LLMGenerationResult

    result = llm_generate("design a voltage regulator circuit", output_dir=Path("/tmp"))
    print(f"Success: {result.success}, Intent: {result.intent.name}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMGenerationResult:
    """Complete result from the end-to-end LLM generation pipeline.

    Attributes:
        success: True when generation succeeded AND (ERC passed OR refinement converged).
        intent: Parsed GenerationIntent from stage 1, or None if parsing failed.
        generation_result: GenerationResult from stage 2, or None if parsing/generation failed.
        refinement_result: LLMRefinementResult from stage 3, or None if not run.
        critique: CritiqueReport from stage 4, or None if not run (no PCB or disabled).
        evaluation_result: EvaluationResult from stage 5, or None if not run.
        errors: Accumulated non-fatal errors from all stages.
    """

    success: bool
    intent: Any | None = None
    generation_result: Any | None = None
    refinement_result: Any | None = None
    critique: Any | None = None
    evaluation_result: Any | None = None
    errors: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Pipeline function
# ---------------------------------------------------------------------------


def llm_generate(
    description: str,
    output_dir: Path,
    run_refinement: bool = True,
    run_critique: bool = True,
    run_evaluation: bool = True,
    max_refinement_iterations: int = 5,
    intent_parser: Any | None = None,
    design_critic: Any | None = None,
    error_fixer: Any | None = None,
    llm_mode: str | None = None,
    confidence_threshold: float | None = None,
) -> LLMGenerationResult:
    """Execute the full LLM generation pipeline: NL -> KiCad project.

    Orchestrates five stages:
    1. Intent Parsing (IntentParser)
    2. Design Generation (generate_design)
    3. LLM Refinement (llm_refine_design, only when ERC fails)
    4. Design Critique (DesignCritic, only when PCB exists)
    5. Evaluation (evaluate_design)

    Each stage fails gracefully with clear error messages. The function
    accepts injected components (intent_parser, design_critic, error_fixer)
    for testability.

    When ``llm_mode`` is set (or ``KICAD_AGENT_LLM_MODE`` env var is set),
    a HybridLLMClient is created and wired to all stages, enabling local-first
    inference with cloud fallback.

    Args:
        description: Natural language circuit description.
        output_dir: Parent directory for the generated project.
        run_refinement: Whether to run LLM refinement on ERC failure (default True).
        run_critique: Whether to run spatial design critique (default True).
        run_evaluation: Whether to run design evaluation (default True).
        max_refinement_iterations: Max refinement iterations (default 5).
        intent_parser: Optional IntentParser instance (creates fresh if None).
        design_critic: Optional DesignCritic instance (creates fresh if None).
        error_fixer: Optional ErrorFixer instance (creates fresh if None).
        llm_mode: Optional LLM mode override: "local_first", "cloud_only", "local_only".
        confidence_threshold: Optional confidence threshold for local-to-cloud fallback.

    Returns:
        LLMGenerationResult with all intermediate outputs and accumulated errors.
    """
    errors: list[str] = []

    # --- Resolve LLM backend ---
    hybrid_client = _resolve_hybrid_client(llm_mode, confidence_threshold)

    # --- Stage 1: Intent Parsing ---
    intent = None
    try:
        if intent_parser is None:
            if hybrid_client is not None:
                from kicad_agent.llm.unified_parsers import UnifiedIntentParser
                intent_parser = UnifiedIntentParser(hybrid_client)
            else:
                from kicad_agent.llm.intent_parser import IntentParser
                intent_parser = IntentParser()

        intent = intent_parser.parse(description)
        logger.info("Parsed intent: %s", intent.name)

    except Exception as exc:
        error_msg = str(exc)
        logger.error("Intent parsing failed: %s", error_msg)
        return LLMGenerationResult(
            success=False,
            errors=(error_msg,),
        )

    # --- Stage 2: Design Generation ---
    from kicad_agent.generation.pipeline import generate_design

    try:
        generation_result = generate_design(
            intent, output_dir, run_validation=True, run_export=False,
        )
    except (ValueError, PermissionError) as exc:
        error_msg = str(exc)
        errors.append(error_msg)
        logger.error("Design generation failed: %s", error_msg)
        return LLMGenerationResult(
            success=False,
            intent=intent,
            generation_result=None,
            errors=tuple(errors),
        )

    if not generation_result.success:
        errors.extend(generation_result.errors)
        return LLMGenerationResult(
            success=False,
            intent=intent,
            generation_result=generation_result,
            errors=tuple(errors),
        )

    errors.extend(generation_result.errors)
    logger.info(
        "Generated design: %s (ERC=%s, PCB=%s)",
        intent.name,
        generation_result.erc_pass,
        generation_result.pcb_path is not None,
    )

    # --- Stage 3: LLM Refinement ---
    refinement_result = None
    erc_passed = generation_result.erc_pass is True

    if run_refinement and not erc_passed:
        from kicad_agent.llm.refinement import llm_refine_design

        sch_path = generation_result.schematic_path
        pcb_path = generation_result.pcb_path

        if sch_path is not None and sch_path.exists():
            # Wire error fixer through hybrid client
            fixer = error_fixer
            if fixer is None and hybrid_client is not None:
                from kicad_agent.llm.unified_parsers import UnifiedErrorFixer
                fixer = UnifiedErrorFixer(hybrid_client)

            refinement_result = llm_refine_design(
                sch_path,
                pcb_path=pcb_path,
                max_iterations=max_refinement_iterations,
                error_fixer=fixer,
            )
            if refinement_result.final_erc_pass:
                erc_passed = True
                logger.info("Refinement converged after %d iterations", refinement_result.total_iterations)
            else:
                logger.warning(
                    "Refinement did not converge: %d iterations, ERC pass=%s",
                    refinement_result.total_iterations,
                    refinement_result.final_erc_pass,
                )

    # --- Stage 4: Design Critique ---
    critique = None
    if run_critique and generation_result.pcb_path is not None and generation_result.pcb_path.exists():
        try:
            if design_critic is None:
                critic_client = hybrid_client  # will be None for pure cloud
                if critic_client is not None:
                    from kicad_agent.llm.design_critic import DesignCritic
                    design_critic = DesignCritic(client=critic_client)
                else:
                    from kicad_agent.llm.design_critic import DesignCritic
                    design_critic = DesignCritic()

            # Parse PCB and build spatial data
            from kicad_agent.parser import parse_pcb
            from kicad_agent.ir.pcb_ir import PcbIR
            from kicad_agent.spatial.extractor import extract_all
            from kicad_agent.spatial.query import SpatialQueryEngine

            pcb_ir = PcbIR(_parse_result=parse_pcb(generation_result.pcb_path))
            primitives = extract_all(pcb_ir)

            # Flatten all primitive lists into a single list for the engine
            all_primitives = []
            for primitive_list in primitives.values():
                all_primitives.extend(primitive_list)

            engine = SpatialQueryEngine(all_primitives)

            # Get ERC result for error context
            erc_result = None
            sch_for_erc = generation_result.schematic_path
            if sch_for_erc is not None and sch_for_erc.exists():
                try:
                    from kicad_agent.validation.erc_drc import run_erc

                    erc_result = run_erc(sch_for_erc)
                except Exception as exc:
                    logger.debug("ERC re-run for critique context failed: %s", exc)

            critique = design_critic.critique(engine, erc_result=erc_result)
            logger.info("Critique: score=%.2f, findings=%d", critique.overall_quality_score, len(critique.findings))

        except Exception as exc:
            error_msg = f"Critique failed: {exc}"
            errors.append(error_msg)
            logger.warning(error_msg)

    # --- Stage 5: Evaluation ---
    evaluation_result = None
    if run_evaluation:
        try:
            from kicad_agent.generation.evaluation import evaluate_design

            evaluation_result = evaluate_design(
                generation_result, generation_result.project_dir,
            )
            logger.info("Evaluation: score=%.2f", evaluation_result.overall_score)
        except Exception as exc:
            error_msg = f"Evaluation failed: {exc}"
            errors.append(error_msg)
            logger.warning(error_msg)

    # --- Stage 6: Manufacturing Export (non-fatal) ---
    if generation_result.success and generation_result.pcb_path is not None:
        _attempt_export(generation_result, errors)

    # --- Build final result ---
    success = generation_result.success and erc_passed

    return LLMGenerationResult(
        success=success,
        intent=intent,
        generation_result=generation_result,
        refinement_result=refinement_result,
        critique=critique,
        evaluation_result=evaluation_result,
        errors=tuple(errors),
    )


# ---------------------------------------------------------------------------
# Hybrid client resolution
# ---------------------------------------------------------------------------


def _resolve_hybrid_client(
    llm_mode: str | None,
    confidence_threshold: float | None,
) -> Any | None:
    """Create a HybridLLMClient if local inference is configured.

    Returns None if neither llm_mode nor KICAD_AGENT_LLM_MODE is set,
    preserving the existing cloud-only behavior.
    """
    import os

    env_mode = os.environ.get("KICAD_AGENT_LLM_MODE", "").strip().lower()
    mode = llm_mode or env_mode or ""

    if not mode:
        return None

    try:
        from kicad_agent.ai_tracking.tracker import InterventionTracker
        from kicad_agent.llm.backend import HybridLLMClient

        tracker = InterventionTracker()

        kwargs: dict[str, Any] = {
            "fallback_mode": mode,
            "tracker": tracker,
        }
        if confidence_threshold is not None:
            kwargs["confidence_threshold"] = confidence_threshold

        client = HybridLLMClient(**kwargs)
        logger.info(
            "HybridLLMClient created: mode=%s, threshold=%.2f",
            client.fallback_mode,
            client.confidence_threshold,
        )
        return client
    except Exception as exc:
        logger.warning("Could not create HybridLLMClient: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Non-fatal export helper
# ---------------------------------------------------------------------------


def _attempt_export(generation_result: Any, errors: list[str]) -> None:
    """Attempt manufacturing export (Gerber, BOM). Failures are non-fatal.

    Args:
        generation_result: GenerationResult with paths to generated files.
        errors: Mutable list to append non-fatal error messages.
    """
    # Export Gerber
    if generation_result.pcb_path is not None:
        try:
            from kicad_agent.export import export_gerber

            export_gerber(generation_result.pcb_path)
        except Exception as exc:
            errors.append(f"Gerber export failed (non-fatal): {exc}")
            logger.debug("Gerber export failed: %s", exc)

    # Export BOM
    if generation_result.schematic_path is not None:
        try:
            from kicad_agent.export import export_bom

            bom_output = generation_result.project_dir / f"{generation_result.project_dir.name}-bom.csv"
            export_bom(generation_result.schematic_path, bom_output)
        except Exception as exc:
            errors.append(f"BOM export failed (non-fatal): {exc}")
            logger.debug("BOM export failed: %s", exc)
