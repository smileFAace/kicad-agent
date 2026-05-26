"""Routing Elegance Score (RES) — composite quality metric for PCB routing.

Computes a 0..1 score from 6 weighted sub-scores using spatial primitives
extracted from PcbIR data:

    RES = 0.20*DENSITY + 0.25*EFFICIENCY + 0.20*CLEANLINESS
        + 0.15*UNIFORMITY + 0.10*PLANARITY + 0.10*COMPLIANCE

Score interpretation:
    0.8 - 1.0  Professional / Gold Standard
    0.6 - 0.8  Competent
    0.4 - 0.6  Intermediate
    0.2 - 0.4  Amateur
    0.0 - 0.2  Broken / Trivial

Usage:
    from kicad_agent.training.routing_quality import compute_routing_quality

    result = compute_routing_quality(pcb_ir)
    print(f"RES: {result.elegance_score:.3f}")
    print(f"Density: {result.component_density:.3f}")
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any

from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.spatial.extractor import extract_all
from kicad_agent.spatial.primitives import SpatialBox, SpatialPath, SpatialPoint


@dataclass(frozen=True)
class RoutingQualityFeatures:
    """21-field feature vector describing PCB routing quality.

    All density metrics are per mm^2. All ratios are 0..1 unless noted.
    """

    # Density features (6)
    component_density: float  # components/mm^2
    via_density: float  # vias/mm^2
    trace_density: float  # mm_trace/mm^2_board
    active_area_ratio: float  # populated_area / total_area
    component_size_cv: float  # size coefficient of variation
    pad_density: float  # pads/mm^2

    # Efficiency features (4)
    manhattan_efficiency: float  # mean(manhattan/actual) for all segments
    mean_trace_length: float  # mm
    total_routed_length: float  # mm
    trace_length_cv: float  # length variation coefficient

    # Cleanliness features (3)
    right_angle_ratio: float  # 90-deg bends / total segments
    acute_angle_ratio: float  # <90-deg angles / total segments
    stub_ratio: float  # dead-end stubs / total segments

    # Uniformity features (3)
    clearance_cv: float  # clearance variation
    trace_width_cv: float  # width variation
    via_size_uniformity: float  # 1 - CV of via sizes

    # Planarity features (3)
    layer_count: int  # total signal layers with routing
    layer_balance_cv: float  # routing per layer variation
    has_ground_plane: bool  # solid ground plane present

    # Compliance features (2)
    drc_pass: bool  # whether board passes structural checks
    net_class_compliance: float  # fraction of nets with consistent widths

    # Composite
    elegance_score: float  # RES composite (0..1)


def _board_area_from_boxes(boxes: list[SpatialBox]) -> float:
    """Estimate board area from the union of footprint bounding boxes.

    Falls back to bounding box of all content if no Edge.Cuts available.
    """
    if not boxes:
        return 1.0  # avoid division by zero

    xs: list[float] = []
    ys: list[float] = []
    for b in boxes:
        xs.extend([b.x1, b.x2])
        ys.extend([b.y1, b.y2])

    width = max(xs) - min(xs) if xs else 1.0
    height = max(ys) - min(ys) if ys else 1.0
    return max(width * height, 1.0)


def _cv(values: list[float]) -> float:
    """Coefficient of variation (std/mean). Returns 0 for empty/single."""
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    return statistics.stdev(values) / mean


def _path_length(path: SpatialPath) -> float:
    """Compute total length of a spatial path."""
    pts = path.points
    if len(pts) < 2:
        return 0.0
    total = 0.0
    for i in range(len(pts) - 1):
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        total += math.sqrt(dx * dx + dy * dy)
    return total


def _manhattan_length(path: SpatialPath) -> float:
    """Manhattan distance between first and last point."""
    pts = path.points
    if len(pts) < 2:
        return 0.0
    dx = abs(pts[-1][0] - pts[0][0])
    dy = abs(pts[-1][1] - pts[0][1])
    return dx + dy


def _segment_angle(path: SpatialPath) -> list[float]:
    """Compute angles (degrees) between consecutive segments in a path."""
    pts = path.points
    if len(pts) < 3:
        return []

    angles: list[float] = []
    for i in range(len(pts) - 2):
        v1x = pts[i + 1][0] - pts[i][0]
        v1y = pts[i + 1][1] - pts[i][1]
        v2x = pts[i + 2][0] - pts[i + 1][0]
        v2y = pts[i + 2][1] - pts[i + 1][1]

        dot = v1x * v2x + v1y * v2y
        cross = v1x * v2y - v1y * v2x
        angle = math.degrees(math.atan2(abs(cross), dot))
        angles.append(angle)

    return angles


def _box_area(box: SpatialBox) -> float:
    return (box.x2 - box.x1) * (box.y2 - box.y1)


# ---------------------------------------------------------------------------
# Sub-score computation
# ---------------------------------------------------------------------------


def _density_score(
    boxes: list[SpatialBox],
    points: list[SpatialPoint],
    paths: list[SpatialPath],
    board_area: float,
) -> tuple[float, float, float, float, float, float]:
    """Compute density sub-score and individual density features.

    Returns (score, component_density, via_density, trace_density,
              active_area_ratio, pad_density).
    """
    n_components = len(boxes)
    n_vias = sum(1 for p in points if p.entity_type == "via")
    n_pads = sum(1 for p in points if p.entity_type == "pad")
    total_trace_length = sum(_path_length(p) for p in paths)

    comp_density = n_components / board_area
    via_dens = n_vias / board_area
    trace_dens = total_trace_length / board_area
    pad_dens = n_pads / board_area

    # Active area: union of component bounding boxes (approximated)
    if boxes:
        comp_area = sum(_box_area(b) for b in boxes)
        active_ratio = min(comp_area / board_area, 1.0)
    else:
        active_ratio = 0.0

    # Normalize against professional ranges
    area_score = min(active_ratio / 0.8, 1.0)  # 0.7-0.95 pro
    via_score = min(via_dens / 5.0, 1.0)  # 5 vias/mm2 = high density
    trace_score = min(trace_dens / 50.0, 1.0)  # 50mm/mm2 = dense

    score = 0.4 * area_score + 0.3 * via_score + 0.3 * trace_score
    return score, comp_density, via_dens, trace_dens, active_ratio, pad_dens


def _efficiency_score(
    paths: list[SpatialPath],
) -> tuple[float, float, float, float]:
    """Compute efficiency sub-score and features.

    Returns (score, manhattan_efficiency, mean_trace_length,
             total_routed_length, trace_length_cv).
    """
    if not paths:
        return 0.5, 0.0, 0.0, 0.0, 0.0

    manhattan_ratios: list[float] = []
    lengths: list[float] = []

    for path in paths:
        actual = _path_length(path)
        manhattan = _manhattan_length(path)
        lengths.append(actual)

        if actual > 0.01 and manhattan > 0:
            manhattan_ratios.append(min(manhattan / actual, 1.0))

    if not lengths:
        return 0.5, 0.0, 0.0, 0.0, 0.0

    mean_eff = statistics.mean(manhattan_ratios) if manhattan_ratios else 0.5
    total_length = sum(lengths)
    mean_length = statistics.mean(lengths)
    length_cv = _cv(lengths)

    # Pro routing: 0.7-0.95, Amateur: 0.3-0.6
    score = min(mean_eff, 1.0)
    return score, mean_eff, mean_length, total_length, length_cv


def _cleanliness_score(
    paths: list[SpatialPath],
) -> tuple[float, float, float, float]:
    """Compute cleanliness sub-score and features.

    Returns (score, right_angle_ratio, acute_angle_ratio, stub_ratio).
    """
    if not paths:
        return 0.5, 0.0, 0.0, 0.0

    total_angles = 0
    right_angle_count = 0
    acute_angle_count = 0
    stub_count = 0

    for path in paths:
        angles = _segment_angle(path)
        total_angles += len(angles)

        for a in angles:
            # Right angle: 85-95 degrees
            if 85 <= a <= 95:
                right_angle_count += 1
            # Acute angle: < 45 degrees (harsh bends)
            elif a < 45:
                acute_angle_count += 1

        # Stub detection: short dead-end segments
        pts = path.points
        if len(pts) >= 2:
            length = _path_length(path)
            if length < 0.3:  # < 0.3mm = likely a stub
                stub_count += 1

    n_paths = max(len(paths), 1)
    ra_ratio = right_angle_count / max(total_angles, 1)
    acute_ratio = acute_angle_count / max(total_angles, 1)
    stub_ratio = stub_count / n_paths

    # Penalty weighted by severity
    anti_pattern = ra_ratio * 0.3 + acute_ratio * 0.5 + stub_ratio * 0.2
    score = max(0.0, 1.0 - anti_pattern)
    return score, ra_ratio, acute_ratio, stub_ratio


def _uniformity_score(
    points: list[SpatialPoint],
    paths: list[SpatialPath],
) -> tuple[float, float, float]:
    """Compute uniformity sub-score and features.

    Returns (score, clearance_cv, trace_width_cv).
    """
    # Trace width consistency
    widths = [p.width for p in paths if p.width > 0]
    width_cv = _cv(widths)

    # Via size uniformity (approximate: count unique via positions as same size)
    via_points = [p for p in points if p.entity_type == "via"]
    via_uniformity = 1.0 - min(_cv([1.0] * len(via_points)), 1.0) if via_points else 0.5

    # Clearance CV: use spatial engine if available, otherwise approximate
    # from nearest-neighbor distances of pads
    clearance_cv = 0.0
    pad_points = [p for p in points if p.entity_type == "pad"]
    if len(pad_points) >= 2:
        # Sample nearest-neighbor distances (max 200 for performance)
        sample = pad_points[:200]
        nn_dists: list[float] = []
        for i, p1 in enumerate(sample):
            min_dist = float("inf")
            for j, p2 in enumerate(sample):
                if i == j:
                    continue
                dx = p1.x - p2.x
                dy = p1.y - p2.y
                d = math.sqrt(dx * dx + dy * dy)
                if d < min_dist:
                    min_dist = d
            if min_dist < float("inf"):
                nn_dists.append(min_dist)

        clearance_cv = _cv(nn_dists)

    clearance_score = max(0.0, 1.0 - clearance_cv)
    width_score = max(0.0, 1.0 - width_cv)

    score = 0.6 * clearance_score + 0.4 * width_score
    return score, clearance_cv, width_cv


def _planarity_score(
    pcb_ir: PcbIR,
    paths: list[SpatialPath],
) -> tuple[float, int, float, bool]:
    """Compute planarity sub-score and features.

    Returns (score, layer_count, layer_balance_cv, has_ground_plane).
    """
    # Count unique layers with routing
    layer_lengths: dict[str, float] = {}
    for p in paths:
        layer = p.layer or "unknown"
        layer_lengths[layer] = layer_lengths.get(layer, 0.0) + _path_length(p)

    n_layers = len([l for l, length in layer_lengths.items() if length > 0])

    # Layer balance
    active_lengths = [length for length in layer_lengths.values() if length > 0]
    layer_balance = _cv(active_lengths) if active_lengths else 0.0

    # Ground plane detection: check zones for GND net
    has_ground = False
    try:
        board = pcb_ir.board
        if hasattr(board, "zones"):
            for zone in board.zones:
                net_name = ""
                if hasattr(zone, "netName") and zone.netName:
                    net_name = zone.netName
                if net_name.upper() in ("GND", "GROUND", "AGND", "DGND", "PGND", "Earth"):
                    has_ground = True
                    break
    except Exception:
        pass

    plane_score = 0.2 + (0.5 if has_ground else 0.0)

    # Layer balance score
    if n_layers > 1:
        balance_score = max(0.0, 1.0 - layer_balance * 0.5)
    else:
        balance_score = 0.3

    score = 0.6 * plane_score + 0.4 * balance_score
    return score, n_layers, layer_balance, has_ground


def _compliance_score(
    pcb_ir: PcbIR,
    paths: list[SpatialPath],
    boxes: list[SpatialBox],
) -> tuple[float, bool, float]:
    """Compute compliance sub-score and features.

    Returns (score, drc_pass, net_class_compliance).

    Note: Full DRC requires kicad-cli. Here we do structural checks only.
    """
    # Structural checks
    drc_pass = True
    issues = 0

    # Check for overlapping footprints (bounding box intersection)
    for i in range(len(boxes)):
        for j in range(i + 1, min(i + 50, len(boxes))):  # limit pairs
            b1 = boxes[i]
            b2 = boxes[j]
            if (b1.x1 < b2.x2 and b1.x2 > b2.x1 and
                    b1.y1 < b2.y2 and b1.y2 > b2.y1):
                issues += 1

    if issues > len(boxes) * 0.1:  # >10% overlap = likely DRC fail
        drc_pass = False

    # Net class compliance: traces on same net should have consistent width
    net_widths: dict[str, list[float]] = {}
    for p in paths:
        if p.net and p.width > 0:
            net_widths.setdefault(p.net, []).append(p.width)

    compliant_nets = 0
    total_nets = 0
    for net, widths in net_widths.items():
        total_nets += 1
        if len(widths) < 2:
            compliant_nets += 1
            continue
        mean_w = statistics.mean(widths)
        if mean_w > 0:
            cv = statistics.stdev(widths) / mean_w
            if cv < 0.2:  # <20% variation = compliant
                compliant_nets += 1

    net_compliance = compliant_nets / max(total_nets, 1)

    drc_score = 1.0 if drc_pass else 0.5
    score = 0.6 * drc_score + 0.4 * net_compliance
    return score, drc_pass, net_compliance


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute_routing_quality(pcb_ir: PcbIR) -> RoutingQualityFeatures:
    """Compute the full Routing Elegance Score for a PCB.

    Uses spatial primitives extracted from PcbIR data. No kicad-cli required
    (structural checks only for compliance sub-score).

    Args:
        pcb_ir: PCB intermediate representation with loaded board data.

    Returns:
        RoutingQualityFeatures with 21 metrics + composite RES.
    """
    spatial = extract_all(pcb_ir)
    points: list[SpatialPoint] = spatial["points"]
    boxes: list[SpatialBox] = spatial["boxes"]
    paths: list[SpatialPath] = spatial["paths"]

    board_area = _board_area_from_boxes(boxes)

    # Component size CV
    comp_areas = [_box_area(b) for b in boxes]
    comp_size_cv = _cv(comp_areas)

    # Sub-scores
    density, comp_d, via_d, trace_d, active_r, pad_d = _density_score(
        boxes, points, paths, board_area,
    )
    efficiency, manh_eff, mean_len, total_len, len_cv = _efficiency_score(paths)
    cleanliness, ra_ratio, acute_ratio, stub_r = _cleanliness_score(paths)
    uniformity, clear_cv, width_cv = _uniformity_score(points, paths)
    planarity, n_layers, layer_bal_cv, has_gnd = _planarity_score(pcb_ir, paths)
    compliance, drc_ok, net_comp = _compliance_score(pcb_ir, paths, boxes)

    # Weighted composite
    elegance = (
        0.20 * density
        + 0.25 * efficiency
        + 0.20 * cleanliness
        + 0.15 * uniformity
        + 0.10 * planarity
        + 0.10 * compliance
    )

    return RoutingQualityFeatures(
        component_density=comp_d,
        via_density=via_d,
        trace_density=trace_d,
        active_area_ratio=active_r,
        component_size_cv=comp_size_cv,
        pad_density=pad_d,
        manhattan_efficiency=manh_eff,
        mean_trace_length=mean_len,
        total_routed_length=total_len,
        trace_length_cv=len_cv,
        right_angle_ratio=ra_ratio,
        acute_angle_ratio=acute_ratio,
        stub_ratio=stub_r,
        clearance_cv=clear_cv,
        trace_width_cv=width_cv,
        via_size_uniformity=1.0 - min(_cv([1.0] * sum(1 for p in points if p.entity_type == "via")), 1.0),
        layer_count=n_layers,
        layer_balance_cv=layer_bal_cv,
        has_ground_plane=has_gnd,
        drc_pass=drc_ok,
        net_class_compliance=net_comp,
        elegance_score=elegance,
    )


def features_to_dict(features: RoutingQualityFeatures) -> dict[str, Any]:
    """Convert RoutingQualityFeatures to a JSON-serializable dict."""
    return {
        "component_density": features.component_density,
        "via_density": features.via_density,
        "trace_density": features.trace_density,
        "active_area_ratio": features.active_area_ratio,
        "component_size_cv": features.component_size_cv,
        "pad_density": features.pad_density,
        "manhattan_efficiency": features.manhattan_efficiency,
        "mean_trace_length": features.mean_trace_length,
        "total_routed_length": features.total_routed_length,
        "trace_length_cv": features.trace_length_cv,
        "right_angle_ratio": features.right_angle_ratio,
        "acute_angle_ratio": features.acute_angle_ratio,
        "stub_ratio": features.stub_ratio,
        "clearance_cv": features.clearance_cv,
        "trace_width_cv": features.trace_width_cv,
        "via_size_uniformity": features.via_size_uniformity,
        "layer_count": features.layer_count,
        "layer_balance_cv": features.layer_balance_cv,
        "has_ground_plane": features.has_ground_plane,
        "drc_pass": features.drc_pass,
        "net_class_compliance": features.net_class_compliance,
        "elegance_score": features.elegance_score,
    }


def score_to_label(score: float) -> str:
    """Map RES score to human-readable quality label."""
    if score >= 0.8:
        return "professional"
    if score >= 0.6:
        return "competent"
    if score >= 0.4:
        return "intermediate"
    if score >= 0.2:
        return "amateur"
    return "trivial"
