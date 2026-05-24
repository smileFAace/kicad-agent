"""Tests for design critic with spatial reasoning via Claude extended thinking.

Tests mock LLMClient to avoid real Anthropic API calls. Validates:
- CritiqueFinding and CritiqueReport dataclasses
- build_spatial_context producing compact LLM-readable summaries
- DesignCritic using extended thinking for spatial analysis
- Quality score computation from finding severities
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.llm.design_critic import (
    CRITIC_SYSTEM_PROMPT,
    CRITIC_TOOL,
    CritiqueFinding,
    CritiqueReport,
    CritiqueSeverity,
    DesignCritic,
    build_spatial_context,
)
from kicad_agent.spatial.primitives import SpatialBox, SpatialPoint
from kicad_agent.spatial.query import SpatialQueryEngine
from kicad_agent.validation.erc_drc import ErcResult, Severity, Violation


# ---------------------------------------------------------------------------
# Test 1: CritiqueFinding dataclass
# ---------------------------------------------------------------------------


class TestCritiqueFinding:
    """CritiqueFinding holds severity, category, description, and coordinates."""

    def test_fields(self) -> None:
        finding = CritiqueFinding(
            severity=CritiqueSeverity.CRITICAL,
            category="clearance",
            description="U1 and U2 overlap",
            coordinates=((10.0, 20.0), (12.0, 22.0)),
        )
        assert finding.severity is CritiqueSeverity.CRITICAL
        assert finding.category == "clearance"
        assert finding.description == "U1 and U2 overlap"
        assert finding.coordinates == ((10.0, 20.0), (12.0, 22.0))

    def test_frozen(self) -> None:
        finding = CritiqueFinding(
            severity=CritiqueSeverity.WARNING,
            category="thermal",
            description="Hot region",
            coordinates=(),
        )
        with pytest.raises(FrozenInstanceError):
            finding.severity = CritiqueSeverity.INFO  # type: ignore[misc]

    def test_severity_values(self) -> None:
        assert CritiqueSeverity.INFO.value == "info"
        assert CritiqueSeverity.WARNING.value == "warning"
        assert CritiqueSeverity.CRITICAL.value == "critical"


# ---------------------------------------------------------------------------
# Test 2: CritiqueReport dataclass
# ---------------------------------------------------------------------------


class TestCritiqueReport:
    """CritiqueReport holds findings, summary, and overall_quality_score."""

    def test_fields(self) -> None:
        finding = CritiqueFinding(
            severity=CritiqueSeverity.WARNING,
            category="congestion",
            description="Dense cluster",
            coordinates=((5.0, 5.0),),
        )
        report = CritiqueReport(
            findings=(finding,),
            summary="1 issue found",
            overall_quality_score=0.9,
        )
        assert len(report.findings) == 1
        assert report.summary == "1 issue found"
        assert report.overall_quality_score == 0.9

    def test_frozen(self) -> None:
        report = CritiqueReport(
            findings=(), summary="Clean", overall_quality_score=1.0
        )
        with pytest.raises(FrozenInstanceError):
            report.summary = "Changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 3: build_spatial_context with empty engine
# ---------------------------------------------------------------------------


class TestBuildSpatialContextEmpty:
    """build_spatial_context returns total entity count of 0 for empty engine."""

    def test_empty_engine(self) -> None:
        engine = SpatialQueryEngine([])
        result = build_spatial_context(engine)
        assert "Total entities on board: 0" in result


# ---------------------------------------------------------------------------
# Test 4: build_spatial_context with component boxes
# ---------------------------------------------------------------------------


class TestBuildSpatialContextWithComponents:
    """build_spatial_context includes entity counts and bounding boxes."""

    def test_component_boxes(self) -> None:
        boxes = [
            SpatialBox(0, 0, 5, 5, "component", "U1", layer="F.Cu", reference="U1"),
            SpatialBox(10, 10, 15, 15, "component", "U2", layer="F.Cu", reference="U2"),
        ]
        engine = SpatialQueryEngine(boxes)
        result = build_spatial_context(engine)

        assert "Total entities on board: 2" in result
        assert "U1: box(0.0,0.0,5.0,5.0)" in result
        assert "U2: box(10.0,10.0,15.0,15.0)" in result

    def test_mixed_types(self) -> None:
        primitives = [
            SpatialBox(0, 0, 5, 5, "component", "U1", layer="F.Cu", reference="U1"),
            SpatialPoint(10, 10, "via", "v1", layer="F.Cu"),
        ]
        engine = SpatialQueryEngine(primitives)
        result = build_spatial_context(engine)

        assert "Total entities on board: 2" in result


# ---------------------------------------------------------------------------
# Test 5: build_spatial_context caps at 20 component entries
# ---------------------------------------------------------------------------


class TestBuildSpatialContextCap:
    """build_spatial_context caps component bounding boxes at 20 entries."""

    def test_cap_at_20(self) -> None:
        boxes = [
            SpatialBox(i, i, i + 1, i + 1, "component", f"C{i}", reference=f"R{i}")
            for i in range(30)
        ]
        engine = SpatialQueryEngine(boxes)
        result = build_spatial_context(engine)

        # Total count should show all 30
        assert "Total entities on board: 30" in result
        # But component boxes should be capped
        lines = [l for l in result.split("\n") if l.startswith("  C") and "box(" in l]
        assert len(lines) == 20


# ---------------------------------------------------------------------------
# Test 6: DesignCritic.critique returns CritiqueReport
# ---------------------------------------------------------------------------


class TestDesignCriticCritique:
    """DesignCritic.critique returns CritiqueReport with parsed findings."""

    def test_returns_critique_report(self, mock_anthropic_client) -> None:  # noqa: F811
        from conftest_llm import FakeMessage, FakeToolUseBlock

        mock_anthropic_client.return_value = FakeMessage([
            FakeToolUseBlock("design_critique", {
                "findings": [
                    {
                        "severity": "warning",
                        "category": "clearance",
                        "description": "U1 and U2 are too close",
                        "coordinates": [[10.0, 20.0], [12.0, 22.0]],
                    },
                ],
                "summary": "1 clearance issue found",
                "overall_quality_score": 0.9,
            })
        ])

        boxes = [
            SpatialBox(0, 0, 5, 5, "component", "U1", reference="U1"),
            SpatialBox(4, 0, 9, 5, "component", "U2", reference="U2"),
        ]
        engine = SpatialQueryEngine(boxes)
        critic = DesignCritic()
        report = critic.critique(engine)

        assert isinstance(report, CritiqueReport)
        assert len(report.findings) == 1
        assert report.findings[0].category == "clearance"
        assert report.findings[0].severity is CritiqueSeverity.WARNING


# ---------------------------------------------------------------------------
# Test 7: DesignCritic includes extended thinking in API call
# ---------------------------------------------------------------------------


class TestExtendedThinking:
    """DesignCritic passes extended thinking parameters to LLMClient."""

    def test_thinking_params(self, mock_anthropic_client) -> None:  # noqa: F811
        from conftest_llm import FakeMessage, FakeToolUseBlock

        mock_anthropic_client.return_value = FakeMessage([
            FakeToolUseBlock("design_critique", {
                "findings": [],
                "summary": "Clean layout",
                "overall_quality_score": 1.0,
            })
        ])

        boxes = [SpatialBox(0, 0, 5, 5, "component", "U1", reference="U1")]
        engine = SpatialQueryEngine(boxes)
        critic = DesignCritic()
        critic.critique(engine)

        call_kwargs = mock_anthropic_client.call_args[1]
        assert call_kwargs["thinking"] == {
            "type": "enabled",
            "budget_tokens": 8000,
        }


# ---------------------------------------------------------------------------
# Test 8: DesignCritic includes ERC/DRC violation summary
# ---------------------------------------------------------------------------


class TestErrorContextInclusion:
    """DesignCritic includes ERC/DRC violation summary in context."""

    def test_erc_context_included(self, mock_anthropic_client) -> None:  # noqa: F811
        from conftest_llm import FakeMessage, FakeToolUseBlock

        mock_anthropic_client.return_value = FakeMessage([
            FakeToolUseBlock("design_critique", {
                "findings": [],
                "summary": "Clean",
                "overall_quality_score": 1.0,
            })
        ])

        boxes = [SpatialBox(0, 0, 5, 5, "component", "U1", reference="U1")]
        engine = SpatialQueryEngine(boxes)

        violation = Violation(
            description="Pin not connected",
            severity=Severity.ERROR,
            type="erc_error",
        )
        erc_result = ErcResult(
            passed=False,
            file_path=__file__,
            violations=(violation,),
        )

        critic = DesignCritic()
        critic.critique(engine, erc_result=erc_result)

        call_kwargs = mock_anthropic_client.call_args[1]
        user_msg = call_kwargs["messages"][0]["content"]
        assert "ERC" in user_msg


# ---------------------------------------------------------------------------
# Test 9: Quality score computation from finding severities
# ---------------------------------------------------------------------------


class TestQualityScoreComputation:
    """Quality score computed from finding severities: critical=-0.3, warning=-0.1, info=-0.02."""

    def test_score_with_mixed_severities(self, mock_anthropic_client) -> None:  # noqa: F811
        from conftest_llm import FakeMessage, FakeToolUseBlock

        mock_anthropic_client.return_value = FakeMessage([
            FakeToolUseBlock("design_critique", {
                "findings": [
                    {
                        "severity": "critical",
                        "category": "clearance",
                        "description": "Overlap",
                        "coordinates": [[0, 0]],
                    },
                    {
                        "severity": "warning",
                        "category": "congestion",
                        "description": "Dense area",
                        "coordinates": [[5, 5]],
                    },
                    {
                        "severity": "info",
                        "category": "placement",
                        "description": "Suboptimal",
                        "coordinates": [[10, 10]],
                    },
                ],
                "summary": "3 issues",
                "overall_quality_score": 0.58,
            })
        ])

        boxes = [SpatialBox(0, 0, 5, 5, "component", "U1", reference="U1")]
        engine = SpatialQueryEngine(boxes)
        critic = DesignCritic()
        report = critic.critique(engine)

        # Computed: 1.0 - 0.3 - 0.1 - 0.02 = 0.58
        assert report.overall_quality_score == pytest.approx(0.58, abs=0.01)

    def test_score_clamped_to_zero(self, mock_anthropic_client) -> None:  # noqa: F811
        from conftest_llm import FakeMessage, FakeToolUseBlock

        # 5 criticals would give 1.0 - 1.5 = -0.5, clamped to 0.0
        mock_anthropic_client.return_value = FakeMessage([
            FakeToolUseBlock("design_critique", {
                "findings": [
                    {"severity": "critical", "category": "clearance", "description": f"Issue {i}", "coordinates": [[0, 0]]}
                    for i in range(5)
                ],
                "summary": "Terrible",
                "overall_quality_score": 0.0,
            })
        ])

        boxes = [SpatialBox(0, 0, 5, 5, "component", "U1", reference="U1")]
        engine = SpatialQueryEngine(boxes)
        critic = DesignCritic()
        report = critic.critique(engine)

        assert report.overall_quality_score == 0.0


# ---------------------------------------------------------------------------
# Test 10: DesignCritic uses LLMClient (not direct anthropic import)
# ---------------------------------------------------------------------------


class TestUsesLLMClient:
    """DesignCritic delegates to LLMClient, not direct anthropic.Anthropic."""

    def test_delegates_to_llm_client(self, mock_anthropic_client) -> None:  # noqa: F811
        from conftest_llm import FakeMessage, FakeToolUseBlock

        mock_anthropic_client.return_value = FakeMessage([
            FakeToolUseBlock("design_critique", {
                "findings": [],
                "summary": "OK",
                "overall_quality_score": 1.0,
            })
        ])

        boxes = [SpatialBox(0, 0, 5, 5, "component", "U1", reference="U1")]
        engine = SpatialQueryEngine(boxes)
        critic = DesignCritic()
        report = critic.critique(engine)

        # LLMClient was called (via mock_anthropic_client)
        assert mock_anthropic_client.called
        assert isinstance(report, CritiqueReport)
