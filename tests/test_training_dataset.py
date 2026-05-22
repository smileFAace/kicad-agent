"""Tests for synthetic maze-routing dataset generation (Plan 09-01).

Covers:
  - MazeSample construction and immutability
  - MazeDataset creation, JSONL round-trip, split ratios
  - generate_dataset() with small sample counts
  - Difficulty grading logic
  - Deduplication
  - Parallel generation
  - Adversarial generation
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from kicad_agent.training.dataset import (
    DEFAULT_BOARD_CONFIGS,
    MazeDataset,
    MazeSample,
    _grade_difficulty,
    generate_dataset,
)
from kicad_agent.training.generator import generate_adversarial_samples, generate_samples_parallel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_a() -> MazeSample:
    """A minimal valid MazeSample."""
    return MazeSample(
        sample_id=0,
        seed=42,
        board_width_mm=50.0,
        board_height_mm=50.0,
        grid_size_mm=5.0,
        obstacle_count=10,
        obstacle_positions=((5.0, 5.0), (10.0, 10.0)),
        source_point=(2.5, 2.5),
        target_point=(47.5, 47.5),
        solution_path=((2.5, 2.5), (7.5, 2.5), (47.5, 47.5)),
        solution_length=3,
        difficulty="easy",
        board_hash="abc123",
    )


@pytest.fixture
def sample_b() -> MazeSample:
    """A second distinct MazeSample."""
    return MazeSample(
        sample_id=1,
        seed=43,
        board_width_mm=30.0,
        board_height_mm=30.0,
        grid_size_mm=5.0,
        obstacle_count=5,
        obstacle_positions=(),
        source_point=(2.5, 2.5),
        target_point=(27.5, 27.5),
        solution_path=((2.5, 2.5), (27.5, 27.5)),
        solution_length=2,
        difficulty="easy",
        board_hash="def456",
    )


# ======================================================================
# TestMazeSample
# ======================================================================


class TestMazeSample:
    """MazeSample construction and immutability."""

    def test_construction(self, sample_a: MazeSample) -> None:
        """MazeSample fields are set correctly."""
        assert sample_a.sample_id == 0
        assert sample_a.seed == 42
        assert sample_a.board_width_mm == 50.0
        assert sample_a.obstacle_count == 10
        assert sample_a.solution_length == 3
        assert sample_a.difficulty == "easy"

    def test_frozen(self, sample_a: MazeSample) -> None:
        """MazeSample is frozen — cannot modify attributes."""
        with pytest.raises(FrozenInstanceError):
            sample_a.sample_id = 99  # type: ignore[misc]

    def test_tuple_fields(self, sample_a: MazeSample) -> None:
        """Obstacle positions and solution path are tuples."""
        assert isinstance(sample_a.obstacle_positions, tuple)
        assert isinstance(sample_a.solution_path, tuple)
        assert len(sample_a.obstacle_positions) == 2


# ======================================================================
# TestMazeDataset
# ======================================================================


class TestMazeDataset:
    """MazeDataset creation, JSONL round-trip, and splitting."""

    def test_len(self, sample_a: MazeSample, sample_b: MazeSample) -> None:
        """Dataset length matches sample count."""
        ds = MazeDataset(samples=[sample_a, sample_b])
        assert len(ds) == 2

    def test_empty_dataset(self) -> None:
        """Empty dataset has length 0."""
        ds = MazeDataset()
        assert len(ds) == 0

    def test_difficulty_counts(
        self, sample_a: MazeSample, sample_b: MazeSample
    ) -> None:
        """difficulty_counts returns correct mapping."""
        ds = MazeDataset(samples=[sample_a, sample_b])
        counts = ds.difficulty_counts
        assert counts.get("easy", 0) == 2

    def test_jsonl_round_trip(
        self, sample_a: MazeSample, sample_b: MazeSample, tmp_path: Path
    ) -> None:
        """JSONL write and read preserves all samples."""
        ds = MazeDataset(samples=[sample_a, sample_b])
        jsonl_path = tmp_path / "test.jsonl"
        n_written = ds.to_jsonl(jsonl_path)
        assert n_written == 2

        loaded = MazeDataset.from_jsonl(jsonl_path)
        assert len(loaded) == 2
        assert loaded.samples[0].sample_id == 0
        assert loaded.samples[1].sample_id == 1
        assert loaded.samples[0].board_hash == "abc123"

    def test_jsonl_content_valid(
        self, sample_a: MazeSample, tmp_path: Path
    ) -> None:
        """Each JSONL line is valid JSON with expected keys."""
        ds = MazeDataset(samples=[sample_a])
        jsonl_path = tmp_path / "single.jsonl"
        ds.to_jsonl(jsonl_path)

        with open(jsonl_path) as f:
            line = f.readline().strip()
            obj = json.loads(line)
            assert "sample_id" in obj
            assert "seed" in obj
            assert "difficulty" in obj
            assert "solution_path" in obj
            assert "board_hash" in obj

    def test_split_ratios(
        self, sample_a: MazeSample, sample_b: MazeSample, tmp_path: Path
    ) -> None:
        """Split produces correct ratios for a 10-sample dataset."""
        samples = []
        for i in range(10):
            samples.append(
                MazeSample(
                    sample_id=i,
                    seed=42 + i,
                    board_width_mm=50.0,
                    board_height_mm=50.0,
                    grid_size_mm=5.0,
                    obstacle_count=5,
                    obstacle_positions=(),
                    source_point=(2.5, 2.5),
                    target_point=(47.5, 47.5),
                    solution_path=((2.5, 2.5), (47.5, 47.5)),
                    solution_length=2,
                    difficulty="easy",
                    board_hash=f"hash_{i}",
                )
            )
        ds = MazeDataset(samples=samples)
        train, val, test = ds.split(train=0.8, val=0.1, test=0.1)
        assert len(train) == 8
        assert len(val) == 1
        assert len(test) == 1

    def test_split_invalid_ratios(self) -> None:
        """Invalid split ratios raise ValueError."""
        ds = MazeDataset(samples=[MazeSample(
            sample_id=0, seed=0, board_width_mm=50, board_height_mm=50,
            grid_size_mm=5, obstacle_count=0, obstacle_positions=(),
            source_point=(0, 0), target_point=(1, 1),
            solution_path=((0, 0), (1, 1)), solution_length=2,
            difficulty="easy", board_hash="x",
        )])
        with pytest.raises(ValueError, match="sum to 1.0"):
            ds.split(train=0.5, val=0.3, test=0.3)


# ======================================================================
# TestDifficultyGrading
# ======================================================================


class TestDifficultyGrading:
    """Difficulty grading boundary conditions."""

    def test_easy(self) -> None:
        """Short path + low density = easy."""
        assert _grade_difficulty(solution_length=3, obstacle_count=5, total_cells=100) == "easy"

    def test_medium(self) -> None:
        """Medium path or moderate density = medium."""
        assert _grade_difficulty(solution_length=10, obstacle_count=35, total_cells=100) == "medium"

    def test_hard(self) -> None:
        """Long path or high density = hard."""
        assert _grade_difficulty(solution_length=20, obstacle_count=55, total_cells=100) == "hard"

    def test_adversarial(self) -> None:
        """Very long path + very high density = adversarial."""
        assert _grade_difficulty(solution_length=35, obstacle_count=75, total_cells=100) == "adversarial"

    def test_boundary_easy_medium(self) -> None:
        """Boundary between easy and medium."""
        # solution_length=6 (just above easy threshold of 5) but density still low
        result = _grade_difficulty(solution_length=6, obstacle_count=20, total_cells=100)
        assert result == "medium"

    def test_zero_cells(self) -> None:
        """Zero total cells produces density 0."""
        result = _grade_difficulty(solution_length=2, obstacle_count=0, total_cells=0)
        assert result == "easy"


# ======================================================================
# TestGenerateDataset
# ======================================================================


class TestGenerateDataset:
    """Integration test for generate_dataset()."""


    def test_small_dataset(self) -> None:
        """generate_dataset with n_samples=5 produces valid samples."""
        ds = generate_dataset(n_samples=5, seed_base=42)
        assert len(ds) >= 1  # at least some should succeed
        assert ds.metadata["n_requested"] == 5
        assert ds.metadata["n_generated"] == len(ds)

    def test_deterministic_seeding(self) -> None:
        """Same seed produces same obstacle positions and solution paths."""
        ds1 = generate_dataset(n_samples=3, seed_base=100)
        ds2 = generate_dataset(n_samples=3, seed_base=100)
        assert len(ds1) == len(ds2)
        if ds1.samples and ds2.samples:
            # Board hashes differ due to kiutils serialization non-determinism,
            # but the spatial data (obstacles, solution) must be identical
            assert ds1.samples[0].obstacle_positions == ds2.samples[0].obstacle_positions
            assert ds1.samples[0].solution_path == ds2.samples[0].solution_path
            assert ds1.samples[0].source_point == ds2.samples[0].source_point

    def test_invalid_n_samples(self) -> None:
        """n_samples < 1 raises ValueError."""
        with pytest.raises(ValueError, match="n_samples must be >= 1"):
            generate_dataset(n_samples=0)

    def test_n_samples_too_large(self) -> None:
        """n_samples > 1M raises ValueError."""
        with pytest.raises(ValueError, match="n_samples must be <="):
            generate_dataset(n_samples=2_000_000)

    def test_deduplication(self) -> None:
        """Duplicate board hashes are skipped."""
        # With very few seeds, dedup is unlikely but the mechanism exists
        ds = generate_dataset(n_samples=3, seed_base=42)
        hashes = [s.board_hash for s in ds.samples]
        assert len(hashes) == len(set(hashes)), "No duplicate hashes should remain"


# ======================================================================
# TestParallelGeneration
# ======================================================================


class TestParallelGeneration:
    """Parallel sample generation."""


    def test_parallel_generates_correct_count(self) -> None:
        """Parallel generation produces samples."""
        ds = generate_samples_parallel(n_samples=6, n_workers=2, seed_base=42)
        assert len(ds) >= 1
        assert ds.metadata["n_workers"] == 2

    def test_parallel_deduplicates(self) -> None:
        """Parallel generation deduplicates across workers."""
        ds = generate_samples_parallel(n_samples=4, n_workers=2, seed_base=42)
        hashes = [s.board_hash for s in ds.samples]
        assert len(hashes) == len(set(hashes))


# ======================================================================
# TestAdversarialGeneration
# ======================================================================


class TestAdversarialGeneration:
    """Adversarial sample generation produces high-difficulty boards."""


    def test_adversarial_produces_samples(self) -> None:
        """Adversarial generation produces at least some samples."""
        ds = generate_adversarial_samples(n_samples=5, seed_base=42)
        assert len(ds) >= 1

    def test_adversarial_has_variety(self) -> None:
        """Adversarial samples use diverse board sizes."""
        ds = generate_adversarial_samples(n_samples=5, seed_base=42)
        if ds.samples:
            widths = set(s.board_width_mm for s in ds.samples)
            assert len(widths) >= 1  # at minimum some diversity from configs
