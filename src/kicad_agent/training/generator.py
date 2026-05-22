"""Parallel maze sample generation engine.

Extends dataset generation with multi-worker parallel execution and
adversarial sample generation tuned for high difficulty.

Usage:
    from kicad_agent.training.generator import generate_samples_parallel

    ds = generate_samples_parallel(n_samples=1000, n_workers=4)
"""

from __future__ import annotations

import logging
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from kicad_agent.training.dataset import (
    DEFAULT_BOARD_CONFIGS,
    MazeDataset,
    MazeSample,
    _grade_difficulty,
)

logger = logging.getLogger(__name__)

# Adversarial board configs: larger boards, higher obstacle density
ADVERSARIAL_CONFIGS: list[dict] = [
    {"width_mm": 80.0, "height_mm": 80.0, "grid_size_mm": 3.0},
    {"width_mm": 100.0, "height_mm": 80.0, "grid_size_mm": 3.0},
    {"width_mm": 100.0, "height_mm": 100.0, "grid_size_mm": 4.0},
    {"width_mm": 120.0, "height_mm": 90.0, "grid_size_mm": 3.0},
    {"width_mm": 90.0, "height_mm": 90.0, "grid_size_mm": 3.0},
]


def _generate_chunk(
    chunk_id: int,
    n_samples: int,
    seed_offset: int,
    board_configs: list[dict],
) -> list[dict]:
    """Generate a chunk of samples in a subprocess.

    Returns list of dicts (not MazeSample) to avoid pickling frozen dataclasses.
    """
    import hashlib

    from kicad_agent.spatial.maze_generator import generate_maze_board

    results: list[dict] = []

    with tempfile.TemporaryDirectory(prefix=f"maze_chunk_{chunk_id}_") as tmpdir:
        for i in range(n_samples):
            global_idx = chunk_id * n_samples + i
            config = board_configs[global_idx % len(board_configs)]
            seed = seed_offset + global_idx

            try:
                pcb_path = Path(tmpdir) / f"maze_{i}.kicad_pcb"
                maze = generate_maze_board(
                    output_path=pcb_path,
                    width_mm=config["width_mm"],
                    height_mm=config["height_mm"],
                    grid_size_mm=config["grid_size_mm"],
                    seed=seed,
                )

                board_content = pcb_path.read_text()
                board_hash = hashlib.sha256(board_content.encode()).hexdigest()

                total_cells = int(
                    maze.board_width_mm / config["grid_size_mm"]
                ) * int(maze.board_height_mm / config["grid_size_mm"])
                difficulty = _grade_difficulty(
                    solution_length=len(maze.solution_path),
                    obstacle_count=len(maze.obstacles),
                    total_cells=total_cells,
                )

                results.append({
                    "sample_id": global_idx,
                    "seed": seed,
                    "board_width_mm": maze.board_width_mm,
                    "board_height_mm": maze.board_height_mm,
                    "grid_size_mm": config["grid_size_mm"],
                    "obstacle_count": len(maze.obstacles),
                    "obstacle_positions": tuple(
                        (round((b.x1 + b.x2) / 2, 2), round((b.y1 + b.y2) / 2, 2))
                        for b in maze.obstacles
                    ),
                    "source_point": (maze.source_point.x, maze.source_point.y),
                    "target_point": (maze.target_point.x, maze.target_point.y),
                    "solution_path": maze.solution_path,
                    "solution_length": len(maze.solution_path),
                    "difficulty": difficulty,
                    "board_hash": board_hash,
                })

            except Exception as e:
                logger.warning("Chunk %d sample %d failed: %s", chunk_id, i, e)

    return results


def generate_samples_parallel(
    n_samples: int = 100_000,
    n_workers: int = 4,
    seed_base: int = 42,
    board_configs: list[dict] | None = None,
) -> MazeDataset:
    """Generate maze samples using parallel workers.

    Distributes generation across n_workers processes. Each worker generates
    a chunk of samples with unique seed ranges to avoid overlap.

    Args:
        n_samples: Total number of samples to generate.
        n_workers: Number of parallel worker processes.
        seed_base: Base seed for deterministic generation.
        board_configs: Board configurations to cycle through.

    Returns:
        MazeDataset with all generated samples, deduplicated.
    """
    if board_configs is None:
        board_configs = DEFAULT_BOARD_CONFIGS

    chunk_size = max(1, n_samples // n_workers)
    seen_hashes: set[str] = set()
    all_samples: list[MazeSample] = []

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = []
        for worker_id in range(n_workers):
            start = worker_id * chunk_size
            end = min(start + chunk_size, n_samples)
            if start >= n_samples:
                break
            actual_chunk_size = end - start
            futures.append(
                executor.submit(
                    _generate_chunk,
                    chunk_id=worker_id,
                    n_samples=actual_chunk_size,
                    seed_offset=seed_base,
                    board_configs=board_configs,
                )
            )

        for future in futures:
            chunk_results = future.result()
            for d in chunk_results:
                if d["board_hash"] in seen_hashes:
                    continue
                seen_hashes.add(d["board_hash"])

                sample = MazeSample(
                    sample_id=len(all_samples),
                    seed=d["seed"],
                    board_width_mm=d["board_width_mm"],
                    board_height_mm=d["board_height_mm"],
                    grid_size_mm=d["grid_size_mm"],
                    obstacle_count=d["obstacle_count"],
                    obstacle_positions=d["obstacle_positions"],
                    source_point=d["source_point"],
                    target_point=d["target_point"],
                    solution_path=d["solution_path"],
                    solution_length=d["solution_length"],
                    difficulty=d["difficulty"],
                    board_hash=d["board_hash"],
                )
                all_samples.append(sample)

    from collections import Counter

    metadata = {
        "n_requested": n_samples,
        "n_generated": len(all_samples),
        "n_workers": n_workers,
        "seed_base": seed_base,
        "difficulty_counts": dict(Counter(s.difficulty for s in all_samples)),
    }

    return MazeDataset(samples=all_samples, metadata=metadata)


def generate_adversarial_samples(
    n_samples: int = 10_000,
    seed_base: int = 999_999,
) -> MazeDataset:
    """Generate adversarial samples tuned for high difficulty.

    Uses larger boards with higher obstacle density to produce
    primarily hard and adversarial difficulty samples.

    Args:
        n_samples: Number of adversarial samples to generate.
        seed_base: Base seed for deterministic generation.

    Returns:
        MazeDataset with high-difficulty samples.
    """
    return generate_samples_parallel(
        n_samples=n_samples,
        n_workers=min(4, max(1, n_samples // 10)),
        seed_base=seed_base,
        board_configs=ADVERSARIAL_CONFIGS,
    )
