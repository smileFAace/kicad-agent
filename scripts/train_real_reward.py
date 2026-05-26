#!/usr/bin/env python3
"""Train reward model on real PCB board data.

Loads ingested PCB data from JSONL, synthesizes reasoning chains,
trains the reward model, and evaluates.

Usage:
    # First, ingest data:
    python scripts/train_real_pcbs.py --output-dir training_data

    # Then train:
    python scripts/train_real_reward.py --data-dir training_data --output-dir training_output/real_pcb_run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.training.real_dataset import RealBoardDataset  # noqa: E402
from kicad_agent.training.board_chains import (  # noqa: E402
    synthesize_board_chain,
    synthesize_corrupted_board_chain,
    _compute_chain_labels,
)
from kicad_agent.training.reward_model import (  # noqa: E402
    RewardModel,
    predict_reward,
    train_reward_model,
)
from kicad_agent.training.tokenizer import ChainTokenizer  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_real_reward")


def main() -> int:
    parser = argparse.ArgumentParser(description="Train reward model on real PCB data")
    parser.add_argument("--data-dir", type=Path, default=Path("training_data"))
    parser.add_argument("--output-dir", type=Path, default=Path("training_output/real_pcb_v1"))
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    start = time.time()

    # Auto-detect GPU
    if args.device == "cpu":
        try:
            import torch
            if torch.backends.mps.is_available():
                args.device = "mps"
                logger.info("Apple MPS detected — using Metal GPU")
            elif torch.cuda.is_available():
                args.device = "cuda"
                logger.info("CUDA detected — using GPU")
        except ImportError:
            pass

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "config": {
            "data_dir": str(args.data_dir),
            "device": args.device,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "learning_rate": args.lr,
        },
        "steps": {},
    }

    # 1. Load data
    logger.info("Step 1: Loading data from %s", args.data_dir)
    train_ds = RealBoardDataset.from_jsonl(args.data_dir / "train.jsonl")
    val_ds = RealBoardDataset.from_jsonl(args.data_dir / "val.jsonl")
    test_ds = RealBoardDataset.from_jsonl(args.data_dir / "test.jsonl")

    report["steps"]["data"] = {
        "train": len(train_ds),
        "val": len(val_ds),
        "test": len(test_ds),
        "difficulty_counts": train_ds.difficulty_counts,
    }
    logger.info("Loaded: train=%d, val=%d, test=%d", len(train_ds), len(val_ds), len(test_ds))
    logger.info("Train difficulty: %s", train_ds.difficulty_counts)

    # 2. Synthesize chains + labels
    logger.info("Step 2: Synthesizing chains for %d train + %d val samples", len(train_ds), len(val_ds))

    train_texts: list[str] = []
    train_labels: list[tuple[float, float, float]] = []

    for sample in train_ds.samples:
        # Correct chain
        correct = synthesize_board_chain(sample)
        train_texts.append(correct.chain_text)
        train_labels.append(_compute_chain_labels(correct, sample))

        # Corrupted chain (contrastive)
        corrupted = synthesize_corrupted_board_chain(sample, "vague_reasoning")
        train_texts.append(corrupted.chain_text)
        train_labels.append(_compute_chain_labels(corrupted, sample))

    val_texts: list[str] = []
    val_labels: list[tuple[float, float, float]] = []

    for sample in val_ds.samples:
        correct = synthesize_board_chain(sample)
        val_texts.append(correct.chain_text)
        val_labels.append(_compute_chain_labels(correct, sample))

    report["steps"]["chains"] = {"n_train": len(train_texts), "n_val": len(val_texts)}

    # 3. Train tokenizer
    logger.info("Step 3: Training tokenizer on %d texts", len(train_texts))
    tokenizer = ChainTokenizer(vocab_size=8000)
    tokenizer.train(train_texts)
    report["steps"]["tokenizer"] = {"vocab_size": tokenizer.vocab_size_actual}

    # 4. Train reward model
    logger.info("Step 4: Training reward model (%d epochs, device=%s)", args.epochs, args.device)
    model = RewardModel(device=args.device)
    model.set_tokenizer(tokenizer)

    if model.is_available:
        history = train_reward_model(
            model,
            train_texts,
            train_labels,
            val_texts=val_texts,
            val_labels=val_labels,
            n_epochs=args.epochs,
            learning_rate=args.lr,
            batch_size=args.batch_size,
        )
        report["steps"]["reward_model"] = {
            "final_loss": history["losses"][-1] if history.get("losses") else None,
            "final_val_loss": history["val_losses"][-1] if history.get("val_losses") else None,
            "losses": history.get("losses", []),
            "tokenizer_vocab_size": tokenizer.vocab_size_actual,
        }
    else:
        report["steps"]["reward_model"] = {"status": "PyTorch not available"}
        logger.error("PyTorch not available — cannot train")
        return 1

    # 5. Evaluate discrimination on test set
    logger.info("Step 5: Evaluating on %d test samples", len(test_ds))
    correct_scores: list[float] = []
    corrupted_scores: list[float] = []

    for sample in test_ds.samples:
        correct = synthesize_board_chain(sample)
        pred_c = predict_reward(model, correct.chain_text)
        correct_scores.append((pred_c.format_score + pred_c.quality_score + pred_c.accuracy_score) / 3.0)

        corrupted = synthesize_corrupted_board_chain(sample, "vague_reasoning")
        pred_x = predict_reward(model, corrupted.chain_text)
        corrupted_scores.append((pred_x.format_score + pred_x.quality_score + pred_x.accuracy_score) / 3.0)

    avg_correct = sum(correct_scores) / max(len(correct_scores), 1)
    avg_corrupted = sum(corrupted_scores) / max(len(corrupted_scores), 1)
    discrimination_gap = avg_correct - avg_corrupted

    # Check pass rate: model scores correct > corrupted
    passes = sum(1 for c, x in zip(correct_scores, corrupted_scores) if c > x)
    pass_rate = passes / max(len(correct_scores), 1)

    report["steps"]["evaluation"] = {
        "n_test": len(test_ds),
        "avg_correct_score": round(avg_correct, 4),
        "avg_corrupted_score": round(avg_corrupted, 4),
        "discrimination_gap": round(discrimination_gap, 4),
        "pass_rate": round(pass_rate, 4),
    }

    elapsed = time.time() - start
    report["elapsed_seconds"] = round(elapsed, 2)

    # Save report
    report_path = output_dir / "eval_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"Real PCB Training Complete ({elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"  Train samples:     {len(train_ds)} boards ({len(train_texts)} chains)")
    print(f"  Difficulty:        {train_ds.difficulty_counts}")
    print(f"  Tokenizer vocab:   {tokenizer.vocab_size_actual}")
    print(f"  Final loss:        {report['steps']['reward_model']['final_loss']:.6f}")
    print(f"  Avg correct score: {avg_correct:.4f}")
    print(f"  Avg corrupted:     {avg_corrupted:.4f}")
    print(f"  Discrimination:    {discrimination_gap:.4f}")
    print(f"  Pass rate:         {pass_rate:.1%}")
    print(f"  Report:            {report_path}")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
