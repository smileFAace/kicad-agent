#!/usr/bin/env python3
"""Collect schematic-only training data from local staging and discovered repos.

Scans kicad_staging/ for .kicad_sch files, parses each into a connectivity
graph using net labels + wires (no PCB required), deduplicates, and writes
train/val/test JSONL splits.

Usage:
    # From already-cloned repos (no network needed)
    python3 scripts/collect_schematics.py --staging-dir kicad_staging --output-dir training_data_schematics

    # From discovered repos JSON (needs GITHUB_TOKEN for tree lookups + cloning)
    export GITHUB_TOKEN="$(gh auth token)"
    python3 scripts/collect_schematics.py --input discovered_repos.json --output-dir training_data_schematics
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.training.graph_builder import (
    MIN_KICAD_VERSION,
    detect_kicad_version,
    is_likely_parseable,
)
from kicad_agent.training.real_dataset import (
    RealBoardDataset,
    RealBoardSample,
    _schematic_result_to_sample,
    dedup_by_hash,
    filter_quality,
)
from kicad_agent.training.schematic_graph_builder import build_schematic_graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("collect_schematics")


def _scan_local_schematics(staging_dir: Path) -> list[tuple[str, Path]]:
    """Find all valid .kicad_sch files in staging directory.

    Returns:
        List of (repo_name, sch_path) tuples.
    """
    results: list[tuple[str, Path]] = []

    for sch_path in sorted(staging_dir.rglob("*.kicad_sch")):
        if sch_path.stat().st_size == 0:
            continue

        try:
            text = sch_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if not is_likely_parseable(text):
            continue

        ver = detect_kicad_version(text)
        if ver is None or ver < MIN_KICAD_VERSION:
            continue

        # Derive repo name from directory structure
        rel = sch_path.relative_to(staging_dir)
        repo_name = str(rel.parts[0]) if len(rel.parts) > 1 else ""
        results.append((repo_name, sch_path))

    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect schematic-only training data",
    )
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument(
        "--staging-dir", type=Path, default=Path("kicad_staging"),
        help="Local dir with cloned repos (default: kicad_staging)",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("training_data_schematics"),
        help="Output dir for train/val/test JSONL splits",
    )
    args = parser.parse_args()

    staging_dir = args.staging_dir
    if not staging_dir.is_dir():
        logger.error("Staging dir not found: %s", staging_dir)
        return 1

    # Scan for schematics
    logger.info("Scanning %s for .kicad_sch files...", staging_dir)
    schematics = _scan_local_schematics(staging_dir)
    logger.info("Found %d valid schematics", len(schematics))

    if not schematics:
        logger.warning("No valid schematics found")
        return 0

    # Parse each schematic
    raw_samples: list[RealBoardSample] = []
    n_parsed = 0
    n_failed = 0
    sample_id = 0

    for i, (repo_name, sch_path) in enumerate(schematics):
        if (i + 1) % 500 == 0:
            logger.info(
                "Progress: %d/%d (%d parsed, %d failed)",
                i + 1, len(schematics), n_parsed, n_failed,
            )

        result = build_schematic_graph(
            sch_path=sch_path,
            sample_id=sample_id,
            repo_url="",
            repo_name=repo_name,
        )

        if result is None:
            n_failed += 1
            continue

        raw_samples.append(_schematic_result_to_sample(result, sample_id))
        sample_id += 1
        n_parsed += 1

    if not raw_samples:
        logger.warning("No samples collected")
        return 0

    # Dedup and quality filter
    n_before_dedup = len(raw_samples)
    deduped = dedup_by_hash(raw_samples)
    n_deduped = len(deduped)

    n_before_filter = len(deduped)
    filtered = filter_quality(deduped)
    n_filtered = len(filtered)

    difficulty_counts = dict(Counter(s.difficulty for s in filtered))
    metadata = {
        "source_format": "kicad_sch",
        "n_schematics_found": len(schematics),
        "n_parsed": n_parsed,
        "n_failed": n_failed,
        "n_duplicates_removed": n_before_dedup - n_deduped,
        "n_quality_removed": n_before_filter - n_filtered,
        "difficulty_counts": difficulty_counts,
    }

    dataset = RealBoardDataset(samples=filtered, metadata=metadata)

    output_dir = args.output_dir
    train_ds, val_ds, test_ds = dataset.split()
    train_ds.to_jsonl(output_dir / "train.jsonl")
    val_ds.to_jsonl(output_dir / "val.jsonl")
    test_ds.to_jsonl(output_dir / "test.jsonl")

    print(f"\n{'='*60}")
    print(f"Schematic collection complete: {len(dataset)} samples")
    print(f"  Schematics found:    {len(schematics)}")
    print(f"  Parsed:              {n_parsed}")
    print(f"  Failed:              {n_failed}")
    print(f"  Duplicates removed:  {n_before_dedup - n_deduped}")
    print(f"  Quality removed:     {n_before_filter - n_filtered}")
    print(f"  Difficulty:          {difficulty_counts}")
    print(f"  Splits:              {len(train_ds)} train / {len(val_ds)} val / {len(test_ds)} test")
    print(f"  Output:              {output_dir}/")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
