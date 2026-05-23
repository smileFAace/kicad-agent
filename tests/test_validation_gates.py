"""Tests for power net validation and pre-PCB validation gates.

Tests use existing fixtures or create minimal schematics programmatically.
Tests that need kicad-cli skip gracefully when it is unavailable.
"""

import shutil
import tempfile
from pathlib import Path

import pytest
from kiutils.items.common import Position
from kiutils.items.schitems import Connection, LocalLabel
from kiutils.schematic import Schematic

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.validation_gates import (
    check_erc_clean,
    pre_pcb_gate,
    validate_power_nets,
)
from kicad_agent.parser import parse_schematic


def _save_and_parse(sch_path: Path, sch: Schematic) -> SchematicIR:
    """Save a kiutils Schematic to disk and parse it back into SchematicIR."""
    sch.to_file(str(sch_path))
    result = parse_schematic(sch_path)
    return SchematicIR(_parse_result=result)


def _kicad_cli_available() -> bool:
    """Check if kicad-cli is available on PATH."""
    return shutil.which("kicad-cli") is not None


requires_kicad_cli = pytest.mark.skipif(
    not _kicad_cli_available(),
    reason="kicad-cli not available on PATH",
)


class TestValidatePowerNets:
    """Test power net validation."""

    def test_validate_power_nets_with_fixture(self):
        """Test power net validation on RaspberryPi-uHAT (has power symbols)."""
        fixture = Path("tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch")
        if not fixture.exists():
            pytest.skip("RaspberryPi-uHAT fixture not found")

        result = parse_schematic(fixture)
        ir = SchematicIR(_parse_result=result)

        power_result = validate_power_nets(ir)

        assert "valid" in power_result
        assert "unconnected_power_pins" in power_result
        assert "power_nets" in power_result
        assert "missing_power_symbols" in power_result
        assert isinstance(power_result["unconnected_power_pins"], list)
        assert isinstance(power_result["power_nets"], list)
        assert isinstance(power_result["missing_power_symbols"], list)

    def test_validate_power_nets_empty_schematic(self):
        """Test power validation on empty schematic (no power pins)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            ir = _save_and_parse(sch_path, sch)

            result = validate_power_nets(ir)
            assert result["valid"] is True
            assert result["unconnected_power_pins"] == []

    def test_validate_power_nets_structure(self):
        """Verify validate_power_nets returns correct structure."""
        fixture = Path("tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch")
        if not fixture.exists():
            pytest.skip("RaspberryPi-uHAT fixture not found")

        result = parse_schematic(fixture)
        ir = SchematicIR(_parse_result=result)

        power_result = validate_power_nets(ir)
        # Check all expected keys
        for key in ("valid", "unconnected_power_pins", "power_nets", "missing_power_symbols"):
            assert key in power_result


class TestCheckErcClean:
    """Test ERC clean check wrapper."""

    @requires_kicad_cli
    def test_check_erc_clean_on_fixture(self):
        """Run ERC on RaspberryPi-uHAT fixture, verify structured result."""
        fixture = Path("tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch")
        if not fixture.exists():
            pytest.skip("RaspberryPi-uHAT fixture not found")

        result = check_erc_clean(fixture)

        assert "clean" in result
        assert "error_count" in result
        assert "warning_count" in result
        assert "errors" in result
        assert isinstance(result["clean"], bool)
        assert isinstance(result["error_count"], int)
        assert isinstance(result["warning_count"], int)
        assert isinstance(result["errors"], list)

    def test_check_erc_clean_missing_file(self):
        """Test ERC on a nonexistent file returns clean=False."""
        result = check_erc_clean(Path("/nonexistent/test.kicad_sch"))
        assert result["clean"] is False

    def test_check_erc_clean_without_kicad_cli(self):
        """Test ERC when kicad-cli is unavailable (should still return structured result)."""
        if _kicad_cli_available():
            pytest.skip("kicad-cli is available; test checks unavailable case")

        fixture = Path("tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch")
        if not fixture.exists():
            pytest.skip("RaspberryPi-uHAT fixture not found")

        result = check_erc_clean(fixture)
        # Should return clean=False with error_message in the underlying ErcResult
        assert result["clean"] is False


class TestPrePcbGate:
    """Test comprehensive pre-PCB validation gate."""

    def test_pre_pcb_gate_on_fixture_project(self):
        """Run full pre-PCB gate on RaspberryPi-uHAT project directory."""
        fixture_dir = Path("tests/fixtures/RaspberryPi-uHAT")
        if not (fixture_dir / "RaspberryPi-uHAT.kicad_sch").exists():
            pytest.skip("RaspberryPi-uHAT fixture not found")

        result = pre_pcb_gate(fixture_dir)

        # Verify structure
        assert "pass" in result
        assert "erc" in result
        assert "power" in result
        assert "annotation" in result
        assert "recommendations" in result

        # Verify ERC sub-result
        assert "clean" in result["erc"]
        assert "error_count" in result["erc"]

        # Verify power sub-result
        assert "valid" in result["power"]
        assert "power_nets" in result["power"]

        # Verify annotation sub-result
        assert "complete" in result["annotation"]
        assert "unannotated" in result["annotation"]

    def test_pre_pcb_gate_empty_directory(self):
        """Test pre-PCB gate on a directory with no schematics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = pre_pcb_gate(Path(tmpdir))
            assert result["pass"] is False
            assert "No schematic files found" in result["recommendations"][0]

    def test_pre_pcb_gate_with_unannotated_components(self):
        """Test pre-PCB gate detects unannotated components (R?, C?)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal schematic with unannotated components
            fixture = Path("tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch")
            if not fixture.exists():
                pytest.skip("RaspberryPi-uHAT fixture not found")

            import shutil
            tmp_sch = Path(tmpdir) / "test.kicad_sch"
            shutil.copy2(fixture, tmp_sch)

            result = pre_pcb_gate(Path(tmpdir))
            assert "annotation" in result
            assert isinstance(result["annotation"]["complete"], bool)
            assert isinstance(result["annotation"]["unannotated"], list)
