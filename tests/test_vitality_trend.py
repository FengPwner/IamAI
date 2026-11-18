"""Tests for iamai.vitality_trend — VitalityTrend tracker."""

import math
import pytest
from datetime import datetime, timezone

from iamai.vitality_trend import (
    VitalityTrend,
    VitalitySnapshot,
    TrendReport,
    _parse_ts,
    _linear_fit,
    _classify_direction,
    _IMPROVING_THRESHOLD,
    _DECLINING_THRESHOLD,
)


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTs:
    def test_iso_basic(self):
        result = _parse_ts("2026-11-19T04:00:00+00:00")
        assert result > 0

    def test_z_suffix(self):
        result = _parse_ts("2026-11-19T04:00:00Z")
        assert result > 0

    def test_empty(self):
        assert _parse_ts("") == 0.0

    def test_invalid(self):
        assert _parse_ts("not-a-date") == 0.0

    def test_none(self):
        assert _parse_ts(None) == 0.0


# ---------------------------------------------------------------------------
# _linear_fit
# ---------------------------------------------------------------------------

class TestLinearFit:
    def test_empty(self):
        slope, intercept = _linear_fit([])
        assert slope == 0.0
        assert intercept == 0.0

    def test_single_point(self):
        slope, intercept = _linear_fit([(1.0, 5.0)])
        assert slope == 0.0
        assert intercept == 5.0

    def test_perfect_line(self):
        points = [(0, 0), (1, 2), (2, 4), (3, 6)]
        slope, intercept = _linear_fit(points)
        assert abs(slope - 2.0) < 1e-9
        assert abs(intercept) < 1e-9

    def test_horizontal(self):
        points = [(0, 5), (1, 5), (2, 5)]
        slope, intercept = _linear_fit(points)
        assert abs(slope) < 1e-9
        assert abs(intercept - 5.0) < 1e-9

    def test_negative_slope(self):
        points = [(0, 10), (1, 8), (2, 6), (3, 4)]
        slope, intercept = _linear_fit(points)
        assert abs(slope - (-2.0)) < 1e-9
        assert abs(intercept - 10.0) < 1e-9

    def test_noisy_data(self):
        points = [(0, 50), (1, 52), (2, 48), (3, 51), (4, 49)]
        slope, intercept = _linear_fit(points)
        assert abs(slope) < 1.0  # roughly flat

    def test_same_x_values(self):
        # All x-values identical → slope should be 0
        points = [(5, 10), (5, 20), (5, 30)]
        slope, intercept = _linear_fit(points)
        assert slope == 0.0
        assert abs(intercept - 20.0) < 1e-9


# ---------------------------------------------------------------------------
# _classify_direction
# ---------------------------------------------------------------------------

class TestClassifyDirection:
    def test_improving(self):
        assert _classify_direction(5.0) == "improving"
        assert _classify_direction(_IMPROVING_THRESHOLD + 0.01) == "improving"

    def test_declining(self):
        assert _classify_direction(-5.0) == "declining"
        assert _classify_direction(_DECLINING_THRESHOLD - 0.01) == "declining"

    def test_stable(self):
        assert _classify_direction(0.0) == "stable"
        assert _classify_direction(1.0) == "stable"
        assert _classify_direction(-1.0) == "stable"
        assert _classify_direction(_IMPROVING_THRESHOLD) == "stable"
        assert _classify_direction(_DECLINING_THRESHOLD) == "stable"


# ---------------------------------------------------------------------------
# VitalityTrend — construction
# ---------------------------------------------------------------------------

class TestVitalityTrendInit:
    def test_default_window(self):
        t = VitalityTrend()
        assert t.window == 20

    def test_custom_window(self):
        t = VitalityTrend(window=5)
        assert t.window == 5

    def test_window_too_small(self):
        with pytest.raises(ValueError):
            VitalityTrend(window=1)

    def test_window_zero(self):
        with pytest.raises(ValueError):
            VitalityTrend(window=0)

    def test_empty_snapshots(self):
        t = VitalityTrend()
        assert t.snapshots == []


# ---------------------------------------------------------------------------
# VitalityTrend — add
# ---------------------------------------------------------------------------

class TestVitalityTrendAdd:
    def test_add_with_timestamp(self):
        t = VitalityTrend()
        snap = t.add(75.0, at="2026-11-19T04:00:00Z")
        assert isinstance(snap, VitalitySnapshot)
        assert snap.score == 75.0
        assert snap.epoch > 0

    def test_add_without_timestamp(self):
        t = VitalityTrend()
        snap = t.add(80.0)
        assert snap.score == 80.0
        assert snap.epoch > 0

    def test_clamp_above(self):
        t = VitalityTrend()
        snap = t.add(150.0, at="2026-11-19T04:00:00Z")
        assert snap.score == 100.0

    def test_clamp_below(self):
        t = VitalityTrend()
        snap = t.add(-20.0, at="2026-11-19T04:00:00Z")
        assert snap.score == 0.0

    def test_multiple_adds(self):
        t = VitalityTrend()
        t.add(70.0, at="2026-11-19T04:00:00Z")
        t.add(72.0, at="2026-11-19T04:10:00Z")
        t.add(74.0, at="2026-11-19T04:20:00Z")
        assert len(t.snapshots) == 3

    def test_snapshot_to_dict(self):
        t = VitalityTrend()
        snap = t.add(85.0, at="2026-11-19T04:00:00Z")
        d = snap.to_dict()
        assert "epoch" in d
        assert "score" in d
        assert d["score"] == 85.0


# ---------------------------------------------------------------------------
# VitalityTrend — assess with few snapshots
# ---------------------------------------------------------------------------

class TestAssessEdgeCases:
    def test_no_snapshots(self):
        t = VitalityTrend()
        report = t.assess()
        assert report.direction == "stable"
        assert report.velocity == 0.0
        assert report.forecast == 0.0
        assert report.n_snapshots == 0

    def test_single_snapshot(self):
        t = VitalityTrend()
        t.add(75.0, at="2026-11-19T04:00:00Z")
        report = t.assess()
        assert report.direction == "stable"
        assert report.velocity == 0.0
        assert report.forecast == 75.0
        assert report.n_snapshots == 1

    def test_two_snapshots_improving(self):
        t = VitalityTrend()
        # 70 → 85 in 1 hour = +15 pts/hr → improving
        t.add(70.0, at="2026-11-19T03:00:00Z")
        t.add(85.0, at="2026-11-19T04:00:00Z")
        report = t.assess()
        assert report.direction == "improving"
        assert report.velocity > 10.0

    def test_two_snapshots_declining(self):
        t = VitalityTrend()
        # 90 → 60 in 1 hour = -30 pts/hr → declining
        t.add(90.0, at="2026-11-19T03:00:00Z")
        t.add(60.0, at="2026-11-19T04:00:00Z")
        report = t.assess()
        assert report.direction == "declining"
        assert report.velocity < -10.0


# ---------------------------------------------------------------------------
# VitalityTrend — assess with trends
# ---------------------------------------------------------------------------

class TestAssessTrends:
    @staticmethod
    def _make_improving_trend() -> VitalityTrend:
        """5 snapshots over 4 hours, steadily increasing."""
        t = VitalityTrend()
        base = "2026-11-19T0{}:00:00Z"
        for i, score in enumerate([50, 58, 65, 72, 80]):
            t.add(float(score), at=base.format(i))
        return t

    @staticmethod
    def _make_declining_trend() -> VitalityTrend:
        """5 snapshots over 4 hours, steadily decreasing."""
        t = VitalityTrend()
        base = "2026-11-19T0{}:00:00Z"
        for i, score in enumerate([90, 80, 68, 55, 40]):
            t.add(float(score), at=base.format(i))
        return t

    @staticmethod
    def _make_stable_trend() -> VitalityTrend:
        """5 snapshots over 4 hours, hovering around 70."""
        t = VitalityTrend()
        base = "2026-11-19T0{}:00:00Z"
        for i, score in enumerate([70, 71, 69, 70, 71]):
            t.add(float(score), at=base.format(i))
        return t

    def test_improving_direction(self):
        report = self._make_improving_trend().assess()
        assert report.direction == "improving"
        assert report.velocity > _IMPROVING_THRESHOLD

    def test_declining_direction(self):
        report = self._make_declining_trend().assess()
        assert report.direction == "declining"
        assert report.velocity < _DECLINING_THRESHOLD

    def test_stable_direction(self):
        report = self._make_stable_trend().assess()
        assert report.direction == "stable"
        assert abs(report.velocity) <= _IMPROVING_THRESHOLD

    def test_forecast_within_bounds(self):
        report = self._make_improving_trend().assess()
        assert 0.0 <= report.forecast <= 100.0

    def test_forecast_clamped_above(self):
        """Forecast should be clamped to 100 even if trend overshoots."""
        t = VitalityTrend()
        t.add(90.0, at="2026-11-19T00:00:00Z")
        t.add(95.0, at="2026-11-19T01:00:00Z")
        t.add(99.0, at="2026-11-19T02:00:00Z")
        report = t.assess()
        assert report.forecast <= 100.0

    def test_n_snapshots(self):
        report = self._make_improving_trend().assess()
        assert report.n_snapshots == 5


# ---------------------------------------------------------------------------
# Window statistics
# ---------------------------------------------------------------------------

class TestWindowStats:
    def test_basic_stats(self):
        t = VitalityTrend()
        base = "2026-11-19T0{}:00:00Z"
        scores = [60, 70, 80, 90, 100]
        for i, s in enumerate(scores):
            t.add(float(s), at=base.format(i))
        report = t.assess()
        assert report.window_min == 60.0
        assert report.window_max == 100.0
        assert abs(report.window_mean - 80.0) < 1e-9
        assert report.window_std > 0.0

    def test_identical_scores_std_zero(self):
        t = VitalityTrend()
        base = "2026-11-19T0{}:00:00Z"
        for i in range(5):
            t.add(70.0, at=base.format(i))
        report = t.assess()
        assert report.window_std == 0.0
        assert report.window_min == 70.0
        assert report.window_max == 70.0
        assert report.window_mean == 70.0

    def test_window_truncation(self):
        """Only the trailing `window` snapshots are used."""
        t = VitalityTrend(window=3)
        base = "2026-11-19T0{}:00:00Z"
        # Add 5 scores: [10, 20, 80, 85, 90]
        for i, s in enumerate([10, 20, 80, 85, 90]):
            t.add(float(s), at=base.format(i))
        report = t.assess()
        # Only last 3: [80, 85, 90]
        assert report.n_snapshots == 3
        assert report.window_min == 80.0
        assert report.window_max == 90.0
        assert report.direction == "improving"


# ---------------------------------------------------------------------------
# Inflection points
# ---------------------------------------------------------------------------

class TestInflectionPoints:
    def test_no_inflection(self):
        """Steady improvement — no direction flips."""
        t = VitalityTrend()
        base = "2026-11-19T0{}:00:00Z"
        for i, s in enumerate([50, 55, 60, 65, 70]):
            t.add(float(s), at=base.format(i))
        report = t.assess()
        assert report.inflection_points == []

    def test_one_inflection(self):
        """Rise then fall — one direction flip."""
        t = VitalityTrend()
        base = "2026-11-19T0{}:00:00Z"
        # 50 → 80 (improving) → 60 → 40 (declining)
        for i, s in enumerate([50, 65, 80, 60, 40]):
            t.add(float(s), at=base.format(i))
        report = t.assess()
        # Should detect at least one inflection
        assert len(report.inflection_points) >= 1

    def test_inflection_timestamps_are_epochs(self):
        t = VitalityTrend()
        base = "2026-11-19T0{}:00:00Z"
        for i, s in enumerate([50, 65, 80, 60, 40]):
            t.add(float(s), at=base.format(i))
        report = t.assess()
        for ts in report.inflection_points:
            assert ts > 0


# ---------------------------------------------------------------------------
# TrendReport — to_dict
# ---------------------------------------------------------------------------

class TestTrendReportDict:
    def test_keys(self):
        t = VitalityTrend()
        t.add(70.0, at="2026-11-19T03:00:00Z")
        t.add(75.0, at="2026-11-19T04:00:00Z")
        report = t.assess()
        d = report.to_dict()
        assert "direction" in d
        assert "velocity_pts_per_hour" in d
        assert "forecast" in d
        assert "inflection_points" in d
        assert "window" in d
        assert "n_snapshots" in d
        assert "min" in d["window"]
        assert "max" in d["window"]
        assert "mean" in d["window"]
        assert "std" in d["window"]

    def test_values_rounded(self):
        t = VitalityTrend()
        t.add(70.12345, at="2026-11-19T03:00:00Z")
        t.add(75.67890, at="2026-11-19T04:00:00Z")
        report = t.assess()
        d = report.to_dict()
        # velocity should be rounded to 4 decimals
        assert isinstance(d["velocity_pts_per_hour"], float)
        assert isinstance(d["forecast"], float)


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------

class TestClear:
    def test_clear_removes_snapshots(self):
        t = VitalityTrend()
        t.add(70.0, at="2026-11-19T03:00:00Z")
        t.add(80.0, at="2026-11-19T04:00:00Z")
        assert len(t.snapshots) == 2
        t.clear()
        assert len(t.snapshots) == 0

    def test_clear_resets_assess(self):
        t = VitalityTrend()
        t.add(50.0, at="2026-11-19T03:00:00Z")
        t.add(90.0, at="2026-11-19T04:00:00Z")
        t.clear()
        report = t.assess()
        assert report.direction == "stable"
        assert report.n_snapshots == 0


# ---------------------------------------------------------------------------
# Stress / edge cases
# ---------------------------------------------------------------------------

class TestStressAndEdgeCases:
    def test_many_snapshots(self):
        """100 snapshots should work fine."""
        t = VitalityTrend()
        for i in range(100):
            hour = i // 60
            minute = i % 60
            ts = f"2026-11-19T{hour:02d}:{minute:02d}:00Z"
            t.add(50.0 + i * 0.3, at=ts)
        report = t.assess()
        assert report.n_snapshots == t.window  # capped at window
        assert report.direction in ("improving", "stable", "declining")

    def test_zero_interval(self):
        """Two snapshots at the same timestamp."""
        t = VitalityTrend()
        t.add(50.0, at="2026-11-19T04:00:00Z")
        t.add(80.0, at="2026-11-19T04:00:00Z")
        report = t.assess()
        # slope should be 0 because all x values are the same
        assert report.slope_raw == 0.0
        assert report.direction == "stable"

    def test_very_small_window(self):
        t = VitalityTrend(window=2)
        t.add(50.0, at="2026-11-19T03:00:00Z")
        t.add(90.0, at="2026-11-19T04:00:00Z")
        report = t.assess()
        assert report.n_snapshots == 2
        assert report.direction == "improving"

    def test_score_boundary_zero(self):
        t = VitalityTrend()
        snap = t.add(0.0, at="2026-11-19T04:00:00Z")
        assert snap.score == 0.0

    def test_score_boundary_hundred(self):
        t = VitalityTrend()
        snap = t.add(100.0, at="2026-11-19T04:00:00Z")
        assert snap.score == 100.0

    def test_snapshots_returns_copy(self):
        """Mutating returned list should not affect internal state."""
        t = VitalityTrend()
        t.add(50.0, at="2026-11-19T04:00:00Z")
        snaps = t.snapshots
        snaps.clear()
        assert len(t.snapshots) == 1
