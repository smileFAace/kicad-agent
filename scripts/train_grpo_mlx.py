#!/usr/bin/env python3
"""GRPO-style RL fine-tuning using ReST (Rejection Sampling Fine-Tuning).

Uses the SFT model + reward model to iteratively improve chain quality:
  1. Load SFT-fine-tuned model (base + LoRA adapter)
  2. Load reward model for quality scoring
  3. Generate N completions per prompt from policy model
  4. Score completions with reward model
  5. Filter to high-reward samples (above group median)
  6. Fine-tune on filtered samples (SFT on reward-filtered data)
  7. Repeat for K iterations

This implements the GRPO goal (reward model as critic improves policy) with
a stable training loop compatible with mlx-lm on Apple Silicon.

Output: training_output/grpo/ (improved LoRA adapter)

Usage:
    python3 scripts/train_grpo_mlx.py

    # More iterations, larger groups
    python3 scripts/train_grpo_mlx.py --n-iter 3 --group-size 8

    # Quick test
    python3 scripts/train_grpo_mlx.py --n-iter 1 --group-size 4 --sft-iters 200
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import mlx.core as mx
from mlx.optimizers import AdamW
from mlx_lm import load, generate
from mlx_lm.tuner import datasets, train as tuner_train
from mlx_lm.tuner.trainer import TrainingArgs
from mlx_lm.tuner.utils import linear_to_lora_layers

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from kicad_agent.training.reward_model import RewardModel, predict_reward


SYSTEM_PROMPT = (
    "You are a PCB design expert specializing in spatial reasoning. "
    "Analyze boards using coordinate-grounded reasoning with <point x,y> tags. "
    "Provide structured analysis: observation, component analysis, connectivity, "
    "spatial analysis, and routing assessment."
)


def load_prompts(data_path: Path, max_prompts: int = 0) -> list[dict]:
    """Load ChatML prompts from JSONL, return messages (system + user only)."""
    prompts = []
    with open(data_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            text = record["text"]
            messages = _parse_chatml(text)
            if messages and len(messages) >= 2:
                # Extract just system + user messages as the prompt
                prompt_msgs = [m for m in messages if m["role"] in ("system", "user")]
                if len(prompt_msgs) >= 2:
                    prompts.append({
                        "messages": prompt_msgs,
                        "original_response": messages[-1]["content"] if messages[-1]["role"] == "assistant" else "",
                    })
    if max_prompts > 0:
        prompts = prompts[:max_prompts]
    return prompts


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


def format_prompt_for_generation(messages: list[dict]) -> str:
    """Format messages as ChatML prompt for generation."""
    parts = []
    for msg in messages:
        parts.append(f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>")
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


def generate_completions(
    model, tokenizer, prompt_str: str, n: int, max_tokens: int = 512,
    temperature: float = 0.7,
) -> list[str]:
    """Generate N completions for a prompt."""
    # Create temperature sampler for mlx-lm
    def temp_sampler(logits):
        return mx.random.categorical(logits * (1.0 / max(temperature, 1e-8)))

    completions = []
    for _ in range(n):
        response = generate(
            model, tokenizer,
            prompt=prompt_str,
            max_tokens=max_tokens,
            sampler=temp_sampler,
            verbose=False,
        )
        # Extract just the assistant response
        if "<|im_start|>assistant" in prompt_str:
            # generate() returns the full text including prompt
            assistant_part = response
            if response.startswith(prompt_str.rstrip("<|im_start|>assistant\n")):
                assistant_part = response[len(prompt_str.rstrip("<|im_start|>assistant\n")):]
            completions.append(assistant_part.strip())
        else:
            completions.append(response.strip())
    return completions


def score_completion(reward_model, text: str) -> float:
    """Score a completion with the reward model."""
    pred = predict_reward(reward_model, text)
    return (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0


def main() -> int:
    parser = argparse.ArgumentParser(description="GRPO RL fine-tuning (ReST)")
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--adapter", type=Path, default=Path("training_output/sft"),
                        help="Directory containing adapters.safetensors + adapter_config.json")
    parser.add_argument("--reward-model-dir", default="training_output/unified")
    parser.add_argument("--data-dir", type=Path, default=Path("training_output/sft_data"))
    parser.add_argument("--output-dir", type=Path, default=Path("training_output/grpo"))
    parser.add_argument("--n-iter", type=int, default=2, help="Number of ReST iterations")
    parser.add_argument("--group-size", type=int, default=4, help="Completions per prompt")
    parser.add_argument("--max-prompts", type=int, default=200, help="Prompts per iteration")
    parser.add_argument("--filter-top-k", type=float, default=0.5,
                        help="Keep top fraction of completions (0.5 = top half)")
    parser.add_argument("--sft-iters", type=int, default=500, help="SFT iters per ReST round")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--lr", type=float, default=5e-6)
    parser.add_argument("--max-gen-tokens", type=int, default=512)
    parser.add_argument("--gen-temperature", type=float, default=0.8)
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--lora-scale", type=float, default=32.0)
    parser.add_argument("--lora-layers", type=int, default=16)
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    start_time = time.time()
    rng = random.Random(args.seed)

    print(f"\nGRPO RL Fine-Tuning (ReST)")
    print(f"  Model:          {args.model}")
    print(f"  Adapter:        {args.adapter}")
    print(f"  Reward model:   {args.reward_model_dir}")
    print(f"  Iterations:     {args.n_iter}")
    print(f"  Group size:     {args.group_size}")
    print(f"  Max prompts:    {args.max_prompts}")
    print(f"  Filter top:     {args.filter_top_k:.0%}")
    print(f"  SFT iters/round: {args.sft_iters}")
    print(f"  Device:         {mx.default_device()}")

    # ------------------------------------------------------------------
    # Load reward model
    # ------------------------------------------------------------------
    print(f"\nLoading reward model from {args.reward_model_dir}...")
    reward_model = RewardModel.load_trained(args.reward_model_dir)
    print(f"  Loaded (device: {reward_model._device})")

    # ------------------------------------------------------------------
    # Load prompts
    # ------------------------------------------------------------------
    print("\nLoading training prompts...")
    train_prompts = load_prompts(args.data_dir / "train.jsonl", max_prompts=0)
    print(f"  Total prompts: {len(train_prompts)}")

    # ------------------------------------------------------------------
    # ReST iterations
    # ------------------------------------------------------------------
    current_adapter = args.adapter
    all_metrics = []

    for rest_iter in range(args.n_iter):
        iter_start = time.time()
        print(f"\n{'='*60}")
        print(f"ReST Iteration {rest_iter + 1}/{args.n_iter}")
        print(f"{'='*60}")

        # Load model with current adapter (LoRA already applied by load)
        print(f"\n  Loading model + adapter ({current_adapter})...")
        model, tokenizer = load(args.model, adapter_path=str(current_adapter))

        # LoRA layers are already applied by load() with adapter_path.
        # Just set num_layers for config saving.
        num_layers = args.lora_layers

        # Sample prompts for this iteration
        iter_prompts = rng.sample(train_prompts, min(args.max_prompts, len(train_prompts)))

        # ----------------------------------------------------------------
        # Generate + Score
        # ----------------------------------------------------------------
        print(f"\n  Generating {args.group_size} completions per prompt ({len(iter_prompts)} prompts)...")
        filtered_samples = []
        total_generated = 0
        total_kept = 0
        all_scores = []

        for i, prompt_data in enumerate(iter_prompts):
            prompt_msgs = prompt_data["messages"]
            prompt_str = format_prompt_for_generation(prompt_msgs)

            # Generate completions
            completions = generate_completions(
                model, tokenizer, prompt_str,
                n=args.group_size,
                max_tokens=args.max_gen_tokens,
                temperature=args.gen_temperature,
            )

            # Score completions
            scored = []
            for comp in completions:
                if len(comp) < 20:
                    continue
                score = score_completion(reward_model, comp)
                scored.append((comp, score))
                all_scores.append(score)

            if not scored:
                continue

            total_generated += len(scored)

            # Filter: keep top-K by reward
            scored.sort(key=lambda x: x[1], reverse=True)
            keep_n = max(1, int(len(scored) * args.filter_top_k))
            for comp, score in scored[:keep_n]:
                # Build full ChatML sample
                messages = list(prompt_msgs) + [{"role": "assistant", "content": comp}]
                filtered_samples.append({"messages": messages})
                total_kept += 1

            if (i + 1) % 50 == 0:
                print(f"    {i+1}/{len(iter_prompts)} prompts processed")

        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0
        print(f"\n  Generation results:")
        print(f"    Generated: {total_generated}")
        print(f"    Kept:      {total_kept} ({100*total_kept/max(total_generated,1):.1f}%)")
        print(f"    Avg score: {avg_score:.4f}")
        print(f"    Score range: {min(all_scores):.4f} - {max(all_scores):.4f}" if all_scores else "")

        # ----------------------------------------------------------------
        # Re-train on filtered data
        # ----------------------------------------------------------------
        if not filtered_samples:
            print("  WARNING: No filtered samples, skipping SFT round")
            continue

        print(f"\n  Re-training SFT on {len(filtered_samples)} filtered samples...")

        # Split filtered data for train/val
        rng.shuffle(filtered_samples)
        val_count = min(50, len(filtered_samples) // 10)
        train_samples = filtered_samples[val_count:]
        val_samples = filtered_samples[:val_count]

        train_dataset = datasets.CacheDataset(
            datasets.ChatDataset(train_samples, tokenizer, mask_prompt=True)
        )
        val_dataset = datasets.CacheDataset(
            datasets.ChatDataset(val_samples, tokenizer, mask_prompt=True)
        )

        iter_output = args.output_dir / f"iter_{rest_iter + 1}"
        iter_output.mkdir(parents=True, exist_ok=True)

        training_args = TrainingArgs(
            batch_size=args.batch_size,
            iters=args.sft_iters,
            val_batches=min(25, max(1, len(val_samples) // args.batch_size)),
            steps_per_report=50,
            steps_per_eval=args.sft_iters + 1 if not val_samples else 200,
            steps_per_save=args.sft_iters + 1,
            max_seq_length=args.max_seq_length,
            adapter_file=str(iter_output / "adapters.safetensors"),
        )

        optimizer = AdamW(learning_rate=args.lr, weight_decay=0.01)

        model.train()
        tuner_train(
            model=model,
            optimizer=optimizer,
            train_dataset=train_dataset,
            val_dataset=val_dataset,
            args=training_args,
        )

        # Save adapter
        adapter_file = iter_output / "adapters.safetensors"
        model.save_weights(str(adapter_file))

        # Save adapter_config.json so load() can find it
        lora_meta = {
            "num_layers": num_layers,
            "lora_parameters": {
                "rank": args.lora_rank,
                "scale": args.lora_scale,
                "dropout": 0.0,
                "keys": ["self_attn.q_proj", "self_attn.k_proj",
                          "self_attn.v_proj", "self_attn.o_proj"],
            },
        }
        with open(iter_output / "adapter_config.json", "w") as f:
            json.dump(lora_meta, f, indent=2)

        # Save iter config
        iter_config = {
            "rest_iteration": rest_iter + 1,
            "prompts_used": len(iter_prompts),
            "completions_generated": total_generated,
            "samples_kept": total_kept,
            "avg_reward_score": avg_score,
            "sft_iters": args.sft_iters,
            "base_model": args.model,
            "lora_rank": args.lora_rank,
            "lora_scale": args.lora_scale,
            "adapter_path": str(adapter_file),
        }
        with open(iter_output / "iter_config.json", "w") as f:
            json.dump(iter_config, f, indent=2)

        current_adapter = iter_output  # load() expects directory
        elapsed = time.time() - iter_start

        all_metrics.append({
            "iteration": rest_iter + 1,
            "generated": total_generated,
            "kept": total_kept,
            "avg_score": avg_score,
            "elapsed_seconds": round(elapsed, 1),
        })

        print(f"\n  Iteration {rest_iter + 1} complete in {elapsed:.1f}s")
        print(f"    Adapter: {current_adapter}")

    # ------------------------------------------------------------------
    # Final adapter symlink + generate sample
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print("Loading final adapter for sample generation...")

    model, tokenizer = load(args.model, adapter_path=str(current_adapter))
    model.eval()

    response = generate(
        model, tokenizer,
        prompt=(
            "<|im_start|>system\nYou are a PCB design expert.<|im_end|>\n"
            "<|im_start|>user\nAnalyze this PCB: 50 components, 30 nets, "
            "4 layers, 100x80mm board.<|im_end|>\n<|im_start|>assistant\n"
        ),
        max_tokens=300,
        verbose=False,
    )
    print(f"  Sample: {response[:400]}...")

    # Save final config
    final_config = {
        "base_model": args.model,
        "n_rest_iterations": args.n_iter,
        "group_size": args.group_size,
        "filter_top_k": args.filter_top_k,
        "sft_iters_per_round": args.sft_iters,
        "learning_rate": args.lr,
        "final_adapter": str(current_adapter),
        "iteration_metrics": all_metrics,
        "total_elapsed_seconds": round(time.time() - start_time, 1),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with open(args.output_dir / "grpo_report.json", "w") as f:
        json.dump(final_config, f, indent=2)

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"GRPO fine-tuning complete in {elapsed:.1f}s")
    print(f"  Iterations: {args.n_iter}")
    print(f"  Final adapter: {current_adapter}")
    print(f"  Report: {args.output_dir / 'grpo_report.json'}")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
