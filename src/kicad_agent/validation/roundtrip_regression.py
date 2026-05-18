"""Comprehensive round-trip fidelity regression test runner.

Scans a fixture directory recursively for KiCad files of all four types
(.kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod) and runs the two-pass
round-trip stability test on each file. Collects results into a
RegressionSuiteResult for programmatic access and summary reporting.

Usage:
    from kicad_agent.validation.roundtrip_regression import run_regression_suite

    result = run_regression_suite(fixture_dir, tmp_dir)
    print(f"PASS: {result.passed}/{result.total_files} files stable")
    assert result.all_passed
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from kicad_agent.validation.roundtrip import round_trip_compare
from kicad_agent.validation.constants import FILE_TYPE_NAMES

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegressionResult:
    """Result of a round-trip regression test on a single file.

    Attributes:
        file_path: Path to the tested file.
        file_type: One of 'schematic', 'pcb', 'symbol_lib', 'footprint'.
        is_stable: True if pass1 output is byte-identical to pass2 output.
        uuid_preserved: True if UUID count matches original (PCB/footprint only).
            None for file types that don't have UUIDs (schematic, symbol_lib).
        error: Error message if any step failed, None on success.
    """

    file_path: Path
    file_type: str
    is_stable: bool
    uuid_preserved: Optional[bool] = None
    error: Optional[str] = None


@dataclass
class RegressionSuiteResult:
    """Aggregated results of the full regression test suite.

    Attributes:
        total_files: Number of KiCad files discovered and tested.
        passed: Number of files that passed the stability test.
        failed: Number of files that failed the stability test.
        results: Detailed per-file results.
        all_passed: True if every file passed (passed == total_files).
    """

    total_files: int = 0
    passed: int = 0
    failed: int = 0
    results: list[RegressionResult] = field(default_factory=list)
    all_passed: bool = False


def _scan_fixture_files(fixture_dir: Path) -> list[tuple[Path, str]]:
    """Recursively scan fixture_dir for KiCad files.

    Args:
        fixture_dir: Root directory to scan for KiCad files.

    Returns:
        List of (path, file_type) tuples for each discovered file.
    """
    discovered: list[tuple[Path, str]] = []
    for path in sorted(fixture_dir.rglob("*")):
        if path.is_file() and path.suffix in FILE_TYPE_NAMES:
            file_type = FILE_TYPE_NAMES[path.suffix]
            discovered.append((path, file_type))
    return discovered


def run_regression_suite(
    fixture_dir: Path,
    tmp_dir: Path,
) -> RegressionSuiteResult:
    """Run the full round-trip regression test suite.

    Scans fixture_dir recursively for all KiCad file types, runs
    two-pass round-trip stability on each, and collects results.

    Args:
        fixture_dir: Directory containing KiCad fixture files.
        tmp_dir: Temporary directory for intermediate round-trip files.
            Each fixture gets its own subdirectory to avoid collisions.

    Returns:
        RegressionSuiteResult with per-file details and aggregate status.
    """
    files = _scan_fixture_files(fixture_dir)
    results: list[RegressionResult] = []

    for file_path, file_type in files:
        # Create a dedicated temp subdir per file to avoid name collisions
        rel = file_path.relative_to(fixture_dir)
        file_tmp = tmp_dir / rel.parent
        file_tmp.mkdir(parents=True, exist_ok=True)

        rt_result = round_trip_compare(file_path, file_tmp)

        reg_result = RegressionResult(
            file_path=file_path,
            file_type=file_type,
            is_stable=rt_result.is_stable,
            uuid_preserved=rt_result.uuid_preserved,
            error=rt_result.error,
        )
        results.append(reg_result)

    passed = sum(1 for r in results if r.is_stable)
    failed = len(results) - passed
    all_passed = failed == 0 and len(results) > 0

    suite_result = RegressionSuiteResult(
        total_files=len(results),
        passed=passed,
        failed=failed,
        results=results,
        all_passed=all_passed,
    )

    # Log summary
    uuid_files = [
        r for r in results if r.file_type in ("pcb", "footprint")
    ]
    uuid_ok = sum(1 for r in uuid_files if r.uuid_preserved is True)
    logger.info(
        "PASS: %d/%d files stable. "
        "UUID preservation: %d/%d PCB/footprint files.",
        passed,
        len(results),
        uuid_ok,
        len(uuid_files),
    )

    return suite_result
