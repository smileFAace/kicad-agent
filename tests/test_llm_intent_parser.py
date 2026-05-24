"""Tests for IntentParser: NL to GenerationIntent via Claude tool use.

Task 2 RED phase: Tests define expected behavior for:
- IntentParser.parse() converting NL descriptions to GenerationIntent
- Validation of LLM output through Pydantic model_validate
- Error handling when LLM does not return expected tool_use block
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.conftest_llm import FakeMessage, FakeTextBlock, FakeToolUseBlock


# ---------------------------------------------------------------------------
# Test 1: IntentParser.parse returns valid GenerationIntent from NL
# ---------------------------------------------------------------------------


def test_parse_returns_valid_generation_intent(mock_anthropic_client, sample_intent_dict):
    """IntentParser.parse('Design a 3.3V voltage regulator') returns valid GenerationIntent."""
    from kicad_agent.llm.intent_parser import IntentParser

    mock_anthropic_client.return_value = FakeMessage([
        FakeToolUseBlock("create_design_intent", sample_intent_dict)
    ])

    parser = IntentParser()
    result = parser.parse("Design a 3.3V voltage regulator with input filtering")

    assert result.name == "LED Blinker"
    assert result.board.width_mm == 50.0
    assert len(result.components) == 2
    assert result.components[0].library_id == "Device:R"
    assert len(result.nets) == 1
    assert result.power.nets == ["GND", "+3V3"]


# ---------------------------------------------------------------------------
# Test 2: IntentParser.parse raises ValueError when no tool_use block
# ---------------------------------------------------------------------------


def test_parse_raises_value_error_without_tool_use(mock_anthropic_client):
    """IntentParser.parse raises ValueError when LLM does not return a tool_use block."""
    from kicad_agent.llm.intent_parser import IntentParser

    mock_anthropic_client.return_value = FakeMessage([
        FakeTextBlock("I think you want a voltage regulator circuit...")
    ])

    parser = IntentParser()
    with pytest.raises(ValueError, match="tool_use block"):
        parser.parse("Design a voltage regulator")


# ---------------------------------------------------------------------------
# Test 3: IntentParser validates LLM output through GenerationIntent
# ---------------------------------------------------------------------------


def test_parse_validates_library_id(mock_anthropic_client):
    """IntentParser.parse rejects invalid library_id characters via Pydantic ValidationError."""
    from kicad_agent.llm.intent_parser import IntentParser

    invalid_intent = {
        "name": "Bad Design",
        "board": {"width_mm": 50, "height_mm": 50},
        "components": [
            {
                "library_id": "Device:R<script>alert(1)</script>",
                "reference": "R1",
                "value": "10k",
            }
        ],
        "nets": [],
        "power": {"nets": ["GND"]},
    }

    mock_anthropic_client.return_value = FakeMessage([
        FakeToolUseBlock("create_design_intent", invalid_intent)
    ])

    parser = IntentParser()
    with pytest.raises(ValidationError):
        parser.parse("Design something malicious")


# ---------------------------------------------------------------------------
# Test 7 (shared): IntentParser uses LLMClient (not direct anthropic import)
# ---------------------------------------------------------------------------


def test_intent_parser_uses_llm_client(mock_anthropic_client, sample_intent_dict):
    """IntentParser must use LLMClient for API calls, not import anthropic directly."""
    from kicad_agent.llm.intent_parser import IntentParser

    mock_anthropic_client.return_value = FakeMessage([
        FakeToolUseBlock("create_design_intent", sample_intent_dict)
    ])

    parser = IntentParser()
    # Verify it uses LLMClient by checking _client attribute type
    from kicad_agent.llm.client import LLMClient
    assert isinstance(parser._client, LLMClient)

    # Verify the call was made through the client
    parser.parse("Test description")
    mock_anthropic_client.assert_called_once()
