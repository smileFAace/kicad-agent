# Council Plan Review -- v2.2 complete-ops (Phases 25-29)

**Review Date:** 2026-05-29
**Reviewer:** Council of Ricks (Evil Morty presiding)
**Plans Reviewed:** 10 plans across 5 phases
**Context Documents:** REQUIREMENTS.md, ROADMAP.md, research/SUMMARY.md, research/PITFALLS.md

---

## Executive Summary

The plans are well-structured, specific, and actionable. They follow the established codebase patterns correctly, address the 7 critical pitfalls with concrete prevention strategies, and maintain requirements traceability throughout. The interface-first approach (schema + registration in wave 1, handler + tests in wave 2) is consistent and sound.

However, the Council found **11 findings** across 5 severity levels. Two findings are CRITICAL and must be fixed before execution. Three are HIGH and should be addressed. Six are MEDIUM and LOW quality improvements.

**Verdict: NEEDS REVISION** -- 2 critical findings must be resolved before execution begins.

---

## Per-Phase Findings

### Phase 25: Remove Operations (Plans 25-01, 25-02)

**Overall Assessment:** SOLID. Clean interface-first split, correct use of list-filter pattern, proper adjacency check for wires.

#### [CRITICAL] F-25-01: Plan 25-02 remove_wire adjacency check is too conservative -- cannot remove ANY wire in a connected design

**Location:** Plan 25-02, Task 1, step 4
**Severity:** CRITICAL (SLC violation -- functional gap)

**Problem:**
The plan specifies that `remove_wire` raises `RemoveWireError` whenever ANY adjacent wires share endpoints. In a real schematic, almost every wire is part of a multi-segment path. A simple L-shaped connection (two wires meeting at a corner) makes both wires "adjacent" to each other. The plan's approach would make it impossible to remove any wire in a connected design without first removing all wires at the junction.

The pitfall text (Pitfall 4) says "check for shared endpoints before removal; refuse or cascade-remove." The plan chose "refuse" but this is the wrong default for production use. A T-junction with 3 wires: removing the stem should be allowed -- the two cross wires still connect at the junction point. Only if removing a wire leaves an orphaned endpoint (a wire going nowhere, connected to nothing) should the operation refuse.

**Current plan text:**
```
4. If adjacent_wires is non-empty: raise RemoveWireError(...)
```

**Required fix:**
Refine the adjacency check to only refuse when removal would leave a **dangling endpoint** (an endpoint that has no pin, no junction, and no remaining wire at that position). The correct algorithm:
1. Get the wire to remove and its two endpoints (start, end).
2. For each endpoint, check if any OTHER wire, pin, junction, or label exists at that position after removal.
3. If both endpoints still have connections, allow removal.
4. If either endpoint would be orphaned (dangling), refuse with a message identifying which endpoint and what still connects there.

This matches Pitfall 4's intent precisely: "removing a wire segment that other wires connect to leaves dangling endpoints" -- the key word is "leaves," not "shares."

---

#### [MEDIUM] F-25-02: Plan 25-01 get_adjacent_wires uses coordinate matching without tolerance

**Location:** Plan 25-01, Task 2, `get_adjacent_wires` method
**Severity:** MEDIUM

**Problem:**
The `get_adjacent_wires` method compares wire endpoints using exact coordinate equality: `endpoints & item_endpoints`. KiCad schematics use 4-decimal precision but floating-point comparison without tolerance may miss connections in files that have been round-tripped through different tools. The plan's `get_wire_endpoints` method already returns float values, and exact `==` on floats is fragile.

**Recommendation:**
Add a tolerance parameter (default 0.0001 mm, matching schematic precision) and compare using `abs(a - b) < tolerance`. This is not blocking because KiCad's own coordinates are deterministic at 4 decimal places, but it's a robustness improvement worth adding.

---

#### [LOW] F-25-03: Plan 25-02 does not test hierarchical label removal

**Location:** Plan 25-02, Task 2
**Severity:** LOW

**Problem:**
The test plan covers local and global labels but does not explicitly test hierarchical label removal. RemoveLabelOp supports `label_type="hierarchical"`, and the handler dispatches to `schematic.hierarchicalLabels`. A test should verify this path works since it's a different list from local/global labels.

**Recommendation:**
Add one test: `test_removes_hierarchical_label_by_uuid` that creates or finds a hierarchical label in a fixture and removes it.

---

### Phase 26: Connectivity Query (Plan 26-01)

**Overall Assessment:** EXCELLENT. Read-only path is architecturally clean. The `_QUERY_HANDLERS` registry is well-separated from mutation handlers. File mtime verification test is smart.

#### [MEDIUM] F-26-01: Plan 26-01 source/target fields are list[str] but PadRef is tuple[str, str]

**Location:** Plan 26-01, Task 1, Step 2
**Severity:** MEDIUM

**Problem:**
The schema defines `source: Optional[list[str]]` and `target: Optional[list[str]]`, but the handler converts them to `PadRef` tuples. The schema should enforce that these lists have exactly 2 elements. A `list[str]` with 0, 1, or 3+ elements would pass Pydantic validation but fail at runtime when constructing the PadRef tuple.

**Recommendation:**
Add validation: `source: Optional[list[str]] = Field(default=None, min_length=2, max_length=2)` or use a custom type that validates the 2-element constraint. The `@model_validator` already checks presence for certain query_types but not list length.

---

#### [LOW] F-26-02: Plan 26-01 does not test error handling for unparseable PCB files

**Location:** Plan 26-01, Task 1, Step 5
**Severity:** LOW

**Problem:**
The tests cover happy-path queries and schema validation, but do not test what happens when the target file is corrupt or unparseable. The `_execute_query` method calls `parse_pcb(file_path)` which could raise an exception for corrupt files.

**Recommendation:**
Add one test: `test_query_on_invalid_pcb_raises` that creates a malformed .kicad_pcb file and verifies the error propagates cleanly.

---

### Phase 27: Footprint Creation (Plans 27-01, 27-02)

**Overall Assessment:** STRONG. The UUID-preserving raw S-expression approach correctly addresses Pitfall 8. The FootprintPadSpec layer validation via Literal type is comprehensive.

#### [CRITICAL] F-27-01: Plan 27-02 S-expression construction has a syntax error in pad layer output

**Location:** Plan 27-02, Task 1, Step 3, pad_line construction
**Severity:** CRITICAL (will produce invalid .kicad_mod files)

**Problem:**
The implementation outline contains a variable name mismatch:
```python
layer_strs = " ".join(f'"{l}"' for l in pad_spec.layers)
pad_line += f' (layers {layer_str})'  # BUG: layer_str should be layer_strs
```

The variable `layer_strs` is defined but `layer_str` (without the 's') is used in the f-string. This will raise a `NameError` at runtime, making the create_footprint operation completely non-functional.

Additionally, the S-expression structure for pads is incorrect. The plan shows:
```
(pad "1" thru_hole rect (at X Y) (size SX SY) (drill D) (layers "F.Cu" "B.Cu")
  (uuid "xxx"))
```
But the code builds the pad line as a single string and then adds the UUID on a separate line. The closing `)` for the pad element needs to be AFTER the uuid, but the pad_line string does not have a closing paren -- the uuid line and closing paren are added separately. The plan's "IMPORTANT" note at Step 4 explains the correct structure, but the code at Step 3 does not implement it correctly.

**Required fix:**
1. Fix the variable name: `layer_strs` -> use `layer_strs` consistently.
2. Restructure pad S-expression construction so the `(uuid "...")` is a child of `(pad ...)`:
```python
pad_line = (f'  (pad "{_escape_sexpr_value(pad_spec.number)}" '
            f'{pad_spec.pad_type} {pad_spec.shape} '
            f'(at {pos_x} {pos_y}) '
            f'(size {pad_spec.size_x} {pad_spec.size_y})')
# drill...
pad_line += f' (layers {layer_strs})'
lines.append(pad_line)
lines.append(f'    (uuid "{pad_uuid}"))')
```
The final `)` on the uuid line closes the `(pad ...)` element. This matches the KiCad format shown in the plan's Step 4.

---

#### [HIGH] F-27-02: Plan 27-02 does not import uuid module

**Location:** Plan 27-02, Task 1, Step 3
**Severity:** HIGH (runtime NameError)

**Problem:**
The implementation uses `str(uuid.uuid4())` but the import for `uuid` is not specified. The plan says "add the create_footprint function after the existing create_symbol function" but does not mention adding `import uuid` at the top of the file. The existing create_file.py may or may not import uuid already.

**Recommendation:**
Verify whether `uuid` is already imported in create_file.py. If not, add `import uuid` to the imports. This is a minor fix but critical for the handler to work.

---

#### [HIGH] F-27-03: Plan 27-02 uses _escape_sexpr_value but it may not exist in create_file.py

**Location:** Plan 27-02, Task 1, Step 6
**Severity:** HIGH

**Problem:**
The plan says "Add the `_escape_sexpr_value` helper if it does not already exist in create_file.py." Codebase analysis shows `_escape_sexpr_value` exists in `pcb_ir.py` (line 675) but NOT in `create_file.py`. The plan's Step 6 shows defining a local `_escape_sexpr_value` function, which is correct, but it should import from the canonical location rather than defining a duplicate.

**Recommendation:**
Import `_escape_sexpr_value` from `kicad_agent.ir.pcb_ir` rather than defining a local copy. Duplicate implementations risk diverging over time (Pitfall 15 -- schema-prompt mismatch pattern applies here to code duplication).

---

#### [MEDIUM] F-27-04: Plan 27-02 courtyard uses pad positions but does not include pad size

**Location:** Plan 27-02, Task 1, Step 3, courtyard generation
**Severity:** MEDIUM

**Problem:**
The courtyard bounding box is calculated from pad center positions only:
```python
pad_xs = [p.position.x for p in op.pads]
min_x = min(pad_xs) - op.courtyard_margin
```
A pad at position (5, 0) with size (2, 2) extends from x=4 to x=6. The courtyard should account for half the pad size on each side:
```python
min_x = min(p.position.x - p.size_x/2 for p in op.pads) - op.courtyard_margin
max_x = max(p.position.x + p.size_x/2 for p in op.pads) + op.courtyard_margin
```

Using center positions alone produces a courtyard that clips the pads when pads are large relative to the margin. This violates IPC-7351 courtyard requirements and will cause DRC courtyard violations in KiCad.

**Recommendation:**
Account for pad half-sizes in the bounding box calculation. The margin should be added on top of the pad outline, not on top of the pad centers.

---

### Phase 28: Hierarchical Sheet Operations (Plans 28-01, 28-02, 28-03)

**Overall Assessment:** GOOD with one important API mismatch. The three-plan split is well-structured: schema first, then add_sheet + navigate, then add_sheet_pin. PITFALL 1 (exact-match) and PITFALL 11 (boundary positioning) are properly addressed.

#### [HIGH] F-28-01: Plan 28-02 references non-existent SheetInstance class -- should be HierarchicalSheetInstance

**Location:** Plan 28-02, Task 1, Step 4
**Severity:** HIGH (will cause ImportError at runtime)

**Problem:**
The plan imports `SheetInstance` from `kiutils.schematic`:
```python
from kiutils.schematic import SheetInstance
sheet_instance = SheetInstance(path=f"/{root_uuid}/{sheet_uuid}", reference="1")
```

Live verification shows that kiutils 1.4.8 does NOT have a `SheetInstance` class. The correct class is `HierarchicalSheetInstance` with signature `(self, instancePath: str = '/', page: str = '1')`. The plan uses the wrong class name and the wrong field names (`path`/`reference` vs `instancePath`/`page`).

Additionally, the `HierarchicalSheet.instances` field is typed as `List[HierarchicalSheetProjectInstance]`, not `List[HierarchicalSheetInstance]`. The plan may be confusing sheet-level instances with project-level instances. The `schematic.sheetInstances` is a different field from `sheet.instances`.

**Required fix:**
1. Verify the exact kiutils type for `schematic.sheetInstances` by inspecting the Schematic class fields.
2. Use the correct class name and constructor arguments.
3. The plan should include a verification step: `python3 -c "from kiutils.schematic import Schematic; s = Schematic.create_new(); print(type(s.sheetInstances)); print(type(s.sheetInstances[0]) if s.sheetInstances else 'empty')"`.
4. If `schematic.sheetInstances` expects `HierarchicalSheetProjectInstance` objects, construct those with the correct UUID path format.

This is a codebase accuracy issue, not a design issue. The intent is correct (PITFALL 3: update sheetInstances alongside sheets) but the implementation details are wrong.

---

#### [MEDIUM] F-28-02: Plan 28-02 navigate_hierarchy uses parse_schematic without import specification

**Location:** Plan 28-02, Task 2, Step 3
**Severity:** MEDIUM

**Problem:**
The navigate_hierarchy implementation calls `parse_schematic(sub_path)` but does not specify where this import comes from. The plan says "Import `parse_schematic` at the top of the file (lazy import inside the function is also fine)" but the file is `src/kicad_agent/ops/sheet_ops.py`, not a parser module. The correct import path is `from kicad_agent.parser import parse_schematic`.

Similarly, `SchematicIR` is used without specifying the import: `from kicad_agent.ir.schematic_ir import SchematicIR`.

**Recommendation:**
Specify all imports explicitly in the plan. Every file reference should include the full import path.

---

#### [LOW] F-28-03: Plan 28-01 NavigateSheetsOp has max_depth=-1 for unlimited but should cap at reasonable depth

**Location:** Plan 28-01, Task 1
**Severity:** LOW

**Problem:**
`max_depth: int = Field(default=-1, ge=-1, le=50)` allows up to 50 levels. Pitfall 17 suggests 20 levels max. 50 is excessive for real projects and could cause performance issues or stack overflow in pathological cases.

**Recommendation:**
Lower `le=50` to `le=20` to match the `_MAX_WALK_LEVELS` pattern referenced in PITFALLS.md. This is a minor safeguard.

---

### Phase 29: Cross-File Atomic Operations (Plans 29-01, 29-02)

**Overall Assessment:** ARCHITECTURALLY SOUND. The `_CROSSFILE_HANDLERS` registry and `_execute_cross_file` method are well-designed. Path confinement per-file is correctly enforced. The partial failure test with monkeypatch is clever.

#### [MEDIUM] F-29-01: Plan 29-01 SyncSchematicPcbOp has no handler implementation

**Location:** Plan 29-01, Task 3; Plan 29-02, Task 1
**Severity:** MEDIUM

**Problem:**
The schema defines `SyncSchematicPcbOp` with `op_type="sync_schematic_pcb"`, and it's added to `_CROSS_FILE_OP_TYPES`, but no handler is registered for it. The plan's handler registration only includes `propagate_symbol_change`. The test in Plan 29-02 acknowledges this: "Handler implementation deferred."

This means `sync_schematic_pcb` will dispatch to `_execute_cross_file`, parse both files, build the IR map, open AtomicOperation -- and then hit `handler = _CROSSFILE_HANDLERS.get(root.op_type)` which returns `None`, raising `ValueError`. The entire cross-file infrastructure (parsing, path validation, AtomicOperation) runs for nothing before failing.

This is not a functional bug (it will error clearly), but it's an SLC concern: a schema that advertises an operation that cannot be executed.

**Recommendation:**
Either:
(a) Remove `SyncSchematicPcbOp` from the schema and `_CROSS_FILE_OP_TYPES` entirely (YAGNI -- ship what works), or
(b) Register a minimal handler that returns `{"success": True, "synced": False, "message": "Net sync not yet implemented"}` so the operation doesn't crash, or
(c) Add a note in REQUIREMENTS.md that XFILE-06 (sync_schematic_pcb) is deferred to a future milestone and only XFILE-05/XFILE-07 are in scope for v2.2.

Option (a) is cleanest. The schema should not promise what the handler cannot deliver.

---

#### [LOW] F-29-02: Plan 29-02 test file location differs from existing crossfile tests

**Location:** Plan 29-02, Task 1
**Severity:** LOW

**Problem:**
The plan specifies `tests/test_ops/test_crossfile_dispatch.py` but existing crossfile tests are in `tests/test_crossfile/` (e.g., `test_propagation.py`, `test_atomic.py`). Creating a new directory `tests/test_ops/` fragments the test structure.

**Recommendation:**
Place the test at `tests/test_crossfile/test_dispatch.py` to stay consistent with existing test organization. Or create `tests/test_ops/` only if the plan also moves existing executor dispatch tests there.

---

## Cross-Phase Findings

### [HIGH] F-CROSS-01: D-03 violation -- cross-file operations target multiple files, contradicting schema.py docstring

**Location:** schema.py line D-03 comment vs Plan 29-01
**Severity:** HIGH (architectural consistency)

**Problem:**
schema.py line 7 states: `D-03: Single file per operation via target_file field.` But cross-file operations inherently target multiple files. The `PropagateSymbolChangeOp` uses `target_files: list[TargetFile]` (plural) instead of `target_file: TargetFile` (singular). This breaks the D-03 design decision.

This is actually correct for cross-file operations -- they NEED to target multiple files. But the plan should explicitly document that D-03 is intentionally relaxed for cross-file operations and explain why.

**Recommendation:**
Add a design decision note to the Plan 29-01 context section:
> D-03 is relaxed for cross-file operations. Single-file operations use `target_file: TargetFile` for atomicity within one file. Cross-file operations use `target_files: list[TargetFile]` because they coordinate multiple files through AtomicOperation. The executor routes these through a separate `_execute_cross_file` path that enforces per-file path confinement.

---

### [MEDIUM] F-CROSS-02: Plan 25-01 and 28-01 both use `_validate_sexpr_safe_string` but 28-01 references it as imported from schema.py

**Location:** Plans 25-01 Task 1, 28-01 Task 1
**Severity:** MEDIUM

**Problem:**
Plan 25-01 says to add `_validate_sexpr_safe_string` validator on the uuid field, and Plan 28-01 says to apply it to `pin_name` and `sheet_name`. Both reference importing it from `kicad_agent.ops.schema`. This is correct based on the codebase (`_validate_sexpr_safe_string` is defined in schema.py line 59). However, the `_schema_remove.py` plan does not show the actual import statement for this validator. It should explicitly show:
```python
from kicad_agent.ops.schema import _validate_sexpr_safe_string
```

This is a plan clarity issue, not a code bug. But during autonomous execution, the agent might miss the import.

---

## Requirements Coverage Matrix

| Requirement | Phase | Plan | Covered | Notes |
|-------------|-------|------|---------|-------|
| REMOVE-01 | 25 | 25-02 | YES | Wire removal with adjacency check (needs fix per F-25-01) |
| REMOVE-02 | 25 | 25-02 | YES | Label removal with net membership validation |
| REMOVE-03 | 25 | 25-02 | YES | Junction removal |
| REMOVE-04 | 25 | 25-02 | YES | No-connect removal |
| REMOVE-05 | 25 | 25-01, 25-02 | YES | List-filter pattern, Transaction recording |
| QUERY-01 | 26 | 26-01 | YES | Read-only handler wrapping NetGraph |
| QUERY-02 | 26 | 26-01 | YES | 5 query types |
| QUERY-03 | 26 | 26-01 | YES | Read-only via _QUERY_HANDLERS |
| QUERY-04 | 26 | 26-01 | YES | JSON results for LLM chains |
| FOOT-01 | 27 | 27-01, 27-02 | YES | PadSpec + handler |
| FOOT-02 | 27 | 27-02 | YES | Raw S-expression serialization |
| FOOT-03 | 27 | 27-02 | YES | Courtyard generation (needs fix per F-27-04) |
| FOOT-04 | 27 | 27-01 | YES | Literal layer validation |
| SHEET-01 | 28 | 28-02 | YES | add_sheet with fileName resolution |
| SHEET-02 | 28 | 28-03 | YES | add_sheet_pin with exact-match |
| SHEET-03 | 28 | 28-02 | YES | navigate_hierarchy |
| SHEET-04 | 28 | 28-02 | YES | sheetInstances update (needs fix per F-28-01) |
| SHEET-05 | 28 | 28-02 | YES | Sub-sheet file creation |
| SHEET-06 | 28 | 28-02, 28-03 | YES | Nested hierarchy support |
| XFILE-05 | 29 | 29-01, 29-02 | YES | propagate_symbol_change via AtomicOperation |
| XFILE-06 | 29 | 29-01 | PARTIAL | Schema exists, no handler (see F-29-01) |
| XFILE-07 | 29 | 29-02 | YES | Partial failure guarantee tested |

**Coverage:** 21 of 22 requirements covered. XFILE-06 has schema only, no handler implementation.

---

## Pitfall Coverage Assessment

| Critical Pitfall | Addressed | Plan Reference | Assessment |
|-----------------|-----------|----------------|------------|
| Pitfall 1: Exact-match pin names | YES | 28-03 | Correct: `==` comparison, case-sensitive |
| Pitfall 2: Relative path resolution | YES | 28-02 | Correct: `file_path.resolve().parent / child_file` |
| Pitfall 3: Sheet instances update | PARTIAL | 28-02 | Intent correct, wrong kiutils class name (F-28-01) |
| Pitfall 4: Wire adjacency cleanup | PARTIAL | 25-02 | Too conservative, needs refinement (F-25-01) |
| Pitfall 5: Pad/symbol pin cross-validation | NO | -- | Not addressed in any plan |
| Pitfall 6: Read-only query semantics | YES | 26-01 | Excellent: separate registry, mtime test |
| Pitfall 7: Cross-file partial failure | YES | 29-02 | Monkeypatch test for rollback verification |
| Pitfall 8: kiutils UUID drop | YES | 27-02 | Raw S-expression construction, UUID count test |

**Notable gap:** Pitfall 5 (pad/symbol pin cross-validation) is listed in PITFALLS.md as a moderate pitfall but is not explicitly addressed in any plan. The `create_footprint` handler does not cross-validate pad numbers against a target symbol's pin numbers. This is acceptable for v2.2 if documented as a known limitation, but the plans should note it.

---

## Threat Model Assessment

All plans include STRIDE threat models. Assessment:

- **Path confinement:** Consistently enforced across all phases. Cross-file operations extend confinement to all target files (T-29-01).
- **S-expression injection:** `_escape_sexpr_value` used consistently in footprint creation. `_validate_sexpr_safe_string` applied to pin names and sheet names.
- **Input validation:** All schemas enforce min_length/max_length. Literal types prevent arbitrary string injection for layers, pad types, and connection types.
- **No new attack surface:** All five features follow existing patterns. The only new attack surface is the cross-file dispatch path, which is properly confined.

No security findings require plan revision.

---

## Verdict: NEEDS REVISION

### Findings That Must Be Fixed Before Execution

| # | Finding | Severity | Phase | Description |
|---|---------|----------|-------|-------------|
| F-25-01 | Wire adjacency too conservative | CRITICAL | 25-02 | Cannot remove any wire in a connected design. Must refine to dangling-endpoint detection. |
| F-27-01 | S-expression variable name bug | CRITICAL | 27-02 | `layer_str` vs `layer_strs` typo produces NameError. Also pad paren structure needs verification. |

### Findings That Should Be Fixed Before Execution

| # | Finding | Severity | Phase | Description |
|---|---------|----------|-------|-------------|
| F-28-01 | Wrong kiutils class name | HIGH | 28-02 | `SheetInstance` does not exist; must use `HierarchicalSheetInstance` with correct field names. |
| F-27-02 | Missing uuid import | HIGH | 27-02 | `uuid.uuid4()` used without verifying import exists in create_file.py. |
| F-27-03 | Duplicate _escape_sexpr_value | HIGH | 27-02 | Should import from pcb_ir.py, not define locally. |
| F-CROSS-01 | D-03 documentation gap | HIGH | 29-01 | Cross-file operations intentionally violate D-03; must document the exception. |

### Findings That Are Improvements (Can Fix During Execution)

| # | Finding | Severity | Phase | Description |
|---|---------|----------|-------|-------------|
| F-25-02 | Float comparison without tolerance | MEDIUM | 25-01 | Add tolerance to get_adjacent_wires coordinate matching. |
| F-26-01 | source/target list length unvalidated | MEDIUM | 26-01 | Add min_length=2, max_length=2 to source/target fields. |
| F-27-04 | Courtyard ignores pad size | MEDIUM | 27-02 | Include half-pad-size in bounding box calculation. |
| F-29-01 | SyncSchematicPcbOp has no handler | MEDIUM | 29-01 | Remove schema or register stub handler. |
| F-CROSS-02 | Missing import statements | MEDIUM | 25-01, 28-01 | Explicitly show _validate_sexpr_safe_string imports. |
| F-28-02 | Missing import paths | MEDIUM | 28-02 | Specify full import paths for parse_schematic, SchematicIR. |
| F-25-03 | No hierarchical label removal test | LOW | 25-02 | Add test for label_type="hierarchical". |
| F-26-02 | No corrupt PCB error test | LOW | 26-01 | Add test for unparseable target file. |
| F-28-03 | max_depth too high | LOW | 28-01 | Lower from 50 to 20. |
| F-29-02 | Test location inconsistency | LOW | 29-02 | Place test in existing tests/test_crossfile/. |

---

## Council Consensus

| Council Member | Verdict | Notes |
|---------------|---------|-------|
| Rick Sanchez (Code Quality) | NEEDS REVISION | F-27-01 is a typo that would ship a broken operation. F-28-01 is wrong API. |
| Rick C-137 (Security) | APPROVED | No security concerns. Path confinement, S-expression escaping, input validation all solid. |
| Rick Prime (Design/UX) | NEEDS REVISION | F-25-01 is an SLC issue: users cannot remove wires in real designs. |
| Slick Rick (SLC Validator) | NEEDS REVISION | F-27-01 produces a NameError (broken operation). F-29-01 advertises an operation that cannot execute. |
| Rickfucius (Historian) | APPROVED with notes | Pitfall 5 not addressed but acceptable if documented. Plans follow established patterns. |
| KiCad Rick (EDA Specialist) | NEEDS REVISION | F-27-04 courtyard ignores pad size (DRC violation). F-28-01 wrong kiutils class. |
| **Evil Morty (Final)** | **NEEDS REVISION** | **2 critical, 4 high. Fix CRITICALs and HIGHs, then proceed.** |

---

**Review Completed:** 2026-05-29
**Review Duration:** Full Council session
**Next Step:** Revise plans 25-02, 27-02, 28-02, and 29-01 per findings above, then re-submit for Council approval.
