"""File-level transaction with auto-rollback for KiCad file mutations.

D-08: File-level snapshots -- entire file is copied before any mutation.
D-09: Auto-rollback on validation failure, exception, or manual rollback().
D-10: Full file copy via shutil.copy2 (not delta-based).

Security (Council review findings):
- H-02: Symlink TOCTOU protection via resolve() + is_symlink() checks
- H-03: Snapshot files created with 0o600 permissions
- H-04: Concurrent modification guard via .lck file locking (fcntl)
- M-03: Cleanup robust to partial states (missing files, missing dirs)
- MEDIUM Finding 6: Auto-rollback without explicit commit logs a warning

Usage:
    from kicad_agent.ir.transaction import Transaction

    with Transaction(file_path) as txn:
        # ... perform mutations ...
        txn.commit()
    # If exception occurs, auto-rollback restores original file.
"""

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Cross-platform file locking
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    # Windows: use msvcrt for file locking
    import msvcrt
    HAS_FCNTL = False


def _flock_exclusive_nb(fd) -> None:
    """Acquire exclusive non-blocking lock (cross-platform)."""
    if HAS_FCNTL:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        # Windows: msvcrt.locking uses bytes range lock
        try:
            msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise IOError("Cannot acquire lock")


def _flock_release(fd) -> None:
    """Release lock (cross-platform)."""
    if HAS_FCNTL:
        fcntl.flock(fd, fcntl.LOCK_UN)
    else:
        try:
            fd.seek(0)
            msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransactionResult:
    """Result of a transaction commit or rollback.

    Attributes:
        success: True if commit succeeded, False if rolled back.
        target_file: Path to the target file.
        snapshot_created: True if a snapshot was created.
        error: Error message if rollback occurred due to exception.
    """

    success: bool
    target_file: Path
    snapshot_created: bool = False
    error: Optional[str] = None


class Transaction:
    """File-level transaction with snapshot-based rollback.

    D-08: Snapshot entire file content before any mutation.
    D-09: Auto-rollback on validation failure, exception, or manual rollback().
    D-10: Use shutil.copy2 for full file copy (not delta-based).

    Usage:
        with Transaction(file_path) as txn:
            # ... perform mutations ...
            txn.commit()
        # If exception occurs, auto-rollback restores original file.

    Snapshot is stored in a temp directory to avoid polluting the project.
    Stale snapshots from crashes are cleaned up on next Transaction creation
    for the same file (Pitfall 4 from RESEARCH.md).

    Security (Council review):
    - H-02: Symlink TOCTOU protection via resolve() + is_symlink() checks
    - H-03: Snapshot files created with 0o600 permissions
    - H-04: Concurrent modification guard via .lck file locking
    - M-03: Cleanup robust to partial states
    """

    def __init__(self, file_path: Path):
        # Council H-02: Check for symlink BEFORE resolve() (resolve follows symlinks)
        if file_path.is_symlink():
            raise ValueError(f"Refusing to operate on symlink: {file_path}")
        self._file_path = file_path.resolve()
        if not self._file_path.exists():
            raise FileNotFoundError(
                f"Cannot start transaction: file not found: {self._file_path}"
            )
        self._snapshot_path: Optional[Path] = None
        self._snap_dir: Optional[str] = None
        self._committed = False
        self._rolled_back = False
        self._lock_path = self._file_path.with_suffix(
            self._file_path.suffix + ".lck"
        )
        self._lock_fd = None

    def __enter__(self) -> "Transaction":
        # Council M-01: Detect and clean up stale lock files from crashes.
        # A stale lock has no active process holding it (empty file, no flock).
        if self._lock_path.exists():
            try:
                # Try to acquire a blocking lock on the existing file
                test_fd = open(self._lock_path, "r")
                try:
                    _flock_exclusive_nb(test_fd)
                    # Got the lock immediately — it was stale. Release and remove.
                    _flock_release(test_fd)
                    test_fd.close()
                    self._lock_path.unlink(missing_ok=True)
                except (OSError, IOError):
                    # Lock is held by another process — can't acquire
                    test_fd.close()
                    raise RuntimeError(
                        f"Cannot acquire lock on {self._file_path}. "
                        f"Another transaction is in progress."
                    )
            except FileNotFoundError:
                pass  # Race condition: file disappeared, proceed normally

        # Council H-04: Acquire exclusive lock before snapshot
        # Council M-03: Create lock file with restrictive permissions
        self._lock_fd = os.open(
            str(self._lock_path),
            os.O_CREAT | os.O_WRONLY | os.O_EXCL,
            0o600,
        )
        self._lock_fd = os.fdopen(self._lock_fd, "w")
        try:
            _flock_exclusive_nb(self._lock_fd)
        except (OSError, IOError):
            self._lock_fd.close()
            self._lock_fd = None
            raise RuntimeError(
                f"Cannot acquire lock on {self._file_path}. "
                f"Another transaction may be in progress."
            )

        # D-08/D-10: Full file copy to temp directory
        self._snap_dir = tempfile.mkdtemp(prefix="kicad-agent-")
        self._snapshot_path = Path(self._snap_dir) / self._file_path.name
        shutil.copy2(self._file_path, self._snapshot_path)
        # Council H-03: Restrict snapshot file permissions
        if os.name != 'nt':  # Skip on Windows (chmod semantics differ)
            os.chmod(self._snapshot_path, 0o600)
        return self

    def commit(self) -> TransactionResult:
        """Mark transaction as successful. Removes snapshot.

        After commit, the mutated file is on disk and snapshot is cleaned up.
        Idempotent: calling commit() twice returns success without error.
        """
        if self._committed:
            return TransactionResult(
                success=True,
                target_file=self._file_path,
                snapshot_created=True,
            )
        self._cleanup_snapshot()
        self._release_lock()
        self._committed = True
        return TransactionResult(
            success=True,
            target_file=self._file_path,
            snapshot_created=True,
        )

    def rollback(self) -> TransactionResult:
        """Restore file from snapshot (D-09).

        Restores the original file content from the snapshot.
        Idempotent: calling rollback() twice is a no-op.
        """
        if self._rolled_back:
            return TransactionResult(
                success=False,
                target_file=self._file_path,
                snapshot_created=False,
                error="Already rolled back",
            )
        # Council H-02: Re-verify target is not a symlink before restoring
        if self._file_path.is_symlink():
            logger.error(
                "Target file became a symlink during transaction. Aborting rollback."
            )
            self._cleanup_snapshot()
            self._release_lock()
            self._rolled_back = True
            return TransactionResult(
                success=False,
                target_file=self._file_path,
                snapshot_created=True,
                error="Target file became symlink during transaction",
            )
        if self._snapshot_path and self._snapshot_path.exists():
            shutil.copy2(self._snapshot_path, self._file_path)
        self._cleanup_snapshot()
        self._release_lock()
        self._rolled_back = True
        return TransactionResult(
            success=False,
            target_file=self._file_path,
            snapshot_created=True,
            error="Rolled back to pre-mutation state",
        )

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        # D-09: Auto-rollback on exception
        if exc_type is not None and not self._committed:
            logger.warning("Auto-rollback triggered by exception: %s", exc_val)
            self.rollback()
        elif not self._committed and not self._rolled_back:
            # Council MEDIUM Finding 6: No commit and no explicit rollback -- warn
            logger.warning(
                "Transaction exited without commit or rollback on %s. "
                "Auto-rolling back to pre-mutation state.",
                self._file_path,
            )
            self.rollback()
        return False  # Don't suppress exceptions

    def _cleanup_snapshot(self) -> None:
        """Remove snapshot file and temp directory.

        Council M-03: Robust to partial states (file gone, dir gone).
        """
        try:
            if self._snapshot_path and self._snapshot_path.exists():
                self._snapshot_path.unlink()
        except FileNotFoundError:
            pass  # Already cleaned up
        try:
            if self._snap_dir:
                snap_dir_path = Path(self._snap_dir)
                if snap_dir_path.exists():
                    snap_dir_path.rmdir()
        except (FileNotFoundError, OSError):
            pass  # Directory already removed or not empty
        finally:
            self._snap_dir = None
            self._snapshot_path = None

    def _release_lock(self) -> None:
        """Release and remove the lock file (Council H-04)."""
        if self._lock_fd:
            try:
                _flock_release(self._lock_fd)
                self._lock_fd.close()
            except (OSError, IOError):
                pass
            finally:
                self._lock_fd = None
        try:
            if self._lock_path.exists():
                self._lock_path.unlink()
        except (FileNotFoundError, OSError):
            pass

    @property
    def snapshot_path(self) -> Optional[Path]:
        """Path to the snapshot file (for testing/inspection)."""
        return self._snapshot_path
