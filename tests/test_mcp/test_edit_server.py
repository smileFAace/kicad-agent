"""Tests for the MCP edit server (kicad-agent-edit).

Covers: tool generation, call dispatch, error handling, response capping,
meta-tools, and ToolAnnotations assignment.
"""

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.mcp.edit_server import (
    _ALL_TOOLS,
    _META_TOOLS,
    _OP_NAMES,
    _OPERATION_TOOLS,
    _cap_response,
    _error_result,
    _generate_operation_tools,
    app,
    dispatch_tool,
)
from kicad_agent.ops.executor import OperationExecutor
from mcp import types


# ---------------------------------------------------------------------------
# Tool generation
# ---------------------------------------------------------------------------


class TestToolGeneration:
    """Dynamic tool generation from Operation discriminated union."""

    def test_generates_57_operation_tools(self) -> None:
        assert len(_OPERATION_TOOLS) == 65  # 57 original + 8 project CRUD ops

    def test_generates_6_meta_tools(self) -> None:
        assert len(_META_TOOLS) == 6
        meta_names = {t.name for t in _META_TOOLS}
        assert meta_names == {"get_operation_schema", "get_project_context", "erc_check", "drc_check", "undo", "redo"}

    def test_total_tool_count(self) -> None:
        assert len(_ALL_TOOLS) == 71  # 65 ops + 6 meta

    def test_all_tools_have_names(self) -> None:
        for tool in _ALL_TOOLS:
            assert tool.name, "Tool missing name"
            assert isinstance(tool.name, str)

    def test_all_tools_have_input_schema(self) -> None:
        for tool in _ALL_TOOLS:
            assert isinstance(tool.inputSchema, dict), f"{tool.name} missing inputSchema"
            assert "properties" in tool.inputSchema, f"{tool.name} schema missing properties"

    def test_all_tools_have_description(self) -> None:
        for tool in _ALL_TOOLS:
            assert tool.description, f"{tool.name} missing description"
            assert isinstance(tool.description, str)

    def test_operation_tool_names_match_op_type(self) -> None:
        """Each tool name matches its op_type discriminator value."""
        for tool in _OPERATION_TOOLS:
            props = tool.inputSchema.get("properties", {})
            op_type_prop = props.get("op_type", {})
            assert op_type_prop.get("const") == tool.name

    def test_no_duplicate_tool_names(self) -> None:
        names = [t.name for t in _ALL_TOOLS]
        assert len(names) == len(set(names)), f"Duplicates: {[n for n in names if names.count(n) > 1]}"

    def test_op_names_set_matches_tools(self) -> None:
        tool_names = {t.name for t in _OPERATION_TOOLS}
        assert _OP_NAMES == tool_names


class TestToolAnnotations:
    """ToolAnnotations assigned per operation category."""

    def test_read_only_ops_have_hint(self) -> None:
        read_only = {
            "query_connectivity", "navigate_hierarchy", "validate_power_nets",
            "validate_schematic", "parse_erc", "extract_violation_positions",
            "validate_hlabels", "cross_ref_check", "validate_refs",
            "validate_footprint", "verify_pin_map",
        }
        for tool in _OPERATION_TOOLS:
            if tool.name in read_only:
                assert tool.annotations is not None, f"{tool.name} missing annotations"
                assert tool.annotations.readOnlyHint is True, f"{tool.name} should be readOnly"

    def test_destructive_ops_have_hint(self) -> None:
        destructive = {
            "remove_component", "remove_net", "remove_wire", "remove_label",
            "remove_junction", "remove_no_connect", "remove_lib_entry",
            "propagate_symbol_change",
        }
        for tool in _OPERATION_TOOLS:
            if tool.name in destructive:
                assert tool.annotations is not None, f"{tool.name} missing annotations"
                assert tool.annotations.destructiveHint is True, f"{tool.name} should be destructive"

    def test_idempotent_ops_have_hint(self) -> None:
        idempotent = {
            "create_schematic", "create_pcb", "create_project", "create_symbol",
            "create_footprint", "embed_symbol", "add_lib_entry", "snap_to_grid",
            "convert_kicad6_to_10",
        }
        for tool in _OPERATION_TOOLS:
            if tool.name in idempotent:
                assert tool.annotations is not None, f"{tool.name} missing annotations"
                assert tool.annotations.idempotentHint is True, f"{tool.name} should be idempotent"

    def test_meta_tools_are_read_only(self) -> None:
        read_only_meta = [t for t in _META_TOOLS if t.name not in {"undo", "redo"}]
        for tool in read_only_meta:
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is True

    def test_undo_redo_have_destructive_hint(self) -> None:
        undo_tool = next(t for t in _META_TOOLS if t.name == "undo")
        redo_tool = next(t for t in _META_TOOLS if t.name == "redo")
        assert undo_tool.annotations is not None
        assert undo_tool.annotations.destructiveHint is True
        assert undo_tool.annotations.readOnlyHint is not True
        assert redo_tool.annotations is not None
        assert redo_tool.annotations.destructiveHint is True
        assert redo_tool.annotations.readOnlyHint is not True


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


class TestResponseCapping:
    """Response size capping at 50KB."""

    def test_short_response_unchanged(self) -> None:
        text = "Hello world"
        assert _cap_response(text) == text

    def test_exact_limit_unchanged(self) -> None:
        text = "x" * (50 * 1024)  # exactly 50KB in UTF-8
        result = _cap_response(text)
        assert result == text

    def test_oversize_truncated(self) -> None:
        text = "x" * (60 * 1024)  # 60KB
        result = _cap_response(text)
        assert len(result.encode("utf-8")) <= 50 * 1024
        assert "TRUNCATED" in result

    def test_truncation_preserves_prefix(self) -> None:
        text = "START" + "x" * (60 * 1024)
        result = _cap_response(text)
        assert result.startswith("START")


class TestErrorResult:
    """Structured error result construction."""

    def test_basic_error(self) -> None:
        result = _error_result("test_error", "Something went wrong")
        assert result.isError is True
        assert len(result.content) == 1
        body = json.loads(result.content[0].text)
        assert body["error_type"] == "test_error"
        assert body["message"] == "Something went wrong"
        assert "suggestion" not in body

    def test_error_with_suggestion(self) -> None:
        result = _error_result("val_error", "Bad input", "Check your params")
        body = json.loads(result.content[0].text)
        assert body["suggestion"] == "Check your params"


# ---------------------------------------------------------------------------
# Call dispatch (unit tests with mocked executor)
# ---------------------------------------------------------------------------


class TestCallDispatch:
    """Test dispatch logic by calling helpers directly (bypass MCP ContextVar)."""

    def test_unknown_tool_returns_error(self) -> None:
        """Unknown tool name produces structured error."""
        assert "nonexistent_tool" not in _OP_NAMES
        result = _error_result(
            "unknown_tool",
            "Unknown tool: nonexistent_tool",
            "Use get_operation_schema to list available tools.",
        )
        assert result.isError is True
        body = json.loads(result.content[0].text)
        assert body["error_type"] == "unknown_tool"

    def test_get_operation_schema_returns_valid_json(self) -> None:
        """get_operation_schema meta-tool returns valid Operation schema."""
        from kicad_agent.ops.schema import get_operation_schema
        schema = get_operation_schema()
        assert "properties" in schema
        assert "root" in schema["properties"]
        root = schema["properties"]["root"]
        assert "oneOf" in root or "anyOf" in root

    def test_get_project_context_calls_renderer(self, tmp_path: Path) -> None:
        """get_project_context returns render_project_context output."""
        from kicad_agent.context import render_project_context
        # Create a minimal .kicad_sch so discovery finds something
        (tmp_path / "test.kicad_sch").write_text(
            "(kicad_sch (version 20250114) (generator kicad-agent-test)\n"
            "(paper \"A4\")\n"
            "(lib_symbols)\n"
            "(sheet_instances\n"
            "  (path \"/\" (page \"1\"))\n"
            ")\n"
            ")\n"
        )
        result = render_project_context(tmp_path, enrich=True)
        assert "test.kicad_sch" in result

    def test_validation_error_produces_structured_error(self) -> None:
        """Missing required field produces validation_error with suggestion."""
        from pydantic import ValidationError
        from kicad_agent.ops.schema import Operation

        with pytest.raises(ValidationError) as exc_info:
            Operation.model_validate({"root": {"op_type": "add_component", "target_file": "test.kicad_sch"}})

        message = str(exc_info.value)
        error_type = "validation_error"
        suggestion = "Check parameter types and required fields against the operation schema."
        result = _error_result(error_type, message, suggestion)
        assert result.isError is True
        body = json.loads(result.content[0].text)
        assert body["error_type"] == "validation_error"
        assert body["suggestion"] == suggestion

    def test_executor_returns_dict_on_success(self, tmp_path: Path) -> None:
        """OperationExecutor.execute returns dict with success/details."""
        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        # Copy fixture to temp dir
        fixture = Path(__file__).parent.parent / "fixtures" / "Arduino_Mega" / "Arduino_Mega.kicad_sch"
        target = tmp_path / "test.kicad_sch"
        target.write_text(fixture.read_text())

        executor = OperationExecutor(base_dir=tmp_path)
        op = Operation.model_validate({
            "root": {
                "op_type": "parse_erc",
                "target_file": "test.kicad_sch",
            }
        })
        result = executor.execute(op)
        assert isinstance(result, dict)
        assert "success" in result
        assert "operation" in result


class TestDispatchTool:
    """Test dispatch_tool directly with mock executor (no MCP ContextVar needed)."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        """Return (mock_executor, base_dir) pair."""
        executor = MagicMock(spec=OperationExecutor)
        executor.execute.return_value = {
            "success": True,
            "operation": "add_component",
            "target_file": str(tmp_path / "test.kicad_sch"),
            "details": {"component": "R1"},
        }
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        result = await dispatch_tool("nonexistent_tool", {}, executor, base_dir)
        assert result.isError is True
        body = json.loads(result.content[0].text)
        assert body["error_type"] == "unknown_tool"

    @pytest.mark.asyncio
    async def test_get_operation_schema(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        result = await dispatch_tool("get_operation_schema", {}, executor, base_dir)
        assert result.isError is not True
        text = result.content[0].text
        # Full schema is ~96KB, gets truncated — verify it contains operation definitions
        assert '"$defs"' in text
        assert "AddComponentOp" in text

    @pytest.mark.asyncio
    async def test_get_project_context(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        with patch("kicad_agent.mcp.edit_server.render_project_context", return_value="Project summary"):
            result = await dispatch_tool("get_project_context", {"enrich": False}, executor, base_dir)
        assert result.isError is not True
        assert "Project summary" in result.content[0].text

    @pytest.mark.asyncio
    async def test_operation_dispatch_calls_executor(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        # Copy fixture so target_file resolves
        fixture = Path(__file__).parent.parent / "fixtures" / "Arduino_Mega" / "Arduino_Mega.kicad_sch"
        target = base_dir / "test.kicad_sch"
        target.write_text(fixture.read_text())

        result = await dispatch_tool("add_component", {
            "target_file": "test.kicad_sch",
            "library_id": "Device:R_Small_US",
            "reference": "R1",
            "value": "10k",
            "position": {"x": 50.0, "y": 30.0},
        }, executor, base_dir)
        executor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_validation_error_returns_structured_error(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        result = await dispatch_tool("add_component", {
            "target_file": "test.kicad_sch",
            # Missing required library_id
        }, executor, base_dir)
        assert result.isError is True
        body = json.loads(result.content[0].text)
        assert "validation" in body["error_type"].lower() or "ref:" in body["message"]


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------


class TestServerSetup:
    """Server instantiation and configuration."""

    def test_server_name(self) -> None:
        assert app.name == "kicad-agent-edit"

    def test_server_version(self) -> None:
        assert app.version == "0.1.0"

    def test_generate_operation_tools_is_deterministic(self) -> None:
        """Tool generation produces same results on repeated calls."""
        tools1 = _generate_operation_tools()
        tools2 = _generate_operation_tools()
        names1 = [t.name for t in tools1]
        names2 = [t.name for t in tools2]
        assert names1 == names2


class TestValidationTools:
    """Test erc_check and drc_check dispatch with mocked run_erc/run_drc."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        executor = MagicMock(spec=OperationExecutor)
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_erc_check_returns_structured_result(self, mock_executor: tuple) -> None:
        from dataclasses import dataclass
        from kicad_agent.validation.erc_drc import ErcResult
        executor, base_dir = mock_executor
        erc_result = ErcResult(passed=True, file_path=base_dir / "test.kicad_sch", violations=())
        with patch("kicad_agent.mcp.edit_server.run_erc", return_value=erc_result):
            result = await dispatch_tool("erc_check", {"schematic_file": "test.kicad_sch"}, executor, base_dir)
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["passed"] is True
        assert body["violation_count"] == 0

    @pytest.mark.asyncio
    async def test_erc_check_with_violations(self, mock_executor: tuple) -> None:
        from kicad_agent.validation.erc_drc import ErcResult, Violation, Severity
        executor, base_dir = mock_executor
        violations = (Violation(description="Pin not driven", severity=Severity.ERROR, type="pin_not_driven"),)
        erc_result = ErcResult(passed=False, file_path=base_dir / "test.kicad_sch", violations=violations)
        with patch("kicad_agent.mcp.edit_server.run_erc", return_value=erc_result):
            result = await dispatch_tool("erc_check", {"schematic_file": "test.kicad_sch"}, executor, base_dir)
        body = json.loads(result.content[0].text)
        assert body["passed"] is False
        assert body["violation_count"] == 1
        assert body["violations"][0]["description"] == "Pin not driven"

    @pytest.mark.asyncio
    async def test_drc_check_returns_structured_result(self, mock_executor: tuple) -> None:
        from kicad_agent.validation.erc_drc import DrcResult
        executor, base_dir = mock_executor
        drc_result = DrcResult(passed=True, file_path=base_dir / "test.kicad_pcb", violations=(), unconnected_items=())
        with patch("kicad_agent.mcp.edit_server.run_drc", return_value=drc_result):
            result = await dispatch_tool("drc_check", {"pcb_file": "test.kicad_pcb"}, executor, base_dir)
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["passed"] is True
        assert body["unconnected_count"] == 0

    @pytest.mark.asyncio
    async def test_erc_check_missing_file_param(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        result = await dispatch_tool("erc_check", {}, executor, base_dir)
        assert result.isError is True
        body = json.loads(result.content[0].text)
        assert body["error_type"] == "erc_error"

    @pytest.mark.asyncio
    async def test_drc_check_annotations_are_read_only(self) -> None:
        """erc_check and drc_check tools have readOnlyHint=True."""
        erc_tool = next(t for t in _META_TOOLS if t.name == "erc_check")
        drc_tool = next(t for t in _META_TOOLS if t.name == "drc_check")
        assert erc_tool.annotations.readOnlyHint is True
        assert drc_tool.annotations.readOnlyHint is True


class TestUndoRedoDispatch:
    """Test undo/redo dispatch with mock executor."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        executor = MagicMock(spec=OperationExecutor)
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_undo_dispatch_calls_executor(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        executor.undo = MagicMock(return_value={
            "success": True,
            "undone_op": "add_component",
            "target_file": "test.kicad_sch",
        })
        result = await dispatch_tool("undo", {"target_file": "test.kicad_sch"}, executor, base_dir)
        executor.undo.assert_called_once_with("test.kicad_sch")
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True
        assert body["undone_op"] == "add_component"

    @pytest.mark.asyncio
    async def test_redo_dispatch_calls_executor(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        executor.redo = MagicMock(return_value={
            "success": True,
            "redone_op": "add_component",
            "target_file": "test.kicad_sch",
        })
        result = await dispatch_tool("redo", {"target_file": "test.kicad_sch"}, executor, base_dir)
        executor.redo.assert_called_once_with("test.kicad_sch")
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True

    @pytest.mark.asyncio
    async def test_undo_no_history_returns_error(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        executor.undo = MagicMock(return_value={
            "success": False,
            "error": "No operations to undo",
        })
        result = await dispatch_tool("undo", {}, executor, base_dir)
        assert result.isError is True
        body = json.loads(result.content[0].text)
        assert body["error_type"] == "undo_error"

    @pytest.mark.asyncio
    async def test_redo_no_history_returns_error(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        executor.redo = MagicMock(return_value={
            "success": False,
            "error": "No operations to redo",
        })
        result = await dispatch_tool("redo", {}, executor, base_dir)
        assert result.isError is True
        body = json.loads(result.content[0].text)
        assert body["error_type"] == "redo_error"

    @pytest.mark.asyncio
    async def test_undo_without_target_file(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        executor.undo = MagicMock(return_value={
            "success": True,
            "undone_op": "move_component",
            "target_file": "test.kicad_sch",
        })
        result = await dispatch_tool("undo", {}, executor, base_dir)
        executor.undo.assert_called_once_with(None)
        assert result.isError is not True


class TestLifespanUndoStack:
    """Test server_lifespan creates UndoStack and passes to executor."""

    @pytest.mark.asyncio
    async def test_lifespan_creates_undo_stack(self, tmp_path: Path) -> None:
        from kicad_agent.mcp.edit_server import server_lifespan
        with patch.dict(os.environ, {"KICAD_PROJECT_DIR": str(tmp_path)}):
            async with server_lifespan(app) as ctx:
                executor = ctx["executor"]
                assert executor._undo_stack is not None
                assert executor._undo_stack._max_size == 50

    @pytest.mark.asyncio
    async def test_lifespan_custom_max_size(self, tmp_path: Path) -> None:
        from kicad_agent.mcp.edit_server import server_lifespan
        with patch.dict(os.environ, {
            "KICAD_PROJECT_DIR": str(tmp_path),
            "KICAD_UNDO_MAX_SIZE": "25",
        }):
            async with server_lifespan(app) as ctx:
                executor = ctx["executor"]
                assert executor._undo_stack._max_size == 25

    @pytest.mark.asyncio
    async def test_lifespan_invalid_max_size_defaults(self, tmp_path: Path) -> None:
        from kicad_agent.mcp.edit_server import server_lifespan
        with patch.dict(os.environ, {
            "KICAD_PROJECT_DIR": str(tmp_path),
            "KICAD_UNDO_MAX_SIZE": "not_a_number",
        }):
            async with server_lifespan(app) as ctx:
                executor = ctx["executor"]
                assert executor._undo_stack._max_size == 50
