"""Placement training loop extending GRPO training for placement model.

Uses group-relative advantages with spatial reward signals to optimize
the PlacementModel. Each training step generates multiple placement
hypotheses, scores them, and updates via advantage-weighted gradients.

Usage::

    from kicad_agent.placement.training.train import PlacementTrainer, PlacementTrainConfig

    trainer = PlacementTrainer(model, config)
    history = trainer.train(dataset)
"""

from __future__ import annotations

import copy
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PlacementTrainConfig:
    """Configuration for placement model training.

    Attributes:
        n_epochs: Number of training epochs.
        batch_size: Samples per training step.
        learning_rate: AdamW learning rate.
        group_size: Predictions per sample for group comparison.
        seed: Deterministic random seed.
        checkpoint_dir: Directory for saving model checkpoints.
    """

    n_epochs: int = 1
    batch_size: int = 4
    learning_rate: float = 1e-4
    group_size: int = 4
    seed: int = 42
    checkpoint_dir: str = "checkpoints/placement/"


class PlacementTrainer:
    """GRPO-based trainer for the PlacementModel.

    Generates groups of placement predictions, scores them with
    placement_reward, computes group-relative advantages, and
    updates model weights via advantage-weighted gradient descent.

    Args:
        model: PlacementModel to train.
        config: Training configuration.
    """

    def __init__(
        self,
        model: Any,
        config: PlacementTrainConfig | None = None,
    ) -> None:
        import torch

        self._model = model
        self._config = config or PlacementTrainConfig()
        self._torch = torch

        # Create frozen reference model for KL penalty
        self._ref_model = copy.deepcopy(model)
        for param in self._ref_model.parameters():
            param.requires_grad = False

    def train(self, dataset: Any) -> dict:
        """Run training loop over the dataset.

        For each epoch, iterates over the dataset in batches:
        1. Build PlacementGraph from sample data
        2. Generate group_size predictions with different noise
        3. Score each prediction with placement_reward (non-differentiable)
        4. Compute group-relative advantages from rewards
        5. Backpropagate using differentiable model output as surrogate loss

        Args:
            dataset: PlacementDataset with training samples.

        Returns:
            Training history dict with per-step metrics.
        """
        import torch

        from kicad_agent.generation.intent import ComponentSpec, NetSpec
        from kicad_agent.placement.graph import PlacementGraph, netlist_to_placement_graph
        from kicad_agent.placement.training.dataset import PlacementDataset
        from kicad_agent.training.grpo import GRPOTrainer

        if not isinstance(dataset, PlacementDataset):
            raise TypeError("dataset must be a PlacementDataset")

        optimizer = torch.optim.AdamW(
            self._model.parameters(),
            lr=self._config.learning_rate,
        )

        history: dict[str, list[float]] = {
            "losses": [],
            "reward_means": [],
            "hpwls": [],
        }

        grpo = GRPOTrainer(
            policy_model=self._model,
            reward_model=None,
            ref_model=self._ref_model,
        )

        samples = dataset.samples
        n_samples = len(samples)

        for epoch in range(self._config.n_epochs):
            for i in range(0, n_samples, self._config.batch_size):
                batch = samples[i : i + self._config.batch_size]
                if not batch:
                    continue

                optimizer.zero_grad()
                batch_losses: list[torch.Tensor] = []
                batch_reward_sum = 0.0
                batch_count = 0

                for sample in batch:
                    # Deserialize
                    components = [
                        ComponentSpec(**cd)
                        for cd in json.loads(sample.components_json)
                    ]
                    nets = [
                        NetSpec(**nd)
                        for nd in json.loads(sample.nets_json)
                    ]
                    ref_positions_raw = json.loads(sample.optimal_positions_json)
                    reference_positions = {
                        ref: tuple(pos) for ref, pos in ref_positions_raw.items()
                    }
                    board_w = sample.board_width
                    board_h = sample.board_height

                    graph = netlist_to_placement_graph(
                        components, nets, board_w, board_h
                    )
                    pg = PlacementGraph(graph)

                    # Generate group: forward passes with noise for diversity
                    group_rewards: list[float] = []
                    group_energies: list[torch.Tensor] = []

                    for g in range(self._config.group_size):
                        reward, energy = self._forward_and_score(
                            self._model, pg, board_w, board_h,
                            reference_positions,
                            noise_scale=0.1,
                        )
                        group_rewards.append(reward)
                        group_energies.append(energy)

                    # Group-relative advantages
                    advantages = grpo.compute_group_advantages(
                        [group_rewards]
                    )[0]

                    # Differentiable loss: advantage-weighted negative energy
                    # Accumulate weighted energies directly to preserve grad graph
                    sample_loss_parts: list[torch.Tensor] = []
                    for adv, energy in zip(advantages, group_energies):
                        sample_loss_parts.append(-adv * energy)

                    if sample_loss_parts:
                        sample_loss = torch.stack(sample_loss_parts).mean()
                        batch_losses.append(sample_loss)

                    batch_reward_sum += sum(group_rewards) / max(len(group_rewards), 1)
                    batch_count += 1

                if batch_count > 0 and batch_losses:
                    batch_loss = torch.stack(batch_losses).mean()

                    # Backpropagate
                    batch_loss.backward()
                    torch.nn.utils.clip_grad_norm_(
                        self._model.parameters(), 1.0
                    )
                    optimizer.step()

                    loss_val = batch_loss.item()
                    history["losses"].append(loss_val)
                    history["reward_means"].append(
                        batch_reward_sum / batch_count
                    )
                    history["hpwls"].append(0.0)

                logger.info(
                    "Epoch %d/%d step %d: loss=%.4f, reward=%.3f",
                    epoch + 1, self._config.n_epochs,
                    len(history["losses"]),
                    history["losses"][-1] if history["losses"] else 0.0,
                    history["reward_means"][-1] if history["reward_means"] else 0.0,
                )

        return history

    def _forward_and_score(
        self,
        model: Any,
        graph: Any,
        board_w: float,
        board_h: float,
        reference_positions: dict[str, tuple[float, float, float]],
        noise_scale: float = 0.0,
    ) -> tuple[float, Any]:
        """Run model forward pass and compute reward + differentiable energy.

        The reward is a non-differentiable scalar for advantage computation.
        The energy is a differentiable tensor from the model output for
        gradient-based optimization.

        Args:
            model: PlacementModel for prediction.
            graph: PlacementGraph with features.
            board_w: Board width in mm.
            board_h: Board height in mm.
            reference_positions: Ground truth for reward computation.
            noise_scale: Std dev of noise added to features.

        Returns:
            (reward, energy) tuple. reward is a Python float,
            energy is a differentiable torch.Tensor.
        """
        import torch

        from kicad_agent.placement.training.reward import placement_reward

        # Extract features
        comp_features = graph.get_component_features(board_w, board_h)
        net_features = graph.get_net_features()
        adj_matrix = graph.get_adjacency_matrix()

        comp_t = torch.tensor(
            comp_features, dtype=torch.float32
        ).unsqueeze(0)
        net_t = torch.tensor(
            net_features, dtype=torch.float32
        ).unsqueeze(0)
        adj_t = torch.tensor(
            adj_matrix, dtype=torch.float32
        ).unsqueeze(0)
        bw_t = torch.tensor([board_w], dtype=torch.float32)
        bh_t = torch.tensor([board_h], dtype=torch.float32)

        # Add noise for group diversity (no gradient through noise)
        if noise_scale > 0:
            with torch.no_grad():
                noise = torch.randn_like(comp_t) * noise_scale
            comp_t = comp_t + noise

        # Forward pass -- keeps gradient graph
        output = model(comp_t, net_t, adj_t, bw_t, bh_t)

        # Compute non-differentiable reward from detached output
        with torch.no_grad():
            raw = output.squeeze(0).numpy()
            comp_refs = graph.component_nodes()
            ref_names = [nid.replace("comp:", "", 1) for nid in comp_refs]

            positions: dict[str, tuple[float, float, float]] = {}
            for idx, ref in enumerate(ref_names):
                positions[ref] = (
                    float(raw[idx, 0]),
                    float(raw[idx, 1]),
                    float(raw[idx, 2]),
                )

            reward = placement_reward(
                positions, reference_positions, graph, board_w, board_h
            )

        # Differentiable energy: negative mean squared output
        # Acts as surrogate -- higher energy = more confident placement
        energy = -output.pow(2).mean()

        return reward, energy
