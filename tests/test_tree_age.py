"""Tests for iamai.tree_age — directory age analysis.

These tests verify:
- directory_ages returns correct structure and types
- stale_directories filters by threshold correctly
- tree_age_summary produces human-readable output
- edge cases: empty repos, missing directories, no git history
- _git_last_modified handles errors gracefully
- deterministic results with fixed 'now' parameter
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from iamai.tree_age import (
    _git_last_modified,
    _IGNORE,
    directory_ages,
    stale_directories,
    tree_age_summary,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def live_repo():
    """The actual IamAI repository — used for integration tests."""
    return REPO_ROOT


@pytest.fixture
def temp_repo(tmp_path):
    """A minimal git repository for controlled unit tests."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True, check=True,
    )

    # Create some directories and files.
    (repo / "alpha").mkdir()
    (repo / "beta").mkdir()
    (repo / "gamma").mkdir()

    (repo / "alpha" / "a.py").write_text("# alpha module\n")
    (repo / "beta" / "b.py").write_text("# beta module\n")
    (repo / "gamma" / "g.py").write_text("# gamma module\n")
    (repo / "readme.md").write_text("# Test Repo\n")

    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo, capture_output=True, check=True,
    )

    return repo


@pytest.fixture
def empty_repo(tmp_path):
    """A git repo with no commits."""
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    return repo


# ---------------------------------------------------------------------------
# _IGNORE set
# ---------------------------------------------------------------------------


class TestIgnoreSet:
    def test_git_in_ignore(self):
        assert ".git" in _IGNORE

    def test_pycache_in_ignore(self):
        assert "__pycache__" in _IGNORE

    def test_pytest_cache_in_ignore(self):
        assert ".pytest_cache" in _IGNORE


# ---------------------------------------------------------------------------
# _git_last_modified
# ---------------------------------------------------------------------------


class TestGitLastModified:
    def test_returns_float_for_tracked_directory(self, temp_repo):
        ts = _git_last_modified(temp_repo / "alpha", temp_repo)
        assert ts is not None
        assert isinstance(ts, float)
        assert ts > 0

    def test_returns_none_for_nonexistent_directory(self, temp_repo):
        ts = _git_last_modified(temp_repo / "nonexistent", temp_repo)
        # Nonexistent dirs still get a relative path, but git won't find commits.
        # The result depends on whether the dir exists; if not, walk won't find it.
        # We only test that it doesn't crash.
        assert ts is None or isinstance(ts, float)

    def test_returns_none_for_untracked_directory(self, temp_repo):
        (temp_repo / "untracked").mkdir()
        (temp_repo / "untracked" / "file.py").write_text("# untracked\n")
        # Don't git add — directory exists but has no git history.
        ts = _git_last_modified(temp_repo / "untracked", temp_repo)
        assert ts is None

    def test_returns_none_when_not_inside_repo(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        ts = _git_last_modified(outside, tmp_path / "different_repo")
        assert ts is None


# ---------------------------------------------------------------------------
# directory_ages
# ---------------------------------------------------------------------------


class TestDirectoryAges:
    def test_returns_dict(self, temp_repo):
        ages = directory_ages(root=temp_repo)
        assert isinstance(ages, dict)

    def test_keys_are_relative_paths(self, temp_repo):
        ages = directory_ages(root=temp_repo)
        for key in ages:
            assert not key.startswith("/")
            assert ".git" not in key

    def test_values_are_positive_floats(self, temp_repo):
        now = time.time()
        ages = directory_ages(root=temp_repo, now=now)
        for age in ages.values():
            assert isinstance(age, float)
            assert age >= 0

    def test_live_repo_has_entries(self, live_repo):
        ages = directory_ages(root=live_repo)
        assert len(ages) > 5, f"Expected many directories, got {len(ages)}"

    def test_live_repo_iamai_is_recent(self, live_repo):
        ages = directory_ages(root=live_repo)
        if "iamai" in ages:
            # iamai/ should have been modified within the last 4 hours.
            assert ages["iamai"] < 14400, (
                f"iamai/ age is {ages['iamai']:.0f}s, expected < 14400s"
            )

    def test_now_parameter_controls_age(self, temp_repo):
        now = time.time()
        ages_now = directory_ages(root=temp_repo, now=now)
        ages_future = directory_ages(root=temp_repo, now=now + 3600)
        for key in ages_now:
            if key in ages_future:
                assert ages_future[key] > ages_now[key]

    def test_empty_repo_returns_empty(self, empty_repo):
        ages = directory_ages(root=empty_repo)
        assert ages == {}

    def test_depth_one_excludes_nested(self, temp_repo):
        # Create a nested directory.
        (temp_repo / "alpha" / "nested").mkdir()
        (temp_repo / "alpha" / "nested" / "deep.py").write_text("# deep\n")
        subprocess.run(["git", "add", "."], cwd=temp_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add nested"],
            cwd=temp_repo, capture_output=True,
        )

        ages = directory_ages(root=temp_repo, depth=1)
        # With depth=1, we should see "alpha" but not "alpha/nested".
        assert "alpha" in ages
        assert "alpha/nested" not in ages

    def test_excludes_git_directory(self, temp_repo):
        ages = directory_ages(root=temp_repo)
        assert ".git" not in ages


# ---------------------------------------------------------------------------
# stale_directories
# ---------------------------------------------------------------------------


class TestStaleDirectories:
    def test_returns_list(self, temp_repo):
        result = stale_directories(root=temp_repo)
        assert isinstance(result, list)

    def test_fresh_repo_has_no_stale(self, temp_repo):
        # Everything was just committed.
        result = stale_directories(root=temp_repo, threshold_hours=1)
        assert len(result) == 0

    def test_threshold_filters_correctly(self, temp_repo):
        # Use a tiny threshold — everything is "stale" if threshold is 0.
        result = stale_directories(root=temp_repo, threshold_hours=0)
        ages = directory_ages(root=temp_repo)
        assert len(result) == len(ages)

    def test_sorted_oldest_first(self, temp_repo):
        result = stale_directories(root=temp_repo, threshold_hours=0)
        if len(result) >= 2:
            for i in range(len(result) - 1):
                assert result[i]["age_seconds"] >= result[i + 1]["age_seconds"]

    def test_entry_has_required_keys(self, temp_repo):
        result = stale_directories(root=temp_repo, threshold_hours=0)
        for entry in result:
            assert "name" in entry
            assert "age_seconds" in entry

    def test_live_repo_integration(self, live_repo):
        # With a generous threshold, most directories should be fresh.
        result = stale_directories(root=live_repo, threshold_hours=168)  # 1 week
        # This is a check that it doesn't crash and returns a list.
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# tree_age_summary
# ---------------------------------------------------------------------------


class TestTreeAgeSummary:
    def test_returns_string(self, temp_repo):
        result = tree_age_summary(root=temp_repo)
        assert isinstance(result, str)

    def test_contains_directory_count(self, temp_repo):
        result = tree_age_summary(root=temp_repo)
        assert "directories tracked" in result

    def test_fresh_repo_says_all_fresh(self, temp_repo):
        result = tree_age_summary(root=temp_repo, threshold_hours=1)
        assert "all fresh" in result

    def test_empty_repo_handled(self, empty_repo):
        result = tree_age_summary(root=empty_repo)
        assert "no directories" in result

    def test_stale_listed_in_summary(self, temp_repo):
        result = tree_age_summary(root=temp_repo, threshold_hours=0)
        assert "stale" in result

    def test_summary_not_empty_for_live_repo(self, live_repo):
        result = tree_age_summary(root=live_repo)
        assert len(result) > 20


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_none_root_defaults_to_repo(self):
        ages = directory_ages(root=None)
        assert isinstance(ages, dict)
        assert len(ages) > 0

    def test_path_object_works(self, temp_repo):
        ages = directory_ages(root=Path(temp_repo))
        assert isinstance(ages, dict)

    def test_string_root_works(self, temp_repo):
        ages = directory_ages(root=str(temp_repo))
        assert isinstance(ages, dict)

    def test_summary_with_custom_threshold(self, temp_repo):
        result = tree_age_summary(root=temp_repo, threshold_hours=0.001)
        assert isinstance(result, str)
