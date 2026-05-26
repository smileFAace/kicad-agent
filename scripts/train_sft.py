#!/usr/bin/env python3
"""Supervised Fine-Tuning (SFT) of Qwen2.5-1.5B-Instruct on PCB reasoning chains.

Uses LoRA (rank=16, alpha=32) for efficient fine-tuning on consumer hardware.
Training runs on MPS (Apple Silicon) or CUDA.

Data: training_output/sft_data/train.jsonl (ChatML format)
Output: training_output/sft/ (LoRA adapter + training report)

Usage:
    python3 scripts/train_sft.py

    # Custom params
    python3 scripts/train_sft.py --n-epochs 3 --batch-size 4 --lr 2e-5

    # Force CPU (slow, for testing)
    python3 scripts/train_sft.py --device cpu

    # Resume from checkpoint
    python3 scripts/train_sft.py --resume-from training_output/sft/checkpoint-1000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq,
)
from peft import LoraConfig, get_peft_model, TaskType


def load_dataset(data_path: Path, tokenizer, max_length: int = 2048):
    """Load ChatML JSONL data and tokenize for training."""
    samples = []
    with open(data_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            samples.append(record["text"])

    print(f"  Loaded {len(samples)} samples from {data_path.name}")

    def tokenize_fn(texts):
        # Tokenize with ChatML formatting already in the text
        return tokenizer(
            texts,
            truncation=True,
            max_length=max_length,
            padding=False,
            return_attention_mask=True,
        )

    # Tokenize all samples
    all_input_ids = []
    all_attention_mask = []
    all_labels = []

    for text in samples:
        enc = tokenizer(
            text,
            truncation=True,
            max_length=max_length,
            padding=False,
        )
        input_ids = enc["input_ids"]
        attention_mask = enc["attention_mask"]

        # Labels = input_ids (causal LM), but mask the prompt portion
        # Find assistant response start for label masking
        assistant_token = "<|im_start|>assistant\n"
        assistant_ids = tokenizer.encode(assistant_token, add_special_tokens=False)

        # Find where assistant response starts
        label_ids = [-100] * len(input_ids)  # default: ignore all
        assistant_start = _find_sublist(input_ids, assistant_ids)
        if assistant_start is not None:
            # Include everything from assistant start onward
            for i in range(assistant_start, len(input_ids)):
                label_ids[i] = input_ids[i]
        else:
            # Fallback: train on full text
            label_ids = list(input_ids)

        all_input_ids.append(input_ids)
        all_attention_mask.append(attention_mask)
        all_labels.append(label_ids)

    return {
        "input_ids": all_input_ids,
        "attention_mask": all_attention_mask,
        "labels": all_labels,
    }


def _find_sublist(lst: list, sub: list) -> int | None:
    """Find first occurrence of sub in lst."""
    for i in range(len(lst) - len(sub) + 1):
        if lst[i:i + len(sub)] == sub:
            return i
    return None


class JsonDataset(torch.utils.data.Dataset):
    """Simple torch dataset from tokenized data."""

    def __init__(self, data: dict):
        self.data = data

    def __len__(self):
        return len(self.data["input_ids"])

    def __getitem__(self, idx):
        return {
            "input_ids": torch.tensor(self.data["input_ids"][idx], dtype=torch.long),
            "attention_mask": torch.tensor(self.data["attention_mask"][idx], dtype=torch.long),
            "labels": torch.tensor(self.data["labels"][idx], dtype=torch.long),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="SFT training on PCB reasoning chains")
    parser.add_argument("--model-name", default="Qwen/Qwen2.5-1.5B-Instruct")
    parser.add_argument("--data-dir", type=Path, default=Path("training_output/sft_data"))
    parser.add_argument("--output-dir", type=Path, default=Path("training_output/sft"))
    parser.add_argument("--n-epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--resume-from", type=Path, default=None)
    args = parser.parse_args()

    start_time = time.time()

    # Auto-detect device
    device = args.device
    if device == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

    print(f"\nSFT Training")
    print(f"  Model:      {args.model_name}")
    print(f"  Device:     {device}")
    print(f"  LoRA:       rank={args.lora_rank}, alpha={args.lora_alpha}")
    print(f"  Epochs:     {args.n_epochs}")
    print(f"  Batch size: {args.batch_size}")
    print(f"  LR:         {args.lr}")
    print(f"  Max length: {args.max_length}")

    # ------------------------------------------------------------------
    # Load tokenizer
    # ------------------------------------------------------------------
    print("\nLoading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_name,
        trust_remote_code=True,
        padding_side="right",
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    print(f"  Vocab size: {tokenizer.vocab_size}")

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    print("\nLoading data...")
    train_data = load_dataset(args.data_dir / "train.jsonl", tokenizer, args.max_length)
    val_data = load_dataset(args.data_dir / "val.jsonl", tokenizer, args.max_length)

    train_dataset = JsonDataset(train_data)
    val_dataset = JsonDataset(val_data)
    print(f"  Train: {len(train_dataset)}, Val: {len(val_dataset)}")

    # ------------------------------------------------------------------
    # Load model with LoRA
    # ------------------------------------------------------------------
    print("\nLoading model...")
    model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        trust_remote_code=True,
        torch_dtype=torch.float16 if device != "cpu" else torch.float32,
        device_map=device if device in ("cuda", "mps") else None,
    )

    # LoRA config
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        bias="none",
    )

    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    print("\nStarting training...")

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        num_train_epochs=args.n_epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.lr,
        weight_decay=0.01,
        warmup_ratio=0.05,
        logging_steps=50,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        fp16=False,
        bf16=False,
        gradient_accumulation_steps=4,
        max_grad_norm=1.0,
        report_to="none",
        remove_unused_columns=False,
        dataloader_pin_memory=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        data_collator=DataCollatorForSeq2Seq(
            tokenizer=tokenizer,
            padding=True,
            max_length=args.max_length,
        ),
    )

    if args.resume_from:
        trainer.train(resume_from_checkpoint=str(args.resume_from))
    else:
        trainer.train()

    # ------------------------------------------------------------------
    # Save adapter
    # ------------------------------------------------------------------
    print("\nSaving LoRA adapter...")
    adapter_path = args.output_dir / "adapter"
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)

    # ------------------------------------------------------------------
    # Quick eval: generate sample
    # ------------------------------------------------------------------
    print("\nGenerating sample...")
    model.eval()
    test_prompt = (
        "<|im_start|>system\n"
        "You are a PCB design expert specializing in spatial reasoning.<|im_end|>\n"
        "<|im_start|>user\n"
        "Analyze this PCB board:\n"
        "Board: test-board\n"
        "Components: 50, Nets: 30, Layers: 4\n"
        "Board size: 100.0 x 80.0 mm\n"
        "Source: test\n\n"
        "Provide a complete spatial reasoning analysis.<|im_end|>\n"
        "<|im_start|>assistant\n"
    )

    inputs = tokenizer(test_prompt, return_tensors="pt")
    input_ids = inputs["input_ids"]
    if device in ("cuda", "mps"):
        input_ids = input_ids.to(device)

    with torch.no_grad():
        output = model.generate(
            input_ids,
            max_new_tokens=256,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
        )

    generated = tokenizer.decode(output[0][input_ids.shape[1]:], skip_special_tokens=True)
    print(f"  Generated: {generated[:300]}...")

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    elapsed = time.time() - start_time

    # Collect training history
    log_history = trainer.state.log_history
    train_losses = [x["loss"] for x in log_history if "loss" in x]
    eval_losses = [x["eval_loss"] for x in log_history if "eval_loss" in x]

    report = {
        "model_name": args.model_name,
        "lora_rank": args.lora_rank,
        "lora_alpha": args.lora_alpha,
        "n_epochs": args.n_epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.lr,
        "max_length": args.max_length,
        "device": device,
        "train_samples": len(train_dataset),
        "val_samples": len(val_dataset),
        "train_losses": train_losses,
        "eval_losses": eval_losses,
        "final_train_loss": train_losses[-1] if train_losses else None,
        "final_eval_loss": eval_losses[-1] if eval_losses else None,
        "elapsed_seconds": round(elapsed, 2),
        "adapter_path": str(adapter_path),
        "sample_generation": generated[:500],
    }

    report_path = args.output_dir / "sft_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{'='*60}")
    print(f"SFT training complete in {elapsed:.1f}s")
    print(f"  Train samples:     {len(train_dataset)}")
    print(f"  Val samples:       {len(val_dataset)}")
    if train_losses:
        print(f"  Train loss:        {train_losses[0]:.4f} -> {train_losses[-1]:.4f}")
    if eval_losses:
        print(f"  Eval loss:         {eval_losses[-1]:.4f}")
    print(f"  Device:            {device}")
    print(f"  Adapter:           {adapter_path}")
    print(f"  Report:            {report_path}")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
