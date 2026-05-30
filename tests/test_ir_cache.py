"""Tests for IR caching layer (IRCache and CacheEntry).

Uses real ParseResult objects from kicad_agent.parser and real temp files
for mtime-based cache key behavior.
"""

import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from kicad_agent.ops.ir_cache import CacheEntry, IRCache
from kicad_agent.parser.types import ParseResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_parse_result(file_path: Path, content: str = "(kicad_sch)") -> ParseResult:
    """Create a minimal ParseResult for testing."""
    return ParseResult(
        kiutils_obj=None,
        raw_content=content,
        file_path=file_path,
        file_type="schematic",
    )


def _write_file(path: Path, content: str = "(kicad_sch)") -> None:
    """Write content to a file, ensuring a detectable mtime change."""
    path.write_text(content, encoding="utf-8")


def _bump_mtime(path: Path) -> None:
    """Force an mtime change on a file by writing and sleeping briefly."""
    old = path.read_text(encoding="utf-8")
    _write_file(path, old + " ")
    # Ensure filesystem mtime resolution catches the change
    time.sleep(0.01)


# ---------------------------------------------------------------------------
# TestIRCache -- pure cache unit tests
# ---------------------------------------------------------------------------


class TestIRCache:
    """Unit tests for IRCache behavior."""

    def test_cache_hit_when_mtime_matches(self, tmp_path: Path) -> None:
        """Cache returns entry when mtime matches the stored key."""
        cache = IRCache()
        f = tmp_path / "test.kicad_sch"
        _write_file(f)

        pr = _make_parse_result(f)
        entry = CacheEntry(parse_result=pr)
        cache.put(f, entry)

        result = cache.get(f)
        assert result is not None
        assert result.parse_result is pr

    def test_cache_miss_when_mtime_differs(self, tmp_path: Path) -> None:
        """Cache returns None after file mtime changes."""
        cache = IRCache()
        f = tmp_path / "test.kicad_sch"
        _write_file(f)

        pr = _make_parse_result(f)
        cache.put(f, CacheEntry(parse_result=pr))

        # Change the file so mtime differs
        _bump_mtime(f)

        result = cache.get(f)
        assert result is None

    def test_lru_eviction_when_max_size_exceeded(self, tmp_path: Path) -> None:
        """Cache evicts oldest entry when max_size is exceeded."""
        cache = IRCache(max_size=2)

        files = []
        for i in range(3):
            f = tmp_path / f"file_{i}.kicad_sch"
            _write_file(f, f"(kicad_sch version={i})")
            files.append(f)
            pr = _make_parse_result(f, content=f"(kicad_sch version={i})")
            cache.put(f, CacheEntry(parse_result=pr))

        # file_0 should have been evicted (oldest)
        assert cache.get(files[0]) is None
        # file_1 and file_2 should still be present
        assert cache.get(files[1]) is not None
        assert cache.get(files[2]) is not None

    def test_invalidate_removes_entries_for_specific_path(self, tmp_path: Path) -> None:
        """Invalidate removes all entries for a given path."""
        cache = IRCache()
        f1 = tmp_path / "a.kicad_sch"
        f2 = tmp_path / "b.kicad_sch"
        _write_file(f1)
        _write_file(f2)

        cache.put(f1, CacheEntry(parse_result=_make_parse_result(f1)))
        cache.put(f2, CacheEntry(parse_result=_make_parse_result(f2)))

        cache.invalidate(f1)

        assert cache.get(f1) is None
        assert cache.get(f2) is not None

    def test_clear_removes_all_entries(self, tmp_path: Path) -> None:
        """Clear removes every entry from the cache."""
        cache = IRCache()
        for i in range(5):
            f = tmp_path / f"file_{i}.kicad_sch"
            _write_file(f)
            cache.put(f, CacheEntry(parse_result=_make_parse_result(f)))

        cache.clear()

        for i in range(5):
            f = tmp_path / f"file_{i}.kicad_sch"
            assert cache.get(f) is None

    def test_put_moves_existing_key_to_mru_position(self, tmp_path: Path) -> None:
        """Re-putting an entry moves it to most-recently-used position."""
        cache = IRCache(max_size=2)
        f1 = tmp_path / "oldest.kicad_sch"
        f2 = tmp_path / "middle.kicad_sch"
        _write_file(f1)
        _write_file(f2)

        cache.put(f1, CacheEntry(parse_result=_make_parse_result(f1)))
        cache.put(f2, CacheEntry(parse_result=_make_parse_result(f2)))

        # Access f1 to move it to MRU
        cache.get(f1)

        # Add a third file -- should evict f2 (now LRU)
        f3 = tmp_path / "newest.kicad_sch"
        _write_file(f3)
        cache.put(f3, CacheEntry(parse_result=_make_parse_result(f3)))

        assert cache.get(f1) is not None  # Still present (was MRU)
        assert cache.get(f2) is None  # Evicted (was LRU)
        assert cache.get(f3) is not None

    def test_concurrent_access_no_exception(self, tmp_path: Path) -> None:
        """Multiple threads accessing cache concurrently do not raise."""
        cache = IRCache(max_size=32)
        f = tmp_path / "concurrent.kicad_sch"
        _write_file(f)

        errors: list[Exception] = []

        def worker(idx: int) -> None:
            try:
                pr = _make_parse_result(f, content=f"(thread {idx})")
                for _ in range(100):
                    cache.put(f, CacheEntry(parse_result=pr))
                    cache.get(f)
                    cache.invalidate(f)
                    cache.put(f, CacheEntry(parse_result=pr))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent access errors: {errors}"

    def test_cache_entry_stores_parse_result_and_uuid_map(self, tmp_path: Path) -> None:
        """CacheEntry correctly stores both parse_result and uuid_map."""
        f = tmp_path / "test.kicad_sch"
        _write_file(f)

        pr = _make_parse_result(f)
        uuid_map = {"test": "uuid-value"}
        entry = CacheEntry(parse_result=pr, uuid_map=uuid_map)

        assert entry.parse_result is pr
        assert entry.uuid_map == uuid_map

    def test_cache_entry_uuid_map_defaults_to_none(self, tmp_path: Path) -> None:
        """CacheEntry uuid_map defaults to None when not provided."""
        f = tmp_path / "test.kicad_sch"
        _write_file(f)

        entry = CacheEntry(parse_result=_make_parse_result(f))
        assert entry.uuid_map is None

    def test_get_returns_none_for_nonexistent_file(self) -> None:
        """Cache returns None when file does not exist on disk."""
        cache = IRCache()
        result = cache.get(Path("/nonexistent/file.kicad_sch"))
        assert result is None

    def test_max_size_must_be_positive(self) -> None:
        """Cache raises ValueError for max_size < 1."""
        with pytest.raises(ValueError, match="max_size must be >= 1"):
            IRCache(max_size=0)

    def test_invalidate_nonexistent_path_is_noop(self) -> None:
        """Invalidating a path with no cache entries is a no-op."""
        cache = IRCache()
        cache.invalidate(Path("/nonexistent/file.kicad_sch"))  # Should not raise


# ---------------------------------------------------------------------------
# TestExecutorCache -- integration with OperationExecutor
# ---------------------------------------------------------------------------


class TestExecutorCache:
    """Tests for IRCache integration with OperationExecutor."""

    @pytest.fixture
    def fixture_dir(self) -> Path:
        """Return path to test fixtures."""
        return Path(__file__).parent / "fixtures"

    @pytest.fixture
    def arduino_sch(self, fixture_dir: Path) -> Path:
        """Return path to Arduino Mega schematic fixture."""
        return fixture_dir / "Arduino_Mega" / "Arduino_Mega.kicad_sch"

    def test_executor_with_cache_reuses_parse_result(
        self, tmp_path: Path, arduino_sch: Path
    ) -> None:
        """Executor with cache only parses once for repeated operations on same file."""
        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        # Copy fixture to tmp_path so we can mutate it
        work_file = tmp_path / "test.kicad_sch"
        work_file.write_text(arduino_sch.read_text(encoding="utf-8"), encoding="utf-8")

        cache = IRCache()
        executor = OperationExecutor(base_dir=tmp_path, cache=cache)

        # Create a simple operation
        op_data = {
            "root": {
                "op_type": "validate_refs",
                "target_file": "test.kicad_sch",
            }
        }
        op = Operation.model_validate(op_data)

        with patch("kicad_agent.ops.executor.parse_schematic", wraps=None) as mock_parse:
            # Set up the mock to return a real parse result
            from kicad_agent.parser import parse_schematic

            mock_parse.side_effect = lambda p: parse_schematic(p)

            result1 = executor.execute(op)
            assert result1["success"]

            # First call should have parsed (cache miss)
            first_parse_count = mock_parse.call_count

            # Execute same operation again -- should use cache
            result2 = executor.execute(op)
            assert result2["success"]

            # Second call should NOT have incremented parse count
            assert mock_parse.call_count == first_parse_count

    def test_executor_with_cache_reparses_when_mtime_changes(
        self, tmp_path: Path, arduino_sch: Path
    ) -> None:
        """Executor re-parses when file mtime changes after caching."""
        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        work_file = tmp_path / "test.kicad_sch"
        work_file.write_text(arduino_sch.read_text(encoding="utf-8"), encoding="utf-8")

        cache = IRCache()
        executor = OperationExecutor(base_dir=tmp_path, cache=cache)

        op_data = {
            "root": {
                "op_type": "validate_refs",
                "target_file": "test.kicad_sch",
            }
        }
        op = Operation.model_validate(op_data)

        with patch("kicad_agent.ops.executor.parse_schematic", wraps=None) as mock_parse:
            from kicad_agent.parser import parse_schematic

            mock_parse.side_effect = lambda p: parse_schematic(p)

            result1 = executor.execute(op)
            assert result1["success"]
            first_parse_count = mock_parse.call_count

            # Touch the file to change mtime
            time.sleep(0.05)
            _bump_mtime(work_file)

            result2 = executor.execute(op)
            assert result2["success"]

            # Should have re-parsed because mtime changed
            assert mock_parse.call_count > first_parse_count

    def test_executor_without_cache_backward_compat(
        self, tmp_path: Path, arduino_sch: Path
    ) -> None:
        """Executor without cache (default) works identically to before."""
        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        work_file = tmp_path / "test.kicad_sch"
        work_file.write_text(arduino_sch.read_text(encoding="utf-8"), encoding="utf-8")

        # No cache parameter -- backward compatible
        executor = OperationExecutor(base_dir=tmp_path)

        op_data = {
            "root": {
                "op_type": "validate_refs",
                "target_file": "test.kicad_sch",
            }
        }
        op = Operation.model_validate(op_data)

        result = executor.execute(op)
        assert result["success"]
        assert result["operation"] == "validate_refs"

    def test_executor_cache_updated_after_write(
        self, tmp_path: Path, arduino_sch: Path
    ) -> None:
        """After a write operation, cache is updated with new ParseResult."""
        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        work_file = tmp_path / "test.kicad_sch"
        work_file.write_text(arduino_sch.read_text(encoding="utf-8"), encoding="utf-8")

        cache = IRCache()
        executor = OperationExecutor(base_dir=tmp_path, cache=cache)

        # First, populate the cache with a read operation
        op_data = {
            "root": {
                "op_type": "validate_refs",
                "target_file": "test.kicad_sch",
            }
        }
        op = Operation.model_validate(op_data)
        result = executor.execute(op)
        assert result["success"]

        # The cache should now have an entry for the file
        entry = cache.get(work_file)
        assert entry is not None

    def test_cache_hit_for_pcb_includes_uuid_map(self, tmp_path: Path) -> None:
        """Cache entry for PCB files includes the uuid_map."""
        from kicad_agent.parser import parse_pcb
        from kicad_agent.parser.uuid_extractor import extract_uuids

        pcb_fixture = Path(__file__).parent / "fixtures" / "Arduino_Mega" / "Arduino_Mega.kicad_pcb"
        if not pcb_fixture.exists():
            pytest.skip("PCB fixture not found")

        work_file = tmp_path / "test.kicad_pcb"
        work_file.write_text(pcb_fixture.read_text(encoding="utf-8"), encoding="utf-8")

        cache = IRCache()
        pr = parse_pcb(work_file)
        uuid_map = extract_uuids(pr.raw_content, "pcb")
        entry = CacheEntry(parse_result=pr, uuid_map=uuid_map)
        cache.put(work_file, entry)

        cached = cache.get(work_file)
        assert cached is not None
        assert cached.uuid_map is not None
        assert cached.parse_result.file_type == "pcb"
