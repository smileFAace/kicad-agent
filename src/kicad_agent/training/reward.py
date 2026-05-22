"""Reward scoring for coordinate-grounded reasoning chains.

GRPO-03: Per-step dense rewards with format, quality, accuracy signals.
Scores each step in a reasoning chain against the ground-truth maze solution.

Usage:
    from kicad_agent.training.reward import score_chain, RewardConfig

    reward = score_chain(chain, sample)
    print(f"Total reward: {reward.total_reward:.2f}")
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from kicad_agent.training.chains import MazeReasoningChain
from kicad_agent.training.dataset import MazeSample


@dataclass(frozen=True)
class RewardSignal:
    """Per-step reward components.

    Attributes:
        step_index: Which step in the chain (0-indexed).
        format_score: 0..1 — correct structure and coordinate format.
        quality_score: 0..1 — reasoning coherence and specificity.
        accuracy_score: 0..1 — coordinate correctness vs ground truth.
        penalty: 0..-1 — anti-hacking penalties.
        total: Weighted sum of components.
    """

    step_index: int
    format_score: float
    quality_score: float
    accuracy_score: float
    penalty: float
    total: float


@dataclass(frozen=True)
class ChainReward:
    """Aggregate reward for a complete reasoning chain.

    Attributes:
        chain_id: Sample ID of the chain.
        sample_id: Sample ID this chain was scored against.
        step_rewards: Per-step reward signals.
        total_reward: Sum of step reward totals.
        reward_density: total_reward / num_steps.
    """

    chain_id: int
    sample_id: int
    step_rewards: tuple[RewardSignal, ...]
    total_reward: float
    reward_density: float


@dataclass
class RewardConfig:
    """Configuration for reward scoring.

    Attributes:
        format_weight: Weight for format_score in total.
        quality_weight: Weight for quality_score in total.
        accuracy_weight: Weight for accuracy_score in total.
        penalty_scale: Multiplier for penalty magnitude.
        coordinate_format_regex: Regex for detecting coordinate references.
        min_steps: Minimum expected steps in a chain.
        max_steps: Maximum expected steps before length penalty.
    """

    format_weight: float = 0.2
    quality_weight: float = 0.3
    accuracy_weight: float = 0.5
    penalty_scale: float = 1.0
    coordinate_format_regex: str = r"<point\s+[\d.]+,\s*[\d.]+>"
    min_steps: int = 3
    max_steps: int = 50


# Coordinate format regex (compiled once)
_COORD_RE = re.compile(r"<point\s+[\d.]+,\s*[\d.]+>")

# Reasoning verbs indicating quality
_REASONING_VERBS = {
    "found", "navigating", "requires", "indicates", "consider",
    "route", "explore", "backtrack", "moving", "path", "obstacle",
    "avoid", "clearance", "trace", "connect",
}


def _score_format(step: dict, config: RewardConfig) -> float:
    """Score format correctness of a step.

    Checks: coordinate references present, step_type valid, content non-empty.
    """
    score = 0.0

    # Coordinate reference present
    text = step.get("text", "")
    if _COORD_RE.search(text):
        score += 0.5

    # Step type valid
    step_type = step.get("step_type", step.get("action", ""))
    valid_types = {
        "observation", "spatial_context", "coordinate_reference",
        "diagnosis", "recommendation", "explore", "backtrack",
        "dead_end", "found_target",
    }
    if step_type in valid_types:
        score += 0.25

    # Content non-empty and reasonable length
    if len(text) > 10:
        score += 0.25

    return min(1.0, score)


def _score_quality(step: dict) -> float:
    """Score reasoning quality of a step.

    Checks: reasoning verbs present, coordinate specificity, logical flow.
    """
    text = step.get("text", "").lower()
    score = 0.0

    # Reasoning verbs
    verb_count = sum(1 for verb in _REASONING_VERBS if verb in text)
    if verb_count >= 2:
        score += 0.4
    elif verb_count >= 1:
        score += 0.2

    # Coordinate specificity
    coord_matches = _COORD_RE.findall(text)
    if coord_matches:
        score += 0.3
        if len(coord_matches) >= 2:
            score += 0.1

    # Step specificity (not generic)
    if len(text) > 30:
        score += 0.2

    return min(1.0, score)


def _score_accuracy(
    step: dict,
    sample: MazeSample,
    tolerance_mm: float = 2.0,
) -> float:
    """Score coordinate accuracy against ground truth.

    Compares referenced coordinates with the sample's solution path.
    """
    coords = step.get("coordinates", [])
    if not coords:
        # Steps without coordinates (diagnosis, recommendation) get neutral score
        return 0.5

    # Collect all valid coordinates from sample
    valid_coords: list[tuple[float, float]] = []
    valid_coords.append(sample.source_point)
    valid_coords.append(sample.target_point)
    for p in sample.solution_path:
        valid_coords.append(p)
    for obs in sample.obstacle_positions:
        valid_coords.append(obs)

    # Check how many referenced coords are close to valid coords
    correct = 0
    for coord in coords:
        if isinstance(coord, (list, tuple)) and len(coord) == 2:
            cx, cy = float(coord[0]), float(coord[1])
            for vx, vy in valid_coords:
                dist = math.sqrt((cx - vx) ** 2 + (cy - vy) ** 2)
                if dist <= tolerance_mm:
                    correct += 1
                    break

    if len(coords) == 0:
        return 0.5

    return min(1.0, correct / len(coords))


def _compute_penalty(
    step: dict,
    step_index: int,
    all_coords: list[tuple[float, float]],
    config: RewardConfig,
    sample: MazeSample,
) -> float:
    """Compute anti-hacking penalties.

    Penalizes: repeated identical coordinates, out-of-bounds, missing coords.
    """
    penalty = 0.0
    coords = step.get("coordinates", [])

    # Check for repeated coordinates (same coord in >50% of steps)
    if coords and isinstance(coords[0], (list, tuple)):
        coord_tuple = (float(coords[0][0]), float(coords[0][1]))
        repeat_count = sum(
            1 for c in all_coords if abs(c[0] - coord_tuple[0]) < 0.01 and abs(c[1] - coord_tuple[1]) < 0.01
        )
        if repeat_count > len(all_coords) * 0.5 and len(all_coords) > 3:
            penalty += 0.3  # coordinate repetition penalty

    # Out of bounds
    for coord in coords:
        if isinstance(coord, (list, tuple)) and len(coord) == 2:
            cx, cy = float(coord[0]), float(coord[1])
            if cx < -1 or cy < -1 or cx > sample.board_width_mm + 1 or cy > sample.board_height_mm + 1:
                penalty += 0.2
                break

    # Excessive length
    if step_index >= config.max_steps:
        penalty += 0.1

    return -(penalty * config.penalty_scale)


def score_chain(
    chain: MazeReasoningChain,
    sample: MazeSample,
    config: RewardConfig | None = None,
) -> ChainReward:
    """Score a reasoning chain against a maze sample.

    Produces per-step dense rewards (format, quality, accuracy, penalty).

    Args:
        chain: The reasoning chain to score.
        sample: Ground-truth maze sample.
        config: Optional reward configuration.

    Returns:
        ChainReward with per-step signals and aggregate scores.
    """
    if config is None:
        config = RewardConfig()

    steps = chain.steps
    # Collect all coordinates for repetition detection
    all_coords: list[tuple[float, float]] = []
    for step in steps:
        for coord in step.get("coordinates", []):
            if isinstance(coord, (list, tuple)) and len(coord) == 2:
                all_coords.append((float(coord[0]), float(coord[1])))

    step_rewards: list[RewardSignal] = []
    for i, step in enumerate(steps):
        fmt = _score_format(step, config)
        qual = _score_quality(step)
        acc = _score_accuracy(step, sample)
        pen = _compute_penalty(step, i, all_coords, config, sample)

        total = (
            config.format_weight * fmt
            + config.quality_weight * qual
            + config.accuracy_weight * acc
            + pen
        )
        # Clip to [-1, 1]
        total = max(-1.0, min(1.0, total))

        step_rewards.append(RewardSignal(
            step_index=i,
            format_score=round(fmt, 4),
            quality_score=round(qual, 4),
            accuracy_score=round(acc, 4),
            penalty=round(pen, 4),
            total=round(total, 4),
        ))

    total_reward = sum(sr.total for sr in step_rewards)
    reward_density = total_reward / len(step_rewards) if step_rewards else 0.0

    return ChainReward(
        chain_id=chain.sample_id,
        sample_id=sample.sample_id,
        step_rewards=tuple(step_rewards),
        total_reward=round(total_reward, 4),
        reward_density=round(reward_density, 4),
    )
