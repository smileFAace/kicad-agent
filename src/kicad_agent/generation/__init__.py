"""AI-driven PCB generation module.

Provides the GenerationIntent schema for converting high-level design parameters
into structured operation sequences, plus template generators for creating valid
KiCad board and schematic files from scratch.

Usage::

    from kicad_agent.generation import GenerationIntent, generate_board, generate_schematic

    intent = GenerationIntent(name="Motor Driver", board=BoardSpec(width_mm=100, height_mm=80))
    ops = intent_to_operations(intent)
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
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "BoardSpec",
    "BoardTemplate",
    "ComponentSpec",
    "GenerationIntent",
    "NetSpec",
    "OpPlanner",
    "PlacementEngine",
    "PlacementResult",
    "PlanStep",
    "PowerSpec",
    "PositionSpec",
    "SchematicTemplate",
    "generate_board",
    "generate_schematic",
    "intent_to_operations",
    "plan_operation_sequence",
    "validate_placement_clearance",
]
