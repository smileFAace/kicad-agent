"""Placement reward computation for GRPO training.

Computes HPWL (half-perimeter wirelength), overlap area, edge penalties,
and a composite reward signal for group-relative policy optimization.

Usage::

    from kicad_agent.placement.training.reward import (
        compute_hpwl,
        compute_placement_loss,
        placement_reward,
    )
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kicad_agent.placement.graph import PlacementGraph


# ---------------------------------------------------------------------------
# HPWL computation
# ---------------------------------------------------------------------------


def compute_hpwl(
    positions: dict[str, tuple[float, float, float]],
    graph: PlacementGraph,
) -> float:
    """Compute Half-Perimeter Wirelength across all nets.

    For each net, computes the bounding box of connected component positions
    and sums the half-perimeters (width + height). Lower is better.

    Args:
        positions: Mapping of ref -> (x, y, rotation_degrees).
        graph: PlacementGraph for net connectivity.

    Returns:
        Total HPWL across all nets. 0.0 if no nets.
    """
    if not positions:
        return 0.0

    # Build ref -> position mapping (only x, y used)
    ref_pos: dict[str, tuple[float, float]] = {}
    for ref, (x, y, _rot) in positions.items():
        ref_pos[ref] = (x, y)

    # Get net connectivity from the graph
    comp_ids = graph.component_nodes()
    net_ids = graph.net_nodes()

    if not net_ids:
        return 0.0

    # Build adjacency: for each net, which components are connected
    net_index = {nid: j for j, nid in enumerate(net_ids)}
    net_components: dict[str, list[str]] = {nid: [] for nid in net_ids}

    for comp_id in comp_ids:
        ref = comp_id.replace("comp:", "", 1)
        for neighbor in graph._graph.neighbors(comp_id):
            if neighbor in net_components:
                net_components[neighbor].append(ref)

    total_hpwl = 0.0
    for nid, comp_refs in net_components.items():
        # Filter to refs with positions
        positioned = [ref_pos[r] for r in comp_refs if r in ref_pos]
        if len(positioned) < 2:
            continue

        xs = [p[0] for p in positioned]
        ys = [p[1] for p in positioned]
        half_perimeter = (max(xs) - min(xs)) + (max(ys) - min(ys))
        total_hpwl += half_perimeter

    return total_hpwl


# ---------------------------------------------------------------------------
# Overlap computation
# ---------------------------------------------------------------------------


def compute_overlap_area(
    positions: dict[str, tuple[float, float, float]],
    graph: PlacementGraph,
    min_clearance: float = 1.0,
) -> float:
    """Compute sum of pairwise overlap areas between component bounding boxes.

    Uses estimated sizes from component reference prefixes. Each component
    gets a bounding box centered at its position with size based on type.

    Args:
        positions: Mapping of ref -> (x, y, rotation_degrees).
        graph: PlacementGraph for component info.
        min_clearance: Minimum clearance in mm (used for box expansion).

    Returns:
        Total pairwise intersection area.
    """
    if not positions:
        return 0.0

    # Build boxes: (x1, y1, x2, y2) for each component
    boxes: list[tuple[float, float, float, float]] = []
    refs = list(positions.keys())

    for ref in refs:
        x, y, _rot = positions[ref]
        half_size = _estimate_size(ref)
        boxes.append((x - half_size, y - half_size, x + half_size, y + half_size))

    total_overlap = 0.0
    n = len(boxes)
    for i in range(n):
        for j in range(i + 1, n):
            x_overlap = max(0.0, min(boxes[i][2], boxes[j][2]) - max(boxes[i][0], boxes[j][0]))
            y_overlap = max(0.0, min(boxes[i][3], boxes[j][3]) - max(boxes[i][1], boxes[j][1]))
            total_overlap += x_overlap * y_overlap

    return total_overlap


def _estimate_size(ref: str) -> float:
    """Estimate component half-size from reference prefix."""
    prefix = ref[0].upper() if ref else ""
    sizes = {"U": 5.0, "Q": 4.0, "L": 2.5, "J": 3.0, "R": 1.0, "C": 1.0}
    return sizes.get(prefix, 1.5)


# ---------------------------------------------------------------------------
# Edge penalty
# ---------------------------------------------------------------------------


def compute_edge_penalty(
    positions: dict[str, tuple[float, float, float]],
    board_width: float,
    board_height: float,
    margin: float = 2.0,
) -> float:
    """Compute penalty for components within margin of board edges.

    Each violation adds 1.0 to the penalty.

    Args:
        positions: Mapping of ref -> (x, y, rotation_degrees).
        board_width: Board width in mm.
        board_height: Board height in mm.
        margin: Edge margin in mm.

    Returns:
        Total edge violation count.
    """
    penalty = 0.0
    for ref, (x, y, _rot) in positions.items():
        if x < margin or x > board_width - margin:
            penalty += 1.0
        if y < margin or y > board_height - margin:
            penalty += 1.0
    return penalty


# ---------------------------------------------------------------------------
# Composite loss
# ---------------------------------------------------------------------------


def compute_placement_loss(
    positions: dict[str, tuple[float, float, float]],
    graph: PlacementGraph,
    board_width: float,
    board_height: float,
    min_clearance: float = 1.0,
) -> dict[str, float]:
    """Compute composite placement loss.

    Returns:
        Dict with hpwl, overlap_area, edge_penalty, and total_loss.
        total_loss = hpwl + 10.0 * overlap_area + 5.0 * edge_penalty.
    """
    hpwl = compute_hpwl(positions, graph)
    overlap = compute_overlap_area(positions, graph, min_clearance)
    edge = compute_edge_penalty(positions, board_width, board_height)

    total = hpwl + 10.0 * overlap + 5.0 * edge

    return {
        "hpwl": hpwl,
        "overlap_area": overlap,
        "edge_penalty": edge,
        "total_loss": total,
    }


# ---------------------------------------------------------------------------
# GRPO reward
# ---------------------------------------------------------------------------


def placement_reward(
    predicted: dict[str, tuple[float, float, float]],
    reference: dict[str, tuple[float, float, float]] | None,
    graph: PlacementGraph,
    board_width: float,
    board_height: float,
) -> float:
    """Compute reward in [0, 1] for GRPO training.

    Three components:
    - Position accuracy (0.3 weight): distance to reference if available.
    - Wirelength quality (0.4 weight): HPWL normalized by board diagonal * n_comp.
    - Clearance score (0.3 weight): 1.0 if no violations, decreasing with count.

    Args:
        predicted: Predicted positions (ref -> (x, y, rot)).
        reference: Ground truth positions, or None.
        graph: PlacementGraph for net connectivity.
        board_width: Board width in mm.
        board_height: Board height in mm.

    Returns:
        Reward in [0, 1].
    """
    diagonal = math.hypot(board_width, board_height)
    n_comp = len(predicted)

    # --- Position accuracy (0.3 weight) ---
    accuracy_score = 0.0
    if reference and n_comp > 0:
        total_dist = 0.0
        count = 0
        for ref in predicted:
            if ref in reference:
                px, py, _ = predicted[ref]
                rx, ry, _ = reference[ref]
                dist = math.hypot(px - rx, py - ry)
                total_dist += dist
                count += 1
        if count > 0:
            avg_dist = total_dist / count
            # Normalize by diagonal, invert to score
            accuracy_score = max(0.0, 1.0 - avg_dist / diagonal)

    # --- Wirelength quality (0.4 weight) ---
    hpwl = compute_hpwl(predicted, graph)
    if n_comp > 0 and diagonal > 0:
        normalized_hpwl = hpwl / (diagonal * n_comp)
        wire_score = max(0.0, 1.0 - min(normalized_hpwl, 1.0))
    else:
        wire_score = 1.0

    # --- Clearance score (0.3 weight) ---
    overlap = compute_overlap_area(predicted, graph)
    if overlap > 0 and n_comp > 0:
        # Scale by component count: more overlap per component = worse
        overlap_per_comp = overlap / n_comp
        clearance_score = max(0.0, 1.0 - min(overlap_per_comp * 2.0, 1.0))
    else:
        clearance_score = 1.0

    # Weighted combination
    reward = 0.3 * accuracy_score + 0.4 * wire_score + 0.3 * clearance_score
    return max(0.0, min(1.0, reward))
