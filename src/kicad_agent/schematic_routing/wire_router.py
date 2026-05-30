"""Generate wire modifications from routing targets.

For each RoutingTarget, produces either:
  - same_axis: modify existing wire endpoint coordinate
  - l_shape: keep existing wire, add new wire segment(s)

All coordinates snapped to 2.54mm grid.

Usage:
    from kicad_agent.schematic_routing.wire_router import generate_fixes

    fixes = generate_fixes(targets, grid=2.54)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from kicad_agent.schematic_routing.target_finder import RoutingTarget


@dataclass
class WireFix:
    """A wire modification to apply."""
    file: str
    fix_type: str  # "extend" (modify existing wire) or "new_segment" (add wire)
    old_endpoint: tuple[float, float]  # Original endpoint to change (from file, not ERC)
    new_endpoint: tuple[float, float]  # New endpoint (same_axis only)
    new_wire_points: Optional[list[tuple[float, float]]] = None  # For L-shaped routing
    net_name: str = ""
    target_ref: str = ""
    target_pin: str = ""
    distance: float = 0.0
    sheet: str = ""
    wire_endpoints: Optional[tuple[tuple[float, float], tuple[float, float]]] = None  # Actual wire coords from file


def generate_fixes(
    targets: list[RoutingTarget],
    grid: float = 2.54,
) -> list[WireFix]:
    """Generate wire fixes from routing targets.

    Args:
        targets: Routing targets from target_finder.
        grid: Grid spacing in mm for coordinate snapping.

    Returns:
        List of WireFix objects ready to apply.
    """
    fixes = []

    for target in targets:
        # Use exact target pin coordinates (already at correct position)
        target_pos = (round(target.target_x, 2), round(target.target_y, 2))
        violation_pos = (round(target.violation_x, 2), round(target.violation_y, 2))

        # Pass actual wire endpoints from the file for safe replacement
        wire_eps = None
        if target.wire_start and target.wire_end:
            wire_eps = (target.wire_start, target.wire_end)

        if target.routing_type == "same_axis":
            # Just extend the existing wire to the target pin
            fixes.append(WireFix(
                file=target.file,
                fix_type="extend",
                old_endpoint=violation_pos,
                new_endpoint=target_pos,
                net_name=target.net_name,
                target_ref=target.target_ref,
                target_pin=target.target_pin,
                distance=target.distance,
                sheet=target.sheet,
                wire_endpoints=wire_eps,
            ))

        elif target.routing_type == "l_shape":
            # L-shaped routing disabled for safety — same_axis only for now.
            # L-shaped routing creates new wire segments that can introduce
            # wire_dangling and endpoint_off_grid violations.
            pass

    return fixes


def _snap_to_grid(pos: tuple[float, float], grid: float) -> tuple[float, float]:
    """Snap coordinates to nearest grid point.

    Uses floor(x/grid + 0.5) instead of round() to avoid banker's rounding
    which incorrectly snaps already-on-grid values (e.g., 59.69/2.54=23.5 → 24).
    """
    def snap(v: float) -> float:
        nearest = int(v / grid + 0.5)
        return round(nearest * grid, 2)

    return (snap(pos[0]), snap(pos[1]))


def _round_pos(pos: tuple[float, float]) -> tuple[float, float]:
    """Round position for comparison."""
    return (round(pos[0], 2), round(pos[1], 2))
