"""Local filesystem cache for downloaded footprints and symbols.

Uses part numbers as keys. Stores extracted .kicad_mod and .kicad_sym
files in subdirectories. Maintains a JSON manifest for metadata.

Directory structure:
    cache_root/
      cache_manifest.json
      footprints/{part_number}.kicad_mod
      symbols/{part_number}.kicad_sym

Security (threat model):
- T-12-01: ZIP path traversal protection via resolve() checks
- T-12-02: Part number validation against regex before filesystem use
"""

import hashlib
import logging
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from kicad_agent.project.adi_library.types import (
    CacheEntry,
    CacheManifest,
    FetchResult,
)

logger = logging.getLogger(__name__)

# Part number validation: alphanumeric start, then alphanumeric/dash/dot/underscore/slash
_PART_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-._/]*$")

# Allowed file extensions for extraction from ZIP archives
_ALLOWED_EXTENSIONS = frozenset({".kicad_mod", ".kicad_sym", ".step", ".stp", ".wrl"})


def _validate_part_number(part_number: str) -> None:
    """Validate that a part number is safe for filesystem use (T-12-02).

    Args:
        part_number: Part number string to validate.

    Raises:
        ValueError: If the part number contains unsafe characters.
    """
    if not _PART_NUMBER_PATTERN.match(part_number):
        raise ValueError(
            f"Invalid part number '{part_number}': must match "
            "^[A-Za-z0-9][A-Za-z0-9\\-._/]*$"
        )


class FootprintCache:
    """Local filesystem cache for downloaded footprints and symbols.

    Uses part numbers as keys. Stores extracted .kicad_mod and .kicad_sym
    files in subdirectories. Maintains a JSON manifest for metadata.
    """

    def __init__(self, cache_root: Path) -> None:
        """Initialize cache. Creates directories if they don't exist.

        Loads existing manifest from cache_root/cache_manifest.json.

        Args:
            cache_root: Root directory for the cache.
        """
        self.cache_root = cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)

        self.footprints_dir = cache_root / "footprints"
        self.symbols_dir = cache_root / "symbols"
        self.footprints_dir.mkdir(exist_ok=True)
        self.symbols_dir.mkdir(exist_ok=True)

        self.manifest_path = cache_root / "cache_manifest.json"
        self._manifest = self._load_manifest()

    def is_cached(self, part_number: str) -> bool:
        """Check if a part number exists in the cache manifest.

        Args:
            part_number: The part number to check.

        Returns:
            True if the part number has a cache entry.
        """
        return part_number in self._manifest.entries

    def get_cached_paths(self, part_number: str) -> dict[str, Path | None]:
        """Return dict with 'footprint' and 'symbol' keys pointing to cached files.

        Args:
            part_number: The part number to look up.

        Returns:
            Dict with 'footprint' and 'symbol' keys. Values are Paths or None
            if the part is not cached or has no file for that type.
        """
        entry = self._manifest.entries.get(part_number)
        if entry is None:
            return {"footprint": None, "symbol": None}

        return {
            "footprint": (
                self.cache_root / entry.footprint_path
                if entry.footprint_path
                else None
            ),
            "symbol": (
                self.cache_root / entry.symbol_path
                if entry.symbol_path
                else None
            ),
        }

    def add_entry(
        self,
        part_number: str,
        source: str,
        footprint_path: Path | None = None,
        symbol_path: Path | None = None,
        model_3d_path: Path | None = None,
        content_hash: str = "",
    ) -> None:
        """Add or update a cache entry. Copies files into cache directories.

        Updates the manifest file on disk.

        Args:
            part_number: The part number (used as key).
            source: Where the file came from ('samacsys', 'manual', 'local').
            footprint_path: Path to a .kicad_mod file to copy into cache.
            symbol_path: Path to a .kicad_sym file to copy into cache.
            model_3d_path: Path to a 3D model file to copy into cache.
            content_hash: SHA256 hash of the original archive.

        Raises:
            ValueError: If the part number fails validation (T-12-02).
        """
        _validate_part_number(part_number)

        dest_footprint: str | None = None
        dest_symbol: str | None = None
        dest_model_3d: str | None = None

        if footprint_path is not None and footprint_path.exists():
            dest = self.footprints_dir / f"{part_number}.kicad_mod"
            shutil.copy2(footprint_path, dest)
            dest_footprint = f"footprints/{part_number}.kicad_mod"

        if symbol_path is not None and symbol_path.exists():
            dest = self.symbols_dir / f"{part_number}.kicad_sym"
            shutil.copy2(symbol_path, dest)
            dest_symbol = f"symbols/{part_number}.kicad_sym"

        if model_3d_path is not None and model_3d_path.exists():
            # Preserve extension from source file
            ext = model_3d_path.suffix
            models_dir = self.cache_root / "models"
            models_dir.mkdir(exist_ok=True)
            dest = models_dir / f"{part_number}{ext}"
            shutil.copy2(model_3d_path, dest)
            dest_model_3d = f"models/{part_number}{ext}"

        self._manifest.entries[part_number] = CacheEntry(
            part_number=part_number,
            source=source,
            footprint_path=dest_footprint,
            symbol_path=dest_symbol,
            model_3d_path=dest_model_3d,
            downloaded_at=datetime.now(timezone.utc).isoformat(),
            content_hash=content_hash,
        )
        self._save_manifest()

    def extract_zip_safe(
        self, zip_path: Path, part_number: str, source: str
    ) -> FetchResult:
        """Extract a ZIP archive into the cache with path traversal protection.

        1. Open ZIP with zipfile.ZipFile
        2. For each entry that is NOT a directory:
           a. Resolve the target path
           b. Verify resolved path starts with cache_root.resolve() (T-12-01)
           c. Write the file bytes to the target path
        3. Classify extracted files by extension
        4. Add cache entry via add_entry()
        5. Return FetchResult with paths
        6. Delete the ZIP after successful extraction

        Args:
            zip_path: Path to the ZIP archive to extract.
            part_number: The part number for this download.
            source: Download source identifier.

        Returns:
            FetchResult with paths to extracted files.

        Raises:
            ValueError: If a ZIP entry would escape cache_root (T-12-01).
            FileNotFoundError: If the ZIP file does not exist.
        """
        _validate_part_number(part_number)

        if not zip_path.exists():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")

        cache_root_resolved = self.cache_root.resolve()
        footprint_path: Path | None = None
        symbol_path: Path | None = None
        model_3d_path: Path | None = None

        # Compute hash of the ZIP contents
        zip_data = zip_path.read_bytes()
        content_hash = self._compute_hash(zip_data)

        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                # Skip directories
                if info.is_dir():
                    continue

                filename = Path(info.filename)
                ext = filename.suffix.lower()

                # Only extract allowed file types
                if ext not in _ALLOWED_EXTENSIONS:
                    logger.debug("Skipping non-KiCad file in ZIP: %s", info.filename)
                    continue

                # Determine target subdirectory based on extension
                if ext == ".kicad_mod":
                    target_dir = self.footprints_dir
                    target_name = f"{part_number}.kicad_mod"
                elif ext == ".kicad_sym":
                    target_dir = self.symbols_dir
                    target_name = f"{part_number}.kicad_sym"
                else:
                    # 3D model
                    target_dir = self.cache_root / "models"
                    target_dir.mkdir(exist_ok=True)
                    target_name = f"{part_number}{ext}"

                target_file = (target_dir / target_name).resolve()

                # Path traversal protection (T-12-01)
                if not str(target_file).startswith(str(cache_root_resolved)):
                    raise ValueError(
                        f"ZIP entry '{info.filename}' escapes target directory "
                        f"(path traversal attempt)"
                    )

                # Ensure parent directory exists
                target_file.parent.mkdir(parents=True, exist_ok=True)

                # Write file bytes
                target_file.write_bytes(zf.read(info.filename))

                # Classify the extracted file
                if ext == ".kicad_mod":
                    footprint_path = target_file
                elif ext == ".kicad_sym":
                    symbol_path = target_file
                else:
                    model_3d_path = target_file

        # Register in cache manifest
        self.add_entry(
            part_number=part_number,
            source=source,
            footprint_path=footprint_path,
            symbol_path=symbol_path,
            model_3d_path=model_3d_path,
            content_hash=content_hash,
        )

        # Delete ZIP after successful extraction
        zip_path.unlink()

        return FetchResult(
            part_number=part_number,
            footprint_path=footprint_path,
            symbol_path=symbol_path,
            model_3d_path=model_3d_path,
            source=source,
            from_cache=False,
        )

    def _compute_hash(self, data: bytes) -> str:
        """Compute SHA256 hex digest of bytes using hashlib.

        Args:
            data: Raw bytes to hash.

        Returns:
            Hex digest string.
        """
        return hashlib.sha256(data).hexdigest()

    def _load_manifest(self) -> CacheManifest:
        """Load manifest from cache_manifest.json.

        Returns:
            CacheManifest parsed from file, or empty CacheManifest if missing.
        """
        if self.manifest_path.exists():
            try:
                data = self.manifest_path.read_text(encoding="utf-8")
                return CacheManifest.model_validate_json(data)
            except Exception:
                logger.warning(
                    "Failed to parse cache manifest, starting fresh: %s",
                    self.manifest_path,
                )
        return CacheManifest()

    def _save_manifest(self) -> None:
        """Write manifest to cache_manifest.json with model_dump_json(indent=2)."""
        self.manifest_path.write_text(
            self._manifest.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
