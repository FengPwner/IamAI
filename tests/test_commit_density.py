"""Tests for iamai/commit_density.py — commit content density measurement."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.commit_density import (
    NOISE_FLOOR,
    aggregate_label,
    commit_density,
    density_report,
    density_summary,
    score_commits,
)


# ---------------------------------------------------------------------------
# commit_density
# ---------------------------------------------------------------------------

class TestCommitDensity:
    def test_zero_changes(self):
        assert commit_density(0, 0) == 0.0

    def test_noise_floor_exact(self):
        """Exactly noise_floor lines changed → density 0."""
        assert commit_density(1, 1) == 0.0

    def test_below_noise_floor(self):
        assert commit_density(1, 0) == 0.0

    def test_small_real_change(self):
        """3 insertions, 0 deletions → (3-2)/3 = 0.3333."""
        assert commit_density(3, 0) == pytest.approx(0.3333, abs=0.001)

    def test_medium_change(self):
        """10+5=15 raw, useful=13, density=13/15=0.8667."""
        assert commit_density(10, 5) == pytest.approx(0.8667, abs=0.001)

    def test_large_change(self):
        """50+50=100, useful=98, density=0.98."""
        assert commit_density(50, 50) == 0.98

    def test_custom_noise_floor(self):
        """With noise_floor=10, a 12-line commit → 2/12=0.1667."""
        assert commit_density(8, 4, noise_floor=10) == pytest.approx(0.1667, abs=0.001)

    def test_negative_insertions_clamped(self):
        """Negative values treated as zero raw."""
        assert commit_density(-5, 0) == 0.0

    def test_pure_deletion(self):
        """0 insertions, 10 deletions → 8/10 = 0.8."""
        assert commit_density(0, 10) == 0.8


# ---------------------------------------------------------------------------
# aggregate_label
# ---------------------------------------------------------------------------

class TestAggregateLabel:
    def test_dense(self):
        assert aggregate_label(0.85) == "dense"

    def test_dense_boundary(self):
        assert aggregate_label(0.70) == "dense"

    def test_moderate(self):
        assert aggregate_label(0.55) == "moderate"

    def test_moderate_boundary(self):
        assert aggregate_label(0.40) == "moderate"

    def test_thin(self):
        assert aggregate_label(0.30) == "thin"

    def test_thin_boundary(self):
        assert aggregate_label(0.20) == "thin"

    def test_hollow(self):
        assert aggregate_label(0.10) == "hollow"

    def test_hollow_zero(self):
        assert aggregate_label(0.0) == "hollow"


# ---------------------------------------------------------------------------
# score_commits
# ---------------------------------------------------------------------------

class TestScoreCommits:
    def test_empty_list(self):
        assert score_commits([]) == []

    def test_single_commit(self):
        commits = [{"hash": "abc1234", "insertions": 20, "deletions": 5, "files": 3}]
        result = score_commits(commits)
        assert len(result) == 1
        assert result[0]["hash"] == "abc1234"
        assert result[0]["density"] == pytest.approx(0.92, abs=0.01)
        assert result[0]["files"] == 3

    def test_missing_fields_default(self):
        """Missing insertions/deletions default to 0."""
        commits = [{"hash": "def5678"}]
        result = score_commits(commits)
        assert result[0]["density"] == 0.0
        assert result[0]["insertions"] == 0

    def test_multiple_commits(self):
        commits = [
            {"hash": "a", "insertions": 50, "deletions": 0},
            {"hash": "b", "insertions": 1, "deletions": 1},
            {"hash": "c", "insertions": 10, "deletions": 10},
        ]
        result = score_commits(commits)
        assert len(result) == 3
        assert result[0]["density"] > result[1]["density"]
        assert result[1]["density"] == 0.0  # noise floor
        assert result[2]["density"] == 0.9


# ---------------------------------------------------------------------------
# density_report
# ---------------------------------------------------------------------------

class TestDensityReport:
    def test_empty_commits(self):
        report = density_report([])
        assert report["count"] == 0
        assert report["label"] == "hollow"

    def test_all_dense(self):
        commits = [
            {"hash": f"c{i}", "insertions": 50, "deletions": 10}
            for i in range(5)
        ]
        report = density_report(commits)
        assert report["count"] == 5
        assert report["label"] == "dense"
        assert report["mean_density"] > 0.70

    def test_all_hollow(self):
        commits = [
            {"hash": f"c{i}", "insertions": 1, "deletions": 1}
            for i in range(5)
        ]
        report = density_report(commits)
        assert report["label"] == "hollow"
        assert report["mean_density"] == 0.0

    def test_median_odd(self):
        commits = [
            {"hash": "a", "insertions": 1, "deletions": 1},   # 0.0
            {"hash": "b", "insertions": 10, "deletions": 0},   # 0.8
            {"hash": "c", "insertions": 50, "deletions": 50},  # 0.98
        ]
        report = density_report(commits)
        assert report["median_density"] == 0.8

    def test_median_even(self):
        commits = [
            {"hash": "a", "insertions": 1, "deletions": 1},   # 0.0
            {"hash": "b", "insertions": 5, "deletions": 0},    # 0.6
            {"hash": "c", "insertions": 10, "deletions": 0},   # 0.8
            {"hash": "d", "insertions": 50, "deletions": 50},  # 0.98
        ]
        report = density_report(commits)
        assert report["median_density"] == pytest.approx(0.7, abs=0.01)


# ---------------------------------------------------------------------------
# density_summary
# ---------------------------------------------------------------------------

class TestDensitySummary:
    def test_empty(self):
        assert density_summary({"count": 0}) == "no commits to score"

    def test_normal(self):
        report = {
            "count": 10,
            "mean_density": 0.6543,
            "median_density": 0.7000,
            "label": "moderate",
        }
        s = density_summary(report)
        assert "10 commits" in s
        assert "0.65" in s
        assert "moderate" in s
