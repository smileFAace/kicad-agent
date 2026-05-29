# Domain Pitfalls -- MCP Operations Server

**Domain:** Exposing kicad-agent's 57 synchronous operations as an MCP tool server for LLM consumption
**Researched:** 2026-05-29
**Context:** The existing kicad-agent has 57 atomic operations (Pydantic schemas, OperationExecutor dispatch, IR mutation pipeline) all purely synchronous. This document covers pitfalls SPECIFIC to wrapping this synchronous library as an MCP tool server.
**Confidence:** HIGH (verified against MCP Python SDK 1.12.3 source, existing server.py patterns, live schema measurements)

---

## Critical Pitfalls

Mistakes that cause rewrites or major issues.

---

### Pitfall 1: Synchronous OperationExecutor Blocks the Async MCP Event Loop

**What goes wrong:**
`OperationExecutor.execute()` is a synchronous method that performs file I/O (read KiCad file, parse S-expressions into IR, mutate IR, serialize IR, write file back). A typical operation takes 10-200ms. If called directly from the MCP `call_tool` handler without `asyncio.to_thread()`, it blocks the async event loop for that entire duration. During blocking, the MCP server cannot respond to `list_tools` requests, `ping` health checks, or any other tool calls. The client perceives this as a frozen server and may timeout the connection.

**Why it happens:**
The developer sees that `call_tool` is an `async def` and writes `result = executor.execute(op)` without wrapping. Python does not warn about blocking calls inside async functions. The server appears to work for single requests but hangs under concurrent load or when the client sends a pipelined request (list_tools + call_tool in quick succession).

**Consequences:**
- MCP client timeouts on operations that take >30 seconds (large PCB files)
- Server becomes unresponsive to health checks, client assumes server crashed
- JSON-RPC message queue fills up while event loop is blocked
- Debugging is difficult because the issue only manifests under concurrent load

**Prevention:**
1. Wrap EVERY `executor.execute()` call in `asyncio.to_thread(executor.execute, op)` -- same pattern as existing `server.py` line 170
2. Do NOT use `asyncio.to_thread()` for validation-only code (Pydantic `model_validate` is fast and can stay on the event loop)
3. Test with a concurrent load: send 5 operations simultaneously, verify all complete without timeout
4. Measure blocking time: log `time.monotonic()` before and after `asyncio.to_thread()`, flag anything over 5 seconds

**Detection:**
If the MCP client reports timeouts on `tools/call` requests, the executor is blocking the event loop. Add `logging.debug("execute start")` / `logging.debug("execute end")` around the `to_thread` call to verify it is actually being awaited.

**Phase to address:** First implementation phase -- the async wrapping must be correct from the first line of `call_tool`.

---

### Pitfall 2: Error Responses Never Set isError=True, Breaking MCP Client Error Handling

**What goes wrong:**
MCP clients (Claude Desktop, Cursor, etc.) use the `CallToolResult.isError` field to determine whether a tool call succeeded or failed. When `isError=True`, the client typically displays the error to the user and may retry or abort. When `isError=False` (or absent), the client treats the response as a successful result and may pass it to the LLM as-is.

The existing `server.py` (line 247-259) returns `[types.TextContent(type="text", text=f"Error: {e}")]` for all errors. The MCP Python SDK wraps this in `CallToolResult(isError=False, content=[...])`. The client sees a "successful" response containing the error text. The LLM receives error text as if it were a valid operation result, which confuses its reasoning about what happened.

**Why it happens:**
The low-level `Server.call_tool` decorator in MCP SDK 1.12.3 auto-wraps the returned content in `CallToolResult(isError=False)`. To signal an error, the handler must explicitly return `types.CallToolResult(isError=True, content=[...])` instead of just `[types.TextContent(...)]`. The existing component-search server never does this.

**Consequences:**
- LLM receives error messages as successful tool results and tries to reason about them as data
- Client-side error handling (retry logic, error display) is bypassed
- Validation errors ("target_file contains unsafe characters") appear as successful text output
- Makes debugging harder because no tool call is ever "failed" from the client perspective

**Prevention:**
1. For validation errors (Pydantic `ValidationError`, `ValueError`): return `CallToolResult(isError=True, content=[TextContent(type="text", text=error_message)])`
2. For executor errors (file not found, security violations): return `CallToolResult(isError=True, content=[TextContent(type="text", text=error_message)])`
3. For internal/unexpected errors: return `CallToolResult(isError=True, content=[TextContent(type="text", text=f"Internal error (ref: {correlation_id})")])`
4. Only return `isError=False` (or just `[TextContent]`) for genuinely successful operation results
5. Write a helper function `_error_response(message: str, is_error: bool = True) -> CallToolResult` to enforce consistency

**Detection:**
Log every `call_tool` response with its `isError` status. After testing, grep logs for "isError=False" entries that contain error-related text (e.g., "not found", "validation", "error").

**Phase to address:** First implementation phase -- build the error response helper before writing any tool handlers.

---

### Pitfall 3: 57 Individual Tool Schemas Sum to 68KB -- Client Context Window Overhead

**What goes wrong:**
MCP clients receive the complete tool list (all 57 tools with their inputSchemas) during initialization and include it in every LLM context window. The combined schema size is 68KB of JSON. At 4 characters per token (rough estimate), this is ~17,000 tokens of context overhead before any user request. For operations-heavy sessions, the LLM spends significant context budget on tool definitions it may never use.

Individual tool schemas range from 456 bytes (`navigate_hierarchy`) to 5,411 bytes (`create_footprint`), averaging 1,192 bytes each. The full `Operation` discriminated union schema (all 57 in one object) is 67.9KB with 61 `$defs` entries -- even larger.

**Why it happens:**
Each Pydantic `model_json_schema()` call produces a complete JSON Schema with `properties`, `required`, field constraints (`min_length`, `max_length`, `gt`, `le`), `$defs` for nested types (PositionSpec, PropertySpec, PinSpec, FootprintPadSpec), and `description` strings from docstrings. This is thorough but verbose.

**Consequences:**
- LLM context window has 17K tokens consumed by tool definitions before the conversation starts
- For models with 128K context, this is 13% overhead before any work begins
- For smaller models (32K context), this is 53% overhead -- leaving barely enough room for conversation
- Slower inference because the model processes all 57 tool definitions for every request
- Client-side performance degradation loading and parsing 68KB of JSON on initialization

**Prevention:**
1. **Strip verbose descriptions from schemas before registration**: Remove `$defs` descriptions and long field descriptions. Keep only field names, types, and constraints.
2. **Compress shared type definitions**: PositionSpec, PropertySpec, and PinSpec are repeated in every operation that uses them. Define them once in a shared `$defs` block instead of inlining per-tool.
3. **Consider tool grouping**: Register high-level tool groups (e.g., `schematic_operation`, `pcb_operation`) with an `op_type` discriminator, instead of 57 individual tools. This reduces the tool count from 57 to 4-8 but requires the client to discover operations within each group.
4. **Lazy tool registration**: Use MCP's `notifications/tools/list_changed` to register tools on-demand. Start with 0 tools, register only tools the client actually uses.
5. **Measure actual impact**: Test with target MCP clients (Claude Code, Cursor) and measure context window consumption. Do not optimize prematurely if clients handle 68KB without issue.

**Detection:**
Log the total JSON size of `list_tools` responses. If it exceeds 100KB, the overhead is likely impacting client performance.

**Phase to address:** First implementation phase for basic schema registration. Optimization (compression, grouping) in a follow-up phase if measurements show impact.

---

### Pitfall 4: Path Security Has Two Layers That Must Both Be Enforced

**What goes wrong:**
The MCP server receives file paths from two sources: (1) the `base_dir` configuration (where the server looks for files), and (2) the `target_file` field in each operation's JSON arguments. The existing `TargetFile` validator in `schema.py` (line 143-159) rejects absolute paths, `..` traversal, null bytes, and non-KiCad extensions. The `OperationExecutor` (line 624-627) additionally checks that the resolved path stays within `base_dir`.

But the MCP server introduces a NEW attack surface: the `base_dir` itself. If `base_dir` is configured via environment variable (`KICAD_PROJECT_DIR`) or CLI argument, a compromised or confused LLM could potentially influence the server to use a different `base_dir`, gaining access to files outside the intended project. Additionally, the MCP server's working directory at launch time becomes the default `base_dir` -- if the server is started from `/` or the user's home directory, the executor gains access to all KiCad files on the system.

**Why it happens:**
The existing `OperationExecutor` trusts its `base_dir` -- it only validates that `target_file` resolves within it. The MCP server sets `base_dir = Path.cwd()` by default, which depends on where the server process is launched. Claude Code launches MCP servers from its own working directory, which may or may not be the KiCad project directory.

**Consequences:**
- If launched from home directory: operations can edit ANY KiCad file in the user's home directory
- If `KICAD_PROJECT_DIR` is not set and CWD is wrong: operations fail or edit wrong files
- Path confinement check passes for any file under CWD, which may be too broad
- Security model assumes `base_dir` is the project root, but MCP server has no way to verify this

**Prevention:**
1. **Require explicit `base_dir` configuration**: Do NOT default to `Path.cwd()`. Instead, require `KICAD_PROJECT_DIR` environment variable. Fail fast with a clear error if not set.
2. **Validate `base_dir` on startup**: Check that the configured directory contains at least one `.kicad_pro` file (indicating a valid KiCad project). Reject directories without a project file.
3. **Log the resolved `base_dir` on startup** so operators can verify the scope
4. **Keep the existing TargetFile validator** -- it provides defense-in-depth even with correct `base_dir`
5. **Keep the executor's path confinement check** -- it provides a second layer of defense
6. **Test the security boundary**: attempt operations with `target_file="../../../etc/passwd"` (must fail at Pydantic validation), `"target_file": "/absolute/path.kicad_sch"` (must fail at TargetFile validator), and a valid path outside the project (must fail at executor confinement)

**Detection:**
After server startup, log `base_dir` resolved path. If it is `/`, home directory, or any path without a `.kicad_pro` file, the configuration is wrong.

**Phase to address:** First implementation phase -- security boundaries must be established before any tool handlers are written.

---

### Pitfall 5: Large KiCad Files Produce Multi-Megabyte JSON Responses

**What goes wrong:**
A typical `.kicad_pcb` file for a real board is 500KB to 10MB of S-expression text. When an operation returns results that include parsed file content (e.g., `query_connectivity` returning all net information, or `validate_schematic` returning all ERC violations with positions), the JSON response can be several megabytes. MCP clients may have response size limits, and the LLM context window cannot meaningfully consume multi-MB responses.

The `OperationExecutor.execute()` returns `dict[str, Any]`, which is serialized to JSON in the MCP handler. For operations that return file content or extensive analysis results, this dict can grow very large.

**Why it happens:**
The executor returns whatever the handler produces. Handlers are designed for programmatic consumption (other Python code), not LLM consumption. A `validate_schematic` handler might return every violation with full context (surrounding lines, pin positions, net names) because downstream code expects it. The MCP server passes this through without filtering.

**Consequences:**
- MCP client receives a response too large to process, truncates or errors
- LLM context window fills with raw file data, leaving no room for reasoning
- Response serialization itself takes significant time (JSON encoding 5MB of dicts)
- Network/transport overhead for large responses over stdio is minimal but still measurable

**Prevention:**
1. **Cap response size**: Add a maximum response size (e.g., 50KB JSON). If the serialized result exceeds this, truncate with a summary: `"result_truncated": true, "total_items": 1234, "returned_items": 50`
2. **Summarize, don't dump**: For query operations, return summary statistics instead of full data. E.g., `query_connectivity` should return `{"nets": 42, "connected_pads": 380, "unconnected_pads": 5}` not the full net list
3. **Paginate large results**: Add `offset` and `limit` parameters to query operations. Return results in pages of 50-100 items.
4. **Strip verbose fields**: Remove internal fields (UUIDs, raw S-expressions, internal IDs) from MCP responses. The LLM does not need UUIDs to reason about connectivity.
5. **Test with real files**: Use the Arduino_Mega test fixture (which is a real schematic) to measure response sizes for all 57 operations.

**Detection:**
Log the serialized JSON size for every tool response. Flag responses over 50KB as warnings, over 500KB as errors.

**Phase to address:** First implementation phase for basic size capping. Pagination and summarization can come in follow-up phases.

---

## Moderate Pitfalls

---

### Pitfall 6: MCP Clients May Have Tool Count Limits

**What goes wrong:**
Registering 57 tools means the MCP client receives a `tools/list` response with 57 entries. While the MCP specification does not define a maximum tool count, individual clients may have practical limits. Claude Desktop and Claude Code have been observed to handle 50+ tools without issue, but other clients (Cursor, Windsurf, custom integrations) may truncate the tool list, show only the first N tools in their UI, or fail to process the full list.

**Why it happens:**
MCP is a young protocol. Client implementations vary in maturity. Some clients may load all tools into a dropdown or sidebar that has rendering limits. Others may have hardcoded limits on how many tool definitions they pass to the LLM's system prompt.

**Consequences:**
- Some operations invisible to the LLM (client dropped them from the tool list)
- Confusing behavior where some operations work and others silently fail
- No error message from the client -- it just truncates

**Prevention:**
1. **Test with target clients early**: Register all 57 tools, verify the client sees all of them via its UI or API
2. **Group tools by domain if needed**: If a client has a limit, register domain-level tools (e.g., `schematic_edit`, `pcb_edit`) with an `op_type` parameter. This reduces 57 tools to 6-8 grouped tools.
3. **Use MCP tool annotations to help clients prioritize**: Set `readOnlyHint=True` on query/validation operations so clients can deprioritize them in UI
4. **Support `notifications/tools/list_changed`**: If the client signals support, register tools on-demand rather than all at startup

**Detection:**
After registering all 57 tools, query `tools/list` from the client side and count the response. If fewer than 57, the client truncated.

**Phase to address:** First implementation phase for registration. Grouping as a fallback in a follow-up phase if clients have limits.

---

### Pitfall 7: Concurrent Edits From Multiple MCP Clients Corrupt Files

**What goes wrong:**
MCP servers using stdio transport are typically one-server-per-client. But if the same project is opened by two MCP clients (e.g., Claude Code in one terminal and Cursor in another, both configured to use kicad-agent), two MCP server processes run concurrently against the same KiCad files. The `OperationExecutor` has no inter-process locking -- it uses `Transaction` objects that snapshot files for in-process rollback, but they do not prevent concurrent writes from another process.

Client A reads `motor-driver.kicad_sch`, applies mutation, writes back. Client B had already read the same file, applies its own mutation, writes back -- overwriting Client A's changes. The file is now corrupted: Client A's mutation is lost, Client B's mutation is applied to a stale base.

**Why it happens:**
The `Transaction` class in `ir/transaction.py` uses `fcntl.flock` for file locking, but `flock` on many systems (macOS, Linux NFS) is advisory, not mandatory. Two processes that both use `flock` will respect each other's locks, but if one process does not use `flock` (or uses it incorrectly), the lock provides no protection. Additionally, the lock is held only during the write phase, not during the read-parse-mutate phase -- a classic TOCTOU race.

**Consequences:**
- Silent data loss: one client's edits are overwritten by another
- File corruption if both writes interleave at the OS level (partial writes)
- Extremely difficult to reproduce and debug -- depends on exact timing
- KiCad GUI also accesses these files, adding a third concurrent actor

**Prevention:**
1. **Use a PID lock file**: On startup, write a `.kicad-agent.lock` file in the project directory containing the server's PID. If the file exists and the PID is alive, refuse to start a second server.
2. **Advisory: log a warning**: If the server detects another kicad-agent MCP server process for the same project, log a warning. The user may have a legitimate reason for multiple servers (unlikely but possible).
3. **Document the single-server constraint**: In README and configuration docs, state that only one MCP server should be active per KiCad project at a time.
4. **Do NOT implement distributed locking**: It adds complexity (lock expiration, deadlock detection) that is not justified for a local CLI tool. PID lock file is sufficient.
5. **Test the lock**: Start two MCP servers for the same project, verify the second one refuses or warns.

**Detection:**
Check for `.kicad-agent.lock` file in project directory. If it exists and the PID is alive, another server is running.

**Phase to address:** Second implementation phase (after basic server works). Not blocking for initial development.

---

### Pitfall 8: Dynamic Schema Generation Can Produce Invalid inputSchema at Runtime

**What goes wrong:**
The plan is to generate 57 MCP tool definitions dynamically from Pydantic `model_json_schema()` output. But Pydantic JSON Schema output is not always a strict subset of what MCP's `inputSchema` field accepts. Specifically:

- Pydantic generates `$defs` sections with shared type definitions. The MCP `inputSchema` field is documented as accepting "a JSON Schema object", but some MCP clients may not handle `$defs`/`$ref` correctly.
- Pydantic includes `"title"` and `"default"` fields that are valid JSON Schema but may confuse some MCP clients.
- Literal type fields (like `op_type: Literal["add_component"] = "add_component"`) generate `{"enum": ["add_component"]}` or `{"const": "add_component"}` depending on Pydantic version. The `const` form may not be recognized by all MCP client schema parsers.
- The `$defs` block for PositionSpec references (`{"$ref": "#/$defs/PositionSpec"}`) may not resolve correctly if the MCP client does not handle JSON Schema references.

**Why it happens:**
JSON Schema is a large specification with many features. MCP clients may implement only a subset. Pydantic generates full JSON Schema output including features that edge-case clients might not support.

**Consequences:**
- Tool registration succeeds (MCP server accepts any `inputSchema` dict) but the client cannot parse the schema
- Client shows garbled or missing parameter fields for some tools
- Client-side validation rejects valid operation arguments because it misinterprets the schema
- Failures are client-specific and hard to reproduce

**Prevention:**
1. **Test schema generation early**: Run `model_json_schema()` on all 57 op classes, register them as MCP tools, verify the client shows them correctly.
2. **Flatten `$refs` if needed**: If a client cannot handle `$defs`/`$ref`, inline the referenced definitions directly into each property. This increases schema size but removes the reference resolution requirement.
3. **Strip `const` fields**: Replace `"const": "add_component"` with `"enum": ["add_component"]` for broader compatibility.
4. **Remove unnecessary fields**: Strip `title`, `$id`, `default` from the schema before registering. Keep only `type`, `properties`, `required`, `description`, and constraint keywords.
5. **Schema normalization function**: Write a `_normalize_schema(schema: dict) -> dict` function that strips or transforms incompatible features before passing to `types.Tool(inputSchema=...)`.

**Detection:**
After registering tools, query the client's representation of tool parameters. If any tool shows missing or garbled parameters, the schema has compatibility issues.

**Phase to address:** First implementation phase -- schema generation is foundational.

---

## Minor Pitfalls

---

### Pitfall 9: MCP Server base_dir Must Match KiCad Project Root, Not CWD

**What goes wrong:**
This is related to Pitfall 4 but concerns the developer experience. If the MCP server uses `Path.cwd()` as `base_dir`, and the server is launched by Claude Code (which sets CWD to the project root), it works. But if the server is launched manually or by another tool, CWD might be the user's home directory or the kicad-agent source directory. Operations will either fail (no KiCad files found) or succeed against the wrong files.

**Why it happens:**
MCP stdio servers are launched by the MCP client, and the client sets the working directory. Claude Code sets it to the project root. Other clients may set it differently. Manual testing (`python3 -m kicad_agent.mcp.ops_server`) inherits the shell's CWD.

**Prevention:**
1. Log the resolved `base_dir` and CWD at startup
2. Verify `base_dir` contains a `.kicad_pro` file before accepting operations
3. Support CLI `--project-dir` argument for manual testing

**Detection:**
First operation fails with "file not found" if base_dir is wrong. The error message should include the resolved base_dir to help diagnose.

**Phase to address:** First implementation phase.

---

### Pitfall 10: Tool Description Quality Directly Affects LLM Operation Selection

**What goes wrong:**
The LLM chooses which tool to call based on the tool's `name` and `description`. If `add_component` has the description "Add a component" and `duplicate_component` has "Duplicate a component", the LLM may confuse them. With 57 tools, many have similar names (add_wire, add_label, add_power, add_junction, add_no_connect are all "add something to a schematic"). Poor descriptions cause the LLM to pick the wrong tool, leading to failed operations and frustrated users.

**Why it happens:**
The Pydantic schema docstrings were written for developer documentation, not LLM tool selection. `AddWireOp.__doc__` might say "Operation to add a wire segment" which is accurate but does not distinguish it from `AddLabelOp.__doc__` "Operation to add a label" in a way that helps the LLM choose correctly.

**Consequences:**
- LLM calls `add_label` when it should call `add_wire`
- Repeated failed operations as the LLM tries similar-but-wrong tools
- User has to explicitly specify which operation to use, defeating the purpose of natural language interaction

**Prevention:**
1. Write tool descriptions that include: (a) what the operation does, (b) when to use it vs alternatives, (c) the file type it targets
2. Example: `"Add a wire segment connecting two points in a schematic. Use for point-to-point electrical connections. Targets .kicad_sch files. Use add_label instead to name a net, add_power to place a power symbol, add_junction to mark a wire intersection."`
3. Include operation category in the description: `[SCHEMATIC] Add a wire...`, `[PCB] Add copper zone...`, `[CREATE] Create a new...`
4. Test with the target LLM: give it a task and verify it selects the correct tool

**Detection:**
Run a set of test prompts through the MCP client and check which tool the LLM selects. If accuracy is below 90%, descriptions need improvement.

**Phase to address:** Second implementation phase (after basic server works). Description quality is iterative.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation | Phase to Address |
|-------------|---------------|------------|-----------------|
| Async wrapping of sync executor | Blocking event loop (Pitfall 1) | `asyncio.to_thread()` for every `execute()` call | Phase 1: Server skeleton |
| Error response format | isError never set to True (Pitfall 2) | Return `CallToolResult(isError=True)` for all errors | Phase 1: Server skeleton |
| Tool registration from Pydantic | Schema compatibility (Pitfall 8) | Test schema generation with target clients early | Phase 1: Tool registration |
| base_dir configuration | Path security scope (Pitfall 4) | Require explicit KICAD_PROJECT_DIR, validate on startup | Phase 1: Server skeleton |
| Response size | Multi-MB JSON responses (Pitfall 5) | Cap response size, summarize large results | Phase 1: Response handler |
| 57-tool registration | Client tool count limits (Pitfall 6) | Test with all target clients, have grouping fallback ready | Phase 1: Tool registration |
| Schema size overhead | 68KB context window consumption (Pitfall 3) | Strip verbose fields, compress shared defs | Phase 2: Optimization |
| Tool descriptions | LLM selects wrong tool (Pitfall 10) | Write distinguishing descriptions with usage guidance | Phase 2: Description quality |
| Concurrent access | Multi-client file corruption (Pitfall 7) | PID lock file, single-server constraint documentation | Phase 2: Hardening |
| base_dir vs CWD | Wrong project directory (Pitfall 9) | CLI --project-dir arg, .kicad_pro validation | Phase 1: Server skeleton |

## Recommended Implementation Order

Based on pitfall severity and dependency:

1. **Phase 1: Core server with security and error handling** -- Addresses Pitfalls 1, 2, 4, 5, 8, 9
   - Async wrapping pattern (Pitfall 1)
   - Error response helper returning `CallToolResult(isError=True)` (Pitfall 2)
   - base_dir configuration with validation (Pitfalls 4, 9)
   - Schema generation and normalization (Pitfall 8)
   - Response size capping (Pitfall 5)
   - Register all 57 tools, test with target clients (Pitfall 6)

2. **Phase 2: Optimization and hardening** -- Addresses Pitfalls 3, 7, 10
   - Schema size optimization (Pitfall 3)
   - Tool description quality (Pitfall 10)
   - PID lock file for concurrent access prevention (Pitfall 7)

## Sources

- MCP Python SDK 1.12.3: `mcp.types.Tool`, `mcp.types.CallToolResult`, `mcp.types.ToolAnnotations` (verified via `inspect.signature`)
- MCP specification: Tools concept (modelcontextprotocol.io), error handling (`isError` field)
- Existing codebase: `src/kicad_agent/mcp/server.py` (284 lines, proven pattern for async wrapping and error handling)
- Existing codebase: `src/kicad_agent/ops/executor.py` (1090 lines, synchronous OperationExecutor)
- Existing codebase: `src/kicad_agent/ops/schema.py` (433 lines, 57-operation discriminated union)
- Live measurement: 57 tool schemas total 67,992 bytes, individual range 456-5,411 bytes, average 1,192 bytes

---
*MCP server pitfalls research for: kicad-agent milestone mcp-ops-server*
*Researched: 2026-05-29*
*Confidence: HIGH*
