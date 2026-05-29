# Feature Landscape: MCP Operations Server

**Domain:** MCP tool server exposing kicad-agent's 57 operations to LLM clients
**Researched:** 2026-05-29
**Confidence:** HIGH
**Scope:** New MCP server milestone -- wrapping existing OperationExecutor as MCP tools

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Design Context](#design-context)
3. [Table Stakes](#table-stakes)
4. [Differentiators](#differentiators)
5. [Anti-Features](#anti-features)
6. [Feature Dependencies](#feature-dependencies)
7. [MVP Recommendation](#mvp-recommendation)
8. [Tool Annotation Strategy](#tool-annotation-strategy)
9. [Sources](#sources)

---

## Executive Summary

The MCP operations server exposes kicad-agent's 57 atomic operations as MCP tools, allowing any LLM client (Claude Code, Cursor, Windsurf, etc.) to edit KiCad schematics, PCBs, symbol libraries, and footprint libraries through a standardized protocol. The core design question is NOT whether to expose all 57 operations -- they should all be exposed -- but HOW to structure them for optimal LLM consumption and what supporting features (project context, validation, resource subscriptions) elevate the server from functional to excellent.

The primary design decision is between two tool architectures: **flat registration** (57 individual tools, one per op_type) versus **categorized dispatch** (5-8 grouped tools with an op_type discriminator). Flat registration is the recommended approach. It maximizes LLM tool-selection accuracy because each tool has a unique name, a specific JSON Schema, and a focused description. Categorized dispatch forces the LLM to choose a category AND an op_type, increasing the chance of miscategorization. The MCP filesystem reference server uses flat registration (11 tools, each with a clear name like `read_file`, `write_file`), and it works well.

Beyond the 57 operation tools, the table-stakes features are: project context discovery (so the LLM knows what files exist and their contents), operation listing (so the LLM can discover available operations), and ERC/DRC validation (so the LLM can verify its edits). Differentiators include MCP Resources for file content access, batch operations, sampling-assisted operations, and resource subscriptions for file watching.

---

## Design Context

### What Already Exists

| Component | Location | Purpose |
|-----------|----------|---------|
| `OperationExecutor` | `ops/executor.py` | Dispatches 57 op_types to handlers. Returns `dict[str, Any]`. Synchronous. |
| `Operation` schema | `ops/schema.py` | Pydantic v2 discriminated union. `model_json_schema()` exports JSON Schema per op. |
| Component-search MCP | `mcp/server.py` | Reference server pattern: `mcp.Server`, stdio transport, `asyncio.to_thread()`, rate limiting. |
| `ProjectSummary` | `context.py` | Discovers KiCad files, counts components/nets/footprints, renders text summary. |
| `SchematicIR` / `PcbIR` | `ir/` | Parsed intermediate representations with query methods. |
| Transaction system | `ir/transaction.py` | Per-file snapshot/commit/rollback. |
| `AtomicOperation` | `crossfile/atomic.py` | Multi-file all-or-nothing transactions. |

### The 57 Operation Types (by Category)

| Category | Count | Op Types | Executor Registry |
|----------|-------|----------|-------------------|
| Schematic mutation | 22 | add_component, remove_component, move_component, modify_property, duplicate_component, array_replicate, add_wire, add_label, add_power, add_no_connect, add_junction, remove_wire, remove_label, remove_junction, remove_no_connect, add_sheet, add_sheet_pin, navigate_hierarchy, snap_to_grid, add_power_flag, rebuild_root_sheet, embed_symbol, swap_symbol, convert_kicad6_to_10 | `_SCHEMATIC_HANDLERS` |
| PCB mutation | 9 | update_footprint_from_library, swap_footprint, add_net, remove_net, rename_net, add_copper_zone, set_board_outline, assign_net_class, auto_route | `_PCB_HANDLERS` |
| Project file | 4 | add_lib_entry, remove_lib_entry, add_net_class, add_design_rule | `_PROJECT_HANDLERS` |
| Create | 5 | create_schematic, create_pcb, create_project, create_symbol, create_footprint | `_CREATE_HANDLERS` |
| Query (read-only) | 1 | query_connectivity | `_QUERY_HANDLERS` |
| Validation (read-only) | 7 | validate_power_nets, validate_schematic, parse_erc, extract_violation_positions, validate_hlabels, validate_footprint, verify_pin_map | `_SCHEMATIC_HANDLERS` (mixed) |
| Reference (read-only) | 4 | renumber_refs, validate_refs, annotate, cross_ref_check | `_SCHEMATIC_HANDLERS` (mixed) |
| Cross-file | 1 | propagate_symbol_change | `_CROSSFILE_HANDLERS` |
| Repair | 1 | repair_schematic | `_SCHEMATIC_HANDLERS` |

**Note:** Some op_types are registered in `_SCHEMATIC_HANDLERS` but are semantically read-only (validation, reference ops). The MCP server should annotate these correctly regardless of executor registry placement.

---

## Table Stakes

Features the LLM client expects. Missing any of these makes the server feel incomplete or dangerous to use.

### TS-1: All 57 Operations as Individual MCP Tools

**Why expected:** The LLM needs to discover and call each operation independently. A tool server that cannot perform all registered operations is incomplete.

**Complexity:** MEDIUM (not LOW because generating good descriptions and annotations for 57 tools requires careful work, even though the dispatch logic is trivial)

**Dependencies:** OperationExecutor, Operation schema, all 57 op schemas

**Implementation:**
1. Extract 57 op classes from `Operation.model_fields['root'].annotation` via `typing.get_args()`
2. For each class, call `model_json_schema()` to produce `inputSchema`
3. Construct `mcp.types.Tool(name=op_type, description=..., inputSchema=schema)`
4. Register all in `@app.list_tools()`
5. In `@app.call_tool()`, route by tool name to `OperationExecutor.execute()`

**Key decision:** Flat 57-tool registration, NOT categorized dispatch.

**Rationale for flat registration:**
- LLMs select tools by name + description. Unique names (e.g., `add_component`, `remove_net`) are unambiguous.
- Each tool's JSON Schema is specific to that operation. No wasted fields or conditional branches.
- The MCP filesystem reference server uses flat registration (11 tools). The pattern scales.
- Adding a new operation later means adding one tool, not modifying a dispatcher.
- `model_json_schema()` on each Pydantic op class already produces the exact JSON Schema needed. No transformation layer.

**Rationale against categorized dispatch:**
- Would require 5-8 tools with `op_type` as a discriminator inside the JSON Schema. The LLM must pick both the correct category AND the correct op_type. Two chances to be wrong.
- The Pydantic `Operation` discriminated union already handles this validation. Exposing it as a flat tool list sidesteps the problem entirely -- the MCP call_tool handler validates through `Operation.model_validate()` regardless.
- Categorized descriptions become long and ambiguous ("execute a schematic operation like add_component or remove_component..."). Individual tool descriptions are specific ("Add a component to a KiCad schematic").

### TS-2: Project Context Discovery Tool

**Why expected:** The LLM cannot edit files it does not know exist. Before any editing session, the LLM needs to discover the project structure: which schematics, PCBs, and libraries are present, how many components, what the file hierarchy looks like.

**Complexity:** LOW

**Dependencies:** `context.py` (already built)

**Implementation:**
- Single MCP tool: `get_project_context`
- Input: `project_dir: str` (path to KiCad project directory)
- Calls `render_project_context(project_dir, enrich=True)` which already exists
- Returns formatted text summary with file lists, component counts, net counts

**Why a tool, not a resource:** The LLM needs to explicitly ask "what's in this project?" as a first step in its workflow. Resources are passively available; the LLM may not know to look for them. A tool forces the discovery step.

### TS-3: Operation Listing Tool

**Why expected:** With 57 tools registered, the LLM needs a quick way to see what operations are available, grouped by category, without reading all 57 tool descriptions.

**Complexity:** LOW

**Dependencies:** Operation schema registry

**Implementation:**
- Single MCP tool: `list_operations`
- Input: optional `category` filter (schematic, pcb, project, create, query, validation, repair, cross_file)
- Returns structured JSON: categories with op_type names, brief descriptions, and read/write classification
- This is a meta-tool: it describes the other tools

**Alternative considered:** Rely solely on MCP's built-in `list_tools`. Rejected because 57 tools produce a very long response. `list_operations` gives a condensed categorical view.

### TS-4: ERC/DRC Validation Tools

**Why expected:** After editing a schematic or PCB, the LLM must verify the changes are electrically correct. Running ERC after schematic edits and DRC after PCB edits is mandatory per the project's own CLAUDE.md rules. The operations for `parse_erc`, `validate_schematic`, `validate_power_nets`, `validate_hlabels` already exist in the schema -- they need to be exposed as MCP tools alongside a convenience wrapper.

**Complexity:** LOW

**Dependencies:** Existing validation ops in schema, `kicad-cli` for ERC/DRC

**Implementation:**
- The 7 validation ops are already among the 57 tools (TS-1 covers them)
- Additionally provide `run_erc` and `run_drc` convenience tools that wrap `kicad-cli sch erc` and `kicad-cli pcb drc` and parse the output
- These are distinct from the schema validation ops because they run the external KiCad validator rather than internal checks
- Input: `target_file: str`
- Returns: structured violations list with positions, severities, descriptions

### TS-5: Base Directory Configuration

**Why expected:** The LLM needs to know which project directory the server is operating on. All 57 operations use relative `target_file` paths resolved against a `base_dir`. The MCP server must accept this configuration at startup or through a tool.

**Complexity:** LOW

**Dependencies:** OperationExecutor constructor

**Implementation:**
- Accept `--base-dir` CLI argument when starting the server
- Alternatively, accept a `set_base_dir` MCP tool for dynamic reconfiguration
- Store as `OperationExecutor(base_dir=Path(base_dir))` in lifespan context
- All operation tool calls use this executor instance

---

## Differentiators

Features that set the server apart from a basic operation executor. Not expected, but they significantly improve the LLM's editing workflow.

### D-1: MCP Resources for File Content

**Value:** The LLM can read KiCad file contents without calling an operation. Resources are passive data the LLM can browse before deciding what to edit. This is faster than calling `get_project_context` for every file.

**Complexity:** MEDIUM

**Dependencies:** Parser modules, IR modules

**Implementation:**
- Register MCP resource templates:
  - `kicad://project/{path}` -- returns `render_project_context()` for any directory
  - `kicad://schematic/{path}` -- returns parsed schematic summary (components, nets, labels, hierarchy)
  - `kicad://pcb/{path}` -- returns parsed PCB summary (footprints, nets, zones, dimensions)
  - `kicad://library/{path}` -- returns library contents (symbol names, footprint names)
- Use `mcp.types.ResourceTemplate` with RFC 6570 URI templates
- Implement `@app.list_resources()` and `@app.read_resource()` handlers
- Resources are read-only -- no mutation through resource URIs

**Why it differentiates:** Most MCP tool servers are tool-only. Adding resources lets the LLM explore the project passively, building context before editing. This matches how an experienced KiCad user would first open files to understand the design before making changes.

### D-2: Batch Operation Execution

**Value:** The LLM often needs to perform multiple operations in sequence (e.g., add 10 components, wire them, add labels). Sending 10 individual tool calls is slow and risks partial completion. A batch tool executes multiple operations atomically -- all succeed or all roll back.

**Complexity:** HIGH

**Dependencies:** AtomicOperation, OperationExecutor

**Implementation:**
- Single MCP tool: `execute_batch`
- Input: `operations: list[Operation]` (array of validated operation objects)
- Executes within a single AtomicOperation context
- If any operation fails, rolls back ALL operations (even successful ones)
- Returns array of results, one per operation

**Risk:** Large batches may timeout on the MCP transport. Consider a batch size limit (e.g., max 20 operations per batch).

**Why it differentiates:** The internal AtomicOperation system already supports this pattern for cross-file operations. Extending it to arbitrary operation sequences gives the LLM a powerful compound-edit capability that no other KiCad MCP server provides.

### D-3: Structured Error Responses with Repair Hints

**Value:** When an operation fails, the LLM gets a structured error with a suggested fix, not just a traceback. This dramatically improves the LLM's ability to self-correct.

**Complexity:** MEDIUM

**Dependencies:** Existing error types, schema validators

**Implementation:**
- Standardize error response format:
  ```json
  {
    "success": false,
    "operation": "add_component",
    "error": {
      "type": "validation_error",
      "message": "Library ID 'Device:R_Small' not found in sym-lib-table",
      "suggestion": "Run list_operations with category='library' to see available libraries, or add the library with add_lib_entry",
      "target_file": "motor-driver.kicad_sch",
      "recoverable": true
    }
  }
  ```
- Error types: `validation_error`, `file_not_found`, `parse_error`, `mutation_error`, `security_error`
- Each handler maps its exceptions to structured errors with suggestions
- Use `isError: true` in MCP `CallToolResult` for protocol-correct error signaling

**Why it differentiates:** The existing executor returns `{"success": True, ...}` on success but raises exceptions on failure. Wrapping exceptions in structured error responses with repair hints gives the LLM actionable information for self-correction. This is the difference between "something went wrong" and "the footprint library path is wrong, try running validate_footprint first."

### D-4: Pre/Post Validation Hooks

**Value:** Automatically run validation before and after mutation operations. Pre-validation catches issues early (e.g., "this schematic has ERC errors before you even start editing"). Post-validation confirms the edit did not introduce new errors.

**Complexity:** MEDIUM

**Dependencies:** Existing validation ops, kicad-cli

**Implementation:**
- Server-level configuration: `validate_before: bool`, `validate_after: bool`
- Before mutation ops: run a quick structural validation (parse the file, check format)
- After mutation ops: run full validation (ERC for schematics, DRC for PCBs)
- Results attached to the operation response as `pre_validation` and `post_validation` fields
- Optional: `strict_mode` where post-validation failures trigger automatic rollback

**Why it differentiates:** The existing `validation_gates.py` module provides the validation infrastructure. Wiring it into the MCP server gives the LLM automatic quality assurance. The LLM does not have to remember to run ERC after every edit -- the server does it automatically.

### D-5: Sampling-Assisted Operations

**Value:** The MCP server can request LLM completions through the client using MCP Sampling. This enables operations like "suggest component placement" or "recommend routing strategy" where the server asks the LLM for reasoning.

**Complexity:** HIGH

**Dependencies:** MCP Sampling protocol support in client

**Implementation:**
- Use `app.request_context.session.create_message()` to request LLM completions
- Example: `auto_layout` operation that asks the LLM "given these 20 components, suggest optimal positions based on connectivity"
- The LLM response feeds back into the operation handler as placement coordinates
- Requires client support for MCP Sampling (Claude Code supports this)

**Why it differentiates:** This closes the loop -- the MCP server becomes bidirectional. Not just "LLM calls tools" but "tools call LLM for reasoning." This is architecturally unique and enables higher-level operations that require spatial reasoning.

### D-6: Operation History and Undo

**Value:** The LLM can see what operations it has performed in the current session and undo them. This is critical for error recovery -- "undo the last 3 operations" is faster than manually reversing each one.

**Complexity:** MEDIUM

**Dependencies:** Transaction system, git (for undo)

**Implementation:**
- Maintain an in-memory operation log per session
- Each successful operation records: op_type, target_file, parameters, timestamp, result
- `get_operation_history` tool returns the log
- `undo_last_operation` tool reverts the most recent operation by restoring from Transaction backup
- Optional: `undo_n_operations` for batch undo

**Why it differentiates:** Most MCP tool servers are stateless. Adding session history and undo makes the server stateful in a useful way. The Transaction system already captures file snapshots -- the undo tool just restores them.

---

## Anti-Features

Features to explicitly NOT build. These would harm the server's usability, safety, or maintainability.

### AF-1: Auto-Discovery of Available Operations via LLM

**Why avoid:** Letting the LLM discover available operations by "asking" the server through freeform text is fragile. The LLM should use structured tool listing, not conversational discovery.

**What to do instead:** Fixed tool list via `list_tools()`. Clear descriptions. `list_operations` meta-tool for categorical overview.

### AF-2: Automatic Batch Inference from Single Operation

**Why avoid:** The server should not automatically infer that "add a resistor" means "add component + wire it to the nearest net + assign footprint + add label." Each operation is atomic (D-02). Breaking this invariant for convenience would make behavior unpredictable and debugging impossible.

**What to do instead:** Explicit batch execution via `execute_batch` (D-2). The LLM specifies exactly which operations to chain.

### AF-3: File Watching / Resource Subscriptions

**Why avoid:** Real-time file change notifications via MCP Resource Subscriptions add significant complexity (inotify/fsevents, debouncing, concurrent modification detection) for minimal benefit. The LLM editing workflow is synchronous: read -> edit -> validate. It does not need push notifications.

**What to do instead:** LLM calls `get_project_context` or reads a resource when it needs current state. Polling is sufficient for the editing use case.

### AF-4: Persistent State Across Sessions

**Why avoid:** Storing operation history, preferences, or learned patterns across MCP server restarts adds a database dependency and complicates the server lifecycle. The MCP server should be stateless between sessions.

**What to do instead:** In-memory state only. The LLM rediscovers project context at session start. Operation history lives only for the current session.

### AF-5: GUI Integration / KiCad IPC

**Why avoid:** Communicating with a running KiCad GUI instance (via IPC, socket, or file watchers) is fragile, platform-dependent, and introduces concurrency issues. The MCP server should operate on files, not on a live GUI session.

**What to do instead:** File-based editing only. The user refreshes the KiCad GUI to see changes (KiCad detects file changes automatically). If KiCad is running, the server should warn that concurrent editing may cause conflicts.

### AF-6: Dynamic Tool Registration / Runtime Schema Modification

**Why avoid:** Adding or removing MCP tools based on the current project's libraries or configuration would make the tool list unpredictable. The LLM cannot plan its workflow if the available tools change mid-session.

**What to do instead:** Fixed set of 57 operation tools, always available. Validation operations (validate_footprint, verify_pin_map) report what is missing, rather than the tool disappearing.

---

## Feature Dependencies

### Internal Dependency Graph

```
TS-1 (57 tools)
  depends on: OperationExecutor, Operation schema (all 57 classes)
  blocks: everything else (core dispatch)

TS-5 (base dir config)
  depends on: OperationExecutor constructor
  blocks: TS-1 (executor needs base_dir)

TS-2 (project context)
  depends on: context.py (exists)
  blocks: nothing (standalone tool)

TS-3 (list operations)
  depends on: schema.py metadata
  blocks: nothing (standalone tool)

TS-4 (ERC/DRC tools)
  depends on: kicad-cli, existing validation ops
  blocks: D-4 (pre/post validation hooks)

D-1 (resources)
  depends on: parser modules, IR modules
  blocks: nothing

D-2 (batch ops)
  depends on: TS-1, AtomicOperation
  blocks: nothing

D-3 (structured errors)
  depends on: TS-1 (wraps existing dispatch)
  blocks: nothing

D-4 (validation hooks)
  depends on: TS-1, TS-4, validation_gates.py
  blocks: nothing

D-5 (sampling)
  depends on: TS-1, MCP Sampling support in client
  blocks: nothing

D-6 (history/undo)
  depends on: TS-1, Transaction system
  blocks: nothing
```

### External Dependencies

| Dependency | Type | Status | Notes |
|------------|------|--------|-------|
| `mcp` package 1.12.3 | Python package | Installed | Low-level Server + types |
| `mcp.server.stdio` | Transport | Installed | stdio transport, same as component-search |
| `kicad-cli 10.0.1` | External CLI | Installed | For ERC/DRC execution |
| Pydantic v2 2.12.5 | Python package | Installed | Schema generation |
| `asyncio.to_thread()` | Python stdlib | Available | Wrapping sync executor calls |

---

## MVP Recommendation

### Phase 1: Core Server (Must-Have)

The minimum viable MCP operations server. Without these, the server is unusable.

| Feature | ID | Est. Effort |
|---------|-----|-------------|
| All 57 operations as MCP tools | TS-1 | 2-3 days |
| Base directory configuration | TS-5 | 0.5 day |
| Project context discovery | TS-2 | 0.5 day |
| Operation listing | TS-3 | 0.5 day |
| Structured error responses | D-3 | 1 day |

**Total: 4-5 days**

This gives the LLM a fully functional editing server. It can discover projects, list available operations, execute any of the 57 operations, and receive clear error messages when something goes wrong.

### Phase 2: Validation (Should-Have)

| Feature | ID | Est. Effort |
|---------|-----|-------------|
| ERC/DRC convenience tools | TS-4 | 1 day |
| Pre/post validation hooks | D-4 | 1-2 days |
| Operation history and undo | D-6 | 1-2 days |

**Total: 3-5 days**

This adds safety nets. The LLM can verify its edits, get automatic validation feedback, and undo mistakes.

### Phase 3: Advanced (Nice-to-Have)

| Feature | ID | Est. Effort |
|---------|-----|-------------|
| MCP Resources for file content | D-1 | 2-3 days |
| Batch operation execution | D-2 | 2-3 days |
| Sampling-assisted operations | D-5 | 3-5 days |

**Total: 7-11 days**

This elevates the server from functional to excellent. Resources provide passive context. Batch operations enable compound edits. Sampling enables bidirectional LLM collaboration.

### Deferred

| Feature | Reason |
|---------|--------|
| File watching/subscriptions (AF-3) | Polling is sufficient for editing workflow |
| Persistent state (AF-4) | Stateless is simpler and more reliable |
| KiCad GUI IPC (AF-5) | File-based is safer and platform-independent |
| Dynamic tool registration (AF-6) | Fixed tool list is more predictable |

---

## Tool Annotation Strategy

MCP tool annotations hint at tool behavior without enforcing it. The MCP protocol defines these annotation fields:

| Annotation | Purpose | When to Set `true` |
|------------|---------|-------------------|
| `readOnlyHint` | Tool does not modify state | All query, validation, and reference ops |
| `destructiveHint` | Tool may destroy data irreversibly | Remove operations, repair operations |
| `idempotentHint` | Repeated calls produce same result | Create ops (create if not exists), validation ops |
| `openWorldHint` | Tool accesses external resources | Component search ops (access JLCPCB API) |

### Annotation Map by Category

| Category | readOnlyHint | destructiveHint | idempotentHint | openWorldHint |
|----------|-------------|-----------------|----------------|---------------|
| Schematic mutation (add/move/modify) | false | false | false | false |
| Schematic remove | false | true | false | false |
| PCB mutation | false | false | false | false |
| PCB remove (remove_net, rename_net) | false | true | false | false |
| Project file (add_lib_entry, add_net_class) | false | false | false | false |
| Project file (remove_lib_entry) | false | true | false | false |
| Create | false | false | true | false |
| Query (query_connectivity) | true | false | false | false |
| Validation (all 7 ops) | true | false | true | false |
| Reference (renumber, annotate, validate_refs) | false | false | false | false |
| Reference (cross_ref_check) | true | false | false | false |
| Cross-file (propagate_symbol_change) | false | false | false | false |
| Repair (repair_schematic, snap_to_grid, convert) | false | true | false | false |
| Repair (rebuild_root_sheet, add_power_flag) | false | false | false | false |
| Context tools (get_project_context, list_operations) | true | false | true | false |
| ERC/DRC tools (run_erc, run_drc) | true | false | false | false |

### Annotation Implementation

```python
# Tool annotation mapping: op_type -> mcp.types.ToolAnnotations
TOOL_ANNOTATIONS = {
    # Read-only operations
    "query_connectivity": ToolAnnotations(readOnlyHint=True),
    "validate_power_nets": ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    "validate_schematic": ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    "parse_erc": ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    "extract_violation_positions": ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    "validate_hlabels": ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    "validate_footprint": ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    "verify_pin_map": ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    "cross_ref_check": ToolAnnotations(readOnlyHint=True),
    "navigate_hierarchy": ToolAnnotations(readOnlyHint=True),

    # Destructive operations
    "remove_component": ToolAnnotations(destructiveHint=True),
    "remove_wire": ToolAnnotations(destructiveHint=True),
    "remove_label": ToolAnnotations(destructiveHint=True),
    "remove_junction": ToolAnnotations(destructiveHint=True),
    "remove_no_connect": ToolAnnotations(destructiveHint=True),
    "remove_net": ToolAnnotations(destructiveHint=True),
    "remove_lib_entry": ToolAnnotations(destructiveHint=True),
    "repair_schematic": ToolAnnotations(destructiveHint=True),
    "snap_to_grid": ToolAnnotations(destructiveHint=True),
    "convert_kicad6_to_10": ToolAnnotations(destructiveHint=True),

    # Idempotent operations
    "create_schematic": ToolAnnotations(idempotentHint=True),
    "create_pcb": ToolAnnotations(idempotentHint=True),
    "create_project": ToolAnnotations(idempotentHint=True),
    "create_symbol": ToolAnnotations(idempotentHint=True),
    "create_footprint": ToolAnnotations(idempotentHint=True),
}
```

---

## Sources

- `src/kicad_agent/ops/schema.py` -- 57 operation schemas, discriminated union, `model_json_schema()` export
- `src/kicad_agent/ops/executor.py` -- OperationExecutor dispatch, 6 handler registries, Transaction wrapping
- `src/kicad_agent/mcp/server.py` -- Existing MCP server pattern (low-level Server, stdio transport, asyncio.to_thread)
- `src/kicad_agent/mcp/tools.py` -- Tool implementation pattern (validation, formatting, rate limiting)
- `src/kicad_agent/context.py` -- ProjectSummary, file discovery, context rendering
- MCP Specification: `https://modelcontextprotocol.io/docs/concepts/tools` -- Tool definitions, annotations, error handling
- MCP Specification: `https://modelcontextprotocol.io/docs/concepts/resources` -- Resource templates, subscriptions
- MCP Filesystem Server (reference implementation) -- 11 tools with annotation table, flat registration pattern
- `typing.get_args()` on `Operation.model_fields['root'].annotation` -- Extracts exactly 57 op classes

---
*Feature landscape research for: kicad-agent MCP operations server milestone*
*Researched: 2026-05-29*
*Confidence: HIGH*
