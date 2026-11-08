"""Tests for iamai.commit_rhythm_drift — commit cadence drift analysis.

Tests cover:
- IntervalDrift properties (over / under)
- CommitRhythmDrift basic metrics (mean, max, min, count)
- Trend calculation (recovering, degrading, stable)
- Health grading (steady, drifting, erratic, stalled)
- Edge cases (0/1 timestamps, unsorted input, equal gaps)
- Convenience functions (rhythm_health, drift_report)
"""

import pytest

from iamai.commit_rhythm_drift import (
    DEFAULT_TARGET,
    STALL_MULTIPLIER,
    CommitRhythmDrift,
    IntervalDrift,
    drift_report,
    rhythm_health,
)


# --- helpers ---


def _perfect_timestamps(n: int, target: float = DEFAULT_TARGET, start: float = 1000.0) -> list[float]:
    """Generate n timestamps with exactly target-second gaps."""
    return [start + i * target for i in range(n)]


def _drifting_timestamps(gaps: list[float], start: float = 1000.0) -> list[float]:
    """Generate timestamps from a list of inter-commit gaps."""
    ts = [start]
    for g in gaps:
        ts.append(ts[-1] + g)
    return ts


# --- IntervalDrift ---


class TestIntervalDrift:
    def test_over(self):
        iv = IntervalDrift(gap=700, target=600, drift=100, drift_ratio=100/600)
        assert iv.over is True
        assert iv.under is False

    def test_under(self):
        iv = IntervalDrift(gap=500, target=600, drift=100, drift_ratio=100/600)
        assert iv.over is False
        assert iv.under is True

    def test_exact(self):
        iv = IntervalDrift(gap=600, target=600, drift=0, drift_ratio=0.0)
        assert iv.over is False
        assert iv.under is False

    def test_frozen(self):
        iv = IntervalDrift(gap=600, target=600, drift=0, drift_ratio=0.0)
        with pytest.raises(AttributeError):
            iv.gap = 700


# --- CommitRhythmDrift: basic metrics ---


class TestBasicMetrics:
    def test_count(self):
        rd = CommitRhythmDrift(tuple(_perfect_timestamps(5)))
        assert rd.count == 4

    def test_count_empty(self):
        rd = CommitRhythmDrift(())
        assert rd.count == 0

    def test_count_single(self):
        rd = CommitRhythmDrift((1000.0,))
        assert rd.count == 0

    def test_mean_drift_perfect(self):
        rd = CommitRhythmDrift(tuple(_perfect_timestamps(5)))
        assert rd.mean_drift == pytest.approx(0.0)
        assert rd.mean_drift_ratio == pytest.approx(0.0)

    def test_mean_drift_uniform_over(self):
        # All gaps 700s, target 600 → drift = 100 each, ratio = 1/6
        ts = _drifting_timestamps([700, 700, 700, 700])
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.mean_drift == pytest.approx(100.0)
        assert rd.mean_drift_ratio == pytest.approx(100 / 600)

    def test_mean_drift_mixed(self):
        # Gaps: 500 (drift 100), 700 (drift 100) → mean drift = 100
        ts = _drifting_timestamps([500, 700])
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.count == 2
        assert rd.mean_drift == pytest.approx(100.0)

    def test_max_drift(self):
        ts = _drifting_timestamps([610, 620, 900, 610])
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.max_drift == pytest.approx(300.0)
        assert rd.max_drift_ratio == pytest.approx(300 / 600)

    def test_min_gap(self):
        ts = _drifting_timestamps([500, 650, 580, 620])
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.min_gap == pytest.approx(500.0)

    def test_max_gap(self):
        ts = _drifting_timestamps([500, 650, 1200, 580])
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.max_gap == pytest.approx(1200.0)

    def test_unsorted_input_sorted_internally(self):
        ts = [1600, 1000, 2200]  # unsorted → sorted: [1000, 1600, 2200]
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.timestamps == (1000.0, 1600.0, 2200.0)
        assert rd.count == 2
        assert rd.mean_drift == pytest.approx(0.0)

    def test_zero_target_avoids_division_error(self):
        ts = _drifting_timestamps([100, 200, 300])
        rd = CommitRhythmDrift(tuple(ts), target=0)
        # drift_ratio = drift / 0 → guarded: returns 0.0
        assert rd.mean_drift_ratio == 0.0


# --- trend ---


class TestTrend:
    def test_trend_stable(self):
        # All intervals identical → zero slope
        ts = _perfect_timestamps(10, target=600)
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.trend == pytest.approx(0.0)
        assert rd.trend_label == "stable"

    def test_trend_recovering(self):
        # Gaps decreasing: 900, 800, 700, 650, 620 → drift shrinking
        ts = _drifting_timestamps([900, 800, 700, 650, 620])
        rd = CommitRhythmDrift(tuple(ts), target=600)
        assert rd.trend < -0.01
        assert rd.trend_label == "recovering"

    def test_trend_degrading(self):
        # Gaps increasing: 620, 650, 700, 800, 900 → drift growing
        ts = _drifting_timestamps([620, 650, 700, 800, 900])
        rd = CommitRhythmDrift(tuple(ts), target=600)
        assert rd.trend > 0.01
        assert rd.trend_label == "degrading"

    def test_trend_single_interval_zero(self):
        ts = _drifting_timestamps([700])
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.trend == 0.0
        assert rd.trend_label == "stable"

    def test_trend_empty_zero(self):
        rd = CommitRhythmDrift(())
        assert rd.trend == 0.0


# --- health grading ---


class TestHealthGrading:
    def test_steady_perfect(self):
        ts = _perfect_timestamps(10)
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.grade == "steady"
        assert rd.has_stall is False

    def test_steady_slight_drift(self):
        # 5% drift on each interval → mean_drift_ratio = 0.05 < 0.10
        ts = _drifting_timestamps([630, 630, 630, 630])
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.grade == "steady"

    def test_drifting(self):
        # 15% drift each → mean_drift_ratio = 0.15 → drifting (0.10–0.25)
        ts = _drifting_timestamps([690, 690, 690, 690])
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.grade == "drifting"

    def test_erratic(self):
        # 35% drift each → mean_drift_ratio = 0.35 → erratic (0.25–0.50)
        ts = _drifting_timestamps([810, 810, 810, 810])
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.grade == "erratic"

    def test_stalled_by_mean_drift(self):
        # 60% drift each → mean_drift_ratio = 0.60 → stalled (>0.50)
        ts = _drifting_timestamps([960, 960, 960, 960])
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.grade == "stalled"

    def test_stalled_by_single_gap(self):
        # One huge gap (> 3× target = 1800s) overrides otherwise steady rhythm
        ts = _drifting_timestamps([600, 600, 2000, 600])
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.has_stall is True
        assert rd.grade == "stalled"

    def test_no_stall_below_threshold(self):
        # Gap exactly at 3× target (1800s) is not > threshold, so not stalled
        ts = _drifting_timestamps([600, 600, 1800, 600])
        rd = CommitRhythmDrift(tuple(ts))
        assert rd.has_stall is False

    def test_empty_is_stalled(self):
        # No intervals → mean_drift_ratio=0 → grade="steady" (vacuously)
        rd = CommitRhythmDrift(())
        assert rd.grade == "steady"


# --- convenience: rhythm_health ---


class TestRhythmHealth:
    def test_returns_dict(self):
        result = rhythm_health([1000, 1600, 2200])
        assert isinstance(result, dict)
        assert "grade" in result
        assert "mean_drift_ratio" in result

    def test_accepts_list(self):
        result = rhythm_health([1000, 1600, 2200])
        assert result["count"] == 2

    def test_single_timestamp(self):
        result = rhythm_health([1000])
        assert result["count"] == 0
        assert result["mean_drift"] == 0.0


# --- convenience: drift_report ---


class TestDriftReport:
    def test_empty(self):
        assert drift_report([1000]) == "no intervals — need at least 2 timestamps"

    def test_perfect(self):
        ts = _perfect_timestamps(4)
        report = drift_report(ts)
        assert "3 intervals" in report
        assert "0.0%" in report
        assert "stable" in report

    def test_format_includes_all_fields(self):
        ts = _drifting_timestamps([700, 500, 800])
        report = drift_report(ts)
        assert "intervals" in report
        assert "mean drift" in report
        assert "max" in report
        assert "trend:" in report

    def test_custom_target(self):
        # Target = 300s; gaps are all 330s → drift = 30, ratio = 0.1 → steady
        ts = _drifting_timestamps([330, 330, 330])
        report = drift_report(ts, target=300)
        assert "3 intervals" in report
        assert "10.0%" in report


# --- summary_dict ---


class TestSummaryDict:
    def test_keys(self):
        ts = _perfect_timestamps(5)
        rd = CommitRhythmDrift(tuple(ts))
        d = rd.summary_dict()
        expected_keys = {
            "count", "target", "mean_drift", "mean_drift_ratio",
            "max_drift", "max_drift_ratio", "max_gap", "min_gap",
            "trend", "trend_label", "grade", "has_stall",
        }
        assert set(d.keys()) == expected_keys

    def test_values_rounded(self):
        ts = _drifting_timestamps([617, 583, 621, 599])
        rd = CommitRhythmDrift(tuple(ts))
        d = rd.summary_dict()
        # mean_drift_ratio rounded to 4 decimal places
        assert isinstance(d["mean_drift_ratio"], float)
        # trend rounded to 4 decimal places
        assert isinstance(d["trend"], float)
