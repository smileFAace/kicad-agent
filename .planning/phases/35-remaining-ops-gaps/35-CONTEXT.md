---
phase: 35
phase_name: Remaining Ops Gaps
created: 2026-05-31
status: approved
---

# Phase 35 Context — Remaining Ops Gaps

## Goal

Close the five remaining operation gaps for complete CRUD coverage. Requirements: GEN-01, GEN-03, GEN-04, GEN-05, GEN-06.

## Decisions

### GEN-01 + GEN-06: Full CRUD for project files + .kicad_pro write

**Decision:** Implement full list/modify/remove operations for lib tables, net classes, and design rules. Add .kicad_pro read/write support.

**What already exists (DO NOT recreate):**
- `AddLibEntryOp` / `RemoveLibEntryOp` schemas in `_schema_library.py` + registered handlers in executor
- `AddNetClassOp` / `AddDesignRuleOp` / `AssignNetClassOp` schemas in `_schema_pcb.py` + registered handlers
- `DesignRulesFile` class in `project/design_rules.py` with parse/write
- `ProjectFile` class in `project/project_file.py` with read support
- `parse_lib_table` / `serialize_lib_table` in `project/lib_table.py`

**New operations to add:**
1. `list_lib_entries` — query op returning all entries in sym-lib-table / fp-lib-table
2. `list_net_classes` — query op returning all net class definitions from .kicad_dru
3. `list_design_rules` — query op returning all custom DRC rules from .kicad_dru
4. `modify_net_class` — update dimensions for an existing net class
5. `remove_net_class` — delete a net class from .kicad_dru
6. `modify_design_rule` — update constraint values for an existing DRC rule
7. `remove_design_rule` — delete a DRC rule from .kicad_dru
8. `modify_project_settings` — read/modify .kicad_pro settings (add write support to ProjectFile)

**Why:** LLM agents need query capabilities to discover existing state before making changes. Full CRUD prevents agents from needing to delete-and-recreate when a modify suffices.

**How to apply:**
- Schemas go in `_schema_library.py` (lib ops) and `_schema_pcb.py` (net class / design rule ops)
- Handlers use existing `DesignRulesFile` and `LibTable` classes
- `modify_project_settings` needs write method added to `ProjectFile`
- Register list ops as `@register_project` handlers
- Register net class / design rule CRUD as `@register_project` handlers (they target .kicad_dru)

### GEN-03: ERC auto-fix meta-operation

**Decision:** Add `erc_auto_fix` meta-operation that chains `parse_erc` → analyze violations → dispatch appropriate repair ops. Individual repair ops already exist and are sufficient.

**What already exists (DO NOT recreate):**
- 11 registered repair ops: repair_schematic, fix_shorted_nets, break_wire_shorts, fix_pin_type_mismatches, place_missing_units, remove_dangling_wires, add_power_flag, rebuild_root_sheet, snap_to_grid, convert_kicad6_to_10, update_symbols_from_library, swap_symbol
- `parse_erc` handler returning structured violations
- `extract_violation_positions` handler for coordinate extraction

**New operation to add:**
1. `erc_auto_fix` — schematic handler that:
   - Runs `parse_erc` to get violations
   - Maps violation types to repair operations:
     - `pin_not_connected` → `place_no_connects`
     - `power_pin_not_driven` → `add_power_flag`
     - `pin_to_pin` → `fix_pin_type_mismatches`
     - `missing_power_pin` → `place_missing_units`
     - wire-level shorts → `break_wire_shorts`
     - off-grid pins → `snap_to_grid`
   - Executes repairs in priority order (shorts first, then type fixes, then cosmetic)
   - Returns summary of fixes applied + remaining violations

**Why:** LLM agents and MCP callers currently need to chain parse_erc + repair ops manually. A single meta-op simplifies the common workflow.

**How to apply:**
- Schema in `_schema_repair.py` with `ErcAutoFixOp`
- Handler in `repair.py` (or new `erc_auto_fix.py` if > 100 lines)
- Register as `@register_schematic("erc_auto_fix")`
- Use existing `parse_erc` + `repair_wire_snapping` + etc. internally

### GEN-04: Hierarchical sheet power span validation

**Decision:** Add hierarchical sheet power net span check to `validate_power_nets`.

**What already exists (DO NOT recreate):**
- `ValidatePowerNetsOp` schema in `_schema_validation.py`
- `validate_power_nets()` function in `validation_gates.py`
- `pre_pcb_gate()` combining ERC + power + annotation checks
- Sheet pin / hierarchical label matching in `validation_gates.py`

**New functionality to add:**
1. Extend `validate_power_nets()` to traverse hierarchical sheets
2. For each sub-sheet, check that power nets visible at the sheet boundary have power symbols inside the sub-sheet
3. Report missing power connections across sheet boundaries

**Why:** Real KiCad projects use hierarchical sheets extensively. Power nets can be declared at the top level but not actually connected inside sub-sheets, causing ERC errors that are hard to diagnose.

**How to apply:**
- Extend existing `validate_power_nets()` function (no new op_type)
- Add `check_hierarchical` flag to `ValidatePowerNetsOp` schema (default True)
- Reuse sheet traversal from `validate_schematic_completeness()`

### GEN-05: Copper zone modify + delete

**Decision:** Add `modify_copper_zone` and `remove_copper_zone` operations.

**What already exists (DO NOT recreate):**
- `AddCopperZoneOp` schema in `_schema_pcb.py`
- `add_copper_zone()` function in `pcb_ops.py` with kiutils Zone creation
- Registered `@register_pcb("add_copper_zone")` handler

**New operations to add:**
1. `modify_copper_zone` — update zone properties (net, layer, clearance, priority)
2. `remove_copper_zone` — delete a zone by UUID or index

**Why:** Full CRUD for copper zones lets agents iterate on zone placement during layout refinement.

**How to apply:**
- Schemas in `_schema_pcb.py` (ModifyCopperZoneOp, RemoveCopperZoneOp)
- Functions in `pcb_ops.py`
- Register as `@register_pcb` handlers
- Identify zones by UUID (preferred) or index

## Implementation Notes

### Plan Structure (suggested)
- **Plan 35-01**: GEN-01 + GEN-06 — List/modify/remove ops for lib tables, net classes, design rules + .kicad_pro write
- **Plan 35-02**: GEN-03 — erc_auto_fix meta-operation
- **Plan 35-03**: GEN-04 + GEN-05 — Hierarchical power validation + copper zone modify/delete

### Reusable Patterns
- Handler registration: `@register_project("op_name")` for project-file ops, `@register_pcb("op_name")` for PCB ops, `@register_schematic("op_name")` for schematic ops
- Schema pattern: Pydantic BaseModel with `op_type: Literal["name"]` discriminator
- Handler pattern: lazy import implementation function, delegate to it, return dict
- Existing parse/serialize classes: `LibTable`, `DesignRulesFile`, `ProjectFile`

### Constraints
- No new dependencies
- All new ops get MCP tool exposure via existing edit_server.py registration pattern
- Tests for each new operation (follow existing test patterns in tests/)
- Lazy imports in handlers (no top-level imports of implementation modules)
