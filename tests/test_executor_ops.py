"""Tests for core schematic operation executor dispatch (Plan 24-04, Task 2).

Validates that the executor properly dispatches add_wire, add_label,
add_power, add_no_connect, and add_junction operations through the
OperationExecutor and produces correct results.

Uses the Arduino_Mega fixture for a realistic schematic.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from kicad_agent.handler import handle_operation
from kicad_agent.result import OperationResult

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "Arduino_Mega"
FIXTURE_SCH = "Arduino_Mega.kicad_sch"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a temporary project with a copy of the Arduino_Mega fixture."""
    sch_src = FIXTURE_DIR / FIXTURE_SCH
    sch_dst = tmp_path / FIXTURE_SCH
    shutil.copy2(sch_src, sch_dst)
    return tmp_path


# ---------------------------------------------------------------------------
# add_wire
# ---------------------------------------------------------------------------


def test_add_wire_executor(project_dir: Path) -> None:
    """add_wire operation dispatches correctly and adds a wire to the schematic."""
    op_json = json.dumps({
        "op_type": "add_wire",
        "target_file": FIXTURE_SCH,
        "start_x": 50.0,
        "start_y": 30.0,
        "end_x": 80.0,
        "end_y": 30.0,
    })
    result = handle_operation(op_json, project_dir=project_dir)
    assert isinstance(result, OperationResult), f"Expected OperationResult, got {type(result)}"
    assert result.success
    assert result.operation_type == "add_wire"

    # Verify the file is still valid KiCad
    content = (project_dir / FIXTURE_SCH).read_text(encoding="utf-8")
    assert "kicad_sch" in content, "File should still be a valid KiCad schematic"


def test_add_wire_file_unchanged_on_failure(tmp_path: Path) -> None:
    """add_wire on a non-existent file returns an error without creating the file."""
    op_json = json.dumps({
        "op_type": "add_wire",
        "target_file": "nonexistent.kicad_sch",
        "start_x": 0.0,
        "start_y": 0.0,
        "end_x": 10.0,
        "end_y": 10.0,
    })
    result = handle_operation(op_json, project_dir=tmp_path)
    assert not result.success


def test_connect_pins_executor_uses_real_pin_positions(project_dir: Path) -> None:
    """connect_pins resolves REF.PIN descriptors and adds a wire at pin endpoints."""
    from kicad_agent.ir.schematic_ir import SchematicIR
    from kicad_agent.parser import parse_schematic

    op_json = json.dumps({
        "op_type": "connect_pins",
        "target_file": FIXTURE_SCH,
        "source": "J1.1",
        "target": "J1.2",
    })
    result = handle_operation(op_json, project_dir=project_dir)
    assert isinstance(result, OperationResult)
    assert result.success
    assert result.operation_type == "connect_pins"

    sch_path = project_dir / FIXTURE_SCH
    ir = SchematicIR(_parse_result=parse_schematic(sch_path))
    pins = {
        (p["reference"], p["pin_number"]): (p["x"], p["y"])
        for p in ir.get_pin_positions()
    }
    source_xy = pins[("J1", "1")]
    target_xy = pins[("J1", "2")]

    assert result.details["route"] == "orthogonal"
    assert result.details["wires"][0]["start"] == [source_xy[0], source_xy[1]]
    assert result.details["wires"][0]["end"] == [target_xy[0], target_xy[1]]

    wires = ir.get_wire_endpoints()
    assert any(
        w["start_x"] == source_xy[0]
        and w["start_y"] == source_xy[1]
        and w["end_x"] == target_xy[0]
        and w["end_y"] == target_xy[1]
        for w in wires
    )


def test_connect_pins_unknown_pin_returns_error(project_dir: Path) -> None:
    """connect_pins fails clearly when a REF.PIN descriptor cannot resolve."""
    op_json = json.dumps({
        "op_type": "connect_pins",
        "target_file": FIXTURE_SCH,
        "source": "J1.999",
        "target": "J1.2",
    })
    result = handle_operation(op_json, project_dir=project_dir)
    assert not result.success
    assert result.operation_type == "connect_pins"


# ---------------------------------------------------------------------------
# add_label
# ---------------------------------------------------------------------------


def test_add_label_executor(project_dir: Path) -> None:
    """add_label operation dispatches correctly and adds a label to the schematic."""
    op_json = json.dumps({
        "op_type": "add_label",
        "target_file": FIXTURE_SCH,
        "name": "TEST_NET",
        "label_type": "local",
        "position": {"x": 50.0, "y": 30.0, "angle": 0.0},
    })
    result = handle_operation(op_json, project_dir=project_dir)
    assert isinstance(result, OperationResult)
    assert result.success
    assert result.operation_type == "add_label"


# ---------------------------------------------------------------------------
# add_power
# ---------------------------------------------------------------------------


def test_add_power_executor(project_dir: Path) -> None:
    """add_power operation dispatches correctly and adds a power symbol."""
    op_json = json.dumps({
        "op_type": "add_power",
        "target_file": FIXTURE_SCH,
        "name": "+5V",
        "position": {"x": 60.0, "y": 40.0, "angle": 0.0},
    })
    result = handle_operation(op_json, project_dir=project_dir)
    assert isinstance(result, OperationResult)
    assert result.success
    assert result.operation_type == "add_power"


# ---------------------------------------------------------------------------
# add_no_connect
# ---------------------------------------------------------------------------


def test_add_no_connect_executor(project_dir: Path) -> None:
    """add_no_connect operation dispatches and places a no-connect marker."""
    op_json = json.dumps({
        "op_type": "add_no_connect",
        "target_file": FIXTURE_SCH,
        "position": {"x": 70.0, "y": 50.0},
    })
    result = handle_operation(op_json, project_dir=project_dir)
    assert isinstance(result, OperationResult)
    assert result.success
    assert result.operation_type == "add_no_connect"


# ---------------------------------------------------------------------------
# add_junction
# ---------------------------------------------------------------------------


def test_add_junction_executor(project_dir: Path) -> None:
    """add_junction operation dispatches and places a junction dot."""
    op_json = json.dumps({
        "op_type": "add_junction",
        "target_file": FIXTURE_SCH,
        "position": {"x": 55.0, "y": 35.0},
    })
    result = handle_operation(op_json, project_dir=project_dir)
    assert isinstance(result, OperationResult)
    assert result.success
    assert result.operation_type == "add_junction"


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_unknown_op_type_returns_error(project_dir: Path) -> None:
    """Unknown op_type returns OperationError, not exception."""
    op_json = json.dumps({
        "op_type": "fly_to_moon",
        "target_file": FIXTURE_SCH,
    })
    result = handle_operation(op_json, project_dir=project_dir)
    assert not result.success


def test_path_traversal_returns_error(tmp_path: Path) -> None:
    """Path traversal in target_file returns OperationError."""
    op_json = json.dumps({
        "op_type": "add_wire",
        "target_file": "../../etc/passwd",
        "start_x": 0.0,
        "start_y": 0.0,
        "end_x": 10.0,
        "end_y": 10.0,
    })
    result = handle_operation(op_json, project_dir=tmp_path)
    assert not result.success
