#!/usr/bin/env python3
"""Score reasoning chains with the trained unified reward model.

Loads the model from training_output/unified/ and provides 3 modes:

  1. Score a single chain           --chain "Observation: ..."
  2. Score chains from a JSONL file --input training_data_gold/train.jsonl
  3. Best-of-N generation           --best-of 5 --sample <pcb_path>

Usage:
    # Score a single chain
    python3 scripts/score_chain.py --chain "Observation: board has 50 components..."

    # Score all chains from gold standard data
    python3 scripts/score_chain.py --input training_data_gold/train.jsonl

    # Best-of-N: generate chains for a PCB and pick the best
    python3 scripts/score_chain.py --best-of 5 --sample kicad_staging/hackrf/hardware/hackrf-one/hackrf-one.kicad_pcb

    # Discrimination test: correct vs corrupted chains
    python3 scripts/score_chain.py --discriminate --input training_data_v3/train.jsonl --limit 20
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


def load_model(model_dir: str) -> RewardModel:
    """Load trained model + tokenizer."""
    print(f"Loading model from {model_dir}...")
    t0 = time.time()
    model = RewardModel.load_trained(model_dir)
    elapsed = time.time() - t0
    print(f"  Loaded in {elapsed:.2f}s (device: {model._device})")
    return model


def print_score(chain_text: str, label: str = "") -> None:
    """Pretty-print scores for a chain."""
    pred = predict_score(chain_text)
    avg = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0
    prefix = f"  [{label}] " if label else "  "
    print(f"{prefix}Avg={avg:.4f}  fmt={pred.format_score:.4f}  qual={pred.quality_score:.4f}  acc={pred.accuracy_score:.4f}")


# ---------------------------------------------------------------------------
# Mode 1: Score a single chain
# ---------------------------------------------------------------------------

def score_single(model: RewardModel, chain_text: str) -> None:
    pred = predict_reward(model, chain_text)
    avg = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0
    print(f"\nChain: {chain_text[:120]}...")
    print(f"  Format:   {pred.format_score:.4f}")
    print(f"  Quality:  {pred.quality_score:.4f}")
    print(f"  Accuracy: {pred.accuracy_score:.4f}")
    print(f"  Average:  {avg:.4f}")


# ---------------------------------------------------------------------------
# Mode 2: Score chains from JSONL
# ---------------------------------------------------------------------------

def score_jsonl(model: RewardModel, input_path: Path, limit: int = 0) -> None:
    samples = []
    with open(input_path) as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))

    if limit > 0:
        samples = samples[:limit]

    print(f"\nScoring {len(samples)} chains from {input_path.name}...")

    scores = []
    t0 = time.time()
    for i, raw in enumerate(samples):
        # Build chain text from available fields
        chain_text = _extract_chain_text(raw)
        if not chain_text:
            continue

        pred = predict_reward(model, chain_text)
        avg = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0
        scores.append(avg)

        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(samples)}] avg_score so far: {sum(scores)/len(scores):.4f}")

    elapsed = time.time() - t0
    if scores:
        print(f"\n  Results ({elapsed:.1f}s, {len(scores)/elapsed:.0f} chains/s):")
        print(f"    Mean:   {sum(scores)/len(scores):.4f}")
        print(f"    Min:    {min(scores):.4f}")
        print(f"    Max:    {max(scores):.4f}")
        print(f"    Median: {sorted(scores)[len(scores)//2]:.4f}")


# ---------------------------------------------------------------------------
# Mode 3: Discrimination test (correct vs corrupted)
# ---------------------------------------------------------------------------

def discriminate(model: RewardModel, input_path: Path, limit: int = 20) -> None:
    """Score correct vs corrupted chains and measure discrimination gap."""
    from kicad_agent.training.real_dataset import RealBoardSample

    samples = []
    with open(input_path) as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))

    rng = random.Random(42)
    samples = samples[:limit]

    print(f"\nDiscrimination test: {len(samples)} samples from {input_path.name}")

    from kicad_agent.training.board_chains import (
        synthesize_board_chain,
        synthesize_corrupted_board_chain,
        _compute_chain_labels,
    )

    correct_scores = []
    corrupted_scores = []
    gaps = []

    for i, raw in enumerate(samples):
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
        except Exception:
            continue

        correct = synthesize_board_chain(sample)
        corrupted = synthesize_corrupted_board_chain(
            sample, "random", rng_seed=rng.randint(0, 999999),
        )

        pred_c = predict_reward(model, correct.chain_text)
        pred_x = predict_reward(model, corrupted.chain_text)

        c_score = (pred_c.format_score + pred_c.quality_score + pred_c.accuracy_score) / 3.0
        x_score = (pred_x.format_score + pred_x.quality_score + pred_x.accuracy_score) / 3.0
        gap = c_score - x_score

        correct_scores.append(c_score)
        corrupted_scores.append(x_score)
        gaps.append(gap)

        label = "OK" if gap > 0 else "INV"
        print(f"  [{i+1:3d}] correct={c_score:.4f}  corrupted={x_score:.4f}  gap={gap:+.4f}  [{label}]")

    if gaps:
        avg_gap = sum(gaps) / len(gaps)
        correct_pct = sum(1 for g in gaps if g > 0) / len(gaps) * 100
        print(f"\n  Discrimination summary:")
        print(f"    Avg gap:           {avg_gap:+.4f}")
        print(f"    Correct > Corrupt: {correct_pct:.0f}%")
        print(f"    Mean correct:      {sum(correct_scores)/len(correct_scores):.4f}")
        print(f"    Mean corrupted:    {sum(corrupted_scores)/len(corrupted_scores):.4f}")


# ---------------------------------------------------------------------------
# Mode 4: Best-of-N for a PCB file
# ---------------------------------------------------------------------------

def best_of_n(model: RewardModel, pcb_path: Path, n: int = 5) -> None:
    """Parse a PCB, generate N reasoning chains, score and rank them."""
    from kicad_agent.parser.pcb_parser import parse_pcb
    from kicad_agent.parser.uuid_extractor import extract_uuids
    from kicad_agent.ir.pcb_ir import PcbIR
    from kicad_agent.training.real_dataset import RealBoardSample
    from kicad_agent.training.board_chains import (
        synthesize_board_chain,
        synthesize_corrupted_board_chain,
    )

    print(f"\nParsing {pcb_path.name}...")
    result = parse_pcb(pcb_path)
    if not result or not result.kiutils_obj:
        print("  Failed to parse PCB")
        return

    uuid_map = extract_uuids(result.raw_content, "pcb")
    ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)

    sample = RealBoardSample(
        sample_id=0,
        repo_url="",
        repo_name=pcb_path.stem,
        schematic_path="",
        pcb_path=str(pcb_path),
        component_count=len(ir.footprints),
        net_count=len(ir.nets) if hasattr(ir, "nets") else 0,
        layer_count=len(ir.layers) if hasattr(ir, "layers") else 0,
        board_width_mm=0.0,
        board_height_mm=0.0,
        difficulty="medium",
        board_hash="",
        graph_json="{}",
        spatial_summary_json="{}",
        source_format="kicad_pcb",
    )

    print(f"  {len(ir.footprints)} footprints, {sample.net_count} nets")

    # Generate candidates
    rng = random.Random(42)
    candidates = [synthesize_board_chain(sample)]
    corruption_types = [
        "wrong_coords", "missing_steps", "subtle_coord_drift",
        "swapped_components", "vague_reasoning",
    ]
    for i in range(min(n - 1, len(corruption_types))):
        corrupted = synthesize_corrupted_board_chain(
            sample, corruption_types[i % len(corruption_types)],
            rng_seed=rng.randint(0, 999999),
        )
        candidates.append(corrupted)

    # Score all candidates
    print(f"\nBest-of-{n} selection:")
    scored = []
    for i, chain in enumerate(candidates):
        pred = predict_reward(model, chain.chain_text)
        avg = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0
        scored.append((avg, pred, chain))
        tag = "CORRECT" if i == 0 else chain.corruption_type
        print(f"  [{i+1}] avg={avg:.4f}  fmt={pred.format_score:.4f}  qual={pred.quality_score:.4f}  acc={pred.accuracy_score:.4f}  ({tag})")

    # Winner
    scored.sort(key=lambda x: x[0], reverse=True)
    winner_score, winner_pred, winner_chain = scored[0]
    print(f"\n  Winner: avg={winner_score:.4f}")
    print(f"  Chain preview: {winner_chain.chain_text[:200]}...")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_chain_text(raw: dict) -> str:
    """Extract or synthesize chain text from a JSONL sample."""
    # If it has a chain_text field directly
    if "chain_text" in raw:
        return raw["chain_text"]

    # Board graph data — synthesize from graph
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

    # Gold standard routing data
    if "routing_features" in raw:
        fts = raw["routing_features"]
        return (
            f"Board routing analysis: {raw.get('pcb_name', 'unknown')}\n"
            f"Components: {raw.get('n_footprints', 0)}, Nets: {raw.get('n_nets', 0)}\n"
            f"Routing Elegance Score: {fts.get('elegance_score', 0):.3f}\n"
        )

    # EasyEDA component data
    if "lcsc" in raw:
        return (
            f"Component: {raw.get('name', '')} (LCSC {raw.get('lcsc', '')})\n"
            f"Package: {raw.get('package', '')}\n"
        )

    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score reasoning chains with the trained reward model",
    )
    parser.add_argument(
        "--model-dir",
        default="training_output/unified",
        help="Directory with reward_model.pt and tokenizer.json",
    )
    parser.add_argument(
        "--chain",
        type=str,
        help="Score a single chain text",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Score chains from a JSONL file",
    )
    parser.add_argument(
        "--best-of",
        type=int,
        default=0,
        help="Best-of-N selection for a PCB file",
    )
    parser.add_argument(
        "--sample",
        type=Path,
        help="PCB file for best-of-N scoring",
    )
    parser.add_argument(
        "--discriminate",
        action="store_true",
        help="Discrimination test: correct vs corrupted chains",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max samples to process (0=all)",
    )
    args = parser.parse_args()

    model = load_model(args.model_dir)

    if args.chain:
        score_single(model, args.chain)
    elif args.discriminate and args.input:
        discriminate(model, args.input, args.limit or 20)
    elif args.best_of > 0 and args.sample:
        best_of_n(model, args.sample, args.best_of)
    elif args.input:
        score_jsonl(model, args.input, args.limit)
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
