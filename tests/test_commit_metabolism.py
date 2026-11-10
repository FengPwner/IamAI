#!/usr/bin/env python3
"""Tests for commit_metabolism.py — codebase metabolism measurement."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_metabolism as cmet


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _c(sha="x", files=None, add=10, delete=0):
    """Shorthand factory for MetabolicCommit."""
    return cmet.MetabolicCommit(
        sha=sha,
        files=set(files or []),
        additions=add,
        deletions=delete,
    )


# ---------------------------------------------------------------------------
# classify_metabolism
# ---------------------------------------------------------------------------

class TestClassifyMetabolism:
    def test_anabolic_at_boundary(self):
        assert cmet.classify_metabolism(0.80) == "anabolic"

    def test_anabolic_high(self):
        assert cmet.classify_metabolism(0.95) == "anabolic"

    def test_anabolic_at_one(self):
        assert cmet.classify_metabolism(1.0) == "anabolic"

    def test_balanced_lower(self):
        assert cmet.classify_metabolism(0.60) == "balanced"

    def test_balanced_upper(self):
        assert cmet.classify_metabolism(0.79) == "balanced"

    def test_catabolic_lower(self):
        assert cmet.classify_metabolism(0.40) == "catabolic"

    def test_catabolic_upper(self):
        assert cmet.classify_metabolism(0.55) == "catabolic"

    def test_wasteful_lower(self):
        assert cmet.classify_metabolism(0.20) == "wasteful"

    def test_wasteful_upper(self):
        assert cmet.classify_metabolism(0.35) == "wasteful"

    def test_necrotic_at_zero(self):
        assert cmet.classify_metabolism(0.0) == "necrotic"

    def test_necrotic_low(self):
        assert cmet.classify_metabolism(0.10) == "necrotic"

    def test_necrotic_below_boundary(self):
        assert cmet.classify_metabolism(0.19) == "necrotic"

    def test_just_below_balanced(self):
        assert cmet.classify_metabolism(0.599) == "catabolic"

    def test_just_below_wasteful(self):
        assert cmet.classify_metabolism(0.199) == "necrotic"

    def test_clamp_above_one(self):
        assert cmet.classify_metabolism(1.5) == "anabolic"

    def test_negative(self):
        assert cmet.classify_metabolism(-0.5) == "necrotic"


# ---------------------------------------------------------------------------
# _compute_absorption_rate
# ---------------------------------------------------------------------------

class TestAbsorptionRate:
    def test_empty(self):
        assert cmet._compute_absorption_rate([]) == 0.0

    def test_single_commit(self):
        commits = [_c(sha="a", files={"x.py", "y.py"})]
        assert cmet._compute_absorption_rate(commits) == 0.0

    def test_all_absorbed(self):
        """All introduced files are touched again later."""
        commits = [
            _c(sha="a", files={"x.py"}),
            _c(sha="b", files={"x.py", "y.py"}),
            _c(sha="c", files={"x.py", "y.py"}),
        ]
        # x.py introduced at 0, touched at 1 -> absorbed
        # y.py introduced at 1, touched at 2 -> absorbed
        assert cmet._compute_absorption_rate(commits) == 1.0

    def test_none_absorbed(self):
        """Each commit introduces files never touched again."""
        commits = [
            _c(sha="a", files={"x.py"}),
            _c(sha="b", files={"y.py"}),
            _c(sha="c", files={"z.py"}),
        ]
        # x.py introduced at 0, never again -> not absorbed
        # y.py introduced at 1, never again -> not absorbed
        # z.py introduced at 2 -> last commit, can't be touched again
        assert cmet._compute_absorption_rate(commits) == 0.0

    def test_partial_absorption(self):
        commits = [
            _c(sha="a", files={"x.py", "y.py"}),
            _c(sha="b", files={"x.py"}),
            _c(sha="c", files={"z.py"}),
        ]
        # x.py introduced at 0, touched at 1 -> absorbed
        # y.py introduced at 0, never again -> not absorbed
        # z.py introduced at 2 -> last commit, no chance to absorb
        # 3 introduced files, 1 absorbed -> 1/3
        assert abs(cmet._compute_absorption_rate(commits) - 1 / 3) < 0.001

    def test_empty_file_sets(self):
        commits = [
            _c(sha="a", files=set()),
            _c(sha="b", files=set()),
        ]
        assert cmet._compute_absorption_rate(commits) == 0.0


# ---------------------------------------------------------------------------
# _compute_retention_score
# ---------------------------------------------------------------------------

class TestRetentionScore:
    def test_empty(self):
        assert cmet._compute_retention_score([]) == 0.0

    def test_all_retained(self):
        commits = [
            _c(add=50, delete=0),
            _c(add=30, delete=0),
        ]
        assert cmet._compute_retention_score(commits) == 1.0

    def test_half_retained(self):
        commits = [
            _c(add=100, delete=0),
            _c(add=0, delete=50),
        ]
        # net = 100 - 50 = 50, retention = 50/100 = 0.5
        assert cmet._compute_retention_score(commits) == 0.5

    def test_all_deleted(self):
        commits = [
            _c(add=100, delete=0),
            _c(add=0, delete=100),
        ]
        # net = 0, retention = 0/100 = 0
        assert cmet._compute_retention_score(commits) == 0.0

    def test_over_deleted(self):
        """Deletions exceed additions (legacy cleanup)."""
        commits = [
            _c(add=50, delete=0),
            _c(add=0, delete=100),
        ]
        # net = -50, clamped to 0
        assert cmet._compute_retention_score(commits) == 0.0

    def test_no_additions_only_deletions(self):
        commits = [_c(add=0, delete=50)]
        assert cmet._compute_retention_score(commits) == 0.0

    def test_no_changes_at_all(self):
        commits = [_c(add=0, delete=0)]
        assert cmet._compute_retention_score(commits) == 0.0


# ---------------------------------------------------------------------------
# _compute_rework_fraction
# ---------------------------------------------------------------------------

class TestReworkFraction:
    def test_empty(self):
        assert cmet._compute_rework_fraction([]) == 0.0

    def test_no_rework(self):
        commits = [_c(add=100, delete=0)]
        assert cmet._compute_rework_fraction(commits) == 0.0

    def test_full_rework(self):
        commits = [
            _c(add=100, delete=0),
            _c(add=0, delete=100),
        ]
        assert cmet._compute_rework_fraction(commits) == 1.0

    def test_partial_rework(self):
        commits = [
            _c(add=100, delete=0),
            _c(add=0, delete=30),
        ]
        assert cmet._compute_rework_fraction(commits) == 0.3

    def test_clamp_over_rework(self):
        """Deletions exceed additions."""
        commits = [
            _c(add=50, delete=0),
            _c(add=0, delete=200),
        ]
        assert cmet._compute_rework_fraction(commits) == 1.0

    def test_no_additions_has_deletions(self):
        commits = [_c(add=0, delete=50)]
        assert cmet._compute_rework_fraction(commits) == 1.0

    def test_no_additions_no_deletions(self):
        commits = [_c(add=0, delete=0)]
        assert cmet._compute_rework_fraction(commits) == 0.0


# ---------------------------------------------------------------------------
# _compute_churn_index
# ---------------------------------------------------------------------------

class TestChurnIndex:
    def test_empty(self):
        assert cmet._compute_churn_index([]) == 0.0

    def test_no_churn(self):
        """All commits have more additions than deletions."""
        commits = [
            _c(sha="a", files={"x.py"}, add=50, delete=10),
            _c(sha="b", files={"y.py"}, add=30, delete=5),
        ]
        assert cmet._compute_churn_index(commits) == 0.0

    def test_full_churn(self):
        """All commits delete more than they add."""
        commits = [
            _c(sha="a", files={"x.py"}, add=5, delete=50),
            _c(sha="b", files={"y.py"}, add=3, delete=30),
        ]
        assert cmet._compute_churn_index(commits) == 1.0

    def test_half_churn(self):
        commits = [
            _c(sha="a", files={"x.py", "y.py"}, add=50, delete=10),
            _c(sha="b", files={"z.py"}, add=5, delete=50),
        ]
        # commit a: add > del -> not churning (2 touches)
        # commit b: del > add -> churning (1 touch)
        # churn = 1/3
        assert abs(cmet._compute_churn_index(commits) - 1 / 3) < 0.001

    def test_no_files(self):
        commits = [_c(sha="a", files=set(), add=10, delete=5)]
        assert cmet._compute_churn_index(commits) == 0.0

    def test_equal_add_delete(self):
        """Equal additions and deletions — not churning (not strictly more)."""
        commits = [_c(sha="a", files={"x.py"}, add=50, delete=50)]
        assert cmet._compute_churn_index(commits) == 0.0


# ---------------------------------------------------------------------------
# _compute_efficiency
# ---------------------------------------------------------------------------

class TestEfficiency:
    def test_perfect_metabolism(self):
        score = cmet._compute_efficiency(1.0, 1.0, 0.0, 0.0)
        assert score == 1.0

    def test_terrible_metabolism(self):
        score = cmet._compute_efficiency(0.0, 0.0, 1.0, 1.0)
        assert score == 0.0

    def test_balanced(self):
        score = cmet._compute_efficiency(0.5, 0.5, 0.5, 0.5)
        # 0.30*0.5 + 0.30*0.5 + 0.25*0.5 + 0.15*0.5 = 0.5
        assert abs(score - 0.5) < 0.001

    def test_weights_matter(self):
        """Absorption and retention have more weight than rework/churn."""
        high_abs_ret = cmet._compute_efficiency(1.0, 1.0, 1.0, 1.0)
        # 0.30*1 + 0.30*1 + 0.25*0 + 0.15*0 = 0.60
        assert abs(high_abs_ret - 0.60) < 0.001

        low_abs_ret = cmet._compute_efficiency(0.0, 0.0, 0.0, 0.0)
        # 0.30*0 + 0.30*0 + 0.25*1 + 0.15*1 = 0.40
        assert abs(low_abs_ret - 0.40) < 0.001


# ---------------------------------------------------------------------------
# compute_metabolism
# ---------------------------------------------------------------------------

class TestComputeMetabolism:
    def test_empty(self):
        result = cmet.compute_metabolism([])
        assert result.metabolic_class == "necrotic"
        assert result.metabolic_efficiency == 0.0
        assert result.commit_count == 0

    def test_healthy_growth(self):
        """Files are introduced, built upon, with moderate additions."""
        commits = [
            _c(sha="a", files={"core.py", "utils.py"}, add=80, delete=0),
            _c(sha="b", files={"core.py", "tests.py"}, add=60, delete=10),
            _c(sha="c", files={"core.py", "utils.py", "tests.py"},
               add=20, delete=5),
        ]
        result = cmet.compute_metabolism(commits)
        assert result.commit_count == 3
        assert result.total_files == 3
        assert result.total_additions == 160
        assert result.total_deletions == 15
        # All files absorbed (core, utils, tests all touched again)
        assert result.absorption_rate == 1.0
        # Retention: (160-15)/160 = 0.9063
        assert result.retention_score > 0.9
        assert result.metabolic_class in ("anabolic", "balanced")

    def test_wasteful_churn(self):
        """Lots of one-shot files and heavy deletions."""
        commits = [
            _c(sha="a", files={"draft1.py"}, add=100, delete=0),
            _c(sha="b", files={"draft2.py"}, add=100, delete=0),
            _c(sha="c", files={"draft3.py"}, add=10, delete=200),
        ]
        result = cmet.compute_metabolism(commits)
        # No files are touched again after introduction
        assert result.absorption_rate == 0.0
        # Net: 210 - 200 = 10, retention = 10/210 ≈ 0.0476
        assert result.retention_score < 0.1
        assert result.metabolic_class in ("wasteful", "necrotic")

    def test_single_commit(self):
        commits = [_c(sha="a", files={"x.py"}, add=50, delete=10)]
        result = cmet.compute_metabolism(commits)
        assert result.commit_count == 1
        # Single commit: absorption = 0 (nothing to absorb into)
        assert result.absorption_rate == 0.0
        # Retention: (50-10)/50 = 0.8
        assert abs(result.retention_score - 0.8) < 0.01


# ---------------------------------------------------------------------------
# metabolism_trend
# ---------------------------------------------------------------------------

class TestMetabolismTrend:
    def test_empty(self):
        trend = cmet.metabolism_trend([])
        assert trend.trend == "stable"
        assert trend.slope == 0.0

    def test_strengthening(self):
        results = [
            cmet.MetabolismResult(metabolic_efficiency=0.3),
            cmet.MetabolismResult(metabolic_efficiency=0.5),
            cmet.MetabolismResult(metabolic_efficiency=0.7),
            cmet.MetabolismResult(metabolic_efficiency=0.85),
        ]
        trend = cmet.metabolism_trend(results)
        assert trend.trend == "strengthening"
        assert trend.slope > 0.02

    def test_declining(self):
        results = [
            cmet.MetabolismResult(metabolic_efficiency=0.9),
            cmet.MetabolismResult(metabolic_efficiency=0.7),
            cmet.MetabolismResult(metabolic_efficiency=0.4),
            cmet.MetabolismResult(metabolic_efficiency=0.2),
        ]
        trend = cmet.metabolism_trend(results)
        assert trend.trend == "declining"
        assert trend.slope < -0.02

    def test_stable(self):
        results = [
            cmet.MetabolismResult(metabolic_efficiency=0.65),
            cmet.MetabolismResult(metabolic_efficiency=0.66),
            cmet.MetabolismResult(metabolic_efficiency=0.64),
            cmet.MetabolismResult(metabolic_efficiency=0.65),
        ]
        trend = cmet.metabolism_trend(results)
        assert trend.trend == "stable"
        assert abs(trend.slope) <= 0.02

    def test_single_window(self):
        results = [cmet.MetabolismResult(metabolic_efficiency=0.7)]
        trend = cmet.metabolism_trend(results)
        assert trend.trend == "stable"
        assert trend.slope == 0.0
        assert trend.mean == 0.7

    def test_stats_computed(self):
        results = [
            cmet.MetabolismResult(metabolic_efficiency=0.5),
            cmet.MetabolismResult(metabolic_efficiency=0.7),
        ]
        trend = cmet.metabolism_trend(results)
        assert abs(trend.mean - 0.6) < 0.01
        assert trend.stddev > 0
        assert len(trend.scores) == 2


# ---------------------------------------------------------------------------
# metabolism_report
# ---------------------------------------------------------------------------

class TestMetabolismReport:
    def test_report_contains_key_fields(self):
        result = cmet.MetabolismResult(
            absorption_rate=0.75,
            retention_score=0.82,
            rework_fraction=0.15,
            churn_index=0.10,
            metabolic_efficiency=0.72,
            metabolic_class="balanced",
            commit_count=10,
            total_files=25,
            total_additions=500,
            total_deletions=75,
        )
        report = cmet.metabolism_report(result)
        assert "balanced" in report
        assert "0.72" in report
        assert "0.75" in report
        assert "0.82" in report
        assert "500" in report
        assert "10" in report

    def test_empty_report(self):
        result = cmet.MetabolismResult()
        report = cmet.metabolism_report(result)
        assert "necrotic" in report


# ---------------------------------------------------------------------------
# trend_report
# ---------------------------------------------------------------------------

class TestTrendReport:
    def test_report_contains_key_fields(self):
        trend = cmet.MetabolismTrend(
            scores=[0.6, 0.65, 0.7],
            trend="strengthening",
            slope=0.05,
            mean=0.65,
            stddev=0.04,
        )
        report = cmet.trend_report(trend)
        assert "strengthening" in report
        assert "0.05" in report
        assert "3" in report

    def test_empty_report(self):
        trend = cmet.MetabolismTrend()
        report = cmet.trend_report(trend)
        assert "No metabolism data" in report


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_many_files_one_commit(self):
        files = {f"file_{i}.py" for i in range(100)}
        commits = [_c(sha="a", files=files, add=1000, delete=0)]
        result = cmet.compute_metabolism(commits)
        assert result.total_files == 100
        assert result.absorption_rate == 0.0  # single commit, no absorption

    def test_duplicate_files_across_commits(self):
        """Same file touched in every commit."""
        commits = [
            _c(sha=f"c{i}", files={"core.py"}, add=10, delete=2)
            for i in range(10)
        ]
        result = cmet.compute_metabolism(commits)
        assert result.total_files == 1
        # core.py introduced at 0, touched in every subsequent commit
        assert result.absorption_rate == 1.0

    def test_zero_sized_commits(self):
        commits = [
            _c(sha="a", files=set(), add=0, delete=0),
            _c(sha="b", files=set(), add=0, delete=0),
        ]
        result = cmet.compute_metabolism(commits)
        assert result.commit_count == 2
        assert result.total_files == 0
        assert result.metabolic_efficiency >= 0.0
