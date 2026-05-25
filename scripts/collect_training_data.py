#!/usr/bin/env python3
"""Collect real-world KiCad training data from GitHub.

Discovers public KiCad repositories using multiple strategies, downloads
schematic+PCB pairs, parses them into structured graph data, deduplicates,
quality-filters, and writes train/val/test JSONL splits.

Usage:
    export GITHUB_TOKEN="ghp_..."

    # Default: search API only (backward compat)
    python scripts/collect_training_data.py --max-repos 500 --output-dir training_data

    # Multi-strategy discovery (topics + search + curated orgs)
    python scripts/collect_training_data.py --strategy all --max-repos 2000

    # Topic-only (faster, broader coverage)
    python scripts/collect_training_data.py --strategy topics --max-repos 2000

    # Skip repos already downloaded
    python scripts/collect_training_data.py --strategy all --max-repos 2000 --skip-existing
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Add src to path so this script works without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.crawler.bulk_fetcher import BulkFetcher  # noqa: E402
from kicad_agent.crawler.github_discovery import GithubDiscovery  # noqa: E402
from kicad_agent.crawler.file_fetcher import FileFetcher  # noqa: E402
from kicad_agent.training.graph_builder import build_board_graph  # noqa: E402
from kicad_agent.training.real_dataset import (  # noqa: E402
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
logger = logging.getLogger("collect_training_data")


def _get_existing_repos(staging_dir: Path) -> set[str]:
    """Get set of repo directory names already in staging."""
    if not staging_dir.is_dir():
        return set()
    return {d.name for d in staging_dir.iterdir() if d.is_dir()}


def _run_bulk(
    args: argparse.Namespace,
    repos: list,
    staging_dir: Path,
) -> int:
    """Bulk mode: git clone repos, scan locally, parse, and write splits.

    Uses ``git clone --depth 1`` instead of the Contents API. Orders of
    magnitude faster for large crawls because we get the entire repo in
    one operation and scan for KiCad files locally.

    Args:
        args: Parsed CLI arguments.
        repos: List of RepoInfo from discovery.
        staging_dir: Local directory for cloned repos.

    Returns:
        Exit code (0 = success).
    """
    from collections import Counter

    fetcher = BulkFetcher(staging_dir=staging_dir, timeout=args.clone_timeout)
    repo_names = [r.full_name for r in repos]

    logger.info("Bulk cloning %d repos (timeout=%ds)...", len(repo_names), args.clone_timeout)
    batch_results = fetcher.clone_batch(repo_names, skip_existing=args.skip_existing)

    logger.info("Cloned %d repos with KiCad pairs, parsing...", len(batch_results))

    raw_samples: list[RealBoardSample] = []
    n_parsed = 0
    n_failed = 0
    n_no_pairs = 0
    sample_id = 0
    n_discovered = 0

    # Build lookup from repo_name -> RepoInfo for metadata
    repo_info_map = {r.full_name: r for r in repos}

    for repo_name, pairs in batch_results.items():
        n_discovered += len(pairs)
        repo_info = repo_info_map.get(repo_name)
        repo_url = repo_info.html_url if repo_info else ""
        repo_full = repo_info.full_name if repo_info else repo_name

        for pair in pairs:
            try:
                result = build_board_graph(
                    sch_path=pair.schematic_path,
                    pcb_path=pair.pcb_path,
                    sample_id=sample_id,
                    repo_url=repo_url,
                    repo_name=repo_full,
                    sch_repo_path=str(pair.schematic_path),
                    pcb_repo_path=str(pair.pcb_path),
                )

                if result is None:
                    n_failed += 1
                    continue

                raw_samples.append(_graph_result_to_sample(result, sample_id))
                sample_id += 1
                n_parsed += 1

            except Exception as e:
                logger.warning("Failed for %s/%s: %s", repo_name, pair.base_name, e)
                n_failed += 1

    if not raw_samples:
        logger.warning("No samples collected from %d repos", len(batch_results))
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
        "strategy": f"{args.strategy}-bulk",
        "n_repos_scanned": len(repos),
        "n_repos_with_pairs": len(batch_results),
        "n_discovered": n_discovered,
        "n_parsed": n_parsed,
        "n_failed": n_failed,
        "n_duplicates_removed": n_before_dedup - n_deduped,
        "n_quality_removed": n_before_filter - n_filtered,
        "difficulty_counts": difficulty_counts,
    }

    dataset = RealBoardDataset(samples=filtered, metadata=metadata)

    output_dir = Path(args.output_dir)
    train_ds, val_ds, test_ds = dataset.split()
    train_ds.to_jsonl(output_dir / "train.jsonl")
    val_ds.to_jsonl(output_dir / "val.jsonl")
    test_ds.to_jsonl(output_dir / "test.jsonl")

    print(f"\n{'='*60}")
    print(f"Bulk collection complete: {len(dataset)} samples")
    print(f"  Strategy:      {args.strategy}-bulk")
    print(f"  Repos scanned: {len(repos)}")
    print(f"  Repos cloned:  {len(batch_results)} with pairs")
    print(f"  Discovered:    {n_discovered} file pairs")
    print(f"  Parsed:        {n_parsed} boards")
    print(f"  Failed:        {n_failed}")
    print(f"  Duplicates:    {n_before_dedup - n_deduped} removed")
    print(f"  Low quality:   {n_before_filter - n_filtered} removed")
    print(f"  Difficulty:    {difficulty_counts}")
    print(f"  Splits:        {len(train_ds)} train / {len(val_ds)} val / {len(test_ds)} test")
    print(f"  Output:        {output_dir}/")
    print(f"{'='*60}")

    return 0


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
    parser.add_argument(
        "--strategy",
        default="search",
        choices=["search", "topics", "curated", "all"],
        help="Discovery strategy: search (default), topics, curated, or all",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip repos already present in staging-dir",
    )
    parser.add_argument(
        "--bulk",
        action="store_true",
        help="Use git clone --depth 1 instead of Contents API (much faster for large crawls)",
    )
    parser.add_argument(
        "--clone-timeout",
        type=int,
        default=120,
        help="Seconds before git clone times out (default: 120)",
    )
    args = parser.parse_args()

    if not args.token:
        logger.error("GITHUB_TOKEN not set. Use --token or set GITHUB_TOKEN env var.")
        return 1

    staging_dir = Path(args.staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    # Discover repos
    discovery = GithubDiscovery(args.token)

    if args.strategy == "all":
        logger.info("Discovering repos with ALL strategies (max=%d)", args.max_repos)
        repos = discovery.discover_all(max_repos=args.max_repos)
    elif args.strategy == "topics":
        logger.info("Discovering repos by TOPICS (max=%d)", args.max_repos)
        repos = discovery.discover_by_topics(max_repos=args.max_repos)
    elif args.strategy == "curated":
        logger.info("Discovering repos from CURATED orgs (max=%d)", args.max_repos)
        repos = discovery.discover_from_curated(max_repos=args.max_repos)
    else:
        logger.info("Discovering repos via SEARCH queries (max=%d)", args.max_repos)
        repos = discovery.discover_repos(max_repos=args.max_repos)

    logger.info("Discovered %d unique repos", len(repos))

    # Filter out existing repos if requested
    if args.skip_existing:
        existing = _get_existing_repos(staging_dir)
        before = len(repos)
        repos = [r for r in repos if r.full_name.replace("/", "_") not in existing]
        skipped = before - len(repos)
        if skipped > 0:
            logger.info("Skipped %d already-downloaded repos (%d remaining)", skipped, len(repos))

    if not repos:
        logger.warning("No new repos to process")
        return 0

    # Choose fetch mode
    if args.bulk:
        return _run_bulk(args, repos, staging_dir)

    # Set up file fetcher (Contents API mode)
    fetcher = FileFetcher(
        github_client=discovery._client,
        staging_dir=staging_dir,
        rate_limiter=discovery._rate_limiter,
    )

    # Stream: discover pairs -> fetch -> parse -> collect samples
    raw_samples: list[RealBoardSample] = []
    n_parsed = 0
    n_failed = 0
    n_no_pairs = 0
    sample_id = 0
    n_discovered = 0

    for repo_info in repos:
        pairs = discovery.find_kicad_pairs(repo_info)
        if not pairs:
            n_no_pairs += 1
            continue

        n_discovered += len(pairs)

        for pair in pairs:
            try:
                sch_file, pcb_file = fetcher.fetch_pair(repo_info.full_name, pair)

                if sch_file is None or pcb_file is None:
                    n_failed += 1
                    continue

                result = build_board_graph(
                    sch_path=sch_file.local_path,
                    pcb_path=pcb_file.local_path,
                    sample_id=sample_id,
                    repo_url=repo_info.html_url,
                    repo_name=repo_info.full_name,
                    sch_repo_path=pair.schematic_path,
                    pcb_repo_path=pair.pcb_path,
                )

                if result is None:
                    n_failed += 1
                    continue

                raw_samples.append(_graph_result_to_sample(result, sample_id))
                sample_id += 1
                n_parsed += 1

            except Exception as e:
                logger.warning("Failed for %s/%s: %s", repo_info.full_name, pair.base_name, e)
                n_failed += 1

    # Dedup and quality filter
    n_before_dedup = len(raw_samples)
    deduped = dedup_by_hash(raw_samples)
    n_deduped = len(deduped)

    n_before_filter = len(deduped)
    filtered = filter_quality(deduped)
    n_filtered = len(filtered)

    # Build dataset
    from collections import Counter

    difficulty_counts = dict(Counter(s.difficulty for s in filtered))
    metadata = {
        "strategy": args.strategy,
        "n_repos_scanned": len(repos),
        "n_repos_no_pairs": n_no_pairs,
        "n_discovered": n_discovered,
        "n_parsed": n_parsed,
        "n_failed": n_failed,
        "n_duplicates_removed": n_before_dedup - n_deduped,
        "n_quality_removed": n_before_filter - n_filtered,
        "difficulty_counts": difficulty_counts,
    }

    dataset = RealBoardDataset(samples=filtered, metadata=metadata)

    # Write splits
    output_dir = Path(args.output_dir)
    train_ds, val_ds, test_ds = dataset.split()
    train_ds.to_jsonl(output_dir / "train.jsonl")
    val_ds.to_jsonl(output_dir / "val.jsonl")
    test_ds.to_jsonl(output_dir / "test.jsonl")

    print(f"\n{'='*60}")
    print(f"Collection complete: {len(dataset)} samples")
    print(f"  Strategy:      {args.strategy}")
    print(f"  Repos scanned: {len(repos)} ({n_no_pairs} had no KiCad pairs)")
    print(f"  Discovered:    {n_discovered} file pairs")
    print(f"  Parsed:        {n_parsed} boards")
    print(f"  Failed:        {n_failed}")
    print(f"  Duplicates:    {n_before_dedup - n_deduped} removed")
    print(f"  Low quality:   {n_before_filter - n_filtered} removed")
    print(f"  Difficulty:    {difficulty_counts}")
    print(f"  Splits:        {len(train_ds)} train / {len(val_ds)} val / {len(test_ds)} test")
    print(f"  Output:        {output_dir}/")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
