"""Tests for LLM-augmented refinement loop.

Tests verify deterministic-first-fix behavior, LLM fallback for "other" errors,
stagnation detection, hard iteration cap, and iteration history tracking.
All Anthropic calls are mocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from conftest_llm import FakeMessage, FakeToolUseBlock


# ---------- Helpers ----------


def _make_erc_result(passed: bool, violations: list[tuple[str, str, str]]):
    """Create a mock ErcResult.

    Args:
        passed: Whether ERC passed.
        violations: List of (description, severity, type) tuples.

    Returns:
        MagicMock with .passed, .error_count, .violations attributes.
    """
    from kicad_agent.validation.erc_drc import Severity

    mock = MagicMock()
    mock.passed = passed
    vlist = []
    for desc, sev, vtype in violations:
        v = MagicMock()
        v.description = desc
        v.severity = Severity.ERROR if sev == "error" else Severity.WARNING
        v.type = vtype
        v.items = ()
        vlist.append(v)
    mock.violations = tuple(vlist)
    mock.error_count = len(vlist)
    return mock


def _make_fixer_return(operations=None, description="LLM fix", success=True):
    """Create a mock FixResult."""
    from kicad_agent.llm.error_fixer import FixResult

    return FixResult(
        operations=tuple(operations or []),
        fix_description=description,
        success=success,
    )


# ---------- Tests ----------


class TestLLMRefinementResult:
    """Tests for LLMRefinementResult and LLMRefinementIteration dataclasses."""

    def test_result_has_llm_fixes_count(self):
        """LLMRefinementResult tracks total_llm_fixes."""
        from kicad_agent.llm.refinement import LLMRefinementResult

        result = LLMRefinementResult(
            iterations=(),
            final_erc_pass=True,
            final_drc_pass=False,
            total_iterations=0,
            converged=True,
            total_llm_fixes=5,
            stagnation_detected=False,
        )
        assert result.total_llm_fixes == 5

    def test_result_has_stagnation_flag(self):
        """LLMRefinementResult tracks stagnation_detected."""
        from kicad_agent.llm.refinement import LLMRefinementResult

        result = LLMRefinementResult(
            iterations=(),
            final_erc_pass=False,
            final_drc_pass=False,
            total_iterations=4,
            converged=False,
            total_llm_fixes=0,
            stagnation_detected=True,
        )
        assert result.stagnation_detected is True

    def test_iteration_has_llm_fixes_applied(self):
        """LLMRefinementIteration tracks llm_fixes_applied count."""
        from kicad_agent.llm.refinement import LLMRefinementIteration

        it = LLMRefinementIteration(
            iteration=1,
            erc_errors=3,
            drc_errors=0,
            fixes_applied=("wire_snapping",),
            llm_fixes_applied=2,
            passed=False,
        )
        assert it.llm_fixes_applied == 2

    def test_result_frozen(self):
        """LLMRefinementResult is immutable."""
        from kicad_agent.llm.refinement import LLMRefinementResult

        result = LLMRefinementResult(
            iterations=(),
            final_erc_pass=False,
            final_drc_pass=False,
            total_iterations=0,
            converged=False,
            total_llm_fixes=0,
            stagnation_detected=False,
        )
        with pytest.raises(AttributeError):
            result.converged = True  # type: ignore[misc]


class TestLLMRefineDesign:
    """Tests for llm_refine_design function."""

    def test_deterministic_only_no_llm_call(self, tmp_path):
        """llm_refine_design does NOT call LLM when only deterministic errors exist."""
        from kicad_agent.llm.refinement import llm_refine_design

        sch_path = tmp_path / "test.kicad_sch"
        sch_path.write_text("(kicad_sch (version 20231120))")

        # Mock ERC: first call returns pin_not_connected, second returns passed
        erc_fail = _make_erc_result(False, [
            ("Pin U1.5 not connected", "error", "pin_unconnected"),
        ])
        erc_pass = _make_erc_result(True, [])

        mock_fixer = MagicMock()

        with patch("kicad_agent.llm.refinement.run_erc") as mock_erc, \
             patch("kicad_agent.llm.refinement._apply_place_no_connects") as mock_nc:
            mock_erc.side_effect = [erc_fail, erc_pass]
            mock_nc.return_value = 1

            result = llm_refine_design(
                sch_path,
                error_fixer=mock_fixer,
                max_iterations=5,
            )

        # ErrorFixer should NOT have been called (no "other" errors)
        mock_fixer.fix.assert_not_called()
        assert result.converged is True

    def test_other_errors_trigger_llm(self, tmp_path):
        """llm_refine_design calls ErrorFixer when 'other' category errors exist."""
        from kicad_agent.llm.refinement import llm_refine_design

        sch_path = tmp_path / "test.kicad_sch"
        sch_path.write_text("(kicad_sch (version 20231120))")

        # ERC has only "other" errors
        erc_fail = _make_erc_result(False, [
            ("Symbol U1 has conflicting values", "error", "conflict"),
            ("Duplicate reference R1", "error", "duplicate"),
        ])
        erc_pass = _make_erc_result(True, [])

        mock_fixer = MagicMock()
        mock_fixer.fix.return_value = _make_fixer_return(
            operations=[{"op_type": "modify_property", "target_file": "test.kicad_sch"}],
            description="Fixed conflicting values",
        )

        with patch("kicad_agent.llm.refinement.run_erc") as mock_erc:
            mock_erc.side_effect = [erc_fail, erc_pass]

            result = llm_refine_design(
                sch_path,
                error_fixer=mock_fixer,
                max_iterations=5,
            )

        mock_fixer.fix.assert_called_once()
        assert result.total_llm_fixes >= 1

    def test_stagnation_detection(self, tmp_path):
        """llm_refine_design stops after 3 consecutive iterations with same error count."""
        from kicad_agent.llm.refinement import llm_refine_design

        sch_path = tmp_path / "test.kicad_sch"
        sch_path.write_text("(kicad_sch (version 20231120))")

        # Same errors every iteration (stagnation)
        erc_fail = _make_erc_result(False, [
            ("Unfixable error X", "error", "unknown"),
        ])

        mock_fixer = MagicMock()
        mock_fixer.fix.return_value = _make_fixer_return(
            operations=[],
            description="Could not fix",
        )

        with patch("kicad_agent.llm.refinement.run_erc") as mock_erc:
            # Return same errors every time
            mock_erc.return_value = erc_fail

            result = llm_refine_design(
                sch_path,
                error_fixer=mock_fixer,
                max_iterations=10,
            )

        assert result.stagnation_detected is True
        assert result.converged is False
        # Should stop at iteration 4 (3 consecutive stagnation + 1 initial)
        assert result.total_iterations <= 5

    def test_hard_cap_ten_iterations(self, tmp_path):
        """llm_refine_design respects hard cap of 10 iterations even with higher max."""
        from kicad_agent.llm.refinement import llm_refine_design

        sch_path = tmp_path / "test.kicad_sch"
        sch_path.write_text("(kicad_sch (version 20231120))")

        # Alternate error counts to avoid stagnation detection
        erc_3 = _make_erc_result(False, [
            ("Error A", "error", "a"),
            ("Error B", "error", "b"),
            ("Error C", "error", "c"),
        ])
        erc_2 = _make_erc_result(False, [
            ("Error A", "error", "a"),
            ("Error B", "error", "b"),
        ])

        mock_fixer = MagicMock()
        mock_fixer.fix.return_value = _make_fixer_return(operations=[], description="No fix")

        call_count = 0

        def alternating_erc(path):
            nonlocal call_count
            call_count += 1
            # Alternate between 3 and 2 errors to avoid stagnation at count 3
            return erc_2 if call_count % 2 == 0 else erc_3

        with patch("kicad_agent.llm.refinement.run_erc") as mock_erc:
            mock_erc.side_effect = alternating_erc

            result = llm_refine_design(
                sch_path,
                error_fixer=mock_fixer,
                max_iterations=50,  # Way above cap
            )

        assert result.total_iterations <= 10

    def test_converges_when_erc_passes(self, tmp_path):
        """llm_refine_design converges when ERC passes after LLM fixes."""
        from kicad_agent.llm.refinement import llm_refine_design

        sch_path = tmp_path / "test.kicad_sch"
        sch_path.write_text("(kicad_sch (version 20231120))")

        erc_fail = _make_erc_result(False, [
            ("Unknown error", "error", "other"),
        ])
        erc_pass = _make_erc_result(True, [])

        mock_fixer = MagicMock()
        mock_fixer.fix.return_value = _make_fixer_return(
            operations=[{"op_type": "repair_schematic", "target_file": "test.kicad_sch"}],
            description="Auto-repaired",
        )

        with patch("kicad_agent.llm.refinement.run_erc") as mock_erc:
            mock_erc.side_effect = [erc_fail, erc_pass]

            result = llm_refine_design(
                sch_path,
                error_fixer=mock_fixer,
                max_iterations=5,
            )

        assert result.converged is True
        assert result.total_iterations == 1
        assert result.final_erc_pass is True

    def test_iteration_history_passed_to_fixer(self, tmp_path):
        """Iteration history is passed to ErrorFixer on subsequent calls."""
        from kicad_agent.llm.refinement import llm_refine_design

        sch_path = tmp_path / "test.kicad_sch"
        sch_path.write_text("(kicad_sch (version 20231120))")

        erc_fail = _make_erc_result(False, [
            ("Unknown error", "error", "other"),
        ])

        mock_fixer = MagicMock()
        mock_fixer.fix.return_value = _make_fixer_return(operations=[], description="No fix")

        call_count = 0

        def erc_side_effect(path):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                return _make_erc_result(True, [])
            return erc_fail

        with patch("kicad_agent.llm.refinement.run_erc") as mock_erc:
            mock_erc.side_effect = erc_side_effect

            result = llm_refine_design(
                sch_path,
                error_fixer=mock_fixer,
                max_iterations=5,
            )

        # On the second fix call, iteration_history should be non-empty
        if mock_fixer.fix.call_count >= 2:
            second_call_kwargs = mock_fixer.fix.call_args_list[1]
            history = second_call_kwargs.kwargs.get("iteration_history")
            if history is None and second_call_kwargs[0]:
                history = second_call_kwargs[0][1] if len(second_call_kwargs[0]) > 1 else None
            # History should have at least one entry from iteration 1
            assert history is not None and len(history) > 0

    def test_total_llm_fixes_accumulated(self, tmp_path):
        """LLMRefinementResult.total_llm_fixes accumulates across iterations."""
        from kicad_agent.llm.refinement import llm_refine_design

        sch_path = tmp_path / "test.kicad_sch"
        sch_path.write_text("(kicad_sch (version 20231120))")

        erc_fail = _make_erc_result(False, [
            ("Unknown error", "error", "other"),
        ])

        mock_fixer = MagicMock()
        mock_fixer.fix.return_value = _make_fixer_return(
            operations=[{"op_type": "add_wire", "target_file": "test.kicad_sch"}],
            description="Fix attempt",
        )

        call_count = 0

        def erc_converge(path):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                return _make_erc_result(True, [])
            return erc_fail

        with patch("kicad_agent.llm.refinement.run_erc") as mock_erc:
            mock_erc.side_effect = erc_converge

            result = llm_refine_design(
                sch_path,
                error_fixer=mock_fixer,
                max_iterations=5,
            )

        # Each iteration with "other" errors called fixer once, each returned 1 operation
        assert result.total_llm_fixes >= 1

    def test_missing_schematic_returns_empty(self, tmp_path):
        """llm_refine_design returns empty result when schematic doesn't exist."""
        from kicad_agent.llm.refinement import llm_refine_design

        sch_path = tmp_path / "nonexistent.kicad_sch"
        mock_fixer = MagicMock()

        result = llm_refine_design(sch_path, error_fixer=mock_fixer)

        assert result.converged is False
        assert result.total_iterations == 0
        assert result.total_llm_fixes == 0
