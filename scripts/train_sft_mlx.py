#!/usr/bin/env python3
"""SFT fine-tuning of Qwen2.5 on PCB reasoning chains using mlx-lm.

Uses MLX for native Apple Silicon GPU acceleration with LoRA adapters.

Usage:
    python3 scripts/train_sft_mlx.py

    # Larger model
    python3 scripts/train_sft_mlx.py --model Qwen/Qwen2.5-1.5B-Instruct

    # Quick test
    python3 scripts/train_sft_mlx.py --model Qwen/Qwen2.5-0.5B-Instruct --iters 200
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
from mlx.optimizers import AdamW
from mlx_lm import load, generate
from mlx_lm.tuner import datasets, train as tuner_train
from mlx_lm.tuner.trainer import TrainingArgs
from mlx_lm.tuner.utils import linear_to_lora_layers


def load_chatml_dataset(data_path: Path) -> list[dict]:
    """Load ChatML JSONL into messages format for mlx-lm ChatDataset."""
    samples = []
    with open(data_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            text = record["text"]
            messages = _parse_chatml(text)
            if messages:
                samples.append({"messages": messages})
    return samples


def _parse_chatml(text: str) -> list[dict] | None:
    """Parse <|im_start|>role\\ncontent<|im_end|> into message dicts."""
    messages = []
    parts = text.split("<|im_start|>")

    for part in parts:
        if not part.strip():
            continue
        role_end = part.find("\n")
        if role_end < 0:
            continue
        role = part[:role_end].strip()
        content = part[role_end + 1:]
        if content.endswith("<|im_end|>"):
            content = content[:-len("<|im_end|>")]
        content = content.strip()
        if role in ("system", "user", "assistant") and content:
            messages.append({"role": role, "content": content})

    return messages if len(messages) >= 2 else None


def main() -> int:
    parser = argparse.ArgumentParser(description="SFT training with mlx-lm")
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--data-dir", type=Path, default=Path("training_output/sft_data"))
    parser.add_argument("--output-dir", type=Path, default=Path("training_output/sft"))
    parser.add_argument("--iters", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--lora-scale", type=float, default=32.0)
    parser.add_argument("--lora-dropout", type=float, default=0.0)
    parser.add_argument("--lora-layers", type=int, default=16)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--steps-per-report", type=int, default=10)
    parser.add_argument("--steps-per-eval", type=int, default=200)
    parser.add_argument("--steps-per-save", type=int, default=500)
    parser.add_argument("--val-batches", type=int, default=25)
    args = parser.parse_args()

    start_time = time.time()

    print(f"\nSFT Training (mlx-lm)")
    print(f"  Model:    {args.model}")
    print(f"  LoRA:     rank={args.lora_rank}, scale={args.lora_scale}, layers={args.lora_layers}")
    print(f"  Iters:    {args.iters}")
    print(f"  Device:   {mx.default_device()}")

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    print("\nLoading data...")
    train_messages = load_chatml_dataset(args.data_dir / "train.jsonl")
    val_messages = load_chatml_dataset(args.data_dir / "val.jsonl")
    print(f"  Train: {len(train_messages)}, Val: {len(val_messages)}")

    if not train_messages:
        print("ERROR: No training samples")
        return 1

    # ------------------------------------------------------------------
    # Load model
    # ------------------------------------------------------------------
    print(f"\nLoading {args.model}...")
    model, tokenizer = load(args.model)
    print(f"  Vocab: {tokenizer.vocab_size}")

    # ------------------------------------------------------------------
    # Apply LoRA
    # ------------------------------------------------------------------
    lora_config = {
        "rank": args.lora_rank,
        "scale": args.lora_scale,
        "dropout": args.lora_dropout,
        "keys": ["self_attn.q_proj", "self_attn.k_proj",
                  "self_attn.v_proj", "self_attn.o_proj"],
    }

    num_layers = min(args.lora_layers, len(model.layers))
    linear_to_lora_layers(model, num_layers, lora_config)

    # Count params (mlx Module.parameters() returns nested pytree)
    def _count_params(params) -> tuple[int, int]:
        total, trainable = 0, 0
        if isinstance(params, mx.array):
            total = params.size
            trainable = params.size if not getattr(params, 'freeze', False) else 0
        elif isinstance(params, (list, tuple)):
            for p in params:
                t, tr = _count_params(p)
                total += t
                trainable += tr
        elif isinstance(params, dict):
            for p in params.values():
                t, tr = _count_params(p)
                total += t
                trainable += tr
        return total, trainable

    total, trainable = _count_params(model.parameters())
    print(f"  Total params:     {total:,}")
    print(f"  Trainable:        {trainable:,} ({100*trainable/total:.2f}%)" if total else "  Trainable: N/A")

    # ------------------------------------------------------------------
    # Create datasets
    # ------------------------------------------------------------------
    train_dataset = datasets.CacheDataset(
        datasets.ChatDataset(train_messages, tokenizer, mask_prompt=True)
    )
    val_dataset = datasets.CacheDataset(
        datasets.ChatDataset(val_messages, tokenizer, mask_prompt=True)
    ) if val_messages else None

    # ------------------------------------------------------------------
    # Train
    # ------------------------------------------------------------------
    print("\nStarting training...")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArgs(
        batch_size=args.batch_size,
        iters=args.iters,
        val_batches=args.val_batches,
        steps_per_report=args.steps_per_report,
        steps_per_eval=args.steps_per_eval if val_dataset else args.iters + 1,
        steps_per_save=args.steps_per_save,
        max_seq_length=args.max_seq_length,
        adapter_file=str(args.output_dir / "adapters.safetensors"),
    )

    optimizer = AdamW(learning_rate=args.lr, weight_decay=0.01)

    tuner_train(
        model=model,
        optimizer=optimizer,
        train_dataset=train_dataset,
        val_dataset=val_dataset,
        args=training_args,
    )

    # ------------------------------------------------------------------
    # Save adapter + config
    # ------------------------------------------------------------------
    adapter_path = args.output_dir / "adapters.safetensors"
    model.save_weights(str(adapter_path))

    config = {
        "base_model": args.model,
        "lora_rank": args.lora_rank,
        "lora_scale": args.lora_scale,
        "lora_layers": num_layers,
        "iters": args.iters,
        "batch_size": args.batch_size,
        "learning_rate": args.lr,
        "train_samples": len(train_messages),
        "val_samples": len(val_messages),
        "adapter_path": str(adapter_path),
    }
    with open(args.output_dir / "adapter_config.json", "w") as f:
        json.dump(config, f, indent=2)

    # ------------------------------------------------------------------
    # Generate sample
    # ------------------------------------------------------------------
    print("\nGenerating sample...")
    model.eval()
    response = generate(
        model, tokenizer,
        prompt=(
            "<|im_start|>system\nYou are a PCB design expert.<|im_end|>\n"
            "<|im_start|>user\nAnalyze this PCB: 50 components, 30 nets, "
            "4 layers, 100x80mm board.<|im_end|>\n<|im_start|>assistant\n"
        ),
        max_tokens=200,
        verbose=False,
    )
    print(f"  {response[:300]}...")

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"SFT complete in {elapsed:.1f}s")
    print(f"  Adapter: {adapter_path}")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
