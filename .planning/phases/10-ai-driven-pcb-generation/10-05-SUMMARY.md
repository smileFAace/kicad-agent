---
phase: 10-ai-driven-pcb-generation
plan: 05
subsystem: generation
tags: [placement, op-planner, clearance, spatial-scoring]
dependency_graph:
  requires: [10-04]
  provides: [placement-engine, op-planner]
  affects: [generation-module]
tech_stack:
  added: [shapely-clearance-validation, grid-placement-algorithm]
  patterns: [dependency-ordered-plan-steps, pairwise-clearance-checks]
key_files:
  created:
    - src/kicad_agent/generation/placement.py
    - src/kicad_agent/generation/op_planner.py
    - tests/test_placement.py
    - tests/test_op_planner.py
  modified:
    - src/kicad_agent/generation/__init__.py
decisions:
  - Grid placement algorithm chosen over optimization for deterministic results
  - Default 2mm bounding box per component for clearance checks
  - Relative paths in PlanStep operations (schema rejects absolute paths)
metrics:
  duration: 6 min
  completed: "2026-05-23T05:28:00Z"
  tasks: 2
  tests_added: 21
  tests_passing: 21
---

# Phase 10 Plan 05: Component Placement Engine and Operation-Sequence Planner Summary

Grid-based placement engine with Shapely clearance validation and dependency-ordered operation sequencing that converts GenerationIntent into executable PlanSteps.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Component placement engine with clearance validation | 03b2049 | placement.py, test_placement.py |
| 2 | Operation-sequence planner | abf85f0 | op_planner.py, test_op_planner.py |
| - | Generation barrel exports | c1ee154 | __init__.py |

## Key Implementation Details

### PlacementEngine (placement.py)
- Grid placement algorithm divides board into cells based on component count
- Components sorted by estimated size (ICs largest, passives smallest)
- `validate_placement_clearance` uses Shapely geometry pairwise distance checks
- `place_decoupling_caps` places bypass caps within 5mm of IC power pins
- `score_placement` computes weighted score: 30% wire length, 40% clearance, 30% edge penalty
- 500 component cap for DoS mitigation (T-10-15)
- All coordinates validated within board bounds (T-10-16)

### OpPlanner (op_planner.py)
- Converts GenerationIntent into dependency-ordered PlanSteps
- Each PlanStep wraps an existing Operation from schema.py with dependency tracking
- Dependency chain: board outline -> components -> power -> nets -> wires -> repair -> validation
- `plan_operation_sequence` convenience function for one-shot planning
- Uses relative paths for target_file (schema rejects absolute paths)

## Verification Results

- All 21 new tests passing (13 placement + 8 planner)
- Full test suite: 795 passed, 6 pre-existing failures (Arduino Mega fixture compatibility)
- No regressions introduced

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] target_file validation rejected absolute paths**
- **Found during:** Task 2 (op_planner.py)
- **Issue:** SetBoardOutlineOp and other ops rejected absolute paths like `/tmp/TestBoard.kicad_pcb`
- **Fix:** Changed all step builders to use relative filenames (`TestBoard.kicad_pcb`) instead of `self._target_dir / filename`
- **Files modified:** op_planner.py
- **Commit:** abf85f0

**2. [Rule 1 - Bug] Test positions caused clearance score inversion**
- **Found during:** Task 1 (test_placement.py)
- **Issue:** Close positions (2mm apart) with 2mm-wide boxes overlapped, causing clearance score = 0, making close score worse than far score
- **Fix:** Adjusted test positions to be 6mm apart (clearance ~4mm, above 1mm minimum)
- **Files modified:** test_placement.py
- **Commit:** 03b2049

## Threat Flags

No new threat surface beyond what the plan's threat model already covers. T-10-15 (DoS via pairwise checks) mitigated by 500 component cap. T-10-16 (coordinate tampering) mitigated by bounds validation.

## Self-Check: PASSED

- [x] src/kicad_agent/generation/placement.py exists
- [x] src/kicad_agent/generation/op_planner.py exists
- [x] tests/test_placement.py exists
- [x] tests/test_op_planner.py exists
- [x] Commit 03b2049 exists
- [x] Commit abf85f0 exists
- [x] Commit c1ee154 exists
