#!/usr/bin/env python3
"""Collect real-world KiCad training data from GitHub.

Discovers public KiCad repositories, downloads schematic+PCB pairs,
parses them into structured graph data, deduplicates, quality-filters,
and writes train/val/test JSONL splits.

Usage:
    export GITHUB_TOKEN="ghp_..."
    python scripts/collect_training_data.py --max-repos 100 --output-dir training_data
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Add src to path so this script works without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.training.real_dataset import run_pipeline  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("collect_training_data")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect real-world KiCad training data from GitHub",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("GITHUB_TOKEN"),
        help="GitHub PAT with public_repo scope (default: GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--max-repos",
        type=int,
        default=500,
        help="Maximum repos to discover (default: 500)",
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=Path("kicad_staging"),
        help="Local dir for downloaded files (default: kicad_staging)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training_data"),
        help="Output dir for train.jsonl, val.jsonl, test.jsonl (default: training_data)",
    )
    args = parser.parse_args()

    if not args.token:
        logger.error("GITHUB_TOKEN not set. Use --token or set GITHUB_TOKEN env var.")
        return 1

    logger.info(
        "Starting pipeline: max_repos=%d, staging=%s, output=%s",
        args.max_repos,
        args.staging_dir,
        args.output_dir,
    )

    dataset = run_pipeline(
        token=args.token,
        staging_dir=args.staging_dir,
        max_repos=args.max_repos,
        output_dir=args.output_dir,
    )

    meta = dataset.metadata
    print(f"\n{'='*50}")
    print(f"Collection complete: {len(dataset)} samples")
    print(f"  Discovered:    {meta.get('n_discovered', 0)} file pairs")
    print(f"  Parsed:        {meta.get('n_parsed', 0)} boards")
    print(f"  Failed:        {meta.get('n_failed', 0)}")
    print(f"  Duplicates:    {meta.get('n_duplicates_removed', 0)} removed")
    print(f"  Low quality:   {meta.get('n_quality_removed', 0)} removed")
    print(f"  Difficulty:    {dataset.difficulty_counts}")
    print(f"  Output:        {args.output_dir}/")
    print(f"{'='*50}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
