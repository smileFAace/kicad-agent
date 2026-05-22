"""Cold-start reasoning chain synthesis from maze samples.

GRPO-02: Generates coordinate-grounded reasoning chains from maze-routing
samples. Two chain types: solution chains (5-step) and exploration chains
(DFS with backtracking).

Each chain references coordinates in `<point x,y>` format for spatial grounding.

Usage:
    from kicad_agent.training.chains import synthesize_maze_chain

    chain = synthesize_maze_chain(sample)
    print(chain.chain_text)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kicad_agent.training.dataset import MazeSample


@dataclass(frozen=True)
class MazeReasoningChain:
    """A coordinate-grounded reasoning chain for a maze-routing puzzle.

    Attributes:
        sample_id: Links back to the MazeSample.
        difficulty: Inherited from sample ("easy"/"medium"/"hard"/"adversarial").
        chain_text: Full reasoning chain as natural language text.
        steps: Structured steps with coordinates and step types.
        coordinates_referenced: All coordinates mentioned in the chain.
        is_correct: Whether the chain reaches the correct target.
        exploration_branches: Number of exploration branches (0 for solution chains).
    """

    sample_id: int
    difficulty: str
    chain_text: str
    steps: tuple[dict, ...]
    coordinates_referenced: tuple[tuple[float, float], ...]
    is_correct: bool
    exploration_branches: int


def _point_str(x: float, y: float) -> str:
    """Format a coordinate as <point x,y>."""
    return f"<point {x:.1f},{y:.1f}>"


def _nearest_obstacle_distance(
    point: tuple[float, float],
    obstacles: tuple[tuple[float, float], ...],
) -> tuple[float, tuple[float, float] | None]:
    """Find nearest obstacle to a point.

    Args:
        point: (x, y) center point.
        obstacles: Obstacle center coordinates.

    Returns:
        (distance, nearest_obstacle) tuple. distance is inf if no obstacles.
    """
    import math

    min_dist = float("inf")
    nearest = None
    for obs in obstacles:
        dx = point[0] - obs[0]
        dy = point[1] - obs[1]
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < min_dist:
            min_dist = dist
            nearest = obs
    return min_dist, nearest


def synthesize_maze_chain(sample: MazeSample) -> MazeReasoningChain:
    """Build a 5-step solution chain from a maze sample.

    Steps:
      1. observation: Board dimensions, obstacle count, source/target positions
      2. spatial_context: Nearby obstacles, distances
      3. coordinate_reference: Full solution path with coordinates
      4. diagnosis: Path characteristics, clearance
      5. recommendation: Routing instruction

    Args:
        sample: MazeSample with verified solution.

    Returns:
        MazeReasoningChain with 5 ordered steps.
    """
    src = sample.source_point
    tgt = sample.target_point
    obstacles = sample.obstacle_positions
    path = sample.solution_path

    # Step 1: Observation
    obs_text = (
        f"Board is {sample.board_width_mm:.0f}x{sample.board_height_mm:.0f}mm "
        f"with {sample.obstacle_count} obstacles. "
        f"Source via at {_point_str(src[0], src[1])}, "
        f"target via at {_point_str(tgt[0], tgt[1])}."
    )

    # Step 2: Spatial context
    dist, nearest = _nearest_obstacle_distance(src, obstacles)
    if nearest is not None:
        spatial_text = (
            f"The path from source to target must navigate around "
            f"{sample.obstacle_count} obstacles. "
            f"Nearest obstacle to source at {_point_str(nearest[0], nearest[1])}, "
            f"distance {dist:.1f}mm."
        )
    else:
        spatial_text = "No obstacles present. Direct path available."

    # Step 3: Coordinate reference
    path_strs = [_point_str(p[0], p[1]) for p in path]
    coord_text = (
        f"Solution path: {' → '.join(path_strs)} "
        f"({len(path)} steps)."
    )

    # Step 4: Diagnosis
    diagnosis_text = (
        f"The optimal route requires {len(path)} steps, "
        f"passing through clear cells while maintaining "
        f"obstacle avoidance across {sample.board_width_mm:.0f}x{sample.board_height_mm:.0f}mm board."
    )

    # Step 5: Recommendation
    rec_text = (
        f"Route trace from source {_point_str(src[0], src[1])} "
        f"following the verified path to target {_point_str(tgt[0], tgt[1])} "
        f"in {len(path)} steps."
    )

    chain_text = f"{obs_text}\n{spatial_text}\n{coord_text}\n{diagnosis_text}\n{rec_text}"

    all_coords = [src, tgt]
    for p in path:
        if p not in all_coords:
            all_coords.append(p)
    if nearest is not None and nearest not in all_coords:
        all_coords.append(nearest)

    steps = (
        {"step_type": "observation", "text": obs_text, "coordinates": [src, tgt]},
        {"step_type": "spatial_context", "text": spatial_text, "coordinates": [src] + ([nearest] if nearest else [])},
        {"step_type": "coordinate_reference", "text": coord_text, "coordinates": list(path)},
        {"step_type": "diagnosis", "text": diagnosis_text, "coordinates": []},
        {"step_type": "recommendation", "text": rec_text, "coordinates": [src, tgt]},
    )

    return MazeReasoningChain(
        sample_id=sample.sample_id,
        difficulty=sample.difficulty,
        chain_text=chain_text,
        steps=steps,
        coordinates_referenced=tuple(all_coords),
        is_correct=True,  # solution chains always reach target
        exploration_branches=0,
    )


def synthesize_exploration_chain(
    sample: MazeSample,
    grid: list[list[bool]] | None = None,
) -> MazeReasoningChain:
    """Build an exploration chain using DFS with backtracking.

    Produces longer chains with dead-end detection and backtracking,
    providing richer training signal with more coordinate references.

    Args:
        sample: MazeSample with verified solution.
        grid: Optional grid. If None, reconstructed from sample metadata.

    Returns:
        MazeReasoningChain with exploration steps.
    """
    from kicad_agent.training.chain_builder import dfs_explore, exploration_to_chain

    if grid is None:
        grid = _reconstruct_grid(sample)

    rows = int(sample.board_height_mm / sample.grid_size_mm)
    cols = int(sample.board_width_mm / sample.grid_size_mm)

    # Find start/end cells
    src_col = int(sample.source_point[0] / sample.grid_size_mm)
    src_row = int(sample.source_point[1] / sample.grid_size_mm)
    tgt_col = int(sample.target_point[0] / sample.grid_size_mm)
    tgt_row = int(sample.target_point[1] / sample.grid_size_mm)

    # Clamp to grid bounds
    src_row = max(0, min(src_row, rows - 1))
    src_col = max(0, min(src_col, cols - 1))
    tgt_row = max(0, min(tgt_row, rows - 1))
    tgt_col = max(0, min(tgt_col, cols - 1))

    steps = dfs_explore(grid, (src_row, src_col), (tgt_row, tgt_col), sample.grid_size_mm)
    chain_dict = exploration_to_chain(sample, steps)

    return MazeReasoningChain(
        sample_id=sample.sample_id,
        difficulty=sample.difficulty,
        chain_text=chain_dict["chain_text"],
        steps=tuple(chain_dict["steps"]),
        coordinates_referenced=tuple(chain_dict["coordinates_referenced"]),
        is_correct=chain_dict["is_correct"],
        exploration_branches=chain_dict["exploration_branches"],
    )


def _reconstruct_grid(sample: MazeSample) -> list[list[bool]]:
    """Reconstruct a boolean grid from sample metadata.

    Obstacle positions are marked True. All other cells are False.
    """
    rows = max(1, int(sample.board_height_mm / sample.grid_size_mm))
    cols = max(1, int(sample.board_width_mm / sample.grid_size_mm))
    grid = [[False] * cols for _ in range(rows)]

    for ox, oy in sample.obstacle_positions:
        c = int(ox / sample.grid_size_mm)
        r = int(oy / sample.grid_size_mm)
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c] = True

    return grid
