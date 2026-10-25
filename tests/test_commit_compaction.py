"""Tests for iamai.commit_compaction — commit density tracking."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.commit_compaction import (
    _count_commits_in_window,
    _total_commits,
    classify_density,
    commit_density,
    compaction_summary,
)


# ---------------------------------------------------------------------------
# classify_density
# ---------------------------------------------------------------------------

class TestClassifyDensity:
    def test_sparse_below_2(self):
        assert classify_density(1.0) == "sparse"

    def test_sparse_at_zero(self):
        assert classify_density(0.0) == "sparse"

    def test_sparse_just_below_threshold(self):
        assert classify_density(1.99) == "sparse"

    def test_healthy_at_2(self):
        assert classify_density(2.0) == "healthy"

    def test_healthy_midpoint(self):
        assert classify_density(4.0) == "healthy"

    def test_healthy_just_below_6(self):
        assert classify_density(5.99) == "healthy"

    def test_dense_at_6(self):
        assert classify_density(6.0) == "dense"

    def test_dense_midpoint(self):
        assert classify_density(8.0) == "dense"

    def test_dense_just_below_12(self):
        assert classify_density(11.99) == "dense"

    def test_compact_at_12(self):
        assert classify_density(12.0) == "compact"

    def test_compact_above_12(self):
        assert classify_density(15.0) == "compact"

    def test_compact_far_above(self):
        assert classify_density(100.0) == "compact"


# ---------------------------------------------------------------------------
# _count_commits_in_window
# ---------------------------------------------------------------------------

class TestCountCommitsInWindow:
    def test_no_repo(self, tmp_path):
        """Non-existent repo returns 0."""
        count = _count_commits_in_window(tmp_path / "nonexistent", 60)
        assert count == 0

    def test_git_failure_returns_0(self, tmp_path):
        """Git command failure returns 0."""
        with patch("iamai.commit_compaction._run_git", return_value=None):
            count = _count_commits_in_window(tmp_path, 60)
            assert count == 0

    def test_valid_count(self, tmp_path):
        """Valid git output is parsed correctly."""
        with patch("iamai.commit_compaction._run_git", return_value="15\n"):
            count = _count_commits_in_window(tmp_path, 60)
            assert count == 15

    def test_empty_string_returns_0(self, tmp_path):
        """Empty git output returns 0."""
        with patch("iamai.commit_compaction._run_git", return_value=""):
            count = _count_commits_in_window(tmp_path, 60)
            assert count == 0

    def test_invalid_output_returns_0(self, tmp_path):
        """Non-numeric git output returns 0."""
        with patch("iamai.commit_compaction._run_git", return_value="not a number"):
            count = _count_commits_in_window(tmp_path, 60)
            assert count == 0


# ---------------------------------------------------------------------------
# _total_commits
# ---------------------------------------------------------------------------

class TestTotalCommits:
    def test_no_repo(self, tmp_path):
        """Non-existent repo returns 0."""
        total = _total_commits(tmp_path / "nonexistent")
        assert total == 0

    def test_git_failure_returns_0(self, tmp_path):
        """Git command failure returns 0."""
        with patch("iamai.commit_compaction._run_git", return_value=None):
            total = _total_commits(tmp_path)
            assert total == 0

    def test_valid_count(self, tmp_path):
        """Valid git output is parsed correctly."""
        with patch("iamai.commit_compaction._run_git", return_value="1403\n"):
            total = _total_commits(tmp_path)
            assert total == 1403

    def test_empty_string_returns_0(self, tmp_path):
        """Empty git output returns 0."""
        with patch("iamai.commit_compaction._run_git", return_value=""):
            total = _total_commits(tmp_path)
            assert total == 0


# ---------------------------------------------------------------------------
# commit_density
# ---------------------------------------------------------------------------

class TestCommitDensity:
    def test_empty_repo(self, tmp_path):
        """Empty repo returns sparse verdict."""
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=0):
            with patch("iamai.commit_compaction._total_commits", return_value=0):
                result = commit_density(tmp_path, 60)
                assert result["commits_in_window"] == 0
                assert result["commits_per_hour"] == 0.0
                assert result["verdict"] == "sparse"

    def test_healthy_density(self, tmp_path):
        """Healthy commit rate is classified correctly."""
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=4):
            with patch("iamai.commit_compaction._total_commits", return_value=100):
                result = commit_density(tmp_path, 60)
                assert result["commits_in_window"] == 4
                assert result["commits_per_hour"] == 4.0
                assert result["verdict"] == "healthy"

    def test_dense_rate(self, tmp_path):
        """Dense commit rate is classified correctly."""
        # 8 commits in 60 minutes = 8 cph
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=8):
            with patch("iamai.commit_compaction._total_commits", return_value=500):
                result = commit_density(tmp_path, 60)
                assert result["commits_per_hour"] == 8.0
                assert result["verdict"] == "dense"

    def test_compact_rate(self, tmp_path):
        """Compact commit rate is classified correctly."""
        # 15 commits in 60 minutes = 15 cph
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=15):
            with patch("iamai.commit_compaction._total_commits", return_value=1403):
                result = commit_density(tmp_path, 60)
                assert result["commits_per_hour"] == 15.0
                assert result["verdict"] == "compact"

    def test_short_window_scales_rate(self, tmp_path):
        """Shorter window scales the rate correctly."""
        # 5 commits in 30 minutes = 10 cph
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=5):
            with patch("iamai.commit_compaction._total_commits", return_value=200):
                result = commit_density(tmp_path, 30)
                assert result["commits_per_hour"] == 10.0
                assert result["verdict"] == "dense"

    def test_long_window(self, tmp_path):
        """Longer window computes rate correctly."""
        # 20 commits in 120 minutes = 10 cph
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=20):
            with patch("iamai.commit_compaction._total_commits", return_value=800):
                result = commit_density(tmp_path, 120)
                assert result["commits_per_hour"] == 10.0
                assert result["verdict"] == "dense"

    def test_window_minutes_preserved(self, tmp_path):
        """The requested window is preserved in the output."""
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=1):
            with patch("iamai.commit_compaction._total_commits", return_value=50):
                result = commit_density(tmp_path, 45)
                assert result["window_minutes"] == 45

    def test_total_commits_preserved(self, tmp_path):
        """Total commits are preserved in the output."""
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=3):
            with patch("iamai.commit_compaction._total_commits", return_value=999):
                result = commit_density(tmp_path, 60)
                assert result["total_commits"] == 999


# ---------------------------------------------------------------------------
# compaction_summary
# ---------------------------------------------------------------------------

class TestCompactionSummary:
    def test_compact_recommends_squash(self, tmp_path):
        """Compact verdict recommends squash."""
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=15):
            with patch("iamai.commit_compaction._total_commits", return_value=1403):
                summary = compaction_summary(tmp_path, 60)
                assert "compact" in summary
                assert "squash recommended" in summary
                assert "1403 total" in summary

    def test_dense_considers_squash(self, tmp_path):
        """Dense verdict suggests considering squash."""
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=8):
            with patch("iamai.commit_compaction._total_commits", return_value=500):
                summary = compaction_summary(tmp_path, 60)
                assert "dense" in summary
                assert "consider squashing" in summary

    def test_healthy_no_action(self, tmp_path):
        """Healthy verdict says no action needed."""
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=4):
            with patch("iamai.commit_compaction._total_commits", return_value=823):
                summary = compaction_summary(tmp_path, 60)
                assert "healthy" in summary
                assert "no action needed" in summary

    def test_sparse_nothing_to_squash(self, tmp_path):
        """Sparse verdict says nothing to squash."""
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=0):
            with patch("iamai.commit_compaction._total_commits", return_value=0):
                summary = compaction_summary(tmp_path, 60)
                assert "sparse" in summary
                assert "nothing to squash" in summary

    def test_rate_included(self, tmp_path):
        """The commit rate is included in the summary."""
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=10):
            with patch("iamai.commit_compaction._total_commits", return_value=600):
                summary = compaction_summary(tmp_path, 60)
                assert "10.0 commits/hr" in summary

    def test_format_consistency(self, tmp_path):
        """Summary format is consistent across verdicts."""
        with patch("iamai.commit_compaction._count_commits_in_window", return_value=4):
            with patch("iamai.commit_compaction._total_commits", return_value=100):
                summary = compaction_summary(tmp_path, 60)
                # Should match pattern: "X commits/hr (VERDICT) — ACTION, Y total"
                assert "commits/hr" in summary
                assert "(" in summary and ")" in summary
                assert "—" in summary
                assert "total" in summary
