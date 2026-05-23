---
phase: 11-ltspice-integration
plan: 03
subsystem: api
tags: [ltspice, net-graph, networkx, connectivity, wire-geometry, pin-matching]

# Dependency graph
requires: [11-01]
provides:
  - LTspiceNetGraph class deriving connectivity from wire geometry
  - FLAG net name propagation across connected components
  - Component pin position calculation with rotation transforms
  - Pin-to-net matching via coordinate geometry
affects: [11-ltspice-integration, ltspice-bridge]

# Tech tracking
tech-stack:
  added: []
  patterns: [wire-segment-splitting, rotation-transforms, connected-component-propagation]

key-files:
  created:
    - src/kicad_agent/ltspice/net_graph.py
    - tests/test_ltspice_net_graph.py
  modified:
    - src/kicad_agent/ltspice/__init__.py
    - tests/fixtures/ltspice/basic_rc.asc

key-decisions:
  - "Wire segments split at component pin positions for accurate connectivity"
  - "Pin positions computed from .asy stub pin offsets + rotation transforms (8 rotation variants)"
  - "Parallel RC circuit fixture replaces series fixture to ensure all pins connect to wires"
  - "Rotation validation rejects unknown values per threat model T-11-08"

requirements-completed: [LTSPICE-03]

# Metrics
duration: 5min
completed: 2026-05-23
---

# Phase 11 Plan 03: Net Connectivity Graph Summary

**Wire connectivity graph with FLAG propagation and pin-to-net matching via networkx, including wire segment splitting at component pin positions**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-23T18:00:35Z
- **Completed:** 2026-05-23T18:05:43Z
- **Tasks:** 1
- **Files modified:** 4

## Accomplishments
- LTspiceNetGraph.from_schematic() builds networkx graph from wire segments with splitting at pin positions
- FLAG net names propagate across connected components via nx.node_connected_component
- Component pin absolute positions computed from .asy stub offsets + 8 rotation transforms (R0-R270, M0-M270)
- Rotation validation mitigates threat T-11-08 (unknown rotation values raise ValueError)
- Query API: get_net_names(), get_pins_on_net(), get_connected_component(), are_connected(), get_net_stats()
- 11 tests covering wire connectivity, FLAG assignment, pin matching, and rail separation

## Task Commits

TDD RED/GREEN cycle:

1. **Task 1: Build wire connectivity graph and assign net names from FLAGs** - `44e7e36` (test RED) + `94a9b8e` (feat GREEN)

## Files Created/Modified
- `src/kicad_agent/ltspice/net_graph.py` - LTspiceNetGraph class with from_schematic(), query methods, wire splitting
- `tests/test_ltspice_net_graph.py` - 11 tests for wire connectivity, FLAG propagation, pin matching
- `src/kicad_agent/ltspice/__init__.py` - Added LTspiceNetGraph to barrel exports
- `tests/fixtures/ltspice/basic_rc.asc` - Updated to parallel RC circuit with proper pin-to-wire connections

## Decisions Made
- Wire segments split at pin interior points instead of only matching endpoints -- handles LTspice's common case where wires pass through pin positions without ending there
- Parallel RC circuit fixture instead of series -- ensures both pins of each component touch wire segments, which is required for testing pin-to-net matching
- .asy stub files loaded via AsyReader with caching per symbol -- avoids re-reading the same .asy file for multiple components
- Rotation validation raises ValueError for unknown rotations (mitigates threat T-11-08) -- consistent with threat model disposition

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Functionality] Fixed basic_rc.asc fixture for proper pin connectivity**
- **Found during:** Task 1 (pre-implementation analysis)
- **Issue:** Original fixture had wires that did not pass through component pin positions -- only R1.Pin2 (80,0) lay on a wire, other 5 pins had no electrical connection
- **Fix:** Redesigned fixture as parallel RC circuit with explicit wire routing through all 6 pin positions across VCC and GND rails
- **Files modified:** tests/fixtures/ltspice/basic_rc.asc
- **Verification:** All 11 net_graph tests pass, all 14 parser tests still pass with updated fixture

**2. [Rule 2 - Missing Functionality] Added wire segment splitting at pin positions**
- **Found during:** Task 1 (implementation)
- **Issue:** Plan described only adding wire endpoints as graph nodes, but LTspice pins often lie on wire segment interiors -- not at endpoints
- **Fix:** Added _point_on_segment() check and segment splitting logic: when a pin position lies on a wire interior, the segment is split into sub-segments at that point
- **Files modified:** src/kicad_agent/ltspice/net_graph.py
- **Verification:** get_pins_on_net("0") returns 3 pins (R1.Pin2, C1.Pin2, V1.Pin2)

---

**Total deviations:** 2 auto-fixed (both missing functionality)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep.

## Next Phase Readiness
- LTspiceNetGraph ready for KiCad-to-LTspice bridge mapping (future plan)
- Pin position calculation supports all 8 rotation variants
- Net membership queries enable cross-referencing KiCad nets with LTspice nets

---
*Phase: 11-ltspice-integration*
*Completed: 2026-05-23*

## Self-Check: PASSED

All 3 claimed files verified present. Both commit hashes (44e7e36, 94a9b8e) verified in git log.
