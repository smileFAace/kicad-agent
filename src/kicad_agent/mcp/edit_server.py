"""MCP server exposing all 57 kicad-agent operations as individually named tools.

Dynamic tool generation from Pydantic Operation discriminated union.
Follows the same pattern as the existing component-search server.

Usage:
    # Start as MCP server (stdio transport)
    kicad-agent-edit

    # Configure project directory
    KICAD_PROJECT_DIR=/path/to/project kicad-agent-edit
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, get_args

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from kicad_agent.context import render_project_context
from kicad_agent.ops.executor import OperationExecutor
from kicad_agent.ops.schema import Operation
from kicad_agent.ops.undo_stack import UndoStack
from kicad_agent.validation.erc_drc import run_erc, run_drc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Response size limit
# ---------------------------------------------------------------------------

_MAX_RESPONSE_BYTES = 50 * 1024  # 50KB


# ---------------------------------------------------------------------------
# ToolAnnotations by category
# ---------------------------------------------------------------------------

_READ_ONLY_OPS = frozenset({
    "query_connectivity", "navigate_hierarchy", "validate_power_nets",
    "validate_schematic", "parse_erc", "extract_violation_positions",
    "validate_hlabels", "cross_ref_check", "validate_refs",
    "validate_footprint", "verify_pin_map",
})

_DESTRUCTIVE_OPS = frozenset({
    "remove_component", "remove_net", "remove_wire", "remove_label",
    "remove_junction", "remove_no_connect", "remove_lib_entry",
    "propagate_symbol_change",
})

_IDEMPOTENT_OPS = frozenset({
    "create_schematic", "create_pcb", "create_project", "create_symbol",
    "create_footprint", "embed_symbol", "add_lib_entry", "snap_to_grid",
    "convert_kicad6_to_10",
})


def _annotations_for(op_type: str) -> types.ToolAnnotations | None:
    """Assign ToolAnnotations based on operation category."""
    if op_type in _READ_ONLY_OPS:
        return types.ToolAnnotations(readOnlyHint=True)
    if op_type in _DESTRUCTIVE_OPS:
        return types.ToolAnnotations(destructiveHint=True)
    if op_type in _IDEMPOTENT_OPS:
        return types.ToolAnnotations(idempotentHint=True)
    return None


# ---------------------------------------------------------------------------
# Dynamic tool generation from Operation discriminated union
# ---------------------------------------------------------------------------

def _generate_operation_tools() -> list[types.Tool]:
    """Generate one MCP tool per Operation union variant."""
    ann = Operation.model_fields["root"].annotation
    variants = get_args(ann)
    tools: list[types.Tool] = []

    for variant_cls in variants:
        op_type = variant_cls.model_fields["op_type"].default
        schema = variant_cls.model_json_schema()
        # Strip $defs — MCP clients handle flat schemas better
        schema.pop("$defs", None)
        # Strip $ref references that point to removed $defs
        for prop in schema.get("properties", {}).values():
            prop.pop("$ref", None)

        description = schema.pop("description", f"Execute {op_type} operation.")
        annotations = _annotations_for(op_type)

        tools.append(types.Tool(
            name=op_type,
            description=description,
            inputSchema=schema,
            annotations=annotations,
        ))

    return tools


# Meta-tool definitions (static)
_META_TOOLS = [
    types.Tool(
        name="get_operation_schema",
        description=(
            "Get the full JSON Schema for all 57 kicad-agent operations. "
            "Use this to discover available operations and their parameters."
        ),
        inputSchema={"type": "object", "properties": {}},
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="get_project_context",
        description=(
            "Get a summary of the current KiCad project: files, component counts, "
            "net counts, and board statistics. Useful for understanding the project "
            "before making edits."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "enrich": {
                    "type": "boolean",
                    "description": "Parse files to count components and nets (default true)",
                    "default": True,
                },
            },
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="erc_check",
        description=(
            "Run Electrical Rules Check (ERC) on a KiCad schematic using kicad-cli. "
            "Returns structured results: pass/fail status, violation count, and "
            "violation details with positions. Equivalent to kicad-cli sch erc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "schematic_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_sch file (e.g. 'motor-driver.kicad_sch')",
                    "minLength": 1,
                },
            },
            "required": ["schematic_file"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="drc_check",
        description=(
            "Run Design Rules Check (DRC) on a KiCad PCB using kicad-cli. "
            "Returns structured results: pass/fail status, violation count, "
            "unconnected items, and violation details with positions. "
            "Equivalent to kicad-cli pcb drc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "pcb_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_pcb file (e.g. 'motor-driver.kicad_pcb')",
                    "minLength": 1,
                },
            },
            "required": ["pcb_file"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="undo",
        description=(
            "Undo the most recent file mutation. Restores the file to its state "
            "before the last operation. Session-scoped -- undo history is lost on "
            "server restart. Create operations (create_schematic, create_pcb, etc.) "
            "are not undoable."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "target_file": {
                    "type": "string",
                    "description": (
                        "Relative path to the file to undo (e.g. 'motor-driver.kicad_sch'). "
                        "Optional -- when omitted, undoes the most recently modified file."
                    ),
                },
            },
        },
        annotations=types.ToolAnnotations(destructiveHint=True),
    ),
    types.Tool(
        name="redo",
        description=(
            "Redo the most recently undone operation. Restores the file to its state "
            "after the undone operation. Session-scoped -- redo history is lost on "
            "server restart."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "target_file": {
                    "type": "string",
                    "description": (
                        "Relative path to the file to redo (e.g. 'motor-driver.kicad_sch'). "
                        "Optional -- when omitted, redoes the most recently undone file."
                    ),
                },
            },
        },
        annotations=types.ToolAnnotations(destructiveHint=True),
    ),
]


# Cache tool list at module level
_OPERATION_TOOLS = _generate_operation_tools()
_ALL_TOOLS = _OPERATION_TOOLS + _META_TOOLS
_OP_NAMES = {t.name for t in _OPERATION_TOOLS}


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _cap_response(text: str) -> str:
    """Truncate response if it exceeds 50KB."""
    if len(text.encode("utf-8")) <= _MAX_RESPONSE_BYTES:
        return text
    truncation_notice = (
        f'\n\n--- RESPONSE TRUNCATED (original {len(text)} chars) ---\n'
        "Use query_connectivity or get_project_context for focused queries."
    )
    budget = _MAX_RESPONSE_BYTES - len(truncation_notice.encode("utf-8"))
    return text[:budget] + truncation_notice


def _error_result(error_type: str, message: str, suggestion: str = "") -> types.CallToolResult:
    """Build a structured error result."""
    body = {"error_type": error_type, "message": message}
    if suggestion:
        body["suggestion"] = suggestion
    return types.CallToolResult(
        isError=True,
        content=[types.TextContent(type="text", text=json.dumps(body, indent=2))],
    )


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def server_lifespan(server: Server):  # type: ignore[type-arg]
    """Create OperationExecutor and resolve base directory."""
    base_dir_str = os.environ.get("KICAD_PROJECT_DIR", "")
    base_dir = Path(base_dir_str) if base_dir_str else Path.cwd()
    base_dir = base_dir.resolve()

    if not base_dir.is_dir():
        logger.warning("KICAD_PROJECT_DIR does not exist: %s", base_dir)

    # M-02: Parse KICAD_UNDO_MAX_SIZE with error handling
    try:
        max_undo = max(1, int(os.environ.get("KICAD_UNDO_MAX_SIZE", "50")))
    except (ValueError, TypeError):
        max_undo = 50
    undo_stack = UndoStack(max_size=max_undo)
    executor = OperationExecutor(base_dir=base_dir, undo_stack=undo_stack)
    yield {"executor": executor, "base_dir": base_dir}


app = Server("kicad-agent-edit", version="0.1.0", lifespan=server_lifespan)


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """Return all available MCP tools (65 operations + 6 meta-tools)."""
    return _ALL_TOOLS


async def dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    executor: OperationExecutor,
    base_dir: Path,
) -> types.CallToolResult:
    """Route tool calls to executor or meta-tool handlers.

    Separated from the MCP handler for testability — tests can call this
    directly without needing a live MCP request context.
    """
    # --- Meta-tools ---
    if name == "get_operation_schema":
        schema = Operation.model_json_schema()
        text = _cap_response(json.dumps(schema, indent=2))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
        )

    if name == "get_project_context":
        try:
            enrich = arguments.get("enrich", True)
            context = await asyncio.to_thread(
                render_project_context, base_dir, enrich,
            )
            text = _cap_response(context)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)],
            )
        except Exception as e:
            return _error_result("context_error", str(e))

    # --- Validation tools ---
    if name == "erc_check":
        try:
            sch_file = arguments["schematic_file"]
            sch_path = base_dir / sch_file
            result = await asyncio.to_thread(run_erc, sch_path)
            text = _cap_response(json.dumps({
                "passed": result.passed,
                "file": str(result.file_path),
                "violation_count": len(result.violations),
                "errors": len(result.errors),
                "warnings": len(result.warnings),
                "violations": [
                    {"severity": v.severity.value, "type": v.type,
                     "description": v.description, "sheet": v.sheet_path}
                    for v in result.violations[:50]
                ],
                "kicad_version": result.kicad_version,
                "error_message": result.error_message,
            }, indent=2, default=str))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)],
            )
        except Exception as e:
            return _error_result(
                "erc_error", str(e), "Verify the schematic file path is correct."
            )

    if name == "drc_check":
        try:
            pcb_file = arguments["pcb_file"]
            pcb_path = base_dir / pcb_file
            result = await asyncio.to_thread(run_drc, pcb_path)
            text = _cap_response(json.dumps({
                "passed": result.passed,
                "file": str(result.file_path),
                "violation_count": len(result.violations),
                "unconnected_count": len(result.unconnected_items),
                "violations": [
                    {"severity": v.severity.value, "type": v.type,
                     "description": v.description}
                    for v in result.violations[:50]
                ],
                "unconnected_items": [
                    {"description": v.description, "type": v.type}
                    for v in result.unconnected_items[:20]
                ],
                "kicad_version": result.kicad_version,
                "error_message": result.error_message,
            }, indent=2, default=str))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)],
            )
        except Exception as e:
            return _error_result(
                "drc_error", str(e), "Verify the PCB file path is correct."
            )

    # --- Undo/Redo tools ---
    if name == "undo":
        try:
            target_file = arguments.get("target_file")
            result = await asyncio.to_thread(executor.undo, target_file)
            if result.get("success"):
                text = _cap_response(json.dumps(result, indent=2, default=str))
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=text)],
                )
            return _error_result("undo_error", result.get("error", "No operations to undo"))
        except Exception as e:
            return _error_result("undo_error", str(e), "No operations to undo.")

    if name == "redo":
        try:
            target_file = arguments.get("target_file")
            result = await asyncio.to_thread(executor.redo, target_file)
            if result.get("success"):
                text = _cap_response(json.dumps(result, indent=2, default=str))
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=text)],
                )
            return _error_result("redo_error", result.get("error", "No operations to redo"))
        except Exception as e:
            return _error_result("redo_error", str(e), "No operations to redo.")

    # --- Operation tools ---
    if name not in _OP_NAMES:
        return _error_result(
            "unknown_tool",
            f"Unknown tool: {name}",
            f"Available tools: {', '.join(sorted(_OP_NAMES)[:10])}...",
        )

    try:
        # Inject op_type and resolve target_file against base_dir
        payload = {**arguments, "op_type": name}
        if "target_file" in payload:
            payload["target_file"] = str(Path(payload["target_file"]))
        if "target_files" in payload and isinstance(payload["target_files"], list):
            payload["target_files"] = [
                {**tf, "path": str(Path(tf["path"]))} if isinstance(tf, dict) and "path" in tf else tf
                for tf in payload["target_files"]
            ]

        # Validate via Pydantic
        op = Operation.model_validate({"root": payload})

        # Execute in thread to avoid blocking event loop
        result = await asyncio.to_thread(executor.execute, op)

        text = _cap_response(json.dumps(result, indent=2, default=str))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
        )

    except Exception as e:
        correlation_id = str(uuid.uuid4())[:8]
        logger.exception("Tool %s failed [ref=%s]", name, correlation_id)

        error_type = type(e).__name__
        message = str(e)
        suggestion = ""

        if "validation error" in message.lower():
            error_type = "validation_error"
            suggestion = "Check parameter types and required fields against the operation schema."
        elif isinstance(e, FileNotFoundError):
            suggestion = "Verify the target file path is correct and the file exists."
        elif isinstance(e, PermissionError):
            suggestion = "Check file permissions on the target KiCad file."

        return _error_result(
            error_type,
            f"{message} [ref: {correlation_id}]",
            suggestion,
        )


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    """MCP handler — extracts lifespan context and delegates to dispatch_tool."""
    lifespan_ctx = app.request_context.lifespan_context  # type: ignore[attr-defined]
    executor: OperationExecutor = lifespan_ctx["executor"]
    base_dir: Path = lifespan_ctx["base_dir"]
    return await dispatch_tool(name, arguments, executor, base_dir)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run_server() -> None:
    """Run the MCP server with stdio transport."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


def main() -> None:
    """CLI entry point for kicad-agent-edit."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run_server())


if __name__ == "__main__":
    main()
