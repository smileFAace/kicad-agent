"""Tests for placement training infrastructure.

Tests cover:
- PlacementSample serialization round-trip
- PlacementDataset JSONL I/O
- Synthetic data generation with SA targets
- HPWL, overlap, edge penalty, and composite loss computation
- GRPO placement reward function
- PlacementTrainer single-step training
- Dataset sample cap enforcement
"""

import json
import math
import tempfile
from pathlib import Path

import pytest

from kicad_agent.generation.intent import ComponentSpec, NetSpec
from kicad_agent.placement.graph import PlacementGraph, netlist_to_placement_graph
from kicad_agent.placement.training.dataset import (
    PlacementDataset,
    PlacementSample,
    generate_placement_samples,
)
from kicad_agent.placement.training.reward import (
    compute_edge_penalty,
    compute_hpwl,
    compute_overlap_area,
    compute_placement_loss,
    placement_reward,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_components():
    """Three components for reward testing."""
    return [
        ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
        ComponentSpec(library_id="Device:C_Small", reference="C1", value="100nF"),
        ComponentSpec(library_id="MCU_ST:STM32F103", reference="U1", value="STM32"),
    ]


@pytest.fixture
def sample_nets():
    """Two nets connecting the components."""
    return [
        NetSpec(name="SDA", pins=["R1.1", "U1.3"]),
        NetSpec(name="GND", pins=["U1.5", "C1.2", "R1.2"]),
    ]


@pytest.fixture
def placement_graph(sample_components, sample_nets):
    """PlacementGraph for reward tests."""
    graph = netlist_to_placement_graph(
        sample_components, sample_nets, board_width=100.0, board_height=80.0
    )
    return PlacementGraph(graph)


@pytest.fixture
def well_placed_positions():
    """Good positions spread across the board."""
    return {
        "R1": (20.0, 20.0, 0.0),
        "C1": (80.0, 60.0, 0.0),
        "U1": (50.0, 40.0, 0.0),
    }


# ---------------------------------------------------------------------------
# Dataset tests
# ---------------------------------------------------------------------------


class TestPlacementSample:
    """Tests for PlacementSample serialization."""

    def test_placement_sample_serialization(self):
        """Round-trip through to_dict/from_dict preserves fields."""
        sample = PlacementSample(
            sample_id=1,
            board_width=100.0,
            board_height=80.0,
            n_components=5,
            components_json='[{"reference":"R1"}]',
            nets_json='[{"name":"SDA"}]',
            optimal_positions_json='{"R1":[20.0,30.0,0.0]}',
            difficulty="easy",
            board_hash="abc123",
        )

        d = sample.to_dict()
        restored = PlacementSample.from_dict(d)

        assert restored.sample_id == 1
        assert restored.board_width == 100.0
        assert restored.board_height == 80.0
        assert restored.n_components == 5
        assert restored.components_json == '[{"reference":"R1"}]'
        assert restored.nets_json == '[{"name":"SDA"}]'
        assert restored.optimal_positions_json == '{"R1":[20.0,30.0,0.0]}'
        assert restored.difficulty == "easy"
        assert restored.board_hash == "abc123"


class TestPlacementDataset:
    """Tests for PlacementDataset JSONL I/O."""

    def test_placement_dataset_jsonl(self, tmp_path):
        """Write 3 samples to JSONL, read back, verify count."""
        samples = [
            PlacementSample(
                sample_id=i,
                board_width=100.0,
                board_height=80.0,
                n_components=3 + i,
                components_json="[]",
                nets_json="[]",
                optimal_positions_json="{}",
                difficulty="easy",
                board_hash=f"hash_{i}",
            )
            for i in range(3)
        ]
        dataset = PlacementDataset(samples=samples)

        jsonl_path = tmp_path / "test.jsonl"
        count = dataset.to_jsonl(jsonl_path)
        assert count == 3

        loaded = PlacementDataset.from_jsonl(jsonl_path)
        assert len(loaded) == 3
        assert loaded.samples[0].sample_id == 0
        assert loaded.samples[2].sample_id == 2

    def test_placement_dataset_len(self):
        """Dataset __len__ returns sample count."""
        ds = PlacementDataset(samples=[
            PlacementSample(0, 100, 80, 1, "[]", "[]", "{}", "easy", "h"),
            PlacementSample(1, 100, 80, 2, "[]", "[]", "{}", "medium", "h"),
        ])
        assert len(ds) == 2


class TestSampleGeneration:
    """Tests for synthetic sample generation."""

    def test_generate_placement_samples(self):
        """Generate 5 samples, verify structure."""
        dataset = generate_placement_samples(
            n_samples=5, board_width=100.0, board_height=80.0, seed_base=42
        )
        assert len(dataset) == 5

        for sample in dataset.samples:
            assert sample.board_width == 100.0
            assert sample.board_height == 80.0
            assert sample.n_components >= 3

            # components_json is valid JSON
            comps = json.loads(sample.components_json)
            assert isinstance(comps, list)
            assert len(comps) == sample.n_components

            # nets_json is valid JSON
            nets = json.loads(sample.nets_json)
            assert isinstance(nets, list)

            # optimal_positions_json is valid JSON
            positions = json.loads(sample.optimal_positions_json)
            assert isinstance(positions, dict)

            assert sample.difficulty in ("easy", "medium", "hard")
            assert len(sample.board_hash) == 64  # SHA256 hex

    def test_dataset_cap(self):
        """Attempting > 100,000 samples raises ValueError."""
        with pytest.raises(ValueError, match="100000"):
            generate_placement_samples(
                n_samples=100_001, board_width=100.0, board_height=80.0
            )


# ---------------------------------------------------------------------------
# Reward tests
# ---------------------------------------------------------------------------


class TestHPWL:
    """Tests for HPWL computation."""

    def test_compute_hpwl(self, placement_graph):
        """Known positions on 100x80 board, verify HPWL matches manual calc."""
        # R1 at (10, 10), C1 at (90, 70), U1 at (50, 40)
        positions = {
            "R1": (10.0, 10.0, 0.0),
            "C1": (90.0, 70.0, 0.0),
            "U1": (50.0, 40.0, 0.0),
        }

        # Net SDA: R1 + U1 -> BB = (10,10)-(50,40) -> HPWL = 40 + 30 = 70
        # Net GND: U1 + C1 + R1 -> BB = (10,10)-(90,70) -> HPWL = 80 + 60 = 140
        # Total = 70 + 140 = 210
        hpwl = compute_hpwl(positions, placement_graph)
        assert abs(hpwl - 210.0) < 1.0

    def test_compute_hpwl_zero_net(self):
        """No nets -> HPWL is 0.0."""
        # Build graph with no nets
        components = [
            ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
        ]
        graph = netlist_to_placement_graph(components, [], 100.0, 80.0)
        pg = PlacementGraph(graph)

        positions = {"R1": (50.0, 40.0, 0.0)}
        assert compute_hpwl(positions, pg) == 0.0


class TestOverlap:
    """Tests for overlap computation."""

    def test_no_overlap(self, placement_graph):
        """Well-separated components have zero overlap."""
        positions = {
            "R1": (10.0, 10.0, 0.0),
            "C1": (90.0, 70.0, 0.0),
            "U1": (50.0, 40.0, 0.0),
        }
        overlap = compute_overlap_area(positions, placement_graph)
        assert overlap == 0.0

    def test_overlapping_components(self, placement_graph):
        """Identical positions produce positive overlap."""
        positions = {
            "R1": (50.0, 40.0, 0.0),
            "C1": (50.0, 40.0, 0.0),
            "U1": (50.0, 40.0, 0.0),
        }
        overlap = compute_overlap_area(positions, placement_graph)
        assert overlap > 0.0


class TestEdgePenalty:
    """Tests for edge penalty computation."""

    def test_no_edge_penalty(self):
        """Components well inside bounds have no edge penalty."""
        positions = {"R1": (50.0, 40.0, 0.0)}
        penalty = compute_edge_penalty(positions, 100.0, 80.0, margin=2.0)
        assert penalty == 0.0

    def test_edge_penalty_violations(self):
        """Component at edge incurs penalty."""
        positions = {"R1": (1.0, 1.0, 0.0)}
        penalty = compute_edge_penalty(positions, 100.0, 80.0, margin=2.0)
        assert penalty > 0.0


class TestCompositeLoss:
    """Tests for composite placement loss."""

    def test_compute_placement_loss(self, placement_graph, well_placed_positions):
        """Compute loss for positions, verify all keys present and total > 0."""
        result = compute_placement_loss(
            well_placed_positions, placement_graph, 100.0, 80.0
        )

        assert "hpwl" in result
        assert "overlap_area" in result
        assert "edge_penalty" in result
        assert "total_loss" in result
        assert result["total_loss"] > 0.0
        # Verify loss formula
        expected = result["hpwl"] + 10.0 * result["overlap_area"] + 5.0 * result["edge_penalty"]
        assert abs(result["total_loss"] - expected) < 1e-6


class TestPlacementReward:
    """Tests for GRPO reward function."""

    def test_placement_reward_perfect(self, placement_graph, well_placed_positions):
        """Same positions as reference -> high reward."""
        reward = placement_reward(
            predicted=well_placed_positions,
            reference=well_placed_positions,
            graph=placement_graph,
            board_width=100.0,
            board_height=80.0,
        )
        # Perfect match on accuracy + good wirelength/clearance
        assert reward > 0.8

    def test_placement_reward_random(self, placement_graph, well_placed_positions):
        """Random positions vs reference -> reward in [0, 1]."""
        import random
        rng = random.Random(42)

        random_positions = {}
        for ref in well_placed_positions:
            x = rng.uniform(5.0, 95.0)
            y = rng.uniform(5.0, 75.0)
            random_positions[ref] = (x, y, 0.0)

        reward = placement_reward(
            predicted=random_positions,
            reference=well_placed_positions,
            graph=placement_graph,
            board_width=100.0,
            board_height=80.0,
        )
        assert 0.0 <= reward <= 1.0

    def test_placement_reward_no_reference(self, placement_graph, well_placed_positions):
        """Without reference, accuracy contributes 0 but other scores still work."""
        reward = placement_reward(
            predicted=well_placed_positions,
            reference=None,
            graph=placement_graph,
            board_width=100.0,
            board_height=80.0,
        )
        # Still has wirelength and clearance scores
        assert 0.0 <= reward <= 1.0
        assert reward > 0.0  # wirelength + clearance should be > 0


# ---------------------------------------------------------------------------
# Trainer tests
# ---------------------------------------------------------------------------


class TestPlacementTrainer:
    """Tests for PlacementTrainer."""

    def test_placement_trainer_single_step(self):
        """Run 1 training step on 4 samples, verify metrics are valid."""
        from kicad_agent.placement.model import PlacementModel
        from kicad_agent.placement.training.train import (
            PlacementTrainConfig,
            PlacementTrainer,
        )

        model = PlacementModel()
        config = PlacementTrainConfig(
            n_epochs=1,
            batch_size=4,
            group_size=2,
        )
        trainer = PlacementTrainer(model, config)

        # Generate small dataset
        dataset = generate_placement_samples(
            n_samples=4, board_width=100.0, board_height=80.0, seed_base=42
        )

        history = trainer.train(dataset)

        # Verify history structure
        assert "losses" in history
        assert "reward_means" in history
        assert len(history["losses"]) > 0
        assert len(history["reward_means"]) > 0

        # Loss should be finite
        for loss in history["losses"]:
            assert not math.isnan(loss)
            assert not math.isinf(loss)

        # Reward should be in reasonable range
        for reward in history["reward_means"]:
            assert 0.0 <= reward <= 1.0

    def test_trainer_config_defaults(self):
        """PlacementTrainConfig has sensible defaults."""
        from kicad_agent.placement.training.train import PlacementTrainConfig

        config = PlacementTrainConfig()
        assert config.n_epochs == 1
        assert config.batch_size == 4
        assert config.learning_rate == 1e-4
        assert config.group_size == 4
        assert config.seed == 42
