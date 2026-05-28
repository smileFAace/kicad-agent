"""Tests for root sheet generator.

SCHREPAIR-08: Root sheet generation from sub-sheet hierarchical labels.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.ops.root_sheet import (
    RootSheetResult,
    _classify_direction,
    rebuild_root_sheet,
)
from kicad_agent.ops.schema import Operation, RebuildRootSheetOp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_hlabel(text: str, shape: str) -> MagicMock:
    """Create a mock hierarchical label."""
    lbl = MagicMock()
    lbl.text = text
    lbl.shape = shape
    return lbl


def _make_mock_sheet(
    file_name: str, x: float, y: float, width: float, height: float
) -> MagicMock:
    """Create a mock hierarchical sheet."""
    sheet = MagicMock()
    sheet.fileName.value = file_name
    sheet.sheetName.value = file_name.replace(".kicad_sch", "")
    sheet.position.X = x
    sheet.position.Y = y
    sheet.width = width
    sheet.height = height
    sheet.pins = []
    return sheet


# ---------------------------------------------------------------------------
# Direction classification tests
# ---------------------------------------------------------------------------


def test_classify_direction_input():
    assert _classify_direction("input") == "input"


def test_classify_direction_output():
    assert _classify_direction("output") == "output"


def test_classify_direction_bidirectional():
    assert _classify_direction("bidirectional") == "bidirectional"


def test_classify_direction_passive():
    assert _classify_direction("passive") == "passive"


def test_classify_direction_unknown():
    assert _classify_direction("unknown_shape") == "passive"


# ---------------------------------------------------------------------------
# rebuild_root_sheet tests
# ---------------------------------------------------------------------------


def test_rebuild_root_sheet_basic():
    """Basic test: 3 hlabels -> 3 pins with correct sides."""
    mock_root_ir = MagicMock()
    mock_sheet = _make_mock_sheet("sub.kicad_sch", 100, 100, 50, 50)
    mock_root_ir.schematic.sheets = [mock_sheet]

    # Mock sub-sheet IR with 3 hierarchical labels
    mock_sub_ir = MagicMock()
    mock_sub_ir.schematic.hierarchicalLabels = [
        _make_mock_hlabel("SDA", "input"),
        _make_mock_hlabel("SCL", "output"),
        _make_mock_hlabel("VCC", "bidirectional"),
    ]

    mock_parse_result = MagicMock()

    with patch("kicad_agent.parser.parse_schematic", return_value=mock_parse_result) as mock_parse, \
         patch("kicad_agent.ir.schematic_ir.SchematicIR") as mock_ir_class, \
         patch("pathlib.Path.exists", return_value=True):
        # First call returns root IR, second returns sub IR
        mock_ir_class.side_effect = [mock_root_ir, mock_sub_ir]

        results = rebuild_root_sheet(Path("root.kicad_sch"))

    assert len(results) == 1
    result = results[0]
    assert isinstance(result, RootSheetResult)
    assert result.pins_placed == 3
    assert result.sheet_name == "sub.kicad_sch"

    # Check pin sides: SDA input -> LEFT, SCL output -> RIGHT, VCC bidirectional -> LEFT
    left_pins = [d for d in result.pin_details if d["side"] == "left"]
    right_pins = [d for d in result.pin_details if d["side"] == "right"]
    assert len(left_pins) == 2  # SDA + VCC
    assert len(right_pins) == 1  # SCL

    # Check pin names
    left_names = {d["pin_name"] for d in left_pins}
    right_names = {d["pin_name"] for d in right_pins}
    assert "SDA" in left_names
    assert "VCC" in left_names
    assert "SCL" in right_names


def test_rebuild_root_sheet_missing_subsheet():
    """Missing sub-sheet is skipped with warning, no crash."""
    mock_root_ir = MagicMock()
    mock_sheet = _make_mock_sheet("nonexistent.kicad_sch", 100, 100, 50, 50)
    mock_root_ir.schematic.sheets = [mock_sheet]

    with patch("kicad_agent.parser.parse_schematic") as mock_parse, \
         patch("kicad_agent.ir.schematic_ir.SchematicIR", return_value=mock_root_ir):
        # parse_schematic returns a result, but sub-sheet path won't exist
        results = rebuild_root_sheet(Path("root.kicad_sch"))

    assert results == []


def test_rebuild_root_sheet_empty_subsheet():
    """Sub-sheet with no hierarchical labels produces 0 pins."""
    mock_root_ir = MagicMock()
    mock_sheet = _make_mock_sheet("empty.kicad_sch", 100, 100, 50, 50)
    mock_root_ir.schematic.sheets = [mock_sheet]

    mock_sub_ir = MagicMock()
    mock_sub_ir.schematic.hierarchicalLabels = []

    with patch("kicad_agent.parser.parse_schematic"), \
         patch("kicad_agent.ir.schematic_ir.SchematicIR") as mock_ir_class, \
         patch("pathlib.Path.exists", return_value=True):
        mock_ir_class.side_effect = [mock_root_ir, mock_sub_ir]

        results = rebuild_root_sheet(Path("root.kicad_sch"))

    assert len(results) == 1
    assert results[0].pins_placed == 0


def test_rebuild_root_sheet_pin_positioning():
    """Pin positions follow LEFT/RIGHT and 2.54mm spacing."""
    mock_root_ir = MagicMock()
    mock_sheet = _make_mock_sheet("sub.kicad_sch", 100, 100, 50, 50)
    mock_root_ir.schematic.sheets = [mock_sheet]

    mock_sub_ir = MagicMock()
    mock_sub_ir.schematic.hierarchicalLabels = [
        _make_mock_hlabel("A", "input"),
        _make_mock_hlabel("B", "input"),
        _make_mock_hlabel("C", "output"),
    ]

    with patch("kicad_agent.parser.parse_schematic"), \
         patch("kicad_agent.ir.schematic_ir.SchematicIR") as mock_ir_class, \
         patch("pathlib.Path.exists", return_value=True):
        mock_ir_class.side_effect = [mock_root_ir, mock_sub_ir]

        results = rebuild_root_sheet(Path("root.kicad_sch"))

    assert len(results) == 1
    details = results[0].pin_details

    # LEFT pins start at x=100
    left_pins = [d for d in details if d["side"] == "left"]
    assert left_pins[0]["position"]["x"] == 100
    assert left_pins[1]["position"]["x"] == 100

    # Y spacing: 100 + 5.08, 100 + 5.08 + 2.54
    assert abs(left_pins[0]["position"]["y"] - 105.08) < 0.01
    assert abs(left_pins[1]["position"]["y"] - 107.62) < 0.01

    # RIGHT pin at x=150 (100 + 50)
    right_pins = [d for d in details if d["side"] == "right"]
    assert right_pins[0]["position"]["x"] == 150


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_rebuild_root_sheet_schema():
    """RebuildRootSheetOp validates correctly."""
    op = RebuildRootSheetOp(
        op_type="rebuild_root_sheet",
        target_file="root.kicad_sch",
    )
    assert op.op_type == "rebuild_root_sheet"


def test_rebuild_root_sheet_op_integration():
    """Full schema -> validate -> operation flow works."""
    wrapped = Operation.model_validate({
        "root": {
            "op_type": "rebuild_root_sheet",
            "target_file": "root.kicad_sch",
        }
    })
    assert wrapped.root.op_type == "rebuild_root_sheet"


def test_rebuild_root_sheet_op_schema_reject():
    """Invalid inputs are rejected by schema validation."""
    from pydantic import ValidationError

    # Path traversal rejected
    with pytest.raises(ValidationError):
        Operation.model_validate({
            "root": {
                "op_type": "rebuild_root_sheet",
                "target_file": "../etc/passwd",
            }
        })

    # Wrong extension rejected
    with pytest.raises(ValidationError):
        Operation.model_validate({
            "root": {
                "op_type": "rebuild_root_sheet",
                "target_file": "test.txt",
            }
        })
