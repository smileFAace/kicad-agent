"""Resolve each violation position to a net name.

For each unconnected_wire_endpoint violation:
1. Find the wire containing this endpoint
2. Trace the connected end (other endpoint) through labels, pins, and junctions
3. Return the net name

This is the critical safety step: knowing the net name ensures we only
connect to pins on the same net.

Usage:
    from kicad_agent.schematic_routing.net_resolver import resolve_violation_nets

    resolved = resolve_violation_nets(violations, net_index, pin_index, sch_dir)
    # resolved: [{x, y, sheet, net_name, wire_endpoint, file}, ...]
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from kicad_agent.schematic_routing.schematic_graph import SchematicGraph


def resolve_violation_nets(
    violations: list[dict],
    net_index: dict[str, list[tuple[str, str]]],
    pin_index: dict[tuple[str, str], str],
    sch_dir: Path,
) -> list[dict]:
    """Resolve each violation's net name by tracing connected wires.

    Args:
        violations: List of violation dicts with x, y, sheet, description, uuid.
        net_index: {net_name: [(ref, pin), ...]} from netlist parser.
        pin_index: {(ref, pin): net_name} reverse index from netlist parser.
        sch_dir: Directory containing sub-sheet .kicad_sch files.

    Returns:
        List of resolved violations with added net_name, wire_endpoint, and file fields.
    """
    # Parse all sub-sheets once
    sheets = _load_sub_sheets(sch_dir)

    resolved = []

    for v in violations:
        pos = _round_pos((v["x"], v["y"]))

        # Search ALL sub-sheets for this violation position.
        # ERC reports all violations under root sheet "/" for hierarchical designs,
        # but the actual wires live in sub-sheet files.
        graph = _find_graph_by_position(pos, sheets)
        if not graph:
            resolved.append(_unresolved(v))
            continue

        # Trace the endpoint to its net
        net_name = graph.trace_endpoint_to_net(pos, pin_index)

        resolved_v = dict(v)
        resolved_v["net_name"] = net_name
        resolved_v["file"] = graph.filepath

        # Find the specific wire for this endpoint
        wire = graph.find_wire_at(pos)
        if wire:
            resolved_v["wire"] = wire

        resolved.append(resolved_v)

    return resolved


def _round_pos(pos: tuple[float, float]) -> tuple[float, float]:
    return (round(pos[0], 2), round(pos[1], 2))


def _unresolved(v: dict) -> dict:
    """Mark a violation as unresolved."""
    result = dict(v)
    result["net_name"] = None
    result["file"] = ""
    return result


def _find_graph_by_position(
    pos: tuple[float, float],
    sheets: dict[str, SchematicGraph],
) -> Optional[SchematicGraph]:
    """Find which sub-sheet graph contains a wire endpoint at this position."""
    for name, graph in sheets.items():
        # Check if any wire endpoint matches this position
        wire_eps = graph.wire_endpoints if hasattr(graph, 'wire_endpoints') else {}
        # Build endpoint index on the fly
        for wire in graph.wires:
            if _round_pos(wire.start) == pos or _round_pos(wire.end) == pos:
                return graph
    return None


def _load_sub_sheets(sch_dir: Path) -> dict[str, SchematicGraph]:
    """Load all sub-sheet .kicad_sch files."""
    sheets: dict[str, SchematicGraph] = {}
    for f in sch_dir.glob("*.kicad_sch"):
        # Skip board files (root schematics)
        if "board" in f.name.lower():
            continue
        graph = SchematicGraph.from_file(f)
        sheets[f.stem.lower()] = graph
    return sheets


def _find_sheet_graph(
    sheet_path: str,
    sheets: dict[str, SchematicGraph],
    sch_dir: Path,
) -> Optional[SchematicGraph]:
    """Find the SchematicGraph for a sheet path.

    Sheet paths from ERC JSON look like: "/", "/EQ Stage/", "/Preamp Stage/"
    Sub-sheet files are named like: eq-stage.kicad_sch, preamp-stage.kicad_sch
    """
    # Normalize: strip slashes, lowercase, replace spaces with hyphens
    normalized = sheet_path.strip("/").lower().replace(" ", "-")

    if not normalized:
        # Root sheet — try to find it
        for name in ("analog-board", "digital-board"):
            if name in sheets:
                return sheets[name]
        return None

    # Direct match
    if normalized in sheets:
        return sheets[normalized]

    # Partial match
    for name, graph in sheets.items():
        if normalized in name or name in normalized:
            return graph

    # Try with common suffixes
    for suffix in ("-stage", "-dac", "-audio", "-analog", "-digital"):
        candidate = normalized + suffix
        if candidate in sheets:
            return sheets[candidate]
        candidate = normalized.replace("-stage", suffix)
        if candidate in sheets:
            return sheets[candidate]

    return None
