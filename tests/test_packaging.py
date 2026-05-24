"""Packaging smoke tests: build system, versioning, CLI entry point, and installability."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestVersion:
    """Verify dynamic version from importlib.metadata / setuptools-scm."""

    def test_version_is_string(self) -> None:
        """__version__ is a non-empty string matching a semver-like pattern."""
        from kicad_agent import __version__

        assert isinstance(__version__, str)
        assert __version__, "__version__ must not be empty"
        assert re.match(r"^\d+\.\d+\.\d+", __version__), f"Version {__version__!r} not semver-like"

    def test_version_not_zero(self) -> None:
        """__version__ is not 0.0.0, which would indicate setuptools-scm failure."""
        from kicad_agent import __version__

        assert __version__ != "0.0.0", (
            "Version is 0.0.0 -- setuptools-scm likely failed to detect git version"
        )


class TestPublicImports:
    """Verify the public API surface is importable."""

    def test_import_kicad_agent(self) -> None:
        import kicad_agent

        assert hasattr(kicad_agent, "__version__")

    def test_cli_entry_point_module(self) -> None:
        from kicad_agent.cli import main

        assert callable(main)

    def test_handler_imports(self) -> None:
        from kicad_agent.handler import format_result, handle_operation, validate_operation

        assert callable(validate_operation)
        assert callable(handle_operation)
        assert callable(format_result)


class TestCLI:
    """Verify CLI entry point behavior."""

    def test_schema_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--schema prints valid JSON with a 'properties' key (the operation schema)."""
        from kicad_agent.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--schema"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "properties" in data, "Schema JSON missing 'properties' key"


@pytest.mark.slow
class TestBuild:
    """Integration tests that exercise the build toolchain."""

    @pytest.mark.skipif(not shutil.which("python"), reason="python not available")
    def test_build_produces_wheel(self, tmp_path: Path) -> None:
        """python -m build produces a wheel and sdist in dist/."""
        result = subprocess.run(
            ["python", "-m", "build"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"Build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

        dist_dir = REPO_ROOT / "dist"
        wheels = list(dist_dir.glob("*.whl"))
        sdists = list(dist_dir.glob("*.tar.gz"))

        assert wheels, "No wheel file produced in dist/"
        assert sdists, "No sdist file produced in dist/"

        # Wheel should contain package files but not tests
        whl_check = subprocess.run(
            ["unzip", "-l", str(wheels[0])],
            capture_output=True,
            text=True,
        )
        assert "kicad_agent/__init__.py" in whl_check.stdout, "Wheel missing kicad_agent/__init__.py"
        assert "tests/" not in whl_check.stdout, "Wheel should not contain tests/"

        # Clean up build artifacts
        shutil.rmtree(dist_dir, ignore_errors=True)
