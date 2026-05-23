"""Unit tests for GitHub crawler: discovery, pairing, fetching, and rate limiting.

All GitHub API interactions are mocked -- no real API calls in tests.
"""

import base64
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.crawler.github_discovery import (
    GithubDiscovery,
    KicadFilePair,
    RepoInfo,
)
from kicad_agent.crawler.file_fetcher import FetchedFile, FileFetcher
from kicad_agent.crawler.rate_limiter import RateLimiter


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_mock_repo(
    full_name="user/project",
    stars=42,
    description="A test repo",
    default_branch="main",
):
    """Create a mock PyGithub Repository."""
    repo = MagicMock()
    repo.full_name = full_name
    repo.html_url = f"https://github.com/{full_name}"
    repo.stargazers_count = stars
    repo.description = description
    repo.default_branch = default_branch
    return repo


def _make_tree_element(path, element_type="blob"):
    """Create a mock GitTreeElement."""
    element = MagicMock()
    element.path = path
    element.type = element_type
    return element


def _make_rate_resource(remaining=1000, reset_dt=None):
    """Create a mock rate limit resource."""
    resource = MagicMock()
    resource.remaining = remaining
    resource.reset = reset_dt or datetime.now(timezone.utc) + timedelta(hours=1)
    return resource


def _make_rate_limit(core_remaining=1000, search_remaining=1000):
    """Create a mock rate limit object.

    Default remaining counts are well above the 50-request threshold
    so tests do not trigger real time.sleep calls.
    """
    rate_limit = MagicMock()
    rate_limit.core = _make_rate_resource(remaining=core_remaining)
    rate_limit.search = _make_rate_resource(remaining=search_remaining)
    return rate_limit


class _FakePaginatedList:
    """Fake PyGithub PaginatedList that supports iteration.

    PyGithub search_repositories returns a PaginatedList. MagicMock
    __iter__ is unreliable, so we use a concrete iterable wrapper.
    """

    def __init__(self, items):
        self._items = list(items)

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)


# ---------------------------------------------------------------------------
# TestRateLimiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    """Tests for RateLimiter API throttling logic."""

    def test_no_sleep_when_remaining_above_threshold(self):
        """No sleep when remaining requests are well above threshold."""
        mock_client = MagicMock()
        mock_client.get_rate_limit.return_value = _make_rate_limit(core_remaining=1000)
        limiter = RateLimiter(mock_client)

        with patch("kicad_agent.crawler.rate_limiter.time.sleep") as mock_sleep:
            limiter.wait_if_needed("core")
            mock_sleep.assert_not_called()

    def test_sleeps_when_remaining_below_threshold(self):
        """Sleeps when remaining requests drop below threshold."""
        reset_time = datetime.now(timezone.utc) + timedelta(seconds=120)
        mock_client = MagicMock()
        mock_client.get_rate_limit.return_value = _make_rate_limit(
            core_remaining=10,
        )
        mock_client.get_rate_limit.return_value.core.reset = reset_time

        limiter = RateLimiter(mock_client)

        with patch("kicad_agent.crawler.rate_limiter.time.sleep") as mock_sleep:
            limiter.wait_if_needed("core")
            mock_sleep.assert_called_once()
            sleep_arg = mock_sleep.call_args[0][0]
            assert 119 < sleep_arg < 122

    def test_no_sleep_when_reset_in_past(self):
        """No sleep when remaining is low but reset time has already passed."""
        past_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        mock_client = MagicMock()
        mock_client.get_rate_limit.return_value = _make_rate_limit(
            core_remaining=10,
        )
        mock_client.get_rate_limit.return_value.core.reset = past_time

        limiter = RateLimiter(mock_client)

        with patch("kicad_agent.crawler.rate_limiter.time.sleep") as mock_sleep:
            limiter.wait_if_needed("core")
            mock_sleep.assert_not_called()

    def test_remaining_property(self):
        """remaining property returns core remaining count."""
        mock_client = MagicMock()
        mock_client.get_rate_limit.return_value = _make_rate_limit(core_remaining=500)
        limiter = RateLimiter(mock_client)
        assert limiter.remaining == 500

    def test_search_limit_type_uses_search_resource(self):
        """Search limit type checks search resource, not core."""
        mock_client = MagicMock()
        mock_client.get_rate_limit.return_value = _make_rate_limit(
            core_remaining=10, search_remaining=1000
        )
        limiter = RateLimiter(mock_client)

        with patch("kicad_agent.crawler.rate_limiter.time.sleep") as mock_sleep:
            limiter.wait_if_needed("search")
            mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# TestGithubDiscovery
# ---------------------------------------------------------------------------


class TestGithubDiscovery:
    """Tests for GithubDiscovery repo search and file pair extraction."""

    @patch("kicad_agent.crawler.github_discovery.Github")
    @patch("kicad_agent.crawler.github_discovery.Auth")
    def test_discover_repos_returns_repo_info_list(self, mock_auth, mock_github_cls):
        """discover_repos returns RepoInfo list with correct fields."""
        mock_client = MagicMock()
        mock_github_cls.return_value = mock_client
        mock_client.get_rate_limit.return_value = _make_rate_limit()

        repo1 = _make_mock_repo("user/proj1", stars=100)
        repo2 = _make_mock_repo("user/proj2", stars=50)
        mock_client.search_repositories.return_value = _FakePaginatedList([repo1, repo2])

        discovery = GithubDiscovery(token="fake-token")
        repos = discovery.discover_repos(queries=["test query"])

        assert len(repos) == 2
        assert isinstance(repos[0], RepoInfo)
        assert repos[0].full_name == "user/proj1"
        assert repos[0].stars == 100
        assert repos[0].html_url == "https://github.com/user/proj1"
        assert repos[0].description == "A test repo"
        assert repos[0].default_branch == "main"

    @patch("kicad_agent.crawler.github_discovery.Github")
    @patch("kicad_agent.crawler.github_discovery.Auth")
    def test_discover_repos_deduplicates_by_full_name(self, mock_auth, mock_github_cls):
        """Two queries returning the same repo only produce one RepoInfo."""
        mock_client = MagicMock()
        mock_github_cls.return_value = mock_client
        mock_client.get_rate_limit.return_value = _make_rate_limit()

        repo = _make_mock_repo("user/shared", stars=10)
        mock_client.search_repositories.return_value = _FakePaginatedList([repo])

        discovery = GithubDiscovery(token="fake-token")
        repos = discovery.discover_repos(queries=["query1", "query2"])

        assert len(repos) == 1
        assert repos[0].full_name == "user/shared"

    @patch("kicad_agent.crawler.github_discovery.Github")
    @patch("kicad_agent.crawler.github_discovery.Auth")
    def test_discover_repos_respects_max_repos(self, mock_auth, mock_github_cls):
        """discover_repos truncates results to max_repos."""
        mock_client = MagicMock()
        mock_github_cls.return_value = mock_client
        mock_client.get_rate_limit.return_value = _make_rate_limit()

        repos_mock = [_make_mock_repo(f"user/r{i}", stars=i) for i in range(10)]
        mock_client.search_repositories.return_value = _FakePaginatedList(repos_mock)

        discovery = GithubDiscovery(token="fake-token")
        repos = discovery.discover_repos(max_repos=3, queries=["test"])

        assert len(repos) == 3

    @patch("kicad_agent.crawler.github_discovery.Github")
    @patch("kicad_agent.crawler.github_discovery.Auth")
    def test_find_kicad_pairs_matches_by_base_name(self, mock_auth, mock_github_cls):
        """find_kicad_pairs matches .kicad_sch and .kicad_pcb by shared base name."""
        mock_client = MagicMock()
        mock_github_cls.return_value = mock_client
        mock_client.get_rate_limit.return_value = _make_rate_limit()

        elements = [
            _make_tree_element("board.kicad_sch"),
            _make_tree_element("board.kicad_pcb"),
            _make_tree_element("other.kicad_pcb"),
        ]
        tree = MagicMock()
        tree.tree = elements

        mock_repo = MagicMock()
        mock_repo.get_git_tree.return_value = tree
        mock_client.get_repo.return_value = mock_repo

        discovery = GithubDiscovery(token="fake-token")
        repo_info = RepoInfo(
            full_name="user/proj",
            html_url="https://github.com/user/proj",
            stars=10,
            description="test",
            default_branch="main",
        )
        pairs = discovery.find_kicad_pairs(repo_info)

        assert len(pairs) == 1
        assert pairs[0].base_name == "board"
        assert pairs[0].schematic_path == "board.kicad_sch"
        assert pairs[0].pcb_path == "board.kicad_pcb"

    @patch("kicad_agent.crawler.github_discovery.Github")
    @patch("kicad_agent.crawler.github_discovery.Auth")
    def test_find_kicad_pairs_returns_empty_on_error(self, mock_auth, mock_github_cls):
        """find_kicad_pairs returns empty list when API call fails."""
        from github import GithubException

        mock_client = MagicMock()
        mock_github_cls.return_value = mock_client
        mock_client.get_rate_limit.return_value = _make_rate_limit()
        mock_client.get_repo.side_effect = GithubException(404, "Not Found", {})

        discovery = GithubDiscovery(token="fake-token")
        repo_info = RepoInfo(
            full_name="user/gone",
            html_url="",
            stars=0,
            description="",
            default_branch="main",
        )
        pairs = discovery.find_kicad_pairs(repo_info)

        assert pairs == []

    @patch("kicad_agent.crawler.github_discovery.Github")
    @patch("kicad_agent.crawler.github_discovery.Auth")
    def test_find_kicad_pairs_skips_orphaned_files(self, mock_auth, mock_github_cls):
        """find_kicad_pairs returns empty when no matching pairs exist."""
        mock_client = MagicMock()
        mock_github_cls.return_value = mock_client
        mock_client.get_rate_limit.return_value = _make_rate_limit()

        elements = [
            _make_tree_element("board.kicad_sch"),
            # No matching board.kicad_pcb
        ]
        tree = MagicMock()
        tree.tree = elements

        mock_repo = MagicMock()
        mock_repo.get_git_tree.return_value = tree
        mock_client.get_repo.return_value = mock_repo

        discovery = GithubDiscovery(token="fake-token")
        repo_info = RepoInfo(
            full_name="user/proj",
            html_url="",
            stars=0,
            description="",
            default_branch="main",
        )
        pairs = discovery.find_kicad_pairs(repo_info)

        assert pairs == []

    @patch("kicad_agent.crawler.github_discovery.Github")
    @patch("kicad_agent.crawler.github_discovery.Auth")
    def test_discover_pairs_filters_repos_without_pairs(self, mock_auth, mock_github_cls):
        """discover_pairs only returns repos that have at least one file pair."""
        mock_client = MagicMock()
        mock_github_cls.return_value = mock_client
        mock_client.get_rate_limit.return_value = _make_rate_limit()

        # 3 repos from search
        repos_mock = [
            _make_mock_repo("user/r1", stars=30),
            _make_mock_repo("user/r2", stars=20),
            _make_mock_repo("user/r3", stars=10),
        ]
        mock_client.search_repositories.return_value = _FakePaginatedList(repos_mock)

        # r1 has pairs, r2 has no pairs, r3 has pairs
        pair_elements = [
            _make_tree_element("main.kicad_sch"),
            _make_tree_element("main.kicad_pcb"),
        ]
        tree_with_pairs = MagicMock()
        tree_with_pairs.tree = pair_elements

        empty_tree = MagicMock()
        empty_tree.tree = [_make_tree_element("orphan.kicad_sch")]

        mock_repo_obj = MagicMock()
        mock_client.get_repo.return_value = mock_repo_obj
        # Called 3 times: r1 gets pairs, r2 empty, r3 gets pairs
        mock_repo_obj.get_git_tree.side_effect = [
            tree_with_pairs,
            empty_tree,
            tree_with_pairs,
        ]

        discovery = GithubDiscovery(token="fake-token")
        results = discovery.discover_pairs(max_repos=10)

        assert len(results) == 2
        assert results[0][0].full_name == "user/r1"
        assert results[1][0].full_name == "user/r3"

    @patch("kicad_agent.crawler.github_discovery.Github")
    @patch("kicad_agent.crawler.github_discovery.Auth")
    def test_find_kicad_pairs_handles_nested_paths(self, mock_auth, mock_github_cls):
        """find_kicad_pairs correctly extracts base names from nested paths."""
        mock_client = MagicMock()
        mock_github_cls.return_value = mock_client
        mock_client.get_rate_limit.return_value = _make_rate_limit()

        elements = [
            _make_tree_element("hardware/board.kicad_sch"),
            _make_tree_element("hardware/board.kicad_pcb"),
        ]
        tree = MagicMock()
        tree.tree = elements

        mock_repo = MagicMock()
        mock_repo.get_git_tree.return_value = tree
        mock_client.get_repo.return_value = mock_repo

        discovery = GithubDiscovery(token="fake-token")
        repo_info = RepoInfo(
            full_name="user/nested",
            html_url="",
            stars=0,
            description="",
            default_branch="main",
        )
        pairs = discovery.find_kicad_pairs(repo_info)

        assert len(pairs) == 1
        assert pairs[0].base_name == "board"
        assert pairs[0].schematic_path == "hardware/board.kicad_sch"
        assert pairs[0].pcb_path == "hardware/board.kicad_pcb"


# ---------------------------------------------------------------------------
# TestFileFetcher
# ---------------------------------------------------------------------------


class TestFileFetcher:
    """Tests for FileFetcher sparse file retrieval."""

    def test_fetch_file_writes_to_staging_dir(self, tmp_path):
        """fetch_file downloads and writes file to staging directory."""
        content = b"(kicad_pcb (version 20221018) ...)"
        encoded = base64.b64encode(content).decode()

        mock_contents = MagicMock()
        mock_contents.content = encoded

        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = mock_contents

        mock_client = MagicMock()
        mock_client.get_repo.return_value = mock_repo

        fetcher = FileFetcher(mock_client, tmp_path)
        result = fetcher.fetch_file("user/proj", "board.kicad_pcb")

        assert result is not None
        assert isinstance(result, FetchedFile)
        assert result.repo_name == "user/proj"
        assert result.path == "board.kicad_pcb"
        assert result.local_path.exists()
        assert result.local_path.read_bytes() == content
        assert len(result.content_hash) == 64  # SHA256 hex digest

    def test_fetch_file_returns_none_on_error(self, tmp_path):
        """fetch_file returns None when API call fails."""
        mock_client = MagicMock()
        mock_client.get_repo.side_effect = Exception("API error")

        fetcher = FileFetcher(mock_client, tmp_path)
        result = fetcher.fetch_file("user/gone", "board.kicad_pcb")

        assert result is None

    def test_fetch_file_rejects_non_kicad_extensions(self, tmp_path):
        """fetch_file returns None for non-.kicad_sch/.kicad_pcb files."""
        content = b"readme content"
        encoded = base64.b64encode(content).decode()

        mock_contents = MagicMock()
        mock_contents.content = encoded

        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = mock_contents

        mock_client = MagicMock()
        mock_client.get_repo.return_value = mock_repo

        fetcher = FileFetcher(mock_client, tmp_path)
        result = fetcher.fetch_file("user/proj", "README.txt")

        assert result is None

    def test_fetch_file_returns_none_for_directory(self, tmp_path):
        """fetch_file returns None when get_contents returns a directory."""
        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = [MagicMock()]  # list = directory

        mock_client = MagicMock()
        mock_client.get_repo.return_value = mock_repo

        fetcher = FileFetcher(mock_client, tmp_path)
        result = fetcher.fetch_file("user/proj", "hardware/")

        assert result is None

    def test_fetch_pair_returns_both_files(self, tmp_path):
        """fetch_pair returns both schematic and PCB files."""
        sch_content = b"(kicad_sch (version 20221018) ...)"
        pcb_content = b"(kicad_pcb (version 20221018) ...)"

        def mock_get_contents(path):
            mock = MagicMock()
            if path.endswith(".kicad_sch"):
                mock.content = base64.b64encode(sch_content).decode()
            else:
                mock.content = base64.b64encode(pcb_content).decode()
            return mock

        mock_repo = MagicMock()
        mock_repo.get_contents.side_effect = mock_get_contents

        mock_client = MagicMock()
        mock_client.get_repo.return_value = mock_repo

        fetcher = FileFetcher(mock_client, tmp_path)
        pair = KicadFilePair(
            schematic_path="board.kicad_sch",
            pcb_path="board.kicad_pcb",
            base_name="board",
        )
        sch_file, pcb_file = fetcher.fetch_pair("user/proj", pair)

        assert sch_file is not None
        assert pcb_file is not None
        assert sch_file.local_path.read_bytes() == sch_content
        assert pcb_file.local_path.read_bytes() == pcb_content

    def test_fetch_pair_returns_none_for_failed_side(self, tmp_path):
        """fetch_pair returns None for the failed side."""
        pcb_content = b"(kicad_pcb (version 20221018) ...)"

        def mock_get_contents(path):
            if path.endswith(".kicad_sch"):
                raise Exception("Not found")
            mock = MagicMock()
            mock.content = base64.b64encode(pcb_content).decode()
            return mock

        mock_repo = MagicMock()
        mock_repo.get_contents.side_effect = mock_get_contents

        mock_client = MagicMock()
        mock_client.get_repo.return_value = mock_repo

        fetcher = FileFetcher(mock_client, tmp_path)
        pair = KicadFilePair(
            schematic_path="board.kicad_sch",
            pcb_path="board.kicad_pcb",
            base_name="board",
        )
        sch_file, pcb_file = fetcher.fetch_pair("user/proj", pair)

        assert sch_file is None
        assert pcb_file is not None

    def test_fetch_file_creates_repo_subdirectory(self, tmp_path):
        """fetch_file creates a repo-specific subdirectory for isolation."""
        content = b"(kicad_pcb ...)"
        encoded = base64.b64encode(content).decode()

        mock_contents = MagicMock()
        mock_contents.content = encoded

        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = mock_contents

        mock_client = MagicMock()
        mock_client.get_repo.return_value = mock_repo

        fetcher = FileFetcher(mock_client, tmp_path)
        result = fetcher.fetch_file("user/proj", "board.kicad_pcb")

        assert result is not None
        # File should be in user_proj subdirectory
        assert result.local_path.parent.name == "user_proj"
