"""Placement module: graph construction, validation, and quality scoring.

Provides the netlist-to-placement-graph converter that transforms
schematic netlists into bipartite component-net graphs, DRC-aware
placement validation, and quality scoring with HPWL/congestion metrics.

Usage::

    from kicad_agent.placement import (
        PlacementGraph,
        PlacementValidator,
        PlacementScorer,
        netlist_to_placement_graph,
    )
"""

from kicad_agent.placement.features import (
    COMP_FEATURE_DIM,
    NET_FEATURE_DIM,
    extract_component_features,
    extract_net_features,
)
from kicad_agent.placement.graph import PlacementGraph, netlist_to_placement_graph
from kicad_agent.placement.scoring import PlacementScore, PlacementScorer
from kicad_agent.placement.validation import (
    PlacementValidator,
    PlacementViolation,
    validate_placement,
)

__all__ = [
    "PlacementGraph",
    "PlacementValidator",
    "PlacementScorer",
    "PlacementScore",
    "PlacementViolation",
    "netlist_to_placement_graph",
    "validate_placement",
    "extract_component_features",
    "extract_net_features",
    "COMP_FEATURE_DIM",
    "NET_FEATURE_DIM",
]
