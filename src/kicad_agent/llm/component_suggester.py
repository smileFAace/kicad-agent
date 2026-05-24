"""Functional description to KiCad component suggestion via Claude tool use.

Suggests KiCad components with valid library_id values based on a functional
description, using Claude's tool use feature for structured output.

Security (threat model):
  T-15-02: _validate_safe_id on all library_id values from LLM; rejects
           injection characters.
"""

from __future__ import annotations

from dataclasses import dataclass

from kicad_agent.generation.intent import _SAFE_ID_PATTERN
from kicad_agent.llm.client import LLMClient
from kicad_agent.llm.tools import COMPONENT_SYSTEM_PROMPT, SUGGEST_TOOL


@dataclass(frozen=True)
class ComponentSuggestion:
    """A suggested KiCad component with metadata.

    Attributes:
        library_id: KiCad symbol library ID (e.g., Device:R_Small_US).
        value: Component value string (e.g., 10k, 100nF).
        reference_prefix: Reference designator prefix (e.g., R, C, U).
        rationale: Why this component was suggested.
    """

    library_id: str
    value: str
    reference_prefix: str
    rationale: str


class ComponentSuggester:
    """Suggests KiCad components based on functional descriptions.

    Uses Claude's tool use feature with a system prompt containing common
    KiCad library IDs to produce structured component suggestions.

    Args:
        model: Optional model override. If None, uses LLMClient default.
    """

    def __init__(self, model: str | None = None) -> None:
        self._client = LLMClient(model=model)

    def suggest(self, functional_description: str) -> list[ComponentSuggestion]:
        """Suggest KiCad components for a given functional description.

        Args:
            functional_description: Description of the needed component
                functionality (e.g., "voltage regulator 3.3V").

        Returns:
            List of ComponentSuggestion instances with validated library_id values.

        Raises:
            ValueError: If the LLM does not return a tool_use block,
                or if a library_id contains unsafe characters.
        """
        response = self._client.create_message(
            system=COMPONENT_SYSTEM_PROMPT,
            max_tokens=4096,
            tools=[SUGGEST_TOOL],
            tool_choice={"type": "tool", "name": "suggest_components"},
            messages=[{"role": "user", "content": functional_description}],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "suggest_components":
                suggestions_data = block.input.get("suggestions", [])
                return self._validate_suggestions(suggestions_data)

        raise ValueError(
            "LLM did not return a tool_use block for suggest_components"
        )

    @staticmethod
    def _validate_suggestions(
        suggestions_data: list[dict],
    ) -> list[ComponentSuggestion]:
        """Validate suggestion data and create ComponentSuggestion instances.

        Args:
            suggestions_data: Raw suggestion dicts from LLM tool use output.

        Returns:
            List of validated ComponentSuggestion instances.

        Raises:
            ValueError: If any library_id contains unsafe characters.
        """
        results: list[ComponentSuggestion] = []
        for item in suggestions_data:
            library_id = item.get("library_id", "")
            if not _SAFE_ID_PATTERN.match(library_id):
                raise ValueError(
                    f"Identifier contains unsafe characters: {library_id!r}. "
                    "Allowed: alphanumeric, underscore, dash, colon, dot, hash, forward slash."
                )
            results.append(
                ComponentSuggestion(
                    library_id=library_id,
                    value=item.get("value", ""),
                    reference_prefix=item.get("reference_prefix", ""),
                    rationale=item.get("rationale", ""),
                )
            )
        return results
