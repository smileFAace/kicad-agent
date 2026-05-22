"""Batch chain writing to JSONL for large-scale training data.

Streams chains to disk one at a time to avoid memory exhaustion on
large datasets (100k+ samples).

Usage:
    from kicad_agent.training.chain_writer import build_training_chains

    count = build_training_chains(dataset, Path("chains.jsonl"), chain_type="solution")
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from kicad_agent.training.chains import (
    MazeReasoningChain,
    synthesize_exploration_chain,
    synthesize_maze_chain,
)
from kicad_agent.training.dataset import MazeDataset

logger = logging.getLogger(__name__)


def _chain_to_dict(chain: MazeReasoningChain) -> dict:
    """Convert MazeReasoningChain to JSON-serializable dict."""
    return {
        "sample_id": chain.sample_id,
        "difficulty": chain.difficulty,
        "chain_text": chain.chain_text,
        "steps": list(chain.steps),
        "coordinates_referenced": list(chain.coordinates_referenced),
        "is_correct": chain.is_correct,
        "exploration_branches": chain.exploration_branches,
    }


def write_chains_jsonl(
    chains: list[MazeReasoningChain],
    path: Path,
) -> int:
    """Write a list of chains as JSONL (one JSON object per line).

    Args:
        chains: List of MazeReasoningChain objects.
        path: Output file path.

    Returns:
        Number of chains written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w") as f:
        for chain in chains:
            f.write(json.dumps(_chain_to_dict(chain)) + "\n")
            count += 1
    return count


def build_training_chains(
    dataset: MazeDataset,
    output_path: Path,
    chain_type: str = "solution",
) -> int:
    """Generate chains for all samples and stream to JSONL.

    Processes samples one at a time and writes immediately to avoid
    accumulating all chains in memory.

    Args:
        dataset: MazeDataset with samples to process.
        output_path: Where to write the JSONL file.
        chain_type: "solution" for 5-step chains, "exploration" for DFS chains,
            "both" for both types per sample (doubles the output).

    Returns:
        Number of chains written.

    Raises:
        ValueError: If chain_type is not one of "solution", "exploration", "both".
    """
    if chain_type not in ("solution", "exploration", "both"):
        raise ValueError(
            f"chain_type must be 'solution', 'exploration', or 'both', got '{chain_type}'"
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with open(output_path, "w") as f:
        for sample in dataset.samples:
            try:
                if chain_type in ("solution", "both"):
                    chain = synthesize_maze_chain(sample)
                    f.write(json.dumps(_chain_to_dict(chain)) + "\n")
                    count += 1

                if chain_type in ("exploration", "both"):
                    chain = synthesize_exploration_chain(sample)
                    f.write(json.dumps(_chain_to_dict(chain)) + "\n")
                    count += 1

            except Exception as e:
                logger.warning(
                    "Failed to synthesize chain for sample %d: %s",
                    sample.sample_id,
                    e,
                )

    return count
