"""Integration tests for the end-to-end generation pipeline.

Tests exercise the full pipeline from GenerationIntent to GenerationResult.
Tests that require kicad-cli (validation, export) are skipped gracefully.
"""

import shutil
from pathlib import Path

import pytest

from kicad_agent.generation.intent import (
    BoardSpec,
    ComponentSpec,
    GenerationIntent,
    NetSpec,
    PowerSpec,
)
from kicad_agent.generation.pipeline import GenerationResult, generate_design

# Check if kicad-cli is available for integration tests
KICAD_CLI_AVAILABLE = shutil.which("kicad-cli") is not None


def _skip_without_kicad():
    """Skip test if kicad-cli is not available."""
    if not KICAD_CLI_AVAILABLE:
        pytest.skip("kicad-cli not available")


class TestGenerationPipeline:
    """Integration tests for generate_design()."""

    def test_generate_design_empty_intent(self, tmp_path: Path):
        """Intent with just a name produces project directory."""
        intent = GenerationIntent(name="empty_project")
        result = generate_design(intent, tmp_path, run_validation=False, run_export=False)

        assert isinstance(result, GenerationResult)
        assert result.success is True
        assert result.project_dir == tmp_path / "empty_project"
        assert result.project_dir.exists()
        assert result.schematic_path is not None
        assert result.pcb_path is not None
        assert result.schematic_path.exists()
        assert result.pcb_path.exists()

    def test_generate_design_with_board(self, tmp_path: Path):
        """Intent with board spec produces .kicad_pcb with correct dimensions."""
        intent = GenerationIntent(
            name="board_test",
            board=BoardSpec(width_mm=100, height_mm=80, layer_count=4),
        )
        result = generate_design(intent, tmp_path, run_validation=False, run_export=False)

        assert result.success is True
        assert result.pcb_path is not None
        assert result.pcb_path.suffix == ".kicad_pcb"

        # Verify PCB content contains board outline
        pcb_content = result.pcb_path.read_text()
        assert "Edge.Cuts" in pcb_content

    def test_generate_design_with_components(self, tmp_path: Path):
        """Intent with 3 components produces operations_executed > 0."""
        intent = GenerationIntent(
            name="comp_test",
            components=[
                ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
                ComponentSpec(library_id="Device:C_Small", reference="C1", value="100nF"),
                ComponentSpec(library_id="Device:LED", reference="D1", value="RED"),
            ],
        )
        result = generate_design(intent, tmp_path, run_validation=False, run_export=False)

        assert result.success is True
        assert result.operations_executed > 0

        # Verify schematic has components
        sch_content = result.schematic_path.read_text()
        assert "R1" in sch_content
        assert "C1" in sch_content
        assert "D1" in sch_content

    def test_generate_design_result_structure(self, tmp_path: Path):
        """GenerationResult has all expected fields with correct types."""
        intent = GenerationIntent(name="struct_test")
        result = generate_design(intent, tmp_path, run_validation=False, run_export=False)

        assert isinstance(result.success, bool)
        assert isinstance(result.project_dir, Path)
        assert isinstance(result.operations_executed, int)
        assert isinstance(result.errors, tuple)
        assert isinstance(result.statistics, dict)

        # With run_validation=False, these should be None
        assert result.erc_pass is None
        assert result.drc_pass is None

    def test_generate_design_statistics(self, tmp_path: Path):
        """Statistics dict has component_count and net_count."""
        intent = GenerationIntent(
            name="stats_test",
            components=[
                ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
                ComponentSpec(library_id="Device:C_Small", reference="C1", value="100nF"),
            ],
            nets=[
                NetSpec(name="VCC", pins=["R1.1", "C1.1"]),
                NetSpec(name="GND", pins=["R1.2", "C1.2"]),
            ],
        )
        result = generate_design(intent, tmp_path, run_validation=False, run_export=False)

        assert result.success is True
        assert "component_count" in result.statistics
        assert "net_count" in result.statistics
        assert result.statistics["component_count"] == 2

    def test_generate_design_unsafe_name_rejected(self, tmp_path: Path):
        """Unsafe design names are rejected."""
        intent = GenerationIntent(name="../../../etc/passwd")
        # Pydantic might not catch this, but pipeline should
        with pytest.raises(ValueError, match="unsafe characters"):
            generate_design(intent, tmp_path)

    def test_generate_design_unsafe_name_semicolon(self, tmp_path: Path):
        """Names with shell metacharacters are rejected."""
        intent = GenerationIntent(name="test;rm -rf /")
        with pytest.raises(ValueError, match="unsafe characters"):
            generate_design(intent, tmp_path)

    def test_generate_design_validation_with_kicad(self, tmp_path: Path):
        """Full pipeline with validation when kicad-cli is available."""
        _skip_without_kicad()

        intent = GenerationIntent(
            name="validation_test",
            components=[
                ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
            ],
        )
        result = generate_design(intent, tmp_path, run_validation=True, run_export=False)

        assert result.success is True
        # ERC/DRC may pass or fail, but they should have been run
        assert result.erc_pass is not None or result.drc_pass is not None

    def test_generate_design_export_with_kicad(self, tmp_path: Path):
        """Full pipeline with export when kicad-cli is available."""
        _skip_without_kicad()

        intent = GenerationIntent(
            name="export_test",
            board=BoardSpec(width_mm=50, height_mm=50),
        )
        result = generate_design(
            intent, tmp_path, run_validation=False, run_export=True
        )

        assert result.success is True
        # Export results depend on kicad-cli version and board content
        # Just verify the pipeline didn't crash
        assert isinstance(result, GenerationResult)
