"""Real-world PCB board dataset for GRPO training.

RW-04: SHA256 deduplication and quality filtering for real board data.
RW-05: JSONL serialization compatible with Phase 9 GRPO training pipeline.

Follows the MazeDataset pattern: frozen dataclass + JSONL streaming +
train/val/test split. Designed for 50k+ board scale with streaming
processing (parse one, serialize, discard, move to next).
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from kicad_agent.crawler.file_fetcher import FileFetcher
from kicad_agent.crawler.github_discovery import GithubDiscovery, KicadFilePair, RepoInfo
from kicad_agent.training.graph_builder import (
    MIN_KICAD_VERSION,
    BoardGraphResult,
    build_board_graph,
    detect_kicad_version,
    is_likely_parseable,
)
from kicad_agent.training.schematic_graph_builder import (
    SchematicGraphResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Quality thresholds (T-13-09)
# ---------------------------------------------------------------------------

MIN_COMPONENTS = 3  # boards with fewer are trivially simple
MIN_NETS = 2  # boards with fewer lack meaningful connectivity


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RealBoardSample:
    """A single real-world PCB sample with graph and spatial data.

    All fields are primitives or JSON strings to ensure safe serialization
    to JSONL. Mirrors BoardGraphResult fields exactly.

    Attributes:
        sample_id: Sequential index in dataset.
        repo_url: Source repository URL.
        repo_name: Source repository full name.
        schematic_path: Path to schematic file within repo.
        pcb_path: Path to PCB file within repo.
        component_count: Number of component nodes in graph.
        net_count: Number of unique nets.
        layer_count: Number of PCB layers.
        board_width_mm: Board width in millimeters.
        board_height_mm: Board height in millimeters.
        difficulty: "easy", "medium", or "hard".
        board_hash: SHA256 hex digest for deduplication.
        graph_json: networkx graph serialized as JSON (node-link-data).
        spatial_summary_json: JSON string with spatial feature counts.
    """

    sample_id: int
    repo_url: str
    repo_name: str
    schematic_path: str
    pcb_path: str
    component_count: int
    net_count: int
    layer_count: int
    board_width_mm: float
    board_height_mm: float
    difficulty: str
    board_hash: str
    graph_json: str
    spatial_summary_json: str
    source_format: str = "kicad_pcb"  # "kicad_pcb" or "kicad_sch"


@dataclass
class RealBoardDataset:
    """Collection of real-world PCB samples with metadata.

    Follows MazeDataset pattern: JSONL serialization, train/val/test split,
    and metadata tracking.

    Attributes:
        samples: Ordered list of RealBoardSample objects.
        metadata: Pipeline metadata (counts, difficulty distribution).
    """

    samples: list[RealBoardSample] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.samples)

    @property
    def difficulty_counts(self) -> dict[str, int]:
        """Count of samples per difficulty level."""
        return dict(Counter(s.difficulty for s in self.samples))

    def to_jsonl(self, path: Path) -> int:
        """Write samples as JSONL (one JSON object per line).

        Args:
            path: Output file path.

        Returns:
            Number of lines written.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(path, "w") as f:
            for sample in self.samples:
                f.write(json.dumps(_sample_to_dict(sample)) + "\n")
                count += 1
        return count

    @staticmethod
    def from_jsonl(path: Path) -> RealBoardDataset:
        """Load samples from a JSONL file.

        Args:
            path: Input JSONL file path.

        Returns:
            RealBoardDataset with loaded samples.
        """
        path = Path(path)
        samples: list[RealBoardSample] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    samples.append(_dict_to_sample(json.loads(line)))
        return RealBoardDataset(samples=samples)

    def split(
        self,
        train: float = 0.8,
        val: float = 0.1,
        test: float = 0.1,
    ) -> tuple[RealBoardDataset, RealBoardDataset, RealBoardDataset]:
        """Deterministic train/val/test split by sample_id order.

        Args:
            train: Fraction for training set (default 0.8).
            val: Fraction for validation set (default 0.1).
            test: Fraction for test set (default 0.1).

        Returns:
            Tuple of (train_dataset, val_dataset, test_dataset).

        Raises:
            ValueError: If fractions don't sum to 1.0 (within tolerance).
        """
        total = train + val + test
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Split fractions must sum to 1.0, got {total}")

        n = len(self.samples)
        indices = list(range(n))
        import random
        rng = random.Random(42)
        rng.shuffle(indices)
        shuffled = [self.samples[i] for i in indices]
        train_end = int(n * train)
        val_end = train_end + int(n * val)

        return (
            RealBoardDataset(samples=shuffled[:train_end]),
            RealBoardDataset(samples=shuffled[train_end:val_end]),
            RealBoardDataset(samples=shuffled[val_end:]),
        )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _sample_to_dict(s: RealBoardSample) -> dict:
    """Convert RealBoardSample to a JSON-serializable dict."""
    return {
        "sample_id": s.sample_id,
        "repo_url": s.repo_url,
        "repo_name": s.repo_name,
        "schematic_path": s.schematic_path,
        "pcb_path": s.pcb_path,
        "component_count": s.component_count,
        "net_count": s.net_count,
        "layer_count": s.layer_count,
        "board_width_mm": s.board_width_mm,
        "board_height_mm": s.board_height_mm,
        "difficulty": s.difficulty,
        "board_hash": s.board_hash,
        "graph_json": s.graph_json,
        "spatial_summary_json": s.spatial_summary_json,
        "source_format": s.source_format,
    }


def _dict_to_sample(d: dict) -> RealBoardSample:
    """Convert a dict back to RealBoardSample."""
    return RealBoardSample(
        sample_id=d["sample_id"],
        repo_url=d["repo_url"],
        repo_name=d["repo_name"],
        schematic_path=d["schematic_path"],
        pcb_path=d["pcb_path"],
        component_count=d["component_count"],
        net_count=d["net_count"],
        layer_count=d["layer_count"],
        board_width_mm=d["board_width_mm"],
        board_height_mm=d["board_height_mm"],
        difficulty=d["difficulty"],
        board_hash=d["board_hash"],
        graph_json=d["graph_json"],
        spatial_summary_json=d["spatial_summary_json"],
        source_format=d.get("source_format", "kicad_pcb"),
    )


# ---------------------------------------------------------------------------
# Quality filtering
# ---------------------------------------------------------------------------


def is_valid_sample(sample: RealBoardSample) -> bool:
    """Check whether a sample meets minimum quality thresholds.

    Args:
        sample: RealBoardSample to validate.

    Returns:
        True if sample has at least MIN_COMPONENTS and MIN_NETS.
    """
    return sample.component_count >= MIN_COMPONENTS and sample.net_count >= MIN_NETS


def filter_quality(samples: list[RealBoardSample]) -> list[RealBoardSample]:
    """Remove trivially simple boards from a sample list.

    Args:
        samples: Input list of RealBoardSample objects.

    Returns:
        Filtered list with only valid samples.
    """
    filtered = [s for s in samples if is_valid_sample(s)]
    removed = len(samples) - len(filtered)
    if removed > 0:
        logger.info("Quality filter removed %d trivial boards out of %d", removed, len(samples))
    return filtered


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def dedup_by_hash(samples: list[RealBoardSample]) -> list[RealBoardSample]:
    """Remove duplicate samples by board_hash, keeping first occurrence.

    Uses O(n) set lookup. The board_hash field is already a SHA256 hex
    digest computed from raw schematic+PCB content bytes.

    Args:
        samples: Input list of RealBoardSample objects.

    Returns:
        Deduplicated list preserving first-occurrence order.
    """
    seen: set[str] = set()
    unique: list[RealBoardSample] = []
    duplicates = 0

    for sample in samples:
        if sample.board_hash in seen:
            duplicates += 1
            continue
        seen.add(sample.board_hash)
        unique.append(sample)

    if duplicates > 0:
        logger.info("Dedup removed %d duplicate boards out of %d", duplicates, len(samples))

    return unique


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------


def _graph_result_to_sample(result: BoardGraphResult, sample_id: int) -> RealBoardSample:
    """Convert a BoardGraphResult to a RealBoardSample.

    Fields map 1:1 since RealBoardSample mirrors BoardGraphResult.

    Args:
        result: BoardGraphResult from graph_builder.
        sample_id: Sequential sample index.

    Returns:
        RealBoardSample with identical field values.
    """
    return RealBoardSample(
        sample_id=sample_id,
        repo_url=result.repo_url,
        repo_name=result.repo_name,
        schematic_path=result.schematic_path,
        pcb_path=result.pcb_path,
        component_count=result.component_count,
        net_count=result.net_count,
        layer_count=result.layer_count,
        board_width_mm=result.board_width_mm,
        board_height_mm=result.board_height_mm,
        difficulty=result.difficulty,
        board_hash=result.board_hash,
        graph_json=result.graph_json,
        spatial_summary_json=result.spatial_summary_json,
        source_format="kicad_pcb",
    )


def _schematic_result_to_sample(result: SchematicGraphResult, sample_id: int) -> RealBoardSample:
    """Convert a SchematicGraphResult to a RealBoardSample.

    Args:
        result: SchematicGraphResult from schematic_graph_builder.
        sample_id: Sequential sample index.

    Returns:
        RealBoardSample with schematic-only fields.
    """
    return RealBoardSample(
        sample_id=sample_id,
        repo_url=result.repo_url,
        repo_name=result.repo_name,
        schematic_path=result.schematic_path,
        pcb_path=result.pcb_path,
        component_count=result.component_count,
        net_count=result.net_count,
        layer_count=result.layer_count,
        board_width_mm=result.board_width_mm,
        board_height_mm=result.board_height_mm,
        difficulty=result.difficulty,
        board_hash=result.board_hash,
        graph_json=result.graph_json,
        spatial_summary_json=result.spatial_summary_json,
        source_format="kicad_sch",
    )


def run_pipeline(
    token: str,
    staging_dir: Path,
    max_repos: int = 500,
    output_dir: Path | None = None,
) -> RealBoardDataset:
    """End-to-end pipeline: discover -> fetch -> parse -> dedup -> filter.

    Processes one board at a time (streaming). After build_board_graph
    returns a BoardGraphResult, converts it to RealBoardSample (all
    primitives/strings) and discards the live parsed IR.

    Args:
        token: GitHub personal access token with public_repo scope.
        staging_dir: Local directory for downloaded KiCad files.
        max_repos: Maximum number of repos to discover.
        output_dir: If provided, write train.jsonl, val.jsonl, test.jsonl
            splits to this directory.

    Returns:
        RealBoardDataset with metadata including discovery and filter counts.
    """
    if not token or not token.strip():
        raise ValueError("GitHub token must be a non-empty string")

    # 1. Discover repos with KiCad file pairs
    discovery = GithubDiscovery(token)
    repo_pairs = discovery.discover_pairs(max_repos=max_repos)

    n_discovered = sum(len(pairs) for _, pairs in repo_pairs)
    logger.info("Discovered %d file pairs across %d repos", n_discovered, len(repo_pairs))

    # 2. Set up file fetcher
    fetcher = FileFetcher(
        github_client=discovery._client,
        staging_dir=staging_dir,
        rate_limiter=discovery._rate_limiter,
    )

    # 3. Stream: fetch -> parse -> convert -> accumulate samples only
    raw_samples: list[RealBoardSample] = []
    n_parsed = 0
    n_failed = 0
    sample_id = 0

    for repo_info, pairs in repo_pairs:
        for pair in pairs:
            try:
                # Fetch both files
                sch_file, pcb_file = fetcher.fetch_pair(repo_info.full_name, pair)

                if sch_file is None or pcb_file is None:
                    n_failed += 1
                    continue

                # Parse into graph (streaming: IR lives only during this call)
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

                # Convert to serializable sample and discard live IR
                raw_samples.append(_graph_result_to_sample(result, sample_id))
                sample_id += 1
                n_parsed += 1

            except Exception as e:
                logger.warning("Pipeline failed for %s/%s: %s", repo_info.full_name, pair.base_name, e)
                n_failed += 1

    # 4. Dedup by board_hash
    n_before_dedup = len(raw_samples)
    deduped = dedup_by_hash(raw_samples)
    n_deduped = len(deduped)

    # 5. Quality filter
    n_before_filter = len(deduped)
    filtered = filter_quality(deduped)
    n_filtered = len(filtered)

    # 6. Build dataset with audit metadata (T-13-12)
    difficulty_counts = dict(Counter(s.difficulty for s in filtered))
    metadata = {
        "n_discovered": n_discovered,
        "n_parsed": n_parsed,
        "n_failed": n_failed,
        "n_duplicates_removed": n_before_dedup - n_deduped,
        "n_quality_removed": n_before_filter - n_filtered,
        "difficulty_counts": difficulty_counts,
    }

    dataset = RealBoardDataset(samples=filtered, metadata=metadata)

    logger.info(
        "Pipeline complete: %d discovered -> %d parsed -> %d deduped -> %d filtered",
        n_discovered,
        n_parsed,
        n_deduped,
        n_filtered,
    )

    # 7. Write JSONL splits if output_dir provided
    if output_dir is not None:
        output_dir = Path(output_dir)
        train_ds, val_ds, test_ds = dataset.split()
        train_ds.to_jsonl(output_dir / "train.jsonl")
        val_ds.to_jsonl(output_dir / "val.jsonl")
        test_ds.to_jsonl(output_dir / "test.jsonl")
        logger.info("Wrote splits to %s", output_dir)

    return dataset


def _find_pcb_sch_pairs(staging_dir: Path) -> list[tuple[Path, Path]]:
    """Find all valid .kicad_pcb + .kicad_sch pairs in a staging directory.

    Pairs by matching base name within the same directory. Skips empty files
    and files with KiCad version < MIN_KICAD_VERSION.

    Args:
        staging_dir: Root directory to scan recursively.

    Returns:
        List of (sch_path, pcb_path) tuples.
    """
    pairs: list[tuple[Path, Path]] = []

    for pcb_path in sorted(staging_dir.rglob("*.kicad_pcb")):
        if pcb_path.stat().st_size == 0:
            continue

        # Check version
        try:
            pcb_text = pcb_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not is_likely_parseable(pcb_text):
            continue
        pcb_ver = detect_kicad_version(pcb_text)
        if pcb_ver is None or pcb_ver < MIN_KICAD_VERSION:
            continue

        # Find matching schematic (same base name, same directory)
        sch_path = pcb_path.with_suffix(".kicad_sch")
        if not sch_path.exists() or sch_path.stat().st_size == 0:
            continue

        try:
            sch_text = sch_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not is_likely_parseable(sch_text):
            continue
        sch_ver = detect_kicad_version(sch_text)
        if sch_ver is None or sch_ver < MIN_KICAD_VERSION:
            continue

        pairs.append((sch_path, pcb_path))

    return pairs


def run_local_pipeline(
    staging_dir: Path,
    output_dir: Path | None = None,
) -> RealBoardDataset:
    """Ingest local KiCad files into a RealBoardDataset.

    Scans staging_dir for .kicad_pcb + .kicad_sch pairs, parses each into a
    board graph, deduplicates, quality-filters, and optionally writes
    train/val/test JSONL splits.

    No GitHub token or network access required — processes files already on disk.

    Args:
        staging_dir: Directory containing KiCad project subdirectories.
        output_dir: If provided, write train.jsonl, val.jsonl, test.jsonl
            splits to this directory.

    Returns:
        RealBoardDataset with metadata including discovery and filter counts.
    """
    staging_dir = Path(staging_dir)
    if not staging_dir.is_dir():
        raise FileNotFoundError(f"Staging directory not found: {staging_dir}")

    # 1. Find all valid PCB+SCH pairs
    file_pairs = _find_pcb_sch_pairs(staging_dir)
    n_discovered = len(file_pairs)
    logger.info("Found %d valid PCB+SCH pairs in %s", n_discovered, staging_dir)

    if n_discovered == 0:
        logger.warning("No valid file pairs found — check KiCad version (need v7+)")
        return RealBoardDataset(metadata={"n_discovered": 0, "difficulty_counts": {}})

    # 2. Parse each pair into a board graph
    raw_samples: list[RealBoardSample] = []
    n_parsed = 0
    n_failed = 0

    for idx, (sch_path, pcb_path) in enumerate(file_pairs):
        try:
            # Derive repo name from directory structure
            rel = pcb_path.relative_to(staging_dir)
            repo_name = str(rel.parts[0]) if len(rel.parts) > 1 else ""

            result = build_board_graph(
                sch_path=sch_path,
                pcb_path=pcb_path,
                sample_id=idx,
                repo_url="",
                repo_name=repo_name,
                sch_repo_path=str(rel.with_suffix(".kicad_sch")),
                pcb_repo_path=str(rel),
            )

            if result is None:
                n_failed += 1
                continue

            raw_samples.append(_graph_result_to_sample(result, idx))
            n_parsed += 1

        except Exception as e:
            logger.warning("Failed to parse %s: %s", pcb_path.name, e)
            n_failed += 1

    # 3. Dedup
    n_before_dedup = len(raw_samples)
    deduped = dedup_by_hash(raw_samples)
    n_deduped = len(deduped)

    # 4. Quality filter
    n_before_filter = len(deduped)
    filtered = filter_quality(deduped)
    n_filtered = len(filtered)

    # 5. Build dataset with metadata
    difficulty_counts = dict(Counter(s.difficulty for s in filtered))
    metadata = {
        "source": "local",
        "staging_dir": str(staging_dir),
        "n_discovered": n_discovered,
        "n_parsed": n_parsed,
        "n_failed": n_failed,
        "n_duplicates_removed": n_before_dedup - n_deduped,
        "n_quality_removed": n_before_filter - n_filtered,
        "difficulty_counts": difficulty_counts,
    }

    dataset = RealBoardDataset(samples=filtered, metadata=metadata)

    logger.info(
        "Local pipeline: %d discovered -> %d parsed -> %d deduped -> %d filtered",
        n_discovered, n_parsed, n_deduped, n_filtered,
    )

    # 6. Write JSONL splits if output_dir provided
    if output_dir is not None:
        output_dir = Path(output_dir)
        train_ds, val_ds, test_ds = dataset.split()
        n_train = train_ds.to_jsonl(output_dir / "train.jsonl")
        n_val = val_ds.to_jsonl(output_dir / "val.jsonl")
        n_test = test_ds.to_jsonl(output_dir / "test.jsonl")
        logger.info("Wrote splits to %s (train=%d, val=%d, test=%d)", output_dir, n_train, n_val, n_test)

    return dataset
