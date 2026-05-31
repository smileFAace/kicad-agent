"""Tests for PCB operations -- copper zones, board outline, net class assignment.

Tests create minimal PCBs programmatically using kiutils Board.create_new()
following the maze_generator pattern.
"""

import re
import tempfile
from pathlib import Path

import pytest
from kiutils.board import Board
from kiutils.items.common import Net, Position
from kiutils.items.gritems import GrLine

from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.ops.pcb_ops import (
    add_copper_zone,
    assign_net_class,
    set_board_outline,
)
from kicad_agent.parser import parse_pcb
from kicad_agent.parser.uuid_extractor import extract_uuids


def _create_minimal_pcb(tmpdir: Path, name: str = "test.kicad_pcb") -> tuple[Path, PcbIR]:
    """Create a minimal PCB with a GND net, save it, and return parsed IR."""
    pcb_path = tmpdir / name
    board = Board.create_new()
    board.general.thickness = 1.6

    # Add a GND net
    board.nets.append(Net(number=1, name="GND"))
    board.nets.append(Net(number=2, name="VCC"))

    # Add a board outline
    corners = [
        (Position(X=0, Y=0), Position(X=50, Y=0)),
        (Position(X=50, Y=0), Position(X=50, Y=30)),
        (Position(X=50, Y=30), Position(X=0, Y=30)),
        (Position(X=0, Y=30), Position(X=0, Y=0)),
    ]
    for start, end in corners:
        board.graphicItems.append(
            GrLine(start=start, end=end, layer="Edge.Cuts", width=0.15)
        )

    board.to_file(str(pcb_path))

    # Parse and create IR
    result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)
    return pcb_path, ir


class TestAddCopperZone:
    """Test copper zone/ground pour addition."""

    def test_add_copper_zone(self):
        """Add a copper zone on F.Cu for GND net, verify zone in board.zones."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            result = add_copper_zone(
                ir, pcb_path,
                net_name="GND",
                layer="F.Cu",
                clearance=0.5,
            )

            assert result["zone_added"] is True
            assert result["net"] == "GND"
            assert result["layer"] == "F.Cu"
            assert result["clearance"] == 0.5

            # Verify zone was added to board
            assert len(ir.board.zones) == 1
            zone = ir.board.zones[0]
            assert zone.netName == "GND"
            assert "F.Cu" in zone.layers
            assert zone.clearance == 0.5

    def test_add_copper_zone_custom_clearance(self):
        """Add zone with 0.3mm clearance, verify clearance value."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            result = add_copper_zone(
                ir, pcb_path,
                net_name="GND",
                layer="F.Cu",
                clearance=0.3,
                min_width=0.2,
                priority=5,
            )

            assert result["clearance"] == 0.3
            zone = ir.board.zones[0]
            assert zone.clearance == 0.3
            assert zone.minThickness == 0.2
            assert zone.priority == 5

    def test_add_copper_zone_with_custom_outline(self):
        """Add zone with custom outline points."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            outline = [(5.0, 5.0), (45.0, 5.0), (45.0, 25.0), (5.0, 25.0)]
            result = add_copper_zone(
                ir, pcb_path,
                net_name="GND",
                layer="B.Cu",
                outline_points=outline,
            )

            assert result["zone_added"] is True
            assert result["layer"] == "B.Cu"
            zone = ir.board.zones[0]
            assert len(zone.polygons) == 1
            assert len(zone.polygons[0]) == 4


class TestSetBoardOutline:
    """Test board outline setting."""

    def test_set_board_outline(self):
        """Set 50x30mm outline, verify Edge.Cuts graphics form closed rectangle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            result = set_board_outline(ir, width=50.0, height=30.0)

            assert result["outline_set"] is True
            assert result["width_mm"] == 50.0
            assert result["height_mm"] == 30.0

            # Verify Edge.Cuts items
            edge_items = [
                item for item in ir.board.graphicItems
                if getattr(item, "layer", None) == "Edge.Cuts"
            ]
            assert len(edge_items) == 4

            # Verify they form a closed rectangle
            # Collect all start/end points
            points = []
            for item in edge_items:
                points.append((item.start.X, item.start.Y))
                points.append((item.end.X, item.end.Y))

            # Should have corners at (0,0), (50,0), (50,30), (0,30)
            unique_points = set(
                (round(x, 2), round(y, 2)) for x, y in points
            )
            expected_corners = {(0.0, 0.0), (50.0, 0.0), (50.0, 30.0), (0.0, 30.0)}
            assert unique_points == expected_corners

    def test_set_board_outline_removes_existing(self):
        """Set outline twice, verify only one set of Edge.Cuts items."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            # First outline
            set_board_outline(ir, width=100.0, height=50.0)

            # Second outline (should replace first)
            result = set_board_outline(ir, width=80.0, height=40.0)

            edge_items = [
                item for item in ir.board.graphicItems
                if getattr(item, "layer", None) == "Edge.Cuts"
            ]
            assert len(edge_items) == 4

            # Verify dimensions match the second call
            points = []
            for item in edge_items:
                points.append((item.start.X, item.start.Y))
                points.append((item.end.X, item.end.Y))

            unique_x = sorted(set(round(x, 2) for x, y in points))
            unique_y = sorted(set(round(y, 2) for x, y in points))
            assert unique_x == [0.0, 80.0]
            assert unique_y == [0.0, 40.0]


class TestAssignNetClass:
    """Test net class assignment to nets."""

    def test_assign_net_class(self):
        """Assign 'Power' class to VCC net, verify assignment in raw content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            result = assign_net_class(
                ir, pcb_path,
                net_name="VCC",
                net_class_name="Power",
            )

            assert result["net"] == "VCC"
            assert result["class"] == "Power"

            # Verify the raw content was modified
            raw = ir._parse_result.file_path.read_text()
            assert 'net_class "Power"' in raw
            assert 'add_net "VCC"' in raw

    def test_assign_net_class_creates_new_class(self):
        """Assigning to a nonexistent class creates the class block."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            assign_net_class(
                ir, pcb_path,
                net_name="GND",
                net_class_name="Ground",
            )

            raw = ir._parse_result.file_path.read_text()
            assert 'net_class "Ground"' in raw
            assert 'add_net "GND"' in raw

    def test_assign_net_class_nonexistent_net_raises(self):
        """Assigning a class to a nonexistent net raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            with pytest.raises(ValueError, match="not found"):
                assign_net_class(
                    ir, pcb_path,
                    net_name="NONEXISTENT",
                    net_class_name="Default",
                )


class TestModifyCopperZone:
    """Test copper zone modification by UUID."""

    def test_modify_clearance(self):
        """Add a zone, modify clearance, verify updated in board.zones."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            add_copper_zone(ir, pcb_path, net_name="GND", layer="F.Cu", clearance=0.5)
            zone_uuid = ir.board.zones[0].tstamp

            from kicad_agent.ops.pcb_ops import modify_copper_zone
            result = modify_copper_zone(ir, pcb_path, zone_uuid=zone_uuid, clearance=0.3)

            assert result["modified"] is True
            assert result["zone_uuid"] == zone_uuid
            assert "clearance" in result["updated_fields"]
            assert ir.board.zones[0].clearance == 0.3

    def test_modify_net_name(self):
        """Add a zone, change net_name, verify zone.net and zone.netName updated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            add_copper_zone(ir, pcb_path, net_name="GND", layer="F.Cu")
            zone_uuid = ir.board.zones[0].tstamp

            from kicad_agent.ops.pcb_ops import modify_copper_zone
            result = modify_copper_zone(ir, pcb_path, zone_uuid=zone_uuid, net_name="VCC")

            assert result["modified"] is True
            zone = ir.board.zones[0]
            assert zone.netName == "VCC"
            # Net number should resolve to VCC's number (2)
            assert zone.net == 2

    def test_modify_nonexistent_uuid(self):
        """modify_copper_zone raises ValueError for non-existent UUID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            from kicad_agent.ops.pcb_ops import modify_copper_zone
            with pytest.raises(ValueError, match="not found"):
                modify_copper_zone(ir, pcb_path, zone_uuid="nonexistent-uuid")

    def test_modify_returns_updated_fields(self):
        """Verify return dict lists only changed fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            add_copper_zone(ir, pcb_path, net_name="GND", layer="F.Cu", clearance=0.5)
            zone_uuid = ir.board.zones[0].tstamp

            from kicad_agent.ops.pcb_ops import modify_copper_zone
            result = modify_copper_zone(
                ir, pcb_path,
                zone_uuid=zone_uuid,
                clearance=0.3,
                priority=5,
            )

            assert "clearance" in result["updated_fields"]
            assert "priority" in result["updated_fields"]
            # net_name and layer should NOT be in updated_fields since not changed
            assert "net_name" not in result["updated_fields"]


class TestRemoveCopperZone:
    """Test copper zone removal by UUID or index."""

    def test_remove_by_uuid(self):
        """Add zone, remove by UUID, verify gone from board.zones."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            add_copper_zone(ir, pcb_path, net_name="GND", layer="F.Cu")
            zone_uuid = ir.board.zones[0].tstamp

            from kicad_agent.ops.pcb_ops import remove_copper_zone
            result = remove_copper_zone(ir, pcb_path, zone_uuid=zone_uuid)

            assert result["removed"] is True
            assert result["zone_uuid"] == zone_uuid
            assert len(ir.board.zones) == 0

    def test_remove_by_index(self):
        """Add zone, remove by index=0, verify gone."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            add_copper_zone(ir, pcb_path, net_name="GND", layer="F.Cu")

            from kicad_agent.ops.pcb_ops import remove_copper_zone
            result = remove_copper_zone(ir, pcb_path, zone_index=0)

            assert result["removed"] is True
            assert len(ir.board.zones) == 0

    def test_remove_no_identifier(self):
        """remove_copper_zone raises ValueError when neither UUID nor index provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            from kicad_agent.ops.pcb_ops import remove_copper_zone
            with pytest.raises(ValueError, match="Must specify"):
                remove_copper_zone(ir, pcb_path)

    def test_remove_nonexistent_uuid(self):
        """remove_copper_zone raises ValueError for non-existent UUID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            from kicad_agent.ops.pcb_ops import remove_copper_zone
            with pytest.raises(ValueError, match="not found"):
                remove_copper_zone(ir, pcb_path, zone_uuid="nonexistent-uuid")

    def test_remove_out_of_range_index(self):
        """remove_copper_zone raises IndexError for out-of-range index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pcb_path, ir = _create_minimal_pcb(Path(tmpdir))

            from kicad_agent.ops.pcb_ops import remove_copper_zone
            with pytest.raises(IndexError):
                remove_copper_zone(ir, pcb_path, zone_index=99)


class TestSetBoardOutlineOperation:
    """Test set_board_outline operation via executor dispatch."""

    def test_set_board_outline_operation(self):
        """Execute set_board_outline via executor, verify structured result."""
        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            pcb_path, _ = _create_minimal_pcb(tmpdir_path)

            op = Operation.model_validate({
                "root": {
                    "op_type": "set_board_outline",
                    "target_file": "test.kicad_pcb",
                    "width": 60.0,
                    "height": 40.0,
                }
            })

            executor = OperationExecutor(base_dir=tmpdir_path)
            result = executor.execute(op)

            assert result["success"] is True
            assert result["operation"] == "set_board_outline"
            assert result["details"]["outline_set"] is True
            assert result["details"]["width_mm"] == 60.0
            assert result["details"]["height_mm"] == 40.0
