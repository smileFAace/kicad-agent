---
phase: 05-net-reference-footprint-operations
plan: 02
subsystem: ops-schema, ir-schematic
tags: [reference, renumber, annotate, schema, ir-layer, tdd]
dependency_graph:
  requires: [05-01]
  provides: [RenumberRefsOp, ValidateRefsOp, AnnotateOp, CrossRefCheckOp, SchematicIR ref management]
  affects: [schema.py, schematic_ir.py]
tech_stack:
  added: [re.compile for reference parsing, collections.Counter for duplicate detection]
  patterns: [TDD red-green, discriminated union extension, mutation tracking via _record_mutation, regex-based ref parsing with #PWR support]
key_files:
  created:
    - tests/test_ref_ops.py
  modified:
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ir/schematic_ir.py
decisions:
  - Reference regex pattern uses [#A-Za-z]+ prefix to handle KiCad power symbols (#PWR01 etc.)
  - Renumber only records changes when old_ref != new_ref (no-op when already sequential)
  - annotate_components finds max existing numeric suffix per prefix to avoid collisions
  - cross_reference_check builds valid_lib_ids set from schematic.libSymbols
  - Tests scramble fixture references before testing renumber to ensure mutations actually occur
metrics:
  duration: 7 min
  completed: "2026-05-18T08:41:14Z"
  tasks: 2
  tests_added: 24
  tests_passing: 307
  files_modified: 3
---

# Phase 05 Plan 02: Reference Management Operations Summary

Four reference management operation types added to Pydantic discriminated union; SchematicIR gains renumber, validate uniqueness, annotate, and cross-reference check methods with mutation tracking.

## Commits

| Hash | Message |
|------|---------|
| b6db689 | test(05-02): add failing tests for reference management schema and IR methods |
| 486cedf | feat(05-02): add four reference management operation types to schema |
| 22922b6 | feat(05-02): implement reference management methods on SchematicIR |

## What Was Done

### Task 1: Schema Types (TDD)

Added four new operation models to `schema.py`:

- **RenumberRefsOp** -- op_type="renumber_refs", prefix (default "" for all), start_index (ge=1, default 1), step (ge=1, default 1)
- **ValidateRefsOp** -- op_type="validate_refs", target_file only
- **AnnotateOp** -- op_type="annotate", prefix_filter (default "" for all)
- **CrossRefCheckOp** -- op_type="cross_ref_check", target_file only

All types added to the `Operation.root` discriminated union with Field(discriminator="op_type").

### Task 2: SchematicIR Methods (TDD)

**SchematicIR** (`schematic_ir.py`):
- `get_all_references()` -- returns list of (reference, libId) tuples for all schematic symbols
- `_set_component_reference(component, new_ref)` -- updates the "Reference" property on a symbol
- `renumber_references(prefix, start_index, step)` -- renumbers refs grouped by prefix, records mutations per change
- `validate_reference_uniqueness()` -- uses Counter to find duplicate references, returns list of dupes
- `annotate_components(prefix_filter)` -- finds "?"-suffixed refs, assigns sequential numbers from max+1 per prefix
- `cross_reference_check()` -- builds valid libId set from libSymbols, returns unresolved (ref, libId) pairs

## Test Results

24 tests, all passing. 307 total tests passing, zero regressions.

Tests exercise real Arduino_Mega fixture: 14 components with J1-J7 and #PWR01-#PWR07 references.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed reference regex to handle KiCad power symbol prefix**
- **Found during:** Task 2 GREEN phase
- **Issue:** Arduino_Mega fixture has `#PWR01`-style references that the plan's regex `^([A-Za-z]+)(\d+|\?)$` cannot parse
- **Fix:** Changed regex to `^([#A-Za-z]+)(\d+|\?)$` to include `#` character in prefix
- **Files modified:** src/kicad_agent/ir/schematic_ir.py
- **Commit:** 22922b6

**2. [Rule 3 - Blocking] Fixed test assumptions about fixture component references**
- **Found during:** Task 2 GREEN phase
- **Issue:** Plan stated Arduino_Mega has "J1, J2, J3, U1, U2, Y1, P1" but actual fixture has J1-J7 and #PWR01-#PWR07 (no U, Y, or P components)
- **Fix:** Updated tests to match actual fixture data; tests now scramble references before testing renumber operations
- **Files modified:** tests/test_ref_ops.py
- **Commit:** 22922b6

## Verification

1. `python -m pytest tests/test_ref_ops.py -v` -- 24 passed
2. `python -m pytest tests/ -q` -- 307 passed, 0 failed
3. `python -c "from kicad_agent.ops.schema import get_operation_schema; s = get_operation_schema(); assert 'RenumberRefsOp' in str(s)"` -- passes
4. Renumber cycle on Arduino_Mega fixture preserves reference format correctness

## Self-Check: PASSED

All files verified present. All commit hashes verified in git log.
