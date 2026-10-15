"""Tests for iamai.repo_churn — file churn analysis."""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import pytest

from iamai.repo_churn import (
    _file_mod_counts,
    _recent_touched,
    _run,
    _tracked_files,
    churn_report,
    repo_churn,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _init_repo(tmp: Path) -> Path:
    """Create a tiny git repo with a few commits for testing."""
    repo = tmp / "churn_test"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)

    # commit 1: create a.txt, b.txt
    (repo / "a.txt").write_text("hello")
    (repo / "b.txt").write_text("world")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

    # commit 2: modify a.txt
    (repo / "a.txt").write_text("hello again")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "update a"], cwd=repo, capture_output=True)

    # commit 3: modify a.txt again, add c.txt
    (repo / "a.txt").write_text("hello third time")
    (repo / "c.txt").write_text("new file")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "update a + add c"], cwd=repo, capture_output=True)

    return repo


# ---------------------------------------------------------------------------
# _run
# ---------------------------------------------------------------------------

class TestRun:
    def test_successful_command(self, tmp_path):
        result = _run(["echo", "hello"], tmp_path)
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_failing_command(self, tmp_path):
        result = _run(["false"], tmp_path)
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# _tracked_files
# ---------------------------------------------------------------------------

class TestTrackedFiles:
    def test_normal_repo(self, tmp_path):
        repo = _init_repo(tmp_path)
        tracked = _tracked_files(repo)
        assert tracked == {"a.txt", "b.txt", "c.txt"}

    def test_empty_repo(self, tmp_path):
        repo = tmp_path / "empty"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        tracked = _tracked_files(repo)
        assert tracked == set()

    def test_non_git_directory(self, tmp_path):
        tracked = _tracked_files(tmp_path)
        assert tracked == set()


# ---------------------------------------------------------------------------
# _file_mod_counts
# ---------------------------------------------------------------------------

class TestFileModCounts:
    def test_counts(self, tmp_path):
        repo = _init_repo(tmp_path)
        counts = _file_mod_counts(repo)
        assert counts["a.txt"] == 3  # in all 3 commits
        assert counts["b.txt"] == 1  # only in commit 1
        assert counts["c.txt"] == 1  # only in commit 3

    def test_max_commits_limits_walk(self, tmp_path):
        repo = _init_repo(tmp_path)
        # only look at last 1 commit: only a.txt and c.txt should appear
        counts = _file_mod_counts(repo, max_commits=1)
        assert "a.txt" in counts
        assert "c.txt" in counts
        # b.txt was only in the first commit, which is beyond max_commits=1
        assert "b.txt" not in counts

    def test_empty_repo(self, tmp_path):
        repo = tmp_path / "empty"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        counts = _file_mod_counts(repo)
        assert counts == Counter()

    def test_non_git(self, tmp_path):
        counts = _file_mod_counts(tmp_path)
        assert counts == Counter()


# ---------------------------------------------------------------------------
# _recent_touched
# ---------------------------------------------------------------------------

class TestRecentTouched:
    def test_recent(self, tmp_path):
        repo = _init_repo(tmp_path)
        touched = _recent_touched(repo, n_commits=1)
        assert "a.txt" in touched
        assert "c.txt" in touched
        # b.txt was only in commit 1, not in the last 1 commit
        assert "b.txt" not in touched

    def test_all_commits(self, tmp_path):
        repo = _init_repo(tmp_path)
        touched = _recent_touched(repo, n_commits=100)
        assert touched == {"a.txt", "b.txt", "c.txt"}

    def test_empty_repo(self, tmp_path):
        repo = tmp_path / "empty"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        touched = _recent_touched(repo)
        assert touched == set()


# ---------------------------------------------------------------------------
# repo_churn
# ---------------------------------------------------------------------------

class TestRepoChurn:
    def test_basic(self, tmp_path):
        repo = _init_repo(tmp_path)
        info = repo_churn(repo)
        assert info["tracked"] == 3
        assert info["hot"][0] == ("a.txt", 3)
        assert info["cold"] == []  # all files touched within 200 commits
        assert info["churn_ratio"] > 0
        assert info["recent_touched_count"] > 0

    def test_cold_files(self, tmp_path):
        repo = _init_repo(tmp_path)
        # add a file, commit, then never touch it again in many commits
        (repo / "d.txt").write_text("cold")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add d"], cwd=repo, capture_output=True)

        # add 5 more commits that only touch a.txt
        for i in range(5):
            (repo / "a.txt").write_text(f"iteration {i}")
            subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
            subprocess.run(["git", "commit", "-m", f"bump {i}"], cwd=repo, capture_output=True)

        # with max_commits=5, d.txt shouldn't appear in mod_counts
        info = repo_churn(repo, max_commits=5, recent_commits=5)
        assert "d.txt" in info["cold"]

    def test_churn_ratio(self, tmp_path):
        repo = _init_repo(tmp_path)
        info = repo_churn(repo, recent_commits=1)
        # last commit touched a.txt and c.txt = 2 out of 3 tracked
        assert abs(info["churn_ratio"] - 2 / 3) < 0.01

    def test_empty_repo(self, tmp_path):
        repo = tmp_path / "empty"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        info = repo_churn(repo)
        assert info["tracked"] == 0
        assert info["hot"] == []
        assert info["cold"] == []
        assert info["churn_ratio"] == 0.0

    def test_hot_n_limits_results(self, tmp_path):
        repo = _init_repo(tmp_path)
        info = repo_churn(repo, hot_n=1)
        assert len(info["hot"]) == 1

    def test_mod_counts_is_counter(self, tmp_path):
        repo = _init_repo(tmp_path)
        info = repo_churn(repo)
        assert isinstance(info["mod_counts"], Counter)


# ---------------------------------------------------------------------------
# churn_report
# ---------------------------------------------------------------------------

class TestChurnReport:
    def test_normal(self, tmp_path):
        repo = _init_repo(tmp_path)
        report = churn_report(repo)
        assert "churn" in report
        assert "touched" in report
        assert "hot:" in report
        assert "a.txt" in report

    def test_empty_repo(self, tmp_path):
        repo = tmp_path / "empty"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        report = churn_report(repo)
        assert "empty repo" in report

    def test_custom_recent_commits(self, tmp_path):
        repo = _init_repo(tmp_path)
        report = churn_report(repo, recent_commits=1)
        assert "last 1 commits" in report
