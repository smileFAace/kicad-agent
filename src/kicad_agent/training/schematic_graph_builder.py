"""Schematic-only graph construction from .kicad_sch files.

Builds connectivity graphs from schematics without requiring a PCB.
Uses net labels (local, global, hierarchical), wire segments, and
power symbols to determine component connectivity.

This unlocks training data from the large set of .kicad_sch files
that have no matching .kicad_pcb -- providing design topology
knowledge (how circuits are connected) without spatial layout data.

Usage:
    from kicad_agent.training.schematic_graph_builder import build_schematic_graph

    result = build_schematic_graph(sch_path=Path("board.kicad_sch"), sample_id=0)
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx

from kicad_agent.ir.base import _ir_registry
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.parser.schematic_parser import parse_schematic

# Reuse version detection from graph_builder
from kicad_agent.training.graph_builder import (
    MIN_KICAD_VERSION,
    detect_kicad_version,
    is_likely_parseable,
)

logger = logging.getLogger(__name__)

# Tolerance for coordinate matching (mm). KiCad uses 0.001mm precision.
_COORD_TOLERANCE = 0.01


@dataclass(frozen=True)
class SchematicGraphResult:
    """Result of building a graph from a schematic file alone.

    All fields are primitives or JSON strings for JSONL serialization.

    Attributes:
        sample_id: Sequential index in dataset.
        repo_url: Source repository URL.
        repo_name: Source repository full name.
        schematic_path: Path to schematic file.
        pcb_path: Always empty for schematic-only.
        component_count: Number of component nodes in the graph.
        net_count: Number of unique nets in the graph.
        layer_count: Always 0 for schematic-only.
        board_width_mm: Always 0.0 for schematic-only.
        board_height_mm: Always 0.0 for schematic-only.
        difficulty: "easy" (<10 components), "medium" (10-50), "hard" (50+).
        board_hash: SHA256 hex digest of raw schematic content.
        graph_json: networkx graph serialized as JSON (node-link-data).
        spatial_summary_json: JSON with schematic spatial feature counts.
        has_pcb: Always False.
        source_format: Always "kicad_sch".
    """

    sample_id: int
    repo_url: str
    repo_name: str
    schematic_path: str
    pcb_path: str
    component_count: int
    net_count: int
    layer_count: int
    board_width_mm: float
    board_height_mm: float
    difficulty: str
    board_hash: str
    graph_json: str
    spatial_summary_json: str
    has_pcb: bool
    source_format: str


def _grade_difficulty(component_count: int) -> str:
    if component_count < 10:
        return "easy"
    if component_count <= 50:
        return "medium"
    return "hard"


def _coords_match(x1: float, y1: float, x2: float, y2: float) -> bool:
    """Check if two (x,y) coordinates are within tolerance."""
    return abs(x1 - x2) < _COORD_TOLERANCE and abs(y1 - y2) < _COORD_TOLERANCE


def _build_net_connectivity(sch_ir: SchematicIR) -> dict[str, set[str]]:
    """Build net→{component_refs} mapping from schematic labels, wires, and power symbols.

    Algorithm:
    1. Union-Find over ALL coordinates: wire endpoints, pin positions, label positions
    2. Wire segments union their start/end coords
    3. Pin positions union with matching wire/label coords (within tolerance)
    4. Net names assigned from labels, propagated via union-find
    5. Power symbols resolved into power nets

    Returns:
        Dict mapping net_name -> set of component references on that net.
    """
    sch = sch_ir.schematic

    # Collect all coordinates from pins, wires, and labels
    pin_positions = sch_ir.get_pin_positions()
    wire_endpoints = sch_ir.get_wire_endpoints()
    label_positions = sch_ir.get_label_positions()

    # Snap tolerance: KiCad standard pin pitch is 2.54mm
    _SNAP_TOLERANCE = 2.55

    # Union-Find over rounded coordinates
    parent: dict[tuple[float, float], tuple[float, float]] = {}

    def find(coord: tuple[float, float]) -> tuple[float, float]:
        if coord not in parent:
            parent[coord] = coord
        while parent[coord] != coord:
            parent[coord] = parent[parent[coord]]  # path compression
            coord = parent[coord]
        return coord

    def union(a: tuple[float, float], b: tuple[float, float]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Step 1: Union all wire endpoints (builds the wire connectivity graph)
    wire_coords: set[tuple[float, float]] = set()
    for wire in wire_endpoints:
        start = (round(wire["start_x"], 2), round(wire["start_y"], 2))
        end = (round(wire["end_x"], 2), round(wire["end_y"], 2))
        union(start, end)
        wire_coords.add(start)
        wire_coords.add(end)

    # Step 2: Snap pin positions to nearest wire/label coordinate within tolerance
    # This handles KiCad's pin origin vs connection point offset
    coord_pins: dict[tuple[float, float], list[tuple[str, str]]] = {}

    for pin in pin_positions:
        ref = pin["reference"]
        if ref.startswith("#"):
            continue
        pin_num = pin.get("pin_number", "")
        px = round(pin["x"], 2)
        py = round(pin["y"], 2)
        pin_coord = (px, py)

        # Find nearest wire coordinate within snap tolerance
        snapped = pin_coord
        best_dist = _SNAP_TOLERANCE

        for wc in wire_coords:
            dist = abs(wc[0] - px) + abs(wc[1] - py)  # Manhattan distance
            if dist < best_dist:
                best_dist = dist
                snapped = wc

        # Union the pin's actual position with its snapped position
        union(pin_coord, snapped)

        if pin_coord not in coord_pins:
            coord_pins[pin_coord] = []
        coord_pins[pin_coord].append((ref, pin_num))

    # Step 3: Union label positions with wire network
    # Labels at wire endpoints inherit connectivity
    label_nets: dict[tuple[float, float], str] = {}
    for label_info in label_positions:
        lx = round(label_info["x"], 2)
        ly = round(label_info["y"], 2)
        label_coord = (lx, ly)
        union(label_coord, label_coord)
        label_nets[label_coord] = label_info["name"]

    # Step 4: Propagate net names through union-find
    # For each root, collect all net names from labels in that group
    root_to_nets: dict[tuple[float, float], set[str]] = {}
    for label_coord, net_name in label_nets.items():
        root = find(label_coord)
        if root not in root_to_nets:
            root_to_nets[root] = set()
        root_to_nets[root].add(net_name)

    # Step 5: Assign pins to nets based on connectivity
    net_to_refs: dict[str, set[str]] = {}

    for pin_coord, pins_at_coord in coord_pins.items():
        root = find(pin_coord)
        nets = root_to_nets.get(root, set())

        for net_name in nets:
            if net_name not in net_to_refs:
                net_to_refs[net_name] = set()
            for ref, _pin_num in pins_at_coord:
                net_to_refs[net_name].add(ref)

    # Also check if pin coord matches a label coord directly
    for pin_coord, pins_at_coord in coord_pins.items():
        if pin_coord in label_nets:
            net_name = label_nets[pin_coord]
            if net_name not in net_to_refs:
                net_to_refs[net_name] = set()
            for ref, _ in pins_at_coord:
                net_to_refs[net_name].add(ref)

    # Step 6: Resolve power symbols
    for sym in sch.schematicSymbols:
        lib_id = sym.libId
        if not lib_id.startswith("power:"):
            continue
        power_net = lib_id[6:]

        sym_x = round(sym.position.X, 2)
        sym_y = round(sym.position.Y, 2)
        sym_coord = (sym_x, sym_y)
        union(sym_coord, sym_coord)

        # Assign power net to this coordinate
        root = find(sym_coord)
        if root not in root_to_nets:
            root_to_nets[root] = set()
        root_to_nets[root].add(power_net)

        # Find any pins connected to this power symbol via wires
        for pin_coord, pins_at_coord in coord_pins.items():
            pin_root = find(pin_coord)
            if pin_root == root:
                if power_net not in net_to_refs:
                    net_to_refs[power_net] = set()
                for ref, _ in pins_at_coord:
                    net_to_refs[power_net].add(ref)

    return net_to_refs


def build_schematic_graph(
    sch_path: Path,
    sample_id: int = 0,
    repo_url: str = "",
    repo_name: str = "",
    sch_repo_path: str = "",
) -> SchematicGraphResult | None:
    """Build connectivity graph from a .kicad_sch file alone.

    Parses the schematic, extracts components and net connectivity from
    labels, wires, and power symbols, builds a networkx graph, and
    serializes for training.

    Args:
        sch_path: Path to .kicad_sch file.
        sample_id: Sequential sample index for dataset.
        repo_url: Source repository URL.
        repo_name: Source repository full name.
        sch_repo_path: Relative path within repo.

    Returns:
        SchematicGraphResult with connectivity graph, or None on parse failure.
    """
    _registered_ids: set[int] = set()
    try:
        # 1. Read raw content
        sch_bytes = sch_path.read_bytes()
        sch_text = sch_bytes.decode("utf-8", errors="replace")

        # 2. Validate
        if not is_likely_parseable(sch_text):
            logger.warning("Skipping unparseable schematic: %s", sch_path)
            return None

        sch_ver = detect_kicad_version(sch_text)
        if sch_ver is None or sch_ver < MIN_KICAD_VERSION:
            logger.warning(
                "Skipping unsupported KiCad version: sch=%s (need >=%d)",
                sch_ver, MIN_KICAD_VERSION,
            )
            return None

        # 3. Hash for dedup
        board_hash = hashlib.sha256(sch_bytes).hexdigest()

        # 4. Parse schematic
        sch_result = parse_schematic(sch_path)
        _registered_ids.add(id(sch_result))
        sch_ir = SchematicIR(_parse_result=sch_result)

        # 5. Build connectivity
        net_to_refs = _build_net_connectivity(sch_ir)

        # 6. Build graph
        G = nx.Graph()

        # 6a. Add component nodes
        for sym in sch_ir.components:
            ref = ""
            value = ""
            footprint = ""
            lib_id = sym.libId

            for prop in sym.properties:
                if prop.key == "Reference":
                    ref = prop.value
                elif prop.key == "Value":
                    value = prop.value
                elif prop.key == "Footprint":
                    footprint = prop.value

            if not ref or ref.startswith("#"):
                continue  # skip power flags

            G.add_node(
                ref,
                node_type="component",
                value=value,
                footprint=footprint,
                lib_id=lib_id,
            )

            # Add schematic position
            G.nodes[ref]["x_mm"] = sym.position.X
            G.nodes[ref]["y_mm"] = sym.position.Y
            G.nodes[ref]["rotation_deg"] = sym.position.angle or 0.0

        # 6b. Add net edges
        for net_name, component_refs in net_to_refs.items():
            refs_list = sorted(component_refs)
            for i in range(len(refs_list)):
                for j in range(i + 1, len(refs_list)):
                    G.add_edge(refs_list[i], refs_list[j], net=net_name)

        # 7. Compute metadata
        component_count = sum(
            1 for _, attrs in G.nodes(data=True)
            if attrs.get("node_type") == "component"
        )
        net_count = len(net_to_refs)
        difficulty = _grade_difficulty(component_count)

        # 8. Spatial summary (schematic coordinates)
        all_x = [attrs["x_mm"] for _, attrs in G.nodes(data=True) if "x_mm" in attrs]
        all_y = [attrs["y_mm"] for _, attrs in G.nodes(data=True) if "y_mm" in attrs]

        spatial_summary: dict[str, Any] = {
            "point_count": component_count,
            "source": "schematic",
        }
        if all_x and all_y:
            spatial_summary["min_x"] = min(all_x)
            spatial_summary["max_x"] = max(all_x)
            spatial_summary["min_y"] = min(all_y)
            spatial_summary["max_y"] = max(all_y)

        # 9. Serialize
        graph_data = nx.node_link_data(G)
        graph_json = json.dumps(graph_data, sort_keys=True)

        sch_path_str = sch_repo_path if sch_repo_path else str(sch_path)

        # Clean up IR registry
        _ir_registry.difference_update(_registered_ids)

        return SchematicGraphResult(
            sample_id=sample_id,
            repo_url=repo_url,
            repo_name=repo_name,
            schematic_path=sch_path_str,
            pcb_path="",
            component_count=component_count,
            net_count=net_count,
            layer_count=0,
            board_width_mm=0.0,
            board_height_mm=0.0,
            difficulty=difficulty,
            board_hash=board_hash,
            graph_json=graph_json,
            spatial_summary_json=json.dumps(spatial_summary, sort_keys=True),
            has_pcb=False,
            source_format="kicad_sch",
        )

    except (ValueError, OSError, KeyError, AttributeError, RuntimeError) as e:
        _ir_registry.difference_update(_registered_ids)
        logger.warning("Failed to build schematic graph for %s: %s", sch_path, e)
        return None
    except Exception as e:
        _ir_registry.difference_update(_registered_ids)
        logger.warning(
            "Unexpected error building schematic graph for %s: %s",
            sch_path, e, exc_info=True,
        )
        return None
