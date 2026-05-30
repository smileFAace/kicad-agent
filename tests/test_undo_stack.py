"""Tests for UndoStack module and executor undo/redo integration."""

import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.ops.undo_stack import UndoEntry, UndoStack


# ---------------------------------------------------------------------------
# Unit tests for UndoStack
# ---------------------------------------------------------------------------


class TestUndoStack:
    """Unit tests for the UndoStack class."""

    def test_push_creates_entry_retrievable_via_pop_undo(self):
        """Push creates an entry retrievable via pop_undo."""
        stack = UndoStack()
        fp = Path("/tmp/test_file.kicad_sch")
        stack.push(fp, "old content", "new content", "add_component")
        entry = stack.pop_undo(fp)
        assert entry is not None
        assert entry.file_path == fp.resolve()
        assert entry.pre_content == "old content"
        assert entry.post_content == "new content"
        assert entry.op_type == "add_component"
        assert entry.post_mtime == 0

    def test_pop_undo_returns_most_recent_pushes_to_redo(self):
        """pop_undo returns the most recent entry and pushes to redo stack."""
        stack = UndoStack()
        fp = Path("/tmp/test.kicad_sch")
        stack.push(fp, "v1", "v2", "op1")
        stack.push(fp, "v2", "v3", "op2")

        entry = stack.pop_undo(fp)
        assert entry is not None
        assert entry.pre_content == "v2"
        assert entry.post_content == "v3"
        assert entry.op_type == "op2"

        # Should be on redo stack now
        assert stack.can_redo(fp)
        # One entry still remains on undo (we pushed 2, popped 1)
        assert stack.can_undo(fp)

        # Pop the remaining undo entry
        entry2 = stack.pop_undo(fp)
        assert entry2.op_type == "op1"
        assert not stack.can_undo(fp)

    def test_pop_redo_returns_most_recently_undone(self):
        """pop_redo returns the most recently undone entry and pushes back to undo."""
        stack = UndoStack()
        fp = Path("/tmp/test.kicad_sch")
        stack.push(fp, "v1", "v2", "op1")
        stack.pop_undo(fp)

        entry = stack.pop_redo(fp)
        assert entry is not None
        assert entry.pre_content == "v1"
        assert entry.post_content == "v2"
        assert entry.op_type == "op1"

        # Should be back on undo stack
        assert stack.can_undo(fp)
        assert not stack.can_redo(fp)

    def test_push_clears_redo_stack(self):
        """New push clears redo stack (standard undo/redo semantics)."""
        stack = UndoStack()
        fp = Path("/tmp/test.kicad_sch")
        stack.push(fp, "v1", "v2", "op1")
        stack.pop_undo(fp)  # Moves to redo

        assert stack.can_redo(fp)

        # New push should clear redo
        stack.push(fp, "v2", "v3", "op2")
        assert not stack.can_redo(fp)

    def test_max_size_pruning(self):
        """deque maxlen=3 with 5 pushes only keeps last 3 entries."""
        stack = UndoStack(max_size=3)
        fp = Path("/tmp/test.kicad_sch")
        for i in range(5):
            stack.push(fp, f"pre_{i}", f"post_{i}", f"op_{i}")

        # Should only have last 3 entries
        entries = []
        while stack.can_undo(fp):
            entries.append(stack.pop_undo(fp))

        assert len(entries) == 3
        # Most recent first from pop_undo
        assert entries[0].op_type == "op_4"
        assert entries[1].op_type == "op_3"
        assert entries[2].op_type == "op_2"

    def test_can_undo_can_redo_return_false_for_empty(self):
        """can_undo/can_redo return False for empty stacks."""
        stack = UndoStack()
        fp = Path("/tmp/test.kicad_sch")
        assert not stack.can_undo(fp)
        assert not stack.can_redo(fp)

    def test_clear_empties_both_stacks(self):
        """clear() empties both undo and redo stacks."""
        stack = UndoStack()
        fp = Path("/tmp/test.kicad_sch")
        stack.push(fp, "v1", "v2", "op1")
        stack.pop_undo(fp)  # Move to redo

        assert stack.can_undo(fp) or stack.can_redo(fp)

        stack.clear()
        assert not stack.can_undo(fp)
        assert not stack.can_redo(fp)

    def test_per_file_isolation(self):
        """Two files have independent stacks."""
        stack = UndoStack()
        fp_a = Path("/tmp/file_a.kicad_sch")
        fp_b = Path("/tmp/file_b.kicad_sch")

        stack.push(fp_a, "a_v1", "a_v2", "op_a")
        stack.push(fp_b, "b_v1", "b_v2", "op_b")

        assert stack.can_undo(fp_a)
        assert stack.can_undo(fp_b)

        entry_a = stack.pop_undo(fp_a)
        assert entry_a.op_type == "op_a"

        # fp_b still has its entry
        assert stack.can_undo(fp_b)
        # fp_a is empty
        assert not stack.can_undo(fp_a)

    def test_value_error_when_max_size_less_than_one(self):
        """ValueError raised when max_size < 1."""
        with pytest.raises(ValueError, match="max_size must be >= 1"):
            UndoStack(max_size=0)

        with pytest.raises(ValueError, match="max_size must be >= 1"):
            UndoStack(max_size=-1)

    def test_thread_safety_concurrent_pushes(self):
        """10 threads x 100 pushes = 1000 total entries."""
        stack = UndoStack(max_size=1000)
        fp = Path("/tmp/test.kicad_sch")
        num_threads = 10
        pushes_per_thread = 100

        def push_entries(thread_id):
            for i in range(pushes_per_thread):
                stack.push(
                    fp,
                    f"pre_{thread_id}_{i}",
                    f"post_{thread_id}_{i}",
                    f"op_{thread_id}_{i}",
                )

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(push_entries, t) for t in range(num_threads)]
            for f in futures:
                f.result()

        # Count total entries
        count = 0
        while stack.can_undo(fp):
            stack.pop_undo(fp)
            count += 1

        assert count == num_threads * pushes_per_thread

    def test_concurrent_push_and_pop(self):
        """Concurrent push and pop from different threads (M-06)."""
        stack = UndoStack()
        fp = Path("/tmp/test.kicad_sch")
        total_pushes = 50
        push_done = threading.Event()

        def pusher():
            for i in range(total_pushes):
                stack.push(fp, f"pre_{i}", f"post_{i}", f"op_{i}")
            push_done.set()

        pop_count = 0
        def popper():
            nonlocal pop_count
            while not push_done.is_set() or stack.can_undo(fp):
                entry = stack.pop_undo(fp)
                if entry is not None:
                    pop_count += 1
                else:
                    time.sleep(0.001)

        t_push = threading.Thread(target=pusher)
        t_pop = threading.Thread(target=popper)
        t_push.start()
        t_pop.start()
        t_push.join(timeout=10)
        push_done.wait(timeout=10)
        t_pop.join(timeout=10)

        # Remaining entries + popped entries = total pushes
        remaining = 0
        while stack.can_undo(fp):
            stack.pop_undo(fp)
            remaining += 1
        assert remaining + pop_count == total_pushes

    def test_pop_latest_undo_returns_entry_across_files(self):
        """pop_latest_undo returns an entry across all files."""
        stack = UndoStack()
        fp_a = Path("/tmp/file_a.kicad_sch")
        fp_b = Path("/tmp/file_b.kicad_sch")

        stack.push(fp_a, "a_v1", "a_v2", "op_a")
        stack.push(fp_b, "b_v1", "b_v2", "op_b")

        entry = stack.pop_latest_undo()
        assert entry is not None
        assert entry.op_type in ("op_a", "op_b")

    def test_pop_latest_redo_returns_entry_across_files(self):
        """pop_latest_redo returns an entry across all files."""
        stack = UndoStack()
        fp_a = Path("/tmp/file_a.kicad_sch")
        fp_b = Path("/tmp/file_b.kicad_sch")

        stack.push(fp_a, "a_v1", "a_v2", "op_a")
        stack.push(fp_b, "b_v1", "b_v2", "op_b")
        stack.pop_undo(fp_a)
        stack.pop_undo(fp_b)

        entry = stack.pop_latest_redo()
        assert entry is not None
        assert entry.op_type in ("op_a", "op_b")

    def test_max_size_property(self):
        """max_size property returns configured value."""
        stack = UndoStack(max_size=25)
        assert stack.max_size == 25

    def test_push_with_post_mtime(self):
        """Push stores post_mtime in the entry."""
        stack = UndoStack()
        fp = Path("/tmp/test.kicad_sch")
        stack.push(fp, "pre", "post", "op1", post_mtime=123456789)
        entry = stack.pop_undo(fp)
        assert entry is not None
        assert entry.post_mtime == 123456789

    def test_pop_returns_none_for_unknown_file(self):
        """pop_undo/pop_redo return None for file with no history."""
        stack = UndoStack()
        fp = Path("/tmp/nonexistent.kicad_sch")
        assert stack.pop_undo(fp) is None
        assert stack.pop_redo(fp) is None

    def test_pop_latest_returns_none_when_empty(self):
        """pop_latest_undo/pop_latest_redo return None when all stacks empty."""
        stack = UndoStack()
        assert stack.pop_latest_undo() is None
        assert stack.pop_latest_redo() is None


# ---------------------------------------------------------------------------
# Integration tests for executor undo/redo
# ---------------------------------------------------------------------------


class TestExecutorUndoIntegration:
    """Integration tests for undo/redo in OperationExecutor."""

    @pytest.fixture(autouse=True)
    def _setup_fixture(self, tmp_path):
        """Copy Arduino_Mega fixture to tmp_path for each test."""
        fixture_src = Path("tests/fixtures/Arduino_Mega")
        fixture_dst = tmp_path / "Arduino_Mega"
        shutil.copytree(fixture_src, fixture_dst)
        self.fixture_dir = fixture_dst
        self.sch_path = fixture_dst / "Arduino_Mega.kicad_sch"

    def _make_executor(self, undo_stack=None, cache=None):
        """Helper to create an OperationExecutor with undo stack."""
        from kicad_agent.ops.executor import OperationExecutor
        return OperationExecutor(
            base_dir=self.fixture_dir,
            cache=cache,
            undo_stack=undo_stack,
        )

    def test_schematic_operation_captures_snapshot(self):
        """Execute add_component, verify undo_stack.can_undo is True."""
        from kicad_agent.ops.schema import Operation
        stack = UndoStack()
        executor = self._make_executor(undo_stack=stack)

        op = Operation.model_validate({
            "root": {
                "op_type": "add_component",
                "target_file": "Arduino_Mega.kicad_sch",
                "library_id": "Device:R",
                "reference": "R99",
                "value": "10k",
                "position": {"x": 50.0, "y": 50.0},
            }
        })
        result = executor.execute(op)
        assert result["success"]
        assert stack.can_undo(self.sch_path)

    def test_undo_restores_file_content(self):
        """Execute add_component, undo, verify file content matches original."""
        from kicad_agent.ops.schema import Operation
        stack = UndoStack()
        executor = self._make_executor(undo_stack=stack)

        original_content = self.sch_path.read_text(encoding="utf-8")

        op = Operation.model_validate({
            "root": {
                "op_type": "add_component",
                "target_file": "Arduino_Mega.kicad_sch",
                "library_id": "Device:R",
                "reference": "R99",
                "value": "10k",
                "position": {"x": 50.0, "y": 50.0},
            }
        })
        executor.execute(op)
        assert self.sch_path.read_text(encoding="utf-8") != original_content

        result = executor.undo(target_file="Arduino_Mega.kicad_sch")
        assert result["success"], f"Undo failed: {result}"
        assert self.sch_path.read_text(encoding="utf-8") == original_content

    def test_redo_restores_post_mutation_content(self):
        """After undo, redo restores file to post-mutation state."""
        from kicad_agent.ops.schema import Operation
        stack = UndoStack()
        executor = self._make_executor(undo_stack=stack)

        op = Operation.model_validate({
            "root": {
                "op_type": "add_component",
                "target_file": "Arduino_Mega.kicad_sch",
                "library_id": "Device:R",
                "reference": "R99",
                "value": "10k",
                "position": {"x": 50.0, "y": 50.0},
            }
        })
        executor.execute(op)
        post_mutation_content = self.sch_path.read_text(encoding="utf-8")

        executor.undo(target_file="Arduino_Mega.kicad_sch")

        result = executor.redo(target_file="Arduino_Mega.kicad_sch")
        assert result["success"], f"Redo failed: {result}"
        assert self.sch_path.read_text(encoding="utf-8") == post_mutation_content

    def test_cache_invalidation_after_undo(self):
        """After undo, cache.get returns None for the affected file."""
        from kicad_agent.ops.ir_cache import IRCache
        from kicad_agent.ops.schema import Operation
        cache = IRCache()
        stack = UndoStack()
        executor = self._make_executor(undo_stack=stack, cache=cache)

        op = Operation.model_validate({
            "root": {
                "op_type": "add_component",
                "target_file": "Arduino_Mega.kicad_sch",
                "library_id": "Device:R",
                "reference": "R99",
                "value": "10k",
                "position": {"x": 50.0, "y": 50.0},
            }
        })
        executor.execute(op)
        # Cache should have an entry after execute
        assert cache.get(self.sch_path) is not None

        executor.undo(target_file="Arduino_Mega.kicad_sch")
        # Cache should be invalidated after undo
        assert cache.get(self.sch_path) is None

    def test_create_operations_not_captured(self):
        """Create operations do NOT push to undo stack."""
        from kicad_agent.ops.schema import Operation
        stack = UndoStack()
        executor = self._make_executor(undo_stack=stack)

        op = Operation.model_validate({
            "root": {
                "op_type": "create_schematic",
                "target_file": "new_schematic.kicad_sch",
            }
        })
        executor.execute(op)

        new_path = self.fixture_dir / "new_schematic.kicad_sch"
        assert not stack.can_undo(new_path)

    def test_undo_with_no_history_returns_error(self):
        """Undo when no history returns error dict."""
        stack = UndoStack()
        executor = self._make_executor(undo_stack=stack)

        result = executor.undo(target_file="Arduino_Mega.kicad_sch")
        assert result["success"] is False
        assert "error" in result

    def test_redo_with_no_history_returns_error(self):
        """Redo when no history returns error dict."""
        stack = UndoStack()
        executor = self._make_executor(undo_stack=stack)

        result = executor.redo(target_file="Arduino_Mega.kicad_sch")
        assert result["success"] is False
        assert "error" in result

    def test_undo_without_stack_returns_error(self):
        """Undo returns error when undo_stack is None."""
        executor = self._make_executor()

        result = executor.undo(target_file="Arduino_Mega.kicad_sch")
        assert result["success"] is False
        assert "not enabled" in result["error"]

    def test_redo_without_stack_returns_error(self):
        """Redo returns error when undo_stack is None."""
        executor = self._make_executor()

        result = executor.redo(target_file="Arduino_Mega.kicad_sch")
        assert result["success"] is False
        assert "not enabled" in result["error"]

    def test_project_file_operation_captures_snapshot(self, tmp_path):
        """Project-file operation captures snapshot (M-04)."""
        from kicad_agent.ops.schema import Operation
        stack = UndoStack()
        executor = self._make_executor(undo_stack=stack)

        # Create a sym-lib-table file
        lib_table = self.fixture_dir / "sym-lib-table"
        lib_table.write_text(
            "(sym_lib_table\n  (version 7)\n  (lib (name Test)(type Legacy)(uri /path)(options \"\")(descr \"\"))\n)\n",
            encoding="utf-8",
        )

        op = Operation.model_validate({
            "root": {
                "op_type": "add_lib_entry",
                "target_file": "sym-lib-table",
                "lib_name": "NewLib",
                "lib_type": "Legacy",
                "uri": "/new/path",
            }
        })
        result = executor.execute(op)
        assert result["success"]
        assert stack.can_undo(lib_table)

    def test_undo_returns_error_when_parent_dir_deleted(self):
        """Undo returns error when parent directory no longer exists (M-08)."""
        from kicad_agent.ops.schema import Operation
        stack = UndoStack()
        executor = self._make_executor(undo_stack=stack)

        # Create a subdirectory with a schematic
        subdir = self.fixture_dir / "subdir"
        subdir.mkdir()
        sub_sch = subdir / "test.kicad_sch"
        shutil.copy2(self.sch_path, sub_sch)

        op = Operation.model_validate({
            "root": {
                "op_type": "add_component",
                "target_file": "subdir/test.kicad_sch",
                "library_id": "Device:R",
                "reference": "R99",
                "value": "10k",
                "position": {"x": 50.0, "y": 50.0},
            }
        })
        executor.execute(op)
        assert stack.can_undo(sub_sch)

        # Delete parent directory
        shutil.rmtree(subdir)

        result = executor.undo(target_file="subdir/test.kicad_sch")
        assert result["success"] is False
        assert "parent directory" in result["error"]

    def test_undo_latest_without_target_file(self):
        """Undo with no target_file pops from latest across all files."""
        from kicad_agent.ops.schema import Operation
        stack = UndoStack()
        executor = self._make_executor(undo_stack=stack)

        op = Operation.model_validate({
            "root": {
                "op_type": "add_component",
                "target_file": "Arduino_Mega.kicad_sch",
                "library_id": "Device:R",
                "reference": "R99",
                "value": "10k",
                "position": {"x": 50.0, "y": 50.0},
            }
        })
        executor.execute(op)

        result = executor.undo()
        assert result["success"], f"Undo failed: {result}"
        assert result["undone_op"] == "add_component"
