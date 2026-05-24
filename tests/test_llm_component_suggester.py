"""Tests for ComponentSuggester: functional description to KiCad component candidates.

Task 2 RED phase: Tests define expected behavior for:
- ComponentSuggester.suggest() returning valid ComponentSuggestion instances
- library_id validation against safe identifier patterns
- Error handling when LLM does not return expected tool_use block
- COMPONENT_SYSTEM_PROMPT used as system message
"""

from __future__ import annotations

import pytest

from tests.conftest_llm import FakeMessage, FakeTextBlock, FakeToolUseBlock


# ---------------------------------------------------------------------------
# Test 4: ComponentSuggester.suggest returns valid suggestions
# ---------------------------------------------------------------------------


def test_suggest_returns_valid_suggestions(mock_anthropic_client, sample_suggestions_dict):
    """ComponentSuggester.suggest('voltage regulator 3.3V') returns list of ComponentSuggestion."""
    from kicad_agent.llm.component_suggester import ComponentSuggester

    mock_anthropic_client.return_value = FakeMessage([
        FakeToolUseBlock("suggest_components", {"suggestions": sample_suggestions_dict})
    ])

    suggester = ComponentSuggester()
    results = suggester.suggest("voltage regulator 3.3V")

    assert len(results) == 2
    assert results[0].library_id == "Device:R_Small_US"
    assert results[0].value == "10k"
    assert results[0].reference_prefix == "R"
    assert results[0].rationale == "Standard pull-up resistor value"
    assert results[1].library_id == "Device:C_Small"


# ---------------------------------------------------------------------------
# Test 5: ComponentSuggester.suggest raises ValueError without tool_use block
# ---------------------------------------------------------------------------


def test_suggest_raises_value_error_without_tool_use(mock_anthropic_client):
    """ComponentSuggester.suggest raises ValueError when LLM returns no tool_use block."""
    from kicad_agent.llm.component_suggester import ComponentSuggester

    mock_anthropic_client.return_value = FakeMessage([
        FakeTextBlock("I would suggest using a voltage regulator...")
    ])

    suggester = ComponentSuggester()
    with pytest.raises(ValueError, match="tool_use block"):
        suggester.suggest("decoupling capacitor")


# ---------------------------------------------------------------------------
# Test 6: library_id validation rejects unsafe characters
# ---------------------------------------------------------------------------


def test_suggest_validates_library_id(mock_anthropic_client):
    """ComponentSuggestion.library_id values must pass _validate_safe_id pattern."""
    from kicad_agent.llm.component_suggester import ComponentSuggester

    malicious_suggestions = {
        "suggestions": [
            {
                "library_id": "Device:R; DROP TABLE--",
                "value": "10k",
                "reference_prefix": "R",
                "rationale": "Malicious",
            }
        ]
    }

    mock_anthropic_client.return_value = FakeMessage([
        FakeToolUseBlock("suggest_components", malicious_suggestions)
    ])

    suggester = ComponentSuggester()
    with pytest.raises(ValueError, match="unsafe characters"):
        suggester.suggest("something malicious")


# ---------------------------------------------------------------------------
# Test 7 (shared): ComponentSuggester uses LLMClient
# ---------------------------------------------------------------------------


def test_suggester_uses_llm_client(mock_anthropic_client, sample_suggestions_dict):
    """ComponentSuggester must use LLMClient for API calls."""
    from kicad_agent.llm.component_suggester import ComponentSuggester
    from kicad_agent.llm.client import LLMClient

    mock_anthropic_client.return_value = FakeMessage([
        FakeToolUseBlock("suggest_components", {"suggestions": sample_suggestions_dict})
    ])

    suggester = ComponentSuggester()
    assert isinstance(suggester._client, LLMClient)

    suggester.suggest("test")
    mock_anthropic_client.assert_called_once()


# ---------------------------------------------------------------------------
# Test: COMPONENT_SYSTEM_PROMPT used as system message
# ---------------------------------------------------------------------------


def test_suggester_uses_system_prompt(mock_anthropic_client, sample_suggestions_dict):
    """ComponentSuggester must pass COMPONENT_SYSTEM_PROMPT as system message."""
    from kicad_agent.llm.component_suggester import ComponentSuggester
    from kicad_agent.llm.tools import COMPONENT_SYSTEM_PROMPT

    mock_anthropic_client.return_value = FakeMessage([
        FakeToolUseBlock("suggest_components", {"suggestions": sample_suggestions_dict})
    ])

    suggester = ComponentSuggester()
    suggester.suggest("resistor for LED")

    call_kwargs = mock_anthropic_client.call_args
    assert "system" in call_kwargs.kwargs or "system" in (call_kwargs[1] if len(call_kwargs) > 1 else {})
    # Check system parameter contains the prompt
    system_val = call_kwargs.kwargs.get("system", call_kwargs[1].get("system") if len(call_kwargs) > 1 else None)
    assert COMPONENT_SYSTEM_PROMPT in system_val
