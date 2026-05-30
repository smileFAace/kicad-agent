"""Find nearest same-net pin targets for each violation.

For each resolved violation (with a known net name), find the nearest pin
on the same net that the wire could be extended to reach. Classify the
routing type (same_axis extension vs L-shaped routing).

Safety: targets are verified to be on the same net via netlist cross-reference.

Usage:
    from kicad_agent.schematic_routing.target_finder import find_targets

    targets = find_targets(resolved, net_index, pin_index, sch_dir, max_distance=25.4)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from kicad_agent.schematic_routing.netlist_parser import get_nets_for_sheet
from kicad_agent.schematic_routing.schematic_graph import SchematicGraph, _round_pos


@dataclass
class RoutingTarget:
    """A pin target that a wire endpoint can be routed to."""
    violation_x: float
    violation_y: float
    target_x: float
    target_y: float
    net_name: str
    target_ref: str
    target_pin: str
    distance: float
    routing_type: str  # "same_axis", "l_shape", "too_far"
    file: str
    sheet: str
    wire_start: Optional[tuple[float, float]] = None  # Actual wire start from file
    wire_end: Optional[tuple[float, float]] = None     # Actual wire end from file


def find_targets(
    resolved: list[dict],
    net_index: dict[str, list[tuple[str, str]]],
    pin_index: dict[tuple[str, str], str],
    sch_dir: Path,
    max_distance: float = 25.4,
) -> list[RoutingTarget]:
    """Find routing targets for resolved violations.

    Args:
        resolved: Violations with net_name, file fields (from net_resolver).
        net_index: {net_name: [(ref, pin), ...]} from netlist.
        pin_index: {(ref, pin): net_name} reverse index.
        sch_dir: Directory with sub-sheet files.
        max_distance: Max distance (mm) to consider a target reachable.

    Returns:
        List of RoutingTarget with routing type classification.
    """
    from kicad_agent.schematic_routing.net_resolver import _load_sub_sheets

    sheets = _load_sub_sheets(sch_dir)
    targets = []

    for v in resolved:
        net_name = v.get("net_name")
        if not net_name:
            continue

        # Get all pins on this net from the netlist
        net_pins = net_index.get(net_name, [])

        # Find the sub-sheet graph — use the file path from net_resolver
        # (ERC sheet paths are "/" for all violations in hierarchical designs)
        graph = _find_graph_by_file(v.get("file", ""), sheets)
        if not graph:
            continue

        # Get sheet's component refs for filtering
        sheet_refs = graph.get_sheet_refs()

        # Find pin positions on this net that are in this sheet
        violation_pos = (v["x"], v["y"])

        # Get actual wire data from the resolved violation
        wire = v.get("wire")
        wire_start = wire.start if wire else None
        wire_end = wire.end if wire else None

        best_target: Optional[RoutingTarget] = None
        best_dist = float("inf")

        # Strategy 1: Netlist pins (most reliable)
        for ref, pin_num in net_pins:
            # Only consider pins in the same sheet
            if ref not in sheet_refs:
                continue

            # Find this pin's position in the graph
            pin_pos = _find_pin_position(graph, ref, pin_num)
            if pin_pos is None:
                continue

            # Skip if this is the pin the wire is already (almost) touching
            if _round_pos(pin_pos) == _round_pos(violation_pos):
                continue

            # Calculate distance
            dist = _distance(violation_pos, pin_pos)

            if dist < best_dist and dist <= max_distance:
                best_dist = dist
                routing = _classify_routing(violation_pos, pin_pos)
                best_target = RoutingTarget(
                    violation_x=v["x"],
                    violation_y=v["y"],
                    target_x=pin_pos[0],
                    target_y=pin_pos[1],
                    net_name=net_name,
                    target_ref=ref,
                    target_pin=pin_num,
                    distance=dist,
                    routing_type=routing,
                    file=v.get("file", ""),
                    sheet=v["sheet"],
                    wire_start=wire_start,
                    wire_end=wire_end,
                )

        # Strategy 2: Same-name labels in the same sub-sheet
        # For nets not in the netlist (incomplete connections), labels define the net
        if not best_target:
            for label in graph.labels:
                if label.name != net_name:
                    continue
                label_pos = _round_pos(label.position)
                if label_pos == _round_pos(violation_pos):
                    continue
                dist = _distance(violation_pos, label_pos)
                if dist < best_dist and dist <= max_distance:
                    best_dist = dist
                    routing = _classify_routing(violation_pos, label_pos)
                    best_target = RoutingTarget(
                        violation_x=v["x"],
                        violation_y=v["y"],
                        target_x=label_pos[0],
                        target_y=label_pos[1],
                        net_name=net_name,
                        target_ref=f"label:{label.name}",
                        target_pin="",
                        distance=dist,
                        routing_type=routing,
                        file=v.get("file", ""),
                        sheet=v["sheet"],
                        wire_start=wire_start,
                        wire_end=wire_end,
                    )

        if best_target:
            targets.append(best_target)

    return targets


def _find_graph_by_file(
    filepath: str,
    sheets: dict[str, SchematicGraph],
) -> Optional[SchematicGraph]:
    """Find a SchematicGraph by its file path."""
    if not filepath:
        return None
    stem = Path(filepath).stem.lower()
    return sheets.get(stem)


def _find_pin_position(graph: SchematicGraph, ref: str, pin_number: str) -> Optional[tuple[float, float]]:
    """Find the wire-end position of a specific pin in a graph."""
    for pin in graph.pins:
        if pin.ref == ref and pin.pin_number == pin_number:
            return pin.position
    return None


def _distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def _classify_routing(
    start: tuple[float, float],
    end: tuple[float, float],
) -> str:
    """Classify the routing type needed.

    - same_axis: endpoint and target share x or y → straight extension
    - l_shape: need a bend → intermediate point needed
    """
    dx = abs(start[0] - end[0])
    dy = abs(start[1] - end[1])

    # If one axis aligns (within 1.27mm = half grid unit), it's a straight extension.
    # KiCad considers pins connected within this tolerance.
    if dx < 1.27 or dy < 1.27:
        return "same_axis"
    return "l_shape"
