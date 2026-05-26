#!/usr/bin/env python3
"""Fetch + parse discovered repos into training data.

Takes the JSON output from discover_100k.py, pre-filters via GitHub tree API,
sparse-clones, parses KiCad files, deduplicates, and writes train/val/test splits.

Usage:
    export GITHUB_TOKEN="$(gh auth token)"
    python3 scripts/fetch_100k.py --input discovered_repos.json --output-dir training_data_100k
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

from kicad_agent.crawler.bulk_fetcher import BulkFetcher
from kicad_agent.crawler.github_discovery import GithubDiscovery, RepoInfo
from kicad_agent.training.graph_builder import build_board_graph
from kicad_agent.training.real_dataset import (
    RealBoardDataset,
    RealBoardSample,
    _graph_result_to_sample,
    dedup_by_hash,
    filter_quality,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fetch_100k")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch + parse discovered repos")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--input", default="discovered_repos.json")
    parser.add_argument("--staging-dir", default="kicad_staging", type=Path)
    parser.add_argument("--output-dir", default="training_data_100k", type=Path)
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--clone-timeout", type=int, default=180)
    parser.add_argument("--batch-size", type=int, default=500,
                       help="Process repos in batches to manage memory")
    args = parser.parse_args()

    if not args.token:
        logger.error("GITHUB_TOKEN not set")
        return 1

    # Load discovered repos
    with open(args.input) as f:
        data = json.load(f)

    repo_dicts = data.get("repos", data) if isinstance(data, dict) else data
    logger.info("Loaded %d repos from %s", len(repo_dicts), args.input)

    # Convert to RepoInfo
    repos = [
        RepoInfo(
            full_name=r["full_name"],
            html_url=r["html_url"],
            stars=r.get("stars", 0),
            description=None,
            default_branch=r.get("default_branch", "main"),
        )
        for r in repo_dicts
    ]

    discovery = GithubDiscovery(args.token)
    fetcher = BulkFetcher(staging_dir=args.staging_dir, timeout=args.clone_timeout)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_raw: list[RealBoardSample] = []
    total_scanned = 0
    total_with_pairs = 0
    total_cloned = 0
    total_parsed = 0
    total_failed = 0
    sample_id = 0

    # Process in batches
    for batch_start in range(0, len(repos), args.batch_size):
        batch = repos[batch_start: batch_start + args.batch_size]
        batch_num = batch_start // args.batch_size + 1
        total_batches = (len(repos) + args.batch_size - 1) // args.batch_size

        logger.info(
            "=== Batch %d/%d: repos %d-%d ===",
            batch_num, total_batches, batch_start + 1,
            min(batch_start + args.batch_size, len(repos)),
        )

        # Phase 1: Pre-filter via tree API
        repos_with_pairs: dict[str, list] = {}
        for i, repo_info in enumerate(batch):
            if (i + 1) % 100 == 0:
                logger.info("Pre-filter: %d/%d (%d with pairs)",
                           i + 1, len(batch), len(repos_with_pairs))
            pairs = discovery.find_kicad_pairs(repo_info)
            if pairs:
                repos_with_pairs[repo_info.full_name] = pairs

        total_scanned += len(batch)
        total_with_pairs += len(repos_with_pairs)

        if not repos_with_pairs:
            logger.info("No pairs in this batch, skipping")
            continue

        # Phase 2: Sparse clone
        batch_results = fetcher.sparse_clone_batch(
            repos_with_pairs, skip_existing=args.skip_existing,
        )
        total_cloned += len(batch_results)

        # Phase 3: Parse
        repo_info_map = {r.full_name: r for r in batch}

        for repo_name, pairs in batch_results.items():
            repo_info = repo_info_map.get(repo_name)

            for pair in pairs:
                try:
                    result = build_board_graph(
                        sch_path=pair.schematic_path,
                        pcb_path=pair.pcb_path,
                        sample_id=sample_id,
                        repo_url=repo_info.html_url if repo_info else "",
                        repo_name=repo_info.full_name if repo_info else repo_name,
                        sch_repo_path=str(pair.schematic_path),
                        pcb_repo_path=str(pair.pcb_path),
                    )
                    if result is None:
                        total_failed += 1
                        continue
                    all_raw.append(_graph_result_to_sample(result, sample_id))
                    sample_id += 1
                    total_parsed += 1
                except Exception as e:
                    total_failed += 1

        logger.info(
            "Batch %d done: %d parsed, %d failed, %d total samples so far",
            batch_num, total_parsed, total_failed, len(all_raw),
        )

        # Flush partial results each batch
        if all_raw:
            deduped = dedup_by_hash(all_raw)
            filtered = filter_quality(deduped)
            difficulty_counts = dict(Counter(s.difficulty for s in filtered))
            dataset = RealBoardDataset(samples=filtered, metadata={
                "batch": batch_num,
                "repos_scanned": total_scanned,
                "repos_with_pairs": total_with_pairs,
                "repos_cloned": total_cloned,
                "parsed": total_parsed,
                "failed": total_failed,
                "difficulty_counts": difficulty_counts,
            })
            train_ds, val_ds, test_ds = dataset.split()
            train_ds.to_jsonl(args.output_dir / "train.jsonl")
            val_ds.to_jsonl(args.output_dir / "val.jsonl")
            test_ds.to_jsonl(args.output_dir / "test.jsonl")

    # Final summary
    deduped = dedup_by_hash(all_raw)
    filtered = filter_quality(deduped)
    difficulty_counts = dict(Counter(s.difficulty for s in filtered))

    dataset = RealBoardDataset(samples=filtered, metadata={
        "repos_scanned": total_scanned,
        "repos_with_pairs": total_with_pairs,
        "repos_cloned": total_cloned,
        "parsed": total_parsed,
        "failed": total_failed,
        "difficulty_counts": difficulty_counts,
    })
    train_ds, val_ds, test_ds = dataset.split()
    train_ds.to_jsonl(args.output_dir / "train.jsonl")
    val_ds.to_jsonl(args.output_dir / "val.jsonl")
    test_ds.to_jsonl(args.output_dir / "test.jsonl")

    print(f"\n{'='*60}")
    print(f"100K Collection complete: {len(dataset)} samples")
    print(f"  Repos scanned:  {total_scanned}")
    print(f"  With pairs:     {total_with_pairs}")
    print(f"  Cloned:         {total_cloned}")
    print(f"  Parsed:         {total_parsed}")
    print(f"  Failed:         {total_failed}")
    print(f"  Duplicates:     {len(all_raw) - len(deduped)} removed")
    print(f"  Low quality:    {len(deduped) - len(filtered)} removed")
    print(f"  Difficulty:     {difficulty_counts}")
    print(f"  Splits:         {len(train_ds)} train / {len(val_ds)} val / {len(test_ds)} test")
    print(f"  Output:         {args.output_dir}/")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
