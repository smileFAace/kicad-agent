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
    """Lazy imports for template modules (avoid circular dependency during incremental build)."""
    if name in ("BoardTemplate", "generate_board"):
        from kicad_agent.generation.template_board import BoardTemplate, generate_board

        return BoardTemplate if name == "BoardTemplate" else generate_board
    if name in ("SchematicTemplate", "generate_schematic"):
        from kicad_agent.generation.template_schematic import (
            SchematicTemplate,
            generate_schematic,
        )

        return SchematicTemplate if name == "SchematicTemplate" else generate_schematic
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "BoardSpec",
    "BoardTemplate",
    "ComponentSpec",
    "GenerationIntent",
    "NetSpec",
    "PowerSpec",
    "PositionSpec",
    "SchematicTemplate",
    "generate_board",
    "generate_schematic",
    "intent_to_operations",
]
