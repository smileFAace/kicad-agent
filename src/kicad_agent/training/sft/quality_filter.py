"""Reward model quality filtering and train/val/test splitting for SFT data.

Scores ChatML samples using the trained reward model and removes the bottom
quartile. Splits retained samples into deterministic 80/10/10 splits.

Usage:
    from kicad_agent.training.sft.quality_filter import (
        filter_by_reward_model,
        split_and_save,
    )

    filtered = filter_by_reward_model(samples, "training_output/unified", keep_fraction=0.75)
    counts = split_and_save(filtered, Path("training_output/sft_prepared"))
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from kicad_agent.training.reward_model import RewardModel, predict_reward
from kicad_agent.training.sft.converter import ChatMLSample


def filter_by_reward_model(
    samples: list[ChatMLSample],
    model_dir: str,
    keep_fraction: float = 0.75,
    batch_size: int = 32,
) -> list[ChatMLSample]:
    """Score samples with reward model and keep top fraction.

    Loads the trained reward model, scores each sample's assistant response,
    sorts by composite score, and retains the top keep_fraction.

    Args:
        samples: ChatML samples to score.
        model_dir: Directory containing reward_model.pt and tokenizer.json.
        keep_fraction: Fraction of samples to keep (0.75 = remove bottom 25%).
        batch_size: Unused batch_size parameter (scores one at a time for simplicity).

    Returns:
        Filtered list of ChatMLSamples with quality_score set.
    """
    if not samples:
        return []

    # Load reward model
    reward_model = RewardModel.load_trained(model_dir)

    # Score each sample
    scored: list[tuple[float, ChatMLSample]] = []
    for sample in samples:
        assistant_text = sample.messages[-1]["content"]
        pred = predict_reward(reward_model, assistant_text)
        composite = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0
        scored.append((composite, sample))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # Keep top fraction
    keep_count = max(1, int(len(scored) * keep_fraction))
    retained = scored[:keep_count]

    # Set quality_score on retained samples
    result: list[ChatMLSample] = []
    for score, sample in retained:
        # Create new frozen instance with quality_score set
        scored_sample = ChatMLSample(
            messages=sample.messages,
            source=sample.source,
            source_id=sample.source_id,
            quality_score=score,
        )
        result.append(scored_sample)

    return result


def split_and_save(
    samples: list[ChatMLSample],
    output_dir: Path,
    seed: int = 42,
) -> dict[str, int]:
    """Deterministically split samples into train/val/test and save as JSONL.

    Uses seeded shuffle for reproducible 80/10/10 splits.

    Args:
        samples: ChatML samples to split.
        output_dir: Directory to write train.jsonl, val.jsonl, test.jsonl.
        seed: Random seed for reproducibility.

    Returns:
        Dict with train, val, test counts.
    """
    if not samples:
        return {"train": 0, "val": 0, "test": 0}

    output_dir.mkdir(parents=True, exist_ok=True)

    # Deterministic shuffle
    rng = random.Random(seed)
    indices = list(range(len(samples)))
    rng.shuffle(indices)

    shuffled = [samples[i] for i in indices]

    # 80/10/10 split
    n = len(shuffled)
    train_end = int(n * 0.8)
    val_end = train_end + int(n * 0.1)

    splits = {
        "train": shuffled[:train_end],
        "val": shuffled[train_end:val_end],
        "test": shuffled[val_end:],
    }

    counts: dict[str, int] = {}
    for split_name, split_samples in splits.items():
        filepath = output_dir / f"{split_name}.jsonl"
        with open(filepath, "w") as f:
            for sample in split_samples:
                record = {
                    "messages": [
                        {"role": m["role"], "content": m["content"]}
                        for m in sample.messages
                    ],
                    "source": sample.source,
                    "source_id": sample.source_id,
                }
                if sample.quality_score is not None:
                    record["quality_score"] = sample.quality_score
                f.write(json.dumps(record) + "\n")
        counts[split_name] = len(split_samples)

    return counts
