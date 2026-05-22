"""Test suite for handler routing and result rendering (Plan 07-02).

Covers:
  - Valid add_component and remove_component JSON validation
  - Invalid JSON syntax returns OperationError with suggestion
  - Unknown op_type returns OperationError
  - Missing required fields return OperationError with field name
  - Path traversal in target_file returns OperationError
  - handle_operation returns OperationResult for valid operations
  - handle_operation returns OperationError for invalid operations
  - OperationResult.to_text() includes success message
  - OperationError.to_text() includes suggestion
"""

import json

import pytest

from kicad_agent.handler import format_result, handle_operation, validate_operation
from kicad_agent.result import OperationError, OperationResult


# ---------------------------------------------------------------------------
# Test 1: Valid add_component JSON validates successfully
# ---------------------------------------------------------------------------


def test_validate_add_component_success():
    json_str = json.dumps({
        "op_type": "add_component",
        "target_file": "test.kicad_sch",
        "library_id": "Device:R_Small_US",
        "position": {"x": 50.0, "y": 30.0},
    })
    op, err = validate_operation(json_str)
    assert op is not None
    assert err is None
    assert op.root.op_type == "add_component"
    assert op.root.target_file == "test.kicad_sch"


# ---------------------------------------------------------------------------
# Test 2: Valid remove_component JSON validates successfully
# ---------------------------------------------------------------------------


def test_validate_remove_component_success():
    json_str = json.dumps({
        "op_type": "remove_component",
        "target_file": "test.kicad_sch",
        "reference": "R1",
    })
    op, err = validate_operation(json_str)
    assert op is not None
    assert err is None
    assert op.root.op_type == "remove_component"
    assert op.root.reference == "R1"


# ---------------------------------------------------------------------------
# Test 3: Invalid JSON (bad syntax) returns OperationError with suggestion
# ---------------------------------------------------------------------------


def test_validate_invalid_json_syntax():
    json_str = "{bad json"
    op, err = validate_operation(json_str)
    assert op is None
    assert err is not None
    assert err.success is False
    assert "JSON" in err.error or "syntax" in err.error.lower()
    assert len(err.suggestion) > 0


# ---------------------------------------------------------------------------
# Test 4: Valid JSON but unknown op_type returns OperationError
# ---------------------------------------------------------------------------


def test_validate_unknown_op_type():
    json_str = json.dumps({
        "op_type": "explode",
        "target_file": "test.kicad_sch",
    })
    op, err = validate_operation(json_str)
    assert op is None
    assert err is not None
    assert err.success is False
    assert "explode" in err.error or "op_type" in err.error


# ---------------------------------------------------------------------------
# Test 5: Missing required field returns OperationError with field name
# ---------------------------------------------------------------------------


def test_validate_missing_required_field():
    # add_component without library_id
    json_str = json.dumps({
        "op_type": "add_component",
        "target_file": "test.kicad_sch",
    })
    op, err = validate_operation(json_str)
    assert op is None
    assert err is not None
    assert err.success is False
    # Error should mention the missing field or validation failure
    assert "library_id" in err.error or "Field required" in err.error


# ---------------------------------------------------------------------------
# Test 6: Path traversal in target_file returns OperationError
# ---------------------------------------------------------------------------


def test_validate_path_traversal():
    json_str = json.dumps({
        "op_type": "add_component",
        "target_file": "../../../etc/passwd",
        "library_id": "Device:R",
        "position": {"x": 1.0, "y": 1.0},
    })
    op, err = validate_operation(json_str)
    assert op is None
    assert err is not None
    assert err.success is False
    assert "path" in err.error.lower() or "traversal" in err.error.lower() or ".." in err.error


# ---------------------------------------------------------------------------
# Test 7: handle_operation returns OperationResult for valid operations
# ---------------------------------------------------------------------------


def test_handle_operation_valid():
    """handle_operation with a valid operation on a real file returns OperationResult."""
    import pathlib
    fixture = pathlib.Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch")
    json_str = json.dumps({
        "op_type": "move_component",
        "target_file": str(fixture),
        "reference": "J1",
        "position": {"x": 50.0, "y": 30.0},
    })
    result = handle_operation(json_str)
    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation_type == "move_component"


# ---------------------------------------------------------------------------
# Test 8: handle_operation returns OperationError for invalid operations
# ---------------------------------------------------------------------------


def test_handle_operation_invalid():
    json_str = "{bad json"
    result = handle_operation(json_str)
    assert isinstance(result, OperationError)
    assert result.success is False


# ---------------------------------------------------------------------------
# Test 9: OperationResult.to_text() includes success message
# ---------------------------------------------------------------------------


def test_operation_result_to_text():
    result = OperationResult(
        success=True,
        operation_type="add_component",
        target_file="test.kicad_sch",
        message="Operation validated and queued",
        details={"library_id": "Device:R_Small_US"},
    )
    text = result.to_text()
    assert "add_component" in text
    assert "test.kicad_sch" in text
    assert "success" in text.lower() or "validated" in text.lower()


# ---------------------------------------------------------------------------
# Test 10: OperationError.to_text() includes suggestion
# ---------------------------------------------------------------------------


def test_operation_error_to_text():
    err = OperationError(
        success=False,
        operation_type="unknown",
        error="Invalid JSON syntax",
        suggestion="Check that your JSON is well-formed",
    )
    text = err.to_text()
    assert "Invalid JSON syntax" in text
    assert "Check that your JSON is well-formed" in text
