"""Single-command training pipeline for GRPO spatial reasoning.

GRPO-07: Reproducible end-to-end pipeline — dataset generation, chain synthesis,
reward model training, GRPO training, and evaluation — with configurable
hyperparameters and deterministic seeding.

Usage:
    from kicad_agent.training.pipeline import run_pipeline, TrainingPipelineConfig

    config = TrainingPipelineConfig(n_samples=100, seed=42)
    report = run_pipeline(config)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from kicad_agent.training.chains import synthesize_maze_chain
from kicad_agent.training.dataset import MazeDataset, generate_dataset
from kicad_agent.training.evaluation import EvaluationHarness, run_baseline
from kicad_agent.training.grpo import GRPOConfig, GRPOTrainer
from kicad_agent.training.reward import RewardConfig, score_chain
from kicad_agent.training.reward_model import RewardModel, train_reward_model

logger = logging.getLogger(__name__)


@dataclass
class TrainingPipelineConfig:
    """Configuration for the full training pipeline.

    Attributes:
        n_samples: Number of maze samples to generate.
        n_chains_per_sample: Chains per sample (1=solution, 2=solution+exploration).
        seed: Deterministic random seed.
        device: "cpu" or "cuda".
        output_dir: Directory for all outputs.
        reward_config: Optional reward scoring configuration.
        grpo_config: Optional GRPO training configuration.
    """

    n_samples: int = 100_000
    n_chains_per_sample: int = 2
    seed: int = 42
    device: str = "cpu"
    output_dir: str = "training_output/"
    reward_config: RewardConfig | None = None
    grpo_config: GRPOConfig | None = None


def run_pipeline(config: TrainingPipelineConfig) -> dict:
    """Execute the full GRPO training pipeline.

    Steps:
      1. Generate dataset
      2. Split train/val/test
      3. Synthesize chains
      4. Score chains (ground truth rewards)
      5. Train reward model
      6. Evaluate baseline
      7. GRPO train
      8. Evaluate trained model
      9. Compare results
      10. Save report

    Args:
        config: Pipeline configuration.

    Returns:
        Summary dict with all metrics and file paths.
    """
    start_time = time.time()
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "config": {
            "n_samples": config.n_samples,
            "seed": config.seed,
            "device": config.device,
        },
        "steps": {},
    }

    # Step 1: Generate dataset
    logger.info("Step 1: Generating %d maze samples...", config.n_samples)
    dataset = generate_dataset(n_samples=config.n_samples, seed_base=config.seed)
    report["steps"]["dataset"] = {
        "n_generated": len(dataset),
        "difficulty_counts": dataset.difficulty_counts,
    }

    # Step 2: Split
    logger.info("Step 2: Splitting dataset...")
    train_ds, val_ds, test_ds = dataset.split()
    report["steps"]["split"] = {
        "train": len(train_ds),
        "val": len(val_ds),
        "test": len(test_ds),
    }

    # Step 3: Synthesize chains and score (ground truth)
    logger.info("Step 3: Scoring training chains...")
    train_texts: list[str] = []
    train_labels: list[tuple[float, float, float]] = []

    reward_config = config.reward_config or RewardConfig()
    for sample in train_ds.samples[:1000]:  # Limit for CPU training
        chain = synthesize_maze_chain(sample)
        chain_reward = score_chain(chain, sample, reward_config)
        train_texts.append(chain.chain_text)
        # Average scores across steps
        fmt_avg = sum(sr.format_score for sr in chain_reward.step_rewards) / max(len(chain_reward.step_rewards), 1)
        qual_avg = sum(sr.quality_score for sr in chain_reward.step_rewards) / max(len(chain_reward.step_rewards), 1)
        acc_avg = sum(sr.accuracy_score for sr in chain_reward.step_rewards) / max(len(chain_reward.step_rewards), 1)
        train_labels.append((fmt_avg, qual_avg, acc_avg))

    report["steps"]["chains"] = {"n_scored": len(train_texts)}

    # Step 4: Train reward model
    logger.info("Step 4: Training reward model...")
    reward_model = RewardModel(device=config.device)
    if reward_model.is_available:
        rm_history = train_reward_model(
            reward_model,
            train_texts,
            train_labels,
            n_epochs=3,
            learning_rate=1e-4,
            batch_size=32,
        )
        report["steps"]["reward_model"] = {
            "final_loss": rm_history["losses"][-1] if rm_history.get("losses") else None,
        }
    else:
        report["steps"]["reward_model"] = {"status": "PyTorch not available"}

    # Step 5: Evaluate baseline
    logger.info("Step 5: Evaluating baseline...")
    baseline_result = run_baseline(test_ds)
    report["steps"]["baseline"] = {
        "avg_reward": baseline_result.avg_reward,
        "avg_accuracy": baseline_result.avg_accuracy,
        "pass_rate": baseline_result.pass_rate,
        "n_samples": baseline_result.n_samples,
    }

    # Step 6: GRPO training
    logger.info("Step 6: GRPO training...")
    grpo_config = config.grpo_config or GRPOConfig(
        seed=config.seed,
        output_dir=str(output_dir / "checkpoints"),
    )

    # Use a frozen copy of the reward model as reference
    ref_model = RewardModel(device=config.device)
    trainer = GRPOTrainer(
        policy_model=reward_model,
        reward_model=reward_model,
        ref_model=ref_model,
        config=grpo_config,
    )

    grpo_history = trainer.train(train_ds, n_epochs=1, batch_size=8)
    report["steps"]["grpo"] = {
        "n_steps": len(grpo_history["losses"]),
        "final_loss": grpo_history["losses"][-1] if grpo_history["losses"] else None,
        "final_reward_mean": grpo_history["reward_means"][-1] if grpo_history["reward_means"] else None,
    }

    # Step 7: Evaluate trained model
    logger.info("Step 7: Evaluating trained model...")
    harness = EvaluationHarness(test_ds, reward_model)
    trained_result = harness.evaluate(model=reward_model)
    report["steps"]["trained"] = {
        "avg_reward": trained_result.avg_reward,
        "avg_accuracy": trained_result.avg_accuracy,
        "pass_rate": trained_result.pass_rate,
        "n_samples": trained_result.n_samples,
    }

    # Step 8: Compare
    comparison = harness.compare(None, reward_model)
    report["comparison"] = {
        "delta_reward": comparison["delta_reward"],
        "delta_accuracy": comparison["delta_accuracy"],
        "delta_pass_rate": comparison["delta_pass_rate"],
    }

    # Save report
    elapsed = time.time() - start_time
    report["elapsed_seconds"] = round(elapsed, 2)

    report_path = output_dir / "eval_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info("Pipeline complete in %.1fs. Report: %s", elapsed, report_path)
    return report
