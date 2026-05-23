"""AI-driven PCB generation module.

Provides the GenerationIntent schema for converting high-level design parameters
into structured operation sequences, plus template generators for creating valid
KiCad board and schematic files from scratch, an end-to-end generation pipeline,
iterative refinement loop, and evaluation harness.

Usage::

    from kicad_agent.generation import GenerationIntent, generate_design, generate_board

    intent = GenerationIntent(name="Motor Driver", board=BoardSpec(width_mm=100, height_mm=80))
    result = generate_design(intent, Path("/output"))
"""

from kicad_agent.generation.intent import (
    BoardSpec,
    ComponentSpec,
    GenerationIntent,
    NetSpec,
    PowerSpec,
    PositionSpec,
    intent_to_operations,
)


def __getattr__(name: str):
    """Lazy imports for template/placement/planner modules (avoid circular dependency)."""
    if name in ("BoardTemplate", "generate_board"):
        from kicad_agent.generation.template_board import BoardTemplate, generate_board

        return BoardTemplate if name == "BoardTemplate" else generate_board
    if name in ("SchematicTemplate", "generate_schematic"):
        from kicad_agent.generation.template_schematic import (
            SchematicTemplate,
            generate_schematic,
        )

        return SchematicTemplate if name == "SchematicTemplate" else generate_schematic
    if name in ("PlacementEngine", "PlacementResult", "validate_placement_clearance"):
        from kicad_agent.generation.placement import (
            PlacementEngine,
            PlacementResult,
            validate_placement_clearance,
        )

        return {
            "PlacementEngine": PlacementEngine,
            "PlacementResult": PlacementResult,
            "validate_placement_clearance": validate_placement_clearance,
        }[name]
    if name in ("OpPlanner", "PlanStep", "plan_operation_sequence"):
        from kicad_agent.generation.op_planner import (
            OpPlanner,
            PlanStep,
            plan_operation_sequence,
        )

        return {
            "OpPlanner": OpPlanner,
            "PlanStep": PlanStep,
            "plan_operation_sequence": plan_operation_sequence,
        }[name]
    if name in ("generate_design", "GenerationResult"):
        from kicad_agent.generation.pipeline import GenerationResult, generate_design

        return GenerationResult if name == "GenerationResult" else generate_design
    if name in ("refine_design", "RefinementResult", "RefinementIteration"):
        from kicad_agent.generation.refinement import (
            RefinementIteration,
            RefinementResult,
            refine_design,
        )

        return {
            "refine_design": refine_design,
            "RefinementResult": RefinementResult,
            "RefinementIteration": RefinementIteration,
        }[name]
    if name in ("evaluate_design", "EvaluationResult", "evaluate_intent_suite", "get_test_intents"):
        from kicad_agent.generation.evaluation import (
            EvaluationResult,
            evaluate_design,
            evaluate_intent_suite,
            get_test_intents,
        )

        return {
            "evaluate_design": evaluate_design,
            "EvaluationResult": EvaluationResult,
            "evaluate_intent_suite": evaluate_intent_suite,
            "get_test_intents": get_test_intents,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "BoardSpec",
    "BoardTemplate",
    "ComponentSpec",
    "EvaluationResult",
    "GenerationIntent",
    "GenerationResult",
    "NetSpec",
    "OpPlanner",
    "PlacementEngine",
    "PlacementResult",
    "PlanStep",
    "PowerSpec",
    "PositionSpec",
    "RefinementIteration",
    "RefinementResult",
    "SchematicTemplate",
    "evaluate_design",
    "evaluate_intent_suite",
    "generate_board",
    "generate_design",
    "generate_schematic",
    "get_test_intents",
    "intent_to_operations",
    "plan_operation_sequence",
    "refine_design",
    "validate_placement_clearance",
]
