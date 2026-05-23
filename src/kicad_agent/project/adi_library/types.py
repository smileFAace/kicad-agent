"""Type definitions for the ADI footprint library module.

Frozen dataclasses for immutable result types. Pydantic model for the
cache manifest (serializable to JSON).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


@dataclass(frozen=True)
class FetchResult:
    """Immutable result of a footprint fetch operation.

    Attributes:
        part_number: The queried part number (e.g. 'AD8606ARMZ').
        footprint_path: Path to the cached .kicad_mod file, or None if not found.
        symbol_path: Path to the cached .kicad_sym file, or None if not found.
        model_3d_path: Path to the cached 3D model file, or None.
        source: Where the file came from ('samacsys', 'manual', 'local').
        from_cache: True if served from cache without network access.
    """

    part_number: str
    footprint_path: Optional[Path]
    symbol_path: Optional[Path]
    model_3d_path: Optional[Path]
    source: str
    from_cache: bool


class CacheEntry(BaseModel):
    """Pydantic model for a single cache manifest entry.

    Serialized to JSON in the cache manifest file.
    """

    part_number: str
    source: str  # "samacsys" | "manual" | "local"
    footprint_path: Optional[str] = None
    symbol_path: Optional[str] = None
    model_3d_path: Optional[str] = None
    downloaded_at: str  # ISO 8601 timestamp
    content_hash: str = ""  # SHA256 of the downloaded archive


class CacheManifest(BaseModel):
    """Pydantic model for the cache manifest file (cache_manifest.json).

    Maps part numbers to their cached file locations and metadata.
    """

    version: str = "1.0"
    entries: dict[str, CacheEntry] = {}
