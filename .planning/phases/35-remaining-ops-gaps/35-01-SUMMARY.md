---
phase: 35-remaining-ops-gaps
plan: 01
subsystem: ops
tags: [pydantic, schema, design-rules, project-file, lib-table, executor]

# Dependency graph
requires:
  - phase: 34-llm-provider-abstraction
    provides: "Existing operation schema pattern and executor dispatch infrastructure"
provides:
  - "8 new operation schemas for project file CRUD (list/modify/remove lib entries, net classes, design rules, modify_project_settings)"
  - "DesignRulesFile.modify_net_class() and modify_rule() using dataclasses.replace for frozen dataclasses"
  - "write_project_settings() with atomic write and deep merge for .kicad_pro"
  - "8 handler registrations in executor.py with lazy-import pattern"
affects: [mcp-server, documentation, slc-compliance]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Optional fields on modify schemas for partial updates", "dataclasses.replace for frozen dataclass mutation", "atomic write via tempfile+os.replace for .kicad_pro"]

key-files:
  created: []
  modified:
    - src/kicad_agent/ops/_schema_library.py
    - src/kicad_agent/ops/_schema_pcb.py
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ops/executor.py
    - src/kicad_agent/project/design_rules.py
    - src/kicad_agent/project/project_file.py
    - src/kicad_agent/mcp/edit_server.py
    - tests/test_project_file.py
    - tests/test_slc_compliance.py
    - tests/test_mcp/test_edit_server.py
    - README.md
    - skills/SKILL.md

key-decisions:
  - "ModifyNetClassOp uses Optional[float] fields (None=keep existing) rather than required fields for partial updates"
  - "write_project_settings operates on raw JSON dict, not ProjectFile dataclass, to preserve unknown keys"
  - "List handlers are read-only (no serialize call), returning structured data with entries+count"
  - "KeyError propagates from modify/remove handlers (consistent with existing remove_net_class/remove_rule pattern)"

patterns-established:
  - "ListOp pattern: target_file-only schema returning {items: [...], count: N}"
  - "ModifyOp pattern: Optional fields for partial updates, filtering non-None in handler"
  - "Atomic write pattern for .kicad_pro: tempfile.mkstemp + os.replace"

requirements-completed: [GEN-01, GEN-06]

# Metrics
duration: 19min
completed: 2026-05-31
---

# Phase 35 Plan 01: Project CRUD Operations Summary

**8 new operations for full CRUD on lib tables, net classes, design rules, and .kicad_pro settings with TDD-verified schemas, handlers, and atomic project file writes**

## Performance

- **Duration:** 19 min
- **Started:** 2026-05-31T15:44:53Z
- **Completed:** 2026-05-31T16:04:15Z
- **Tasks:** 1
- **Files modified:** 12

## Accomplishments
- 8 new operation schemas (ListLibEntriesOp, ModifyNetClassOp, RemoveNetClassOp, ListNetClassesOp, ModifyDesignRuleOp, RemoveDesignRuleOp, ListDesignRulesOp, ModifyProjectSettingsOp) registered in schema.py union
- DesignRulesFile.modify_net_class() and modify_rule() methods using dataclasses.replace for frozen dataclasses
- write_project_settings() with atomic write (tempfile+os.replace) and deep merge for .kicad_pro
- 8 handler registrations in executor.py following lazy-import pattern
- 38 tests in test_project_file.py all passing (21 new + 17 existing)
- Updated operation counts across README.md, SKILL.md, SLC compliance tests, and MCP tests (63 -> 71)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add 8 new schemas, DesignRulesFile modify methods, write_project_settings, and handler registrations** - `e0510e4` (feat) [TDD: test + feat combined]

## Files Created/Modified
- `src/kicad_agent/ops/_schema_library.py` - Added ListLibEntriesOp schema
- `src/kicad_agent/ops/_schema_pcb.py` - Added 7 new schemas (ModifyNetClassOp, RemoveNetClassOp, ListNetClassesOp, ModifyDesignRuleOp, RemoveDesignRuleOp, ListDesignRulesOp, ModifyProjectSettingsOp)
- `src/kicad_agent/ops/schema.py` - Updated imports, union (71 types), and __all__
- `src/kicad_agent/ops/executor.py` - Added 8 @register_project handlers with lazy imports
- `src/kicad_agent/project/design_rules.py` - Added modify_net_class() and modify_rule() methods
- `src/kicad_agent/project/project_file.py` - Added write_project_settings() with atomic write
- `src/kicad_agent/mcp/edit_server.py` - Updated docstring count (57->65 ops)
- `tests/test_project_file.py` - Added 21 new tests across 10 test classes
- `tests/test_slc_compliance.py` - Updated operation count assertion (63->71)
- `tests/test_mcp/test_edit_server.py` - Updated tool count assertions (57->65 ops, 63->71 total)
- `README.md` - Updated operation count (63->71)
- `skills/SKILL.md` - Updated operation count (63->71)

## Decisions Made
- ModifyNetClassOp uses Optional[float] fields (None=keep existing) rather than required fields, enabling partial updates without read-modify-write
- write_project_settings operates on raw JSON dict, not ProjectFile dataclass, to preserve unknown keys per RESEARCH Pitfall 6
- List handlers are read-only (no serialize call), returning {entries: [...], count: N} per Council CR-02
- KeyError propagates from modify/remove handlers unchanged -- consistent with existing remove_net_class/remove_rule pattern in executor

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Tests expected result dict with success=False for KeyError, but executor propagates exceptions**
- **Found during:** Task 1 (GREEN phase -- test_modify_net_class_nonexistent_raises and similar)
- **Issue:** Test assertions checked result["success"] is False and result["error"], but executor._execute_project does not catch exceptions -- KeyError propagates to caller
- **Fix:** Changed tests to use pytest.raises(KeyError) matching existing remove_lib_entry test pattern
- **Files modified:** tests/test_project_file.py
- **Verification:** All 38 tests pass

**2. [Rule 3 - Blocking] SLC compliance tests, MCP tests, README, and SKILL.md had stale operation counts (63 instead of 71)**
- **Found during:** Task 1 (verification -- full test suite run)
- **Issue:** Adding 8 new operations invalidated hardcoded operation counts in tests and documentation
- **Fix:** Updated test assertions (63->71), README.md (63->71), SKILL.md (63->71), edit_server.py docstring (57->65)
- **Files modified:** tests/test_slc_compliance.py, tests/test_mcp/test_edit_server.py, README.md, skills/SKILL.md, src/kicad_agent/mcp/edit_server.py
- **Verification:** All SLC compliance tests pass (25/25), MCP tests pass (46/46)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both auto-fixes necessary for correctness and test suite integrity. No scope creep.

## Issues Encountered
- test_add_component.py::test_full_pipeline_add_component fails when run in the full suite but passes in isolation (pre-existing IR registry state leak between tests). Unrelated to this plan -- excluded from scope.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 71 operations registered and tested
- Remaining ops gaps (plans 02 and 03) can proceed
- Operation count now at 71 across schema.py union
