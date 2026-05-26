#!/usr/bin/env python3
"""Convert training chains to ChatML instruction format for SFT fine-tuning.

Loads all 7 data sources, converts each chain into ChatML format with
task-specific prompt templates, scores with reward model, filters bottom
quartile, writes train/val/test splits.

Output format (ChatML / Qwen2.5):
    <|im_start|>system
    You are a PCB design expert. Analyze boards using coordinate-grounded reasoning.
    <|im_end|>
    <|im_start|>user
    [task-specific prompt with board context]
    <|im_end|>
    <|im_start|>assistant
    [reasoning chain]
    <|im_end|>

Usage:
    python3 scripts/prepare_sft_data.py

    # Custom model dir
    python3 scripts/prepare_sft_data.py --model-dir training_output/unified

    # Custom output
    python3 scripts/prepare_sft_data.py --output-dir training_output/sft_data

    # Skip quality filter
    python3 scripts/prepare_sft_data.py --no-filter
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.training.reward_model import RewardModel, predict_reward

SYSTEM_PROMPT = (
    "You are a PCB design expert specializing in spatial reasoning. "
    "Analyze boards using coordinate-grounded reasoning with <point x,y> tags. "
    "Provide structured analysis: observation, component analysis, connectivity, "
    "spatial analysis, and routing assessment."
)

# ---------------------------------------------------------------------------
# Task-specific prompt templates
# ---------------------------------------------------------------------------

PROMPT_TEMPLATES = {
    "board_analysis": (
        "Analyze this PCB board:\n"
        "Board: {board_name}\n"
        "Components: {n_components}, Nets: {n_nets}, Layers: {n_layers}\n"
        "Board size: {width:.1f} x {height:.1f} mm\n"
        "Source: {source}\n\n"
        "Provide a complete spatial reasoning analysis."
    ),
    "schematic_analysis": (
        "Analyze this schematic:\n"
        "Schematic: {board_name}\n"
        "Components: {n_components}, Nets: {n_nets}\n"
        "Source: {source}\n\n"
        "Describe the circuit topology and connectivity."
    ),
    "routing_quality": (
        "Assess the routing quality of this PCB:\n"
        "Board: {board_name}\n"
        "Components: {n_components}, Nets: {n_nets}, Traces: {n_traces}\n"
        "RES Score: {res_score:.3f} ({quality_label})\n"
        "Density: {density:.3f} comp/mm2, Via density: {via_density:.3f}/mm2\n"
        "Manhattan efficiency: {manhattan_eff:.3f}\n\n"
        "Evaluate the routing quality and identify strengths and weaknesses."
    ),
    "component_knowledge": (
        "Describe this electronic component:\n"
        "Name: {comp_name}\n"
        "Manufacturer: {brand}\n"
        "Package: {package}\n"
        "Category: {category}\n"
        "Pins: {pin_count}\n\n"
        "Provide a detailed technical description."
    ),
    "domain_knowledge": (
        "Explain this electronics design concept:\n"
        "Source: {source}, Chapter: {chapter}\n"
        "Topic covers: {topic_hint}\n\n"
        "Provide a clear, technically accurate explanation."
    ),
}


def _extract_chain_fields(raw: dict) -> dict:
    """Extract template variables from a raw JSONL sample."""
    fields = {
        "board_name": raw.get("pcb_name", raw.get("repo_name", "unknown")),
        "n_components": raw.get("component_count", raw.get("n_footprints", 0)),
        "n_nets": raw.get("net_count", raw.get("n_nets", 0)),
        "n_layers": raw.get("layer_count", 0),
        "width": raw.get("board_width_mm", 0.0),
        "height": raw.get("board_height_mm", 0.0),
        "source": raw.get("source", raw.get("repo_url", "unknown")),
        "n_traces": raw.get("n_trace_items", 0),
        "res_score": 0.0,
        "quality_label": "unknown",
        "density": 0.0,
        "via_density": 0.0,
        "manhattan_eff": 0.0,
        "comp_name": raw.get("name", ""),
        "brand": raw.get("brand", ""),
        "package": raw.get("package", ""),
        "category": raw.get("category", ""),
        "pin_count": raw.get("pin_count", 0),
        "chapter": raw.get("chapter", ""),
        "topic_hint": "",
    }

    # Gold standard routing features
    fts = raw.get("routing_features", {})
    if fts:
        fields["res_score"] = fts.get("elegance_score", 0.0)
        fields["quality_label"] = raw.get("quality_label", "unknown")
        fields["density"] = fts.get("component_density", 0.0)
        fields["via_density"] = fts.get("via_density", 0.0)
        fields["manhattan_eff"] = fts.get("manhattan_efficiency", 0.0)

    # Topic hint from textbook content
    content = raw.get("content", "")
    if content:
        words = content[:100].split()
        fields["topic_hint"] = " ".join(words[:10]) + "..."

    return fields


def _detect_task_type(raw: dict) -> str:
    """Auto-detect task type from JSONL sample fields."""
    if "routing_features" in raw:
        return "routing_quality"
    if "lcsc" in raw:
        return "component_knowledge"
    if "content_type" in raw:
        return "domain_knowledge"
    # Board graph data (schematic or PCB)
    if "graph_json" in raw:
        source = raw.get("source_format", "")
        if "sch" in source:
            return "schematic_analysis"
        return "board_analysis"
    return "board_analysis"


def _build_chain_text(raw: dict) -> str:
    """Extract or synthesize chain text from a JSONL sample."""
    if "chain_text" in raw:
        return raw["chain_text"]

    # Board graph data
    if "graph_json" in raw:
        from kicad_agent.training.real_dataset import RealBoardSample
        from kicad_agent.training.board_chains import synthesize_board_chain

        try:
            sample = RealBoardSample(
                sample_id=raw.get("sample_id", 0),
                repo_url=raw.get("repo_url", ""),
                repo_name=raw.get("repo_name", ""),
                schematic_path=raw.get("schematic_path", ""),
                pcb_path=raw.get("pcb_path", ""),
                component_count=raw.get("component_count", 0),
                net_count=raw.get("net_count", 0),
                layer_count=raw.get("layer_count", 0),
                board_width_mm=raw.get("board_width_mm", 0.0),
                board_height_mm=raw.get("board_height_mm", 0.0),
                difficulty=raw.get("difficulty", "medium"),
                board_hash=raw.get("board_hash", ""),
                graph_json=raw.get("graph_json", "{}"),
                spatial_summary_json=raw.get("spatial_summary_json", "{}"),
                source_format=raw.get("source_format", "kicad_pcb"),
            )
            chain = synthesize_board_chain(sample)
            return chain.chain_text
        except Exception:
            pass

    # Gold standard
    if "routing_features" in raw:
        fts = raw["routing_features"]
        return (
            f"Board routing analysis: {raw.get('pcb_name', 'unknown')}\n"
            f"Source: {raw.get('source', '')} (tier {raw.get('tier', '?')})\n"
            f"Components: {raw.get('n_footprints', 0)}, Nets: {raw.get('n_nets', 0)}\n"
            f"Routing Elegance Score: {fts.get('elegance_score', 0):.3f} "
            f"({raw.get('quality_label', '')})\n"
            f"Density: {fts.get('component_density', 0):.3f} comp/mm2\n"
            f"Manhattan efficiency: {fts.get('manhattan_efficiency', 0):.3f}\n"
            f"Assessment: This board demonstrates {raw.get('quality_label', 'unknown')} "
            f"routing quality with RES={fts.get('elegance_score', 0):.3f}."
        )

    # EasyEDA component
    if "lcsc" in raw:
        parts = [f"Component: {raw.get('name', '')} (LCSC {raw.get('lcsc', '')})"]
        if raw.get("brand"):
            parts.append(f"Manufacturer: {raw['brand']}")
        if raw.get("package"):
            parts.append(f"Package: {raw['package']}")
        if raw.get("category"):
            parts.append(f"Category: {raw['category']}")
        pins = raw.get("pins", [])
        if pins:
            descs = []
            for p in pins[:8]:
                num = p.get("number", "")
                pname = p.get("name", "")
                if num and pname:
                    descs.append(f"pin {num}={pname}")
            if descs:
                parts.append("Pins: " + ", ".join(descs))
        return "\n".join(parts)

    # Textbook
    if "content_type" in raw:
        content = raw.get("content", "")
        return (
            f"Domain knowledge: {raw.get('source', '')}, {raw.get('chapter', '')}.\n"
            f"Content: {content[:2000]}\n"
            f"This describes electronics design principles."
        )

    return ""


def _load_jsonl(path: Path) -> list[dict]:
    samples = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def convert_to_chatml(
    raw: dict,
    chain_text: str,
) -> str:
    """Convert a sample + chain to ChatML format."""
    task_type = _detect_task_type(raw)
    fields = _extract_chain_fields(raw)

    try:
        prompt = PROMPT_TEMPLATES[task_type].format(**fields)
    except KeyError:
        prompt = f"Analyze this PCB:\n{json.dumps(fields, indent=2)}\n\nProvide spatial reasoning."

    return (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{prompt}<|im_end|>\n"
        f"<|im_start|>assistant\n{chain_text}<|im_end|>"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert training chains to ChatML instruction format",
    )
    parser.add_argument(
        "--data-dirs",
        nargs="*",
        default=[
            "training_data",
            "training_data_v3",
            "training_data_100k",
            "training_data_schematics",
            "training_data_textbook",
            "training_data_easyeda",
            "training_data_gold",
        ],
    )
    parser.add_argument("--model-dir", default="training_output/unified")
    parser.add_argument("--output-dir", type=Path, default=Path("training_output/sft_data"))
    parser.add_argument("--no-filter", action="store_true", help="Skip quality filtering")
    parser.add_argument("--filter-percentile", type=float, default=25.0,
                        help="Remove chains below this percentile (default: 25)")
    args = parser.parse_args()

    start = time.time()

    # Load model for filtering
    model = None
    if not args.no_filter:
        print(f"Loading reward model from {args.model_dir}...")
        model = RewardModel.load_trained(args.model_dir)
        print(f"  Loaded (device: {model._device})")

    # ------------------------------------------------------------------
    # Load all samples
    # ------------------------------------------------------------------
    all_samples: list[dict] = []

    for data_dir_str in args.data_dirs:
        data_dir = Path(data_dir_str)
        train_path = data_dir / "train.jsonl"
        if not train_path.exists():
            continue

        samples = _load_jsonl(train_path)
        if not samples:
            continue

        print(f"  {data_dir.name}: {len(samples)} samples")
        all_samples.extend(samples)

    if not all_samples:
        print("ERROR: No samples loaded")
        return 1

    print(f"\nTotal samples: {len(all_samples)}")

    # ------------------------------------------------------------------
    # Convert to ChatML
    # ------------------------------------------------------------------
    print("Converting to ChatML...")
    chatml_samples: list[tuple[str, dict, float]] = []  # (chatml, metadata, score)

    for raw in all_samples:
        chain_text = _build_chain_text(raw)
        if not chain_text or len(chain_text) < 20:
            continue

        chatml = convert_to_chatml(raw, chain_text)
        task_type = _detect_task_type(raw)

        # Score with reward model
        score = 0.5  # neutral default
        if model:
            pred = predict_reward(model, chain_text)
            score = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0

        metadata = {
            "task_type": task_type,
            "source": raw.get("source", raw.get("repo_name", "unknown")),
            "chain_length": len(chain_text),
            "reward_score": score,
        }
        chatml_samples.append((chatml, metadata, score))

    print(f"  Converted: {len(chatml_samples)}")

    # ------------------------------------------------------------------
    # Quality filter
    # ------------------------------------------------------------------
    if model and not args.no_filter:
        scores = [s[2] for s in chatml_samples]
        scores_sorted = sorted(scores)
        threshold_idx = int(len(scores_sorted) * args.filter_percentile / 100)
        threshold = scores_sorted[threshold_idx]

        filtered = [s for s in chatml_samples if s[2] >= threshold]
        removed = len(chatml_samples) - len(filtered)
        print(f"\n  Quality filter (below {args.filter_percentile}th percentile = {threshold:.4f}):")
        print(f"    Removed: {removed}")
        print(f"    Retained: {len(filtered)}")
        chatml_samples = filtered
    else:
        print("  Quality filter: skipped")

    # ------------------------------------------------------------------
    # Shuffle and split
    # ------------------------------------------------------------------
    rng = random.Random(42)
    rng.shuffle(chatml_samples)

    train_end = int(len(chatml_samples) * 0.9)
    val_end = train_end + int(len(chatml_samples) * 0.05)

    splits = {
        "train": chatml_samples[:train_end],
        "val": chatml_samples[train_end:val_end],
        "test": chatml_samples[val_end:],
    }

    # ------------------------------------------------------------------
    # Write output
    # ------------------------------------------------------------------
    args.output_dir.mkdir(parents=True, exist_ok=True)

    task_counts: dict[str, int] = {}
    for split_name, split_data in splits.items():
        path = args.output_dir / f"{split_name}.jsonl"
        with open(path, "w") as f:
            for chatml, metadata, score in split_data:
                record = {
                    "text": chatml,
                    "task_type": metadata["task_type"],
                    "reward_score": score,
                }
                f.write(json.dumps(record) + "\n")
                task_counts[metadata["task_type"]] = task_counts.get(metadata["task_type"], 0) + 1

    # Also write as plain text for simpler training
    for split_name, split_data in splits.items():
        path = args.output_dir / f"{split_name}.txt"
        with open(path, "w") as f:
            for chatml, _, _ in split_data:
                f.write(chatml + "\n\n")

    # Stats
    elapsed = time.time() - start
    scores = [s[2] for s in chatml_samples]

    report = {
        "total_input_samples": len(all_samples),
        "converted_samples": len(chatml_samples),
        "filter_threshold": threshold if model and not args.no_filter else None,
        "splits": {k: len(v) for k, v in splits.items()},
        "task_type_counts": task_counts,
        "score_distribution": {
            "mean": sum(scores) / len(scores) if scores else 0,
            "min": min(scores) if scores else 0,
            "max": max(scores) if scores else 0,
        },
        "elapsed_seconds": round(elapsed, 2),
    }

    report_path = args.output_dir / "preparation_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{'='*60}")
    print(f"SFT data preparation complete in {elapsed:.1f}s")
    print(f"  Input samples:    {len(all_samples)}")
    print(f"  Converted:        {len(chatml_samples)}")
    print(f"  Splits:           {len(splits['train'])} train / {len(splits['val'])} val / {len(splits['test'])} test")
    print(f"  By task type:")
    for task, count in sorted(task_counts.items(), key=lambda x: -x[1]):
        print(f"    {task:<25} {count:>6}")
    print(f"  Score range:      {min(scores):.4f} - {max(scores):.4f} (mean {sum(scores)/len(scores):.4f})")
    print(f"  Output:           {args.output_dir}/")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
