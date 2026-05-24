---
phase: 16-component-placement-ai
plan: 04
subsystem: placement
tags: [interactive, hybrid-engine, sa-refinement, constraint-propagation, barrel-exports]
dependency_graph:
  requires: [16-02, 16-03]
  provides: [HybridPlacementEngine, interactive_placement, PlacementRequest, PlacementOutput]
  affects: [placement/__init__.py]
tech_stack:
  added: [scipy.optimize.dual_annealing, pydantic BaseModel for request/response]
  patterns: [constraint-propagation, ml-first-with-fallback, interactive-placement]
key_files:
  created:
    - src/kicad_agent/placement/interactive.py
    - src/kicad_agent/placement/engine.py
    - tests/test_placement_interactive.py
    - tests/test_placement_engine.py
  modified:
    - src/kicad_agent/placement/__init__.py
decisions:
  - Clamped SA params inside objective function and final result (dual_annealing local search can step outside bounds)
  - ConstraintSet as frozen dataclass matching project pattern
  - PlacementRequest/PlacementOutput as Pydantic BaseModel for validation
  - Per-component scores computed from average HPWL contribution across connected nets
  - Rule-based PlacementEngine instantiated lazily on first fallback use
metrics:
  duration: 10min
  completed: 2026-05-24T01:29:46Z
  tasks: 2
  files: 5
  tests_added: 24
  tests_passing: 1185
---

# Phase 16 Plan 04: Interactive Placement and Hybrid Engine Summary

Interactive constraint-based placement with SA refinement and hybrid ML/rule-based engine wiring all placement components into a single end-to-end pipeline.

## Completed Tasks

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Interactive placement with constraint propagation and SA refinement | f932547 | interactive.py, test_placement_interactive.py |
| 2 | Hybrid placement engine and barrel export updates | 5533aec | engine.py, __init__.py, test_placement_engine.py |

## What Was Built

### Task 1: Interactive Placement (interactive.py)

- `ConstraintSet`: Frozen dataclass holding fixed_positions, keepout_zones, min_clearance, max_sa_iterations
- `interactive_placement()`: Partitions components into fixed/free, runs scipy dual_annealing on free positions only
- Fixed components NEVER appear in SA parameter vector (pitfall 5 from RESEARCH.md)
- Grid fallback distributes free components evenly, avoiding fixed positions
- Clearance penalty (10x) against fixed components, keepout zone penalty (20x)
- `suggest_placements()`: Convenience wrapper for quick interactive placement

### Task 2: Hybrid Engine (engine.py)

- `PlacementRequest`: Pydantic-validated input with board dims > 0, component cap at 500
- `PlacementOutput`: Result with positions, score, HPWL, validity, source, per-component scores
- `HybridPlacementEngine`: ML-first strategy with decision logic:
  - Fixed positions provided -> interactive mode (source="interactive")
  - use_ml=True and predictor ready -> ML prediction (source="ml_prediction" or "ml_refined")
  - Otherwise -> rule-based grid fallback (source="rule_based")
- `place_components_simple()`: Minimal API for basic usage
- Updated barrel exports: 24 symbols covering all placement modules

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] dual_annealing local search steps outside bounds**
- **Found during:** Task 1 test execution (TestFreeComponentsInBounds failure)
- **Issue:** scipy dual_annealing with local search can produce parameter values outside declared bounds, causing components to be placed beyond board edges
- **Fix:** Clamped parameter values inside the objective function AND clamped final result positions to board bounds as safety net
- **Files modified:** interactive.py
- **Commit:** f932547

## Test Results

- test_placement_interactive.py: 11 passed
- test_placement_engine.py: 13 passed
- Full suite: 1185 passed, 1 skipped, 0 failures

## Verification

- All 4 verification commands pass:
  1. `pytest tests/test_placement_interactive.py tests/test_placement_engine.py` -- 24 passing
  2. `from kicad_agent.placement import HybridPlacementEngine, PlacementGraph, interactive_placement` -- OK
  3. `from kicad_agent.placement.engine import PlacementRequest, PlacementOutput` -- OK
  4. Full test suite: 1185 passed, 0 failures
  5. Barrel export count: 24 symbols

## Phase 16 Complete

All 4 plans delivered:
- Plan 01: Bipartite graph construction (graph.py, features.py)
- Plan 02: GNN model and training pipeline (model.py, predict.py, training/)
- Plan 03: DRC validation and quality scoring (validation.py, scoring.py)
- Plan 04: Interactive placement and hybrid engine (interactive.py, engine.py)
