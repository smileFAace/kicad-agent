---
phase: "32"
plan: "01"
subsystem: executor-performance
tags: [cache, performance, ir, executor]
dependency_graph:
  requires: [parser, ir-base, executor]
  provides: [ir-cache, executor-cache-integration]
  affects: [executor]
tech_stack:
  added: [OrderedDict LRU, threading.Lock]
  patterns: [cache-aside, mtime-invalidation]
key_files:
  created:
    - src/kicad_agent/ops/ir_cache.py
    - tests/test_ir_cache.py
  modified:
    - src/kicad_agent/ops/executor.py
decisions:
  - mtime_ns as cache key (nanosecond resolution avoids false hits on fast writes)
  - OrderedDict for LRU (stdlib, no dependencies, O(1) eviction)
  - cache-aside pattern (executor checks/puts, cache is passive)
  - invalidate-after-write to handle Transaction rollback correctly
metrics:
  duration: 1953s
  completed: 2026-05-30
  tasks: 2
  files: 3
---

# Phase 32 Plan 01: IR Caching Layer Summary

IR caching layer that eliminates redundant file parsing for sequential operations on the same file. IRCache stores ParseResult + UUIDMap keyed by (file_path, mtime_ns), returning cached data when the file hasn't changed.

## What Was Done

### Task 1: IRCache Module (commit 8ac702c)

Created `src/kicad_agent/ops/ir_cache.py` with:

- **CacheEntry** frozen dataclass: stores `parse_result: ParseResult` and optional `uuid_map`
- **IRCache** class with LRU eviction via `OrderedDict`:
  - `get(file_path)` -- resolves path, reads `os.stat().st_mtime_ns`, looks up `(resolved, mtime)` key, moves to end on hit (LRU)
  - `put(file_path, entry)` -- resolves path, reads mtime, inserts/moves-to-end, evicts oldest if over max_size
  - `invalidate(file_path)` -- removes all entries for a specific resolved path
  - `clear()` -- removes all entries
  - Thread-safe via `threading.Lock` on all public methods
  - `max_size` parameter (default 64), validated >= 1

12 unit tests covering: cache hit/miss by mtime, LRU eviction, invalidation, clear, MRU promotion, concurrent access (8 threads), CacheEntry fields, edge cases (nonexistent file, invalid max_size, invalidating missing path).

### Task 2: Executor Integration (commit 9cd1d41)

Modified `src/kicad_agent/ops/executor.py`:

- **OperationExecutor.__init__**: accepts optional `cache: Optional[IRCache]` keyword argument (backward compatible -- defaults to None)
- **_execute_schematic**: checks cache before `parse_schematic()`, stores on miss, invalidates and re-stores after Transaction commit
- **_execute_pcb**: checks cache before `parse_pcb()` + `extract_uuids()`, stores with uuid_map on miss, invalidates and re-stores after Transaction commit
- **_execute_query**: checks cache before `parse_pcb()` + `extract_uuids()`, stores with uuid_map on miss (read-only, no invalidation needed)

5 integration tests covering: cache reuse (parse count verified via mock), mtime change triggers re-parse, backward compatibility without cache, cache updated after successful write, PCB cache hit includes uuid_map.

## Deviations from Plan

None -- plan executed exactly as written.

## Test Results

- `tests/test_ir_cache.py`: 17/17 passed
- `tests/test_mcp/test_edit_server.py`: 37/37 passed (regression)
- `tests/test_executor_ops.py`: 8/8 passed (regression)

### Pre-existing Failures (out of scope)

Three test failures from a pre-existing IR registry leak between tests that create PcbIR objects directly (not via executor). These existed before this plan and are unrelated:

- `tests/test_connectivity_query.py::TestQueryExecutor::test_shortest_path_returns_path` -- IR registry leak from prior test
- `tests/test_pcb_ops.py::TestAssignNetClass::test_assign_net_class_creates_new_class` -- same pattern
- `tests/test_add_component.py::TestOperationExecutorAdd::test_full_pipeline_add_component` -- same pattern (order-dependent)

Root cause: tests create PcbIR directly without calling `_clear_registry()`, so `id(parse_result)` persists in the global `_ir_registry` across test boundaries.

## Self-Check: PASSED

- `src/kicad_agent/ops/ir_cache.py`: FOUND
- `tests/test_ir_cache.py`: FOUND
- `src/kicad_agent/ops/executor.py`: FOUND (modified)
- Commit `8ac702c`: FOUND
- Commit `9cd1d41`: FOUND
