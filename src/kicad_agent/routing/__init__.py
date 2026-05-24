"""Routing graph model and A* pathfinding with DRC constraints.

Provides:
    - RoutingConstraints: Frozen dataclass of design-rule parameters.
    - RoutingGraph: Grid-based routing graph with DRC-aware edge costs.
    - RouteResult: Frozen dataclass for a routed net path.
    - DiffPairResult: Frozen dataclass for differential pair routing.
    - build_routing_graph: Convenience function for graph construction.
    - route_net: A* pathfinding for a single net.
    - route_all_nets: Batch routing for multiple nets (shortest first).
    - route_differential_pair: Differential pair routing with length matching.
"""

from kicad_agent.routing.constraints import RoutingConstraints
from kicad_agent.routing.diff_pair import DiffPairResult, route_differential_pair
from kicad_agent.routing.graph import RoutingGraph
from kicad_agent.routing.pathfinder import (
    RouteResult,
    build_routing_graph,
    route_all_nets,
    route_net,
)

__all__ = [
    "RoutingConstraints",
    "RoutingGraph",
    "RouteResult",
    "DiffPairResult",
    "build_routing_graph",
    "route_net",
    "route_all_nets",
    "route_differential_pair",
]
