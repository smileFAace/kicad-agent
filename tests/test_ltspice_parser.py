"""Tests for LTspice .asc parsing and simulation command extraction.

Covers:
- LTSPICE-01: .asc file parses into structured component/net/simulation data
- LTSPICE-02: Component values, positions, orientations extractable
- LTSPICE-04: Simulation commands parseable from directives
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_agent.ltspice.asc_parser import parse_asc
from kicad_agent.ltspice.types import (
    LTspiceComponent,
    LTspiceDirective,
    LTspiceFlag,
    LTspiceSchematic,
    LTspiceWire,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ltspice"
BASIC_RC_ASC = FIXTURE_DIR / "basic_rc.asc"


class TestAscParser:
    """Tests for parse_asc() function."""

    def test_1_parse_returns_schematic_with_components(self) -> None:
        """parse_asc('basic_rc.asc') returns LTspiceSchematic with R1, C1, V1."""
        result = parse_asc(BASIC_RC_ASC)

        assert isinstance(result, LTspiceSchematic)
        refs = {c.reference for c in result.components}
        assert "R1" in refs
        assert "C1" in refs
        assert "V1" in refs

    def test_2_component_has_value_position_rotation_symbol(self) -> None:
        """R1 component has value='1k', position as ints, rotation='R0', symbol='res'."""
        result = parse_asc(BASIC_RC_ASC)

        r1 = next(c for c in result.components if c.reference == "R1")
        assert r1.value == "1k"
        assert isinstance(r1.position_x, int)
        assert isinstance(r1.position_y, int)
        assert r1.rotation == "R0"
        assert r1.symbol == "res"

    def test_3_wires_list_non_empty(self) -> None:
        """Wires list is non-empty with LTspiceWire entries having (x1,y1,x2,y2)."""
        result = parse_asc(BASIC_RC_ASC)

        assert len(result.wires) > 0
        for wire in result.wires:
            assert isinstance(wire, LTspiceWire)
            assert isinstance(wire.x1, int)
            assert isinstance(wire.y1, int)
            assert isinstance(wire.x2, int)
            assert isinstance(wire.y2, int)

    def test_4_flags_contain_gnd(self) -> None:
        """Flags list contains at least one entry with text='0' (GND symbol)."""
        result = parse_asc(BASIC_RC_ASC)

        assert len(result.flags) > 0
        gnd_flags = [f for f in result.flags if f.text == "0"]
        assert len(gnd_flags) >= 1

    def test_5_directives_contain_tran(self) -> None:
        """Directives list contains '.tran 0 1ms 0 1u' parsed via sim_commands."""
        result = parse_asc(BASIC_RC_ASC)

        assert len(result.directives) > 0
        tran_directives = [d for d in result.directives if ".tran" in d.text]
        assert len(tran_directives) >= 1
        assert ".tran 0 1ms 0 1u" in tran_directives[0].text

    def test_6_nonexistent_file_raises_file_not_found(self) -> None:
        """parse_asc with non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            parse_asc("/nonexistent/path/circuit.asc")

    def test_7_path_traversal_raises_value_error(self) -> None:
        """parse_asc with malformed path raises ValueError (path traversal protection)."""
        with pytest.raises(ValueError, match="[Tt]raversal|[Pp]ath|[Ii]nvalid"):
            parse_asc("/some/path/../../../etc/passwd.asc")


class TestSimCommands:
    """Tests for parse_simulation_command() function.

    Populated in Task 2.
    """
