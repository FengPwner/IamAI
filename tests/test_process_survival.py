"""Tests for iamai.process_survival — process survival tracking."""

from datetime import datetime

import pytest
from iamai.process_survival import (
    SurvivalInterval,
    SurvivalTracker,
    _fmt_duration,
    survival_summary,
)


# ---------------------------------------------------------------------------
# SurvivalInterval
# ---------------------------------------------------------------------------

class TestSurvivalInterval:
    def test_duration_basic(self):
        iv = SurvivalInterval(
            restart_at=_dt("2026-11-03T06:00:00+08:00"),
            death_at=_dt("2026-11-03T09:30:00+08:00"),
        )
        assert iv.duration_seconds == 3.5 * 3600  # 12600

    def test_duration_zero(self):
        iv = SurvivalInterval(
            restart_at=_dt("2026-11-03T06:00:00+08:00"),
            death_at=_dt("2026-11-03T06:00:00+08:00"),
        )
        assert iv.duration_seconds == 0.0

    def test_duration_negative_clamped(self):
        """Death before restart should clamp to 0."""
        iv = SurvivalInterval(
            restart_at=_dt("2026-11-03T09:00:00+08:00"),
            death_at=_dt("2026-11-03T06:00:00+08:00"),
        )
        assert iv.duration_seconds == 0.0


# ---------------------------------------------------------------------------
# SurvivalTracker — recording
# ---------------------------------------------------------------------------

class TestTrackerRecording:
    def test_record_interval_from_strings(self):
        tracker = SurvivalTracker()
        iv = tracker.record_interval(
            "2026-11-03T06:00:00+08:00",
            "2026-11-03T09:00:00+08:00",
        )
        assert iv.duration_seconds == 3 * 3600
        assert tracker.count() == 1

    def test_record_interval_from_datetime(self):
        tracker = SurvivalTracker()
        iv = tracker.record_interval(
            _dt("2026-11-03T06:00:00+08:00"),
            _dt("2026-11-03T12:00:00+08:00"),
        )
        assert iv.duration_seconds == 6 * 3600
        assert tracker.count() == 1

    def test_multiple_intervals(self):
        tracker = _make_tracker_3()
        assert tracker.count() == 3

    def test_record_restart_and_death_helpers(self):
        tracker = SurvivalTracker()
        restart = tracker.record_restart("2026-11-03T06:00:00+08:00")
        death = tracker.record_death("2026-11-03T08:00:00+08:00")
        assert restart.hour == 6
        assert death.hour == 8

    def test_utc_timezone_handling(self):
        tracker = SurvivalTracker()
        iv = tracker.record_interval(
            "2026-11-03T00:00:00Z",
            "2026-11-03T02:00:00Z",
        )
        assert iv.duration_seconds == 2 * 3600

    def test_naive_datetime_gets_utc(self):
        """Naive datetime strings should be treated as UTC."""
        tracker = SurvivalTracker()
        iv = tracker.record_interval(
            "2026-11-03T00:00:00",
            "2026-11-03T03:00:00",
        )
        assert iv.duration_seconds == 3 * 3600


# ---------------------------------------------------------------------------
# SurvivalTracker — statistics
# ---------------------------------------------------------------------------

class TestTrackerStatistics:
    def test_durations(self):
        tracker = _make_tracker_3()
        durs = tracker.durations()
        assert len(durs) == 3
        assert durs[0] == 3 * 3600
        assert durs[1] == 6 * 3600
        assert durs[2] == 1 * 3600

    def test_mean_survival(self):
        tracker = _make_tracker_3()
        mean = tracker.mean_survival()
        expected = (3 * 3600 + 6 * 3600 + 1 * 3600) / 3
        assert mean == pytest.approx(expected)

    def test_median_survival(self):
        tracker = _make_tracker_3()
        median = tracker.median_survival()
        # sorted: 3600, 10800, 21600 → median = 10800
        assert median == 3 * 3600

    def test_min_survival(self):
        tracker = _make_tracker_3()
        assert tracker.min_survival() == 1 * 3600

    def test_max_survival(self):
        tracker = _make_tracker_3()
        assert tracker.max_survival() == 6 * 3600

    def test_all_none_when_empty(self):
        tracker = SurvivalTracker()
        assert tracker.mean_survival() is None
        assert tracker.median_survival() is None
        assert tracker.min_survival() is None
        assert tracker.max_survival() is None
        assert tracker.count() == 0

    def test_single_interval(self):
        tracker = SurvivalTracker()
        tracker.record_interval(
            "2026-11-03T06:00:00+08:00",
            "2026-11-03T07:00:00+08:00",
        )
        assert tracker.mean_survival() == 3600
        assert tracker.median_survival() == 3600
        assert tracker.min_survival() == 3600
        assert tracker.max_survival() == 3600


# ---------------------------------------------------------------------------
# SurvivalTracker — trend detection
# ---------------------------------------------------------------------------

class TestSurvivalTrend:
    def test_improving(self):
        tracker = SurvivalTracker()
        # First half: short survivals; second half: long survivals
        tracker.record_interval(
            "2026-11-01T06:00:00+08:00", "2026-11-01T06:30:00+08:00")  # 30min
        tracker.record_interval(
            "2026-11-01T07:00:00+08:00", "2026-11-01T08:00:00+08:00")  # 1h
        tracker.record_interval(
            "2026-11-01T10:00:00+08:00", "2026-11-01T18:00:00+08:00")  # 8h
        tracker.record_interval(
            "2026-11-02T06:00:00+08:00", "2026-11-02T20:00:00+08:00")  # 14h
        assert tracker.survival_trend() == "improving"

    def test_worsening(self):
        tracker = SurvivalTracker()
        # First half: long survivals; second half: short survivals
        tracker.record_interval(
            "2026-11-01T06:00:00+08:00", "2026-11-01T20:00:00+08:00")  # 14h
        tracker.record_interval(
            "2026-11-02T06:00:00+08:00", "2026-11-02T18:00:00+08:00")  # 12h
        tracker.record_interval(
            "2026-11-03T06:00:00+08:00", "2026-11-03T07:00:00+08:00")  # 1h
        tracker.record_interval(
            "2026-11-03T08:00:00+08:00", "2026-11-03T08:30:00+08:00")  # 30min
        assert tracker.survival_trend() == "worsening"

    def test_stable(self):
        tracker = SurvivalTracker()
        # All similar durations
        tracker.record_interval(
            "2026-11-01T06:00:00+08:00", "2026-11-01T12:00:00+08:00")  # 6h
        tracker.record_interval(
            "2026-11-01T18:00:00+08:00", "2026-11-02T00:00:00+08:00")  # 6h
        tracker.record_interval(
            "2026-11-02T06:00:00+08:00", "2026-11-02T12:00:00+08:00")  # 6h
        tracker.record_interval(
            "2026-11-02T18:00:00+08:00", "2026-11-03T00:00:00+08:00")  # 6h
        assert tracker.survival_trend() == "stable"

    def test_insufficient_data(self):
        tracker = SurvivalTracker()
        tracker.record_interval(
            "2026-11-01T06:00:00+08:00", "2026-11-01T12:00:00+08:00")
        assert tracker.survival_trend() == "insufficient_data"
        tracker.record_interval(
            "2026-11-01T18:00:00+08:00", "2026-11-02T00:00:00+08:00")
        assert tracker.survival_trend() == "insufficient_data"

    def test_improving_from_zero(self):
        tracker = SurvivalTracker()
        # First half: zero durations
        tracker.record_interval(
            "2026-11-01T06:00:00+08:00", "2026-11-01T06:00:00+08:00")
        tracker.record_interval(
            "2026-11-01T07:00:00+08:00", "2026-11-01T07:00:00+08:00")
        # Second half: positive durations
        tracker.record_interval(
            "2026-11-01T10:00:00+08:00", "2026-11-01T18:00:00+08:00")
        tracker.record_interval(
            "2026-11-02T06:00:00+08:00", "2026-11-02T20:00:00+08:00")
        assert tracker.survival_trend() == "improving"

    def test_stable_from_all_zero(self):
        tracker = SurvivalTracker()
        for _ in range(4):
            tracker.record_interval(
                "2026-11-01T06:00:00+08:00", "2026-11-01T06:00:00+08:00")
        assert tracker.survival_trend() == "stable"


# ---------------------------------------------------------------------------
# SurvivalTracker — fragility score
# ---------------------------------------------------------------------------

class TestFragilityScore:
    def test_empty_default(self):
        tracker = SurvivalTracker()
        assert tracker.fragility_score() == 0.5

    def test_all_long_survival(self):
        """All intervals > 1 hour → score 0.0."""
        tracker = SurvivalTracker()
        for day in range(1, 5):
            tracker.record_interval(
                f"2026-11-{day:02d}T06:00:00+08:00",
                f"2026-11-{day:02d}T12:00:00+08:00",
            )
        assert tracker.fragility_score() == 0.0

    def test_all_short_survival(self):
        """All intervals < 1 hour → score 1.0."""
        tracker = SurvivalTracker()
        for h in range(6, 10):
            tracker.record_interval(
                f"2026-11-01T{h:02d}:00:00+08:00",
                f"2026-11-01T{h:02d}:30:00+08:00",
            )
        assert tracker.fragility_score() == 1.0

    def test_mixed_survival(self):
        """Half short, half long → score ~0.5."""
        tracker = SurvivalTracker()
        # 2 short
        tracker.record_interval(
            "2026-11-01T06:00:00+08:00", "2026-11-01T06:30:00+08:00")
        tracker.record_interval(
            "2026-11-01T07:00:00+08:00", "2026-11-01T07:45:00+08:00")
        # 2 long
        tracker.record_interval(
            "2026-11-01T10:00:00+08:00", "2026-11-01T18:00:00+08:00")
        tracker.record_interval(
            "2026-11-02T06:00:00+08:00", "2026-11-02T20:00:00+08:00")
        assert tracker.fragility_score() == 0.5


# ---------------------------------------------------------------------------
# SurvivalTracker — fragility grade
# ---------------------------------------------------------------------------

class TestFragilityGrade:
    def test_robust(self):
        tracker = SurvivalTracker()
        for day in range(1, 6):
            tracker.record_interval(
                f"2026-11-{day:02d}T06:00:00+08:00",
                f"2026-11-{day:02d}T18:00:00+08:00",
            )
        assert tracker.fragility_grade() == "robust"

    def test_acceptable(self):
        tracker = SurvivalTracker()
        # 80% long, 20% short
        for day in range(1, 5):
            tracker.record_interval(
                f"2026-11-{day:02d}T06:00:00+08:00",
                f"2026-11-{day:02d}T12:00:00+08:00",
            )
        tracker.record_interval(
            "2026-11-05T06:00:00+08:00", "2026-11-05T06:30:00+08:00")
        assert tracker.fragility_grade() == "acceptable"

    def test_fragile(self):
        tracker = SurvivalTracker()
        # 50% short → should be fragile
        tracker.record_interval(
            "2026-11-01T06:00:00+08:00", "2026-11-01T06:30:00+08:00")
        tracker.record_interval(
            "2026-11-01T10:00:00+08:00", "2026-11-01T18:00:00+08:00")
        assert tracker.fragility_grade() == "fragile"

    def test_critical(self):
        tracker = SurvivalTracker()
        for _ in range(5):
            tracker.record_interval(
                "2026-11-01T06:00:00+08:00", "2026-11-01T06:15:00+08:00")
        assert tracker.fragility_grade() == "critical"

    def test_empty_default_is_fragile(self):
        tracker = SurvivalTracker()
        # Default score 0.5 → fragile
        assert tracker.fragility_grade() == "fragile"


# ---------------------------------------------------------------------------
# SurvivalTracker — report
# ---------------------------------------------------------------------------

class TestReport:
    def test_empty_report(self):
        tracker = SurvivalTracker()
        assert tracker.report() == "no survival data recorded"

    def test_report_content(self):
        tracker = _make_tracker_3()
        report = tracker.report()
        assert "3 intervals" in report
        assert "mean:" in report
        assert "median:" in report
        assert "min:" in report
        assert "max:" in report
        assert "trend:" in report
        assert "fragility:" in report


# ---------------------------------------------------------------------------
# survival_summary
# ---------------------------------------------------------------------------

class TestSurvivalSummary:
    def test_summary_keys(self):
        tracker = _make_tracker_3()
        s = survival_summary(tracker)
        expected_keys = {
            "interval_count", "mean_seconds", "median_seconds",
            "min_seconds", "max_seconds", "trend",
            "fragility_score", "fragility_grade", "report",
        }
        assert set(s.keys()) == expected_keys

    def test_summary_values(self):
        tracker = _make_tracker_3()
        s = survival_summary(tracker)
        assert s["interval_count"] == 3
        assert s["mean_seconds"] is not None
        assert s["median_seconds"] is not None
        assert s["min_seconds"] == 1 * 3600
        assert s["max_seconds"] == 6 * 3600
        assert isinstance(s["fragility_score"], float)
        assert s["fragility_grade"] in ("robust", "acceptable", "fragile", "critical")
        assert isinstance(s["report"], str)

    def test_summary_empty(self):
        tracker = SurvivalTracker()
        s = survival_summary(tracker)
        assert s["interval_count"] == 0
        assert s["mean_seconds"] is None
        assert s["fragility_score"] == 0.5


# ---------------------------------------------------------------------------
# _fmt_duration
# ---------------------------------------------------------------------------

class TestFmtDuration:
    def test_none(self):
        assert _fmt_duration(None) == "N/A"

    def test_seconds(self):
        assert _fmt_duration(45) == "45s"

    def test_minutes(self):
        assert _fmt_duration(125) == "2m5s"

    def test_hours(self):
        assert _fmt_duration(7380) == "2h3m"

    def test_zero(self):
        assert _fmt_duration(0) == "0s"

    def test_exact_hour(self):
        assert _fmt_duration(3600) == "1h0m"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _make_tracker_3() -> SurvivalTracker:
    """Create a tracker with 3 intervals: 3h, 6h, 1h."""
    tracker = SurvivalTracker()
    tracker.record_interval(
        "2026-11-01T06:00:00+08:00", "2026-11-01T09:00:00+08:00")  # 3h
    tracker.record_interval(
        "2026-11-01T12:00:00+08:00", "2026-11-01T18:00:00+08:00")  # 6h
    tracker.record_interval(
        "2026-11-02T06:00:00+08:00", "2026-11-02T07:00:00+08:00")  # 1h
    return tracker
