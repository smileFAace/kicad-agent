# Phase 32: Executor Performance - Research

**Researched:** 2026-05-30
**Domain:** IR caching, batch operation execution, file I/O elimination
**Confidence:** HIGH

## Summary

Phase 32 targets the primary performance bottleneck in kicad-agent: every `execute()` call performs a full parse-mutate-serialize-normalize-write cycle, even when 100 sequential operations target the same file. For an LLM agent making 100 property modifications on a single schematic, this means 100 full file reads, 100 kiutils parses, 100 serializations, and 100 file writes. The goal is to reduce this to 1 parse, 100 in-memory mutations, and 1 write -- a theoretical 100x reduction in I/O overhead.

The current `OperationExecutor.execute()` in `src/kicad_agent/ops/executor.py` (1090 lines) follows a clean dispatch pattern: parse file -> build IR -> Transaction(snapshot) -> dispatch to handler -> serialize -> normalize -> commit. The key insight is that the parse and serialize steps are the expensive operations (file I/O + kiutils parsing), while the IR mutations themselves are fast in-memory operations on kiutils objects. Two new capabilities are needed: (1) an LRU cache keyed by `(file_path, mtime)` that returns the same IR when the file hasn't changed, and (2) a batch execution mode that validates all operations upfront, then applies mutations to a single IR instance before writing once.

**Primary recommendation:** Add an `IRCache` class with LRU semantics and an `execute_batch()` method on `OperationExecutor`. The cache stores `(ParseResult, Optional[UUIDMap])` keyed by `(resolved_path, mtime_ns)`. The batch method validates all operations against a single parsed IR, then applies mutations sequentially, then serializes once.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PERF-01 | IR caching layer -- LRU cache keyed by `(file_path, mtime)`, re-parse only on disk change | IRCache class storing `(ParseResult, Optional[UUIDMap])` keyed by `(resolved_path, mtime_ns)`. `os.stat().st_mtime_ns` for nanosecond-precision change detection. See Architecture Patterns. |
| PERF-02 | Batch mode -- `execute_batch(ops)` parses file once, applies all mutations, validates once, writes once | `execute_batch()` method on `OperationExecutor`. Groups ops by target file, validates all ops against single IR per file, applies mutations, serializes once per file. See Pattern 2. |
| PERF-03 | Batch validates ALL operations before executing ANY -- rejects entire batch on validation failure | Two-phase batch: Phase 1 validates every op and collects errors; Phase 2 applies only if all valid. Atomic rejection with error report listing all failures. See Pattern 2. |
| PERF-04 | Benchmark: 100 property modifications in <10s (vs ~100s sequential) | Benchmark test using `time.perf_counter()` on 100 `modify_property` ops against a real schematic fixture. See Validation Architecture. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| IR caching (ParseResult storage) | API / Backend | -- | Executor is the sole consumer of parse results; cache lives in executor layer |
| mtime-based cache invalidation | API / Backend | -- | File metadata check is a backend concern |
| Batch validation (all-or-nothing) | API / Backend | -- | Pre-execution validation is a backend gate |
| Batch mutation application | API / Backend | -- | Sequential IR mutations are in-memory backend operations |
| Benchmark test | Test suite | -- | Performance validation is test infrastructure |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `functools` | stdlib | LRU cache pattern reference (not directly used -- custom class needed) | Python stdlib, well-understood eviction semantics [ASSUMED] |
| `os.stat` | stdlib | `st_mtime_ns` for nanosecond file modification time | Built-in, cross-platform mtime with nanosecond precision [VERIFIED: Python 3.11 stdlib] |
| `collections.OrderedDict` | stdlib | LRU cache implementation backing store | Maintains insertion order for LRU eviction [VERIFIED: Python 3.11 stdlib] |
| `threading.Lock` | stdlib | Thread-safe cache access | Already used in `_ir_registry_lock` pattern in base.py [VERIFIED: codebase] |
| `dataclasses` | stdlib | `CacheEntry` frozen dataclass | Already used throughout the codebase [VERIFIED: codebase] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `time.perf_counter` | stdlib | High-resolution benchmark timing | Benchmark test for PERF-04 |
| `pytest` | ~8.x | Test framework | Existing test infrastructure |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom LRU cache | `functools.lru_cache` | `lru_cache` requires hashable keys; `Path` objects are hashable but we need mutable cache control (invalidate, clear) and the key includes mtime which changes. Custom class gives explicit control over invalidation and eviction. |
| `os.stat().st_mtime_ns` | file content hash (SHA256) | Hash is 100% reliable but requires reading the entire file. mtime_ns is O(1) stat call and sufficient for our use case (only kicad-agent writes to these files during a session). |
| OrderedDict LRU | `cachetools.LRUCache` | No new dependency needed for something achievable in ~30 lines with OrderedDict. |

**Installation:**
```bash
# No new dependencies needed -- all stdlib
```

**Version verification:** All libraries are Python stdlib, no package installation required.

## Architecture Patterns

### System Architecture Diagram

```
                    execute_batch(ops: list[Operation])
                                |
                                v
                    +--- Group by target_file ---+
                    |                             |
                    v                             v
            [file_A ops]                  [file_B ops]
                    |                             |
                    v                             v
            Check IRCache               Check IRCache
            (path, mtime) hit?          (path, mtime) hit?
               /      \                    /      \
            YES        NO              YES        NO
             |          |               |          |
             v          v               v          v
        Return      Parse file     Return      Parse file
        cached      + build IR     cached      + build IR
        (PR,UM)       |            (PR,UM)       |
             |        |               |          |
             v        v               v          v
        +----+--------+----+   +-----+----------+----+
        |  Validate ALL ops  |   |  Validate ALL ops  |
        |  against single IR |   |  against single IR |
        +----+--------+------|   +-----+----------+---+
             |        |              |          |
         ANY FAIL?  ALL OK?      ANY FAIL?  ALL OK?
             |        |              |          |
             v        v              v          v
        Reject    Apply all      Reject    Apply all
        batch     mutations      batch     mutations
                     |                          |
                     v                          v
              Serialize once              Serialize once
              + normalize                 + normalize
                     |                          |
                     v                          v
              Write once                   Write once
              Update cache                 Update cache
              (new mtime)                  (new mtime)
```

### Recommended Project Structure
```
src/kicad_agent/ops/
  executor.py           # Modified: add IRCache, execute_batch()
  ir_cache.py           # NEW: IRCache class (LRU, thread-safe, mtime-keyed)
tests/
  test_ir_cache.py      # NEW: IRCache unit tests
  test_batch_executor.py # NEW: execute_batch tests + benchmark
```

### Pattern 1: IRCache with mtime-based Invalidation
**What:** A thread-safe LRU cache that stores parsed IR results keyed by `(file_path, mtime_ns)`.
**When to use:** Every `execute()` and `execute_batch()` call checks cache before parsing.
**Example:**
```python
# Source: [ASSUMED pattern, verified against stdlib capabilities]
from dataclasses import dataclass
from pathlib import Path
from collections import OrderedDict
from threading import Lock
from typing import Optional, Any
import os

from kicad_agent.parser.types import ParseResult
from kicad_agent.parser.uuid_extractor import UUIDMap


@dataclass(frozen=True)
class CacheEntry:
    """Immutable cache entry holding parse result and optional UUID map."""
    parse_result: ParseResult
    uuid_map: Optional[UUIDMap] = None


class IRCache:
    """Thread-safe LRU cache for parsed KiCad IR results.

    Keyed by (resolved_path, mtime_ns). Re-uses cached ParseResult
    when file has not changed on disk. Bounded to max_size entries
    with LRU eviction.
    """

    def __init__(self, max_size: int = 64) -> None:
        self._cache: OrderedDict[tuple[Path, int], CacheEntry] = OrderedDict()
        self._lock = Lock()
        self._max_size = max_size

    def get(self, file_path: Path) -> Optional[CacheEntry]:
        """Return cached entry if file unchanged, else None."""
        resolved = file_path.resolve()
        mtime = os.stat(resolved).st_mtime_ns
        key = (resolved, mtime)

        with self._lock:
            entry = self._cache.get(key)
            if entry is not None:
                # Move to end (most recently used)
                self._cache.move_to_end(key)
            return entry

    def put(self, file_path: Path, entry: CacheEntry) -> None:
        """Store a cache entry. Evicts LRU if at capacity."""
        resolved = file_path.resolve()
        mtime = os.stat(resolved).st_mtime_ns
        key = (resolved, mtime)

        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                self._cache[key] = entry
                if len(self._cache) > self._max_size:
                    self._cache.popitem(last=False)  # Remove oldest

    def invalidate(self, file_path: Path) -> None:
        """Remove all entries for a given file path (all mtimes)."""
        resolved = file_path.resolve()
        with self._lock:
            keys_to_remove = [
                k for k in self._cache if k[0] == resolved
            ]
            for k in keys_to_remove:
                del self._cache[k]

    def clear(self) -> None:
        """Clear the entire cache."""
        with self._lock:
            self._cache.clear()
```

### Pattern 2: Batch Execution with Pre-Validation
**What:** `execute_batch(ops)` validates all operations against a single IR, rejects the entire batch if any fail, then applies all mutations before writing once.
**When to use:** When an LLM agent sends multiple operations targeting the same file (e.g., 100 property modifications).
**Example:**
```python
# Source: [ASSUMED pattern based on executor.py architecture]
from kicad_agent.ops.executor import OperationExecutor
from kicad_agent.ir.base import _clear_registry

def execute_batch(self, ops: list[Operation]) -> dict[str, Any]:
    """Execute multiple operations with single parse/write per file.

    PERF-02: Parses each file once, applies all mutations, validates
    once, writes once.
    PERF-03: Validates ALL operations before executing ANY.

    Returns:
        Dict with success, results list, and any validation errors.
    """
    if not ops:
        return {"success": True, "results": []}

    # Group operations by target file
    file_ops: dict[Path, list[Operation]] = {}
    for op in ops:
        root = op.root
        file_path = self._base_dir / root.target_file
        # Security check (T-24-01)
        resolved = file_path.resolve()
        base_resolved = self._base_dir.resolve()
        if not resolved.is_relative_to(base_resolved):
            raise ValueError(f"Security: path escapes project: {root.target_file}")
        file_ops.setdefault(file_path, []).append(op)

    # Phase 1: Parse files (using cache) and validate ALL ops
    _clear_registry()
    ir_map: dict[Path, Any] = {}
    validation_errors: list[dict] = []

    for file_path, file_op_list in file_ops.items():
        # Check cache
        cached = self._cache.get(file_path) if self._cache else None
        if cached is not None:
            # CRITICAL: Must create new IR from cached ParseResult
            # (one-IR-per-ParseResult invariant requires fresh IR)
            # BUT: batch reuses the same IR for all ops on this file
            # So we create one IR here and apply all ops to it
            if file_path.suffix == ".kicad_pcb":
                ir_map[file_path] = PcbIR(
                    _parse_result=cached.parse_result,
                    _uuid_map=cached.uuid_map,
                )
            else:
                ir_map[file_path] = SchematicIR(
                    _parse_result=cached.parse_result,
                )
        else:
            # Parse fresh
            ir_map[file_path] = self._parse_file(file_path)

        # Validate all ops against this IR
        for op in file_op_list:
            try:
                self._validate_op(op, ir_map[file_path], file_path)
            except (ValueError, FileNotFoundError) as exc:
                validation_errors.append({
                    "op_type": op.root.op_type,
                    "target_file": op.root.target_file,
                    "error": str(exc),
                })

    # PERF-03: Reject entire batch on any validation failure
    if validation_errors:
        return {
            "success": False,
            "results": [],
            "validation_errors": validation_errors,
            "error": f"Batch rejected: {len(validation_errors)} validation failures",
        }

    # Phase 2: Apply mutations + serialize + write (per file)
    results = []
    for file_path, file_op_list in file_ops.items():
        ir = ir_map[file_path]

        with Transaction(file_path) as txn:
            for op in file_op_list:
                detail = self._dispatch(op.root.op_type, op.root, ir, file_path)
                results.append({
                    "success": True,
                    "operation": op.root.op_type,
                    "target_file": op.root.target_file,
                    "details": detail,
                })

            # Serialize once per file
            self._serialize_ir(ir, file_path)
            txn.commit()

        # Update cache with new state
        if self._cache:
            self._cache.invalidate(file_path)
            # Re-parse to get fresh ParseResult for cache
            # OR store the mutated parse_result directly
            entry = CacheEntry(
                parse_result=ir._parse_result,
                uuid_map=getattr(ir, '_uuid_map', None),
            )
            self._cache.put(file_path, entry)

    return {"success": True, "results": results}
```

### Anti-Patterns to Avoid
- **Cache returning same IR instance across operations:** The `_ir_registry` in `base.py` enforces one-IR-per-ParseResult. Cache must store `ParseResult` + `UUIDMap`, not IR instances directly. Each cache consumer creates a new IR from the cached ParseResult. [VERIFIED: base.py lines 35-43]
- **Batch with partial success:** PERF-03 requires all-or-nothing. Never write partial results from a batch.
- **Caching mutated IR:** After mutations, the IR is dirty. The cache must be invalidated after writes, not store the mutated state. The next read should re-parse from the newly written file (or store post-serialize state with new mtime).
- **Ignoring the registry clear:** `_clear_registry()` is called at the start of `execute()`. Batch must also call it, but only once at the start, not per-operation.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Thread-safe LRU cache | Custom lock + dict + eviction logic | `collections.OrderedDict` + `threading.Lock` | OrderedDict maintains insertion order, `popitem(last=False)` evicts oldest. ~30 lines vs ~100 for full custom. |
| File change detection | Content hashing or size comparison | `os.stat().st_mtime_ns` | Nanosecond-precision mtime is sufficient; kicad-agent is the only writer during a session. O(1) vs O(n). |
| Benchmark timing | Custom timing harness | `time.perf_counter()` | Highest resolution timer available, stdlib, no dependency. |

**Key insight:** The existing codebase already has `OrderedDict` usage (in `_mutation_log` via `deque`) and `threading.Lock` (in `_ir_registry_lock`). The patterns are established and familiar.

## Common Pitfalls

### Pitfall 1: One-IR-per-ParseResult Registry Violation
**What goes wrong:** The `_ir_registry` in `base.py` raises `RuntimeError` if you try to create two IR instances from the same `ParseResult`. If the cache returns the same `ParseResult` and you create an IR from it, a second cache hit for the same file will fail.
**Why it happens:** The registry uses `id(parse_result)` to track ownership. Same object = same id = duplicate registration.
**How to avoid:** The cache stores `ParseResult`. When a batch or execute needs IR, it creates exactly one IR per ParseResult. For sequential `execute()` calls that hit cache, each call must clear the registry first (already done in `execute()` line 760). For batch, create one IR per file and apply all ops to it.
**Warning signs:** `RuntimeError: ParseResult already has an IR wrapper` in cache hit path.

### Pitfall 2: Stale Cache After Mutation
**What goes wrong:** After a mutation + serialize + write, the file's mtime changes. A subsequent cache lookup with the new mtime misses and re-parses, defeating the purpose of caching.
**Why it happens:** The cache key includes mtime. After writing, mtime changes, so the old entry is orphaned and a new parse is triggered.
**How to avoid:** After a successful write, store the new entry in the cache with the new mtime. The `put()` method will add it. Optionally, since batch just wrote and the ParseResult is still in memory, store it directly without re-parsing.
**Warning signs:** Cache hit rate near 0% for sequential operations on the same file.

### Pitfall 3: PCB UUID Map Not Cached
**What goes wrong:** PCB parsing requires two steps: `parse_pcb()` + `extract_uuids()`. If cache only stores `ParseResult` but not `UUIDMap`, the expensive UUID extraction runs on every cache hit.
**Why it happens:** `extract_uuids()` scans the entire raw_content string with regex -- it's nearly as expensive as parsing for large files.
**How to avoid:** `CacheEntry` stores both `ParseResult` and `Optional[UUIDMap]`. For PCB files, both are cached together.
**Warning signs:** Benchmark shows minimal improvement for PCB files despite cache hits.

### Pitfall 4: Transaction Snapshot Conflicts with Cache
**What goes wrong:** `Transaction.__enter__` calls `shutil.copy2` to create a snapshot. If the executor is using a cached IR whose underlying file gets modified by another process, the snapshot captures the current disk state (which may differ from the cached IR state).
**Why it happens:** Cache stores ParseResult from a previous parse. Between cache storage and batch execution, the file could theoretically change (unlikely in single-process use, but possible in concurrent MCP sessions).
**How to avoid:** Verify mtime immediately before creating the Transaction. If mtime changed, invalidate cache and re-parse. The batch should check mtime once at the start, not per-operation.
**Warning signs:** File corruption after rollback (snapshot doesn't match IR state).

### Pitfall 5: Batch Op Dispatching to Wrong Registry
**What goes wrong:** Batch operations might include a mix of schematic and PCB operations targeting different files. Dispatching a PCB op through `_SCHEMATIC_HANDLERS` or vice versa.
**Why it happens:** Grouping by file type requires checking each op's target file extension and dispatching to the correct handler registry.
**How to avoid:** The existing `execute()` already branches on `file_path.suffix`. Batch should use the same logic per file group: `.kicad_pcb` goes to `_PCB_HANDLERS`, everything else to `_SCHEMATIC_HANDLERS`.
**Warning signs:** `ValueError: Unknown op_type` for valid operations.

## Code Examples

### IR Cache Integration with Executor
```python
# Source: [ASSUMED pattern based on executor.py architecture analysis]

# In executor.py, modify __init__ to accept optional cache:
class OperationExecutor:
    def __init__(self, base_dir: Path, *, cache: Optional[IRCache] = None) -> None:
        self._base_dir = base_dir
        self._cache = cache  # Shared across calls for session-level caching

    def execute(self, op: Operation) -> dict[str, Any]:
        """Single operation execution with optional cache hit."""
        # ... existing security checks ...

        # Check cache before parsing
        if self._cache and file_path.suffix == ".kicad_pcb":
            cached = self._cache.get(file_path)
            if cached:
                # Use cached ParseResult + UUIDMap
                ir = PcbIR(_parse_result=cached.parse_result, _uuid_map=cached.uuid_map)
                # ... dispatch, serialize, commit ...
                # Update cache after write
                self._cache.invalidate(file_path)
                self._cache.put(file_path, CacheEntry(
                    parse_result=ir._parse_result,
                    uuid_map=ir._uuid_map,
                ))
                return result

        # ... existing parse path (cache miss) ...
```

### Benchmark Test Pattern
```python
# Source: [ASSUMED pattern]
import shutil
import time
from pathlib import Path

import pytest

from kicad_agent.ops.executor import OperationExecutor
from kicad_agent.ops.schema import Operation

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestBatchPerformance:
    """PERF-04: Benchmark test for batch execution throughput."""

    def test_batch_100_property_mods_under_10s(self, tmp_path: Path) -> None:
        """100 property modifications via batch must complete in <10s."""
        # Setup: copy schematic with enough components
        src = FIXTURE_DIR / "Arduino_Mega" / "Arduino_Mega.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy2(src, dst)

        executor = OperationExecutor(base_dir=tmp_path)

        # Build 100 modify_property operations
        ops = []
        for i in range(100):
            op = Operation.model_validate({
                "root": {
                    "op_type": "modify_property",
                    "target_file": "test.kicad_sch",
                    "reference": "J1",
                    "property_name": f"CustomProp{i}",
                    "new_value": f"Value{i}",
                }
            })
            ops.append(op)

        # Measure batch execution
        start = time.perf_counter()
        result = executor.execute_batch(ops)
        elapsed = time.perf_counter() - start

        assert result["success"] is True
        assert len(result["results"]) == 100
        assert elapsed < 10.0, f"Batch took {elapsed:.2f}s, exceeds 10s target"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Parse-per-operation | Cache-aware parsing | Phase 32 (this phase) | 10x+ throughput on sequential edits |
| Sequential execute() | Batch execute_batch() | Phase 32 (this phase) | Single parse/write cycle per batch |
| No file change detection | mtime_ns invalidation | Phase 32 (this phase) | Cache auto-invalidates on external file changes |

**Deprecated/outdated:**
- None yet -- this is a new capability

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `functools.lru_cache` cannot be used directly because keys include mutable mtime and we need explicit invalidation control | Standard Stack | Low -- custom OrderedDict implementation is well-understood |
| A2 | `os.stat().st_mtime_ns` is sufficient for change detection (kicad-agent is the only writer during a session) | Architecture Patterns | Medium -- if concurrent MCP sessions modify the same file, stale cache reads could occur. Mitigate with mtime check before Transaction. |
| A3 | `_ir_registry` one-IR-per-ParseResult invariant requires clearing before batch IR creation | Common Pitfalls | High -- if registry semantics change, cache integration breaks. Must clear registry once at batch start. |
| A4 | 100 property modifications currently takes ~100s sequentially (implied by <10s target being 10x improvement) | Phase Requirements | Low -- actual baseline will be measured by benchmark test |
| A5 | `extract_uuids()` for PCB files is expensive enough to warrant caching alongside ParseResult | Common Pitfalls | Medium -- if UUID extraction is fast, caching UUIDMap adds complexity for minimal gain. Profile to confirm. |

## Open Questions

1. **Should the cache be shared across OperationExecutor instances?**
   - What we know: MCP server creates one executor per session. Batch and sequential calls within a session use the same executor.
   - What's unclear: Whether multiple MCP sessions might share a project directory.
   - Recommendation: Start with per-executor cache (simplest). If multi-session caching is needed, promote to a module-level singleton later.

2. **Should batch support cross-file operations?**
   - What we know: Cross-file operations (propagate_symbol_change) already have their own dispatch path.
   - What's unclear: Whether batch should include cross-file ops mixed with single-file ops.
   - Recommendation: Start with single-file ops only in batch. Cross-file ops already parse all files and coordinate -- adding them to batch adds complexity for no clear benefit.

3. **How should batch handle operations targeting different files?**
   - What we know: PERF-02 says "parses file once" -- singular. But batch could contain ops for multiple files.
   - What's unclear: Whether the benchmark targets single-file or multi-file batches.
   - Recommendation: Support multi-file batches by grouping ops by target file. Each file group gets its own parse-mutate-serialize cycle. This still eliminates redundant I/O per file.

## Environment Availability

Step 2.6: SKIPPED (no external dependencies identified -- all changes use Python stdlib and existing project packages)

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | pyproject.toml (existing) |
| Quick run command | `python -m pytest tests/test_ir_cache.py tests/test_batch_executor.py -x` |
| Full suite command | `python -m pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PERF-01 | IRCache returns cached entry on mtime match | unit | `python -m pytest tests/test_ir_cache.py::TestIRCache::test_hit_on_same_mtime -x` | Wave 0 |
| PERF-01 | IRCache returns None on mtime mismatch | unit | `python -m pytest tests/test_ir_cache.py::TestIRCache::test_miss_on_mtime_change -x` | Wave 0 |
| PERF-01 | IRCache evicts LRU entries at max_size | unit | `python -m pytest tests/test_ir_cache.py::TestIRCache::test_lru_eviction -x` | Wave 0 |
| PERF-01 | IRCache invalidation removes all entries for path | unit | `python -m pytest tests/test_ir_cache.py::TestIRCache::test_invalidate -x` | Wave 0 |
| PERF-01 | Executor uses cache on sequential execute() calls | integration | `python -m pytest tests/test_ir_cache.py::TestExecutorCache::test_cache_hit_on_sequential_execute -x` | Wave 0 |
| PERF-02 | execute_batch parses file once for all ops | integration | `python -m pytest tests/test_batch_executor.py::TestBatchExecutor::test_single_parse_for_batch -x` | Wave 0 |
| PERF-02 | execute_batch writes file once after all mutations | integration | `python -m pytest tests/test_batch_executor.py::TestBatchExecutor::test_single_write_for_batch -x` | Wave 0 |
| PERF-03 | execute_batch rejects entire batch on validation failure | integration | `python -m pytest tests/test_batch_executor.py::TestBatchExecutor::test_reject_on_validation_failure -x` | Wave 0 |
| PERF-03 | execute_batch reports all validation errors | integration | `python -m pytest tests/test_batch_executor.py::TestBatchExecutor::test_reports_all_validation_errors -x` | Wave 0 |
| PERF-04 | 100 property modifications in <10s | benchmark | `python -m pytest tests/test_batch_executor.py::TestBatchPerformance::test_batch_100_property_mods_under_10s -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_ir_cache.py tests/test_batch_executor.py -x`
- **Per wave merge:** `python -m pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_ir_cache.py` -- covers PERF-01 cache unit tests
- [ ] `tests/test_batch_executor.py` -- covers PERF-02, PERF-03, PERF-04
- [ ] `src/kicad_agent/ops/ir_cache.py` -- IRCache implementation

*(Existing test infrastructure covers all other needs: conftest.py fixtures, schema validation, executor dispatch)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | N/A -- executor is a local library, no auth |
| V3 Session Management | no | N/A |
| V4 Access Control | yes | Path confinement (T-24-01) already enforced in execute() -- batch must also enforce |
| V5 Input Validation | yes | Pydantic schema validation on all Operation inputs; batch pre-validation (PERF-03) |
| V6 Cryptography | no | N/A |

### Known Threat Patterns for Executor Performance

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cache poisoning (mtime spoofing) | Tampering | kicad-agent is sole writer; mtime spoofing requires filesystem access which means game over anyway |
| Batch injection (malicious ops in batch) | Tampering | Pydantic schema validation rejects invalid ops before mutation |
| Cache poisoning via symlink | Tampering | Transaction already checks for symlinks (H-02); cache resolves paths before lookup |
| Path traversal in batch ops | Tampering | T-24-01 path confinement check on every op in batch, not just first |

## Sources

### Primary (HIGH confidence)
- Codebase analysis: `src/kicad_agent/ops/executor.py` (1090 lines) -- full executor architecture, dispatch, Transaction wrapping
- Codebase analysis: `src/kicad_agent/ir/base.py` -- IR registry enforcement, one-IR-per-ParseResult invariant
- Codebase analysis: `src/kicad_agent/ir/transaction.py` -- Transaction snapshot, rollback, lock mechanism
- Codebase analysis: `src/kicad_agent/parser/schematic_parser.py` -- parse_schematic() implementation
- Codebase analysis: `src/kicad_agent/parser/pcb_parser.py` -- parse_pcb() + _fix_pad_net_syntax
- Codebase analysis: `src/kicad_agent/ops/modify_property.py` -- typical handler pattern (modify_property as benchmark target)
- Codebase analysis: `src/kicad_agent/parser/types.py` -- ParseResult frozen dataclass definition
- Codebase analysis: `.planning/REQUIREMENTS.md` -- PERF-01 through PERF-04 definitions
- Codebase analysis: `.planning/ROADMAP.md` -- Phase 32 scope and success criteria

### Secondary (MEDIUM confidence)
- Python 3.11 stdlib: `collections.OrderedDict`, `os.stat`, `threading.Lock`, `functools.lru_cache` -- verified via `help()` output

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all stdlib, no external dependencies
- Architecture: HIGH - executor codebase thoroughly analyzed, patterns well-established
- Pitfalls: HIGH - one-IR-per-ParseResult registry is a verified constraint in base.py
- Performance target: MEDIUM - 10x improvement is theoretically sound but benchmark will confirm

**Research date:** 2026-05-30
**Valid until:** 2026-06-30 (stable -- stdlib APIs, no fast-moving dependencies)
