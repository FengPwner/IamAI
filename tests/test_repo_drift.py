"""Tests for iamai.repo_drift library."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iamai.repo_drift import (
    _count_commits,
    _current_branch,
    _get_sha,
    _tracking_branch,
    drift_report,
    needs_pull,
    safe_to_push,
    summarize,
)


# ---------------------------------------------------------------------------
# _run_git / helpers
# ---------------------------------------------------------------------------


class TestCurrentBranch:
    def test_returns_branch_name(self, tmp_path):
        with patch("iamai.repo_drift._run_git", return_value=(0, "main")):
            assert _current_branch(tmp_path) == "main"

    def test_returns_none_on_detached(self, tmp_path):
        with patch("iamai.repo_drift._run_git", return_value=(0, "HEAD")):
            assert _current_branch(tmp_path) is None

    def test_returns_none_on_error(self, tmp_path):
        with patch("iamai.repo_drift._run_git", return_value=(128, "")):
            assert _current_branch(tmp_path) is None


class TestTrackingBranch:
    def test_returns_remote_ref(self, tmp_path):
        def side_effect(*args, cwd=None):
            if any(".remote" in a for a in args):
                return (0, "origin")
            if any(".merge" in a for a in args):
                return (0, "refs/heads/main")
            return (1, "")

        with patch("iamai.repo_drift._run_git", side_effect=side_effect):
            assert _tracking_branch("main", tmp_path) == "origin/main"

    def test_returns_none_when_no_remote(self, tmp_path):
        with patch("iamai.repo_drift._run_git", return_value=(1, "")):
            assert _tracking_branch("main", tmp_path) is None

    def test_strips_refs_heads_prefix(self, tmp_path):
        def side_effect(*args, cwd=None):
            if any(".remote" in a for a in args):
                return (0, "origin")
            if any(".merge" in a for a in args):
                return (0, "refs/heads/feature/test")
            return (1, "")

        with patch("iamai.repo_drift._run_git", side_effect=side_effect):
            assert _tracking_branch("feature/test", tmp_path) == "origin/feature/test"


class TestCountCommits:
    def test_returns_count(self, tmp_path):
        with patch("iamai.repo_drift._run_git", return_value=(0, "5")):
            assert _count_commits("origin/main", "HEAD", tmp_path) == 5

    def test_returns_zero(self, tmp_path):
        with patch("iamai.repo_drift._run_git", return_value=(0, "0")):
            assert _count_commits("origin/main", "HEAD", tmp_path) == 0

    def test_returns_none_on_error(self, tmp_path):
        with patch("iamai.repo_drift._run_git", return_value=(128, "fatal")):
            assert _count_commits("origin/main", "HEAD", tmp_path) is None

    def test_returns_none_on_garbage(self, tmp_path):
        with patch("iamai.repo_drift._run_git", return_value=(0, "not-a-number")):
            assert _count_commits("origin/main", "HEAD", tmp_path) is None


class TestGetSha:
    def test_returns_short_sha(self, tmp_path):
        with patch(
            "iamai.repo_drift._run_git",
            return_value=(0, "abc123def456789"),
        ):
            assert _get_sha("HEAD", tmp_path) == "abc123def456"

    def test_returns_none_on_error(self, tmp_path):
        with patch("iamai.repo_drift._run_git", return_value=(128, "")):
            assert _get_sha("nonexistent", tmp_path) is None


# ---------------------------------------------------------------------------
# drift_report
# ---------------------------------------------------------------------------


class TestDriftReport:
    def test_synced(self, tmp_path):
        def side_effect(*args, cwd=None):
            cmd = args
            if cmd == ("rev-parse", "--abbrev-ref", "HEAD"):
                return (0, "main")
            if cmd == ("config", "branch.main.remote"):
                return (0, "origin")
            if cmd == ("config", "branch.main.merge"):
                return (0, "refs/heads/main")
            if cmd == ("rev-parse", "--verify", "HEAD"):
                return (0, "abc1234567890")
            if cmd == ("rev-parse", "--verify", "origin/main"):
                return (0, "abc1234567890")
            if "rev-list" in cmd and "HEAD" in cmd[-1]:
                return (0, "0")  # ahead
            if "rev-list" in cmd and "origin/main" in cmd[-1]:
                return (0, "0")  # behind
            return (1, "")

        with patch("iamai.repo_drift._run_git", side_effect=side_effect):
            report = drift_report(cwd=tmp_path)
            assert report["status"] == "synced"
            assert report["ahead"] == 0
            assert report["behind"] == 0

    def test_ahead(self, tmp_path):
        def side_effect(*args, cwd=None):
            cmd = args
            if cmd == ("rev-parse", "--abbrev-ref", "HEAD"):
                return (0, "main")
            if cmd == ("config", "branch.main.remote"):
                return (0, "origin")
            if cmd == ("config", "branch.main.merge"):
                return (0, "refs/heads/main")
            if cmd == ("rev-parse", "--verify", "HEAD"):
                return (0, "def456789012")
            if cmd == ("rev-parse", "--verify", "origin/main"):
                return (0, "abc123456789")
            if "rev-list" in cmd and any("..HEAD" in a for a in cmd):
                return (0, "3")  # ahead
            if "rev-list" in cmd and any("..origin/main" in a for a in cmd):
                return (0, "0")  # behind
            return (1, "")

        with patch("iamai.repo_drift._run_git", side_effect=side_effect):
            report = drift_report(cwd=tmp_path)
            assert report["status"] == "ahead"
            assert report["ahead"] == 3
            assert report["behind"] == 0

    def test_behind(self, tmp_path):
        def side_effect(*args, cwd=None):
            cmd = args
            if cmd == ("rev-parse", "--abbrev-ref", "HEAD"):
                return (0, "main")
            if cmd == ("config", "branch.main.remote"):
                return (0, "origin")
            if cmd == ("config", "branch.main.merge"):
                return (0, "refs/heads/main")
            if cmd == ("rev-parse", "--verify", "HEAD"):
                return (0, "abc123456789")
            if cmd == ("rev-parse", "--verify", "origin/main"):
                return (0, "def456789012")
            if "rev-list" in cmd and any("..HEAD" in a for a in cmd):
                return (0, "0")  # ahead
            if "rev-list" in cmd and any("..origin/main" in a for a in cmd):
                return (0, "2")  # behind
            return (1, "")

        with patch("iamai.repo_drift._run_git", side_effect=side_effect):
            report = drift_report(cwd=tmp_path)
            assert report["status"] == "behind"
            assert report["ahead"] == 0
            assert report["behind"] == 2

    def test_diverged(self, tmp_path):
        def side_effect(*args, cwd=None):
            cmd = args
            if cmd == ("rev-parse", "--abbrev-ref", "HEAD"):
                return (0, "main")
            if cmd == ("config", "branch.main.remote"):
                return (0, "origin")
            if cmd == ("config", "branch.main.merge"):
                return (0, "refs/heads/main")
            if cmd == ("rev-parse", "--verify", "HEAD"):
                return (0, "aaa111222333")
            if cmd == ("rev-parse", "--verify", "origin/main"):
                return (0, "bbb444555666")
            if "rev-list" in cmd and any("..HEAD" in a for a in cmd):
                return (0, "2")  # ahead
            if "rev-list" in cmd and any("..origin/main" in a for a in cmd):
                return (0, "1")  # behind
            return (1, "")

        with patch("iamai.repo_drift._run_git", side_effect=side_effect):
            report = drift_report(cwd=tmp_path)
            assert report["status"] == "diverged"
            assert report["ahead"] == 2
            assert report["behind"] == 1

    def test_detached_head(self, tmp_path):
        with patch(
            "iamai.repo_drift._run_git", return_value=(0, "HEAD")
        ):
            report = drift_report(cwd=tmp_path)
            assert report["status"] == "detached"
            assert report["branch"] is None

    def test_no_tracking_branch(self, tmp_path):
        def side_effect(*args, cwd=None):
            if args == ("rev-parse", "--abbrev-ref", "HEAD"):
                return (0, "feature")
            return (1, "")

        with patch("iamai.repo_drift._run_git", side_effect=side_effect):
            report = drift_report(cwd=tmp_path)
            assert report["status"] == "no_remote"


# ---------------------------------------------------------------------------
# summarize / needs_pull / safe_to_push
# ---------------------------------------------------------------------------


class TestSummarize:
    def test_synced(self):
        r = {"branch": "main", "remote_ref": "origin/main", "status": "synced",
             "ahead": 0, "behind": 0, "local_sha": "abc123", "remote_sha": "abc123"}
        assert "synced" in summarize(r)

    def test_ahead(self):
        r = {"branch": "main", "remote_ref": "origin/main", "status": "ahead",
             "ahead": 3, "behind": 0, "local_sha": "def456", "remote_sha": "abc123"}
        s = summarize(r)
        assert "3" in s
        assert "ahead" in s

    def test_behind(self):
        r = {"branch": "main", "remote_ref": "origin/main", "status": "behind",
             "ahead": 0, "behind": 2, "local_sha": "abc123", "remote_sha": "def456"}
        s = summarize(r)
        assert "2" in s
        assert "behind" in s

    def test_diverged(self):
        r = {"branch": "main", "remote_ref": "origin/main", "status": "diverged",
             "ahead": 2, "behind": 1, "local_sha": "aaa111", "remote_sha": "bbb222"}
        s = summarize(r)
        assert "diverged" in s
        assert "2" in s
        assert "1" in s

    def test_detached(self):
        r = {"branch": None, "status": "detached", "remote_ref": None,
             "ahead": None, "behind": None, "local_sha": None, "remote_sha": None}
        assert "detached" in summarize(r)

    def test_no_remote(self):
        r = {"branch": "feature", "status": "no_remote", "remote_ref": None,
             "ahead": None, "behind": None, "local_sha": "abc123", "remote_sha": None}
        assert "no remote" in summarize(r)


class TestNeedsPull:
    def test_behind_needs_pull(self):
        assert needs_pull({"status": "behind"}) is True

    def test_diverged_needs_pull(self):
        assert needs_pull({"status": "diverged"}) is True

    def test_synced_no_pull(self):
        assert needs_pull({"status": "synced"}) is False

    def test_ahead_no_pull(self):
        assert needs_pull({"status": "ahead"}) is False


class TestSafeToPush:
    def test_synced_safe(self):
        assert safe_to_push({"status": "synced"}) is True

    def test_ahead_safe(self):
        assert safe_to_push({"status": "ahead"}) is True

    def test_behind_not_safe(self):
        assert safe_to_push({"status": "behind"}) is False

    def test_diverged_not_safe(self):
        assert safe_to_push({"status": "diverged"}) is False
