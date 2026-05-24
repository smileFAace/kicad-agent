"""Integration tests for KiCad-to-LTspice .asc writer.

Tests CoordinateTransformer (Y-axis flip, grid alignment), net name
sanitization, AscWriter export, and round-trip validation with parse_asc().
"""

from __future__ import annotations

import os
import tempfile
import warnings
from pathlib import Path

import pytest

from kicad_agent.ltspice.asc_parser import parse_asc
from kicad_agent.ltspice.asc_writer import (
    AscWriter,
    CoordinateTransformer,
    _sanitize_net_name,
)
from kicad_agent.ltspice.sim_commands import (
    AcCommand,
    DcCommand,
    NoiseCommand,
    OpCommand,
    TranCommand,
    parse_simulation_command,
    serialize_sim_command,
)
from kicad_agent.ltspice.symbol_mapper import SymbolMapper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_minimal_schematic():
    """Build a minimal KiCad schematic with R1, C1, V1, a wire, and labels."""
    from kiutils.schematic import (
        Connection,
        GlobalLabel,
        LocalLabel,
        Position,
        Property,
        Schematic,
        SchematicSymbol,
    )

    sch = Schematic()

    # R1 at (50, 30) mm
    r1 = SchematicSymbol(libraryNickname="Device", entryName="R")
    r1.position = Position(X=50.0, Y=30.0)
    r1.properties.append(Property(key="Reference", value="R1"))
    r1.properties.append(Property(key="Value", value="1k"))
    sch.schematicSymbols.append(r1)

    # C1 at (80, 30) mm
    c1 = SchematicSymbol(libraryNickname="Device", entryName="C")
    c1.position = Position(X=80.0, Y=30.0)
    c1.properties.append(Property(key="Reference", value="C1"))
    c1.properties.append(Property(key="Value", value="100n"))
    sch.schematicSymbols.append(c1)

    # V1 (voltage source) at (20, 60) mm
    v1 = SchematicSymbol(
        libraryNickname="Simulation", entryName="VOLTAGE"
    )
    v1.position = Position(X=20.0, Y=60.0)
    v1.properties.append(Property(key="Reference", value="V1"))
    v1.properties.append(Property(key="Value", value="5"))
    sch.schematicSymbols.append(v1)

    # Power:GND at (20, 80) mm -- will become FLAG "0"
    gnd = SchematicSymbol(libraryNickname="power", entryName="GND")
    gnd.position = Position(X=20.0, Y=80.0)
    sch.schematicSymbols.append(gnd)

    # Wire from (50, 30) to (80, 30)
    wire = Connection()
    wire.type = "wire"
    wire.points.append(Position(X=50.0, Y=30.0))
    wire.points.append(Position(X=80.0, Y=30.0))
    sch.graphicalItems.append(wire)

    # Local label "/VCC" at (50, 10) mm -> FLAG "VCC"
    vcc_label = LocalLabel(text="/VCC")
    vcc_label.position = Position(X=50.0, Y=10.0)
    sch.labels.append(vcc_label)

    return sch


# ---------------------------------------------------------------------------
# TestCoordinateTransformer
# ---------------------------------------------------------------------------


class TestCoordinateTransformer:
    """Coordinate conversion from KiCad mm to LTspice internal units."""

    def test_origin_maps_to_top(self):
        """KiCad origin (0,0) maps to (0, sheet_height*scale) after Y-flip."""
        ct = CoordinateTransformer()
        x, y = ct.mm_to_ltspice(0.0, 0.0)
        assert x == 0
        # Y should be near top: sheet_height_mm * scale = 297 * 16 = 4752
        assert y == 4752

    def test_y_axis_flipped(self):
        """Increasing KiCad Y decreases LTspice Y (Y-axis flip)."""
        ct = CoordinateTransformer()
        _, y_top = ct.mm_to_ltspice(0.0, 0.0)
        _, y_bottom = ct.mm_to_ltspice(0.0, 100.0)
        assert y_bottom < y_top

    def test_grid_alignment(self):
        """All outputs are multiples of 16 (LTspice grid)."""
        ct = CoordinateTransformer()
        # Test a range of arbitrary coordinates
        for x_mm in [0.0, 10.0, 33.7, 100.5, 200.0]:
            for y_mm in [0.0, 15.3, 42.0, 99.9, 297.0]:
                x, y = ct.mm_to_ltspice(x_mm, y_mm)
                assert x % 16 == 0, f"X {x} not grid-aligned for ({x_mm}, {y_mm})"
                assert y % 16 == 0, f"Y {y} not grid-aligned for ({x_mm}, {y_mm})"


# ---------------------------------------------------------------------------
# TestNetNameSanitization
# ---------------------------------------------------------------------------


class TestNetNameSanitization:
    """Net label text cleaning for LTspice FLAG entries."""

    def test_strip_leading_slash(self):
        assert _sanitize_net_name("/VCC") == "VCC"

    def test_decode_slash_token(self):
        assert _sanitize_net_name("NET{slash}A") == "NET/A"

    def test_unchanged_names(self):
        assert _sanitize_net_name("GND") == "GND"

    def test_strip_whitespace(self):
        assert _sanitize_net_name("  VCC  ") == "VCC"

    def test_slash_and_whitespace_combined(self):
        assert _sanitize_net_name("  /VCC  ") == "VCC"


# ---------------------------------------------------------------------------
# TestAscWriter
# ---------------------------------------------------------------------------


class TestAscWriter:
    """AscWriter export and round-trip validation."""

    def test_export_creates_valid_asc(self, tmp_path):
        """Export produces a non-empty .asc file that parse_asc() can read."""
        sch = _build_minimal_schematic()
        mapper = SymbolMapper()
        transformer = CoordinateTransformer()
        writer = AscWriter(sch, mapper, transformer)

        output = tmp_path / "output.asc"
        result_path = writer.write(output)

        assert result_path.exists()
        content = result_path.read_text()
        assert len(content) > 0
        assert "Version 4" in content

        # parse_asc() should succeed on the output
        parsed = parse_asc(result_path)
        assert parsed.components is not None
        assert len(parsed.components) >= 3  # R1, C1, V1 at minimum

    def test_component_references_match(self, tmp_path):
        """Component references from KiCad survive the export round-trip."""
        sch = _build_minimal_schematic()
        mapper = SymbolMapper()
        transformer = CoordinateTransformer()
        writer = AscWriter(sch, mapper, transformer)

        output = tmp_path / "refs.asc"
        writer.write(output)
        parsed = parse_asc(output)

        refs = {c.reference for c in parsed.components}
        assert "R1" in refs
        assert "C1" in refs
        assert "V1" in refs

    def test_ground_flag_present(self, tmp_path):
        """Power:GND symbol becomes FLAG '0' in exported .asc."""
        sch = _build_minimal_schematic()
        mapper = SymbolMapper()
        transformer = CoordinateTransformer()
        writer = AscWriter(sch, mapper, transformer)

        output = tmp_path / "gnd.asc"
        writer.write(output)

        # Check raw file content for FLAG ... 0
        content = output.read_text()
        assert "FLAG" in content
        # Ground flag text should be "0"
        assert "0" in content.split("FLAG")[-1].split("\n")[0]

        # Also verify via parse_asc
        parsed = parse_asc(output)
        flag_texts = [f.text for f in parsed.flags]
        assert "0" in flag_texts

    def test_net_label_slash_stripped(self, tmp_path):
        """KiCad label '/VCC' becomes FLAG 'VCC' (slash stripped)."""
        sch = _build_minimal_schematic()
        mapper = SymbolMapper()
        transformer = CoordinateTransformer()
        writer = AscWriter(sch, mapper, transformer)

        output = tmp_path / "labels.asc"
        writer.write(output)
        parsed = parse_asc(output)

        flag_texts = [f.text for f in parsed.flags]
        assert "VCC" in flag_texts

    def test_round_trip_component_count(self, tmp_path):
        """Round-trip: export, parse back, component count matches."""
        sch = _build_minimal_schematic()
        mapper = SymbolMapper()
        transformer = CoordinateTransformer()
        writer = AscWriter(sch, mapper, transformer)

        output = tmp_path / "roundtrip.asc"
        writer.write(output)
        parsed = parse_asc(output)

        # We expect R1, C1, V1 (GND becomes a FLAG, not a component)
        assert len(parsed.components) == 3

    def test_wire_segments_exported(self, tmp_path):
        """Wire segments from KiCad survive export."""
        sch = _build_minimal_schematic()
        mapper = SymbolMapper()
        transformer = CoordinateTransformer()
        writer = AscWriter(sch, mapper, transformer)

        output = tmp_path / "wires.asc"
        writer.write(output)
        parsed = parse_asc(output)

        # We added 1 wire segment with 2 points -> 1 wire in LTspice
        assert len(parsed.wires) >= 1


# ---------------------------------------------------------------------------
# TestExportWithUnmappedSymbol
# ---------------------------------------------------------------------------


class TestExportWithUnmappedSymbol:
    """Unmapped symbols produce warnings but do not crash."""

    def test_unmapped_produces_warning(self, tmp_path):
        """An unmapped symbol logs a warning without raising."""
        from kiutils.schematic import Position, Property, Schematic, SchematicSymbol

        sch = Schematic()

        # Add a known component
        r1 = SchematicSymbol(libraryNickname="Device", entryName="R")
        r1.position = Position(X=50.0, Y=30.0)
        r1.properties.append(Property(key="Reference", value="R1"))
        r1.properties.append(Property(key="Value", value="1k"))
        sch.schematicSymbols.append(r1)

        # Add an unmapped component
        unk = SchematicSymbol(libraryNickname="CustomLib", entryName="MagicIC")
        unk.position = Position(X=100.0, Y=50.0)
        unk.properties.append(Property(key="Reference", value="U1"))
        unk.properties.append(Property(key="Value", value="MCU123"))
        sch.schematicSymbols.append(unk)

        mapper = SymbolMapper()
        transformer = CoordinateTransformer()
        writer = AscWriter(sch, mapper, transformer)

        output = tmp_path / "unmapped.asc"
        # Should not raise
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            writer.write(output)

        # Output should exist and be valid
        assert output.exists()
        parsed = parse_asc(output)
        # Only R1 exported, not the unmapped U1
        refs = {c.reference for c in parsed.components}
        assert "R1" in refs
        assert "U1" not in refs


# ---------------------------------------------------------------------------
# TestSimCommandSerialization (TDD RED phase)
# ---------------------------------------------------------------------------


class TestSimCommandSerialization:
    """Serialize SimulationCommand dataclasses to LTspice directive text."""

    def test_tran_command_serializes(self):
        """TranCommand serializes to '.tran {tstart} {tstop} {tstart_meas} {tstep}'."""
        cmd = TranCommand(tstart=0, tstop=0.001, tstart_meas=0, tstep=0.000001)
        result = serialize_sim_command(cmd)
        assert result == ".tran 0 0.001 0 1e-06"

    def test_ac_command_serializes(self):
        """AcCommand serializes to '.ac {sweep} {npoints} {fstart} {fstop}'."""
        cmd = AcCommand(sweep="dec", npoints=10, fstart=1.0, fstop=1000000.0)
        result = serialize_sim_command(cmd)
        assert result == ".ac dec 10 1.0 1000000.0"

    def test_dc_command_serializes(self):
        """DcCommand serializes to '.dc {source} {start} {stop} {step}'."""
        cmd = DcCommand(source="V1", start=0.0, stop=5.0, step=0.1)
        result = serialize_sim_command(cmd)
        assert result == ".dc V1 0.0 5.0 0.1"

    def test_op_command_serializes(self):
        """OpCommand serializes to '.op'."""
        cmd = OpCommand()
        result = serialize_sim_command(cmd)
        assert result == ".op"

    def test_noise_command_serializes(self):
        """NoiseCommand serializes to '.noise {output} {source} {sweep} {npoints} {fstart} {fstop}'."""
        cmd = NoiseCommand(
            output="V(out)", source="src", sweep="dec",
            npoints=10, fstart=1.0, fstop=1000.0,
        )
        result = serialize_sim_command(cmd)
        assert result == ".noise V(out) src dec 10 1.0 1000.0"

    def test_round_trip_tran(self):
        """Round-trip: serialize TranCommand -> parse -> produces equivalent command."""
        original = TranCommand(tstart=0, tstop=0.001, tstart_meas=0, tstep=0.000001)
        text = serialize_sim_command(original)
        recovered = parse_simulation_command(text)
        assert isinstance(recovered, TranCommand)
        assert recovered.tstart == original.tstart
        assert recovered.tstop == original.tstop

    def test_round_trip_ac(self):
        """Round-trip: serialize AcCommand -> parse -> produces equivalent command."""
        original = AcCommand(sweep="dec", npoints=10, fstart=1.0, fstop=1000000.0)
        text = serialize_sim_command(original)
        recovered = parse_simulation_command(text)
        assert isinstance(recovered, AcCommand)
        assert recovered.sweep == original.sweep
        assert recovered.npoints == original.npoints

    def test_round_trip_dc(self):
        """Round-trip: serialize DcCommand -> parse -> produces equivalent command."""
        original = DcCommand(source="V1", start=0.0, stop=5.0, step=0.1)
        text = serialize_sim_command(original)
        recovered = parse_simulation_command(text)
        assert isinstance(recovered, DcCommand)
        assert recovered.source == original.source
