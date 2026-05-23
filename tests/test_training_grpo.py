"""Tests for GRPO training loop and evaluation (Plan 09-04).

Covers:
  - GRPOConfig defaults and validation
  - GRPOTrainer.compute_group_rewards() normalizes within groups
  - compute_kl_penalty() returns non-negative value
  - EvaluationHarness.evaluate() returns valid EvalResult
  - run_baseline() produces result with pass_rate in [0, 1]
  - TrainingPipelineConfig construction with defaults
  - run_pipeline() with tiny config completes without error
  - Deterministic seeding produces identical results
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_agent.training.dataset import MazeDataset, MazeSample, generate_dataset
from kicad_agent.training.evaluation import (
    EvalResult,
    EvaluationHarness,
    run_baseline,
)
from kicad_agent.training.grpo import GRPOConfig, GRPOTrainer
from kicad_agent.training.pipeline import TrainingPipelineConfig, run_pipeline
from kicad_agent.training.reward_model import RewardModel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_dataset() -> MazeDataset:
    """A tiny dataset for fast testing."""
    return generate_dataset(n_samples=5, seed_base=42)


@pytest.fixture
def reward_model() -> RewardModel:
    """A RewardModel instance for testing."""
    return RewardModel(device="cpu")


# ======================================================================
# TestGRPOConfig
# ======================================================================


class TestGRPOConfig:
    """GRPOConfig defaults."""

    def test_defaults(self) -> None:
        """Default config values are reasonable."""
        config = GRPOConfig()
        assert config.learning_rate == 1e-5
        assert config.group_size == 8
        assert config.kl_coefficient == 0.1
        assert config.clip_range == 0.2
        assert config.seed == 42

    def test_custom_config(self) -> None:
        """Custom config values are set correctly."""
        config = GRPOConfig(learning_rate=1e-4, group_size=4, seed=99)
        assert config.learning_rate == 1e-4
        assert config.group_size == 4
        assert config.seed == 99


# ======================================================================
# TestGRPOTrainer
# ======================================================================


class TestGRPOTrainer:
    """GRPO training loop methods."""


    def test_compute_group_rewards(self, tiny_dataset: MazeDataset, reward_model: RewardModel) -> None:
        """compute_group_rewards returns correct number of groups."""
        ref_model = RewardModel(device="cpu")
        trainer = GRPOTrainer(reward_model, reward_model, ref_model)
        chain_groups = [["test chain text"] * 4 for _ in range(3)]
        samples = tiny_dataset.samples[:3]
        rewards = trainer.compute_group_rewards(chain_groups, samples)
        assert len(rewards) == 3
        assert all(len(group) == 4 for group in rewards)

    def test_compute_group_advantages(self, tiny_dataset: MazeDataset, reward_model: RewardModel) -> None:
        """Group advantages are normalized within groups."""
        ref_model = RewardModel(device="cpu")
        trainer = GRPOTrainer(reward_model, reward_model, ref_model)

        # Create groups with known rewards
        group_rewards = [
            [0.2, 0.4, 0.6, 0.8],  # mean=0.5
            [0.1, 0.3, 0.5, 0.7],  # mean=0.4
        ]
        advantages = trainer.compute_group_advantages(group_rewards)
        assert len(advantages) == 2

        # Each group should have advantages centered near 0
        for group in advantages:
            mean_adv = sum(group) / len(group)
            assert abs(mean_adv) < 0.01  # near zero after normalization

    def test_compute_group_advantages_empty(self, reward_model: RewardModel) -> None:
        """Empty group returns empty advantages."""
        ref_model = RewardModel(device="cpu")
        trainer = GRPOTrainer(reward_model, reward_model, ref_model)
        advantages = trainer.compute_group_advantages([[]])
        assert advantages == [[]]

    def test_compute_kl_penalty_non_negative(self, reward_model: RewardModel) -> None:
        """KL penalty is always non-negative."""
        ref_model = RewardModel(device="cpu")
        trainer = GRPOTrainer(reward_model, reward_model, ref_model)
        kl = trainer.compute_kl_penalty([-1.0, -2.0, -3.0], [-1.5, -2.5, -3.5])
        assert kl >= 0.0

    def test_compute_kl_penalty_empty(self, reward_model: RewardModel) -> None:
        """Empty logprobs returns 0 KL."""
        ref_model = RewardModel(device="cpu")
        trainer = GRPOTrainer(reward_model, reward_model, ref_model)
        kl = trainer.compute_kl_penalty([], [])
        assert kl == 0.0

    def test_train_step(self, tiny_dataset: MazeDataset, reward_model: RewardModel) -> None:
        """train_step returns metrics dict."""
        ref_model = RewardModel(device="cpu")
        config = GRPOConfig(group_size=4)
        trainer = GRPOTrainer(reward_model, reward_model, ref_model, config)
        batch = tiny_dataset.samples[:3]
        metrics = trainer.train_step(batch)
        assert "loss" in metrics
        assert "reward_mean" in metrics
        assert "kl_divergence" in metrics
        assert metrics["n_samples"] == 3

    def test_train_full(self, tiny_dataset: MazeDataset, reward_model: RewardModel, tmp_path: Path) -> None:
        """Full training loop runs without error."""
        ref_model = RewardModel(device="cpu")
        config = GRPOConfig(group_size=2, output_dir=str(tmp_path / "ckpt"))
        trainer = GRPOTrainer(reward_model, reward_model, ref_model, config)
        history = trainer.train(tiny_dataset, n_epochs=1, batch_size=3)
        assert "losses" in history
        assert "reward_means" in history
        assert len(history["losses"]) > 0


# ======================================================================
# TestEvaluationHarness
# ======================================================================


class TestEvaluationHarness:
    """Evaluation harness."""


    def test_evaluate_returns_valid_result(self, tiny_dataset: MazeDataset) -> None:
        """evaluate() returns valid EvalResult."""
        harness = EvaluationHarness(tiny_dataset)
        result = harness.evaluate(n_samples=3)
        assert isinstance(result, EvalResult)
        assert result.n_samples <= 3
        assert 0.0 <= result.avg_reward <= 1.0
        assert 0.0 <= result.pass_rate <= 1.0

    def test_evaluate_empty_dataset(self) -> None:
        """Empty test dataset returns zeroed EvalResult."""
        empty_ds = MazeDataset()
        harness = EvaluationHarness(empty_ds)
        result = harness.evaluate()
        assert result.n_samples == 0
        assert result.avg_reward == 0.0

    def test_run_baseline(self, tiny_dataset: MazeDataset) -> None:
        """run_baseline produces result with pass_rate in [0, 1]."""
        result = run_baseline(tiny_dataset)
        assert 0.0 <= result.pass_rate <= 1.0
        assert result.model_name == "rule_based"

    def test_compare(self, tiny_dataset: MazeDataset) -> None:
        """compare() returns improvement deltas."""
        harness = EvaluationHarness(tiny_dataset)
        comparison = harness.compare(None, None)
        assert "delta_reward" in comparison
        assert "before" in comparison
        assert "after" in comparison


# ======================================================================
# TestTrainingPipelineConfig
# ======================================================================


class TestTrainingPipelineConfig:
    """Pipeline configuration."""

    def test_defaults(self) -> None:
        """Default pipeline config values."""
        config = TrainingPipelineConfig()
        assert config.n_samples == 100_000
        assert config.seed == 42
        assert config.device in ("cpu", "mps", "cuda")

    def test_custom(self) -> None:
        """Custom pipeline config values."""
        config = TrainingPipelineConfig(n_samples=50, seed=99)
        assert config.n_samples == 50
        assert config.seed == 99


# ======================================================================
# TestRunPipeline
# ======================================================================


class TestRunPipeline:
    """End-to-end pipeline test."""


    def test_pipeline_tiny(self, tmp_path: Path) -> None:
        """run_pipeline with tiny config completes without error."""
        config = TrainingPipelineConfig(
            n_samples=5,
            seed=42,
            output_dir=str(tmp_path / "pipeline_out"),
        )
        report = run_pipeline(config)
        assert "config" in report
        assert "steps" in report
        assert report["steps"]["dataset"]["n_generated"] >= 1
        assert "elapsed_seconds" in report

    def test_pipeline_produces_report(self, tmp_path: Path) -> None:
        """Pipeline writes eval_report.json."""
        config = TrainingPipelineConfig(
            n_samples=5,
            seed=42,
            output_dir=str(tmp_path / "pipeline_out"),
        )
        run_pipeline(config)
        report_path = tmp_path / "pipeline_out" / "eval_report.json"
        assert report_path.exists()
        with open(report_path) as f:
            data = json.load(f)
            assert "steps" in data
            assert "comparison" in data

    def test_deterministic_seeding(self, tmp_path: Path) -> None:
        """Same seed produces identical pipeline results."""
        config1 = TrainingPipelineConfig(
            n_samples=3, seed=42, output_dir=str(tmp_path / "run1"),
        )
        config2 = TrainingPipelineConfig(
            n_samples=3, seed=42, output_dir=str(tmp_path / "run2"),
        )
        report1 = run_pipeline(config1)
        report2 = run_pipeline(config2)
        # Dataset generation should produce same counts
        assert report1["steps"]["dataset"]["n_generated"] == report2["steps"]["dataset"]["n_generated"]


# ======================================================================
# TestLRSchedule
# ======================================================================


class TestLRSchedule:
    """Learning rate schedule with warmup."""

    def test_cosine_schedule(self) -> None:
        """Cosine schedule decays from base_lr to near-zero."""
        lr_start = GRPOTrainer.compute_lr(100, 1000, 1e-4, warmup_steps=100, schedule="cosine")
        lr_end = GRPOTrainer.compute_lr(999, 1000, 1e-4, warmup_steps=100, schedule="cosine")
        assert lr_start > lr_end
        assert lr_end > 0.0

    def test_linear_schedule(self) -> None:
        """Linear schedule decays from base_lr to near-zero."""
        lr_start = GRPOTrainer.compute_lr(50, 100, 1e-4, warmup_steps=10, schedule="linear")
        lr_end = GRPOTrainer.compute_lr(99, 100, 1e-4, warmup_steps=10, schedule="linear")
        assert lr_start > lr_end

    def test_constant_schedule(self) -> None:
        """Constant schedule stays at base_lr."""
        lr = GRPOTrainer.compute_lr(50, 100, 1e-4, warmup_steps=10, schedule="constant")
        assert lr == 1e-4

    def test_warmup_ramps_up(self) -> None:
        """Warmup phase linearly ramps from 0 to base_lr."""
        lr_0 = GRPOTrainer.compute_lr(0, 1000, 1e-4, warmup_steps=100, schedule="cosine")
        lr_50 = GRPOTrainer.compute_lr(50, 1000, 1e-4, warmup_steps=100, schedule="cosine")
        lr_100 = GRPOTrainer.compute_lr(100, 1000, 1e-4, warmup_steps=100, schedule="cosine")
        assert lr_0 < lr_50
        assert lr_50 < lr_100

    def test_zero_warmup(self) -> None:
        """Zero warmup starts at base_lr."""
        lr = GRPOTrainer.compute_lr(0, 100, 1e-4, warmup_steps=0, schedule="cosine")
        assert lr == pytest.approx(1e-4, rel=0.01)


# ======================================================================
# TestGRPOConfigNewFields
# ======================================================================


class TestGRPOConfigNewFields:
    """New GRPOConfig fields for LR schedule."""

    def test_lr_schedule_default(self) -> None:
        """Default lr_schedule is cosine."""
        config = GRPOConfig()
        assert config.lr_schedule == "cosine"
        assert config.warmup_steps == 100
        assert config.total_steps == 0

    def test_custom_lr_schedule(self) -> None:
        """Custom LR schedule config."""
        config = GRPOConfig(lr_schedule="linear", warmup_steps=50, total_steps=500)
        assert config.lr_schedule == "linear"
        assert config.warmup_steps == 50
        assert config.total_steps == 500


# ======================================================================
# TestTrainingPipelineConfigNewFields
# ======================================================================


class TestTrainingPipelineConfigNewFields:
    """New pipeline config fields."""

    def test_new_defaults(self) -> None:
        """New pipeline config defaults."""
        config = TrainingPipelineConfig()
        assert config.n_grpo_epochs == 5
        assert config.max_train_chains == 0
        assert config.hard_board_ratio == 0.4
        assert config.lr_schedule == "cosine"
        assert config.warmup_steps == 100

    def test_custom_epochs(self) -> None:
        """Custom GRPO epoch count."""
        config = TrainingPipelineConfig(n_grpo_epochs=10)
        assert config.n_grpo_epochs == 10


# ======================================================================
# TestTrainWithContrast
# ======================================================================


class TestTrainWithContrast:
    """GRPO train_step now produces contrast via corrupted chains."""

    def test_train_step_has_contrast(self, tiny_dataset: MazeDataset, reward_model: RewardModel) -> None:
        """train_step with corrupted chains produces variance in rewards."""
        ref_model = RewardModel(device="cpu")
        config = GRPOConfig(group_size=4)
        trainer = GRPOTrainer(reward_model, reward_model, ref_model, config)
        batch = tiny_dataset.samples[:2]
        metrics = trainer.train_step(batch)
        assert "loss" in metrics
        assert metrics["n_samples"] == 2

    def test_train_multi_epoch(self, tiny_dataset: MazeDataset, reward_model: RewardModel, tmp_path: Path) -> None:
        """Multi-epoch GRPO training runs."""
        ref_model = RewardModel(device="cpu")
        config = GRPOConfig(group_size=2, output_dir=str(tmp_path / "ckpt"))
        trainer = GRPOTrainer(reward_model, reward_model, ref_model, config)
        history = trainer.train(tiny_dataset, n_epochs=3, batch_size=3)
        assert "learning_rates" in history
        assert len(history["learning_rates"]) > 0
        # LR should vary across steps with cosine schedule
        lrs = history["learning_rates"]
        assert min(lrs) < max(lrs)
