# Phase 19: Interactive Routing Suggestions - Research

**Researched:** 2026-05-23
**Domain:** PCB auto-routing, graph pathfinding, DRC constraints, differential pair routing, interactive design tools
**Confidence:** MEDIUM

## Summary

Phase 19 builds an interactive routing suggestion system that uses spatial primitives (Phase 8) and placement output (Phase 16) to propose trace routing paths on real PCBs. Given placed components and a netlist, the system generates routing suggestions that satisfy DRC clearance constraints and minimize wirelength. The system supports differential pair routing with impedance and length matching constraints, and provides an interactive mode where users approve, reject, or modify suggestions.

The core algorithm is A* pathfinding on a routing graph constructed from the PCB's spatial data. Each graph node represents a grid cell (or via location), and edges represent possible trace segments with DRC-compliant weights. The spatial query engine (SpatialQueryEngine with Shapely STRtree) provides fast clearance checks during pathfinding. Differential pair routing extends single-net routing with coupled constraints (equal length, controlled spacing). The interactive mode exposes a suggestion/approval API that allows incremental constraint refinement.

This phase integrates heavily with Phase 8 (spatial primitives: SpatialPoint, SpatialBox, SpatialPath, SpatialRegion; SpatialQueryEngine for proximity/clearance queries), Phase 16 (placement AI produces placed components as input), and the existing validation pipeline (run_drc for post-route verification). The maze_generator.py from Phase 8 provides a similar grid-based BFS pathfinding approach that can be adapted for real routing.

**Primary recommendation:** Build routing graph from spatial primitives, use A* with DRC-costed edges, extend for differential pairs with length matching, and expose interactive API for suggestion/approval cycles.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ROUTE-01 | Given placed components and netlist, routing suggestions are generated for each net | Architecture: A* pathfinding on routing graph from spatial data |
| ROUTE-02 | Suggested routes satisfy DRC clearance and design rule constraints | Architecture: DRC-costed graph edges + SpatialQueryEngine clearance checks |
| ROUTE-03 | Differential pair routing respects impedance and length matching constraints | Architecture: Coupled A* with serpentining for length matching |
| ROUTE-04 | Interactive mode: user approves/rejects suggestions, AI adapts to constraints | Architecture: Suggestion/approval API with constraint refinement |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Routing graph construction | API / Backend | -- | Graph built from PCB spatial data in Python |
| Pathfinding algorithm | API / Backend | -- | A* on routing graph with DRC constraints |
| DRC constraint checking | API / Backend | SpatialQueryEngine | Uses existing spatial query engine for clearance |
| Differential pair routing | API / Backend | -- | Extends single-net routing with coupled constraints |
| Interactive mode API | API / Backend | -- | Suggestion/approval data structures |
| Post-route verification | Validation pipeline | -- | Uses existing run_drc for final verification |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| networkx | >=3.0 | Graph representation and A* pathfinding | Already a project dependency; provides Dijkstra, A*, and custom heuristics [VERIFIED: pyproject.toml] |
| Shapely | >=2.0 | Spatial geometry operations | Used by SpatialQueryEngine; provides distance, buffer, intersection [VERIFIED: spatial/query.py imports] |
| kiutils | >=1.4.8 | PCB file parsing | Project standard for KiCad file I/O [VERIFIED: pyproject.toml] |
| pydantic | >=2.0 | Data models for routing results | Project standard for structured data [VERIFIED: pyproject.toml] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| heapq (stdlib) | -- | Priority queue for A* | A* open set implementation |
| math (stdlib) | -- | Distance calculations | Euclidean distance heuristic for A* |
| dataclasses (stdlib) | -- | Frozen dataclass types | SpatialPoint, SpatialBox already use this pattern |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| A* pathfinding | Lee's algorithm (wave propagation) | Lee's guarantees shortest path but is O(n^2) memory; A* is faster with good heuristic |
| A* pathfinding | Negotiated congestion routing | Better for multi-net routing order; more complex; add as Phase 2 enhancement |
| networkx A* | Custom A* implementation | networkx is simpler but slower; custom implementation can be 10-100x faster for large grids |
| Grid-based routing | Topological routing | Topological handles multi-layer better; grid-based is simpler to implement and validate |

**Installation:**
```bash
# All dependencies already in pyproject.toml
# No new dependencies needed for core routing
```

## Architecture Patterns

### System Architecture Diagram

```
Placed Components + Netlist (from Phase 16)
        |
        v
  Spatial Extraction (Phase 8)
  (extract_points, extract_boxes, extract_paths, extract_regions)
        |
        v
  Routing Graph Builder
  (grid cells as nodes, DRC-costed edges)
        |
        +-----> SpatialQueryEngine (clearance checks)
        |           |
        |           v
        |     DRC Constraints
        |     (clearance, trace width, via size)
        |
        v
  A* Pathfinding per Net
  (heuristic: Euclidean distance, cost: segment length + DRC penalty)
        |
        +-----> Differential Pair Extension
        |           (coupled routing, length matching via serpentining)
        |
        v
  Routing Suggestion (SpatialPath per net)
        |
        v
  Interactive Mode API
  (approve / reject / modify constraints)
        |
        v
  Post-route DRC Verification (run_drc from validation pipeline)
```

### Recommended Project Structure (new module)

```
src/kicad_agent/
├── routing/                    # NEW MODULE
│   ├── __init__.py             # Public API exports
│   ├── graph.py                # Routing graph construction from spatial data
│   ├── pathfinder.py           # A* pathfinding with DRC costs
│   ├── diff_pair.py            # Differential pair routing + length matching
│   ├── interactive.py          # Suggestion/approval API for interactive mode
│   └── constraints.py          # DRC constraint extraction from board settings
├── spatial/                    # EXISTS (Phase 8)
│   ├── primitives.py           # SpatialPoint, SpatialBox, SpatialPath, SpatialRegion
│   ├── query.py                # SpatialQueryEngine
│   ├── extractor.py            # extract_points, extract_boxes, etc.
│   └── maze_generator.py       # MazeBoard (similar grid-based approach)
├── validation/                 # EXISTS (Phase 3)
│   └── __init__.py             # run_drc, DrcResult, Violation
└── generation/                 # EXISTS (Phase 10)
    └── placement.py            # PlacementEngine output feeds routing
```

### Pattern 1: Routing Graph Construction

**What:** Build a graph where nodes are grid cells on the PCB and edges are possible trace segments. Edge weights incorporate segment length and DRC penalties.

**When to use:** Before pathfinding can begin, the routing graph must be constructed from spatial data.

**Example:**
```python
# Source: [ASSUMED] based on networkx A* API + project spatial primitives
import networkx as nx
from kicad_agent.spatial.primitives import SpatialPoint, SpatialBox
from kicad_agent.spatial.query import SpatialQueryEngine

def build_routing_graph(
    board_bounds: tuple[float, float, float, float],
    obstacles: list[SpatialBox],
    query_engine: SpatialQueryEngine,
    grid_resolution: float = 0.5,  # mm
    clearance_mm: float = 0.2,
) -> nx.Graph:
    """Build routing graph with DRC-costed edges.

    Args:
        board_bounds: (x_min, y_min, x_max, y_max) in mm.
        obstacles: SpatialBox list for components, pours, keepouts.
        query_engine: For clearance checks during edge evaluation.
        grid_resolution: Grid cell size in mm.
        clearance_mm: Minimum DRC clearance in mm.

    Returns:
        networkx Graph with 'weight' attribute on edges.
    """
    G = nx.Graph()
    x_min, y_min, x_max, y_max = board_bounds

    # Create grid nodes
    x = x_min
    while x <= x_max:
        y = y_min
        while y <= y_max:
            # Skip nodes inside obstacles
            if not _point_in_obstacles(x, y, obstacles):
                G.add_node((round(x, 4), round(y, 4)))
            y += grid_resolution
        x += grid_resolution

    # Create edges with DRC-weighted cost
    for node in G.nodes:
        x, y = node
        for dx, dy in [(grid_resolution, 0), (0, grid_resolution)]:
            neighbor = (round(x + dx, 4), round(y + dy, 4))
            if neighbor in G:
                # Check DRC clearance for this edge
                edge_cost = _compute_edge_cost(
                    (x, y), neighbor, query_engine, clearance_mm
                )
                if edge_cost is not None:  # None means DRC violation
                    G.add_edge(node, neighbor, weight=edge_cost)

    return G
```

### Pattern 2: A* Pathfinding with DRC Heuristic

**What:** Use networkx.astar_path with Euclidean distance heuristic and DRC-aware edge weights.

**When to use:** For each net in the netlist, find the lowest-cost path from source to target.

**Example:**
```python
import math
import networkx as nx

def route_net(
    graph: nx.Graph,
    source: tuple[float, float],
    target: tuple[float, float],
) -> list[tuple[float, float]] | None:
    """Find DRC-compliant route for a single net using A*.

    Args:
        graph: Routing graph with DRC-costed edges.
        source: (x, y) start point.
        target: (x, y) end point.

    Returns:
        List of (x, y) waypoints, or None if no route found.
    """
    def euclidean_heuristic(u, v):
        return math.sqrt((u[0] - v[0])**2 + (u[1] - v[1])**2)

    # Snap to nearest graph nodes
    src_node = _snap_to_node(graph, source)
    tgt_node = _snap_to_node(graph, target)

    try:
        path = nx.astar_path(graph, src_node, tgt_node,
                             heuristic=euclidean_heuristic,
                             weight="weight")
        return path
    except nx.NetworkXNoPath:
        return None
```

### Pattern 3: Differential Pair Routing

**What:** Route two coupled nets simultaneously with equal length and controlled spacing. Add serpentining (detour patterns) to match lengths when one path is shorter.

**When to use:** For differential pair nets (e.g., USB D+/D-, HDMI clock/data).

**Example:**
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class DiffPairResult:
    """Result of differential pair routing."""
    net_positive: list[tuple[float, float]]
    net_negative: list[tuple[float, float]]
    length_positive_mm: float
    length_negative_mm: float
    length_mismatch_mm: float
    spacing_mm: float
    valid: bool

def route_differential_pair(
    graph: nx.Graph,
    source_pos: tuple[float, float],
    source_neg: tuple[float, float],
    target_pos: tuple[float, float],
    target_neg: tuple[float, float],
    target_spacing_mm: float = 0.15,
    max_length_mismatch_mm: float = 0.5,
) -> DiffPairResult:
    """Route differential pair with length matching via serpentining.

    Algorithm:
    1. Route positive net first via A*
    2. Route negative net with spacing constraint (offset path)
    3. If lengths differ, add serpentining to shorter path
    4. Verify length mismatch within tolerance
    """
    # Step 1: Route primary net
    path_pos = route_net(graph, source_pos, target_pos)
    path_neg = route_net(graph, source_neg, target_neg)

    if path_pos is None or path_neg is None:
        return DiffPairResult([], [], 0, 0, float('inf'), 0, False)

    # Step 2: Compute lengths
    len_pos = _path_length(path_pos)
    len_neg = _path_length(path_neg)

    # Step 3: Serpentine the shorter path
    if abs(len_pos - len_neg) > max_length_mismatch_mm:
        if len_pos < len_neg:
            path_pos = _add_serpentining(path_pos, len_neg - len_pos, graph)
        else:
            path_neg = _add_serpantining(path_neg, len_pos - len_neg, graph)

    # Recompute after serpentining
    len_pos = _path_length(path_pos)
    len_neg = _path_length(path_neg)

    return DiffPairResult(
        net_positive=path_pos,
        net_negative=path_neg,
        length_positive_mm=len_pos,
        length_negative_mm=len_neg,
        length_mismatch_mm=abs(len_pos - len_neg),
        spacing_mm=target_spacing_mm,
        valid=abs(len_pos - len_neg) <= max_length_mismatch_mm,
    )
```

### Pattern 4: Interactive Routing API

**What:** Data structures for routing suggestions that users can approve, reject, or modify.

**When to use:** When the AI proposes routes and the user wants to accept some, reject others, and add constraints.

**Example:**
```python
from pydantic import BaseModel
from enum import Enum

class SuggestionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"

class RoutingSuggestion(BaseModel):
    """A single net routing suggestion for interactive mode."""
    net_name: str
    path: list[tuple[float, float]]
    length_mm: float
    clearance_violations: list[str]  # DRC violations if any
    status: SuggestionStatus = SuggestionStatus.PENDING
    user_constraints: dict[str, float] = {}  # e.g., {"min_clearance": 0.3}

class InteractiveRoutingSession(BaseModel):
    """State for an interactive routing session."""
    suggestions: list[RoutingSuggestion]
    locked_routes: list[RoutingSuggestion] = []  # User-approved routes
    constraints: dict[str, float] = {
        "min_clearance_mm": 0.2,
        "max_length_mismatch_mm": 0.5,
    }
    iteration: int = 0
    max_iterations: int = 5

    def approve(self, net_name: str) -> None:
        """Move suggestion to locked routes."""
        for s in self.suggestions:
            if s.net_name == net_name:
                s.status = SuggestionStatus.APPROVED
                self.locked_routes.append(s)
                break

    def reject(self, net_name: str, reason: str = "") -> None:
        """Reject suggestion and add constraint for re-routing."""
        for s in self.suggestions:
            if s.net_name == net_name:
                s.status = SuggestionStatus.REJECTED
                break
```

### Anti-Patterns to Avoid

- **Grid too fine for board size:** 0.1mm grid on a 200mm board creates 4M nodes; use adaptive resolution (0.5mm default, finer near obstacles)
- **Routing all nets independently:** Net ordering matters; route shortest nets first, then use rip-up-and-retry for conflicts
- **Ignoring layer transitions:** Single-layer routing misses via opportunities; extend to multi-layer with layer-change cost
- **No rip-up mechanism:** If a net cannot be routed, existing routes may need to be ripped up and re-routed in a different order

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Graph pathfinding | Custom A* from scratch | networkx.astar_path | Battle-tested, supports custom heuristics and weights |
| Spatial clearance checks | Custom distance loops | SpatialQueryEngine.clearance() | Already uses Shapely STRtree for O(log n) queries |
| DRC verification | Custom rule engine | run_drc from validation pipeline | Already integrated with kicad-cli; produces structured results |
| PCB data extraction | Custom parsing | spatial/extractor.py | Already extracts points, boxes, paths, regions from KiCad files |

**Key insight:** This phase is primarily integration work -- combining existing spatial primitives, spatial queries, validation, and generation modules into a routing system. Most components already exist.

## Common Pitfalls

### Pitfall 1: Routing graph too large for real boards

**What goes wrong:** Building a 0.1mm resolution graph for a 150mm x 100mm board creates 1.5M nodes, making A* too slow.

**Why it happens:** Naive grid resolution without considering obstacle density.

**How to avoid:** Use adaptive grid resolution (coarse 1mm grid for sparse areas, fine 0.25mm near obstacles), or use a visibility graph instead of a grid for sparse boards.

**Warning signs:** Graph construction takes >10 seconds, A* times out on individual nets.

### Pitfall 2: Net ordering causes unroutable nets

**What goes wrong:** Earlier routes block later routes, leaving some nets with no path.

**Why it happens:** Routing order matters; longer nets should sometimes be routed first.

**How to avoid:** (1) Route by estimated difficulty (fewest obstacles first), (2) Implement rip-up-and-retry: if a net fails, rip up conflicting nets and re-route in different order.

**Warning signs:** Route success rate drops below 90% on boards with many nets.

### Pitfall 3: Differential pair length matching adds too many detours

**What goes wrong:** Serpentining adds so many bends that the route looks unreasonable and may cause signal integrity issues.

**Why it happens:** One path is much shorter than the other, requiring many accordion bumps.

**How to avoid:** (1) Route both nets simultaneously with coupled constraints, (2) Limit maximum serpentine amplitude, (3) Prefer path re-routing over excessive serpentining.

**Warning signs:** Length mismatch > 20% of total path length after matching.

### Pitfall 4: DRC violations in suggested routes

**What goes wrong:** Routes pass A* but fail DRC when applied to the actual board.

**Why it happens:** Grid-based routing graph approximates trace positions; actual trace geometry (width, endcaps) may encroach on clearance boundaries.

**How to avoid:** (1) Add trace width margin to clearance checks during graph building, (2) Run full DRC after all routes are placed, (3) Iterate: DRC fail -> rip up violating nets -> re-route with increased margin.

**Warning signs:** DRC violations cluster near dense component areas.

## Code Examples

### Integration with existing spatial infrastructure

```python
# Source: [ASSUMED] based on existing spatial module API
from kicad_agent.spatial.extractor import extract_all
from kicad_agent.spatial.query import SpatialQueryEngine
from kicad_agent.validation import run_drc

def route_board(
    pcb_path: Path,
    netlist: dict[str, list[tuple[float, float]]],
    # netlist: {"GND": [(10, 20), (30, 40)], "VCC": [(15, 25), (35, 45)]}
) -> dict[str, list[tuple[float, float]]]:
    """Route all nets on a placed PCB.

    Args:
        pcb_path: Path to .kicad_pcb file.
        netlist: Map of net name to list of (x, y) pin positions.

    Returns:
        Map of net name to routing path (list of waypoints).
    """
    # Step 1: Extract spatial data from PCB
    spatial_data = extract_all(pcb_path)
    obstacles = spatial_data["boxes"]  # Component bounding boxes

    # Step 2: Build spatial query engine for DRC checks
    all_primitives = (
        spatial_data["points"]
        + spatial_data["boxes"]
        + spatial_data["paths"]
        + spatial_data["regions"]
    )
    query_engine = SpatialQueryEngine(all_primitives)

    # Step 3: Build routing graph
    graph = build_routing_graph(
        board_bounds=_get_board_bounds(pcb_path),
        obstacles=obstacles,
        query_engine=query_engine,
    )

    # Step 4: Route each net (simple: shortest first)
    results = {}
    for net_name in sorted(netlist.keys(), key=lambda n: len(netlist[n])):
        pins = netlist[net_name]
        if len(pins) >= 2:
            path = route_net(graph, pins[0], pins[-1])
            if path is not None:
                results[net_name] = path

    return results
```

### Post-route DRC verification

```python
from kicad_agent.validation import run_drc, DrcResult

def verify_routes(pcb_path: Path) -> DrcResult:
    """Run DRC after applying routes to verify compliance."""
    result = run_drc(pcb_path)
    if not result.passed:
        # Filter routing-related violations
        routing_violations = [
            v for v in result.violations
            if v.type in ("clearance", "track_width", "unconnected")
        ]
    return result
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Lee's algorithm (BFS wave) | A* with heuristic | 1990s+ | Faster pathfinding with good heuristic |
| Grid-based routing | Hybrid grid + visibility graph | 2000s+ | Better for sparse boards |
| Sequential net routing | Negotiated congestion routing | 2000s+ | Better global optimization |
| Manual routing only | AI-assisted routing suggestions | 2020s+ | Human-in-the-loop with AI proposals |
| Fixed routing rules | DRC-aware adaptive routing | 2010s+ | Constraint-driven pathfinding |

**Deprecated/outdated:**
- Pure Lee's algorithm: Too slow for real boards; use A* or negotiated congestion
- Grid-only routing: Hybrid approaches perform better on real boards
- Single-layer routing: Modern boards are multi-layer; via transitions are essential

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Grid-based routing is sufficient for initial implementation | Architecture | May need visibility graph for complex boards |
| A2 | networkx A* is fast enough for boards with <100 nets | Standard Stack | May need custom C-extension for larger boards |
| A3 | Phase 16 placement output provides netlist with pin positions | Architecture | If placement output format differs, adapter needed |
| A4 | Single-layer routing first, multi-layer as enhancement | Architecture | If boards require multi-layer from the start, design needs adjustment |
| A5 | Differential pair serpentining uses simple accordion pattern | Diff Pair | Other patterns (trombone, sawtooth) may be needed |

## Open Questions

1. **Grid resolution vs. performance trade-off**
   - What we know: 0.1mm grid creates millions of nodes on real boards
   - What's unclear: What resolution balances accuracy and speed for typical boards
   - Recommendation: Start with 0.5mm default, make configurable, benchmark on real boards

2. **Multi-layer routing scope**
   - What we know: Real PCBs use 2-16 layers with vias connecting them
   - What's unclear: Is single-layer routing sufficient for Phase 19, or is multi-layer essential?
   - Recommendation: Start single-layer for ROUTE-01/02; add multi-layer as enhancement

3. **Integration with Freerouting**
   - What we know: Freerouting is an open-source Java router using Specctra DSN format
   - What's unclear: Should Phase 19 use Freerouting as backend vs. custom routing?
   - Recommendation: Build custom routing for full control; Freerouting integration as future enhancement

4. **Net ordering strategy**
   - What we know: Routing order significantly affects completion rate
   - What's unclear: Best heuristic for net ordering (shortest first? most constrained first?)
   - Recommendation: Start with shortest-first; add congestion-based ordering as enhancement

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| networkx | Graph operations | Yes | >=3.0 | -- |
| Shapely | Spatial queries | Yes | >=2.0 | -- |
| kiutils | PCB parsing | Yes | >=1.4.8 | -- |
| pydantic | Data models | Yes | >=2.0 | -- |
| kicad-cli | DRC verification | Yes | -- | Skip DRC tests if not installed |

**Missing dependencies with no fallback:**
- None -- all required libraries are already in pyproject.toml

**Missing dependencies with fallback:**
- kicad-cli -- DRC tests can be skipped if not installed (existing pattern in test suite)

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/ -x -q -k routing` |
| Full suite command | `python -m pytest tests/ -v --tb=short` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ROUTE-01 | Routing suggestions generated for placed nets | unit | `pytest tests/test_routing.py::test_route_simple_net -x` | No -- Wave 0 |
| ROUTE-02 | Routes satisfy DRC clearance constraints | unit | `pytest tests/test_routing.py::test_drc_clearance -x` | No -- Wave 0 |
| ROUTE-03 | Differential pair routing with length matching | unit | `pytest tests/test_routing.py::test_diff_pair_length_match -x` | No -- Wave 0 |
| ROUTE-04 | Interactive mode approves/rejects suggestions | unit | `pytest tests/test_routing.py::test_interactive_approve -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q -k routing`
- **Per wave merge:** `python -m pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green + new routing tests pass

### Wave 0 Gaps
- [ ] `tests/test_routing.py` -- covers ROUTE-01 through ROUTE-04
- [ ] `src/kicad_agent/routing/__init__.py` -- module initialization
- [ ] `src/kicad_agent/routing/graph.py` -- routing graph builder
- [ ] `src/kicad_agent/routing/pathfinder.py` -- A* pathfinder
- [ ] `src/kicad_agent/routing/diff_pair.py` -- differential pair routing
- [ ] `src/kicad_agent/routing/interactive.py` -- interactive session
- [ ] `src/kicad_agent/routing/constraints.py` -- DRC constraint extraction

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | -- |
| V3 Session Management | no | -- |
| V4 Access Control | no | -- |
| V5 Input Validation | yes | Pydantic models for routing inputs; validate board bounds, grid params |
| V6 Cryptography | no | -- |

### Known Threat Patterns for PCB Routing

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| DoS via huge board dimensions | Denial of service | Cap grid size; reject boards > max dimensions |
| DoS via tiny grid resolution | Denial of service | Minimum grid resolution 0.1mm; cap total nodes |
| Infinite routing loops | Denial of service | Max iterations cap on rip-up-and-retry |
| Malformed PCB input | Tampering | Validate PCB structure before routing graph construction |

## Sources

### Primary (HIGH confidence)
- Project source code (spatial/primitives.py, spatial/query.py, spatial/extractor.py, generation/placement.py, validation/__init__.py) -- verified existing APIs and integration points
- networkx documentation -- A* pathfinding API, graph construction
- pyproject.toml -- verified dependency versions

### Secondary (MEDIUM confidence)
- PCB routing algorithm references -- A* vs Lee's algorithm trade-offs
- Differential pair routing patterns -- serpentining for length matching

### Tertiary (LOW confidence)
- [ASSUMED] Grid-based routing is appropriate initial approach (A1)
- [ASSUMED] networkx A* performance is sufficient for <100 net boards (A2)
- [ASSUMED] Phase 16 placement output format (A3)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in project; no new dependencies
- Architecture: MEDIUM -- routing algorithms are well-understood, but grid resolution and performance on real boards need empirical validation
- Pitfalls: MEDIUM -- common routing issues are documented, but real-board edge cases may require iteration

**Research date:** 2026-05-23
**Valid until:** 2026-06-23 (stable -- algorithmic approaches don't change rapidly)
