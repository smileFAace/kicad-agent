# Project Research Summary

**Project:** kicad-agent MCP Operations Server
**Domain:** MCP tool server exposing 57 KiCad editing operations to LLM clients
**Researched:** 2026-05-29
**Confidence:** HIGH

## Executive Summary

This milestone adds a new MCP server binary (`kicad-agent-edit`) that exposes kicad-agent's 57 atomic KiCad editing operations as individually named MCP tools. The architecture is straightforward: iterate the Pydantic `Operation` discriminated union at startup, generate 57 `mcp.types.Tool` definitions via `model_json_schema()`, and dispatch all calls through the existing `OperationExecutor` with `asyncio.to_thread()` wrapping. Zero new dependencies are required -- everything is already installed and verified.

The recommended approach is a **separate server binary** using the low-level `mcp.server.Server` API (matching the existing component-search server pattern), with **flat 57-tool registration** (not categorized dispatch). Flat registration gives the LLM unambiguous tool names and specific input schemas per operation, maximizing tool-selection accuracy. The total new code is approximately 250 lines in one new file (`mcp/edit_server.py`) plus one entry point in `pyproject.toml`.

The key risks are: (1) synchronous executor blocking the async event loop, (2) error responses never setting `isError=True`, (3) path security scope when `base_dir` defaults to `Path.cwd()`, and (4) 68KB of tool schemas consuming LLM context window. All four are addressable in the first implementation phase with concrete prevention strategies.

## Key Findings

### Recommended Stack

No new dependencies. The `mcp` package (1.12.3) provides the low-level `Server` API. Pydantic v2 (2.12.5) handles schema generation. `asyncio.to_thread()` bridges the sync executor. The existing `OperationExecutor` and `Operation` discriminated union are imported unchanged.

**Core technologies:**
- `mcp.server.Server` (low-level) -- protocol server with full control over `types.Tool` construction from Pydantic schemas
- Pydantic v2 `model_json_schema()` -- generates MCP-compatible `inputSchema` for each of the 57 operations
- `asyncio.to_thread()` -- wraps synchronous `OperationExecutor.execute()` without blocking the event loop
- `mcp.server.stdio` -- stdio transport, matching existing component-search server

### Expected Features

**Must have (table stakes -- Phase 1):**
- All 57 operations as individual MCP tools (TS-1) -- flat registration, dynamic generation from Pydantic schemas
- Base directory configuration (TS-5) -- require `KICAD_PROJECT_DIR`, validate on startup
- Project context discovery tool (TS-2) -- wraps existing `render_project_context()`
- Operation listing tool (TS-3) -- condensed categorical view of all 57 tools
- Structured error responses (D-3) -- `CallToolResult(isError=True)` with repair hints

**Should have (Phase 2):**
- ERC/DRC convenience tools (TS-4) -- wrap `kicad-cli sch erc` and `kicad-cli pcb drc`
- Pre/post validation hooks (D-4) -- automatic ERC/DRC after mutation operations
- Operation history and undo (D-6) -- session-scoped, uses Transaction system
- Tool description quality pass -- distinguishing descriptions for LLM selection accuracy
- PID lock file -- prevent concurrent server instances on same project

**Defer (Phase 3+):**
- MCP Resources for file content (D-1)
- Batch operation execution (D-2)
- Sampling-assisted operations (D-5)

### Architecture Approach

One new file (`mcp/edit_server.py`, ~250 lines) implements the server as a separate binary from the existing component-search server. Tool definitions are generated dynamically from `Operation.model_json_schema()` at startup. All `call_tool` invocations route through a single handler that reconstructs the `Operation` envelope, validates via Pydantic, and dispatches through `OperationExecutor.execute()`.

**Major components:**
1. `mcp/edit_server.py` -- NEW: server skeleton, dynamic tool generation, call_tool dispatch, error handling
2. `pyproject.toml` -- MODIFIED: add `kicad-agent-edit` entry point (1 line)
3. `ops/schema.py` -- IMPORTED: `Operation` discriminated union (no changes)
4. `ops/executor.py` -- IMPORTED: `OperationExecutor` with 6 handler registries (no changes)

### Critical Pitfalls

1. **Sync executor blocks async event loop** -- Wrap every `executor.execute()` in `asyncio.to_thread()`. No exceptions.
2. **Error responses never set isError=True** -- Use `CallToolResult(isError=True, content=[...])` for all error paths, not plain `[TextContent]`.
3. **Path security scope too broad** -- Require explicit `KICAD_PROJECT_DIR`, validate directory contains `.kicad_pro` file, do not default to `Path.cwd()`.
4. **68KB tool schemas consume context** -- Strip verbose fields from schemas, compress shared `$defs`, test with target clients before optimizing further.
5. **Large KiCad files produce multi-MB responses** -- Cap response size at 50KB, summarize instead of dumping, strip internal fields.

## Implications for Roadmap

### Phase 1: Core Server Skeleton
**Rationale:** Foundation that everything else depends on. Must get async wrapping, error handling, path security, and schema generation right from the start.
**Delivers:** Working MCP server with 57 tools, base_dir configuration, structured errors, response size capping.
**Addresses:** TS-1, TS-2, TS-3, TS-5, D-3
**Avoids:** Pitfalls 1, 2, 4, 5, 8, 9
**Estimated:** 4-5 days

### Phase 2: Validation, Hardening, and Description Quality
**Rationale:** Safety nets and polish after the core server works. Add validation wrappers, concurrent access prevention, and tool descriptions that help the LLM select correctly.
**Delivers:** ERC/DRC tools, pre/post validation hooks, operation history/undo, PID lock file, quality tool descriptions.
**Addresses:** TS-4, D-4, D-6
**Avoids:** Pitfalls 3, 7, 10
**Estimated:** 3-5 days

### Phase 3: Advanced Features (Optional)
**Rationale:** Nice-to-have features that elevate the server from functional to excellent. Only build if Phase 1 and 2 prove stable.
**Delivers:** MCP Resources, batch operations, sampling-assisted operations.
**Addresses:** D-1, D-2, D-5
**Estimated:** 7-11 days

### Phase Ordering Rationale

- Phase 1 must come first because all other features depend on the core server being operational
- Phase 2 comes second because validation hooks and error descriptions require the server to exist
- Strict separation (250 new lines, 1 modified line, zero changes to existing code) minimizes risk to the working component-search server
- Pitfalls 1-5 all surface in Phase 1, so they must be addressed there

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1:** Schema normalization for MCP client compatibility -- need to test `$defs`/`$ref` handling across Claude Code, Cursor, and other target clients
- **Phase 2:** Tool description optimization for LLM selection accuracy -- iterative testing required

Phases with standard patterns (skip research-phase):
- **Phase 1 core:** Server skeleton follows exact pattern of existing `server.py` (284 lines, proven)
- **Phase 1 dispatch:** `OperationExecutor` dispatch is unchanged, well-tested

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All dependencies verified installed, versions confirmed, schema generation tested on all 57 ops |
| Features | HIGH | Feature scope derived directly from existing codebase (57 ops already implemented), not speculative |
| Architecture | HIGH | Follows proven pattern from existing component-search server, single new file, minimal changes |
| Pitfalls | HIGH | All pitfalls identified from MCP SDK source code, existing server analysis, and live schema measurements |

**Overall confidence:** HIGH

### Gaps to Address

- **Schema normalization strategy:** Pydantic `$defs`/`$ref` may not render correctly in all MCP clients. Need empirical testing with Claude Code and Cursor during Phase 1 planning. Prepare a `_normalize_schema()` fallback that flattens references.
- **Response size thresholds:** 50KB cap is a guess. Need to measure actual response sizes with real KiCad files (Arduino_Mega fixture) and adjust thresholds based on observed LLM handling.

## Sources

### Primary (HIGH confidence)
- Live codebase inspection: `mcp` 1.12.3 SDK, `mcp.types.Tool` constructor, `mcp.types.ToolAnnotations` fields
- Live codebase inspection: Pydantic 2.12.5 `model_json_schema()` output verified for all 57 operations
- Existing codebase: `src/kicad_agent/mcp/server.py` (284 lines, proven pattern)
- Existing codebase: `src/kicad_agent/ops/executor.py` (1090 lines, all handlers)
- Existing codebase: `src/kicad_agent/ops/schema.py` (433 lines, discriminated union)
- MCP Specification: modelcontextprotocol.io tools concept, error handling, annotations

### Secondary (MEDIUM confidence)
- MCP Filesystem Server (reference implementation) -- flat registration pattern with 11 tools
- Live measurement: 57 tool schemas total 67,992 bytes, range 456-5,411 bytes per tool

---
*Research completed: 2026-05-29*
*Ready for roadmap: yes*
