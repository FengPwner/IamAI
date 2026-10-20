"""Tests for tools/stall_cluster_analyzer.py — cluster analysis logic."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.stall_cluster_analyzer import (
    analyse_clusters,
    cluster_density,
    cluster_severity,
    cluster_summary,
    group_clusters,
)


# ── group_clusters ────────────────────────────────────────────────

class TestGroupClusters:
    def test_empty(self):
        assert group_clusters([]) == []

    def test_single_stall(self):
        result = group_clusters([5])
        assert result == [[5]]

    def test_two_stalls_close(self):
        """Two stalls within cluster_radius belong to same cluster."""
        result = group_clusters([5, 7], cluster_radius=2)
        assert result == [[5, 7]]

    def test_two_stalls_far(self):
        """Two stalls beyond cluster_radius form separate clusters."""
        result = group_clusters([5, 10], cluster_radius=2)
        assert result == [[5], [10]]

    def test_chain_within_radius(self):
        """A chain of stalls, each within radius of the previous."""
        result = group_clusters([1, 3, 5, 7], cluster_radius=2)
        assert result == [[1, 3, 5, 7]]

    def test_chain_with_break(self):
        """A clear gap in the middle splits into two clusters."""
        result = group_clusters([1, 3, 10, 12], cluster_radius=2)
        assert result == [[1, 3], [10, 12]]

    def test_radius_one(self):
        """Only adjacent stalls cluster when radius=1."""
        result = group_clusters([1, 2, 5, 6, 7], cluster_radius=1)
        assert result == [[1, 2], [5, 6, 7]]

    def test_radius_zero(self):
        """Radius 0: only identical indices cluster (impossible in practice)."""
        result = group_clusters([1, 2, 3], cluster_radius=0)
        assert result == [[1], [2], [3]]

    def test_large_gap(self):
        result = group_clusters([2, 100], cluster_radius=5)
        assert result == [[2], [100]]

    def test_many_clusters(self):
        result = group_clusters(
            [1, 2, 10, 11, 20, 21, 22, 50],
            cluster_radius=2,
        )
        assert len(result) == 4
        assert result[0] == [1, 2]
        assert result[1] == [10, 11]
        assert result[2] == [20, 21, 22]
        assert result[3] == [50]


# ── cluster_severity ──────────────────────────────────────────────

class TestClusterSeverity:
    def test_mild_small_cluster(self):
        assert cluster_severity(2, 0.3) == "mild"

    def test_mild_single(self):
        assert cluster_severity(1, 0.1) == "mild"

    def test_moderate_by_size(self):
        assert cluster_severity(4, 0.3) == "moderate"

    def test_moderate_by_density(self):
        assert cluster_severity(2, 0.5) == "moderate"

    def test_severe_by_size(self):
        assert cluster_severity(7, 0.3) == "severe"

    def test_severe_by_density(self):
        assert cluster_severity(3, 0.8) == "severe"

    def test_severe_large_cluster(self):
        assert cluster_severity(10, 0.5) == "severe"

    def test_boundary_density_0_5(self):
        """Exactly 0.5 density → moderate."""
        assert cluster_severity(2, 0.5) == "moderate"

    def test_boundary_density_0_8(self):
        """Exactly 0.8 density → severe."""
        assert cluster_severity(3, 0.8) == "severe"

    def test_boundary_size_7(self):
        """Exactly 7 stalls → severe regardless of density."""
        assert cluster_severity(7, 0.1) == "severe"

    def test_boundary_size_4(self):
        """Exactly 4 stalls → moderate."""
        assert cluster_severity(4, 0.1) == "moderate"


# ── cluster_density ───────────────────────────────────────────────

class TestClusterDensity:
    def test_single_stall(self):
        """Single stall: density = 1/total_commits."""
        assert cluster_density([5], 100) == pytest.approx(0.01)

    def test_full_span(self):
        """All commits are stalls: density = 1.0."""
        assert cluster_density([0, 1, 2, 3, 4], 5) == pytest.approx(1.0)

    def test_half_span(self):
        """3 stalls spanning 6 commits: density = 0.5."""
        assert cluster_density([0, 3, 5], 10) == pytest.approx(0.5)

    def test_zero_total_commits(self):
        """Edge case: total_commits=0 should not crash."""
        result = cluster_density([5], 0)
        assert result >= 0  # just shouldn't raise

    def test_sparse_cluster(self):
        """2 stalls spanning 10 commits."""
        assert cluster_density([0, 9], 100) == pytest.approx(0.2)


# ── analyse_clusters ─────────────────────────────────────────────

class TestAnalyseClusters:
    def test_empty(self):
        result = analyse_clusters([], 100)
        assert result == []

    def test_basic(self):
        result = analyse_clusters([1, 3, 10, 11, 12], 50, cluster_radius=2)
        assert len(result) == 2
        assert result[0]["size"] == 2
        assert result[1]["size"] == 3

    def test_fields_present(self):
        result = analyse_clusters([5, 7], 100)
        assert len(result) == 1
        cl = result[0]
        assert "start" in cl
        assert "end" in cl
        assert "size" in cl
        assert "density" in cl
        assert "severity" in cl

    def test_severity_assigned(self):
        """A cluster of 5 stalls should be at least moderate."""
        result = analyse_clusters([1, 2, 3, 4, 5], 20, cluster_radius=1)
        assert len(result) == 1
        assert result[0]["severity"] in ("moderate", "severe")

    def test_density_bounded(self):
        result = analyse_clusters([0, 1, 2, 3, 4], 10)
        for cl in result:
            assert 0.0 <= cl["density"] <= 1.0


# ── cluster_summary ───────────────────────────────────────────────

class TestClusterSummary:
    def test_empty(self):
        result = cluster_summary([])
        assert result["total_clusters"] == 0
        assert result["severe_ratio"] == 0.0

    def test_single_mild(self):
        clusters = [{"start": 0, "end": 1, "size": 2, "density": 0.3, "severity": "mild"}]
        result = cluster_summary(clusters)
        assert result["total_clusters"] == 1
        assert result["mild_clusters"] == 1
        assert result["severe_clusters"] == 0
        assert result["mean_cluster_size"] == 2.0

    def test_mixed_severity(self):
        clusters = [
            {"start": 0, "end": 1, "size": 2, "density": 0.2, "severity": "mild"},
            {"start": 10, "end": 15, "size": 5, "density": 0.6, "severity": "moderate"},
            {"start": 30, "end": 40, "size": 8, "density": 0.8, "severity": "severe"},
        ]
        result = cluster_summary(clusters)
        assert result["total_clusters"] == 3
        assert result["severe_clusters"] == 1
        assert result["moderate_clusters"] == 1
        assert result["mild_clusters"] == 1
        assert result["max_cluster_size"] == 8
        assert result["mean_cluster_size"] == pytest.approx(5.0)
        # 8 stalls in severe out of 15 total
        assert result["severe_ratio"] == pytest.approx(8 / 15, rel=0.01)

    def test_all_severe(self):
        clusters = [
            {"start": 0, "end": 10, "size": 8, "density": 0.8, "severity": "severe"},
            {"start": 20, "end": 30, "size": 9, "density": 0.9, "severity": "severe"},
        ]
        result = cluster_summary(clusters)
        assert result["severe_ratio"] == 1.0

    def test_summary_fields(self):
        result = cluster_summary([])
        expected_keys = {
            "total_clusters", "severe_clusters", "moderate_clusters",
            "mild_clusters", "mean_cluster_size", "max_cluster_size",
            "severe_ratio",
        }
        assert set(result.keys()) == expected_keys


# ── integration-style tests ───────────────────────────────────────

class TestIntegration:
    def test_realistic_scenario(self):
        """Simulate a realistic stall pattern: a burst, quiet, then another."""
        # Cluster 1: stalls at commits 5,6,7,8,9,10,11 (7 stalls, dense)
        # Quiet: commits 12-30
        # Cluster 2: stalls at commits 31,33 (2 stalls, sparse)
        stall_indices = [5, 6, 7, 8, 9, 10, 11, 31, 33]
        clusters = analyse_clusters(stall_indices, 100, cluster_radius=2)
        summary = cluster_summary(clusters)

        assert summary["total_clusters"] == 2
        # First cluster should be severe (7 stalls, high density)
        assert clusters[0]["severity"] == "severe"
        assert clusters[0]["size"] == 7
        # Second cluster: 2 stalls spanning 3 commits → density 0.667 → moderate
        assert clusters[1]["severity"] == "moderate"
        assert clusters[1]["size"] == 2

    def test_no_stalls(self):
        """Healthy repo with no stalls should produce clean output."""
        clusters = analyse_clusters([], 100)
        summary = cluster_summary(clusters)
        assert summary["total_clusters"] == 0
        assert summary["severe_ratio"] == 0.0
        assert summary["max_cluster_size"] == 0
