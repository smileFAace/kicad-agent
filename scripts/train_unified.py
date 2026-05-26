#!/usr/bin/env python3
"""Unified training: merge all data sources into a single reward model run.

Loads 6 data sources, converts each into (chain_text, labels) pairs,
trains a single tokenizer + reward model on the combined corpus.

Data sources:
  1. PCB graphs (sch+pcb pairs)  → board reasoning chains + corrupted negatives
  2. Schematic-only graphs       → schematic reasoning chains
  3. Textbook knowledge          → domain Q&A chains
  4. 100K crawl (matched pairs)  → board reasoning chains
  5. EasyEDA components           → component knowledge chains
  6. Gold-standard (RES scored)  → routing quality chains

Usage:
    python3 scripts/train_unified.py

    # Custom data dirs
    python3 scripts/train_unified.py --data-dirs training_data training_data_100k training_data_easyeda

    # GPU training
    python3 scripts/train_unified.py --device mps --n-epochs 10 --batch-size 64
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.training.reward_model import RewardModel, train_reward_model
from kicad_agent.training.tokenizer import ChainTokenizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_unified")


# ---------------------------------------------------------------------------
# Chain synthesis per data source
# ---------------------------------------------------------------------------


def load_board_graph_chains(data_dir: Path) -> list[tuple[str, tuple[float, float, float]]]:
    """Load PCB graph samples and synthesize reasoning chains.

    Only matches data dirs with board graph data (has 'graph_json' field).
    Uses board_chains.py for correct + corrupted chains with labels.
    """
    from kicad_agent.training.board_chains import (
        synthesize_board_chain,
        synthesize_corrupted_board_chain,
        _compute_chain_labels,
    )
    from kicad_agent.training.real_dataset import RealBoardSample

    samples = _load_jsonl_samples(data_dir)
    if not samples:
        return []

    # Verify this is board graph data
    if samples and "graph_json" not in samples[0]:
        return []

    texts: list[str] = []
    labels: list[tuple[float, float, float]] = []
    rng = random.Random(42)

    for raw in samples:
        try:
            sample = _dict_to_board_sample(raw)
        except Exception:
            continue

        # Correct chain
        correct = synthesize_board_chain(sample)
        c_labels = _compute_chain_labels(correct, sample)
        texts.append(correct.chain_text)
        labels.append(c_labels)

        # Corrupted negative
        corrupted = synthesize_corrupted_board_chain(sample, "random", rng_seed=rng.randint(0, 999999))
        x_labels = _compute_chain_labels(corrupted, sample)
        texts.append(corrupted.chain_text)
        labels.append(x_labels)

    return list(zip(texts, labels))


def load_textbook_chains(data_dir: Path) -> list[tuple[str, tuple[float, float, float]]]:
    """Load textbook chunks and convert to domain Q&A chains.

    Only matches data dirs with textbook data (has 'content_type' field).
    Textbook content gets high format/quality scores (it's authoritative),
    with accuracy based on presence of technical terms and coordinates.
    """
    samples = _load_jsonl_samples(data_dir)
    if not samples:
        return []

    # Verify this is textbook data
    if samples and "content_type" not in samples[0]:
        return []

    results: list[tuple[str, tuple[float, float, float]]] = []

    for raw in samples:
        content = raw.get("content", "")
        if not content or len(content) < 50:
            continue

        source = raw.get("source", "unknown")
        chapter = raw.get("chapter", "")

        # Synthesize a knowledge chain from the content
        chain = (
            f"Domain knowledge: {source}, {chapter}.\n"
            f"Content: {content[:2000]}\n"
            f"This describes electronics design principles from {source}."
        )

        # Labels: textbook content is authoritative
        has_technical = any(
            term in content.lower()
            for term in ["op-amp", "noise", "impedance", "gain", "frequency",
                         "capacitor", "resistor", "voltage", "current", "feedback",
                         "bandwidth", "distortion", "thermal", "ground", "trace",
                         "routing", "clearance", "drc", "net", "footprint"]
        )
        has_equations = any(c in content for c in ["=", "+", "dB", "MHz", "kHz", "V/", "ohm"])

        fmt = 0.9 if has_technical else 0.6
        qual = 0.95 if has_equations else (0.85 if has_technical else 0.5)
        acc = 0.9  # textbook content is ground truth

        results.append((chain, (fmt, qual, acc)))

    return results


def load_easyeda_chains(data_dir: Path) -> list[tuple[str, tuple[float, float, float]]]:
    """Load EasyEDA component data and convert to component knowledge chains.

    Only matches data dirs containing EasyEDA data (has 'lcsc' field).
    """
    samples = _load_jsonl_samples(data_dir)
    if not samples:
        return []

    # Verify this is actually EasyEDA data
    if samples and "lcsc" not in samples[0]:
        return []

    results: list[tuple[str, tuple[float, float, float]]] = []

    for raw in samples:
        name = raw.get("name", "")
        lcsc = raw.get("lcsc", "")
        package = raw.get("package", "")
        category = raw.get("category", "")
        brand = raw.get("brand", "")
        pin_count = raw.get("pin_count", 0)
        pad_count = raw.get("pad_count", 0)
        attrs = raw.get("attributes", {})

        if not name:
            continue

        # Build component knowledge chain
        parts = [f"Component: {name} (LCSC {lcsc})"]
        if brand:
            parts.append(f"Manufacturer: {brand}")
        if package:
            parts.append(f"Package: {package}")
        if category:
            parts.append(f"Category: {category}")
        if pin_count > 0:
            parts.append(f"Schematic pins: {pin_count}")
        if pad_count > 0:
            parts.append(f"Footprint pads: {pad_count}")

        # Key specs from attributes
        for attr_name, attr_value in list(attrs.items())[:5]:
            parts.append(f"{attr_name}: {attr_value}")

        # Pin descriptions (first 8)
        pins = raw.get("pins", [])
        if pins:
            pin_descs = []
            for p in pins[:8]:
                num = p.get("number", "")
                pname = p.get("name", "")
                if num and pname:
                    pin_descs.append(f"pin {num}={pname}")
            if pin_descs:
                parts.append("Pins: " + ", ".join(pin_descs))

        chain = "\n".join(parts)

        # Labels: component data is factual
        has_specs = bool(package and pin_count > 0)
        has_pins = pin_count > 0 and len(pins) > 0

        fmt = 0.9 if has_specs else 0.6
        qual = 0.85 if has_pins else (0.7 if has_specs else 0.4)
        acc = 0.95  # manufacturer data is accurate

        results.append((chain, (fmt, qual, acc)))

    return results


def load_gold_standard_chains(data_dir: Path) -> list[tuple[str, tuple[float, float, float]]]:
    """Load gold-standard boards with RES scores as routing quality chains.

    Only matches data containing routing_features (RES scored boards).
    """
    samples = _load_jsonl_samples(data_dir)
    if not samples:
        return []

    # Verify this is actually gold-standard RES data
    if samples and "routing_features" not in samples[0]:
        return []

    results: list[tuple[str, tuple[float, float, float]]] = []

    for raw in samples:
        fts = raw.get("routing_features", {})
        score = fts.get("elegance_score", 0.0)
        label = raw.get("quality_label", "unknown")
        n_fp = raw.get("n_footprints", 0)
        n_nets = raw.get("n_nets", 0)
        n_traces = raw.get("n_trace_items", 0)
        source = raw.get("source", "")

        chain = (
            f"Board routing analysis: {raw.get('pcb_name', 'unknown')}\n"
            f"Source: {source} (tier {raw.get('tier', '?')})\n"
            f"Components: {n_fp}, Nets: {n_nets}, Traces: {n_traces}\n"
            f"Routing Elegance Score: {score:.3f} ({label})\n"
            f"Density: {fts.get('component_density', 0):.3f} comp/mm2, "
            f"via density: {fts.get('via_density', 0):.3f}/mm2\n"
            f"Manhattan efficiency: {fts.get('manhattan_efficiency', 0):.3f}, "
            f"layers: {fts.get('layer_count', 0)}, "
            f"ground plane: {fts.get('has_ground_plane', False)}\n"
            f"Assessment: This board demonstrates {label} routing quality."
        )

        # Labels directly from RES score
        fmt = min(score + 0.1, 1.0)  # high-scored boards have good format
        qual = score  # quality = elegance score
        acc = min(score + 0.05, 1.0)  # real boards are accurate

        results.append((chain, (fmt, qual, acc)))

    return results


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------


def _load_jsonl_samples(data_dir: Path) -> list[dict]:
    """Load train.jsonl from a data directory."""
    train_path = data_dir / "train.jsonl"
    if not train_path.exists():
        return []

    samples = []
    with open(train_path) as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def _dict_to_board_sample(raw: dict):
    """Convert a JSONL dict to a RealBoardSample."""
    from kicad_agent.training.real_dataset import RealBoardSample

    return RealBoardSample(
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unified training across all data sources",
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
        help="Data directories to load (default: all standard dirs)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training_output/unified"),
        help="Output directory for model and report",
    )
    parser.add_argument(
        "--n-epochs",
        type=int,
        default=5,
        help="Training epochs (default: 5)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Training batch size (default: 32)",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=1e-4,
        help="Learning rate (default: 1e-4)",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Device: cpu, mps, cuda (auto-detects)",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=0,
        help="Max total samples (0=all)",
    )
    args = parser.parse_args()

    start_time = time.time()

    # Auto-detect device
    device = args.device
    if device == "cpu":
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
        except ImportError:
            pass

    logger.info("Unified training — device=%s", device)

    # ------------------------------------------------------------------
    # Load all data sources
    # ------------------------------------------------------------------

    all_chains: list[tuple[str, tuple[float, float, float]]] = []
    source_counts: dict[str, int] = {}

    loaders = {
        "board_graphs": load_board_graph_chains,
        "textbook": load_textbook_chains,
        "easyeda": load_easyeda_chains,
        "gold_standard": load_gold_standard_chains,
    }

    for data_dir_str in args.data_dirs:
        data_dir = Path(data_dir_str)
        if not data_dir.exists():
            logger.info("Skipping %s (not found)", data_dir)
            continue

        # Try each loader on this directory
        for loader_name, loader_fn in loaders.items():
            try:
                chains = loader_fn(data_dir)
                if chains:
                    all_chains.extend(chains)
                    source_counts[f"{data_dir.name}:{loader_name}"] = len(chains)
                    logger.info("  %s/%s: %d chains", data_dir.name, loader_name, len(chains))
            except Exception as e:
                logger.debug("  %s/%s: skipped (%s)", data_dir.name, loader_name, e)

    if not all_chains:
        logger.error("No training chains loaded from any source")
        return 1

    # Shuffle deterministically
    rng = random.Random(42)
    rng.shuffle(all_chains)

    # Truncate if needed
    if args.max_samples > 0:
        all_chains = all_chains[:args.max_samples]

    texts = [c[0] for c in all_chains]
    labels = [c[1] for c in all_chains]

    logger.info(
        "Total: %d chains from %d sources",
        len(all_chains), len(source_counts),
    )
    for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        logger.info("  %s: %d", src, count)

    # ------------------------------------------------------------------
    # Train tokenizer on full corpus
    # ------------------------------------------------------------------

    logger.info("Training tokenizer on %d texts...", len(texts))
    tokenizer = ChainTokenizer(vocab_size=8000)
    tokenizer.train(texts)
    logger.info("Tokenizer: vocab_size=%d", tokenizer.vocab_size_actual)

    # ------------------------------------------------------------------
    # Train reward model
    # ------------------------------------------------------------------

    logger.info(
        "Training reward model: %d samples, %d epochs, batch=%d, lr=%.1e, device=%s",
        len(texts), args.n_epochs, args.batch_size, args.lr, device,
    )

    reward_model = RewardModel(device=device)
    reward_model.set_tokenizer(tokenizer)

    if not reward_model.is_available:
        logger.error("PyTorch not available — cannot train")
        return 1

    history = train_reward_model(
        reward_model,
        texts,
        labels,
        n_epochs=args.n_epochs,
        learning_rate=args.lr,
        batch_size=args.batch_size,
    )

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Save model
    import torch
    model_path = args.output_dir / "reward_model.pt"
    torch.save(reward_model.model.state_dict(), model_path)

    # Save tokenizer vocab as JSON
    tok_path = args.output_dir / "tokenizer.json"
    import json as _json
    _json.dump({
        "token_to_id": tokenizer.token_to_id,
        "vocab_size": tokenizer.vocab_size_actual,
    }, open(tok_path, "w"), indent=2)

    # Save report
    elapsed = time.time() - start_time
    report = {
        "total_chains": len(texts),
        "source_counts": source_counts,
        "n_epochs": args.n_epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.lr,
        "device": device,
        "tokenizer_vocab_size": tokenizer.vocab_size_actual,
        "training_losses": history.get("losses", []),
        "final_loss": history.get("losses", [None])[-1],
        "elapsed_seconds": round(elapsed, 2),
        "model_path": str(model_path),
        "tokenizer_path": str(tok_path),
    }

    report_path = args.output_dir / "training_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # Print summary
    losses = history.get("losses", [])
    print(f"\n{'='*60}")
    print(f"Unified training complete in {elapsed:.1f}s")
    print(f"  Total chains:        {len(texts)}")
    for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"    {src:<40} {count:>6}")
    print(f"  Tokenizer vocab:     {tokenizer.vocab_size_actual}")
    print(f"  Epochs:              {args.n_epochs}")
    if losses:
        print(f"  Loss:                {losses[0]:.4f} → {losses[-1]:.4f}")
    print(f"  Device:              {device}")
    print(f"  Model:               {model_path}")
    print(f"  Tokenizer:           {tok_path}")
    print(f"  Report:              {report_path}")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
