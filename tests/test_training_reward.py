"""Tests for reward model architecture (Plan 09-03).

Covers:
  - RewardSignal and ChainReward construction
  - score_chain() returns correct number of step rewards
  - Format scoring: chains with <point> tags score higher
  - Accuracy scoring: correct coordinates score higher
  - Penalty: repeated coordinates get penalized
  - Anomaly detection: coordinate repetition identified
  - Smooth penalty function is monotonically increasing
  - RewardModel forward pass shape
  - predict_reward() returns valid PredictedReward
"""

from __future__ import annotations

import math

import pytest

from kicad_agent.training.chains import MazeReasoningChain, synthesize_maze_chain
from kicad_agent.training.dataset import MazeSample
from kicad_agent.training.reward import (
    ChainReward,
    RewardConfig,
    RewardSignal,
    score_chain,
)
from kicad_agent.training.reward_hacking import (
    AnomalyReport,
    detect_anomalies,
    smooth_penalty,
)
from kicad_agent.training.reward_model import RewardModel, predict_reward


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def easy_sample() -> MazeSample:
    """An easy MazeSample for reward testing."""
    return MazeSample(
        sample_id=0,
        seed=42,
        board_width_mm=50.0,
        board_height_mm=50.0,
        grid_size_mm=5.0,
        obstacle_count=3,
        obstacle_positions=((10.0, 10.0), (20.0, 20.0), (30.0, 30.0)),
        source_point=(2.5, 2.5),
        target_point=(47.5, 47.5),
        solution_path=((2.5, 2.5), (7.5, 7.5), (47.5, 47.5)),
        solution_length=3,
        difficulty="easy",
        board_hash="reward_test_0",
    )


@pytest.fixture
def easy_chain(easy_sample: MazeSample) -> MazeReasoningChain:
    """A solution chain from the easy sample."""
    return synthesize_maze_chain(easy_sample)


# ======================================================================
# TestRewardSignal
# ======================================================================


class TestRewardSignal:
    """RewardSignal construction."""

    def test_construction(self) -> None:
        """RewardSignal fields are set correctly."""
        rs = RewardSignal(
            step_index=0,
            format_score=0.8,
            quality_score=0.6,
            accuracy_score=0.9,
            penalty=0.0,
            total=0.77,
        )
        assert rs.step_index == 0
        assert rs.format_score == 0.8
        assert rs.total == 0.77

    def test_frozen(self) -> None:
        """RewardSignal is frozen."""
        rs = RewardSignal(step_index=0, format_score=0.5, quality_score=0.5, accuracy_score=0.5, penalty=0.0, total=0.5)
        from dataclasses import FrozenInstanceError
        with pytest.raises(FrozenInstanceError):
            rs.total = 1.0  # type: ignore[misc]


# ======================================================================
# TestChainReward
# ======================================================================


class TestChainReward:
    """ChainReward construction."""

    def test_construction(self, easy_chain: MazeReasoningChain, easy_sample: MazeSample) -> None:
        """ChainReward has correct fields."""
        reward = score_chain(easy_chain, easy_sample)
        assert reward.chain_id == 0
        assert reward.sample_id == 0
        assert len(reward.step_rewards) == 5  # solution chain has 5 steps
        assert isinstance(reward.total_reward, float)
        assert isinstance(reward.reward_density, float)


# ======================================================================
# TestScoreChain
# ======================================================================


class TestScoreChain:
    """score_chain() scoring behavior."""

    def test_returns_correct_step_count(self, easy_chain: MazeReasoningChain, easy_sample: MazeSample) -> None:
        """Returns one RewardSignal per step."""
        reward = score_chain(easy_chain, easy_sample)
        assert len(reward.step_rewards) == len(easy_chain.steps)

    def test_format_score_high_with_coords(self, easy_chain: MazeReasoningChain, easy_sample: MazeSample) -> None:
        """Steps with coordinate references score higher on format."""
        reward = score_chain(easy_chain, easy_sample)
        # Steps 0 (observation), 2 (coordinate_reference) should have decent format
        assert reward.step_rewards[0].format_score >= 0.5

    def test_accuracy_score_for_correct_coords(self, easy_chain: MazeReasoningChain, easy_sample: MazeSample) -> None:
        """Steps referencing correct coordinates get good accuracy."""
        reward = score_chain(easy_chain, easy_sample)
        # coordinate_reference step (index 2) should have high accuracy
        assert reward.step_rewards[2].accuracy_score >= 0.3

    def test_total_reward_is_sum(self, easy_chain: MazeReasoningChain, easy_sample: MazeSample) -> None:
        """Total reward equals sum of step totals."""
        reward = score_chain(easy_chain, easy_sample)
        expected_total = sum(sr.total for sr in reward.step_rewards)
        assert abs(reward.total_reward - expected_total) < 0.01

    def test_reward_density_is_total_over_steps(self, easy_chain: MazeReasoningChain, easy_sample: MazeSample) -> None:
        """Reward density equals total_reward / num_steps."""
        reward = score_chain(easy_chain, easy_sample)
        expected_density = reward.total_reward / len(reward.step_rewards)
        assert abs(reward.reward_density - expected_density) < 0.01

    def test_all_scores_bounded(self, easy_chain: MazeReasoningChain, easy_sample: MazeSample) -> None:
        """All scores are within valid bounds."""
        reward = score_chain(easy_chain, easy_sample)
        for sr in reward.step_rewards:
            assert 0.0 <= sr.format_score <= 1.0
            assert 0.0 <= sr.quality_score <= 1.0
            assert 0.0 <= sr.accuracy_score <= 1.0
            assert -1.0 <= sr.total <= 1.0


# ======================================================================
# TestPenalty
# ======================================================================


class TestPenalty:
    """Anti-hacking penalty scoring."""

    def test_penalty_for_repeated_coords(self, easy_sample: MazeSample) -> None:
        """Chain with repeated coordinates gets penalized."""
        # Create a chain with heavy coordinate repetition
        repeated_chain = MazeReasoningChain(
            sample_id=0,
            difficulty="easy",
            chain_text="test",
            steps=tuple(
                {
                    "step_type": "observation",
                    "text": f"At <point 2.5,2.5> and <point 2.5,2.5>",
                    "coordinates": [(2.5, 2.5), (2.5, 2.5)],
                }
                for _ in range(10)  # many steps with same coord
            ),
            coordinates_referenced=((2.5, 2.5),),
            is_correct=False,
            exploration_branches=0,
        )
        reward = score_chain(repeated_chain, easy_sample)
        # Should have some penalty
        has_penalty = any(sr.penalty < 0 for sr in reward.step_rewards)
        assert has_penalty


# ======================================================================
# TestAnomalyDetection
# ======================================================================


class TestAnomalyDetection:
    """detect_anomalies() identifies issues."""

    def test_empty_rewards(self) -> None:
        """Empty rewards list returns no anomalies."""
        reports = detect_anomalies([])
        assert reports == []

    def test_single_reward(self) -> None:
        """Single reward returns no anomalies (need statistics)."""
        reward = ChainReward(
            chain_id=0, sample_id=0,
            step_rewards=tuple(RewardSignal(i, 0.5, 0.5, 0.5, 0.0, 0.5) for i in range(5)),
            total_reward=2.5, reward_density=0.5,
        )
        reports = detect_anomalies([reward])
        assert reports == []

    def test_score_inflation_detected(self) -> None:
        """High reward_density with few steps triggers score_inflation."""
        inflated = ChainReward(
            chain_id=0, sample_id=0,
            step_rewards=tuple(RewardSignal(i, 1.0, 1.0, 1.0, 0.0, 1.0) for i in range(3)),
            total_reward=3.0, reward_density=0.95,
        )
        normal = ChainReward(
            chain_id=1, sample_id=1,
            step_rewards=tuple(RewardSignal(i, 0.5, 0.5, 0.5, 0.0, 0.5) for i in range(5)),
            total_reward=2.5, reward_density=0.5,
        )
        reports = detect_anomalies([inflated, normal])
        types = [r.anomaly_type for r in reports]
        assert "score_inflation" in types

    def test_length_anomaly_detected(self) -> None:
        """Very long chain triggers length_anomaly."""
        # Create several normal-length chains and one outlier
        normal_rewards = [
            ChainReward(
                chain_id=i, sample_id=i,
                step_rewards=tuple(RewardSignal(j, 0.5, 0.5, 0.5, 0.0, 0.5) for j in range(5 + i)),
                total_reward=2.5, reward_density=0.5,
            )
            for i in range(10)  # lengths 5-14
        ]
        very_long = ChainReward(
            chain_id=99, sample_id=99,
            step_rewards=tuple(RewardSignal(i, 0.5, 0.5, 0.5, 0.0, 0.5) for i in range(200)),
            total_reward=100.0, reward_density=0.5,
        )
        reports = detect_anomalies(normal_rewards + [very_long])
        types = [r.anomaly_type for r in reports]
        assert "length_anomaly" in types


# ======================================================================
# TestSmoothPenalty
# ======================================================================


class TestSmoothPenalty:
    """smooth_penalty() behavior."""

    def test_returns_non_positive(self) -> None:
        """Smooth penalty is always non-positive."""
        result = smooth_penalty(0.5, 0.8)
        assert result <= 0

    def test_monotonically_increasing_with_severity(self) -> None:
        """Penalty magnitude increases with severity."""
        p1 = smooth_penalty(0.5, 0.2)
        p2 = smooth_penalty(0.5, 0.5)
        p3 = smooth_penalty(0.5, 0.8)
        assert p1 >= p2 >= p3  # more negative = bigger penalty

    def test_zero_raw_penalty(self) -> None:
        """Zero raw penalty returns zero."""
        assert smooth_penalty(0.0, 0.5) == 0.0

    def test_negative_raw_handled(self) -> None:
        """Negative raw penalty is handled (abs taken)."""
        result = smooth_penalty(-0.5, 0.5)
        assert result <= 0


# ======================================================================
# TestRewardModel
# ======================================================================


class TestRewardModel:
    """Neural reward model tests (CPU only)."""

    def test_model_creation(self) -> None:
        """RewardModel can be created."""
        model = RewardModel(device="cpu")
        assert model is not None

    def test_model_available(self) -> None:
        """Model reports availability based on PyTorch."""
        model = RewardModel(device="cpu")
        # PyTorch is installed in this environment
        assert model.is_available

    def test_predict_reward(self) -> None:
        """predict_reward returns valid PredictedReward."""
        model = RewardModel(device="cpu")
        result = predict_reward(model, "Observation: via at <point 5.0,10.0>")
        assert isinstance(result.format_score, float)
        assert isinstance(result.quality_score, float)
        assert isinstance(result.accuracy_score, float)
        assert 0.0 <= result.format_score <= 1.0
        assert 0.0 <= result.quality_score <= 1.0
        assert 0.0 <= result.accuracy_score <= 1.0

    def test_forward_pass_shape(self) -> None:
        """Model forward pass produces correct output shapes."""
        import torch

        model = RewardModel(device="cpu")
        if not model.is_available:
            pytest.skip("PyTorch not available")

        nn_model = model.model
        nn_model.eval()

        # Create dummy input
        input_ids = torch.randint(0, 100, (2, 64))
        attn_mask = torch.ones(2, 64, dtype=torch.long)

        with torch.no_grad():
            fmt, qual, acc = nn_model(input_ids, attn_mask)

        assert fmt.shape == (2, 1)
        assert qual.shape == (2, 1)
        assert acc.shape == (2, 1)
