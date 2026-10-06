"""Tests for iamai.commit_health — composite commit health scoring.

The health score is a weighted sum of four sub-scores. Each test
isolates one dimension to verify the scoring logic is correct and
the thresholds are where the docstrings say they are.
"""

import pytest

from iamai.commit_health import (
    commit_health_score,
    _stall_score,
    _backlog_score,
    _visit_cadence_score,
    _momentum_score,
    _grade,
)


# --- Sub-score tests ---


class TestStallScore:
    def test_healthy_gap(self):
        assert _stall_score(10, cadence_seconds=15) == 100

    def test_exact_cadence(self):
        # gap == cadence means ratio=1.0, which is < 2 → 75
        assert _stall_score(15, cadence_seconds=15) == 75

    def test_slight_delay(self):
        assert _stall_score(29, cadence_seconds=15) == 75

    def test_concerning(self):
        assert _stall_score(30, cadence_seconds=15) == 40

    def test_critical(self):
        assert _stall_score(60, cadence_seconds=15) == 0

    def test_very_long_stall(self):
        assert _stall_score(3600, cadence_seconds=15) == 0

    def test_zero_gap(self):
        assert _stall_score(0, cadence_seconds=15) == 100


class TestBacklogScore:
    def test_clean(self):
        assert _backlog_score(0) == 100

    def test_small_backlog(self):
        assert _backlog_score(5) == 80

    def test_at_soft_limit(self):
        assert _backlog_score(10) == 40

    def test_between_limits(self):
        assert _backlog_score(20) == 40

    def test_at_hard_limit(self):
        assert _backlog_score(30) == 10

    def test_above_hard_limit(self):
        assert _backlog_score(50) == 10

    def test_one_file(self):
        assert _backlog_score(1) == 80


class TestVisitCadenceScore:
    def test_frequent_visits(self):
        assert _visit_cadence_score(1.0) == 100

    def test_at_healthy_threshold(self):
        assert _visit_cadence_score(4.0) == 100

    def test_occasional_visits(self):
        assert _visit_cadence_score(8.0) == 70

    def test_at_warning_threshold(self):
        assert _visit_cadence_score(12.0) == 70

    def test_infrequent_visits(self):
        assert _visit_cadence_score(24.0) == 30

    def test_no_data(self):
        assert _visit_cadence_score(0.0) == 50

    def test_negative(self):
        # negative doesn't make sense physically, but should not crash
        assert _visit_cadence_score(-1.0) == 50


class TestMomentumScore:
    def test_high_momentum(self):
        assert _momentum_score(600) == 100

    def test_at_500(self):
        assert _momentum_score(500) == 100

    def test_moderate(self):
        assert _momentum_score(200) == 85

    def test_at_100(self):
        assert _momentum_score(100) == 85

    def test_low(self):
        assert _momentum_score(75) == 60

    def test_very_low(self):
        assert _momentum_score(10) == 40

    def test_zero(self):
        assert _momentum_score(0) == 40


# --- Grade tests ---


class TestGrade:
    def test_healthy(self):
        assert _grade(90) == "healthy"
        assert _grade(85) == "healthy"

    def test_degraded(self):
        assert _grade(65) == "degraded"
        assert _grade(80) == "degraded"

    def test_concerning(self):
        assert _grade(40) == "concerning"
        assert _grade(50) == "concerning"

    def test_critical(self):
        assert _grade(0) == "critical"
        assert _grade(39) == "critical"


# --- Composite score tests ---


class TestCommitHealthScore:
    def test_perfect_health(self):
        """All sub-scores at maximum → score should be 100."""
        result = commit_health_score(
            gap_seconds=5,
            pending_files=0,
            mean_visit_interval_hours=2.0,
            total_strokes=500,
        )
        assert result["score"] == 100
        assert result["grade"] == "healthy"
        assert result["advice"] == "All systems nominal."

    def test_dead_writer(self):
        """Writer stalled hard, everything else fine → concerning."""
        result = commit_health_score(
            gap_seconds=3600,
            pending_files=0,
            mean_visit_interval_hours=1.0,
            total_strokes=400,
        )
        # stall=0*0.35 + backlog=100*0.30 + visit=100*0.20 + momentum=85*0.15
        # = 0 + 30 + 20 + 12.75 = 62.75 → 63
        assert result["score"] == 63
        assert result["grade"] == "concerning"
        assert "stalled" in result["advice"].lower()

    def test_massive_backlog(self):
        """Large backlog, healthy writer → degraded."""
        result = commit_health_score(
            gap_seconds=10,
            pending_files=50,
            mean_visit_interval_hours=2.0,
            total_strokes=300,
        )
        # stall=100*0.35 + backlog=10*0.30 + visit=100*0.20 + momentum=85*0.15
        # = 35 + 3 + 20 + 12.75 = 70.75 → 71
        assert result["score"] == 71
        assert result["grade"] == "degraded"

    def test_everything_broken(self):
        """All sub-scores at minimum → critical."""
        result = commit_health_score(
            gap_seconds=3600,
            pending_files=50,
            mean_visit_interval_hours=48.0,
            total_strokes=5,
        )
        # stall=0*0.35 + backlog=10*0.30 + visit=30*0.20 + momentum=40*0.15
        # = 0 + 3 + 6 + 6 = 15
        assert result["score"] == 15
        assert result["grade"] == "critical"

    def test_breakdown_keys(self):
        """Ensure breakdown contains all four dimensions."""
        result = commit_health_score(gap_seconds=10)
        assert set(result["breakdown"].keys()) == {
            "stall", "backlog", "visit_cadence", "momentum"
        }

    def test_weights_sum_to_one(self):
        """Weights should sum to 1.0 (within float tolerance)."""
        result = commit_health_score(gap_seconds=10)
        assert abs(sum(result["weights"].values()) - 1.0) < 1e-9

    def test_defaults_all_zeros(self):
        """With defaults (except gap), score should be deterministic."""
        result = commit_health_score(gap_seconds=10)
        # stall=100*0.35 + backlog=100*0.30 + visit(no data)=50*0.20 + momentum(0)=40*0.15
        # = 35 + 30 + 10 + 6 = 81
        assert result["score"] == 81
        assert result["grade"] == "degraded"

    def test_score_bounded(self):
        """Score must be in [0, 100] regardless of inputs."""
        for gap in [0, 1, 15, 60, 3600, 86400]:
            for pending in [0, 1, 10, 100, 1000]:
                result = commit_health_score(
                    gap_seconds=gap,
                    pending_files=pending,
                    mean_visit_interval_hours=2.0,
                    total_strokes=200,
                )
                assert 0 <= result["score"] <= 100
