"""Supervised Fine-Tuning (SFT) data preparation and training.

Converts maze reasoning chains to ChatML instruction-following format,
filters by reward model quality, and produces train/val/test splits
for SFT training with TRL SFTTrainer.

Submodules:

- `templates`: System prompts and task-specific prompt templates
- `converter`: Chain-to-ChatML conversion pipeline
- `quality_filter`: Reward model scoring and train/val/test splitting
- `trainer`: SFTTrainer wrapper with MPS-compatible config
- `evaluator`: SFT evaluation comparing base vs trained model

Usage:
    from kicad_agent.training.sft import convert_chains_to_chatml, filter_and_split

    samples = convert_chains_to_chatml(Path("training_output/chains_100k.jsonl"))
"""

from kicad_agent.training.sft.converter import ChatMLSample, convert_chains_to_chatml
from kicad_agent.training.sft.quality_filter import filter_by_reward_model, split_and_save


def filter_and_split(
    samples: list[ChatMLSample],
    model_dir: str,
    output_dir: str,
    keep_fraction: float = 0.75,
    seed: int = 42,
) -> dict:
    """Run quality filtering and splitting in one call.

    Args:
        samples: ChatML samples to process.
        model_dir: Directory with trained reward model.
        output_dir: Directory to write JSONL splits.
        keep_fraction: Fraction of samples to keep after filtering.
        seed: Random seed for reproducibility.

    Returns:
        Dict with filtering and split metrics.
    """
    filtered = filter_by_reward_model(samples, model_dir, keep_fraction=keep_fraction)
    counts = split_and_save(filtered, output_dir=Path(output_dir), seed=seed)
    return {
        "input_count": len(samples),
        "filtered_count": len(filtered),
        "splits": counts,
    }


__all__ = [
    "ChatMLSample",
    "convert_chains_to_chatml",
    "filter_and_split",
]
