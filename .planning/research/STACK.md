# Technology Stack -- MCP Operations Server

**Project:** kicad-agent -- MCP server exposing all 57 operations as tools
**Milestone:** mcp-ops-server
**Researched:** 2026-05-29
**Confidence:** HIGH

## Executive Summary

The new MCP operations server requires **zero new dependencies**. Everything needed is already installed and verified. The `mcp` package (1.12.3) provides both low-level `Server` (used by the existing component-search server) and `FastMCP` (higher-level convenience). The low-level `Server` approach is recommended here because it gives full control over tool schema generation from Pydantic `model_json_schema()` output, which is critical for dynamically registering 57 tools from the existing operation schema classes.

The architecture is: iterate 57 Pydantic op classes from the `Operation` discriminated union, call `model_json_schema()` on each to produce MCP-compatible `inputSchema`, register as `mcp.types.Tool` objects, and dispatch `call_tool` by `op_type` string through `OperationExecutor.execute()`. The synchronous executor is wrapped in `asyncio.to_thread()`, matching the existing server pattern.

## Recommended Stack

### Core Framework (No Changes)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `mcp` (low-level Server) | 1.12.3 | MCP protocol server, stdio transport | Existing proven pattern in `server.py`. Gives direct control over `types.Tool` construction from Pydantic schemas. `FastMCP` auto-generates inputSchema from function signatures -- wrong fit when schemas already exist in Pydantic models. |
| `mcp.types.Tool` | 1.12.3 | Tool definition objects | Constructor: `(name, description, inputSchema)`. Accepts Pydantic `model_json_schema()` output directly -- verified. All 57 schemas produce valid JSON Schema objects with `type: "object"`, `properties`, and optional `$defs`. |
| `mcp.server.stdio.stdio_server` | 1.12.3 | stdio transport | Same as existing component-search server. Both servers run as CLI entry points, Claude Code connects via stdio. No HTTP needed. |
| Pydantic v2 | 2.12.5 | Schema generation for MCP tools | `model_json_schema()` on each of the 57 op classes produces MCP-compatible inputSchema. Verified: all 57 schemas generate without errors, include `description`, `properties`, `required`, and `$defs` where needed. |
| `OperationExecutor` | existing | Dispatch operations to handlers | Already handles all 57 op_types via registry pattern. Takes `Operation` (validated), returns `dict[str, Any]`. Synchronous -- needs `asyncio.to_thread()` wrapping. |

### Dynamic Tool Registration Pattern

| Component | Source | Role |
|-----------|--------|------|
| `Operation.model_fields['root'].annotation` | `schema.py` | Union type containing all 57 op classes. `typing.get_args()` extracts them as a list. Verified: returns exactly 57 classes. |
| `cls.model_json_schema()` | Pydantic v2 | Produces JSON Schema for each op class. Includes `op_type` as a `const` field, `description` from docstrings, all properties with types/constraints. |
| `mcp.types.Tool(name=..., description=..., inputSchema=schema)` | mcp 1.12.3 | Constructs MCP tool definition. Verified compatible with Pydantic schema output. |
| `asyncio.to_thread(executor.execute, op)` | stdlib | Wraps synchronous executor in async. Same pattern as existing `server.py` line 163. |

### Infrastructure (No Changes)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `pyproject.toml` entry point | existing | CLI registration | Add new entry: `kicad-ops-server = "kicad_agent.mcp.ops_server:main"` alongside existing `kicad-component-search`. |
| `asyncio` | stdlib | Event loop management | `asyncio.run()` for entry point, `asyncio.to_thread()` for sync executor wrapping. Same as existing server. |
| `json.dumps()` | stdlib | Response serialization | Executor returns dicts. Serialize to JSON string for `TextContent`. Same as existing server. |

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| MCP framework | Low-level `Server` | `FastMCP` | FastMCP auto-generates inputSchema from function type hints. We have 57 pre-built Pydantic schemas. Using FastMCP would require either: (a) writing 57 wrapper functions with type hints matching each schema, or (b) using `FastMCP.add_tool(fn)` where `fn` still needs manual schema override. Low-level Server gives direct control and is the proven pattern in this codebase. |
| Transport | stdio | SSE / streamable-http | Both servers are consumed by Claude Code (local CLI). stdio is simpler, proven, and matches the existing component-search server. HTTP transports add complexity (server lifecycle, port management) with no benefit for local-only usage. streamable-http is available in mcp 1.12.3 but unnecessary here. |
| Tool registration | Dynamic from Pydantic | Manual 57-tool list | Manual registration would mean maintaining tool definitions in two places (Pydantic schemas AND MCP tool list). Dynamic generation from `model_json_schema()` is DRY -- schema is the single source of truth. Verified: all 57 schemas generate correctly. |
| Response format | `TextContent` with JSON | Structured output (`outputSchema`) | mcp 1.12.3 supports `outputSchema` on tools, but the executor returns heterogeneous dict shapes (each operation has different result fields). JSON in TextContent is simpler, proven in the existing server, and allows flexible response shapes without maintaining 57 output schemas. |

## What NOT to Add

| Avoid | Why |
|-------|-----|
| `FastMCP` import | Low-level Server already proven in codebase. FastMCP would not simplify the 57-tool dynamic registration case. |
| New pip dependencies | Everything needed is installed: `mcp>=1.0.0` (1.12.3), `pydantic>=2.0` (2.12.5), `asyncio` (stdlib). |
| SSE or HTTP transport | stdio is the right transport for CLI tools consumed by Claude Code. No web serving needed. |
| Separate process for each operation | All 57 tools run in one MCP server process. `OperationExecutor` handles dispatch internally. |
| Tool discovery protocol | MCP's `list_tools` handler returns all 57 tools. No separate discovery needed. |
| Output schema per tool | Executor results are heterogeneous. `TextContent` with JSON is flexible enough. |
| Rate limiting | The existing server rate-limits EasyEdaClient API calls. The operations server wraps local file I/O -- no rate limiting needed. |
| Caching layer | Operations are mutations, not reads. Caching is inappropriate. |
| Authentication/authorization | Local CLI tool, not network-accessible. Security is handled by path confinement in `OperationExecutor` (T-24-01). |

## New Files Needed

| File | Purpose | Pattern Follows |
|------|---------|----------------|
| `src/kicad_agent/mcp/ops_server.py` | New MCP server: dynamic tool registration from Pydantic schemas, `OperationExecutor` dispatch | `src/kicad_agent/mcp/server.py` (existing component-search server) |

## pyproject.toml Changes

One new entry point:

```toml
[project.scripts]
kicad-agent = "kicad_agent.cli:main"
kicad-component-search = "kicad_agent.mcp.server:main"
kicad-ops-server = "kicad_agent.mcp.ops_server:main"  # NEW
```

No new dependencies. The `mcp` optional dependency group already exists (`mcp>=1.0.0`).

## Installation

```bash
# Already installed -- no action needed
pip install -e ".[mcp]"

# Verify
kicad-ops-server --help  # After implementation
```

## Architecture of ops_server.py

```
Module structure (single file, ~200 lines):

1. IMPORTS
   - mcp.types, mcp.server.Server, mcp.server.stdio
   - Operation, OperationExecutor from kicad_agent
   - typing.get_args for union extraction

2. DYNAMIC TOOL REGISTRATION
   _build_tools() -> list[types.Tool]:
     - Extract 57 op classes from Operation.model_fields['root'].annotation
     - For each: cls.model_json_schema() -> types.Tool(name=op_type, ...)
     - Return list

3. SERVER LIFESPAN
   - Create OperationExecutor(base_dir=Path.cwd())
     OR accept base_dir via environment variable / CLI arg
   - Yield {"executor": executor}

4. list_tools HANDLER
   - Return pre-built _TOOLS list

5. call_tool HANDLER
   - Validate arguments against op schema (Operation.model_validate)
   - asyncio.to_thread(executor.execute, op)
   - Return TextContent with JSON result

6. ENTRY POINT
   main() -> asyncio.run(_run_server())
```

## Key Design Decisions

### D-OPS-1: Low-level Server over FastMCP
**Why:** The existing component-search server uses low-level `Server` and it works. FastMCP's strength is auto-generating schemas from function signatures, which is the opposite of what we need (we have schemas, need to register them). Low-level Server gives direct control.

### D-OPS-2: base_dir from Environment Variable
**Why:** The executor needs a `base_dir` to resolve relative `target_file` paths. For MCP servers, the working directory at launch time is the project root. Use `Path.cwd()` as default, with `KICAD_PROJECT_DIR` environment variable override for explicit configuration. This avoids adding a parameter to the MCP protocol.

### D-OPS-3: Single File, Not Package
**Why:** The new server is ~200 lines. The existing `server.py` is 283 lines and is a single file. No need for a sub-package. If it grows beyond 400 lines, extract tool building into `ops_tools.py`.

### D-OPS-4: Reuse Pydantic Validation, Don't Re-validate
**Why:** The `call_tool` handler should call `Operation.model_validate({"root": arguments})` which runs all field validators (including security validators like TargetFile path traversal rejection). This gives us Pydantic validation for free, including the `op_type` discriminator routing. Do NOT manually parse arguments.

### D-OPS-5: Error Handling Mirrors Existing Server
**Why:** Use the same error pattern as `server.py` lines 249-259: `ValidationError`, `ValueError`, and generic `Exception` with correlation ID. Consistency across both MCP servers.

## Sources

- Live inspection: `mcp` 1.12.3 installed, `mcp.types.Tool` constructor signature verified
- Live inspection: Pydantic 2.12.5 `model_json_schema()` output verified for all 57 operations
- Live inspection: `Operation.model_fields['root'].annotation` returns UnionType with 57 members
- Existing codebase: `src/kicad_agent/mcp/server.py` (283 lines, proven pattern)
- Existing codebase: `src/kicad_agent/ops/executor.py` (1090 lines, all 57 handlers registered)
- Existing codebase: `src/kicad_agent/ops/schema.py` (433 lines, discriminated union)

---
*Stack research for: kicad-agent milestone mcp-ops-server*
*Researched: 2026-05-29*
