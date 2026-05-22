"""Spatial primitives for PCB coordinate-grounded reasoning.

VP-01, VP-02, VP-03: Spatial primitive types, extraction pipeline, and rendering.
VP-04: Procedural maze-routing PCB generator.
VP-05: Cold-start reasoning chain synthesis from DRC/ERC violations.
VP-06: Spatial query engine with Shapely STRtree.
VP-08: Rick agent integration for coordinate-grounded domain reports.

Provides:
    - SpatialPoint, SpatialBox, SpatialPath, SpatialRegion: frozen dataclasses
    - extract_points, extract_boxes, extract_paths, extract_regions, extract_all:
      extraction functions that produce spatial primitives from PcbIR
    - render_pcb_layer, render_pcb_layer_grid:
      PCB layer rendering with coordinate grid overlay
    - generate_maze_board: Procedural maze-routing PCB puzzle generator
    - synthesize_chain, synthesize_chains: Reasoning chain synthesis from violations
    - SpatialQueryEngine: Shapely STRtree spatial query engine
    - RickDomain, RickFinding, SpatialRickReport: Rick integration types
    - generate_spatial_report, generate_all_reports: Rick report generation
"""

from kicad_agent.spatial.extractor import (
    extract_all,
    extract_boxes,
    extract_paths,
    extract_points,
    extract_regions,
)
from kicad_agent.spatial.maze_generator import MazeBoard, generate_maze_board
from kicad_agent.spatial.primitives import (
    SpatialBox,
    SpatialPath,
    SpatialPoint,
    SpatialRegion,
)
from kicad_agent.spatial.reasoning_chains import (
    ReasoningChain,
    ReasoningStep,
    synthesize_chain,
    synthesize_chains,
)
from kicad_agent.spatial.query import SpatialQueryEngine
from kicad_agent.spatial.renderer import (
    render_pcb_layer,
    render_pcb_layer_grid,
)
from kicad_agent.spatial.rick_integration import (
    RickDomain,
    RickFinding,
    SpatialRickReport,
    generate_all_reports,
    generate_spatial_report,
)

__all__ = [
    "SpatialPoint",
    "SpatialBox",
    "SpatialPath",
    "SpatialRegion",
    "extract_points",
    "extract_boxes",
    "extract_paths",
    "extract_regions",
    "extract_all",
    "render_pcb_layer",
    "render_pcb_layer_grid",
    "MazeBoard",
    "generate_maze_board",
    "ReasoningChain",
    "ReasoningStep",
    "synthesize_chain",
    "synthesize_chains",
    "SpatialQueryEngine",
    "RickDomain",
    "RickFinding",
    "SpatialRickReport",
    "generate_spatial_report",
    "generate_all_reports",
]
