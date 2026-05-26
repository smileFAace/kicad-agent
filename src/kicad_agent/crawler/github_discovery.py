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
    # Core KiCad file queries
    "kicad_pcb filename:kicad_pcb",
    "kicad_sch filename:kicad_sch",
    "extension:kicad_pcb extension:kicad_sch",
    # Topic queries
    "topic:kicad",
    "topic:pcb-design",
    "topic:hardware",
    "topic:electronics",
    # Star-filtered for quality
    "kicad_pcb language:html",  # matches repos with KiCad web viewers
    "pcb kicad stars:>1",
    "hardware kicad stars:>0",
    # Board-specific queries (MCU dev boards)
    "arduino filename:kicad_pcb",
    "stm32 filename:kicad_pcb",
    "esp32 filename:kicad_pcb",
    "rp2040 filename:kicad_pcb",
    # More star tiers for breadth
    "kicad_pcb stars:>5",
    "kicad_pcb stars:>10",
    # Design tool combos
    "kicad_pcb language:python",
    "pcb-design kicad stars:>2",
    "open-hardware kicad",
]

# Topics for Layer 1 discovery (search API, broader coverage)
_DISCOVERY_TOPICS: list[str] = [
    "kicad", "pcb-design", "hardware", "electronics",
    "eda", "circuit-design", "pcb", "schematic",
    "footprint", "hardware-design", "open-hardware",
    "embedded", "mcu", "pcb-layout",
]

# Known KiCad-heavy GitHub organizations for curated discovery
_CURATED_ORGS: list[str] = [
    # Original
    "KiCad",
    "open-source-hardware",
    "electroniceel",
    "kitspace",
    "adamws",
    # Major hardware vendors
    "arduino",
    "raspberrypi",
    "Adafruit",
    "SparkFun",
    "SeeedStudio",
    # Keyboard / input device designers (prolific KiCad users)
    "foostan",
    "ai03-2725",
    "perigoso",
    # Open hardware projects
    "tinkerforge",
    "greatscottgadgets",
    "mossmann",
    "secworks",
    # KiCad tooling / libraries
    "sunzhengwu-kicad",
    "XBain",
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
        max_pages: int = 3,
    ) -> list[RepoInfo]:
        """Search GitHub for repositories containing KiCad files.

        Runs multiple search queries, deduplicates by full_name, and returns
        up to max_repos unique RepoInfo objects sorted by stars (desc).

        Args:
            max_repos: Maximum number of repos to return.
            queries: Search queries. Defaults to _DEFAULT_QUERIES.
            max_pages: Max pages per query to avoid burning search API quota.
                Search API allows 30 req/hr; each page = 1 request.

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
                page_count = 0
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
                    # PyGithub auto-pages; track pages to limit API spend
                    page_count += 1
                    if page_count % 100 == 0:
                        page_count_within = page_count
                        if page_count_within >= max_pages * 100:
                            logger.info("Query '%s': hit max_pages=%d, stopping", query, max_pages)
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

    def discover_by_topics(
        self,
        max_repos: int = 2000,
        topics: list[str] | None = None,
        max_pages: int = 5,
    ) -> list[RepoInfo]:
        """Enumerate repos by GitHub topics using Search API.

        Uses topic-based queries to find repos that self-identify as
        KiCad or hardware projects. Each topic query can return up to
        1000 results. Uses the search API rate limit (30 req/hr).

        Args:
            max_repos: Maximum number of unique repos to return.
            topics: Topic strings to search. Defaults to _DISCOVERY_TOPICS.
            max_pages: Max pages per topic query (each page = 1 search API call).

        Returns:
            Deduplicated list of RepoInfo, sorted by stars (desc).
        """
        if topics is None:
            topics = _DISCOVERY_TOPICS

        seen: dict[str, RepoInfo] = {}

        for topic in topics:
            self._rate_limiter.wait_if_needed("search")

            try:
                query = f"topic:{topic}"
                results = self._client.search_repositories(
                    query, sort="stars", order="desc"
                )
                count = 0
                for repo in results:
                    count += 1
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
                    # Stop after max_pages worth of results to save quota
                    if count >= max_pages * 100:
                        break

                logger.info("Topic '%s': found %d total unique repos so far", topic, len(seen))

            except GithubException as e:
                logger.warning("Topic query '%s' failed: %s", topic, e)
                continue

            if len(seen) >= max_repos:
                break

        # Sort by stars descending
        repos = sorted(seen.values(), key=lambda r: r.stars, reverse=True)
        return repos[:max_repos]

    def discover_from_curated(
        self,
        max_repos: int = 500,
        orgs: list[str] | None = None,
    ) -> list[RepoInfo]:
        """Discover repos from known KiCad-heavy GitHub orgs/users.

        Enumerates public repos in curated accounts and filters for those
        likely to contain KiCad files (by name, description, or topic).
        Falls back to get_user() when get_organization() 404s.

        Uses the core API (5000/hr rate limit) not the search API.

        Args:
            max_repos: Maximum number of repos to return.
            orgs: GitHub account names to scan. Defaults to _CURATED_ORGS.

        Returns:
            List of RepoInfo for repos likely to contain KiCad files.
        """
        if orgs is None:
            orgs = _CURATED_ORGS

        _KICAD_KEYWORDS = {"kicad", "pcb", "schematic", "footprint", "hardware", "eda"}

        seen: dict[str, RepoInfo] = {}

        for org_name in orgs:
            self._rate_limiter.wait_if_needed("core")

            try:
                try:
                    account = self._client.get_organization(org_name)
                except GithubException:
                    # Not an org — try as a user account
                    account = self._client.get_user(org_name)
                repos_page = account.get_repos(sort="stars", direction="desc")

                for repo in repos_page:
                    # Check if repo is likely to have KiCad files
                    name_lower = (repo.name or "").lower()
                    desc_lower = (repo.description or "").lower()
                    topics = [t.lower() for t in (repo.topics or [])]

                    text = f"{name_lower} {desc_lower} {' '.join(topics)}"
                    has_kicad_signal = any(kw in text for kw in _KICAD_KEYWORDS)

                    if has_kicad_signal or repo.fork:
                        if repo.full_name not in seen:
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
                logger.warning("Failed to scan account '%s': %s", org_name, e)
                continue

            if len(seen) >= max_repos:
                break

        return list(seen.values())[:max_repos]

    def discover_from_forks(
        self,
        repos: list[RepoInfo],
        min_stars: int = 0,
        max_forks_per_repo: int = 100,
        depth: int = 2,
    ) -> list[RepoInfo]:
        """Scan fork networks of repos for additional KiCad projects.

        For each repo with sufficient stars, lists its forks and includes
        those likely to contain KiCad files. Uses core API (5000/hr).
        With depth > 1, scans forks-of-forks recursively.

        Args:
            repos: Already-discovered repos to scan forks of.
            min_stars: Only scan forks of repos with this many stars.
            max_forks_per_repo: Max forks to enumerate per parent repo.
            depth: Recursion depth. 1 = direct forks only, 2 = forks of forks.

        Returns:
            List of RepoInfo for fork repos.
        """
        results: list[RepoInfo] = []
        seen_names: set[str] = {r.full_name for r in repos}

        to_scan = [r for r in repos if r.stars >= min_stars]
        logger.info("Scanning forks of %d repos (stars >= %d, depth=%d)",
                     len(to_scan), min_stars, depth)

        for current_depth in range(depth):
            if not to_scan:
                break
            logger.info("Fork depth %d: scanning %d repos", current_depth + 1, len(to_scan))

            next_round: list[RepoInfo] = []

            for i, repo_info in enumerate(to_scan):
                if (i + 1) % 50 == 0:
                    logger.info("Fork scan progress: %d/%d (%d total forks found)",
                                i + 1, len(to_scan), len(results))

                try:
                    self._rate_limiter.wait_if_needed("core")
                    repo = self._client.get_repo(repo_info.full_name)

                    forks = repo.get_forks()
                    count = 0
                    for fork in forks:
                        if count >= max_forks_per_repo:
                            break
                        if fork.full_name in seen_names:
                            continue

                        # Parent was KiCad, so fork likely is too
                        fork_info = RepoInfo(
                            full_name=fork.full_name,
                            html_url=fork.html_url,
                            stars=fork.stargazers_count,
                            description=fork.description,
                            default_branch=fork.default_branch,
                        )
                        results.append(fork_info)
                        seen_names.add(fork.full_name)
                        count += 1

                        # Queue for next depth round
                        if current_depth < depth - 1 and fork.stargazers_count >= 1:
                            next_round.append(fork_info)

                except GithubException as e:
                    logger.warning("Failed to scan forks of %s: %s", repo_info.full_name, e)
                    continue

            to_scan = next_round
            logger.info("Fork depth %d complete: %d total forks, %d queued for next depth",
                        current_depth + 1, len(results), len(to_scan))

        logger.info("Fork scan found %d additional repos", len(results))
        return results

    def find_schematic_files(self, repo_info: RepoInfo) -> list[str]:
        """Find all .kicad_sch files in a repo (not just matched pairs).

        Uses GitHub Git Tree API to list all schematic files. Useful for
        collecting unmatched schematics for schematic-only training data.

        Args:
            repo_info: RepoInfo identifying the target repository.

        Returns:
            List of repo-relative paths to .kicad_sch files.
        """
        try:
            repo = self._client.get_repo(repo_info.full_name)
            self._rate_limiter.wait_if_needed("core")

            tree = repo.get_git_tree(repo_info.default_branch, recursive=True)

            schematics: list[str] = []
            for element in tree.tree:
                if element.type != "blob":
                    continue
                if element.path.endswith(".kicad_sch"):
                    schematics.append(element.path)

            return schematics

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

    def discover_from_code_search(
        self,
        max_repos: int = 2000,
    ) -> list[RepoInfo]:
        """Discover repos via GitHub code search for KiCad file paths.

        Uses search_code() with path/filename filters to find repos
        containing actual .kicad_pcb files. Shares the search API rate
        limit (30 req/hr). Each query can return up to 1000 results.

        Args:
            max_repos: Maximum number of unique repos to return.

        Returns:
            Deduplicated list of RepoInfo sorted by stars (desc).
        """
        code_queries = [
            "filename:kicad_pcb",
            "path:.kicad_pcb",
            "filename:kicad_sch path:.",
            "extension:kicad_pcb",
            "extension:kicad_sch",
            "filename:kicad_pcb board",
            "path:pcb filename:kicad",
            "path:hardware filename:kicad_pcb",
        ]

        seen: dict[str, RepoInfo] = {}

        for query in code_queries:
            self._rate_limiter.wait_if_needed("search")

            try:
                results = self._client.search_code(query)
                for code_result in results:
                    full_name = code_result.repository.full_name
                    if full_name in seen:
                        continue

                    repo = code_result.repository
                    seen[full_name] = RepoInfo(
                        full_name=repo.full_name,
                        html_url=repo.html_url,
                        stars=repo.stargazers_count,
                        description=repo.description,
                        default_branch=repo.default_branch,
                    )
                    if len(seen) >= max_repos:
                        break

                logger.info("Code search '%s': %d unique repos so far", query, len(seen))

            except GithubException as e:
                logger.warning("Code search '%s' failed: %s", query, e)
                continue

            if len(seen) >= max_repos:
                break

        repos = sorted(seen.values(), key=lambda r: r.stars, reverse=True)
        return repos[:max_repos]

    def discover_all(
        self,
        max_repos: int = 2000,
        strategies: list[str] | None = None,
    ) -> list[RepoInfo]:
        """Run multiple discovery strategies, deduplicate, sort by stars.

        Args:
            max_repos: Maximum total unique repos to return.
            strategies: Which strategies to run. Defaults to all.
                Options: "search", "topics", "curated", "code_search", "forks".
                Order matters: forks amplifies earlier results.

        Returns:
            Deduplicated list of RepoInfo sorted by stars (desc).
        """
        if strategies is None:
            strategies = ["curated", "search", "topics", "code_search", "forks"]

        seen: dict[str, RepoInfo] = {}

        # Allocate budget per strategy
        per_strategy = max_repos * 2  # over-allocate, dedup at end

        # Curated first: uses core API (5000/hr), fast, high-quality
        if "curated" in strategies:
            logger.info("Strategy: curated orgs (%d budget)", per_strategy)
            repos = self.discover_from_curated(max_repos=per_strategy)
            for r in repos:
                if r.full_name not in seen:
                    seen[r.full_name] = r
            logger.info("After curated: %d unique repos", len(seen))

        if "search" in strategies and len(seen) < max_repos:
            logger.info("Strategy: search queries (%d budget)", per_strategy)
            repos = self.discover_repos(max_repos=per_strategy)
            for r in repos:
                if r.full_name not in seen:
                    seen[r.full_name] = r
            logger.info("After search: %d unique repos", len(seen))

        if "topics" in strategies and len(seen) < max_repos:
            logger.info("Strategy: topic enumeration (%d budget)", per_strategy)
            repos = self.discover_by_topics(max_repos=per_strategy)
            for r in repos:
                if r.full_name not in seen:
                    seen[r.full_name] = r
            logger.info("After topics: %d unique repos", len(seen))

        if "code_search" in strategies and len(seen) < max_repos:
            logger.info("Strategy: code search (%d budget)", per_strategy)
            repos = self.discover_from_code_search(max_repos=per_strategy)
            for r in repos:
                if r.full_name not in seen:
                    seen[r.full_name] = r
            logger.info("After code_search: %d unique repos", len(seen))

        # Forks last: amplifies earlier results via fork networks
        if "forks" in strategies and len(seen) < max_repos:
            logger.info("Strategy: fork scanning (amplifying %d repos)", len(seen))
            existing = list(seen.values())
            fork_repos = self.discover_from_forks(existing)
            for r in fork_repos:
                if r.full_name not in seen:
                    seen[r.full_name] = r
            logger.info("After forks: %d unique repos", len(seen))

        # Sort by stars, truncate
        all_repos = sorted(seen.values(), key=lambda r: r.stars, reverse=True)
        return all_repos[:max_repos]
