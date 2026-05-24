"""Shared test fixtures for kicad-agent parser tests.

Provides paths to KiCad test fixture files copied into the project at:
    tests/fixtures/

These fixtures use KiCad's built-in Arduino_Mega and RaspberryPi-uHAT template
projects for testing all four file types (.kicad_sch, .kicad_pcb, .kicad_sym,
.kicad_mod). Fixtures are project-local to isolate from system KiCad changes.
"""

from pathlib import Path

import pytest

# Register LLM test fixtures from conftest_llm.py
pytest_plugins = ["conftest_llm"]

# Test fixture directory for copied KiCad files
FIXTURE_DIR = Path(__file__).parent / "fixtures"

# KiCad application templates directory (KiCad 10 on macOS)
# Kept as reference but fixtures use local copies
KICAD_TEMPLATES = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template")


@pytest.fixture
def arduino_mega_sch() -> Path:
    """Path to Arduino_Mega.kicad_sch from local fixtures.

    Returns:
        Path to a real KiCad schematic with components, wires, and labels.
    """
    return FIXTURE_DIR / "Arduino_Mega" / "Arduino_Mega.kicad_sch"


@pytest.fixture
def arduino_mega_pcb() -> Path:
    """Path to Arduino_Mega.kicad_pcb from local fixtures.

    Returns:
        Path to a real KiCad PCB with footprints, nets, and traces.
    """
    return FIXTURE_DIR / "Arduino_Mega" / "Arduino_Mega.kicad_pcb"


@pytest.fixture
def arduino_mounting_hole_mod() -> Path:
    """Path to MountingHole_3.2mm.kicad_mod from local fixtures.

    Returns:
        Path to a real KiCad footprint with pads and graphics.
    """
    return (
        FIXTURE_DIR
        / "Arduino_Mega"
        / "Arduino_MountingHole.pretty"
        / "MountingHole_3.2mm.kicad_mod"
    )


@pytest.fixture
def sample_sym_lib() -> Path:
    """Path to Regulator_Current.kicad_sym from local fixtures.

    Uses a small symbol library for fast regression testing.

    Returns:
        Path to a real KiCad symbol library file.
    """
    return FIXTURE_DIR / "Regulator_Current.kicad_sym"


@pytest.fixture
def raspberry_pi_sch() -> Path:
    """Path to RaspberryPi-uHAT.kicad_sch from local fixtures.

    Returns:
        Path to a real KiCad schematic (second template for diversity).
    """
    return FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"


@pytest.fixture
def raspberry_pi_pcb() -> Path:
    """Path to RaspberryPi-uHAT.kicad_pcb from local fixtures.

    Returns:
        Path to a real KiCad PCB (second template for diversity).
    """
    return FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_pcb"


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    """Temporary directory for test output files.

    Uses pytest's built-in tmp_path fixture for automatic cleanup.

    Returns:
        Path to a clean temporary directory.
    """
    return tmp_path
