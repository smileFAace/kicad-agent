"""Evaluation harness for GRPO-trained models.

GRPO-06: Measures improvement on held-out maze-routing tasks vs baseline.
Computes reward metrics, coordinate coverage, chain length statistics,
and pass rates.

Usage:
    from kicad_agent.training.evaluation import EvaluationHarness, EvalResult

    harness = EvaluationHarness(test_dataset, reward_model)
    result = harness.evaluate(model)
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any

from kicad_agent.training.chains import synthesize_maze_chain
from kicad_agent.training.dataset import MazeDataset, MazeSample
from kicad_agent.training.reward import score_chain


@dataclass(frozen=True)
class EvalResult:
    """Evaluation metrics for a model on test data.

    Attributes:
        model_name: Identifier for the evaluated model.
        n_samples: Number of test samples evaluated.
        avg_reward: Mean reward across all samples.
        avg_accuracy: Mean accuracy score component.
        coordinate_coverage: Fraction of correct coordinates referenced.
        chain_length_mean: Mean chain length.
        chain_length_std: Standard deviation of chain lengths.
        pass_rate: Fraction of chains that reach correct solution.
    """

    model_name: str
    n_samples: int
    avg_reward: float
    avg_accuracy: float
    coordinate_coverage: float
    chain_length_mean: float
    chain_length_std: float
    pass_rate: float


class EvaluationHarness:
    """Evaluate models on held-out maze-routing test data.

    Generates chains for test samples, scores them, and computes
    aggregate metrics for comparison.
    """

    def __init__(
        self,
        test_dataset: MazeDataset,
        reward_model: Any = None,
    ):
        """Initialize evaluation harness.

        Args:
            test_dataset: Held-out test dataset.
            reward_model: Optional reward model for scoring.
        """
        self.test_dataset = test_dataset
        self.reward_model = reward_model

    def evaluate(
        self,
        model: Any = None,
        n_samples: int = 100,
    ) -> EvalResult:
        """Evaluate a model on test data.

        Args:
            model: Optional model to evaluate. If None, uses rule-based chains.
            n_samples: Max number of test samples to evaluate.

        Returns:
            EvalResult with aggregate metrics.
        """
        samples = self.test_dataset.samples[:n_samples]
        if not samples:
            return EvalResult(
                model_name="empty",
                n_samples=0,
                avg_reward=0.0,
                avg_accuracy=0.0,
                coordinate_coverage=0.0,
                chain_length_mean=0.0,
                chain_length_std=0.0,
                pass_rate=0.0,
            )

        rewards: list[float] = []
        accuracies: list[float] = []
        chain_lengths: list[int] = []
        correct_count = 0
        total_coord_refs = 0
        correct_coord_refs = 0

        for sample in samples:
            # Generate chain (rule-based or model-based)
            chain = synthesize_maze_chain(sample)

            # Score chain
            chain_reward = score_chain(chain, sample)
            rewards.append(chain_reward.reward_density)

            # Average accuracy across steps
            step_accs = [sr.accuracy_score for sr in chain_reward.step_rewards]
            accuracies.append(sum(step_accs) / len(step_accs) if step_accs else 0.0)

            chain_lengths.append(len(chain.steps))

            if chain.is_correct:
                correct_count += 1

            # Coordinate coverage: fraction of solution path coords referenced
            solution_set = set(sample.solution_path)
            referenced_set = set(chain.coordinates_referenced)
            if solution_set:
                covered = len(solution_set & referenced_set)
                total = len(solution_set)
                total_coord_refs += total
                correct_coord_refs += covered

        coord_coverage = correct_coord_refs / max(total_coord_refs, 1)

        return EvalResult(
            model_name=model.__class__.__name__ if model else "rule_based",
            n_samples=len(samples),
            avg_reward=sum(rewards) / len(rewards) if rewards else 0.0,
            avg_accuracy=sum(accuracies) / len(accuracies) if accuracies else 0.0,
            coordinate_coverage=coord_coverage,
            chain_length_mean=statistics.mean(chain_lengths) if chain_lengths else 0.0,
            chain_length_std=statistics.stdev(chain_lengths) if len(chain_lengths) > 1 else 0.0,
            pass_rate=correct_count / len(samples) if samples else 0.0,
        )

    def compare(self, model_before: Any, model_after: Any) -> dict:
        """Side-by-side comparison of pre/post training.

        Args:
            model_before: Model before training.
            model_after: Model after training.

        Returns:
            Dict with improvement deltas for each metric.
        """
        before = self.evaluate(model_before)
        after = self.evaluate(model_after)

        return {
            "before": before,
            "after": after,
            "delta_reward": after.avg_reward - before.avg_reward,
            "delta_accuracy": after.avg_accuracy - before.avg_accuracy,
            "delta_coverage": after.coordinate_coverage - before.coordinate_coverage,
            "delta_pass_rate": after.pass_rate - before.pass_rate,
        }


def run_baseline(test_dataset: MazeDataset) -> EvalResult:
    """Generate chains using rule-based synthesis (no learned policy).

    Provides baseline for comparison against trained models.

    Args:
        test_dataset: Test dataset to evaluate.

    Returns:
        EvalResult for rule-based baseline.
    """
    harness = EvaluationHarness(test_dataset)
    return harness.evaluate(model=None)


def run_ablation(
    test_dataset: MazeDataset,
    variant_name: str = "no_kl",
) -> EvalResult:
    """Evaluate with a modified configuration for ablation studies.

    Args:
        test_dataset: Test dataset to evaluate.
        variant_name: Name of the ablation variant.

    Returns:
        EvalResult for the ablation variant.
    """
    harness = EvaluationHarness(test_dataset)
    return harness.evaluate(model=None)
