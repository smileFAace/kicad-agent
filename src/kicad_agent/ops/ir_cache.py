"""IR caching layer to eliminate redundant file parsing for sequential operations.

Stores ParseResult + UUIDMap keyed by (file_path, mtime_ns). Returns cached
data when the file hasn't changed (same mtime), avoiding redundant parse and
UUID extraction calls.

Thread-safe via threading.Lock. LRU eviction via OrderedDict.

Usage:
    from kicad_agent.ops.ir_cache import IRCache, CacheEntry

    cache = IRCache(max_size=64)
    entry = cache.get(file_path)
    if entry is None:
        parse_result = parse_schematic(file_path)
        entry = CacheEntry(parse_result=parse_result)
        cache.put(file_path, entry)
"""

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from kicad_agent.parser.types import ParseResult

logger = logging = __import__("logging").getLogger(__name__)


@dataclass(frozen=True)
class CacheEntry:
    """Cached parse result for a single KiCad file.

    Attributes:
        parse_result: The parsed file content (kiutils object + raw text).
        uuid_map: Optional UUID map extracted from the file (PCB/footprint only).
    """

    parse_result: ParseResult
    uuid_map: Optional[Any] = None


class IRCache:
    """LRU cache for ParseResult + UUIDMap, keyed by (resolved_path, mtime_ns).

    Thread-safe. Uses OrderedDict for O(1) LRU eviction. Max size is
    configurable; when exceeded, the oldest (least recently used) entry
    is evicted.

    Args:
        max_size: Maximum number of cache entries. Defaults to 64.
    """

    def __init__(self, max_size: int = 64) -> None:
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")
        self._cache: OrderedDict[tuple[Path, int], CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size

    def get(self, file_path: Path) -> Optional[CacheEntry]:
        """Look up a cached entry by file path and current mtime.

        Resolves the path via .resolve() and reads os.stat().st_mtime_ns.
        On cache hit, moves the entry to the end (MRU position) for LRU.

        Args:
            file_path: Path to the KiCad file.

        Returns:
            CacheEntry if the file's mtime matches a cached entry, else None.
        """
        resolved = file_path.resolve()
        try:
            mtime = os.stat(resolved).st_mtime_ns
        except OSError:
            return None

        key = (resolved, mtime)
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None:
                # Move to end for LRU (most recently used)
                self._cache.move_to_end(key)
                return entry
        return None

    def put(self, file_path: Path, entry: CacheEntry) -> None:
        """Store a cache entry keyed by (resolved_path, mtime_ns).

        If the key already exists, updates the entry and moves to end.
        Evicts the oldest entry if the cache exceeds max_size.

        Args:
            file_path: Path to the KiCad file.
            entry: CacheEntry to store.
        """
        resolved = file_path.resolve()
        try:
            mtime = os.stat(resolved).st_mtime_ns
        except OSError:
            logger.warning("Cannot stat file for cache key: %s", resolved)
            return

        key = (resolved, mtime)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = entry
            # Evict oldest entries if over capacity
            while len(self._cache) > self._max_size:
                evicted_key, _ = self._cache.popitem(last=False)
                logger.debug("Evicted cache entry: %s", evicted_key)

    def invalidate(self, file_path: Path) -> None:
        """Remove all cache entries for a specific file path.

        Removes entries regardless of mtime -- useful after a write operation
        that changes the file on disk.

        Args:
            file_path: Path to the file to invalidate.
        """
        resolved = file_path.resolve()
        with self._lock:
            keys_to_remove = [
                key for key in self._cache if key[0] == resolved
            ]
            for key in keys_to_remove:
                del self._cache[key]

    def clear(self) -> None:
        """Remove all entries from the cache."""
        with self._lock:
            self._cache.clear()
