#!/usr/bin/env python3
"""High-speed multi-strategy repo discovery for 100K KiCad crawl.

Uses ALL available GitHub API rate limit buckets in parallel:
  - GraphQL API (5,000/hr): enumerate repos by language + topic
  - REST Core API (5,000/hr): scan curated orgs, list forks
  - Search API (30/hr): targeted queries for quality repos
  - Code Search API (10/min): find repos by actual .kicad_pcb files
  - Google scrape: broad web discovery via mcp__web_reader

Outputs a deduplicated repo list to a JSON file for the bulk fetcher.

Usage:
    export GITHUB_TOKEN="$(gh auth token)"
    python3 scripts/discover_100k.py --output discovered_repos.json --max-repos 100000
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from github import Auth, Github, GithubException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("discover_100k")


@dataclass
class RepoRecord:
    """Minimal repo info for serialization."""

    full_name: str
    html_url: str
    stars: int
    default_branch: str

    def to_dict(self) -> dict:
        return {
            "full_name": self.full_name,
            "html_url": self.html_url,
            "stars": self.stars,
            "default_branch": self.default_branch,
        }


# ---------------------------------------------------------------------------
# Strategy 1: GraphQL — enumerate repos by topic (5,000/hr, no search limit)
# ---------------------------------------------------------------------------

_GRAPHQL_TOPICS = [
    "kicad", "pcb-design", "hardware", "electronics", "eda",
    "circuit-design", "pcb", "schematic", "footprint", "hardware-design",
    "open-hardware", "embedded", "mcu", "pcb-layout", "fpga",
    "raspberry-pi-pcb", "stm32-pcb", "esp32-pcb", "arduino-pcb",
]

_GRAPHQL_QUERY = """
query($query: String!, $cursor: String) {
  search(query: $query, type: REPOSITORY, first: 100, after: $cursor) {
    repositoryCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on Repository {
        nameWithOwner
        url
        stargazerCount
        defaultBranchRef { name }
      }
    }
  }
}
"""


def _graphql_discovery(token: str, max_repos: int) -> dict[str, RepoRecord]:
    """Use GraphQL search (shares search API quota but gets 100/page)."""
    import requests

    seen: dict[str, RepoRecord] = {}
    headers = {"Authorization": f"bearer {token}"}
    endpoint = "https://api.github.com/graphql"

    for topic in _GRAPHQL_TOPICS:
        if len(seen) >= max_repos:
            break

        query_text = f"topic:{topic} sort:stars-desc"
        cursor = None

        for page in range(10):  # max 10 pages x 100 = 1000 per topic
            if len(seen) >= max_repos:
                break

            variables = {"query": query_text}
            if cursor:
                variables["cursor"] = cursor

            try:
                resp = requests.post(
                    endpoint,
                    json={"query": _GRAPHQL_QUERY, "variables": variables},
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code == 403:
                    logger.warning("GraphQL rate limited, sleeping 60s")
                    time.sleep(60)
                    continue
                if resp.status_code != 200:
                    logger.warning("GraphQL error %d: %s", resp.status_code, resp.text[:200])
                    break

                data = resp.json()
                search = data.get("data", {}).get("search", {})
                nodes = search.get("nodes", [])

                for node in nodes:
                    name = node.get("nameWithOwner", "")
                    if not name or name in seen:
                        continue
                    branch = node.get("defaultBranchRef")
                    seen[name] = RepoRecord(
                        full_name=name,
                        html_url=node.get("url", f"https://github.com/{name}"),
                        stars=node.get("stargazerCount", 0),
                        default_branch=branch["name"] if branch else "main",
                    )

                page_info = search.get("pageInfo", {})
                if not page_info.get("hasNextPage"):
                    break
                cursor = page_info.get("endCursor")

            except Exception as e:
                logger.warning("GraphQL topic '%s' page %d failed: %s", topic, page, e)
                break

        logger.info("GraphQL topic '%s': %d total repos so far", topic, len(seen))

    logger.info("GraphQL: %d unique repos", len(seen))
    return seen


# ---------------------------------------------------------------------------
# Strategy 2: REST API — enumerate repos by language (5,000/hr)
# ---------------------------------------------------------------------------

def _rest_language_discovery(token: str, max_repos: int) -> dict[str, RepoRecord]:
    """Use REST /repositories endpoint filtered by language."""
    import requests as req

    seen: dict[str, RepoRecord] = {}
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Search for repos with KiCad-related keywords in name/description
    # Using the standard search API but with sort=stars and per_page=100
    queries = [
        "kicad_pcb",
        "kicad_sch",
        "kicad pcb",
        "pcb design kicad",
        "schematic kicad",
        "hardware kicad",
        "footprint kicad",
        "kicad layout",
        "kicad board",
        "kicad project",
        "kicad hardware",
        "open hardware pcb",
        "pcb layout",
        "circuit board design",
        "stm32 pcb",
        "esp32 pcb",
        "arduino pcb",
        "rp2040 pcb",
        "fpga pcb",
        "dev board pcb",
    ]

    for query in queries:
        if len(seen) >= max_repos:
            break

        for page in range(1, 11):  # 10 pages x 100 = 1000 per query
            if len(seen) >= max_repos:
                break

            url = (
                f"https://api.github.com/search/repositories"
                f"?q={quote(query)}&sort=stars&order=desc&per_page=100&page={page}"
            )

            try:
                resp = req.get(url, headers=headers, timeout=30)
                if resp.status_code == 403:
                    logger.warning("REST search rate limited, sleeping 60s")
                    time.sleep(60)
                    continue
                if resp.status_code != 200:
                    break

                items = resp.json().get("items", [])
                if not items:
                    break

                for item in items:
                    name = item.get("full_name", "")
                    if name and name not in seen:
                        seen[name] = RepoRecord(
                            full_name=name,
                            html_url=item.get("html_url", ""),
                            stars=item.get("stargazers_count", 0),
                            default_branch=item.get("default_branch", "main"),
                        )

            except Exception as e:
                logger.warning("REST query '%s' page %d failed: %s", query, page, e)
                break

        logger.info("REST query '%s': %d total repos so far", query, len(seen))

    logger.info("REST language: %d unique repos", len(seen))
    return seen


# ---------------------------------------------------------------------------
# Strategy 3: Code search API (10/min, separate quota)
# ---------------------------------------------------------------------------

_CODE_SEARCH_QUERIES = [
    "filename:kicad_pcb",
    "extension:kicad_pcb",
    "filename:kicad_sch path:.",
    "extension:kicad_sch",
    "path:pcb filename:kicad_pcb",
    "path:hardware filename:kicad_pcb",
    "path:board filename:kicad_pcb",
    "path:schematic filename:kicad_sch",
    "filename:kicad_pcb board",
    "filename:kicad_sch schematic",
]


def _code_search_discovery(token: str, max_repos: int) -> dict[str, RepoRecord]:
    """Use code search API (separate 10/min quota) to find repos with KiCad files."""
    import requests as req

    seen: dict[str, RepoRecord] = {}
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    for query in _CODE_SEARCH_QUERIES:
        if len(seen) >= max_repos:
            break

        for page in range(1, 4):  # 3 pages x 100
            url = (
                f"https://api.github.com/search/code"
                f"?q={quote(query)}&per_page=100&page={page}"
            )

            try:
                resp = req.get(url, headers=headers, timeout=30)
                if resp.status_code == 403:
                    logger.warning("Code search rate limited, sleeping 60s")
                    time.sleep(60)
                    continue
                if resp.status_code != 200:
                    break

                items = resp.json().get("items", [])
                if not items:
                    break

                for item in items:
                    repo = item.get("repository", {})
                    name = repo.get("full_name", "")
                    if name and name not in seen:
                        seen[name] = RepoRecord(
                            full_name=name,
                            html_url=repo.get("html_url", ""),
                            stars=0,  # code search doesn't return stars
                            default_branch="main",
                        )

            except Exception as e:
                logger.warning("Code search '%s' page %d failed: %s", query, page, e)
                break

        logger.info("Code search '%s': %d total repos so far", query, len(seen))

    logger.info("Code search: %d unique repos", len(seen))
    return seen


# ---------------------------------------------------------------------------
# Strategy 4: Curated orgs via REST (core API, 5,000/hr)
# ---------------------------------------------------------------------------

_CURATED_ORGS = [
    "KiCad", "open-source-hardware", "electroniceel", "kitspace", "adamws",
    "arduino", "raspberrypi", "Adafruit", "SparkFun", "SeeedStudio",
    "foostan", "ai03-2725", "perigoso", "tinkerforge",
    "greatscottgadgets", "mossmann", "secworks",
    "sunzhengwu-kicad", "XBain",
    # More heavy KiCad users
    "qmk", "zeternity", "geekworm-dev", "watterott",
    "dangerousprototypes", "hackaday", "OLIMEX",
    "micropython", "tinyvision-ai-inc", "titansphere",
    "kicad", "kicad-packages3D", "KythonTech",
]


def _curated_org_discovery(token: str, max_repos: int) -> dict[str, RepoRecord]:
    """Scan curated orgs for KiCad repos using core API (5,000/hr)."""
    import requests as req

    seen: dict[str, RepoRecord] = {}
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    _KICAD_KW = {"kicad", "pcb", "schematic", "footprint", "hardware", "eda"}

    for org_name in _CURATED_ORGS:
        if len(seen) >= max_repos:
            break

        for page in range(1, 20):  # up to 20 pages x 100
            if len(seen) >= max_repos:
                break

            url = (
                f"https://api.github.com/orgs/{org_name}/repos"
                f"?sort=stars&direction=desc&per_page=100&page={page}"
            )

            try:
                resp = req.get(url, headers=headers, timeout=30)
                if resp.status_code == 404:
                    # Try as user
                    url = (
                        f"https://api.github.com/users/{org_name}/repos"
                        f"?sort=stars&direction=desc&per_page=100&page={page}"
                    )
                    resp = req.get(url, headers=headers, timeout=30)
                if resp.status_code == 403:
                    logger.warning("Core API rate limited, sleeping 60s")
                    time.sleep(60)
                    continue
                if resp.status_code != 200:
                    break

                repos = resp.json()
                if not repos:
                    break

                for item in repos:
                    name = item.get("full_name", "")
                    desc = (item.get("description") or "").lower()
                    topics = " ".join(item.get("topics") or []).lower()
                    repo_name = item.get("name", "").lower()
                    text = f"{repo_name} {desc} {topics}"

                    if any(kw in text for kw in _KICAD_KW) or item.get("fork"):
                        if name and name not in seen:
                            seen[name] = RepoRecord(
                                full_name=name,
                                html_url=item.get("html_url", ""),
                                stars=item.get("stargazers_count", 0),
                                default_branch=item.get("default_branch", "main"),
                            )

            except Exception as e:
                logger.warning("Curated org '%s' page %d failed: %s", org_name, page, e)
                break

        logger.info("Curated org '%s': %d total repos so far", org_name, len(seen))

    logger.info("Curated orgs: %d unique repos", len(seen))
    return seen


# ---------------------------------------------------------------------------
# Strategy 5: Deep fork scanning (core API, 5,000/hr)
# ---------------------------------------------------------------------------

def _fork_discovery(
    token: str,
    seed_repos: dict[str, RepoRecord],
    max_forks: int = 50000,
    max_per_repo: int = 50,
) -> dict[str, RepoRecord]:
    """Scan fork networks of seed repos for additional KiCad projects."""
    import requests as req

    seen: dict[str, RepoRecord] = dict(seed_repos)  # start with seeds
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Only scan forks of high-star repos (more likely to have active forks)
    high_star = [r for r in seed_repos.values() if r.stars >= 5]
    logger.info("Scanning forks of %d repos with 5+ stars", len(high_star))

    count = 0
    for repo in high_star:
        if count >= max_forks:
            break

        url = f"https://api.github.com/repos/{repo.full_name}/forks?per_page=100"

        try:
            resp = req.get(url, headers=headers, timeout=30)
            if resp.status_code == 403:
                logger.warning("Fork scan rate limited, sleeping 60s")
                time.sleep(60)
                continue
            if resp.status_code != 200:
                continue

            forks = resp.json()
            for fork in forks[:max_per_repo]:
                name = fork.get("full_name", "")
                if name and name not in seen:
                    seen[name] = RepoRecord(
                        full_name=name,
                        html_url=fork.get("html_url", ""),
                        stars=fork.get("stargazers_count", 0),
                        default_branch=fork.get("default_branch", "main"),
                    )
                    count += 1

        except Exception as e:
            continue

        if count % 1000 == 0 and count > 0:
            logger.info("Fork scan: %d new forks so far", count)

    logger.info("Fork scan: +%d new repos (total %d)", count, len(seen))
    return seen


# ---------------------------------------------------------------------------
# Strategy 6: Google scrape via web reader MCP
# ---------------------------------------------------------------------------

def _google_scrape_discovery(max_repos: int) -> dict[str, RepoRecord]:
    """Scrape Google results for GitHub KiCad repos."""
    import re

    seen: dict[str, RepoRecord] = {}

    # These queries target different angles of KiCad projects on GitHub
    google_queries = [
        "github.com kicad pcb projects",
        "github.com kicad hardware design repositories",
        "github kicad_sch kicad_pcb open source hardware",
        "github popular kicad projects pcb layout",
        "github kicad stm32 esp32 arduino board design",
        "github kicad pcb keyboard macro pad",
        "github kicad fpga development board",
        "github kicad power supply board design",
        "github kicad audio amplifier pcb",
        "github kicad motor controller board",
        "github kicad raspberry pi hat pcb",
        "github kicad rp2040 pcb design",
        "github kicad esp32 devkit pcb",
        "github kicad rp2350 board",
        "github open source hardware pcb kicad stars",
    ]

    # Use curl + Google search to extract GitHub URLs
    github_re = re.compile(r'github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)')

    for query in google_queries:
        if len(seen) >= max_repos:
            break

        try:
            # Use DuckDuckGo HTML (more scrape-friendly than Google)
            url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
            result = subprocess.run(
                ["curl", "-sL", "-A", "Mozilla/5.0", url],
                capture_output=True, text=True, timeout=15,
            )

            matches = github_re.findall(result.stdout)
            for match in matches:
                name = match
                # Filter out non-repo paths
                parts = name.split("/")
                if len(parts) == 2 and "." not in parts[1] and parts[1] not in {
                    "features", "pricing", "security", "explore",
                    "marketplace", "settings", "organizations", "new",
                    "notifications", "login", "signup", "about",
                }:
                    if name not in seen:
                        seen[name] = RepoRecord(
                            full_name=name,
                            html_url=f"https://github.com/{name}",
                            stars=0,
                            default_branch="main",
                        )

        except Exception as e:
            logger.warning("Google scrape '%s' failed: %s", query, e)

        logger.info("Google scrape '%s': %d total repos so far", query, len(seen))

    logger.info("Google scrape: %d unique repos", len(seen))
    return seen


# ---------------------------------------------------------------------------
# Strategy 7: GitHub trending / explore (REST API)
# ---------------------------------------------------------------------------

def _trending_discovery(token: str) -> dict[str, RepoRecord]:
    """Fetch trending hardware repos and recently updated KiCad repos."""
    import requests as req

    seen: dict[str, RepoRecord] = {}
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Recently pushed KiCad repos (active projects)
    for sort_type in ["pushed", "stars", "updated"]:
        url = (
            f"https://api.github.com/search/repositories"
            f"?q=kicad+pcb&sort={sort_type}&order=desc&per_page=100"
        )
        try:
            resp = req.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    name = item.get("full_name", "")
                    if name and name not in seen:
                        seen[name] = RepoRecord(
                            full_name=name,
                            html_url=item.get("html_url", ""),
                            stars=item.get("stargazers_count", 0),
                            default_branch=item.get("default_branch", "main"),
                        )
        except Exception:
            pass

    logger.info("Trending: %d unique repos", len(seen))
    return seen


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Discover 100K KiCad repos")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--output", default="discovered_repos.json")
    parser.add_argument("--max-repos", type=int, default=100_000)
    args = parser.parse_args()

    if not args.token:
        logger.error("GITHUB_TOKEN not set")
        return 1

    all_seen: dict[str, RepoRecord] = {}

    # Phase 1: Run fast strategies in parallel (no search API)
    logger.info("Phase 1: Fast strategies (core API + GraphQL + scrape)")

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_curated_org_discovery, args.token, args.max_repos): "curated",
            pool.submit(_google_scrape_discovery, args.max_repos): "google",
            pool.submit(_trending_discovery, args.token): "trending",
            pool.submit(_code_search_discovery, args.token, args.max_repos): "code_search",
        }

        for future in as_completed(futures):
            name = futures[future]
            try:
                results = future.result()
                before = len(all_seen)
                for k, v in results.items():
                    if k not in all_seen:
                        all_seen[k] = v
                added = len(all_seen) - before
                logger.info("Strategy '%s' contributed +%d new repos (total: %d)",
                           name, added, len(all_seen))
            except Exception as e:
                logger.error("Strategy '%s' failed: %s", name, e)

    logger.info("After Phase 1: %d unique repos", len(all_seen))

    # Phase 2: GraphQL + REST search (uses search quota)
    logger.info("Phase 2: GraphQL + REST search (search API quota)")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            pool.submit(_graphql_discovery, args.token, args.max_repos): "graphql",
            pool.submit(_rest_language_discovery, args.token, args.max_repos): "rest_search",
        }

        for future in as_completed(futures):
            name = futures[future]
            try:
                results = future.result()
                before = len(all_seen)
                for k, v in results.items():
                    if k not in all_seen:
                        all_seen[k] = v
                added = len(all_seen) - before
                logger.info("Strategy '%s' contributed +%d new repos (total: %d)",
                           name, added, len(all_seen))
            except Exception as e:
                logger.error("Strategy '%s' failed: %s", name, e)

    logger.info("After Phase 2: %d unique repos", len(all_seen))

    # Phase 3: Fork amplification (core API)
    logger.info("Phase 3: Fork amplification (scanning forks of %d repos)", len(all_seen))
    all_seen = _fork_discovery(args.token, dict(all_seen), max_forks=50_000)

    logger.info("After Phase 3 (forks): %d unique repos", len(all_seen))

    # Sort by stars desc
    sorted_repos = sorted(all_seen.values(), key=lambda r: r.stars, reverse=True)
    truncated = sorted_repos[: args.max_repos]

    # Write output
    output = {
        "total_discovered": len(all_seen),
        "truncated_to": len(truncated),
        "repos": [r.to_dict() for r in truncated],
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    # Print summary
    star_buckets = {"0": 0, "1-10": 0, "11-50": 0, "51-100": 0, "100+": 0}
    for r in truncated:
        s = r.stars
        if s == 0:
            star_buckets["0"] += 1
        elif s <= 10:
            star_buckets["1-10"] += 1
        elif s <= 50:
            star_buckets["11-50"] += 1
        elif s <= 100:
            star_buckets["51-100"] += 1
        else:
            star_buckets["100+"] += 1

    print(f"\n{'='*60}")
    print(f"Discovery complete: {len(truncated)} repos (from {len(all_seen)} total)")
    print(f"  Star distribution:")
    for bucket, count in star_buckets.items():
        print(f"    {bucket:>6} stars: {count}")
    print(f"  Output: {args.output}")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
