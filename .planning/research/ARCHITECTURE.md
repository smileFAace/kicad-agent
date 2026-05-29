# Architecture: MCP Edit Server for KiCad Operations

**Domain:** MCP server exposing 57 KiCad editing operations as AI-callable tools
**Researched:** 2026-05-29
**Confidence:** HIGH (direct codebase analysis, MCP SDK v1.12.3 verified, existing server pattern established)

## Executive Summary

The kicad-agent project needs a new MCP server that exposes its 57 operation types as tools that AI agents (Claude, GPT, etc.) can call to edit KiCad schematic, PCB, symbol, and footprint files. The existing `kicad-component-search` MCP server (4 tools for JLCPCB lookup) provides a proven pattern but serves a fundamentally different purpose -- it wraps an external API client, while the edit server must wrap a local file-mutation engine with Transaction-based rollback, path confinement security, and IR-based structural editing.

The recommended architecture is a **separate server binary** (`kicad-agent-edit`) using the same low-level `mcp.server.Server` API as the existing component-search server, with **dynamic tool generation** from the Pydantic schema's `oneOf` discriminated union. Each of the 57 operation types becomes a distinct MCP tool. The tool definitions are generated at startup by iterating the JSON Schema produced by `Operation.model_json_schema()`, extracting each variant's `op_type` const and its `inputSchema`.

This approach keeps the existing component-search server untouched, avoids the complexity of a monolithic multi-purpose server, and gives AI agents granular tool selection. The OperationExecutor class -- the existing dispatch engine with 6 handler registries (schematic: 41, PCB: 10, project: 4, create: 5, query: 1, cross-file: 1) -- serves as the backend without modification.

## Recommended Architecture

### Integration Approach: Separate Server Binary

Three options were evaluated:

| Option | Description | Verdict |
|--------|-------------|---------|
| **A. Merge into existing server** | Add 57 tools to `kicad-component-search` | REJECTED -- mixes concerns, bloats a focused server, requires shared state |
| **B. Shared module, two entry points** | Extract common MCP infra to `mcp/base.py`, both servers import it | REJECTED -- premature abstraction, existing server is simple and complete at 284 lines |
| **C. New server module, own entry point** | `mcp/edit_server.py` with `kicad-agent-edit` binary | RECOMMENDED -- clean separation, independent lifecycle, zero risk to existing |

**Why separate binary:** The component-search server wraps `EasyEdaClient` for JLCPCB API calls (network I/O, rate limiting, caching). The edit server wraps `OperationExecutor` for local file mutation (disk I/O, AST parsing, Transaction rollback). These have zero shared runtime state. A merged server would carry unnecessary dependencies and complicate error isolation. The separate binary also lets users install only what they need.

**Data flow for the new server:**

```
AI Agent (MCP Client)
  |
  v  (stdio transport, JSON-RPC)
edit_server.py
  |-- list_tools() -> 57 Tool definitions (generated from Pydantic schema at startup)
  |-- call_tool(name, arguments)
       |
       v
     Operation.model_validate({"root": arguments_with_op_type})
       |
       v  (Pydantic validates all fields, rejects unsafe chars, path traversal)
     OperationExecutor(base_dir=project_dir).execute(op)
       |
       v  (dispatches to registry: schematic/pcb/project/create/query/cross-file)
     Handler function (parse -> IR -> mutate -> serialize -> normalize -> commit)
       |
       v
     {"success": true, "operation": "...", "target_file": "...", "details": {...}}
```

### Tool Mapping Strategy: 57 Individual Tools

Three patterns were evaluated for mapping operations to MCP tools:

| Pattern | Description | Pros | Cons |
|---------|-------------|------|------|
| **A. Single `execute_operation` tool** | One tool accepting the full Operation union | Simple server code | AI must construct perfect discriminated union; tool too generic; poor discoverability |
| **B. 57 individual tools** | One tool per op_type | Best discoverability; AI picks exact tool; inputSchema per operation | More tool definitions (but generated dynamically) |
| **C. 6 grouped tools by category** | `schematic_op`, `pcb_op`, etc. each accepting category union | Fewer tools | AI must know category; adds indirection; categories have different dispatch semantics |

**Recommendation: Pattern B -- 57 individual tools.**

Rationale:
1. MCP clients (Claude Desktop, Cursor, etc.) present tools by name. A tool named `add_component` is immediately clear; `execute_operation` with an `op_type` parameter is not.
2. Each tool's `inputSchema` can be extracted directly from the Pydantic schema's `oneOf` variants -- no manual schema writing needed.
3. The existing component-search server manually defined 4 tool schemas. With 57 tools, manual definition is impractical. Dynamic generation from `Operation.model_json_schema()` is the only maintainable approach.
4. MCP's `ToolAnnotations` provides `readOnlyHint` and `destructiveHint` that can be set per tool, giving AI agents safety signals.

**Dynamic tool generation implementation:**

```python
from kicad_agent.ops.schema import Operation, get_operation_schema

def _build_tool_definitions() -> list[types.Tool]:
    """Generate MCP tool definitions from the Pydantic Operation schema."""
    schema = get_operation_schema()
    defs = schema.get("$defs", {})
    root_prop = schema["properties"]["root"]
    tools = []

    for variant in root_prop["oneOf"]:
        ref = variant.get("$ref", "")
        class_name = ref.split("/")[-1]
        cls_schema = defs.get(class_name, {})
        props = cls_schema.get("properties", {})
        op_type = props.get("op_type", {}).get("const", "")

        # Build inputSchema from the variant's properties, minus op_type
        input_props = {k: v for k, v in props.items() if k != "op_type"}
        required = [r for r in cls_schema.get("required", []) if r != "op_type"]

        # Determine annotations based on operation category
        annotations = _build_annotations(op_type)

        tools.append(types.Tool(
            name=op_type,
            description=_build_description(class_name, cls_schema),
            inputSchema={
                "type": "object",
                "properties": input_props,
                "required": required,
            },
            annotations=annotations,
        ))

    return tools
```

### Tool Annotations Strategy

MCP ToolAnnotations (verified available in SDK v1.12.3) provides behavioral hints:

```python
def _build_annotations(op_type: str) -> types.ToolAnnotations:
    """Set safety annotations based on operation category."""
    read_only_ops = {
        "query_connectivity", "validate_refs", "validate_schematic",
        "validate_power_nets", "validate_footprint", "verify_pin_map",
        "cross_ref_check", "parse_erc", "extract_violation_positions",
        "validate_hlabels", "navigate_hierarchy",
    }
    destructive_ops = {
        "remove_component", "remove_net", "remove_wire", "remove_label",
        "remove_junction", "remove_no_connect", "remove_lib_entry",
        "repair_schematic", "convert_kicad6_to_10", "rebuild_root_sheet",
    }

    return types.ToolAnnotations(
        readOnlyHint=op_type in read_only_ops,
        destructiveHint=op_type in destructive_ops,
        idempotentHint=False,  # Most operations produce side effects
        openWorldHint=False,   # All operations target local files
    )
```

### Component Boundaries

| Component | Responsibility | Status | Location |
|-----------|---------------|--------|----------|
| `mcp/edit_server.py` | NEW: MCP server with 57 dynamic tools | Must create | `src/kicad_agent/mcp/` |
| `mcp/server.py` | UNCHANGED: Component search server | No changes | `src/kicad_agent/mcp/` |
| `mcp/tools.py` | UNCHANGED: Component search tool implementations | No changes | `src/kicad_agent/mcp/` |
| `mcp/__init__.py` | UNCHANGED: Package init | No changes | `src/kicad_agent/mcp/` |
| `ops/schema.py` | UNCHANGED: Operation schema + `get_operation_schema()` | Imported, not modified | `src/kicad_agent/ops/` |
| `ops/executor.py` | UNCHANGED: OperationExecutor dispatch engine | Imported, not modified | `src/kicad_agent/ops/` |
| `pyproject.toml` | MODIFIED: Add `kicad-agent-edit` entry point | 1 line addition | Project root |
| `context.py` | UNCHANGED: `render_project_context()` for project context | May be imported for context tool | `src/kicad_agent/` |

### New vs Modified Files

**New files (1):**
- `src/kicad_agent/mcp/edit_server.py` -- Complete MCP edit server (~200-250 lines)

**Modified files (1):**
- `pyproject.toml` -- Add entry point: `kicad-agent-edit = "kicad_agent.mcp.edit_server:main"`

**Total impact: ~250 lines new, 1 line modified. Zero risk to existing functionality.**

### Detailed Data Flow

```
1. Server Startup:
   edit_server.py loads
     -> calls _build_tool_definitions()
     -> Operation.model_json_schema() generates full schema
     -> Iterates oneOf[0..56], extracts op_type consts, builds 57 types.Tool
     -> Server registers list_tools() and call_tool() handlers

2. Tool Discovery (list_tools):
   MCP client sends tools/list request
     -> Server returns 57 Tool objects with name, description, inputSchema, annotations

3. Tool Invocation (call_tool):
   MCP client sends tools/call with name="add_component" and arguments={...}
     -> Server reconstructs Operation: {"root": {"op_type": "add_component", **arguments}}
     -> Operation.model_validate(payload) -- Pydantic validates all fields
     -> If validation fails: return error with field details
     -> OperationExecutor(base_dir).execute(op)
     -> Executor dispatches to _SCHEMATIC_HANDLERS["add_component"]
     -> Handler: parse_schematic -> SchematicIR -> add_component -> serialize -> commit
     -> Return result as types.TextContent(JSON)

4. Error Handling:
   - Pydantic ValidationError -> formatted error message with field details
   - FileNotFoundError -> "Target file not found: ..."
   - ValueError (security/path) -> "Security: path escapes project directory"
   - ValueError (dispatch) -> "Unknown op_type: ..."
   - Unexpected -> correlation ID + server log reference
```

### Project Directory Resolution

The component-search server does not need a project directory (it queries an external API). The edit server must know which project directory to operate on. Three options:

| Option | How | Tradeoff |
|--------|-----|----------|
| **CLI argument** | `kicad-agent-edit --project-dir /path` | Simple, requires restart to change project |
| **Environment variable** | `KICAD_PROJECT_DIR=/path kicad-agent-edit` | Standard, compatible with MCP client configs |
| **Per-call argument** | Every tool includes `project_dir` field | Flexible, but redundant on every call |

**Recommendation: Environment variable with CLI argument fallback.** The server reads `KICAD_PROJECT_DIR` at startup. If not set, falls back to `--project-dir` argument. If neither, fails with clear error message. This matches how MCP clients configure server environments in their JSON config files (e.g., Claude Desktop's `claude_desktop_config.json`).

### Server Lifespan

```python
@asynccontextmanager
async def server_lifespan(server: Server):
    """Initialize OperationExecutor once, share across all tool calls."""
    project_dir = Path(os.environ.get("KICAD_PROJECT_DIR", ".")).resolve()
    if not project_dir.is_dir():
        raise RuntimeError(f"Project directory does not exist: {project_dir}")
    executor = OperationExecutor(base_dir=project_dir)
    yield {"executor": executor, "project_dir": project_dir}
```

### call_tool Implementation

The core routing function is simple because all operations go through a single executor:

```python
@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    lifespan_ctx = app.request_context.lifespan_context
    executor: OperationExecutor = lifespan_ctx["executor"]

    # Reconstruct Operation envelope for Pydantic validation
    payload = {"root": {"op_type": name, **arguments}}

    try:
        op = Operation.model_validate(payload)
    except ValidationError as e:
        return [types.TextContent(type="text", text=f"Validation error: {e}")]

    try:
        result = await asyncio.to_thread(executor.execute, op)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    except FileNotFoundError as e:
        return [types.TextContent(type="text", text=f"File not found: {e}")]
    except ValueError as e:
        return [types.TextContent(type="text", text=f"Error: {e}")]
    except Exception as e:
        correlation_id = str(uuid.uuid4())[:8]
        logger.exception("Tool %s failed [ref=%s]", name, correlation_id)
        return [types.TextContent(
            type="text",
            text=f"Internal error (ref: {correlation_id}). See server logs.",
        )]
```

### Integration with Existing Component-Search Server

The two servers are **completely independent** at runtime:

| Aspect | Component Search | Edit Server |
|--------|-----------------|-------------|
| Entry point | `kicad-component-search` | `kicad-agent-edit` |
| Transport | stdio | stdio |
| Shared code | None (independent) | None (independent) |
| Dependencies | `EasyEdaClient` (network) | `OperationExecutor` (local files) |
| State | API client + cache | Executor + project dir |
| Error domain | API failures, rate limits | File I/O, validation, security |

They share:
- The `kicad_agent` package namespace
- The `mcp` optional dependency group in `pyproject.toml`
- The same `mcp` SDK version

**MCP client configuration (Claude Desktop example):**

```json
{
  "mcpServers": {
    "kicad-component-search": {
      "command": "kicad-component-search"
    },
    "kicad-agent-edit": {
      "command": "kicad-agent-edit",
      "env": {
        "KICAD_PROJECT_DIR": "/Users/bret/projects/my-pcb-project"
      }
    }
  }
}
```

### Operation Category Reference

For the Roadmapper, here is the complete mapping of 62 handler registrations across 57 operation types (some ops register in both schematic and PCB registries):

| Registry | Count | Operations |
|----------|-------|------------|
| `_SCHEMATIC_HANDLERS` | 41 | add_component, remove_component, duplicate_component, array_replicate, move_component, modify_property, add_net, remove_net, rename_net, renumber_refs, validate_refs, annotate, cross_ref_check, assign_footprint, swap_footprint, validate_footprint, verify_pin_map, add_wire, add_label, add_power, add_no_connect, add_junction, repair_schematic, validate_power_nets, validate_schematic, parse_erc, extract_violation_positions, validate_hlabels, convert_kicad6_to_10, snap_to_grid, add_power_flag, rebuild_root_sheet, embed_symbol, swap_symbol, remove_wire, remove_label, remove_junction, remove_no_connect, add_sheet, add_sheet_pin, navigate_hierarchy |
| `_PCB_HANDLERS` | 10 | update_footprint_from_library, swap_footprint, add_net, remove_net, rename_net, validate_footprint, add_copper_zone, set_board_outline, assign_net_class, auto_route |
| `_PROJECT_HANDLERS` | 4 | add_lib_entry, remove_lib_entry, add_net_class, add_design_rule |
| `_CREATE_HANDLERS` | 5 | create_schematic, create_pcb, create_project, create_symbol, create_footprint |
| `_QUERY_HANDLERS` | 1 | query_connectivity |
| `_CROSSFILE_HANDLERS` | 1 | propagate_symbol_change |

Note: `add_net`, `remove_net`, `rename_net`, `swap_footprint`, `validate_footprint` have handlers in both schematic and PCB registries. The executor routes by file extension (`.kicad_pcb` goes to `_PCB_HANDLERS`, everything else to `_SCHEMATIC_HANDLERS`). The MCP server does not need to know about this -- the executor handles it internally.

### Optional: Context Tool

Consider adding a `get_project_context` tool that calls `render_project_context()` from `context.py`. This gives AI agents a way to discover what files exist in the project and their contents before issuing edit operations. This is a natural complement to the editing tools.

```python
types.Tool(
    name="get_project_context",
    description="Get an overview of all KiCad files in the project directory...",
    inputSchema={"type": "object", "properties": {}, "required": []},
    annotations=types.ToolAnnotations(readOnlyHint=True),
)
```

This would bring the total to 58 tools. It can be added in a follow-up phase.

## Patterns to Follow

### Pattern 1: Low-Level Server API (Match Existing)

Use `mcp.server.Server` (not `FastMCP`) to match the existing component-search server pattern. This keeps the two servers structurally consistent and avoids introducing a second MCP API style into the codebase.

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server

app = Server("kicad-agent-edit", version="0.1.0", lifespan=server_lifespan)
```

### Pattern 2: Schema-Driven Tool Generation

Generate tool definitions from the Pydantic schema rather than hand-writing them. This ensures tools stay in sync with the operation schema automatically.

```python
schema = Operation.model_json_schema()
for variant in schema["properties"]["root"]["oneOf"]:
    # Extract tool name, inputSchema, description from schema
    ...
```

### Pattern 3: Sync-to-Async Bridge

Wrap synchronous `OperationExecutor.execute()` calls in `asyncio.to_thread()` to avoid blocking the MCP event loop. This matches the existing pattern in `server.py`.

```python
result = await asyncio.to_thread(executor.execute, op)
```

### Pattern 4: Envelope Reconstruction

MCP tools receive `arguments` as a flat dict. The Pydantic `Operation` model expects `{"root": {"op_type": ..., ...}}`. The server reconstructs this envelope before validation.

```python
payload = {"root": {"op_type": name, **arguments}}
op = Operation.model_validate(payload)
```

### Pattern 5: Correlated Error Responses

Use UUID correlation IDs for unexpected errors (matching existing server pattern). This allows log lookup without exposing internals.

```python
correlation_id = str(uuid.uuid4())[:8]
logger.exception("Tool %s failed [ref=%s]", name, correlation_id)
return [types.TextContent(type="text", text=f"Internal error (ref: {correlation_id})")]
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: FastMCP for This Server

**What:** Using `FastMCP` with `@mcp.tool()` decorators for 57 operations.
**Why bad:** Would require 57 decorated functions or dynamic function generation at module level. The low-level `Server` API with a single `call_tool()` dispatch is cleaner because all 57 operations go through one `OperationExecutor.execute()` call. FastMCP adds decorator overhead with no benefit when the dispatch target is a single function.
**Instead:** Use low-level `Server` with `call_tool()` handler that routes all tools through `OperationExecutor`.

### Anti-Pattern 2: Manual Tool Definitions

**What:** Writing 57 `types.Tool(...)` objects by hand like the component-search server does for 4 tools.
**Why bad:** Error-prone, will drift from schema, 57x the maintenance burden. The Pydantic schema already contains all field names, types, descriptions, and validation rules.
**Instead:** Generate tool definitions dynamically from `Operation.model_json_schema()` at startup.

### Anti-Pattern 3: Merged Server Binary

**What:** Adding editing tools to the existing `kicad-component-search` server.
**Why bad:** The component-search server has no concept of a project directory (it queries an external API). Adding one would break its simplicity. The two servers have completely different dependency trees (network client vs. file mutation engine). Merging creates an unnecessarily large attack surface.
**Instead:** Separate binary with separate entry point.

### Anti-Pattern 4: Exposing Executor Internals

**What:** Having the MCP server expose registry categories, IR types, or Transaction details to the AI client.
**Why bad:** These are implementation details. The AI client should only know about operations and their parameters. Leaking internals couples the MCP interface to the implementation.
**Instead:** The MCP server's interface is strictly: tool name = op_type, tool arguments = operation fields (minus op_type). All dispatch, IR construction, and transaction management is invisible to the client.

### Anti-Pattern 5: Per-Tool Handler Functions

**What:** Writing 57 individual handler functions in the MCP server, one per operation.
**Why bad:** Every handler would do the same thing: reconstruct the Operation envelope, validate it, call executor.execute(). This is 57 copies of the same 5-line function.
**Instead:** Single `call_tool()` handler that works for all 57 tools by reconstructing the envelope from the tool name.

## Scalability Considerations

| Concern | At 57 tools | At 100+ tools | Mitigation |
|---------|------------|---------------|------------|
| Tool listing response size | ~30KB JSON | ~50KB JSON | MCP protocol handles this fine |
| Schema generation time | <50ms (startup) | <100ms | One-time cost at server startup |
| Pydantic validation | <5ms per call | <10ms per call | Negligible vs. file I/O |
| Executor dispatch | O(1) dict lookup | O(1) dict lookup | Dict-based, no scalability concern |
| MCP client tool menu | 57 items is manageable | May need categorization | Not a concern at current scale |

## Build Order (Dependency-Aware)

```
Phase 1: Server Skeleton (no dependencies)
  [NEW] src/kicad_agent/mcp/edit_server.py
    - Server setup with lifespan (project dir resolution)
    - _build_tool_definitions() using Operation.model_json_schema()
    - call_tool() with envelope reconstruction + executor dispatch
    - Error handling with correlation IDs
    - _run_server() + main() entry point
  [MOD] pyproject.toml
    - Add: kicad-agent-edit = "kicad_agent.mcp.edit_server:main"
  Estimated: ~250 lines new, 1 line modified

Phase 2: Tool Annotations (depends on Phase 1)
  [MOD] src/kicad_agent/mcp/edit_server.py
    - Add _build_annotations() categorizing read-only vs destructive ops
    - Apply annotations during tool generation
  Estimated: ~30 lines modified

Phase 3: Context Tool (optional, depends on Phase 1)
  [MOD] src/kicad_agent/mcp/edit_server.py
    - Add get_project_context tool (read-only, wraps context.py)
  Estimated: ~20 lines added

Phase 4: Integration Tests (depends on Phase 1)
  [NEW] tests/test_mcp_edit_server.py
    - Test tool generation produces 57 tools
    - Test tool names match op_type values
    - Test envelope reconstruction
    - Test read-only annotations on validation ops
    - Test destructive annotations on remove ops
    - Test error handling paths
    - Test end-to-end: call_tool -> executor -> result
  Estimated: ~200 lines new
```

**Rationale for ordering:**
- Phase 1 is the core deliverable. It can be built and tested independently.
- Phase 2 is additive (annotations are optional in MCP spec).
- Phase 3 is a nice-to-have that adds project discovery capability.
- Phase 4 validates everything but depends on Phase 1 existing.

## Dependency Graph

```
pyproject.toml (entry point)
    |
    v
edit_server.py
    |-- imports from kicad_agent.ops.schema (Operation, get_operation_schema)
    |-- imports from kicad_agent.ops.executor (OperationExecutor)
    |-- imports from mcp SDK (types, Server, stdio_server)
    |
    +-- OperationExecutor (existing, no changes)
    |       |-- dispatches to 6 handler registries
    |       |-- wraps in Transaction for rollback
    |       |-- path confinement security check
    |       +-- returns standardized result dict
    |
    +-- get_operation_schema() (existing, no changes)
            |-- Pydantic model_json_schema()
            +-- returns JSON Schema with 57 oneOf variants
```

No existing code needs modification except `pyproject.toml`. The new server is purely additive.

## Security Considerations

The existing security mitigations in the operation layer carry through automatically:

| Mitigation | Where Enforced | MCP Layer Concern |
|------------|---------------|-------------------|
| Path traversal rejection | `TargetFile` validator in schema.py | None -- enforced before executor sees it |
| Absolute path rejection | `TargetFile` validator in schema.py | None |
| Path confinement | `OperationExecutor._base_dir` check | Project dir set at server startup |
| Unsafe character rejection | `_validate_safe_identifier()` in schema.py | None -- Pydantic validates |
| S-expression safety | `_validate_sexpr_safe_string()` in schema.py | None -- Pydantic validates |
| Null byte rejection | `TargetFile` validator in schema.py | None |
| String length limits | `Field(max_length=N)` on all fields | None -- Pydantic validates |

The MCP server adds one new security concern: **project directory confinement**. The `KICAD_PROJECT_DIR` environment variable must resolve to an actual directory. The server validates this at startup and refuses to start if invalid. All file operations are then relative to this directory.

## Sources

- Direct codebase analysis: `src/kicad_agent/mcp/server.py` (284 lines), `src/kicad_agent/mcp/tools.py` (336 lines)
- Operation schema: `src/kicad_agent/ops/schema.py` (433 lines), 14 sub-schema modules
- Operation executor: `src/kicad_agent/ops/executor.py` (1090 lines), 62 handler registrations across 6 registries
- MCP Python SDK v1.12.3: `types.Tool` with `annotations` param, `types.ToolAnnotations` with `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`
- MCP specification: tool annotations protocol (verified SDK support)
- pyproject.toml entry point pattern (existing: `kicad-component-search`)
