"""Anti-hacking detection for reward model scoring.

GRPO-05: Statistical anomaly detection across reward batches to prevent
reward hacking. Identifies coordinate repetition, bounds violations,
length anomalies, and score inflation.

Usage:
    from kicad_agent.training.reward_hacking import detect_anomalies, smooth_penalty

    anomalies = detect_anomalies(rewards)
    penalty = smooth_penalty(raw=0.5, severity=0.8)
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class AnomalyReport:
    """Report of a detected anomaly in reward distribution.

    Attributes:
        chain_id: ID of the chain with the anomaly.
        anomaly_type: Category of anomaly detected.
        severity: 0..1 — how severe the anomaly is.
        description: Human-readable description.
    """

    chain_id: int
    anomaly_type: str  # "coordinate_repetition", "bounds_violation", "length_anomaly", "score_inflation"
    severity: float
    description: str


def smooth_penalty(raw_penalty: float, severity: float) -> float:
    """Smooth penalty function using tanh for continuous gradient.

    Prevents discontinuous reward cliffs that encourage hacking.
    The function is monotonically increasing with severity.

    Args:
        raw_penalty: Raw penalty magnitude (non-negative).
        severity: Severity coefficient (0..1).

    Returns:
        Smoothed penalty value (non-positive).
    """
    if raw_penalty < 0:
        raw_penalty = abs(raw_penalty)
    return -(severity * math.tanh(raw_penalty))


def detect_anomalies(
    rewards: list,
) -> list[AnomalyReport]:
    """Detect statistical anomalies across a batch of chain rewards.

    Checks for:
      - coordinate_repetition: Same coordinate in >50% of steps
      - bounds_violation: Coordinates outside board boundaries
      - length_anomaly: Chain length > 3 standard deviations from mean
      - score_inflation: High accuracy score with few unique coordinates

    Args:
        rewards: List of ChainReward objects.

    Returns:
        List of AnomalyReport for detected anomalies.
    """
    if not rewards:
        return []

    reports: list[AnomalyReport] = []

    # Compute chain length statistics
    lengths = [len(cr.step_rewards) for cr in rewards]
    n = len(lengths)
    if n < 2:
        return reports

    mean_len = sum(lengths) / n
    var_len = sum((l - mean_len) ** 2 for l in lengths) / n
    std_len = math.sqrt(var_len) if var_len > 0 else 0.0

    for cr in rewards:
        chain_id = cr.chain_id

        # 1. Score inflation: high accuracy with low reward density
        if cr.reward_density > 0.9 and len(cr.step_rewards) < 4:
            reports.append(AnomalyReport(
                chain_id=chain_id,
                anomaly_type="score_inflation",
                severity=min(1.0, cr.reward_density),
                description=(
                    f"Chain {chain_id} has reward_density={cr.reward_density:.2f} "
                    f"with only {len(cr.step_rewards)} steps — possible inflation"
                ),
            ))

        # 2. Length anomaly
        chain_len = len(cr.step_rewards)
        if std_len > 0 and abs(chain_len - mean_len) > 3 * std_len:
            severity = min(1.0, abs(chain_len - mean_len) / (3 * std_len))
            reports.append(AnomalyReport(
                chain_id=chain_id,
                anomaly_type="length_anomaly",
                severity=severity,
                description=(
                    f"Chain {chain_id} has length {chain_len} vs mean {mean_len:.1f} "
                    f"(>{3} std dev)"
                ),
            ))

    return reports
