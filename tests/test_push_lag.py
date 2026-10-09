#!/usr/bin/env python3
"""Tests for push_lag.py — local/remote commit lag measurement.

These tests mock subprocess calls to avoid requiring a real git repo
with remotes. Each test verifies one behavior of the lag computation
pipeline.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import push_lag as pl


# ---------------------------------------------------------------------------
# count_commits
# ---------------------------------------------------------------------------

class TestCountCommits:
    def test_returns_count_from_git_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "5\n"
        with patch.object(pl, "_git", return_value=mock_result) as mock_git:
            count = pl.count_commits("HEAD", "origin/main", cwd=Path("/tmp"))
            assert count == 5
            mock_git.assert_called_once_with(
                "rev-list", "--count", "HEAD..origin/main", cwd=Path("/tmp")
            )

    def test_returns_zero_on_git_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        with patch.object(pl, "_git", return_value=mock_result):
            count = pl.count_commits("HEAD", "origin/main")
            assert count == 0

    def test_returns_zero_on_bad_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not-a-number\n"
        with patch.object(pl, "_git", return_value=mock_result):
            count = pl.count_commits("HEAD", "origin/main")
            assert count == 0


# ---------------------------------------------------------------------------
# merge_base
# ---------------------------------------------------------------------------

class TestMergeBase:
    def test_returns_short_hash(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abcdef1234567890abcdef\n"
        with patch.object(pl, "_git", return_value=mock_result) as mock_git:
            base = pl.merge_base("HEAD", "origin/main", cwd=Path("/tmp"))
            assert base == "abcdef123456"
            mock_git.assert_called_once_with(
                "merge-base", "HEAD", "origin/main", cwd=Path("/tmp")
            )

    def test_returns_none_on_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch.object(pl, "_git", return_value=mock_result):
            base = pl.merge_base("HEAD", "origin/main")
            assert base is None


# ---------------------------------------------------------------------------
# local_head
# ---------------------------------------------------------------------------

class TestLocalHead:
    def test_returns_short_hash(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc1234\n"
        with patch.object(pl, "_git", return_value=mock_result):
            head = pl.local_head()
            assert head == "abc1234"

    def test_returns_none_on_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 128
        with patch.object(pl, "_git", return_value=mock_result):
            head = pl.local_head()
            assert head is None


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

class TestFetch:
    def test_returns_true_on_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch.object(pl, "_git", return_value=mock_result) as mock_git:
            ok = pl.fetch("origin", "main", cwd=Path("/tmp"))
            assert ok is True
            mock_git.assert_called_once_with("fetch", "origin", "main", cwd=Path("/tmp"))

    def test_returns_false_on_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch.object(pl, "_git", return_value=mock_result):
            ok = pl.fetch("origin", "main")
            assert ok is False


# ---------------------------------------------------------------------------
# compute_lag
# ---------------------------------------------------------------------------

class TestComputeLag:
    def test_pushable_when_not_behind(self):
        """Local is up to date — push should succeed."""
        with patch.object(pl, "fetch", return_value=True), \
             patch.object(pl, "count_commits", side_effect=lambda a, b, cwd=None: 0), \
             patch.object(pl, "merge_base", return_value="abc123def456"), \
             patch.object(pl, "local_head", return_value="def456"):
            lag = pl.compute_lag(do_fetch=True)
            assert lag["pushable"] is True
            assert lag["behind"] == 0
            assert lag["ahead"] == 0

    def test_blocked_when_behind(self):
        """Remote has commits local doesn't — push would fail."""
        def fake_count(ref_a, ref_b, cwd=None):
            # HEAD..origin/main = 3 (behind), origin/main..HEAD = 0 (ahead)
            if ref_a == "HEAD":
                return 3
            return 0

        with patch.object(pl, "fetch", return_value=True), \
             patch.object(pl, "count_commits", side_effect=fake_count), \
             patch.object(pl, "merge_base", return_value="abc123def456"), \
             patch.object(pl, "local_head", return_value="def456"):
            lag = pl.compute_lag(do_fetch=True)
            assert lag["pushable"] is False
            assert lag["behind"] == 3
            assert lag["ahead"] == 0

    def test_diverged_state(self):
        """Both sides have unique commits."""
        def fake_count(ref_a, ref_b, cwd=None):
            if ref_a == "HEAD":
                return 2  # behind
            return 5  # ahead

        with patch.object(pl, "fetch", return_value=True), \
             patch.object(pl, "count_commits", side_effect=fake_count), \
             patch.object(pl, "merge_base", return_value="base12345678"), \
             patch.object(pl, "local_head", return_value="local123"):
            lag = pl.compute_lag(do_fetch=True)
            assert lag["pushable"] is False
            assert lag["behind"] == 2
            assert lag["ahead"] == 5
            assert lag["divergence_point"] == "base12345678"

    def test_skip_fetch(self):
        """When do_fetch=False, fetch should not be called."""
        with patch.object(pl, "fetch") as mock_fetch, \
             patch.object(pl, "count_commits", return_value=0), \
             patch.object(pl, "merge_base", return_value="abc123"), \
             patch.object(pl, "local_head", return_value="def456"):
            lag = pl.compute_lag(do_fetch=False)
            mock_fetch.assert_not_called()

    def test_remote_ref_format(self):
        """Verify the remote_ref is constructed correctly."""
        with patch.object(pl, "fetch", return_value=True), \
             patch.object(pl, "count_commits", return_value=0), \
             patch.object(pl, "merge_base", return_value="abc123"), \
             patch.object(pl, "local_head", return_value="def456"):
            lag = pl.compute_lag(remote="upstream", branch="develop")
            assert lag["remote_ref"] == "upstream/develop"


# ---------------------------------------------------------------------------
# format_text
# ---------------------------------------------------------------------------

class TestFormatText:
    def test_clear_state(self):
        lag = {
            "behind": 0,
            "ahead": 2,
            "pushable": True,
            "divergence_point": "abc123def456",
            "local_head": "xyz789",
            "remote_ref": "origin/main",
        }
        text = pl.format_text(lag)
        assert "CLEAR" in text
        assert "pushable: True" in text
        assert "xyz789" in text

    def test_blocked_state_shows_fix_hint(self):
        lag = {
            "behind": 3,
            "ahead": 0,
            "pushable": False,
            "divergence_point": "abc123def456",
            "local_head": "xyz789",
            "remote_ref": "origin/main",
        }
        text = pl.format_text(lag)
        assert "BLOCKED" in text
        assert "git pull --rebase" in text
        assert "3 commit(s)" in text
