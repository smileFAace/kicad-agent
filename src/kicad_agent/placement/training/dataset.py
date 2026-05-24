"""Synthetic placement training dataset generation.

Generates placement training samples with random board topologies and
computes "optimal" positions using simulated annealing (HPWL + overlap).
Each sample is serialized as JSON for JSONL storage.

Security (threat model):
  T-16-04: Sample count capped at 100,000 to prevent disk/memory exhaustion.

Usage::

    from kicad_agent.placement.training.dataset import (
        PlacementSample,
        PlacementDataset,
        generate_placement_samples,
    )

    dataset = generate_placement_samples(n_samples=50, board_width=100, board_height=80)
    dataset.to_jsonl(Path("placement_data.jsonl"))
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

from kicad_agent.generation.intent import ComponentSpec, NetSpec

# ---------------------------------------------------------------------------
# Safety limits (T-16-04)
# ---------------------------------------------------------------------------

_MAX_SAMPLES = 100_000
"""Maximum number of samples to prevent disk/memory exhaustion."""

# ---------------------------------------------------------------------------
# Component type prefixes for synthetic generation
# ---------------------------------------------------------------------------

_COMP_PREFIXES = ["U", "R", "C", "L", "J", "Q"]

_COMP_LIBRARIES = {
    "U": "MCU_ST:STM32F103",
    "R": "Device:R_Small_US",
    "C": "Device:C_Small",
    "L": "Device:L_Small",
    "J": "Connector:Conn_01x04",
    "Q": "Transistor_FET:2N7002",
}

_COMP_VALUES = {
    "U": "IC",
    "R": "10k",
    "C": "100nF",
    "L": "4.7uH",
    "J": "Header",
    "Q": "MOSFET",
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlacementSample:
    """A single synthetic placement training sample.

    Attributes:
        sample_id: Sequential index in dataset.
        board_width: Board width in mm.
        board_height: Board height in mm.
        n_components: Number of components.
        components_json: JSON-serialized list of ComponentSpec dicts.
        nets_json: JSON-serialized list of NetSpec dicts.
        optimal_positions_json: JSON-serialized dict of ref -> (x, y, rot).
        difficulty: "easy", "medium", or "hard".
        board_hash: SHA256 hex digest for deduplication.
    """

    sample_id: int
    board_width: float
    board_height: float
    n_components: int
    components_json: str
    nets_json: str
    optimal_positions_json: str
    difficulty: str
    board_hash: str

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON storage."""
        return {
            "sample_id": self.sample_id,
            "board_width": self.board_width,
            "board_height": self.board_height,
            "n_components": self.n_components,
            "components_json": self.components_json,
            "nets_json": self.nets_json,
            "optimal_positions_json": self.optimal_positions_json,
            "difficulty": self.difficulty,
            "board_hash": self.board_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PlacementSample:
        """Deserialize from a plain dict."""
        return cls(
            sample_id=d["sample_id"],
            board_width=d["board_width"],
            board_height=d["board_height"],
            n_components=d["n_components"],
            components_json=d["components_json"],
            nets_json=d["nets_json"],
            optimal_positions_json=d["optimal_positions_json"],
            difficulty=d["difficulty"],
            board_hash=d["board_hash"],
        )


class PlacementDataset:
    """Collection of placement training samples with JSONL I/O.

    Attributes:
        samples: Ordered list of PlacementSample objects.
    """

    def __init__(self, samples: list[PlacementSample] | None = None) -> None:
        self.samples: list[PlacementSample] = samples or []

    def __len__(self) -> int:
        return len(self.samples)

    def to_jsonl(self, path: Path) -> int:
        """Write samples as JSONL (one JSON object per line).

        Args:
            path: Output file path.

        Returns:
            Number of lines written.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(path, "w") as f:
            for sample in self.samples:
                f.write(json.dumps(sample.to_dict()) + "\n")
                count += 1
        return count

    @classmethod
    def from_jsonl(cls, path: Path) -> PlacementDataset:
        """Load samples from a JSONL file.

        Args:
            path: Input JSONL file path.

        Returns:
            PlacementDataset with loaded samples.
        """
        path = Path(path)
        samples: list[PlacementSample] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    samples.append(PlacementSample.from_dict(json.loads(line)))
        return cls(samples=samples)


# ---------------------------------------------------------------------------
# Synthetic generation
# ---------------------------------------------------------------------------


def _generate_components(
    n_comp: int,
    rng: random.Random,
) -> list[ComponentSpec]:
    """Generate random ComponentSpec instances with varied types."""
    components: list[ComponentSpec] = []
    prefix_counts: dict[str, int] = {}

    for _ in range(n_comp):
        prefix = rng.choice(_COMP_PREFIXES)
        prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
        idx = prefix_counts[prefix]
        ref = f"{prefix}{idx}"
        lib = _COMP_LIBRARIES[prefix]
        val = _COMP_VALUES[prefix]

        components.append(ComponentSpec(
            library_id=lib,
            reference=ref,
            value=val,
        ))
    return components


def _generate_nets(
    components: list[ComponentSpec],
    rng: random.Random,
    net_density: float = 0.5,
) -> list[NetSpec]:
    """Generate random nets connecting components.

    Args:
        components: Components to connect.
        rng: Random state for reproducibility.
        net_density: Fraction of possible connections to create.
    """
    if len(components) < 2:
        return []

    refs = [c.reference for c in components]
    nets: list[NetSpec] = []
    net_id = 0

    # Create nets by grouping random subsets of components
    n_nets = max(2, int(len(components) * net_density))
    used_pairs: set[tuple[str, ...]] = set()

    for _ in range(n_nets):
        # Pick 2-4 components for this net
        n_in_net = min(len(components), rng.randint(2, min(4, len(components))))
        chosen = rng.sample(refs, n_in_net)
        chosen_sorted = tuple(sorted(chosen))

        if chosen_sorted in used_pairs:
            continue
        used_pairs.add(chosen_sorted)

        net_name = f"N{net_id}"
        net_id += 1

        pins = [f"{ref}.{rng.randint(1, 8)}" for ref in chosen]
        nets.append(NetSpec(name=net_name, pins=pins))

    return nets


def _estimate_component_size(ref: str) -> float:
    """Estimate component bounding box half-size from reference prefix."""
    prefix = ref[0].upper() if ref else ""
    sizes = {"U": 5.0, "Q": 4.0, "L": 2.5, "J": 3.0, "R": 1.0, "C": 1.0}
    return sizes.get(prefix, 1.5)


def _compute_optimal_positions(
    components: list[ComponentSpec],
    nets: list[NetSpec],
    board_width: float,
    board_height: float,
    rng_seed: int,
) -> dict[str, tuple[float, float, float]]:
    """Compute near-optimal positions using simulated annealing.

    Objective: minimize HPWL (half-perimeter wirelength) + overlap penalty.
    Uses scipy.optimize.dual_annealing for global optimization.

    Args:
        components: Components to place.
        nets: Net connections.
        board_width: Board width in mm.
        board_height: Board height in mm.
        rng_seed: Seed for reproducibility.

    Returns:
        Dict mapping ref -> (x, y, rotation_degrees).
    """
    import numpy as np
    from scipy.optimize import dual_annealing

    n = len(components)
    margin = 5.0

    if n == 0:
        return {}

    refs = [c.reference for c in components]
    sizes = [_estimate_component_size(r) for r in refs]

    # Build net connectivity: list of sets of component indices
    ref_to_idx = {r: i for i, r in enumerate(refs)}
    net_groups: list[set[int]] = []
    for net in nets:
        indices: set[int] = set()
        for pin in net.pins:
            parts = pin.split(".")
            if parts and parts[0] in ref_to_idx:
                indices.add(ref_to_idx[parts[0]])
        if len(indices) >= 2:
            net_groups.append(indices)

    def objective(flat_positions: np.ndarray) -> float:
        """HPWL + overlap penalty."""
        positions = flat_positions.reshape(n, 2)
        cost = 0.0

        # HPWL: sum of bounding box half-perimeters per net
        for group in net_groups:
            xs = positions[list(group), 0]
            ys = positions[list(group), 1]
            hpwl = (xs.max() - xs.min()) + (ys.max() - ys.min())
            cost += hpwl

        # Overlap penalty: sum of pairwise intersection areas
        for i in range(n):
            for j in range(i + 1, n):
                si, sj = sizes[i], sizes[j]
                x_overlap = max(0, si + sj - abs(positions[i, 0] - positions[j, 0]))
                y_overlap = max(0, si + sj - abs(positions[i, 1] - positions[j, 1]))
                overlap = x_overlap * y_overlap
                cost += 10.0 * overlap

        return cost

    # Bounds: each (x, y) in [margin, board_dim - margin]
    lb = [margin, margin] * n
    ub = [board_width - margin, board_height - margin] * n

    result = dual_annealing(
        objective,
        bounds=list(zip(lb, ub)),
        seed=rng_seed,
        maxiter=200,
        initial_temp=50.0,
    )

    optimal = result.x.reshape(n, 2)
    positions: dict[str, tuple[float, float, float]] = {}
    for i, ref in enumerate(refs):
        x = float(optimal[i, 0])
        y = float(optimal[i, 1])
        rot = 0.0  # Default rotation
        positions[ref] = (x, y, rot)

    return positions


def _grade_difficulty(n_components: int, n_nets: int) -> str:
    """Grade placement difficulty based on component count and net density."""
    if n_components <= 5:
        return "easy"
    if n_components <= 15 and n_nets <= 10:
        return "easy"
    if n_components <= 20:
        return "medium"
    return "hard"


def _compute_board_hash(
    components: list[ComponentSpec],
    nets: list[NetSpec],
) -> str:
    """Compute SHA256 hash from component + net data for deduplication."""
    parts: list[str] = []
    for c in sorted(components, key=lambda x: x.reference):
        parts.append(f"{c.reference}:{c.library_id}:{c.value}")
    for n in sorted(nets, key=lambda x: x.name):
        parts.append(f"{n.name}:{','.join(sorted(n.pins))}")
    content = "|".join(parts)
    return hashlib.sha256(content.encode()).hexdigest()


def _serialize_components(components: list[ComponentSpec]) -> str:
    """Serialize component list to JSON string."""
    return json.dumps([
        {"library_id": c.library_id, "reference": c.reference, "value": c.value}
        for c in components
    ])


def _serialize_nets(nets: list[NetSpec]) -> str:
    """Serialize net list to JSON string."""
    return json.dumps([
        {"name": n.name, "pins": n.pins}
        for n in nets
    ])


def _serialize_positions(
    positions: dict[str, tuple[float, float, float]],
) -> str:
    """Serialize positions dict to JSON string."""
    # Convert tuples to lists for JSON serialization
    return json.dumps({ref: list(pos) for ref, pos in positions.items()})


def generate_placement_samples(
    n_samples: int,
    board_width: float = 100.0,
    board_height: float = 80.0,
    seed_base: int = 42,
) -> PlacementDataset:
    """Generate synthetic placement training data.

    Creates random board topologies with components and nets, then computes
    near-optimal positions using simulated annealing. Each sample is graded
    by difficulty based on component count and net density.

    Args:
        n_samples: Number of samples to generate (1..100,000).
        board_width: Board width in mm.
        board_height: Board height in mm.
        seed_base: Base seed for deterministic generation.

    Returns:
        PlacementDataset with graded samples.

    Raises:
        ValueError: If n_samples exceeds 100,000.
    """
    if n_samples > _MAX_SAMPLES:
        raise ValueError(
            f"n_samples must be <= {_MAX_SAMPLES}, got {n_samples}"
        )

    samples: list[PlacementSample] = []

    for i in range(n_samples):
        rng = random.Random(seed_base + i)

        # Determine difficulty for this sample
        difficulty_roll = rng.random()
        if difficulty_roll < 0.33:
            n_comp = rng.randint(3, 6)
            net_density = 0.3
        elif difficulty_roll < 0.66:
            n_comp = rng.randint(8, 18)
            net_density = 0.5
        else:
            n_comp = rng.randint(15, 30)
            net_density = 0.7

        components = _generate_components(n_comp, rng)
        nets = _generate_nets(components, rng, net_density=net_density)

        # Compute optimal positions
        optimal = _compute_optimal_positions(
            components, nets, board_width, board_height,
            rng_seed=seed_base + i,
        )

        difficulty = _grade_difficulty(n_comp, len(nets))
        board_hash = _compute_board_hash(components, nets)

        sample = PlacementSample(
            sample_id=i,
            board_width=board_width,
            board_height=board_height,
            n_components=n_comp,
            components_json=_serialize_components(components),
            nets_json=_serialize_nets(nets),
            optimal_positions_json=_serialize_positions(optimal),
            difficulty=difficulty,
            board_hash=board_hash,
        )
        samples.append(sample)

    return PlacementDataset(samples=samples)
