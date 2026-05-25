"""GitHub repo discovery and KiCad file pair extraction.

RW-01: Discovers KiCad repositories via GitHub Search API, extracts
schematic+PCB file pairs from repo trees, and returns structured results.

Uses PyGithub for authenticated search with rate-limit-aware pagination.
Uses GitHub Git Tree API (single request per repo) for efficient file listing.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from github import Auth, Github, GithubException

from kicad_agent.crawler.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

_DEFAULT_QUERIES: list[str] = [
    "kicad_pcb filename:kicad_pcb",
    "kicad_sch filename:kicad_sch",
    "extension:kicad_pcb extension:kicad_sch",
    "topic:kicad",
    "topic:pcb-design",
    "topic:hardware",
    "topic:electronics",
    "kicad_pcb language:html",  # matches repos with KiCad web viewers
    "pcb kicad stars:>1",
    "hardware kicad stars:>0",
]


@dataclass(frozen=True)
class RepoInfo:
    """Immutable metadata for a discovered GitHub repository.

    Attributes:
        full_name: Owner/repo string (e.g. 'user/project').
        html_url: Browser-accessible URL.
        stars: Repository star count.
        description: Repository description (untrusted external data).
        default_branch: Primary branch name (e.g. 'main').
    """

    full_name: str
    html_url: str
    stars: int
    description: Optional[str]
    default_branch: str


@dataclass(frozen=True)
class KicadFilePair:
    """A matched schematic+PCB file pair within a repository.

    Attributes:
        schematic_path: Path to .kicad_sch file within the repo.
        pcb_path: Path to .kicad_pcb file within the repo.
        base_name: Shared base name (e.g. 'board' from 'board.kicad_sch').
    """

    schematic_path: str
    pcb_path: str
    base_name: str


class GithubDiscovery:
    """Discovers KiCad repositories and extracts file pairs.

    Uses GitHub Search API with multiple queries, deduplicates results,
    and extracts schematic+PCB file pairs from repo trees.
    """

    def __init__(self, token: str) -> None:
        """Initialize with a GitHub personal access token.

        Args:
            token: GitHub PAT with public_repo scope. Never logged.
        """
        self._token = token
        self._client = Github(auth=Auth.Token(token))
        self._rate_limiter = RateLimiter(self._client)

    def discover_repos(
        self,
        max_repos: int = 500,
        queries: list[str] | None = None,
    ) -> list[RepoInfo]:
        """Search GitHub for repositories containing KiCad files.

        Runs multiple search queries, deduplicates by full_name, and returns
        up to max_repos unique RepoInfo objects sorted by stars (desc).

        Args:
            max_repos: Maximum number of repos to return.
            queries: Search queries. Defaults to _DEFAULT_QUERIES.

        Returns:
            Deduplicated list of RepoInfo, truncated to max_repos.
        """
        if queries is None:
            queries = _DEFAULT_QUERIES

        seen: dict[str, RepoInfo] = {}

        for query in queries:
            self._rate_limiter.wait_if_needed("search")

            try:
                results = self._client.search_repositories(
                    query, sort="stars", order="desc"
                )
                for repo in results:
                    if repo.full_name in seen:
                        continue
                    seen[repo.full_name] = RepoInfo(
                        full_name=repo.full_name,
                        html_url=repo.html_url,
                        stars=repo.stargazers_count,
                        description=repo.description,
                        default_branch=repo.default_branch,
                    )
                    if len(seen) >= max_repos:
                        break
            except GithubException as e:
                logger.warning("Search query '%s' failed: %s", query, e)
                continue

        return list(seen.values())

    def find_kicad_pairs(self, repo_info: RepoInfo) -> list[KicadFilePair]:
        """Extract matched .kicad_sch + .kicad_pcb pairs from a repo tree.

        Uses GitHub Git Tree API (single recursive request) to list all files,
        then matches by shared base name.

        Args:
            repo_info: RepoInfo identifying the target repository.

        Returns:
            List of KicadFilePair for matched schematic+PCB pairs.
            Empty list if the repo is inaccessible or has no pairs.
        """
        try:
            repo = self._client.get_repo(repo_info.full_name)
            self._rate_limiter.wait_if_needed("core")

            tree = repo.get_git_tree(repo_info.default_branch, recursive=True)

            schematics: dict[str, str] = {}  # base_name -> path
            pcbs: dict[str, str] = {}

            for element in tree.tree:
                if element.type != "blob":
                    continue
                path = element.path
                if path.endswith(".kicad_sch"):
                    base = path.rsplit("/", 1)[-1].removesuffix(".kicad_sch")
                    schematics[base] = path
                elif path.endswith(".kicad_pcb"):
                    base = path.rsplit("/", 1)[-1].removesuffix(".kicad_pcb")
                    pcbs[base] = path

            # Intersect keys to find matched pairs
            pairs: list[KicadFilePair] = []
            for base_name in sorted(set(schematics.keys()) & set(pcbs.keys())):
                pairs.append(
                    KicadFilePair(
                        schematic_path=schematics[base_name],
                        pcb_path=pcbs[base_name],
                        base_name=base_name,
                    )
                )

            return pairs

        except GithubException as e:
            logger.warning(
                "Failed to get tree for %s: %s", repo_info.full_name, e
            )
            return []
        except Exception as e:
            logger.warning(
                "Unexpected error processing %s: %s", repo_info.full_name, e
            )
            return []

    def discover_pairs(
        self, max_repos: int = 500
    ) -> list[tuple[RepoInfo, list[KicadFilePair]]]:
        """Discover repos and extract file pairs in one pass.

        Combines discover_repos + find_kicad_pairs. Filters out repos
        with zero pairs.

        Args:
            max_repos: Maximum number of repos to search.

        Returns:
            List of (RepoInfo, list[KicadFilePair]) for repos with pairs.
        """
        repos = self.discover_repos(max_repos=max_repos)
        results: list[tuple[RepoInfo, list[KicadFilePair]]] = []

        for repo_info in repos:
            pairs = self.find_kicad_pairs(repo_info)
            if pairs:
                results.append((repo_info, pairs))

        logger.info(
            "Discovered %d repos with KiCad file pairs out of %d searched",
            len(results),
            len(repos),
        )

        return results
