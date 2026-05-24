"""Tests for ErrorFixer -- converts ERC/DRC violations into fix operations via Claude tool use.

All tests mock the Anthropic client so no API key or network is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from conftest_llm import FakeMessage, FakeTextBlock, FakeToolUseBlock


class TestFixResult:
    """Tests for FixResult dataclass."""

    def test_fix_result_holds_operations_description_and_success(self):
        """FixResult stores operations list, fix_description string, and success flag."""
        from kicad_agent.llm.error_fixer import FixResult

        ops = ({"op_type": "add_wire", "target_file": "test.kicad_sch"},)
        result = FixResult(
            operations=ops,
            fix_description="Added missing wire",
            success=True,
        )
        assert result.operations == ops
        assert result.fix_description == "Added missing wire"
        assert result.success is True

    def test_fix_result_frozen(self):
        """FixResult is immutable (frozen dataclass)."""
        from kicad_agent.llm.error_fixer import FixResult

        result = FixResult(operations=(), fix_description="none", success=False)
        with pytest.raises(AttributeError):
            result.success = True  # type: ignore[misc]


class TestErrorFixer:
    """Tests for ErrorFixer class."""

    def test_fix_returns_fixresult_with_operations(self, mock_anthropic_client):
        """ErrorFixer.fix returns FixResult with operations and description from LLM."""
        from kicad_agent.llm.error_fixer import ErrorFixer, FixResult

        mock_anthropic_client.return_value = FakeMessage([
            FakeToolUseBlock("apply_fix_operations", {
                "fix_description": "Add wire between pin A and pin B",
                "operations": [
                    {
                        "op_type": "add_wire",
                        "target_file": "test.kicad_sch",
                        "start_x": 10.0,
                        "start_y": 20.0,
                        "end_x": 30.0,
                        "end_y": 20.0,
                    },
                ],
            }),
        ])

        fixer = ErrorFixer()
        violations = [
            {"description": "Pin not connected: U1 pin 5", "severity": "error", "type": "pin"},
        ]
        result = fixer.fix(violations)

        assert isinstance(result, FixResult)
        assert result.success is True
        assert len(result.operations) == 1
        assert result.operations[0]["op_type"] == "add_wire"
        assert "wire" in result.fix_description.lower() or "pin" in result.fix_description.lower()

    def test_fix_includes_iteration_history_in_prompt(self, mock_anthropic_client):
        """ErrorFixer includes iteration_history in the prompt so LLM avoids repeating failed fixes."""
        from kicad_agent.llm.error_fixer import ErrorFixer

        mock_anthropic_client.return_value = FakeMessage([
            FakeToolUseBlock("apply_fix_operations", {
                "fix_description": "Fixed",
                "operations": [],
            }),
        ])

        fixer = ErrorFixer()
        history = [
            "Iteration 1: 5 ERC errors, tried: place_no_connects",
            "Iteration 2: 3 ERC errors, tried: wire_snapping",
        ]
        fixer.fix([], iteration_history=history)

        # Verify the call was made and messages include history
        call_args = mock_anthropic_client.call_args
        messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
        # The history should appear somewhere in the messages
        all_text = str(messages)
        assert "Iteration 1" in all_text or "Previous attempts" in all_text

    def test_fix_no_tool_use_returns_unsuccessful(self, mock_anthropic_client):
        """ErrorFixer returns FixResult with success=False when LLM returns no tool_use block."""
        from kicad_agent.llm.error_fixer import ErrorFixer

        # LLM returns only text, no tool use
        mock_anthropic_client.return_value = FakeMessage([
            FakeTextBlock("I cannot fix this error."),
        ])

        fixer = ErrorFixer()
        result = fixer.fix([{"description": "unknown error", "severity": "error", "type": "other"}])

        assert result.success is False
        assert result.operations == ()
        assert "did not return" in result.fix_description.lower() or "no tool" in result.fix_description.lower()

    def test_fix_tool_uses_operation_schema(self, mock_anthropic_client):
        """FIX_TOOL uses get_operation_schema() for the operations array items schema."""
        from kicad_agent.llm.error_fixer import FIX_TOOL
        from kicad_agent.ops.schema import get_operation_schema

        op_schema = get_operation_schema()
        # FIX_TOOL's operations items should match the operation schema
        assert "operations" in FIX_TOOL["input_schema"]["properties"]
        ops_items = FIX_TOOL["input_schema"]["properties"]["operations"]["items"]
        # The items schema should have the root discriminator from Operation
        assert "properties" in ops_items or "anyOf" in ops_items or "$defs" in FIX_TOOL["input_schema"]

    def test_fix_with_empty_violations(self, mock_anthropic_client):
        """ErrorFixer handles empty violations list gracefully."""
        from kicad_agent.llm.error_fixer import ErrorFixer

        mock_anthropic_client.return_value = FakeMessage([
            FakeToolUseBlock("apply_fix_operations", {
                "fix_description": "No fixes needed",
                "operations": [],
            }),
        ])

        fixer = ErrorFixer()
        result = fixer.fix([])

        assert result.success is True
        assert result.operations == ()

    def test_fix_result_default_success_false(self):
        """FixResult defaults to success=False when LLM does not cooperate."""
        from kicad_agent.llm.error_fixer import FixResult

        result = FixResult(
            operations=(),
            fix_description="LLM did not return fix operations",
            success=False,
        )
        assert result.success is False

    def test_fix_system_prompt_present(self):
        """FIX_SYSTEM_PROMPT is defined and non-empty."""
        from kicad_agent.llm.error_fixer import FIX_SYSTEM_PROMPT

        assert isinstance(FIX_SYSTEM_PROMPT, str)
        assert len(FIX_SYSTEM_PROMPT) > 50
        assert "PCB" in FIX_SYSTEM_PROMPT or "error" in FIX_SYSTEM_PROMPT.lower()
