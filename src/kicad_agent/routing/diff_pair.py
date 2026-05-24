"""Differential pair routing with length matching via accordion serpentining.

Routes both nets of a differential pair using the A* pathfinder, then
equalizes their lengths by adding accordion-shaped serpentine bumps to
the shorter path. Bumps are perpendicular to the path direction at each
segment, with amplitude capped to prevent excessive detours.

Results are immutable DiffPairResult frozen dataclasses.

Usage:
    from kicad_agent.routing.diff_pair import route_differential_pair

    result = route_differential_pair(
        graph, src_p, src_n, tgt_p, tgt_n,
        target_spacing_mm=0.15,
        max_length_mismatch_mm=0.5,
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kicad_agent.routing.pathfinder import route_net


@dataclass(frozen=True)
class DiffPairResult:
    """Immutable result of routing a differential pair.

    Attributes:
        net_positive: Ordered tuple of (x, y) waypoints for the positive net.
        net_negative: Ordered tuple of (x, y) waypoints for the negative net.
        length_positive_mm: Total path length of the positive net in mm.
        length_negative_mm: Total path length of the negative net in mm.
        mismatch_mm: Absolute length difference between the two nets in mm.
        spacing_mm: Target pair spacing used for serpentining.
        valid: True if both nets routed and mismatch is within tolerance.
    """

    net_positive: tuple[tuple[float, float], ...]
    net_negative: tuple[tuple[float, float], ...]
    length_positive_mm: float
    length_negative_mm: float
    mismatch_mm: float
    spacing_mm: float
    valid: bool


def _path_length(path: tuple[tuple[float, float], ...]) -> float:
    """Compute total Euclidean length of a path.

    Args:
        path: Ordered tuple of (x, y) waypoints.

    Returns:
        Sum of Euclidean distances between consecutive points.
    """
    total = 0.0
    for i in range(len(path) - 1):
        total += math.hypot(
            path[i + 1][0] - path[i][0],
            path[i + 1][1] - path[i][1],
        )
    return total


def _interpolate_path(
    path: tuple[tuple[float, float], ...],
    distances: list[float],
) -> list[tuple[float, float]]:
    """Return points at given arc-length distances along the path.

    If a distance exceeds the total path length, the last point is
    returned.

    Args:
        path: Ordered tuple of (x, y) waypoints.
        distances: Sorted list of arc-length distances along the path.

    Returns:
        List of (x, y) points at the requested distances.
    """
    points: list[tuple[float, float]] = []
    seg_idx = 0
    cumulative = 0.0

    for d in distances:
        # Advance to the segment containing distance d.
        while seg_idx < len(path) - 1:
            seg_len = math.hypot(
                path[seg_idx + 1][0] - path[seg_idx][0],
                path[seg_idx + 1][1] - path[seg_idx][1],
            )
            if cumulative + seg_len >= d - 1e-9:
                break
            cumulative += seg_len
            seg_idx += 1

        if seg_idx >= len(path) - 1:
            points.append(path[-1])
            continue

        p0 = path[seg_idx]
        p1 = path[seg_idx + 1]
        seg_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])

        if seg_len < 1e-9:
            points.append(p0)
            continue

        t = max(0.0, min(1.0, (d - cumulative) / seg_len))
        points.append((
            round(p0[0] + t * (p1[0] - p0[0]), 6),
            round(p0[1] + t * (p1[1] - p0[1]), 6),
        ))

    return points


def _direction_at(
    path: tuple[tuple[float, float], ...],
    distance: float,
) -> tuple[float, float, float, float]:
    """Return (ux, uy, px, py) at a given arc-length distance.

    ux, uy = unit direction along the path.
    px, py = perpendicular direction (rotated 90 degrees CCW).

    Args:
        path: Ordered tuple of (x, y) waypoints.
        distance: Arc-length distance along the path.

    Returns:
        Tuple of (ux, uy, px, py) direction components.
    """
    cumulative = 0.0
    for i in range(len(path) - 1):
        seg_len = math.hypot(
            path[i + 1][0] - path[i][0],
            path[i + 1][1] - path[i][1],
        )
        if cumulative + seg_len >= distance - 1e-9 or i == len(path) - 2:
            if seg_len < 1e-9:
                continue
            ux = (path[i + 1][0] - path[i][0]) / seg_len
            uy = (path[i + 1][1] - path[i][1]) / seg_len
            return ux, uy, -uy, ux
        cumulative += seg_len

    # Fallback: use last segment direction.
    if len(path) >= 2:
        p0 = path[-2]
        p1 = path[-1]
        seg_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if seg_len > 1e-9:
            ux = (p1[0] - p0[0]) / seg_len
            uy = (p1[1] - p0[1]) / seg_len
            return ux, uy, -uy, ux

    return 1.0, 0.0, 0.0, 1.0


def _bump_extra_length(amplitude: float, half_w: float) -> float:
    """Compute the extra length added by a single U-shaped bump.

    The bump replaces a straight segment of length ``2 * half_w`` with
    a U-shaped detour: out-perpendicular, advance, return-perpendicular.
    The out and return legs are the hypotenuse of (half_w, amplitude).

    Args:
        amplitude: Perpendicular distance of the bump in mm.
        half_w: Half the bump width along the path in mm.

    Returns:
        Extra length added by the bump beyond the straight segment.
    """
    leg = math.hypot(half_w, amplitude)  # Out-leg: sqrt(hw^2 + amp^2).
    top = 2.0 * half_w                   # Top segment along offset.
    return_leg = amplitude                # Return-leg: straight back.
    bump_total = leg + top + return_leg
    straight = 2.0 * half_w              # Original straight segment.
    return bump_total - straight


def _add_serpentining(
    path: tuple[tuple[float, float], ...],
    target_delta_mm: float,
    spacing_mm: float,
) -> tuple[tuple[float, float], ...]:
    """Add accordion serpentine bumps to a path to increase its length.

    Parameterizes the path by arc length and inserts U-shaped bumps at
    regular intervals. Each bump replaces a straight segment with a
    perpendicular detour. Bumps are capped at ``spacing_mm * 2``
    amplitude and a maximum of 50 bumps total to prevent runaway.

    Uses a measure-and-refine loop: generate bumps at an estimated
    amplitude, measure the actual length change, and adjust. Up to 5
    refinement iterations ensure the target delta is achieved when
    geometrically possible.

    Args:
        path: Original path as ordered tuple of (x, y) waypoints.
        target_delta_mm: Additional length to add in mm.
        spacing_mm: Target pair spacing, used to bound amplitude.

    Returns:
        New path tuple with serpentine bumps inserted.
    """
    if target_delta_mm <= 0 or len(path) < 2:
        return path

    total_len = _path_length(path)
    if total_len < 1e-9:
        return path

    max_amplitude = spacing_mm * 2.0
    max_bumps = 50

    # Bump pitch: distance between bump centers along the path.
    bump_pitch = max(spacing_mm, 0.5)
    half_w = bump_pitch * 0.25  # Half the bump span for U-shape geometry.

    # Determine how many bumps we can fit.
    margin = bump_pitch * 0.5
    usable_length = total_len - 2.0 * margin
    if usable_length < bump_pitch:
        return path

    num_bumps = min(int(usable_length / bump_pitch), max_bumps)
    if num_bumps < 1:
        return path

    # Estimate initial amplitude from the geometric model, then refine.
    # Start with max amplitude as upper bound.
    amplitude = max_amplitude
    # Add a small overshoot (1%) so proportional scaling converges from
    # above rather than asymptotically approaching from below.
    effective_target = target_delta_mm * 1.01

    for _ in range(10):  # Up to 10 refinement iterations.
        # Generate bumps at current amplitude.
        result = _generate_bumps(path, num_bumps, amplitude, bump_pitch,
                                 margin, half_w, total_len)
        actual_delta = _path_length(result) - total_len

        if actual_delta < effective_target - 0.01:
            # Not enough -- increase amplitude (already at max, can't do more).
            if amplitude >= max_amplitude:
                break
            # Scale up amplitude proportionally.
            if actual_delta > 0:
                amplitude = min(
                    max_amplitude,
                    amplitude * (effective_target / actual_delta),
                )
            else:
                amplitude = max_amplitude
        elif actual_delta > effective_target + 0.01:
            # Too much -- reduce amplitude.
            if actual_delta > 0:
                amplitude = max(
                    0.0,
                    amplitude * (effective_target / actual_delta),
                )
            # Don't break -- refine further.
        else:
            # Close enough.
            break

    return _generate_bumps(path, num_bumps, amplitude, bump_pitch,
                           margin, half_w, total_len)


def _generate_bumps(
    path: tuple[tuple[float, float], ...],
    num_bumps: int,
    amplitude: float,
    bump_pitch: float,
    margin: float,
    half_w: float,
    total_len: float,
) -> tuple[tuple[float, float], ...]:
    """Generate serpentine bumps along a path at given amplitude.

    Args:
        path: Original path waypoints.
        num_bumps: Number of bumps to insert.
        amplitude: Perpendicular distance of each bump.
        bump_pitch: Distance between bump centers.
        margin: Start/end margin along the path.
        half_w: Half the bump span for U-shape geometry.
        total_len: Total arc length of the path.

    Returns:
        New path tuple with bumps inserted.
    """
    if amplitude < 1e-9:
        return path

    usable_length = total_len - 2.0 * margin
    spacing_between = usable_length / num_bumps
    bump_positions = [
        margin + spacing_between * (i + 0.5) for i in range(num_bumps)
    ]

    new_points: list[tuple[float, float]] = [path[0]]

    for bp in bump_positions:
        pts = _interpolate_path(path, [bp])
        center = pts[0]

        ux, uy, px, py = _direction_at(path, bp)

        start_pts = _interpolate_path(path, [max(0.0, bp - half_w)])
        start_pt = start_pts[0]

        end_pts = _interpolate_path(path, [min(total_len, bp + half_w)])
        end_pt = end_pts[0]

        # U-shape: go out perpendicular, advance, come back.
        out_x = center[0] + px * amplitude
        out_y = center[1] + py * amplitude

        adv_x = end_pt[0] + px * amplitude
        adv_y = end_pt[1] + py * amplitude

        new_points.append((round(start_pt[0], 6), round(start_pt[1], 6)))
        new_points.append((round(out_x, 6), round(out_y, 6)))
        new_points.append((round(adv_x, 6), round(adv_y, 6)))
        new_points.append((round(end_pt[0], 6), round(end_pt[1], 6)))

    new_points.append(path[-1])
    return tuple(new_points)


def route_differential_pair(
    graph,
    source_pos: tuple[float, float],
    source_neg: tuple[float, float],
    target_pos: tuple[float, float],
    target_neg: tuple[float, float],
    net_name_pos: str = "DP_P",
    net_name_neg: str = "DP_N",
    target_spacing_mm: float = 0.15,
    max_length_mismatch_mm: float = 0.5,
) -> DiffPairResult:
    """Route a differential pair with length matching via accordion serpentining.

    Routes both the positive and negative nets, then applies serpentine
    bumps to the shorter path to bring lengths within tolerance.

    Args:
        graph: Routing graph with DRC-aware edge weights.
        source_pos: (x, y) source coordinate for positive net.
        source_neg: (x, y) source coordinate for negative net.
        target_pos: (x, y) target coordinate for positive net.
        target_neg: (x, y) target coordinate for negative net.
        net_name_pos: Name of the positive net. Defaults to "DP_P".
        net_name_neg: Name of the negative net. Defaults to "DP_N".
        target_spacing_mm: Target pair spacing for serpentining amplitude.
            Defaults to 0.15mm.
        max_length_mismatch_mm: Maximum acceptable length difference in mm.
            Defaults to 0.5mm.

    Returns:
        DiffPairResult with both paths and length matching information.
        If either net fails to route, returns an invalid result with empty
        paths and valid=False.
    """
    # Route positive net.
    result_pos = route_net(graph, source_pos, target_pos, net_name_pos)
    if result_pos is None:
        return DiffPairResult(
            net_positive=(),
            net_negative=(),
            length_positive_mm=0.0,
            length_negative_mm=0.0,
            mismatch_mm=0.0,
            spacing_mm=target_spacing_mm,
            valid=False,
        )

    # Route negative net.
    result_neg = route_net(graph, source_neg, target_neg, net_name_neg)
    if result_neg is None:
        return DiffPairResult(
            net_positive=(),
            net_negative=(),
            length_positive_mm=0.0,
            length_negative_mm=0.0,
            mismatch_mm=0.0,
            spacing_mm=target_spacing_mm,
            valid=False,
        )

    path_pos = result_pos.path
    path_neg = result_neg.path
    len_pos = _path_length(path_pos)
    len_neg = _path_length(path_neg)
    mismatch = abs(len_pos - len_neg)

    # Apply serpentining if mismatch exceeds tolerance.
    if mismatch > max_length_mismatch_mm:
        delta = mismatch - max_length_mismatch_mm
        if len_pos < len_neg:
            # Positive net is shorter -- add serpentining.
            path_pos = _add_serpentining(path_pos, delta, target_spacing_mm)
        else:
            # Negative net is shorter -- add serpentining.
            path_neg = _add_serpentining(path_neg, delta, target_spacing_mm)

        # Recompute lengths after serpentining.
        len_pos = _path_length(path_pos)
        len_neg = _path_length(path_neg)
        mismatch = abs(len_pos - len_neg)

    # Check if serpentining achieved the target mismatch.
    is_valid = mismatch <= max_length_mismatch_mm

    return DiffPairResult(
        net_positive=path_pos,
        net_negative=path_neg,
        length_positive_mm=round(len_pos, 4),
        length_negative_mm=round(len_neg, 4),
        mismatch_mm=round(mismatch, 4),
        spacing_mm=target_spacing_mm,
        valid=is_valid,
    )
