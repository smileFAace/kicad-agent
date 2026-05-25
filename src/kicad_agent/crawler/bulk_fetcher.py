"""Bulk repo fetching via git clone for high-scale data collection.

Uses `git clone --depth 1` to fetch entire repos in a single operation,
then scans for .kicad_pcb + .kicad_sch file pairs locally. Orders of
magnitude faster than the Contents API for repos with many KiCad files.

Usage:
    from kicad_agent.crawler.bulk_fetcher import BulkFetcher

    fetcher = BulkFetcher(staging_dir=Path("kicad_staging"))
    pairs = fetcher.clone_and_scan("user/kicad-project")
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalFilePair:
    """A matched schematic+PCB pair found on local disk.

    Attributes:
        repo_name: GitHub owner/repo string.
        schematic_path: Absolute path to .kicad_sch file.
        pcb_path: Absolute path to .kicad_pcb file.
        base_name: Shared base name (e.g. 'board').
    """

    repo_name: str
    schematic_path: Path
    pcb_path: Path
    base_name: str


class BulkFetcher:
    """Clone repos and scan for KiCad file pairs locally.

    Uses shallow clones (depth=1) for speed. Cloned repos are stored
    under staging_dir/{owner}_{repo}/ and can be re-scanned without
    re-cloning if the directory already exists.
    """

    def __init__(self, staging_dir: Path, timeout: int = 120) -> None:
        """Initialize with staging directory and clone timeout.

        Args:
            staging_dir: Root directory for cloned repos.
            timeout: Maximum seconds per git clone operation.
        """
        self._staging_dir = Path(staging_dir)
        self._timeout = timeout
        self._staging_dir.mkdir(parents=True, exist_ok=True)

    @property
    def staging_dir(self) -> Path:
        return self._staging_dir

    def _repo_dir(self, repo_name: str) -> Path:
        """Get local directory path for a repo."""
        safe_name = repo_name.replace("/", "_")
        return self._staging_dir / safe_name

    def clone(self, repo_name: str, repo_url: str | None = None) -> Path | None:
        """Shallow-clone a repo to staging directory.

        If the directory already exists, skips the clone and returns
        the existing path (incremental mode).

        Args:
            repo_name: GitHub owner/repo string (e.g. 'user/project').
            repo_url: Optional full clone URL. If None, constructs
                from repo_name using HTTPS.

        Returns:
            Path to cloned repo directory, or None if clone failed.
        """
        target = self._repo_dir(repo_name)

        # Skip if already cloned
        if target.is_dir() and any(target.iterdir()):
            logger.debug("Already cloned: %s -> %s", repo_name, target)
            return target

        if repo_url is None:
            repo_url = f"https://github.com/{repo_name}.git"

        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, str(target)],
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )

            if result.returncode != 0:
                stderr = result.stderr.strip()
                logger.warning("Clone failed for %s: %s", repo_name, stderr[:200])
                # Clean up partial clone
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                return None

            logger.info("Cloned: %s -> %s", repo_name, target)
            return target

        except subprocess.TimeoutExpired:
            logger.warning("Clone timed out for %s (%ds)", repo_name, self._timeout)
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            return None
        except Exception as e:
            logger.warning("Clone error for %s: %s", repo_name, e)
            return None

    def scan_for_pairs(self, repo_dir: Path, repo_name: str = "") -> list[LocalFilePair]:
        """Scan a local directory for matched .kicad_sch + .kicad_pcb pairs.

        Searches recursively, matches by base name within each directory.

        Args:
            repo_dir: Local directory to scan.
            repo_name: Repo name for metadata (optional).

        Returns:
            List of LocalFilePair for matched schematic+PCB pairs.
        """
        if not repo_name:
            repo_name = repo_dir.name

        # Index all KiCad files by (directory, base_name)
        schematics: dict[tuple[str, str], Path] = {}
        pcbs: dict[tuple[str, str], Path] = {}

        for path in repo_dir.rglob("*.kicad_sch"):
            key = (str(path.parent), path.stem)
            schematics[key] = path

        for path in repo_dir.rglob("*.kicad_pcb"):
            key = (str(path.parent), path.stem)
            pcbs[key] = path

        # Match pairs by (directory, base_name)
        pairs: list[LocalFilePair] = []
        for key in sorted(set(schematics.keys()) & set(pcbs.keys())):
            pairs.append(LocalFilePair(
                repo_name=repo_name,
                schematic_path=schematics[key],
                pcb_path=pcbs[key],
                base_name=key[1],
            ))

        return pairs

    def clone_and_scan(
        self,
        repo_name: str,
        repo_url: str | None = None,
    ) -> list[LocalFilePair]:
        """Clone a repo and scan for KiCad file pairs.

        Args:
            repo_name: GitHub owner/repo string.
            repo_url: Optional full clone URL.

        Returns:
            List of LocalFilePair found in the cloned repo.
        """
        repo_dir = self.clone(repo_name, repo_url)
        if repo_dir is None:
            return []
        return self.scan_for_pairs(repo_dir, repo_name)

    def clone_batch(
        self,
        repo_names: list[str],
        skip_existing: bool = True,
    ) -> dict[str, list[LocalFilePair]]:
        """Clone multiple repos and scan for pairs.

        Args:
            repo_names: List of GitHub owner/repo strings.
            skip_existing: Skip repos already in staging_dir.

        Returns:
            Dict mapping repo_name -> list of LocalFilePair.
        """
        results: dict[str, list[LocalFilePair]] = {}

        for repo_name in repo_names:
            target = self._repo_dir(repo_name)
            if skip_existing and target.is_dir() and any(target.iterdir()):
                # Already cloned, just scan
                pairs = self.scan_for_pairs(target, repo_name)
            else:
                pairs = self.clone_and_scan(repo_name)

            if pairs:
                results[repo_name] = pairs

        logger.info(
            "Bulk fetch: %d/%d repos had KiCad pairs",
            len(results), len(repo_names),
        )
        return results
