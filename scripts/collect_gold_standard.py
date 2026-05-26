#!/usr/bin/env python3
"""Collect gold-standard PCB routing training data from curated repos.

Clones top-tier repos (HackRF, Mutable Instruments eurorack, etc.),
parses their PCBs, computes Routing Elegance Scores, and writes
curated JSONL training data.

No GitHub token required for public repos (but recommended for rate limits).

Usage:
    python3 scripts/collect_gold_standard.py --output-dir training_data_gold

    # Only clone specific tiers
    python3 scripts/collect_gold_standard.py --tiers S A

    # Use existing clones (skip git clone)
    python3 scripts/collect_gold_standard.py --staging-dir kicad_staging
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.training.routing_quality import (
    RoutingQualityFeatures,
    compute_routing_quality,
    features_to_dict,
    score_to_label,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("collect_gold")

# ---------------------------------------------------------------------------
# Curated repo registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GoldRepo:
    """A curated gold-standard PCB repository."""
    owner: str
    repo: str
    tier: str  # S, A, B, C
    description: str
    expected_boards: int  # rough estimate of .kicad_pcb files


GOLD_REPOS: list[GoldRepo] = [
    # Tier S: Proven gold standard (verified KiCad .kicad_pcb)
    GoldRepo("greatscottgadgets", "hackrf", "S",
             "HackRF One SDR: RF + MCU + USB, impedance-controlled",
             1),
    GoldRepo("skot", "bitaxe", "S",
             "Open source ASIC Bitcoin miner: dense power routing",
             1),

    # Tier A: Professional reference designs
    GoldRepo("pms67", "STM32F4-Reference-PCB", "A",
             "STM32F4 + USB + Buck reference PCB",
             1),
    GoldRepo("mtl", "keyboard-pcbs", "A",
             "Professional keyboard PCBs: amoeba, stabilizer, tp variants",
             6),

    # Tier B: Dense keyboard PCBs
    GoldRepo("beekeeb", "piantor", "B",
             "Split 42-key keyboard, RP2040, USB-C",
             2),
    GoldRepo("pashutk", "chocofi", "B",
             "Split 36-key keyboard, ultra-dense low-profile",
             2),
    GoldRepo("komar007", "gh60", "B",
             "GH60 open-source mechanical keyboard PCB",
             1),

    # Tier C: Dense routing (plates and various)
    GoldRepo("peej", "lumberjack-keyboard", "C",
             "5x12 ortholinear keyboard: 9 PCBs including plates",
             9),
]


def clone_repo(
    repo: GoldRepo,
    staging_dir: Path,
) -> Path | None:
    """Shallow-clone a repo into staging directory.

    Uses --depth 1 for speed. These repos are small enough that
    full shallow clones are fine (no sparse checkout needed).
    """
    target = staging_dir / f"{repo.owner}__{repo.repo}"
    if target.exists():
        logger.info("  Already cloned: %s/%s", repo.owner, repo.repo)
        return target

    url = f"https://github.com/{repo.owner}/{repo.repo}.git"
    logger.info("  Cloning %s/%s (tier %s)...", repo.owner, repo.repo, repo.tier)

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(target)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return target
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        stderr = ""
        if isinstance(e, subprocess.CalledProcessError):
            stderr = e.stderr or ""
        logger.warning("  Clone failed: %s", stderr[:200])
        return None


def find_pcb_files(repo_dir: Path) -> list[Path]:
    """Find all .kicad_pcb files in a repo directory."""
    return sorted(repo_dir.rglob("*.kicad_pcb"))


def parse_and_score(
    pcb_path: Path,
) -> dict | None:
    """Parse a .kicad_pcb file and compute routing quality.

    Returns a dict with features + metadata, or None on parse failure.
    """
    from kicad_agent.parser.pcb_parser import parse_pcb
    from kicad_agent.parser.uuid_extractor import extract_uuids
    from kicad_agent.ir.pcb_ir import PcbIR

    try:
        result = parse_pcb(pcb_path)
        if not result or not result.kiutils_obj:
            return None

        uuid_map = extract_uuids(result.raw_content, "pcb")
        ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)

        # Minimum viable board
        if len(ir.footprints) < 3:
            return None

        features = compute_routing_quality(ir)

        return {
            "pcb_path": str(pcb_path),
            "pcb_name": pcb_path.name,
            "repo_relative": pcb_path.relative_to(pcb_path.parents[3]).as_posix()
            if len(pcb_path.parts) > 3 else pcb_path.name,
            "n_footprints": len(ir.footprints),
            "n_nets": len(ir.nets) if hasattr(ir, "nets") else 0,
            "n_trace_items": len(ir.trace_items),
            "quality_label": score_to_label(features.elegance_score),
            "routing_features": features_to_dict(features),
        }
    except Exception as e:
        logger.debug("  Parse failed for %s: %s", pcb_path.name, e)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect gold-standard PCB routing training data",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training_data_gold"),
        help="Output directory for JSONL training data",
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=Path("kicad_staging"),
        help="Directory for cloned repos",
    )
    parser.add_argument(
        "--tiers",
        nargs="*",
        default=None,
        help="Only collect from these tiers (S, A, B, C). Default: all",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Minimum RES score to include (default: 0.0 = all)",
    )
    args = parser.parse_args()

    tiers = set(args.tiers) if args.tiers else {"S", "A", "B", "C"}
    repos = [r for r in GOLD_REPOS if r.tier in tiers]

    logger.info("Collecting gold-standard PCBs from %d repos (tiers: %s)",
                len(repos), ", ".join(sorted(tiers)))

    args.staging_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_samples: list[dict] = []
    sample_id = 0
    n_parsed = 0
    n_failed = 0

    for i, repo in enumerate(repos):
        logger.info(
            "[%d/%d] %s/%s (tier %s) — expecting ~%d boards",
            i + 1, len(repos), repo.owner, repo.repo, repo.tier,
            repo.expected_boards,
        )

        # Clone
        repo_dir = clone_repo(repo, args.staging_dir)
        if repo_dir is None:
            logger.warning("  Skipping %s/%s (clone failed)", repo.owner, repo.repo)
            continue

        # Find PCB files
        pcb_files = find_pcb_files(repo_dir)
        logger.info("  Found %d .kicad_pcb files", len(pcb_files))

        if not pcb_files:
            continue

        for pcb_path in pcb_files:
            result = parse_and_score(pcb_path)
            if result is None:
                n_failed += 1
                continue

            n_parsed += 1
            score = result["routing_features"]["elegance_score"]

            if score < args.min_score:
                logger.debug(
                    "  %s: RES=%.3f (%s) — below threshold",
                    pcb_path.name, score, result["quality_label"],
                )
                continue

            sample = {
                "sample_id": sample_id,
                "source": f"github/{repo.owner}/{repo.repo}",
                "tier": repo.tier,
                "description": repo.description,
                **result,
            }
            all_samples.append(sample)
            sample_id += 1

            logger.info(
                "  %s: RES=%.3f (%s) — %d footprints, %d nets, %d traces",
                pcb_path.name,
                score,
                result["quality_label"],
                result["n_footprints"],
                result["n_nets"],
                result["n_trace_items"],
            )

            time.sleep(0.1)  # rate limit between parses

        time.sleep(1.0)  # rate limit between repos

    if not all_samples:
        logger.warning("No valid samples collected")
        return 0

    # Sort by elegance score (best first)
    all_samples.sort(
        key=lambda s: s["routing_features"]["elegance_score"],
        reverse=True,
    )

    # Write JSONL splits
    import random
    rng = random.Random(42)
    indices = list(range(len(all_samples)))
    rng.shuffle(indices)
    shuffled = [all_samples[i] for i in indices]

    train_end = int(len(shuffled) * 0.8)
    val_end = train_end + int(len(shuffled) * 0.1)

    for name, subset in [
        ("train", shuffled[:train_end]),
        ("val", shuffled[train_end:val_end]),
        ("test", shuffled[val_end:]),
    ]:
        path = args.output_dir / f"{name}.jsonl"
        with open(path, "w") as f:
            for s in subset:
                f.write(json.dumps(s) + "\n")

    # Stats
    scores = [s["routing_features"]["elegance_score"] for s in all_samples]
    tier_counts = {}
    for s in all_samples:
        tier_counts[s["tier"]] = tier_counts.get(s["tier"], 0) + 1

    print(f"\n{'='*60}")
    print(f"Gold-standard collection complete: {len(all_samples)} boards")
    print(f"  Parsed successfully:  {n_parsed}")
    print(f"  Parse failures:       {n_failed}")
    print(f"  Min RES:              {min(scores):.3f}")
    print(f"  Max RES:              {max(scores):.3f}")
    print(f"  Mean RES:             {sum(scores)/len(scores):.3f}")
    print(f"  Splits:               {train_end} train / {val_end-train_end} val / {len(shuffled)-val_end} test")
    print(f"  By tier:              {dict(sorted(tier_counts.items()))}")
    print(f"  Output:               {args.output_dir}/")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
