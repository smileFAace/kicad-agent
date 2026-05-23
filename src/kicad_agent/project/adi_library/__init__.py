"""ADI footprint library -- on-demand manufacturer footprint and symbol fetching.

Provides local caching, SamacSys HTTP client, and KiCad library integration
for Analog Devices (and other manufacturer) parts.
"""

from kicad_agent.project.adi_library.types import (
    CacheEntry,
    CacheManifest,
    FetchResult,
)
from kicad_agent.project.adi_library.cache import FootprintCache

__all__ = [
    "CacheEntry",
    "CacheManifest",
    "FetchResult",
    "FootprintCache",
]
