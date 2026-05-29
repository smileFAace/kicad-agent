"""Best-of-N chain selection with reward model scoring."""

from __future__ import annotations

from dataclasses import dataclass

from kicad_agent.training.reward_model import PredictedReward, predict_reward


@dataclass(frozen=True)
class ScoredChain:
    """A reasoning chain with reward model scores.

    Attributes:
        chain_text: The generated reasoning chain text.
        format_score: Predicted format correctness (0..1).
        quality_score: Predicted reasoning quality (0..1).
        accuracy_score: Predicted coordinate accuracy (0..1).
        composite_score: Mean of format/quality/accuracy scores.
        generation_time_s: Wall-clock time for this chain's generation.
    """

    chain_text: str
    format_score: float
    quality_score: float
    accuracy_score: float
    composite_score: float
    generation_time_s: float = 0.0


def best_of_n_select(
    chains: list[str],
    reward_model: object | None,
) -> ScoredChain:
    """Score N chains with reward model and return highest-scoring one.

    Args:
        chains: List of generated chain texts to score.
        reward_model: RewardModel instance (or None for no scoring).

    Returns:
        ScoredChain with highest composite score.

    Raises:
        ValueError: If chains list is empty or no valid chain found.
    """
    if not chains:
        raise ValueError("chains list must not be empty")

    if reward_model is None:
        return ScoredChain(
            chain_text=chains[0],
            format_score=0.5,
            quality_score=0.5,
            accuracy_score=0.5,
            composite_score=0.5,
        )

    best: ScoredChain | None = None
    best_composite = -1.0

    for chain_text in chains:
        pred: PredictedReward = predict_reward(reward_model, chain_text)
        composite = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0

        if composite > best_composite:
            best_composite = composite
            best = ScoredChain(
                chain_text=chain_text,
                format_score=pred.format_score,
                quality_score=pred.quality_score,
                accuracy_score=pred.accuracy_score,
                composite_score=composite,
            )

    # best is guaranteed non-None because chains is non-empty
    if best is None:
        raise ValueError("best_of_n_select: no valid chain found")
    return best
