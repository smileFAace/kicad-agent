"""Tests for cold-start reasoning chain synthesis (Plan 09-02).

Covers:
  - MazeReasoningChain construction and immutability
  - synthesize_maze_chain() produces 5-step chains with coordinates
  - Chain text contains <point x,y> coordinate references
  - DFS exploration steps with correct positions
  - Exploration chains include backtracking and dead-end mentions
  - JSONL writing produces valid output
  - build_training_chains() with small dataset
  - Chain correctness: solution chains reach target
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from kicad_agent.training.chains import (
    MazeReasoningChain,
    synthesize_exploration_chain,
    synthesize_maze_chain,
)
from kicad_agent.training.chain_builder import (
    CellState,
    ExplorationStep,
    dfs_explore,
    exploration_to_chain,
)
from kicad_agent.training.chain_writer import build_training_chains, write_chains_jsonl
from kicad_agent.training.dataset import MazeDataset, MazeSample, generate_dataset


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def easy_sample() -> MazeSample:
    """An easy difficulty MazeSample."""
    return MazeSample(
        sample_id=0,
        seed=42,
        board_width_mm=30.0,
        board_height_mm=30.0,
        grid_size_mm=5.0,
        obstacle_count=2,
        obstacle_positions=((10.0, 10.0), (20.0, 20.0)),
        source_point=(2.5, 2.5),
        target_point=(27.5, 27.5),
        solution_path=((2.5, 2.5), (7.5, 2.5), (12.5, 7.5), (27.5, 27.5)),
        solution_length=4,
        difficulty="easy",
        board_hash="test_hash_0",
    )


@pytest.fixture
def simple_grid() -> list[list[bool]]:
    """A simple 6x6 grid with 2 obstacles."""
    grid = [[False] * 6 for _ in range(6)]
    grid[2][2] = True  # obstacle at (12.5, 12.5) mm
    grid[3][3] = True  # obstacle at (17.5, 17.5) mm
    return grid


# ======================================================================
# TestMazeReasoningChain
# ======================================================================


class TestMazeReasoningChain:
    """MazeReasoningChain construction and immutability."""

    def test_construction(self, easy_sample: MazeSample) -> None:
        """Chain fields are set correctly."""
        chain = synthesize_maze_chain(easy_sample)
        assert chain.sample_id == 0
        assert chain.difficulty == "easy"
        assert chain.is_correct is True
        assert chain.exploration_branches == 0
        assert len(chain.chain_text) > 0

    def test_frozen(self, easy_sample: MazeSample) -> None:
        """MazeReasoningChain is frozen."""
        chain = synthesize_maze_chain(easy_sample)
        with pytest.raises(FrozenInstanceError):
            chain.sample_id = 99  # type: ignore[misc]

    def test_has_5_steps(self, easy_sample: MazeSample) -> None:
        """Solution chain has exactly 5 steps."""
        chain = synthesize_maze_chain(easy_sample)
        assert len(chain.steps) == 5

    def test_step_types(self, easy_sample: MazeSample) -> None:
        """Steps follow the 5-type pattern."""
        chain = synthesize_maze_chain(easy_sample)
        expected_types = ["observation", "spatial_context", "coordinate_reference", "diagnosis", "recommendation"]
        actual_types = [s["step_type"] for s in chain.steps]
        assert actual_types == expected_types


# ======================================================================
# TestCoordinateReferences
# ======================================================================


class TestCoordinateReferences:
    """Chain text contains <point x,y> coordinate references."""

    def test_solution_chain_has_coordinates(self, easy_sample: MazeSample) -> None:
        """Solution chain text contains <point> references."""
        chain = synthesize_maze_chain(easy_sample)
        assert "<point" in chain.chain_text
        # Should reference source and target
        assert str(int(easy_sample.source_point[0])) in chain.chain_text
        assert str(int(easy_sample.target_point[0])) in chain.chain_text

    def test_coordinates_referenced_not_empty(self, easy_sample: MazeSample) -> None:
        """Chain has non-empty coordinates_referenced tuple."""
        chain = synthesize_maze_chain(easy_sample)
        assert len(chain.coordinates_referenced) > 0
        assert easy_sample.source_point in chain.coordinates_referenced
        assert easy_sample.target_point in chain.coordinates_referenced

    def test_solution_path_in_chain(self, easy_sample: MazeSample) -> None:
        """Solution path coordinates appear in chain."""
        chain = synthesize_maze_chain(easy_sample)
        for point in easy_sample.solution_path:
            assert point in chain.coordinates_referenced


# ======================================================================
# TestDFSExploration
# ======================================================================


class TestDFSExploration:
    """DFS exploration with backtracking."""

    def test_returns_steps(self, simple_grid: list[list[bool]]) -> None:
        """DFS exploration returns exploration steps."""
        steps = dfs_explore(simple_grid, (0, 0), (5, 5), 5.0)
        assert len(steps) > 0

    def test_finds_target(self, simple_grid: list[list[bool]]) -> None:
        """DFS exploration reaches the target."""
        steps = dfs_explore(simple_grid, (0, 0), (5, 5), 5.0)
        actions = [s.action for s in steps]
        assert "found_target" in actions

    def test_step_positions_in_mm(self, simple_grid: list[list[bool]]) -> None:
        """Step positions are in mm coordinates."""
        steps = dfs_explore(simple_grid, (0, 0), (5, 5), 5.0)
        # First step should be at cell (0,0) = (2.5, 2.5) mm
        first_pos = steps[0].position
        assert first_pos == (2.5, 2.5)

    def test_empty_grid(self) -> None:
        """Empty grid returns empty steps."""
        steps = dfs_explore([], (0, 0), (1, 1), 5.0)
        assert steps == []

    def test_blocked_start(self) -> None:
        """Blocked start cell returns empty steps."""
        grid = [[True]]
        steps = dfs_explore(grid, (0, 0), (0, 0), 5.0)
        assert steps == []

    def test_no_path(self) -> None:
        """Unreachable target has no found_target action."""
        # 2x2 grid with all cells blocked except start and target separated by wall
        grid = [[False, True], [True, False]]
        steps = dfs_explore(grid, (0, 0), (1, 1), 5.0)
        actions = [s.action for s in steps]
        assert "found_target" not in actions


# ======================================================================
# TestExplorationStep
# ======================================================================


class TestExplorationStep:
    """ExplorationStep construction."""

    def test_construction(self) -> None:
        """ExplorationStep fields are set correctly."""
        step = ExplorationStep(
            position=(5.0, 5.0),
            action="explore",
            direction="right",
            obstacle_hit=False,
            coordinates=((5.0, 5.0), (10.0, 5.0)),
        )
        assert step.position == (5.0, 5.0)
        assert step.action == "explore"
        assert step.direction == "right"
        assert step.obstacle_hit is False

    def test_frozen(self) -> None:
        """ExplorationStep is frozen."""
        step = ExplorationStep(
            position=(5.0, 5.0), action="explore", direction="up",
            obstacle_hit=False, coordinates=(),
        )
        with pytest.raises(FrozenInstanceError):
            step.action = "changed"  # type: ignore[misc]


# ======================================================================
# TestExplorationChain
# ======================================================================


class TestExplorationChain:
    """Exploration chain synthesis from DFS."""

    def test_exploration_chain_has_steps(self, easy_sample: MazeSample) -> None:
        """Exploration chain has non-empty steps."""
        chain = synthesize_exploration_chain(easy_sample)
        assert len(chain.steps) > 0

    def test_exploration_chain_has_coordinates(self, easy_sample: MazeSample) -> None:
        """Exploration chain text contains coordinate references."""
        chain = synthesize_exploration_chain(easy_sample)
        assert "<point" in chain.chain_text

    def test_exploration_chain_reaches_target(self, easy_sample: MazeSample) -> None:
        """Exploration chain that finds target is marked correct."""
        # The easy_sample has a clear path, so DFS should find it
        chain = synthesize_exploration_chain(easy_sample)
        assert chain.is_correct is True

    def test_exploration_chain_text_content(self, easy_sample: MazeSample) -> None:
        """Exploration chain includes directional movement text."""
        chain = synthesize_exploration_chain(easy_sample)
        # Should contain at least one direction word
        has_direction = any(
            word in chain.chain_text
            for word in ["up", "right", "down", "left"]
        )
        assert has_direction


# ======================================================================
# TestChainWriter
# ======================================================================


class TestChainWriter:
    """JSONL chain writing and batch processing."""


    def test_write_chains_jsonl(self, easy_sample: MazeSample, tmp_path: Path) -> None:
        """write_chains_jsonl produces valid JSONL."""
        chain = synthesize_maze_chain(easy_sample)
        path = tmp_path / "chains.jsonl"
        count = write_chains_jsonl([chain], path)
        assert count == 1
        assert path.exists()

        with open(path) as f:
            line = f.readline().strip()
            obj = json.loads(line)
            assert obj["sample_id"] == 0
            assert obj["is_correct"] is True

    def test_build_training_chains_solution(self, tmp_path: Path) -> None:
        """build_training_chains with chain_type='solution' writes solution chains."""
        ds = generate_dataset(n_samples=3, seed_base=42)
        path = tmp_path / "sol.jsonl"
        count = build_training_chains(ds, path, chain_type="solution")
        assert count >= 1
        assert path.exists()

    def test_build_training_chains_exploration(self, tmp_path: Path) -> None:
        """build_training_chains with chain_type='exploration' writes exploration chains."""
        ds = generate_dataset(n_samples=3, seed_base=42)
        path = tmp_path / "exp.jsonl"
        count = build_training_chains(ds, path, chain_type="exploration")
        assert count >= 1

    def test_build_training_chains_both(self, tmp_path: Path) -> None:
        """build_training_chains with chain_type='both' doubles output."""
        ds = generate_dataset(n_samples=3, seed_base=42)
        path = tmp_path / "both.jsonl"
        count = build_training_chains(ds, path, chain_type="both")
        sol_path = tmp_path / "sol_only.jsonl"
        sol_count = build_training_chains(ds, sol_path, chain_type="solution")
        assert count == sol_count * 2

    def test_build_training_chains_invalid_type(self, tmp_path: Path) -> None:
        """Invalid chain_type raises ValueError."""
        ds = MazeDataset()
        path = tmp_path / "bad.jsonl"
        with pytest.raises(ValueError, match="chain_type must be"):
            build_training_chains(ds, path, chain_type="invalid")

    def test_chain_correctness_solution(self, tmp_path: Path) -> None:
        """Solution chains always reach target coordinate."""
        ds = generate_dataset(n_samples=3, seed_base=42)
        path = tmp_path / "correct.jsonl"
        build_training_chains(ds, path, chain_type="solution")

        with open(path) as f:
            for line in f:
                obj = json.loads(line.strip())
                assert obj["is_correct"] is True
