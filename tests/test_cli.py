"""CLI test suite -- subprocess invocation of kicad-agent command."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_ADD = json.dumps({
    "op_type": "add_component",
    "target_file": "tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch",
    "library_id": "Device:R_Small_US",
    "position": {"x": 50.0, "y": 30.0},
})

INVALID_JSON_STR = "{bad json}"

PATH_TRAVERSAL = json.dumps({
    "op_type": "add_component",
    "target_file": "../../../etc/passwd",
    "library_id": "Device:R",
    "position": {"x": 1, "y": 1},
})

VALID_MOVE = json.dumps({
    "op_type": "move_component",
    "target_file": "tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch",
    "reference": "J1",
    "position": {"x": 100.0, "y": 200.0},
})


def _run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI via ``python -m kicad_agent.cli``."""
    cmd = [sys.executable, "-m", "kicad_agent.cli", *args]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


# ---------------------------------------------------------------------------
# Test 1: --schema exits 0 and prints valid JSON Schema
# ---------------------------------------------------------------------------
def test_schema_flag_returns_valid_json_schema() -> None:
    result = _run("--schema")
    assert result.returncode == 0
    schema = json.loads(result.stdout)
    assert "properties" in schema


# ---------------------------------------------------------------------------
# Test 2: Valid inline JSON exits 0
# ---------------------------------------------------------------------------
def test_valid_inline_json_exits_zero() -> None:
    result = _run(VALID_ADD)
    assert result.returncode == 0
    assert "[OK]" in result.stdout or "add_component" in result.stdout


# ---------------------------------------------------------------------------
# Test 3: Invalid JSON exits 1
# ---------------------------------------------------------------------------
def test_invalid_json_exits_nonzero() -> None:
    result = _run(INVALID_JSON_STR)
    assert result.returncode != 0
    assert result.stderr != "" or "[ERROR]" in result.stdout


# ---------------------------------------------------------------------------
# Test 4: --dry-run with valid JSON exits 0
# ---------------------------------------------------------------------------
def test_dry_run_valid_exits_zero() -> None:
    result = _run("--dry-run", VALID_ADD)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Test 5: --dry-run with invalid operation exits 1
# ---------------------------------------------------------------------------
def test_dry_run_invalid_exits_nonzero() -> None:
    bad_op = json.dumps({"op_type": "nonexistent_op", "target_file": "x.kicad_sch"})
    result = _run("--dry-run", bad_op)
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# Test 6: JSON file input exits 0
# ---------------------------------------------------------------------------
def test_json_file_input_exits_zero() -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tmp:
        tmp.write(VALID_MOVE)
        tmp_path = tmp.name
    try:
        result = _run(tmp_path)
        assert result.returncode == 0
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 7: Nonexistent file exits 1
# ---------------------------------------------------------------------------
def test_nonexistent_file_exits_nonzero() -> None:
    result = _run("/no/such/path/op.json")
    assert result.returncode != 0
    assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Test 8: Path traversal in target_file exits 1
# ---------------------------------------------------------------------------
def test_path_traversal_exits_nonzero() -> None:
    result = _run(PATH_TRAVERSAL)
    assert result.returncode != 0
    assert "[ERROR]" in result.stdout or "traversal" in result.stdout.lower() or "traversal" in result.stderr.lower()
