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
from kicad_agent.training.tokenizer import ChainTokenizer

logger = logging.getLogger(__name__)


@dataclass
class TrainingPipelineConfig:
    """Configuration for the full training pipeline.

    Attributes:
        n_samples: Number of maze samples to generate.
        n_chains_per_sample: Chains per sample (1=solution, 2=solution+exploration).
        seed: Deterministic random seed.
        device: "cpu" or "cuda" (auto-detects CUDA availability).
        output_dir: Directory for all outputs.
        reward_config: Optional reward scoring configuration.
        grpo_config: Optional GRPO training configuration.
        n_grpo_epochs: Number of GRPO training epochs (default 5).
        max_train_chains: Max chains for reward model training (0=all).
        hard_board_ratio: Fraction of hard/adversarial boards (0..1).
        lr_schedule: "cosine" (default), "linear", or "constant".
        warmup_steps: Number of warmup steps for LR schedule.
    """

    n_samples: int = 100_000
    n_chains_per_sample: int = 2
    seed: int = 42
    device: str = "cpu"
    output_dir: str = "training_output/"
    reward_config: RewardConfig | None = None
    grpo_config: GRPOConfig | None = None
    n_grpo_epochs: int = 5
    max_train_chains: int = 0
    hard_board_ratio: float = 0.4
    lr_schedule: str = "cosine"
    warmup_steps: int = 100

    def __post_init__(self):
        """Auto-detect GPU if device is 'cpu' and a GPU is available."""
        if self.device == "cpu":
            try:
                import torch
                if torch.cuda.is_available():
                    self.device = "cuda"
                    logger.info("CUDA detected — using GPU")
                elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    self.device = "mps"
                    logger.info("Apple MPS detected — using Metal GPU")
            except ImportError:
                pass


def _build_board_configs(hard_ratio: float) -> list[dict]:
    """Build board configs with a mix of easy and hard boards.

    Args:
        hard_ratio: Fraction of configs that should be hard/adversarial.

    Returns:
        List of board configuration dicts.
    """
    easy_configs = [
        {"width_mm": 30.0, "height_mm": 30.0, "grid_size_mm": 5.0},
        {"width_mm": 40.0, "height_mm": 40.0, "grid_size_mm": 4.0},
        {"width_mm": 50.0, "height_mm": 50.0, "grid_size_mm": 5.0},
    ]
    hard_configs = [
        {"width_mm": 80.0, "height_mm": 60.0, "grid_size_mm": 3.0},
        {"width_mm": 100.0, "height_mm": 80.0, "grid_size_mm": 3.0},
        {"width_mm": 120.0, "height_mm": 100.0, "grid_size_mm": 2.5},
        {"width_mm": 80.0, "height_mm": 80.0, "grid_size_mm": 2.0},
    ]
    # Build mixed list proportional to hard_ratio
    n_hard = max(1, int(len(hard_configs) * hard_ratio / 0.5))
    mixed = easy_configs + hard_configs[:n_hard] + hard_configs
    return mixed


def run_pipeline(config: TrainingPipelineConfig) -> dict:
    """Execute the full GRPO training pipeline.

    Steps:
      1. Generate dataset (with hard board mix)
      2. Split train/val/test
      3. Synthesize chains and score (ground truth)
      4. Train reward model
      5. Evaluate baseline
      6. GRPO train (multi-epoch with LR schedule)
      7. Evaluate trained model
      8. Compare results
      9. Save report

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
            "n_grpo_epochs": config.n_grpo_epochs,
            "hard_board_ratio": config.hard_board_ratio,
            "lr_schedule": config.lr_schedule,
            "warmup_steps": config.warmup_steps,
        },
        "steps": {},
    }

    # Step 1: Generate dataset with hard board mix
    logger.info("Step 1: Generating %d maze samples (hard_ratio=%.0f%%)...",
                config.n_samples, config.hard_board_ratio * 100)
    board_configs = _build_board_configs(config.hard_board_ratio)
    dataset = generate_dataset(
        n_samples=config.n_samples,
        seed_base=config.seed,
        board_configs=board_configs,
    )
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
    # No artificial cap — use max_train_chains (0 = all)
    max_chains = config.max_train_chains if config.max_train_chains > 0 else len(train_ds.samples)
    n_to_score = min(max_chains, len(train_ds.samples))
    logger.info("Step 3: Scoring %d training chains...", n_to_score)
    train_texts: list[str] = []
    train_labels: list[tuple[float, float, float]] = []

    reward_config = config.reward_config or RewardConfig()
    for sample in train_ds.samples[:n_to_score]:
        chain = synthesize_maze_chain(sample)
        chain_reward = score_chain(chain, sample, reward_config)
        train_texts.append(chain.chain_text)
        # Average scores across steps
        fmt_avg = sum(sr.format_score for sr in chain_reward.step_rewards) / max(len(chain_reward.step_rewards), 1)
        qual_avg = sum(sr.quality_score for sr in chain_reward.step_rewards) / max(len(chain_reward.step_rewards), 1)
        acc_avg = sum(sr.accuracy_score for sr in chain_reward.step_rewards) / max(len(chain_reward.step_rewards), 1)
        train_labels.append((fmt_avg, qual_avg, acc_avg))

    report["steps"]["chains"] = {"n_scored": len(train_texts)}

    # Step 4: Train tokenizer + reward model
    logger.info("Step 4: Training tokenizer on %d texts...", len(train_texts))
    tokenizer = ChainTokenizer(vocab_size=8000)
    tokenizer.train(train_texts)
    logger.info("Tokenizer vocab size: %d", tokenizer.vocab_size_actual)

    logger.info("Step 4: Training reward model on %d samples...", len(train_texts))
    reward_model = RewardModel(device=config.device)
    reward_model.set_tokenizer(tokenizer)
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
            "tokenizer_vocab_size": tokenizer.vocab_size_actual,
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

    # Step 6: GRPO training (multi-epoch with LR schedule)
    logger.info("Step 6: GRPO training (%d epochs, %s LR schedule)...",
                config.n_grpo_epochs, config.lr_schedule)
    grpo_config = config.grpo_config or GRPOConfig(
        seed=config.seed,
        output_dir=str(output_dir / "checkpoints"),
    )

    # Use a frozen copy of the reward model as reference (same tokenizer)
    ref_model = RewardModel(device=config.device)
    ref_model.set_tokenizer(tokenizer)
    trainer = GRPOTrainer(
        policy_model=reward_model,
        reward_model=reward_model,
        ref_model=ref_model,
        config=grpo_config,
    )

    grpo_history = trainer.train(
        train_ds,
        n_epochs=config.n_grpo_epochs,
        batch_size=8,
    )
    report["steps"]["grpo"] = {
        "n_epochs": config.n_grpo_epochs,
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
        "discrimination_gap": trained_result.discrimination_gap,
    }

    # Step 8: Compare
    comparison = harness.compare(None, reward_model)
    report["comparison"] = {
        "delta_reward": comparison["delta_reward"],
        "delta_accuracy": comparison["delta_accuracy"],
        "delta_pass_rate": comparison["delta_pass_rate"],
        "discrimination_gap": trained_result.discrimination_gap,
    }

    # Save report
    elapsed = time.time() - start_time
    report["elapsed_seconds"] = round(elapsed, 2)

    report_path = output_dir / "eval_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info("Pipeline complete in %.1fs. Report: %s", elapsed, report_path)
    return report
