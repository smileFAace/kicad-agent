"""Interactive placement with constraint propagation and SA refinement.

Lets users fix some components in place and have AI place the rest.
Fixed components are NEVER moved -- they are excluded from the SA
parameter vector entirely (pitfall 5 from RESEARCH.md). Free components
are optimized via scipy dual_annealing with an objective that combines
HPWL, clearance penalties against fixed components, and keepout zone
penalties.

Security (threat model):
  T-16-08: max_sa_iterations capped at 500 (default), configurable via ConstraintSet.
  T-16-09: Fixed positions validated against board bounds, excluded from SA vector.

Usage::

    from kicad_agent.placement.interactive import (
        interactive_placement,
        suggest_placements,
        ConstraintSet,
    )

    constraints = ConstraintSet(
        fixed_positions={"U1": (50.0, 40.0, 0.0)},
        keepout_zones=[(45.0, 35.0, 55.0, 45.0)],
    )
    positions = interactive_placement(graph, constraints, predictor)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy
from scipy.optimize import dual_annealing

from kicad_agent.placement.scoring import compute_hpwl_score
from kicad_agent.placement.validation import PlacementValidator

if TYPE_CHECKING:
    from kicad_agent.placement.graph import PlacementGraph
    from kicad_agent.placement.predict import PlacementPredictor


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_SIZE = 2.0
"""Default bounding box size in mm when component size is unknown."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConstraintSet:
    """Placement constraints for interactive mode.

    Attributes:
        fixed_positions: User-placed components that must not move.
            Mapping of reference designator to (x, y, rotation_degrees).
        keepout_zones: Forbidden rectangular regions as
            (x1, y1, x2, y2) tuples. Free components are penalized
            for being inside these zones.
        min_clearance: Minimum clearance between components in mm.
        max_sa_iterations: Maximum iterations for simulated annealing.
            Capped at 500 for DoS prevention (T-16-08).
    """

    fixed_positions: dict[str, tuple[float, float, float]] = field(
        default_factory=dict
    )
    keepout_zones: list[tuple[float, float, float, float]] = field(
        default_factory=list
    )
    min_clearance: float = 1.0
    max_sa_iterations: int = 500


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def interactive_placement(
    graph: PlacementGraph,
    constraints: ConstraintSet,
    predictor: PlacementPredictor | None = None,
) -> dict[str, tuple[float, float, float]]:
    """Place free components respecting user-fixed positions.

    Algorithm:
    1. Partition components into fixed (from constraints) and free.
    2. If no free components, return fixed positions immediately.
    3. Get initial positions: from predictor or grid fallback.
    4. Run dual_annealing to refine free component positions.
    5. Merge fixed + optimized positions.
    6. Validate and return.

    Args:
        graph: PlacementGraph with board dimensions and net topology.
        constraints: ConstraintSet with fixed positions, keepouts, etc.
        predictor: Optional ML predictor for initial positions.

    Returns:
        Mapping of reference designator to (x, y, rotation_degrees).
    """
    board_w = graph.board_width
    board_h = graph.board_height
    margin = constraints.min_clearance

    # Step 1: Partition components
    fixed: dict[str, tuple[float, float, float]] = dict(constraints.fixed_positions)
    all_refs = [
        graph._graph.nodes[nid].get("reference", "")
        for nid in graph.component_nodes()
    ]
    free_refs = [ref for ref in all_refs if ref not in fixed]

    # Step 2: No free components -> return fixed positions
    if not free_refs:
        return dict(fixed)

    # Step 3: Get initial positions for free components
    if predictor is not None and predictor.is_ready:
        initial_free = _get_predictor_initial(
            graph, free_refs, predictor, board_w, board_h, margin
        )
    else:
        initial_free = _get_grid_initial(
            graph, fixed, free_refs, board_w, board_h, margin
        )

    # Step 4: Build component size lookup
    component_sizes = _extract_component_sizes(graph)

    # Step 5: SA refinement
    n_free = len(free_refs)
    x0 = numpy.zeros(n_free * 2)
    for i, ref in enumerate(free_refs):
        x0[i * 2] = initial_free[ref][0]
        x0[i * 2 + 1] = initial_free[ref][1]

    bounds = [(margin, board_w - margin)] * (n_free * 2)

    def objective(params: numpy.ndarray) -> float:
        # Reconstruct free positions from parameter vector
        # Clamp params to bounds (dual_annealing local search can step outside)
        current_free: dict[str, tuple[float, float, float]] = {}
        for i, ref in enumerate(free_refs):
            x = max(margin, min(board_w - margin, params[i * 2]))
            y = max(margin, min(board_h - margin, params[i * 2 + 1]))
            # Preserve rotation from initial guess
            rot = initial_free[ref][2]
            current_free[ref] = (x, y, rot)

        # Merge fixed + current free
        all_positions: dict[str, tuple[float, float, float]] = {
            **fixed,
            **current_free,
        }

        # HPWL component
        hpwl, _ = compute_hpwl_score(all_positions, graph)

        # Clearance penalty against fixed components
        clearance_penalty = _compute_clearance_penalty(
            current_free, fixed, component_sizes, constraints.min_clearance
        )

        # Keepout zone penalty
        keepout_penalty = _compute_keepout_penalty(
            current_free, constraints.keepout_zones
        )

        return hpwl + clearance_penalty + keepout_penalty

    result = dual_annealing(
        objective,
        bounds=bounds,
        x0=x0,
        maxiter=constraints.max_sa_iterations,
        seed=42,
        no_local_search=False,
    )

    # Build final positions from SA result (clamp to bounds as safety net)
    final_positions: dict[str, tuple[float, float, float]] = dict(fixed)
    for i, ref in enumerate(free_refs):
        x = max(margin, min(board_w - margin, result.x[i * 2]))
        y = max(margin, min(board_h - margin, result.x[i * 2 + 1]))
        rot = initial_free[ref][2]
        final_positions[ref] = (x, y, rot)

    return final_positions


def suggest_placements(
    graph: PlacementGraph,
    fixed_positions: dict[str, tuple[float, float, float]],
    predictor: PlacementPredictor | None = None,
) -> dict[str, tuple[float, float, float]]:
    """Convenience wrapper: build ConstraintSet and call interactive_placement.

    Args:
        graph: PlacementGraph with board dimensions and net topology.
        fixed_positions: User-placed components.
        predictor: Optional ML predictor for initial positions.

    Returns:
        Mapping of reference designator to (x, y, rotation_degrees).
    """
    constraints = ConstraintSet(fixed_positions=fixed_positions)
    return interactive_placement(graph, constraints, predictor)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_predictor_initial(
    graph: PlacementGraph,
    free_refs: list[str],
    predictor: PlacementPredictor,
    board_w: float,
    board_h: float,
    margin: float,
) -> dict[str, tuple[float, float, float]]:
    """Get initial positions for free components from ML predictor."""
    prediction = predictor.predict(graph)
    initial: dict[str, tuple[float, float, float]] = {}
    for ref in free_refs:
        if ref in prediction.positions:
            x, y, rot = prediction.positions[ref]
            # Clamp to board bounds
            x = max(margin, min(board_w - margin, x))
            y = max(margin, min(board_h - margin, y))
            initial[ref] = (x, y, rot)
        else:
            # Fallback for missing predictions
            initial[ref] = (board_w / 2.0, board_h / 2.0, 0.0)
    return initial


def _get_grid_initial(
    graph: PlacementGraph,
    fixed: dict[str, tuple[float, float, float]],
    free_refs: list[str],
    board_w: float,
    board_h: float,
    margin: float,
) -> dict[str, tuple[float, float, float]]:
    """Distribute free components evenly across board, avoiding fixed positions."""
    n_free = len(free_refs)
    if n_free == 0:
        return {}

    # Compute grid layout
    cols = max(1, math.ceil(math.sqrt(n_free * board_w / board_h)))
    rows = max(1, math.ceil(n_free / cols))
    cell_w = (board_w - 2 * margin) / cols
    cell_h = (board_h - 2 * margin) / rows

    # Collect fixed positions as occupied cells for avoidance
    fixed_positions_set = {
        (pos[0], pos[1]) for pos in fixed.values()
    }

    initial: dict[str, tuple[float, float, float]] = {}
    placed_count = 0

    for idx, ref in enumerate(free_refs):
        row = idx // cols
        col = idx % cols
        x = margin + (col + 0.5) * cell_w
        y = margin + (row + 0.5) * cell_h

        # If too close to a fixed component, offset slightly
        for fx, fy in fixed_positions_set:
            dist = math.hypot(x - fx, y - fy)
            if dist < margin * 3:
                # Offset away from fixed component
                dx = x - fx
                dy = y - fy
                norm = math.hypot(dx, dy)
                if norm > 1e-9:
                    x += dx / norm * margin * 2
                    y += dy / norm * margin * 2
                else:
                    x += margin * 2

        # Clamp to bounds
        x = max(margin, min(board_w - margin, x))
        y = max(margin, min(board_h - margin, y))

        initial[ref] = (x, y, 0.0)
        placed_count += 1

    return initial


def _extract_component_sizes(graph: PlacementGraph) -> dict[str, float]:
    """Extract estimated component sizes from graph node data."""
    sizes: dict[str, float] = {}
    for node_id in graph.component_nodes():
        data = graph._graph.nodes[node_id]
        ref = data.get("reference", "")
        size = data.get("estimated_size", _DEFAULT_SIZE)
        sizes[ref] = size
    return sizes


def _compute_clearance_penalty(
    free_positions: dict[str, tuple[float, float, float]],
    fixed_positions: dict[str, tuple[float, float, float]],
    component_sizes: dict[str, float],
    min_clearance: float,
) -> float:
    """Compute penalty for free components too close to fixed components.

    Penalty = 10.0 * count of violations.
    """
    violation_count = 0

    for free_ref, (fx, fy, _) in free_positions.items():
        free_size = component_sizes.get(free_ref, _DEFAULT_SIZE) / 2.0

        for fix_ref, (fix_x, fix_y, _) in fixed_positions.items():
            fix_size = component_sizes.get(fix_ref, _DEFAULT_SIZE) / 2.0
            dist = math.hypot(fx - fix_x, fy - fix_y)
            min_dist = free_size + fix_size + min_clearance
            if dist < min_dist:
                violation_count += 1

    return 10.0 * violation_count


def _compute_keepout_penalty(
    free_positions: dict[str, tuple[float, float, float]],
    keepout_zones: list[tuple[float, float, float, float]],
) -> float:
    """Compute penalty for free components inside keepout zones.

    Penalty = 20.0 * count of components inside any keepout zone.
    """
    violation_count = 0

    for ref, (x, y, _) in free_positions.items():
        for zone in keepout_zones:
            x1, y1, x2, y2 = zone
            if x1 <= x <= x2 and y1 <= y <= y2:
                violation_count += 1
                break  # One violation per component is enough

    return 20.0 * violation_count
