"""Task-specific prompt templates for PCB reasoning SFT.

Defines system prompts and task templates for converting maze reasoning
chains into instruction-following (ChatML) format.

Usage:
    from kicad_agent.training.sft.templates import (
        SYSTEM_PROMPT_SPATIAL,
        TASK_TEMPLATES,
        get_template_for_chain,
    )

    template = get_template_for_chain(chain_dict)
    prompt = template.format(context="Board is 30x30mm with 15 obstacles.")
"""

from __future__ import annotations

SYSTEM_PROMPT_SPATIAL: str = (
    "You are a PCB spatial reasoning assistant. "
    "Analyze board layouts using coordinate-grounded reasoning. "
    "Reference precise positions using <point x,y> format. "
    "Provide structured analysis with observation, spatial context, "
    "coordinate references, diagnosis, and routing recommendations."
)

TASK_TEMPLATES: dict[str, str] = {
    "spatial_reasoning": (
        "Perform a spatial analysis of this PCB routing problem:\n{context}"
    ),
}


def get_template_for_chain(chain_dict: dict) -> str:
    """Return the appropriate task template key based on chain metadata.

    Maze chains default to 'spatial_reasoning'. Future chain types
    (real board, component, schematic) can select different templates
    based on metadata fields.

    Args:
        chain_dict: Chain dictionary from chains_100k.jsonl.

    Returns:
        Template key string matching TASK_TEMPLATES.
    """
    return "spatial_reasoning"
