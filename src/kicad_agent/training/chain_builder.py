"""DFS exploration and chain construction for maze samples.

Provides a depth-first search with backtracking that produces exploration
traces with coordinate data. These traces are converted into reasoning
chains for cold-start training data.

Usage:
    from kicad_agent.training.chain_builder import dfs_explore, exploration_to_chain

    steps = dfs_explore(grid, start, end, grid_size_mm)
    chain = exploration_to_chain(sample, steps)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class CellState(str, Enum):
    """State of a grid cell during DFS exploration."""

    UNVISITED = "unvisited"
    VISITED = "visited"
    DEAD_END = "dead_end"
    ON_PATH = "on_path"


@dataclass(frozen=True)
class ExplorationStep:
    """A single step in a DFS exploration trace.

    Attributes:
        position: Current cell center in mm coordinates.
        action: What happened at this step.
        direction: Movement direction ("up", "right", "down", "left", "none").
        obstacle_hit: Whether this step encountered an obstacle.
        coordinates: Referenced coordinate points in this step.
    """

    position: tuple[float, float]
    action: str  # "explore", "backtrack", "dead_end", "found_target"
    direction: str  # "up", "right", "down", "left", "none"
    obstacle_hit: bool
    coordinates: tuple[tuple[float, float], ...]


# Direction vectors: (dr, dc) and human-readable names
_DIRECTIONS = [
    ((-1, 0), "up"),
    ((0, 1), "right"),
    ((1, 0), "down"),
    ((0, -1), "left"),
]


def _cell_to_mm(row: int, col: int, grid_size_mm: float) -> tuple[float, float]:
    """Convert grid cell (row, col) to mm coordinates (center of cell)."""
    return (grid_size_mm * (col + 0.5), grid_size_mm * (row + 0.5))


def dfs_explore(
    grid: list[list[bool]],
    start: tuple[int, int],
    end: tuple[int, int],
    grid_size_mm: float,
) -> list[ExplorationStep]:
    """DFS exploration with backtracking through a boolean grid.

    Explores neighbors in order: up, right, down, left. Records each
    exploration step, obstacle hit, backtracking, and dead-end detection.

    Args:
        grid: 2D grid where True = obstacle, False = clear.
        start: (row, col) starting cell.
        end: (row, col) target cell.
        grid_size_mm: Grid cell size in mm for coordinate conversion.

    Returns:
        Ordered list of ExplorationStep with coordinate data.
        Empty list if start/end is out of bounds or blocked.
    """
    rows = len(grid)
    cols = len(grid[0]) if rows > 0 else 0
    if rows == 0 or cols == 0:
        return []

    sr, sc = start
    er, ec = end
    if not (0 <= sr < rows and 0 <= sc < cols):
        return []
    if not (0 <= er < rows and 0 <= ec < cols):
        return []
    if grid[sr][sc] or grid[er][ec]:
        return []

    visited: set[tuple[int, int]] = set()
    path: list[tuple[int, int]] = []
    steps: list[ExplorationStep] = []

    def _dfs(r: int, c: int) -> bool:
        """Recursive DFS returning True if target found."""
        cell = (r, c)
        visited.add(cell)
        path.append(cell)

        pos = _cell_to_mm(r, c, grid_size_mm)

        if cell == end:
            steps.append(ExplorationStep(
                position=pos,
                action="found_target",
                direction="none",
                obstacle_hit=False,
                coordinates=(pos,),
            ))
            return True

        # Try each direction
        has_valid_neighbor = False
        for (dr, dc), dir_name in _DIRECTIONS:
            nr, nc = r + dr, c + dc
            neighbor = (nr, nc)

            if not (0 <= nr < rows and 0 <= nc < cols):
                continue

            if grid[nr][nc]:
                # Hit obstacle
                obs_pos = _cell_to_mm(nr, nc, grid_size_mm)
                steps.append(ExplorationStep(
                    position=pos,
                    action="explore",
                    direction=dir_name,
                    obstacle_hit=True,
                    coordinates=(pos, obs_pos),
                ))
                continue

            if neighbor in visited:
                continue

            has_valid_neighbor = True
            next_pos = _cell_to_mm(nr, nc, grid_size_mm)
            steps.append(ExplorationStep(
                position=pos,
                action="explore",
                direction=dir_name,
                obstacle_hit=False,
                coordinates=(pos, next_pos),
            ))

            if _dfs(nr, nc):
                return True

        if not has_valid_neighbor:
            steps.append(ExplorationStep(
                position=pos,
                action="dead_end",
                direction="none",
                obstacle_hit=False,
                coordinates=(pos,),
            ))

        # Backtrack
        path.pop()
        if path:
            prev_r, prev_c = path[-1]
            prev_pos = _cell_to_mm(prev_r, prev_c, grid_size_mm)
            steps.append(ExplorationStep(
                position=pos,
                action="backtrack",
                direction="none",
                obstacle_hit=False,
                coordinates=(pos, prev_pos),
            ))

        return False

    _dfs(sr, sc)
    return steps


def exploration_to_chain(
    sample: Any,
    steps: list[ExplorationStep],
) -> dict:
    """Convert DFS exploration steps into a structured chain dict.

    Groups consecutive explore steps, summarizes backtracking, and
    preserves all coordinate references.

    Args:
        sample: MazeSample with board metadata.
        steps: Exploration steps from dfs_explore().

    Returns:
        Dict with chain metadata and structured steps.
    """
    chain_steps: list[dict] = []
    explore_count = 0
    backtrack_count = 0
    dead_end_count = 0
    coordinates_referenced: list[tuple[float, float]] = []

    for i, step in enumerate(steps):
        # Collect coordinates
        for coord in step.coordinates:
            if coord not in coordinates_referenced:
                coordinates_referenced.append(coord)

        if step.action == "explore":
            explore_count += 1
            if step.obstacle_hit:
                text = (
                    f"At <point {step.position[0]},{step.position[1]}>, "
                    f"exploring {step.direction}. "
                    f"Hit obstacle at <point {step.coordinates[1][0]},{step.coordinates[1][1]}>."
                )
            else:
                text = (
                    f"Moving {step.direction} from "
                    f"<point {step.position[0]},{step.position[1]}> to "
                    f"<point {step.coordinates[1][0]},{step.coordinates[1][1]}>."
                )
            chain_steps.append({
                "step_index": i,
                "action": step.action,
                "text": text,
                "coordinates": list(step.coordinates),
                "direction": step.direction,
                "obstacle_hit": step.obstacle_hit,
            })

        elif step.action == "dead_end":
            dead_end_count += 1
            text = (
                f"Dead end at <point {step.position[0]},{step.position[1]}>. "
                f"No unvisited neighbors available. Backtracking."
            )
            chain_steps.append({
                "step_index": i,
                "action": step.action,
                "text": text,
                "coordinates": list(step.coordinates),
            })

        elif step.action == "backtrack":
            backtrack_count += 1
            text = (
                f"Backtracking from "
                f"<point {step.position[0]},{step.position[1]}> to "
                f"<point {step.coordinates[1][0]},{step.coordinates[1][1]}>."
            )
            chain_steps.append({
                "step_index": i,
                "action": step.action,
                "text": text,
                "coordinates": list(step.coordinates),
            })

        elif step.action == "found_target":
            text = (
                f"Target found at "
                f"<point {step.position[0]},{step.position[1]}>! "
                f"Path complete."
            )
            chain_steps.append({
                "step_index": i,
                "action": step.action,
                "text": text,
                "coordinates": list(step.coordinates),
            })

    # Build full chain text
    chain_text = "\n".join(s["text"] for s in chain_steps)

    return {
        "sample_id": sample.sample_id,
        "difficulty": sample.difficulty,
        "chain_text": chain_text,
        "steps": chain_steps,
        "coordinates_referenced": coordinates_referenced,
        "is_correct": any(s["action"] == "found_target" for s in chain_steps),
        "exploration_branches": explore_count,
        "backtrack_count": backtrack_count,
        "dead_end_count": dead_end_count,
    }
