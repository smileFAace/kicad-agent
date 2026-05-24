"""Placement training infrastructure: dataset, reward, and trainer.

Provides synthetic placement data generation, spatial reward computation,
and GRPO-based training for the PlacementModel.

Usage::

    from kicad_agent.placement.training import (
        PlacementSample,
        PlacementDataset,
        placement_reward,
        compute_placement_loss,
        PlacementTrainer,
        PlacementTrainConfig,
    )
"""

from kicad_agent.placement.training.dataset import (
    PlacementDataset,
    PlacementSample,
)
from kicad_agent.placement.training.reward import (
    compute_placement_loss,
    placement_reward,
)
from kicad_agent.placement.training.train import (
    PlacementTrainConfig,
    PlacementTrainer,
)

__all__ = [
    "PlacementSample",
    "PlacementDataset",
    "placement_reward",
    "compute_placement_loss",
    "PlacementTrainer",
    "PlacementTrainConfig",
]
