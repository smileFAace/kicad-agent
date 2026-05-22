"""Synthetic PCB maze-routing dataset for GRPO training.

GRPO-01: Generates 100k+ samples from the Phase 8 maze generator with
verified BFS solutions and difficulty grading (easy/medium/hard/adversarial).

Each sample captures a complete maze-routing puzzle with ground-truth solution,
spatial metadata, and a deterministic seed for reproducibility.

Usage:
    from kicad_agent.training.dataset import generate_dataset, MazeDataset

    ds = generate_dataset(n_samples=100, seed_base=42)
    ds.to_jsonl(Path("training_data.jsonl"))
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from kicad_agent.spatial.maze_generator import generate_maze_board

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety limits (T-09-01)
# ---------------------------------------------------------------------------

_MAX_SAMPLES = 1_000_000  # prevents disk exhaustion


# ---------------------------------------------------------------------------
# Difficulty grading
# ---------------------------------------------------------------------------


def _grade_difficulty(
    solution_length: int,
    obstacle_count: int,
    total_cells: int,
) -> str:
    """Grade maze difficulty based on solution length and obstacle density.

    Args:
        solution_length: Number of cells in BFS solution path.
        obstacle_count: Number of obstacle cells in the grid.
        total_cells: Total grid cells (rows * cols).

    Returns:
        One of "easy", "medium", "hard", "adversarial".
    """
    density = obstacle_count / total_cells if total_cells > 0 else 0.0

    if solution_length <= 5 and density < 0.30:
        return "easy"
    if solution_length <= 15 or density < 0.50:
        return "medium"
    if solution_length <= 30 or density < 0.70:
        return "hard"
    return "adversarial"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MazeSample:
    """A single maze-routing puzzle with verified BFS solution.

    Attributes:
        sample_id: Sequential index in dataset.
        seed: Random seed for reproducible regeneration.
        board_width_mm: Board width in millimeters.
        board_height_mm: Board height in millimeters.
        grid_size_mm: Grid cell size in millimeters.
        obstacle_count: Number of obstacle cells.
        obstacle_positions: Center coordinates of obstacles in mm.
        source_point: Source via position as (x, y) in mm.
        target_point: Target via position as (x, y) in mm.
        solution_path: BFS-verified solution as ordered (x, y) coordinates.
        solution_length: Number of steps in solution path.
        difficulty: "easy", "medium", "hard", or "adversarial".
        board_hash: SHA256 hex digest of board content for dedup.
    """

    sample_id: int
    seed: int
    board_width_mm: float
    board_height_mm: float
    grid_size_mm: float
    obstacle_count: int
    obstacle_positions: tuple[tuple[float, float], ...]
    source_point: tuple[float, float]
    target_point: tuple[float, float]
    solution_path: tuple[tuple[float, float], ...]
    solution_length: int
    difficulty: str
    board_hash: str


@dataclass
class MazeDataset:
    """Collection of maze-routing samples with metadata.

    Attributes:
        samples: Ordered list of MazeSample objects.
        metadata: Generation metadata (timestamp, config, difficulty counts).
    """

    samples: list[MazeSample] = field(default_factory=list)
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
    def from_jsonl(path: Path) -> MazeDataset:
        """Load samples from a JSONL file.

        Args:
            path: Input JSONL file path.

        Returns:
            MazeDataset with loaded samples.
        """
        path = Path(path)
        samples: list[MazeSample] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    samples.append(_dict_to_sample(json.loads(line)))
        return MazeDataset(samples=samples)

    def split(
        self,
        train: float = 0.8,
        val: float = 0.1,
        test: float = 0.1,
    ) -> tuple[MazeDataset, MazeDataset, MazeDataset]:
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
        train_end = int(n * train)
        val_end = train_end + int(n * val)

        return (
            MazeDataset(samples=self.samples[:train_end]),
            MazeDataset(samples=self.samples[train_end:val_end]),
            MazeDataset(samples=self.samples[val_end:]),
        )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _sample_to_dict(s: MazeSample) -> dict:
    """Convert MazeSample to a JSON-serializable dict."""
    return {
        "sample_id": s.sample_id,
        "seed": s.seed,
        "board_width_mm": s.board_width_mm,
        "board_height_mm": s.board_height_mm,
        "grid_size_mm": s.grid_size_mm,
        "obstacle_count": s.obstacle_count,
        "obstacle_positions": list(s.obstacle_positions),
        "source_point": list(s.source_point),
        "target_point": list(s.target_point),
        "solution_path": list(s.solution_path),
        "solution_length": s.solution_length,
        "difficulty": s.difficulty,
        "board_hash": s.board_hash,
    }


def _dict_to_sample(d: dict) -> MazeSample:
    """Convert a dict back to MazeSample."""
    return MazeSample(
        sample_id=d["sample_id"],
        seed=d["seed"],
        board_width_mm=d["board_width_mm"],
        board_height_mm=d["board_height_mm"],
        grid_size_mm=d["grid_size_mm"],
        obstacle_count=d["obstacle_count"],
        obstacle_positions=tuple(tuple(p) for p in d["obstacle_positions"]),
        source_point=tuple(d["source_point"]),
        target_point=tuple(d["target_point"]),
        solution_path=tuple(tuple(p) for p in d["solution_path"]),
        solution_length=d["solution_length"],
        difficulty=d["difficulty"],
        board_hash=d["board_hash"],
    )


# ---------------------------------------------------------------------------
# Default board configurations for dataset diversity
# ---------------------------------------------------------------------------

DEFAULT_BOARD_CONFIGS: list[dict] = [
    {"width_mm": 30.0, "height_mm": 30.0, "grid_size_mm": 5.0},
    {"width_mm": 50.0, "height_mm": 50.0, "grid_size_mm": 5.0},
    {"width_mm": 50.0, "height_mm": 50.0, "grid_size_mm": 7.0},
    {"width_mm": 80.0, "height_mm": 60.0, "grid_size_mm": 5.0},
    {"width_mm": 80.0, "height_mm": 60.0, "grid_size_mm": 3.0},
    {"width_mm": 40.0, "height_mm": 40.0, "grid_size_mm": 4.0},
    {"width_mm": 60.0, "height_mm": 60.0, "grid_size_mm": 6.0},
]


# ---------------------------------------------------------------------------
# Dataset generation
# ---------------------------------------------------------------------------


def generate_dataset(
    n_samples: int = 100_000,
    seed_base: int = 42,
    board_configs: list[dict] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> MazeDataset:
    """Generate a dataset of maze-routing samples with verified solutions.

    Uses the Phase 8 maze generator under the hood. Each sample gets a unique
    seed derived from seed_base + sample_index. Board configs are cycled to
    create diversity.

    Args:
        n_samples: Number of samples to generate (1..1M).
        seed_base: Base random seed for deterministic generation.
        board_configs: List of board configuration dicts with keys
            width_mm, height_mm, grid_size_mm. Defaults to DEFAULT_BOARD_CONFIGS.
        progress_callback: Optional callback(progress, total) for logging.

    Returns:
        MazeDataset with graded samples.

    Raises:
        ValueError: If n_samples is out of bounds.
    """
    if n_samples < 1:
        raise ValueError(f"n_samples must be >= 1, got {n_samples}")
    if n_samples > _MAX_SAMPLES:
        raise ValueError(f"n_samples must be <= {_MAX_SAMPLES}, got {n_samples}")

    if board_configs is None:
        board_configs = DEFAULT_BOARD_CONFIGS

    seen_hashes: set[str] = set()
    samples: list[MazeSample] = []
    failed_count = 0

    with tempfile.TemporaryDirectory(prefix="maze_gen_") as tmpdir:
        for i in range(n_samples):
            config = board_configs[i % len(board_configs)]
            seed = seed_base + i

            try:
                pcb_path = Path(tmpdir) / f"maze_{i}.kicad_pcb"
                maze = generate_maze_board(
                    output_path=pcb_path,
                    width_mm=config["width_mm"],
                    height_mm=config["height_mm"],
                    grid_size_mm=config["grid_size_mm"],
                    seed=seed,
                )

                # Compute board hash for dedup
                board_content = pcb_path.read_text()
                board_hash = hashlib.sha256(board_content.encode()).hexdigest()

                # Skip duplicates
                if board_hash in seen_hashes:
                    continue
                seen_hashes.add(board_hash)

                # Compute difficulty
                total_cells = int(
                    maze.board_width_mm / config["grid_size_mm"]
                ) * int(maze.board_height_mm / config["grid_size_mm"])
                difficulty = _grade_difficulty(
                    solution_length=len(maze.solution_path),
                    obstacle_count=len(maze.obstacles),
                    total_cells=total_cells,
                )

                sample = MazeSample(
                    sample_id=len(samples),
                    seed=seed,
                    board_width_mm=maze.board_width_mm,
                    board_height_mm=maze.board_height_mm,
                    grid_size_mm=config["grid_size_mm"],
                    obstacle_count=len(maze.obstacles),
                    obstacle_positions=tuple(
                        (round((b.x1 + b.x2) / 2, 2), round((b.y1 + b.y2) / 2, 2))
                        for b in maze.obstacles
                    ),
                    source_point=(maze.source_point.x, maze.source_point.y),
                    target_point=(maze.target_point.x, maze.target_point.y),
                    solution_path=maze.solution_path,
                    solution_length=len(maze.solution_path),
                    difficulty=difficulty,
                    board_hash=board_hash,
                )
                samples.append(sample)

            except Exception as e:
                # T-09-02: Log and skip errors
                logger.warning("Failed to generate sample %d (seed %d): %s", i, seed, e)
                failed_count += 1

            if progress_callback and (i + 1) % 100 == 0:
                progress_callback(i + 1, n_samples)

    metadata = {
        "n_requested": n_samples,
        "n_generated": len(samples),
        "n_failed": failed_count,
        "n_duplicates_skipped": n_samples - len(samples) - failed_count,
        "seed_base": seed_base,
        "difficulty_counts": dict(Counter(s.difficulty for s in samples)),
    }

    return MazeDataset(samples=samples, metadata=metadata)
