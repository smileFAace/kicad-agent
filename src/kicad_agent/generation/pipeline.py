"""End-to-end generation pipeline: intent -> template board -> operations -> validation -> export.

GEN-10: Single-command execution via generate_design() that takes a GenerationIntent
and produces a complete KiCad project with manufacturing outputs.

Pipeline steps:
  1. Create project directory
  2. Plan operations via OpPlanner
  3. Execute operations via OperationExecutor
  4. Generate template board and schematic (if not created by operations)
  5. Validate (ERC/DRC)
  6. Export manufacturing files (Gerber, BOM, position)
  7. Collect board statistics

Security (threat model):
  T-10-18: Validate intent.name is filesystem-safe.
  T-10-19: 120s timeout per kicad-cli validation call (inherited from erc_drc.py).
  DoS: Cap total operations at 1000.

Usage::

    from kicad_agent.generation.pipeline import generate_design, GenerationResult
    from kicad_agent.generation.intent import GenerationIntent

    intent = GenerationIntent(name="LED_Blink", ...)
    result = generate_design(intent, output_dir=Path("/tmp/projects"))
    print(f"Success: {result.success}, ERC: {result.erc_pass}")
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from kicad_agent.generation.intent import GenerationIntent
from kicad_agent.generation.template_board import generate_board
from kicad_agent.generation.template_schematic import generate_schematic

logger = logging.getLogger(__name__)

# Maximum operations to execute (DoS mitigation)
_MAX_OPERATIONS = 1000

# Filesystem-safe name pattern: alphanumeric, underscore, dash, dot
_SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-.]*$")


@dataclass(frozen=True)
class GenerationResult:
    """Complete result from the end-to-end generation pipeline.

    Attributes:
        success: Whether the pipeline completed without fatal errors.
        project_dir: Path to the generated project directory.
        schematic_path: Path to the generated .kicad_sch file, or None.
        pcb_path: Path to the generated .kicad_pcb file, or None.
        gerber_dir: Path to the Gerber output directory, or None.
        bom_path: Path to the BOM output file, or None.
        operations_executed: Number of operations successfully executed.
        erc_pass: True if ERC passed, False if failed, None if not run.
        drc_pass: True if DRC passed, False if failed, None if not run.
        errors: List of non-fatal error messages encountered.
        statistics: Board statistics dict from get_board_statistics().
    """

    success: bool
    project_dir: Path
    schematic_path: Path | None = None
    pcb_path: Path | None = None
    gerber_dir: Path | None = None
    bom_path: Path | None = None
    operations_executed: int = 0
    erc_pass: bool | None = None
    drc_pass: bool | None = None
    errors: tuple[str, ...] = ()
    statistics: dict = field(default_factory=dict)


def _validate_name(name: str) -> str:
    """Validate that intent.name is filesystem-safe.

    Args:
        name: The design name to validate.

    Returns:
        The validated name.

    Raises:
        ValueError: If name contains unsafe characters.
    """
    if not name or not name.strip():
        raise ValueError("Design name must not be empty")
    if not _SAFE_NAME_PATTERN.match(name):
        raise ValueError(
            f"Design name contains unsafe characters: {name!r}. "
            "Allowed: alphanumeric, underscore, dash, dot. Must start with alphanumeric or underscore."
        )
    return name


def generate_design(
    intent: GenerationIntent,
    output_dir: Path,
    run_validation: bool = True,
    run_export: bool = True,
) -> GenerationResult:
    """Execute the full generation pipeline from intent to manufacturing output.

    Single-command entry point that:
    1. Creates the project directory
    2. Plans and executes operations
    3. Generates template board and schematic files
    4. Runs ERC/DRC validation (optional)
    5. Exports manufacturing files (optional)
    6. Collects board statistics

    Args:
        intent: Validated GenerationIntent specifying the design.
        output_dir: Parent directory for the project. Must be writable.
        run_validation: Whether to run ERC/DRC validation (default True).
        run_export: Whether to run manufacturing export (default True).

    Returns:
        GenerationResult with full pipeline metadata.

    Raises:
        ValueError: If intent.name is not filesystem-safe.
        PermissionError: If output_dir is not writable.
    """
    # --- Security: validate intent.name ---
    _validate_name(intent.name)

    # --- Setup project directory ---
    output_dir = Path(output_dir)
    project_dir = output_dir / intent.name
    project_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    operations_executed = 0

    # --- Step 1: Plan operations ---
    from kicad_agent.generation.op_planner import OpPlanner

    planner = OpPlanner(intent, project_dir)
    steps = planner.plan()

    if len(steps) > _MAX_OPERATIONS:
        return GenerationResult(
            success=False,
            project_dir=project_dir,
            errors=(f"Operation count ({len(steps)}) exceeds maximum ({_MAX_OPERATIONS})",),
        )

    # --- Step 2: Generate template files first (operations need files to exist) ---
    sch_path = project_dir / f"{intent.name}.kicad_sch"
    pcb_path = project_dir / f"{intent.name}.kicad_pcb"

    # Generate template board
    try:
        generate_board(
            pcb_path,
            intent.board,
            components=intent.components,
            nets=intent.nets,
        )
        logger.info("Generated template board: %s", pcb_path)
    except Exception as e:
        errors.append(f"Board generation failed: {e}")
        logger.error("Board generation failed: %s", e)

    # Generate template schematic
    try:
        generate_schematic(sch_path, intent)
        logger.info("Generated template schematic: %s", sch_path)
    except Exception as e:
        errors.append(f"Schematic generation failed: {e}")
        logger.error("Schematic generation failed: %s", e)

    # --- Step 3: Execute operations ---
    if sch_path.exists() or pcb_path.exists():
        from kicad_agent.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=project_dir)

        for step in steps:
            try:
                result = executor.execute(step.operation)
                if result.get("success"):
                    operations_executed += 1
                else:
                    errors.append(
                        f"Operation {step.description} failed: {result}"
                    )
                    logger.warning("Operation failed: %s", step.description)
            except FileNotFoundError:
                # Target file doesn't exist yet -- skip gracefully
                logger.debug(
                    "Skipping operation %s: target file not found",
                    step.description,
                )
            except Exception as e:
                errors.append(f"Operation {step.description} error: {e}")
                logger.warning("Operation error: %s - %s", step.description, e)

    # --- Step 4: Validation ---
    erc_pass: bool | None = None
    drc_pass: bool | None = None

    if run_validation:
        if sch_path.exists():
            try:
                from kicad_agent.validation.erc_drc import run_erc

                erc_result = run_erc(sch_path)
                erc_pass = erc_result.passed
                if not erc_pass and erc_result.error_message:
                    errors.append(f"ERC: {erc_result.error_message}")
            except Exception as e:
                errors.append(f"ERC validation error: {e}")
                logger.warning("ERC validation error: %s", e)

        if pcb_path.exists():
            try:
                from kicad_agent.validation.erc_drc import run_drc

                drc_result = run_drc(pcb_path)
                drc_pass = drc_result.passed
                if not drc_pass and drc_result.error_message:
                    errors.append(f"DRC: {drc_result.error_message}")
            except Exception as e:
                errors.append(f"DRC validation error: {e}")
                logger.warning("DRC validation error: %s", e)

    # --- Step 5: Manufacturing export ---
    gerber_dir: Path | None = None
    bom_path_result: Path | None = None

    if run_export:
        # Export Gerber files
        if pcb_path.exists():
            try:
                from kicad_agent.export import export_gerber

                gerber_result = export_gerber(pcb_path)
                if gerber_result.success:
                    gerber_dir = gerber_result.output_dir
                else:
                    errors.append(f"Gerber export failed: {gerber_result.stderr}")
            except Exception as e:
                errors.append(f"Gerber export error: {e}")
                logger.warning("Gerber export error: %s", e)

        # Export BOM
        if sch_path.exists():
            try:
                from kicad_agent.export import export_bom

                bom_output = project_dir / f"{intent.name}-bom.csv"
                bom_result = export_bom(sch_path, bom_output)
                if bom_result.success:
                    bom_path_result = bom_output
                else:
                    errors.append("BOM export failed")
            except Exception as e:
                errors.append(f"BOM export error: {e}")
                logger.warning("BOM export error: %s", e)

        # Export position files
        if pcb_path.exists():
            try:
                from kicad_agent.export import export_position

                pos_result = export_position(pcb_path)
                if not pos_result.success:
                    errors.append("Position export failed (non-fatal)")
            except Exception as e:
                errors.append(f"Position export error: {e}")
                logger.debug("Position export error: %s", e)

    # --- Step 6: Collect statistics ---
    statistics: dict = {}
    if pcb_path.exists():
        try:
            from kicad_agent.export import get_board_statistics

            statistics = get_board_statistics(pcb_path)
        except Exception as e:
            errors.append(f"Statistics collection error: {e}")
            logger.debug("Statistics error: %s", e)

    # --- Build result ---
    # Success if both template files were generated (even if validation/export had issues)
    success = sch_path.exists() and pcb_path.exists()

    return GenerationResult(
        success=success,
        project_dir=project_dir,
        schematic_path=sch_path if sch_path.exists() else None,
        pcb_path=pcb_path if pcb_path.exists() else None,
        gerber_dir=gerber_dir,
        bom_path=bom_path_result,
        operations_executed=operations_executed,
        erc_pass=erc_pass,
        drc_pass=drc_pass,
        errors=tuple(errors),
        statistics=statistics,
    )
