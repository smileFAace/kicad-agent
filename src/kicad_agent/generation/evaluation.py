"""Evaluation harness for measuring generated design quality.

GEN-12: Evaluates generated designs against quality thresholds with a
weighted scoring system (ERC 0.4, DRC 0.3, Gerber 0.15, BOM 0.15).

Provides:
- evaluate_design(): Score a single GenerationResult
- evaluate_intent_suite(): Run evaluation across multiple intents
- get_test_intents(): Predefined test intents for benchmarking

Usage::

    from kicad_agent.generation.evaluation import evaluate_design, get_test_intents

    result = generate_design(intent, output_dir)
    eval_result = evaluate_design(result, result.project_dir)
    print(f"Score: {eval_result.overall_score}")
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from kicad_agent.generation.intent import (
    BoardSpec,
    ComponentSpec,
    GenerationIntent,
    NetSpec,
    PowerSpec,
)
from kicad_agent.generation.pipeline import GenerationResult, generate_design

logger = logging.getLogger(__name__)

# Score weights (must sum to 1.0)
_ERC_WEIGHT = 0.4
_DRC_WEIGHT = 0.3
_GERBER_WEIGHT = 0.15
_BOM_WEIGHT = 0.15


@dataclass(frozen=True)
class EvaluationResult:
    """Evaluation result for a single generated design.

    Attributes:
        intent_name: Name of the evaluated design intent.
        erc_pass: Whether ERC passed.
        drc_pass: Whether DRC passed (None if not run).
        gerber_export_pass: Whether Gerber export succeeded (None if not attempted).
        bom_export_pass: Whether BOM export succeeded (None if not attempted).
        component_count: Number of components in the design.
        net_count: Number of nets in the design.
        overall_score: Weighted score from 0.0 to 1.0.
        issues: List of issues found during evaluation.
    """

    intent_name: str
    erc_pass: bool
    drc_pass: bool | None = None
    gerber_export_pass: bool | None = None
    bom_export_pass: bool | None = None
    component_count: int = 0
    net_count: int = 0
    overall_score: float = 0.0
    issues: tuple[str, ...] = ()


def _compute_score(
    erc_pass: bool,
    drc_pass: bool | None,
    gerber_pass: bool | None,
    bom_pass: bool | None,
) -> float:
    """Compute the weighted overall score.

    Weights: ERC 0.4, DRC 0.3, Gerber 0.15, BOM 0.15.

    Args:
        erc_pass: ERC pass status.
        drc_pass: DRC pass status (None = not run, counts as 0).
        gerber_pass: Gerber export status (None = not attempted, counts as 0).
        bom_pass: BOM export status (None = not attempted, counts as 0).

    Returns:
        Score between 0.0 and 1.0.
    """
    score = 0.0

    if erc_pass:
        score += _ERC_WEIGHT

    if drc_pass is True:
        score += _DRC_WEIGHT

    if gerber_pass is True:
        score += _GERBER_WEIGHT

    if bom_pass is True:
        score += _BOM_WEIGHT

    return round(score, 2)


def evaluate_design(result: GenerationResult, project_dir: Path) -> EvaluationResult:
    """Evaluate a generated design against quality thresholds.

    Checks:
    1. ERC pass/fail
    2. DRC pass/fail (if PCB exists)
    3. Manufacturing export completeness (Gerber files exist, BOM exists)
    4. Component and net counts
    5. Overall weighted score

    Args:
        result: GenerationResult from generate_design().
        project_dir: Path to the generated project directory.

    Returns:
        EvaluationResult with scores and issues.
    """
    issues: list[str] = []
    project_dir = Path(project_dir)

    # ERC check
    erc_pass = result.erc_pass is True
    if result.erc_pass is None:
        issues.append("ERC was not run")
    elif not erc_pass:
        issues.append("ERC failed")

    # DRC check
    drc_pass = result.drc_pass
    if result.pcb_path is None:
        issues.append("No PCB generated for DRC check")
    elif result.drc_pass is None:
        issues.append("DRC was not run")
    elif not result.drc_pass:
        issues.append("DRC failed")

    # Gerber export check
    gerber_pass: bool | None = None
    if result.gerber_dir is not None:
        gerber_pass = result.gerber_dir.exists() and any(
            result.gerber_dir.iterdir()
        )
        if not gerber_pass:
            issues.append("Gerber export produced no files")
    else:
        if result.pcb_path is not None:
            issues.append("Gerber export was not run")

    # BOM export check
    bom_pass: bool | None = None
    if result.bom_path is not None:
        bom_pass = result.bom_path.exists()
        if not bom_pass:
            issues.append("BOM export file not found")
    else:
        if result.schematic_path is not None:
            issues.append("BOM export was not run")

    # Component and net counts from statistics
    component_count = result.statistics.get("component_count", 0)
    net_count = result.statistics.get("net_count", 0)

    # Compute overall score
    overall_score = _compute_score(erc_pass, drc_pass, gerber_pass, bom_pass)

    return EvaluationResult(
        intent_name=result.project_dir.name,
        erc_pass=erc_pass,
        drc_pass=drc_pass,
        gerber_export_pass=gerber_pass,
        bom_export_pass=bom_pass,
        component_count=component_count,
        net_count=net_count,
        overall_score=overall_score,
        issues=tuple(issues),
    )


def evaluate_intent_suite(
    intents: list[GenerationIntent],
    output_base: Path,
) -> list[EvaluationResult]:
    """Run evaluation on a suite of test intents.

    Generates each intent and evaluates the result. Useful for measuring
    generation quality across different design types.

    Args:
        intents: List of GenerationIntent instances to evaluate.
        output_base: Base directory for generated projects.

    Returns:
        List of EvaluationResult, one per intent.
    """
    results: list[EvaluationResult] = []

    for intent in intents:
        try:
            gen_result = generate_design(
                intent, output_base, run_validation=True, run_export=True
            )
            eval_result = evaluate_design(gen_result, gen_result.project_dir)
            results.append(eval_result)
        except Exception as e:
            logger.error("Failed to evaluate intent %s: %s", intent.name, e)
            results.append(
                EvaluationResult(
                    intent_name=intent.name,
                    erc_pass=False,
                    issues=(f"Generation failed: {e}",),
                    overall_score=0.0,
                )
            )

    return results


def get_test_intents() -> list[GenerationIntent]:
    """Return predefined test intents for evaluation benchmarking.

    Three intents covering increasing complexity:
    - led_simple: LED + resistor + power (3 components)
    - mcu_minimal: MCU + decoupling caps + crystal + reset (10 components)
    - power_supply: Voltage regulator + input/output caps + resistors (8 components)

    Returns:
        List of three GenerationIntent instances.
    """

    # --- LED Simple: 3 components ---
    led_simple = GenerationIntent(
        name="led_simple",
        description="Simple LED circuit with current-limiting resistor",
        board=BoardSpec(width_mm=30, height_mm=20, layer_count=2),
        components=[
            ComponentSpec(
                library_id="Device:R_Small_US",
                reference="R1",
                value="330",
            ),
            ComponentSpec(
                library_id="Device:LED",
                reference="D1",
                value="RED",
            ),
        ],
        nets=[
            NetSpec(name="VCC", pins=["R1.1"]),
            NetSpec(name="LED_DRIVE", pins=["R1.2", "D1.1"]),
        ],
        power=PowerSpec(nets=["GND", "+3V3"]),
    )

    # --- MCU Minimal: 10 components ---
    mcu_minimal = GenerationIntent(
        name="mcu_minimal",
        description="Minimal MCU circuit with decoupling, crystal, and reset",
        board=BoardSpec(width_mm=50, height_mm=50, layer_count=4),
        components=[
            ComponentSpec(
                library_id="MCU_Microchip:ATtiny202",
                reference="U1",
                value="ATtiny202",
            ),
            ComponentSpec(
                library_id="Device:C_Small",
                reference="C1",
                value="100nF",
            ),
            ComponentSpec(
                library_id="Device:C_Small",
                reference="C2",
                value="100nF",
            ),
            ComponentSpec(
                library_id="Device:C_Small",
                reference="C3",
                value="10uF",
            ),
            ComponentSpec(
                library_id="Device:Crystal",
                reference="Y1",
                value="16MHz",
            ),
            ComponentSpec(
                library_id="Device:C_Small",
                reference="C4",
                value="22pF",
            ),
            ComponentSpec(
                library_id="Device:C_Small",
                reference="C5",
                value="22pF",
            ),
            ComponentSpec(
                library_id="Device:R_Small_US",
                reference="R1",
                value="10k",
            ),
            ComponentSpec(
                library_id="Device:C_Small",
                reference="C6",
                value="100nF",
            ),
            ComponentSpec(
                library_id="Switch:SW_Push",
                reference="SW1",
                value="RESET",
            ),
        ],
        nets=[
            NetSpec(name="VCC", pins=["U1.1", "C1.1", "C3.1"]),
            NetSpec(name="XTAL1", pins=["U1.2", "Y1.1", "C4.1"]),
            NetSpec(name="XTAL2", pins=["U1.3", "Y1.2", "C5.1"]),
            NetSpec(name="RESET", pins=["U1.4", "R1.1", "SW1.1", "C6.1"]),
        ],
        power=PowerSpec(nets=["GND", "+3V3"]),
    )

    # --- Power Supply: 8 components ---
    power_supply = GenerationIntent(
        name="power_supply",
        description="3.3V linear regulator with input/output filtering",
        board=BoardSpec(width_mm=40, height_mm=30, layer_count=2),
        components=[
            ComponentSpec(
                library_id="Regulator_Linear:AMS1117-3.3",
                reference="U1",
                value="AMS1117-3.3",
            ),
            ComponentSpec(
                library_id="Device:C_Polarized",
                reference="C1",
                value="10uF",
            ),
            ComponentSpec(
                library_id="Device:C_Small",
                reference="C2",
                value="100nF",
            ),
            ComponentSpec(
                library_id="Device:C_Polarized",
                reference="C3",
                value="22uF",
            ),
            ComponentSpec(
                library_id="Device:C_Small",
                reference="C4",
                value="100nF",
            ),
            ComponentSpec(
                library_id="Device:R_Small_US",
                reference="R1",
                value="470",
            ),
            ComponentSpec(
                library_id="Device:LED",
                reference="D1",
                value="GREEN",
            ),
            ComponentSpec(
                library_id="Device:D_Schottky",
                reference="D2",
                value="SS14",
            ),
        ],
        nets=[
            NetSpec(name="VIN", pins=["U1.3", "C1.1", "C2.1", "D2.2"]),
            NetSpec(name="VOUT", pins=["U1.2", "C3.1", "C4.1", "R1.1"]),
            NetSpec(name="PGOOD", pins=["R1.2", "D1.1"]),
        ],
        power=PowerSpec(nets=["GND", "+5V"]),
    )

    return [led_simple, mcu_minimal, power_supply]
