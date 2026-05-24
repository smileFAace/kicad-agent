"""Natural language to GenerationIntent conversion via Claude tool use.

Uses the Anthropic SDK's tool use feature to convert natural language
circuit descriptions into validated GenerationIntent objects.

Security (threat model):
  T-15-01: Pydantic model_validate on all LLM output; rejects structurally
           valid but semantically wrong JSON.
"""

from __future__ import annotations

from kicad_agent.generation.intent import GenerationIntent
from kicad_agent.llm.client import LLMClient
from kicad_agent.llm.tools import INTENT_TOOL


class IntentParser:
    """Converts natural language descriptions to validated GenerationIntent objects.

    Uses Claude's tool use feature to produce structured output that is
    validated through Pydantic's model_validate before being returned.

    Args:
        model: Optional model override. If None, uses LLMClient default.
    """

    def __init__(self, model: str | None = None) -> None:
        self._client = LLMClient(model=model)

    def parse(self, description: str) -> GenerationIntent:
        """Convert a natural language circuit description to a GenerationIntent.

        Args:
            description: Natural language description of the circuit to design.

        Returns:
            A validated GenerationIntent object.

        Raises:
            ValueError: If the LLM does not return a tool_use block.
            pydantic.ValidationError: If the LLM output fails schema validation.
        """
        response = self._client.create_message(
            max_tokens=4096,
            tools=[INTENT_TOOL],
            tool_choice={"type": "tool", "name": "create_design_intent"},
            messages=[{"role": "user", "content": description}],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "create_design_intent":
                return GenerationIntent.model_validate(block.input)

        raise ValueError(
            "LLM did not return a tool_use block for create_design_intent"
        )
