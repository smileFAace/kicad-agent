#!/usr/bin/env python3
"""Evaluate fine-tuned model quality: base vs SFT vs GRPO.

Generates analysis for a set of test prompts, scores with reward model,
and produces a comparison report.

Usage:
    python3 scripts/evaluate_models.py

    # Custom adapters
    python3 scripts/evaluate_models.py --sft-dir training_output/sft --grpo-dir training_output/grpo/iter_2
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent / "src")

import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from kicad_agent.llm.local_client import LocalLLMClient
from kicad_agent.training.reward_model import RewardModel, predict_reward

TEST_PROMPTS = [
    {
        "name": "small_board",
        "board_name": "sensor-board",
        "n_components": 15,
        "n_nets": 12,
        "n_layers": 2,
        "width_mm": 50.0,
        "height_mm": 30.0,
        "source": "test",
    },
    {
        "name": "medium_board",
        "board_name": "Arduino-Mega",
        "n_components": 85,
        "n_nets": 62,
        "n_layers": 4,
        "width_mm": 101.52,
        "height_mm": 53.34,
        "source": "github.com/arduino/ArduinoCore-avr",
    },
    {
        "name": "complex_board",
        "board_name": "raspberry-pi-4",
        "n_components": 200,
        "n_nets": 150,
        "n_layers": 6,
        "width_mm": 85.0,
        "height_mm": 56.0,
        "source": "github.com/raspberrypi/hardware",
    },
    {
        "name": "high_density",
        "board_name": "phone-mainboard",
        "n_components": 500,
        "n_nets": 350,
        "n_layers": 8,
        "width_mm": 70.0,
        "height_mm": 140.0,
        "source": "test",
    },
]


def evaluate_adapter(
    model_name: str,
    adapter_dir: Path | None,
    reward_model: RewardModel,
    max_tokens: int = 512,
) -> list[dict]:
    """Evaluate a model/adapter on test prompts."""
    client = LocalLLMClient(
        model=model_name,
        adapter_dir=adapter_dir,
        max_tokens=max_tokens,
    )

    results = []
    for prompt in TEST_PROMPTS:
        start = time.time()
        # Filter out non-analyze_board kwargs
        board_kwargs = {k: v for k, v in prompt.items() if k != "name"}
        analysis = client.analyze_board(**board_kwargs)
        elapsed = time.time() - start

        # Score with reward model
        pred = predict_reward(reward_model, analysis)
        score = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0

        results.append({
            "prompt_name": prompt["name"],
            "analysis_length": len(analysis),
            "reward_score": score,
            "format_score": pred.format_score,
            "quality_score": pred.quality_score,
            "accuracy_score": pred.accuracy_score,
            "elapsed_seconds": round(elapsed, 2),
            "has_coordinates": "<point" in analysis,
            "has_structured_sections": any(
                s in analysis.lower() for s in ["observation", "component analysis", "connectivity", "routing"]
            ),
            "sample": analysis[:200],
        })

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate fine-tuned model quality")
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--sft-dir", type=Path, default=Path("training_output/sft"))
    parser.add_argument("--grpo-dir", type=Path, default=Path("training_output/grpo/iter_2"))
    parser.add_argument("--reward-model-dir", default="training_output/unified")
    parser.add_argument("--output-dir", type=Path, default=Path("training_output/eval"))
    parser.add_argument("--max-tokens", type=int, default=512)
    args = parser.parse_args()

    start_time = time.time()

    print("\nModel Evaluation")
    print(f"  Base model: {args.model}")
    print(f"  SFT adapter: {args.sft_dir}")
    print(f"  GRPO adapter: {args.grpo_dir}")
    print(f"  Test prompts: {len(TEST_PROMPTS)}")

    # Load reward model
    print(f"\nLoading reward model from {args.reward_model_dir}...")
    reward_model = RewardModel.load_trained(args.reward_model_dir)

    all_results = {}

    # 1. Base model (no adapter)
    print("\n--- Base Model (no adapter) ---")
    try:
        base_results = evaluate_adapter(args.model, None, reward_model, args.max_tokens)
        all_results["base"] = base_results
        for r in base_results:
            print(f"  {r['prompt_name']}: score={r['reward_score']:.4f}, coords={r['has_coordinates']}, len={r['analysis_length']}")
    except Exception as e:
        print(f"  Error: {e}")
        all_results["base"] = []

    # 2. SFT model
    if args.sft_dir.exists():
        print(f"\n--- SFT Model ({args.sft_dir}) ---")
        try:
            sft_results = evaluate_adapter(args.model, args.sft_dir, reward_model, args.max_tokens)
            all_results["sft"] = sft_results
            for r in sft_results:
                print(f"  {r['prompt_name']}: score={r['reward_score']:.4f}, coords={r['has_coordinates']}, len={r['analysis_length']}")
        except Exception as e:
            print(f"  Error: {e}")
            all_results["sft"] = []
    else:
        print(f"\n--- SFT Model: SKIPPED ({args.sft_dir} not found) ---")

    # 3. GRPO model
    if args.grpo_dir.exists():
        print(f"\n--- GRPO Model ({args.grpo_dir}) ---")
        try:
            grpo_results = evaluate_adapter(args.model, args.grpo_dir, reward_model, args.max_tokens)
            all_results["grpo"] = grpo_results
            for r in grpo_results:
                print(f"  {r['prompt_name']}: score={r['reward_score']:.4f}, coords={r['has_coordinates']}, len={r['analysis_length']}")
        except Exception as e:
            print(f"  Error: {e}")
        all_results["grpo"] = all_results.get("grpo", [])
    else:
        print(f"\n--- GRPO Model: SKIPPED ({args.grpo_dir} not found) ---")

    # Summary
    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    print(f"{'Model':<12} {'Avg Score':<12} {'Avg Length':<12} {'Has Coords':<12}")
    print("-" * 48)

    for name, results in all_results.items():
        if not results:
            continue
        avg_score = sum(r["reward_score"] for r in results) / len(results)
        avg_len = sum(r["analysis_length"] for r in results) / len(results)
        coords_pct = sum(1 for r in results if r["has_coordinates"]) / len(results) * 100
        print(f"{name:<12} {avg_score:<12.4f} {avg_len:<12.0f} {coords_pct:<12.0f}%")

    # Save report
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "base_model": args.model,
        "test_prompts": len(TEST_PROMPTS),
        "results": all_results,
        "elapsed_seconds": round(time.time() - start_time, 1),
    }
    report_path = args.output_dir / "eval_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    elapsed = time.time() - start_time
    print(f"\nEvaluation complete in {elapsed:.1f}s")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
