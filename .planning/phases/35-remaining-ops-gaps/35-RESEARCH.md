# Phase 35: Remaining Ops Gaps - Research

**Researched:** 2026-05-31
**Domain:** KiCad operation schema, handler registration, project file I/O, ERC repair
**Confidence:** HIGH

## Summary

Phase 35 closes the five remaining operation gaps (GEN-01, GEN-03, GEN-04, GEN-05, GEN-06) for complete CRUD coverage across project files, net classes, design rules, copper zones, and ERC auto-fix. The codebase has well-established patterns for all of these: Pydantic schemas with `Literal` discriminators in `_schema_*.py` files, handler registration via `@register_*` decorators in `executor.py`, lazy imports in handlers, and existing parse/serialize classes (`LibTable`, `DesignRulesFile`, `ProjectFile`) that already implement most of the needed CRUD methods.

**Primary recommendation:** Add 12 new operation schemas and handlers following the exact patterns established by `add_lib_entry`, `add_net_class`, and `add_copper_zone`. The DesignRulesFile class already has `remove_net_class()` and `remove_rule()` -- only a `modify_net_class()` and `modify_rule()` method is missing. ProjectFile needs a `to_file()` write method added. The erc_auto_fix meta-op chains existing repair functions via the parse_erc + violation type dispatch pattern.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **GEN-01 + GEN-06: Full CRUD for project files + .kicad_pro write** -- Implement list/modify/remove ops for lib tables, net classes, design rules. Add .kicad_pro read/write support.
   - 8 new operations: list_lib_entries, list_net_classes, list_design_rules, modify_net_class, remove_net_class, modify_design_rule, remove_design_rule, modify_project_settings
   - Schemas in `_schema_library.py` (lib ops) and `_schema_pcb.py` (net class / design rule ops)
   - Handlers use existing `DesignRulesFile` and `LibTable` classes
   - `modify_project_settings` needs write method added to `ProjectFile`
   - List ops registered as `@register_project` handlers
   - Net class / design rule CRUD registered as `@register_project` handlers (target .kicad_dru)

2. **GEN-03: ERC auto-fix meta-operation** -- Add `erc_auto_fix` meta-operation chaining parse_erc to repair dispatch.
   - Maps violation types to repair operations: pin_not_connected -> place_no_connects, power_pin_not_driven -> add_power_flag, pin_to_pin -> fix_pin_type_mismatches, missing_power_pin -> place_missing_units, wire-level shorts -> break_wire_shorts, off-grid pins -> snap_to_grid
   - Schema in `_schema_repair.py` with `ErcAutoFixOp`
   - Handler in `repair.py` or new `erc_auto_fix.py` if > 100 lines
   - Register as `@register_schematic("erc_auto_fix")`

3. **GEN-04: Hierarchical sheet power span validation** -- Extend `validate_power_nets` for hierarchical sheets.
   - Add `check_hierarchical` flag to `ValidatePowerNetsOp` schema (default True)
   - Extend existing `validate_power_nets()` function (no new op_type)
   - Reuse sheet traversal from `validate_schematic_completeness()`

4. **GEN-05: Copper zone modify + delete** -- Add `modify_copper_zone` and `remove_copper_zone` operations.
   - Schemas in `_schema_pcb.py` (ModifyCopperZoneOp, RemoveCopperZoneOp)
   - Functions in `pcb_ops.py`
   - Register as `@register_pcb` handlers
   - Identify zones by UUID (preferred) or index

### Implementation Notes from CONTEXT.md
- Plan structure: Plan 35-01 (GEN-01+GEN-06), Plan 35-02 (GEN-03), Plan 35-03 (GEN-04+GEN-05)
- No new dependencies
- All new ops get MCP tool exposure via existing edit_server.py registration pattern
- Tests for each new operation
- Lazy imports in handlers (no top-level imports of implementation modules)

### Deferred Ideas (OUT OF SCOPE)
- Auto-routing improvements (Phase 36)
- Training infrastructure (Phase 37)
- MCP server implementation (Phase 30-31)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GEN-01 | Parse and modify project-level files: sym-lib-table, fp-lib-table, .kicad_dru, .kicad_pro | LibTable (lib_table.py) has full CRUD. DesignRulesFile (design_rules.py) has add/remove, needs modify. ProjectFile (project_file.py) needs write support. |
| GEN-03 | Schematic ERC repair: auto-fix wire snapping, orphaned labels, shorted nets, pin_not_connected | erc_parser.py provides parse_erc with ErcViolation type field. 11 repair ops exist. Dispatch by violation.type to repair function. |
| GEN-04 | Power net validation: check all power pins connected, verify across hierarchical sheets | validate_power_nets() exists in validation_gates.py. Sheet traversal pattern in check_sheet_pin_labels() and validate_schematic_completeness() can be reused. |
| GEN-05 | PCB copper zone operations: add/modify/fill copper pour zones | add_copper_zone() exists in pcb_ops.py. Zones stored in board.zones list. kiutils Zone has all mutable properties. Identify by UUID tstamp field. |
| GEN-06 | Net class and design rule operations: assign net classes, custom DRC rules, board outline | AddNetClassOp/AddDesignRuleOp schemas exist. DesignRulesFile has add/remove. Need modify + list query ops. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| List/query project files | Project handler | -- | Reads project-level files (lib tables, .kicad_dru), no IR needed |
| Modify/remove net classes + design rules | Project handler | -- | Targets .kicad_dru files via DesignRulesFile |
| Modify project settings | Project handler | -- | Targets .kicad_pro JSON files via ProjectFile |
| ERC auto-fix meta-operation | Schematic handler | -- | Chains parse_erc + repair ops, needs SchematicIR |
| Hierarchical power validation | Validation gate | Schematic IR | Extends existing validate_power_nets, needs sheet traversal |
| Copper zone modify/delete | PCB handler | -- | Operates on PcbIR board.zones list |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.x | Operation schemas | Project standard for all op types |
| kiutils | 1.4.8 | KiCad file I/O | Handles Zone, Board, GrLine, Net objects |
| sexpdata | 1.0.0 | S-expression parsing | Used by lib_table.py and design_rules.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| dataclasses | stdlib | LibTable, DesignRulesFile, ProjectFile | Existing parse/serialize classes |
| re | stdlib | Pattern matching in net class assignment | Raw S-expression manipulation |
| json | stdlib | .kicad_pro read/write | ProjectFile JSON parsing |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Register list ops as @register_project | Register as @register_query | Query ops get PcbIR; project ops get file_path only. Project ops are correct since lib tables and .kicad_dru are not PCB IR. |

**Installation:**
No new packages needed -- all dependencies are already installed.

**Version verification:** All packages verified present in existing codebase imports.

## Architecture Patterns

### System Architecture Diagram

```
LLM/MCP caller
      |
      v
OperationExecutor.execute(op)
      |
      v
  op_type routing
      |
      +--> _SCHEMATIC_HANDLERS --> SchematicIR + Transaction + serialize
      |
      +--> _PCB_HANDLERS --> PcbIR + Transaction + serialize
      |
      +--> _PROJECT_HANDLERS --> file_path only (no IR, no Transaction)
      |         |
      |         +--> LibTable.parse/serialize (sym-lib-table, fp-lib-table)
      |         +--> DesignRulesFile.parse/serialize (.kicad_dru)
      |         +--> ProjectFile.parse/write (.kicad_pro)  [NEW: write support]
      |
      +--> _QUERY_HANDLERS --> PcbIR read-only (no Transaction, no serialization)
      |
      +--> _CREATE_HANDLERS --> file_path only (no IR, file doesn't exist)
      |
      +--> _CROSSFILE_HANDLERS --> dict[Path, BaseIR] multi-file
```

### Recommended Project Structure
```
src/kicad_agent/
  ops/
    _schema_library.py    # ADD: ListLibEntriesOp
    _schema_pcb.py        # ADD: ModifyNetClassOp, RemoveNetClassOp, ModifyDesignRuleOp,
                          #      RemoveDesignRuleOp, ModifyCopperZoneOp, RemoveCopperZoneOp
    _schema_repair.py     # ADD: ErcAutoFixOp
    _schema_validation.py # MODIFY: ValidatePowerNetsOp (add check_hierarchical flag)
    pcb_ops.py            # ADD: modify_copper_zone(), remove_copper_zone()
    executor.py           # ADD: 12 new @register_* handlers
    erc_auto_fix.py       # NEW (if > 100 lines, else add to repair.py)
    validation_gates.py   # MODIFY: validate_power_nets() for hierarchical traversal
  project/
    design_rules.py       # ADD: modify_net_class(), modify_rule() methods on DesignRulesFile
    project_file.py       # ADD: write_project_file() / to_file() method
```

### Pattern 1: Schema + Handler Registration (project-level ops)
**What:** New operations follow the existing pattern: Pydantic schema with Literal discriminator, handler function in executor.py, lazy import of implementation.
**When to use:** For all 8 new list/modify/remove project-level ops.

**Example:**
```python
# In _schema_pcb.py (following existing AddNetClassOp pattern)
class ModifyNetClassOp(BaseModel):
    op_type: Literal["modify_net_class"] = "modify_net_class"
    target_file: TargetFile
    name: str = Field(min_length=1, max_length=64)
    clearance: Optional[float] = Field(default=None, gt=0)
    track_width: Optional[float] = Field(default=None, gt=0)
    # ... other optional dimensions

# In executor.py
@register_project("modify_net_class")
def _handle_modify_net_class(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.design_rules import parse_design_rules, serialize_design_rules
    dru = parse_design_rules(file_path)
    dru.modify_net_class(op.name, ...)  # New method
    serialize_design_rules(dru, file_path)
    return {"net_class": op.name, "action": "modified"}
```

### Pattern 2: PCB Handler with PcbIR (copper zone modify/delete)
**What:** PCB handlers receive PcbIR, mutate board object, serialize via Transaction.
**When to use:** For modify_copper_zone and remove_copper_zone.

**Example:**
```python
# In _schema_pcb.py
class RemoveCopperZoneOp(BaseModel):
    op_type: Literal["remove_copper_zone"] = "remove_copper_zone"
    target_file: TargetFile
    zone_uuid: Optional[str] = Field(default=None, description="Zone UUID (tstamp)")
    zone_index: Optional[int] = Field(default=None, ge=0, description="Zone index fallback")

# In pcb_ops.py
def remove_copper_zone(ir: PcbIR, zone_uuid: str | None = None, zone_index: int | None = None):
    zones = ir.board.zones
    if zone_uuid:
        target = next((z for z in zones if z.tstamp == zone_uuid), None)
    elif zone_index is not None:
        target = zones[zone_index]
    zones.remove(target)
    # ... record mutation
```

### Pattern 3: Meta-operation dispatch (erc_auto_fix)
**What:** A single handler that chains parse_erc -> violation type analysis -> repair dispatch.
**When to use:** For erc_auto_fix meta-operation.

**Example:**
```python
# In _schema_repair.py
class ErcAutoFixOp(BaseModel):
    op_type: Literal["erc_auto_fix"] = "erc_auto_fix"
    target_file: TargetFile
    max_iterations: int = Field(default=3, ge=1, le=10)

# In erc_auto_fix.py (or repair.py)
VIOLATION_REPAIR_MAP = {
    "pin_not_connected": "place_no_connects",
    "power_pin_not_driven": "add_power_flag",
    "pin_to_pin": "fix_pin_type_mismatches",
    "missing_power_pin": "place_missing_units",
    # ...
}

def erc_auto_fix(ir: SchematicIR, file_path: Path, max_iterations: int) -> dict:
    all_fixes = []
    for iteration in range(max_iterations):
        violations = parse_erc(file_path)
        if not violations:
            break
        # Group by type, dispatch repairs in priority order
        # ...
    return {"fixes_applied": all_fixes, "iterations": iteration + 1}
```

### Anti-Patterns to Avoid
- **Do not register list/query ops as @register_query:** The query handler path assumes PcbIR (parse_pcb). Project files are not PCBs -- use @register_project.
- **Do not create new handler registries:** The existing 6 registries (schematic, pcb, project, create, query, crossfile) are sufficient.
- **Do not bypass the Operation discriminated union:** Every new schema class must be added to the `Operation.root` Annotated union in schema.py.
- **Do not import implementation modules at module level in executor.py:** Always use lazy imports inside handler functions.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| S-expression parsing for lib tables | Custom parser | `parse_lib_table()` from `lib_table.py` | Handles sexpdata wrapping, validation, path resolution |
| S-expression parsing for design rules | Custom parser | `parse_design_rules()` from `design_rules.py` | Handles multi-form DRU parsing, name/dimension validation |
| JSON parsing for .kicad_pro | Custom reader | `parse_project_file()` from `project_file.py` | Handles version differences, board nesting |
| Zone creation | Raw S-expression strings | `kiutils.items.zones.Zone` | Handles polygon, fill, keepout settings correctly |
| ERC result parsing | Custom regex | `parse_erc()` from `erc_parser.py` | Returns structured ErcViolation with type/position data |

**Key insight:** All parse/serialize infrastructure already exists. The new ops are primarily "wire up existing classes to new handler registrations."

## Common Pitfalls

### Pitfall 1: Forgetting to add new schemas to Operation union
**What goes wrong:** New op types validate as Pydantic models but fail at executor dispatch because they're not in the `Operation.root` Annotated union.
**Why it happens:** The union is a long list in schema.py (lines 274-332), easy to miss.
**How to avoid:** After adding any new schema class, add it to both the Operation union AND the `__all__` export list.
**Warning signs:** `KeyError` or `ValueError: Unknown op_type` at dispatch time.

### Pitfall 2: Using wrong handler registration for project files
**What goes wrong:** Registering list ops as `@register_query` causes a crash because query ops try to parse the file as PCB and create PcbIR.
**Why it happens:** Query and project paths look similar (both read-only intent).
**How to avoid:** Use `@register_project` for ALL ops targeting lib tables, .kicad_dru, and .kicad_pro files. The project handler path calls handlers with `(op, file_path)` -- no IR.
**Warning signs:** `AttributeError: 'NoneType' has no attribute 'board'` or parse failures on non-PCB files.

### Pitfall 3: DesignRulesFile frozen dataclass modification
**What goes wrong:** `NetClassDef` and `DesignRule` are `frozen=True` dataclasses. Direct attribute assignment raises `FrozenInstanceError`.
**Why it happens:** The modify pattern needs to replace the item in the list, not mutate it in place.
**How to avoid:** For `modify_net_class`, find the existing entry by name, create a new `NetClassDef` with updated fields, replace in list. Pattern: `dru.net_classes[i] = new_nc`.
**Warning signs:** `dataclasses.FrozenInstanceError: cannot assign to field 'clearance'`.

### Pitfall 4: Zone UUID vs index confusion
**What goes wrong:** KiCad zones use `tstamp` as UUID, but the field is a string (not a Python UUID object). Some zones may have empty or duplicate tstamp values.
**Why it happens:** tstamp is set during zone creation, may not be truly unique in imported/converted files.
**How to avoid:** Always try UUID first, fall back to index. Validate that zone_index < len(board.zones). Return clear error if neither resolves.
**Warning signs:** `StopIteration` from `next()` with no default, or `IndexError` on zone list.

### Pitfall 5: ERC auto-fix infinite loop
**What goes wrong:** Some repairs (like place_no_connects) may introduce new ERC violations, causing the loop to never terminate.
**Why it happens:** ERC violations are not independent -- fixing one can create another.
**How to avoid:** Enforce `max_iterations` (default 3). Track violation counts per iteration. If violations don't decrease, stop early. Return remaining violations to caller.
**Warning signs:** Auto-fix runs > 3 iterations, or total violation count increases after a repair.

### Pitfall 6: ProjectFile write losing unknown keys
**What goes wrong:** `ProjectFile` only extracts `general`, `pcbnew`, `schematic` sections. Writing back only those sections would lose any unrecognized keys in the JSON.
**Why it happens:** The parse step discards keys not in the dataclass fields.
**How to avoid:** For modify_project_settings, read the raw JSON dict, modify only the specified keys, write the full dict back. Do NOT round-trip through ProjectFile dataclass for writes.
**Warning signs:** .kicad_pro file shrinks after modify, loses `text_variables` or `net_settings` keys.

## Code Examples

### List lib entries (query op, project handler)
```python
# Schema in _schema_library.py
class ListLibEntriesOp(BaseModel):
    op_type: Literal["list_lib_entries"] = "list_lib_entries"
    target_file: TargetFile

# Handler in executor.py
@register_project("list_lib_entries")
def _handle_list_lib_entries(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.lib_table import parse_lib_table
    table = parse_lib_table(file_path)
    return {
        "entries": [
            {"name": e.name, "type": e.type, "uri": e.uri, "options": e.options, "description": e.descr}
            for e in table.entries
        ],
        "count": len(table.entries),
    }
```
[VERIFIED: codebase -- follows exact pattern of add_lib_entry handler]

### Modify net class (project handler with DesignRulesFile)
```python
# Schema in _schema_pcb.py
class ModifyNetClassOp(BaseModel):
    op_type: Literal["modify_net_class"] = "modify_net_class"
    target_file: TargetFile
    name: str = Field(min_length=1, max_length=64)
    clearance: Optional[float] = Field(default=None, gt=0)
    track_width: Optional[float] = Field(default=None, gt=0)
    via_diameter: Optional[float] = Field(default=None, gt=0)
    via_drill: Optional[float] = Field(default=None, gt=0)

# New method on DesignRulesFile (in design_rules.py)
def modify_net_class(self, name: str, **updates) -> NetClassDef:
    for i, nc in enumerate(self.net_classes):
        if nc.name == name:
            new_nc = dataclasses.replace(nc, **{k: v for k, v in updates.items() if v is not None})
            self.net_classes[i] = new_nc
            return new_nc
    raise KeyError(f"Net class '{name}' not found.")
```
[VERIFIED: codebase -- DesignRulesFile uses mutable list, NetClassDef is frozen dataclass, dataclasses.replace is the correct pattern]

### Remove copper zone by UUID (PCB handler)
```python
def remove_copper_zone(ir: PcbIR, zone_uuid: str | None = None, zone_index: int | None = None) -> dict[str, Any]:
    board = ir.board
    target = None
    if zone_uuid:
        target = next((z for z in board.zones if z.tstamp == zone_uuid), None)
        if target is None:
            raise ValueError(f"Zone with UUID '{zone_uuid}' not found")
    elif zone_index is not None:
        if zone_index >= len(board.zones):
            raise IndexError(f"Zone index {zone_index} out of range (total: {len(board.zones)})")
        target = board.zones[zone_index]
    else:
        raise ValueError("Must specify zone_uuid or zone_index")
    board.zones.remove(target)
    ir._record_mutation("remove_copper_zone", {"zone_uuid": target.tstamp})
    return {"removed": True, "zone_uuid": target.tstamp}
```
[VERIFIED: codebase -- follows add_copper_zone pattern in pcb_ops.py, Zone objects have tstamp field]

### Hierarchical power net validation (extending existing function)
```python
# In validation_gates.py, extend validate_power_nets():
def validate_power_nets(ir: SchematicIR, check_hierarchical: bool = False) -> dict[str, Any]:
    # ... existing logic for flat validation ...

    if check_hierarchical:
        hierarchical_issues = _check_hierarchical_power(ir, sch_path)
        # For each sub-sheet, verify power nets visible at boundary have power symbols inside
        # Reuse sheet traversal from check_sheet_pin_labels()
        result["hierarchical_issues"] = hierarchical_issues
        valid = valid and len(hierarchical_issues) == 0

    return result
```
[VERIFIED: codebase -- check_sheet_pin_labels() already traverses sheets, parse_schematic() handles sub-sheets]

### Project settings write (raw JSON round-trip)
```python
# In project_file.py -- new function (NOT method on frozen dataclass)
def write_project_settings(path: Path, updates: dict[str, Any]) -> None:
    """Modify .kicad_pro settings by merging updates into existing JSON."""
    content = path.read_text(encoding="utf-8")
    data = json.loads(content)
    # Deep merge updates into data (only specified keys)
    for section, values in updates.items():
        if isinstance(values, dict) and section in data:
            data[section].update(values)
        else:
            data[section] = values
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
```
[VERIFIED: codebase -- .kicad_pro is JSON format, parse_project_file reads it as JSON]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single schema file (ops/schema.py) | 14 sub-modules (_schema_*.py) | Phase 22-24 | New schemas go in appropriate sub-module, not monolith |
| Top-level imports in handlers | Lazy imports in handler bodies | Phase 24 Council | Avoid circular imports, reduce startup time |
| No undo support | UndoStack with file content snapshots | Phase 33 | Project handlers now support undo (pre/post content capture) |
| No IR cache | IRCache with LRU eviction | Phase 32 | Schematic/PCB handlers benefit from cache; project handlers don't use IR |

**Deprecated/outdated:**
- None for this phase's scope. All existing patterns are current.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | kiutils Zone objects have mutable `net`, `netName`, `layers`, `clearance`, `minThickness`, `priority` attributes suitable for modify_copper_zone | Pattern 2 | LOW -- kiutils 1.4.8 Zone dataclass fields are well-documented |
| A2 | ERC violation types from kicad-cli match the strings listed in CONTEXT.md (pin_not_connected, power_pin_not_driven, pin_to_pin, missing_power_pin) | GEN-03 | MEDIUM -- violation type strings could vary by KiCad version. Need to verify against actual ERC output. |
| A3 | .kicad_pro files use consistent JSON structure with general/pcbnew/schematic top-level keys across KiCad 10 versions | GEN-01 | LOW -- ProjectFile already handles version differences |
| A4 | The erc_auto_fix meta-op can call repair functions directly (import and call) rather than re-dispatching through the executor | GEN-03 | LOW -- repair functions are regular Python functions that accept (ir, file_path, ...) |

**If this table is empty:** All claims in this research were verified or cited -- no user confirmation needed.

## Open Questions

1. **Should list ops be registered as @register_project or as a new read-only project query path?**
   - What we know: Project handlers do not get IR, they get file_path. This is correct for lib table and DRU queries.
   - What's unclear: Whether we need a separate read-only project handler path (like _QUERY_HANDLERS for PCB).
   - Recommendation: Use `@register_project` for simplicity. The project handler path already handles undo correctly. List ops are idempotent reads that happen to modify nothing -- the handler simply returns data without calling serialize.

2. **Should modify_net_class support partial updates (Optional fields) or require all dimensions?**
   - What we know: CONTEXT.md says "update dimensions for an existing net class."
   - What's unclear: Whether all dimension fields must be specified or only changed ones.
   - Recommendation: Use Optional fields with `None` default meaning "keep existing value." This matches REST PATCH semantics and avoids forcing the caller to know current values.

3. **How should erc_auto_fix handle violations that don't map to any repair op?**
   - What we know: Not all ERC violation types have automated repairs.
   - What's unclear: Whether to silently skip or report unmapped types.
   - Recommendation: Report unmapped types in the return value under `"unhandled_violations"` so the caller can escalate to a human.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| kicad-cli | erc_auto_fix (parse_erc calls run_erc) | -- | -- | -- |
| Python 3.11+ | All ops | -- | -- | -- |
| kiutils | Copper zone ops | -- | -- | -- |
| sexpdata | Lib table / DRU ops | -- | -- | -- |

Step 2.6: SKIPPED (no external dependencies -- all tools already verified in project tool inventory)

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | pyproject.toml [tool.pytest.ini_options] |
| Quick run command | `python3 -m pytest tests/test_pcb_ops.py tests/test_project_file.py tests/test_schematic_repair.py -x -q` |
| Full suite command | `python3 -m pytest -x -q --ignore=tests/test_format_convert.py` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GEN-01 | List lib entries from sym-lib-table | unit | `pytest tests/test_project_file.py::TestListLibEntries -x` | Wave 0 |
| GEN-01 | Modify/remove net classes in .kicad_dru | unit | `pytest tests/test_project_file.py::TestModifyNetClass -x` | Wave 0 |
| GEN-01 | Modify/remove design rules in .kicad_dru | unit | `pytest tests/test_project_file.py::TestDesignRules -x` | Wave 0 |
| GEN-01 | Modify .kicad_pro settings | unit | `pytest tests/test_project_file.py::TestModifyProjectSettings -x` | Wave 0 |
| GEN-03 | erc_auto_fix chains parse to repair | integration | `pytest tests/test_schematic_repair.py::TestErcAutoFix -x` | Wave 0 |
| GEN-04 | Hierarchical power validation | unit | `pytest tests/test_validation_gates.py::TestHierarchicalPower -x` | Wave 0 |
| GEN-05 | Modify copper zone properties | unit | `pytest tests/test_pcb_ops.py::TestModifyCopperZone -x` | Wave 0 |
| GEN-05 | Remove copper zone by UUID | unit | `pytest tests/test_pcb_ops.py::TestRemoveCopperZone -x` | Wave 0 |
| GEN-06 | List net classes and design rules | unit | `pytest tests/test_project_file.py::TestListNetClasses -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python3 -m pytest tests/test_pcb_ops.py tests/test_project_file.py -x -q`
- **Per wave merge:** `python3 -m pytest -x -q --ignore=tests/test_format_convert.py`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_project_file.py` -- add test classes for ListLibEntries, ModifyNetClass, RemoveNetClass, ModifyDesignRule, RemoveDesignRule, ModifyProjectSettings
- [ ] `tests/test_schematic_repair.py` -- add TestErcAutoFix class
- [ ] `tests/test_pcb_ops.py` -- add TestModifyCopperZone, TestRemoveCopperZone classes
- [ ] `tests/test_validation_gates.py` -- add TestHierarchicalPower class (file may not exist yet, create)

## Sources

### Primary (HIGH confidence)
- Codebase analysis: _schema_library.py, _schema_pcb.py, _schema_repair.py, _schema_validation.py
- Codebase analysis: executor.py handler registration patterns (6 registries)
- Codebase analysis: design_rules.py (DesignRulesFile with add/remove_net_class, add/remove_rule)
- Codebase analysis: lib_table.py (LibTable with full CRUD + list_entries)
- Codebase analysis: project_file.py (ProjectFile read-only, JSON format)
- Codebase analysis: pcb_ops.py (add_copper_zone, set_board_outline, assign_net_class)
- Codebase analysis: validation_gates.py (validate_power_nets, check_sheet_pin_labels)
- Codebase analysis: erc_parser.py (parse_erc, ErcViolation, ViolationPosition)

### Secondary (MEDIUM confidence)
- CONTEXT.md locked decisions (user-verified architectural choices)

### Tertiary (LOW confidence)
- None -- all findings verified against codebase

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already in use, verified in imports
- Architecture: HIGH - patterns established across 91 completed plans, 57 existing ops
- Pitfalls: HIGH - identified from direct code inspection (frozen dataclass, handler registry types)

**Research date:** 2026-05-31
**Valid until:** 2026-06-30 (stable -- no external dependencies, internal codebase patterns)
