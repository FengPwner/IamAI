"""Tests for iamai.availability_trend — availability trend tracker.

covers:
  - Reading dataclass (regime classification, boundary values)
  - AvailabilityTrend.record / record_many / count / latest
  - rolling_avg (normal, empty, single, window clamping)
  - direction (improving, stable, degrading, edge cases)
  - regime / regime_changed (transitions, same-regime, single reading)
  - min/max availability
  - worst_streak (consecutive below threshold)
  - total_loss
  - report (empty, normal, regime change)
"""

import pytest

from iamai.availability_trend import (
    AvailabilityTrend,
    Reading,
    HEALTHY_THRESHOLD,
    STRAINED_THRESHOLD,
)


# ─── Reading ────────────────────────────────────────────────────────


class TestReading:
    def test_regime_healthy(self):
        r = Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=90.0)
        assert r.regime() == "healthy"

    def test_regime_healthy_boundary(self):
        r = Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=85.0)
        assert r.regime() == "healthy"

    def test_regime_strained(self):
        r = Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=72.0)
        assert r.regime() == "strained"

    def test_regime_strained_lower_boundary(self):
        r = Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=60.0)
        assert r.regime() == "strained"

    def test_regime_critical(self):
        r = Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=59.9)
        assert r.regime() == "critical"

    def test_regime_zero(self):
        r = Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=0.0)
        assert r.regime() == "critical"

    def test_regime_perfect(self):
        r = Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=100.0)
        assert r.regime() == "healthy"

    def test_optional_fields_default(self):
        r = Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=75.0)
        assert r.stall_count == 0
        assert r.total_stall_seconds == 0
        assert r.estimated_loss == 0
        assert r.observed_strokes == 0

    def test_optional_fields_set(self):
        r = Reading(
            at="2026-10-19T12:00:00+08:00",
            visit=233,
            availability_pct=60.5,
            stall_count=7,
            total_stall_seconds=9736,
            estimated_loss=261,
            observed_strokes=400,
        )
        assert r.stall_count == 7
        assert r.estimated_loss == 261


# ─── AvailabilityTrend: record / count / latest ─────────────────────


class TestTrendRecord:
    def test_empty(self):
        t = AvailabilityTrend()
        assert t.count() == 0
        assert t.latest() is None

    def test_record_single(self):
        t = AvailabilityTrend()
        r = Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=80.0)
        t.record(r)
        assert t.count() == 1
        assert t.latest() is r

    def test_record_many(self):
        t = AvailabilityTrend()
        readings = [
            Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=80.0),
            Reading(at="2026-10-19T15:00:00+08:00", visit=2, availability_pct=70.0),
        ]
        t.record_many(readings)
        assert t.count() == 2
        assert t.latest().visit == 2

    def test_readings_returns_copy(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=80.0))
        r = t.readings
        r.clear()
        assert t.count() == 1  # original unaffected


# ─── rolling_avg ─────────────────────────────────────────────────────


class TestRollingAvg:
    def test_empty(self):
        t = AvailabilityTrend()
        assert t.rolling_avg() == 0.0

    def test_single(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=75.0))
        assert t.rolling_avg() == 75.0

    def test_multiple_within_window(self):
        t = AvailabilityTrend(window=5)
        for i, pct in enumerate([90.0, 80.0, 70.0]):
            t.record(Reading(at=f"2026-10-19T{12+i}:00:00+08:00", visit=i, availability_pct=pct))
        assert t.rolling_avg() == pytest.approx(80.0)

    def test_window_clamping(self):
        t = AvailabilityTrend(window=2)
        for i, pct in enumerate([10.0, 90.0, 80.0]):
            t.record(Reading(at=f"2026-10-19T{12+i}:00:00+08:00", visit=i, availability_pct=pct))
        # window=2, so only last 2 readings (90, 80)
        assert t.rolling_avg() == pytest.approx(85.0)

    def test_explicit_n(self):
        t = AvailabilityTrend(window=10)
        for i, pct in enumerate([50.0, 60.0, 70.0, 80.0, 90.0]):
            t.record(Reading(at=f"2026-10-19T{12+i}:00:00+08:00", visit=i, availability_pct=pct))
        assert t.rolling_avg(n=3) == pytest.approx(80.0)  # last 3: 70, 80, 90

    def test_n_larger_than_count(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=60.0))
        t.record(Reading(at="2026-10-19T13:00:00+08:00", visit=2, availability_pct=70.0))
        assert t.rolling_avg(n=100) == pytest.approx(65.0)  # clamps to 2


# ─── direction ───────────────────────────────────────────────────────


class TestDirection:
    def test_empty(self):
        t = AvailabilityTrend()
        assert t.direction() == "stable"

    def test_single(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=70.0))
        assert t.direction() == "stable"

    def test_improving(self):
        t = AvailabilityTrend()
        # first half avg ~55, second half avg ~85 → delta +30 → improving
        for i, pct in enumerate([50.0, 60.0, 80.0, 90.0]):
            t.record(Reading(at=f"2026-10-19T{12+i}:00:00+08:00", visit=i, availability_pct=pct))
        assert t.direction() == "improving"

    def test_degrading(self):
        t = AvailabilityTrend()
        # first half avg ~85, second half avg ~55 → delta -30 → degrading
        for i, pct in enumerate([90.0, 80.0, 60.0, 50.0]):
            t.record(Reading(at=f"2026-10-19T{12+i}:00:00+08:00", visit=i, availability_pct=pct))
        assert t.direction() == "degrading"

    def test_stable(self):
        t = AvailabilityTrend()
        # all readings within 2pp of each other
        for i, pct in enumerate([70.0, 71.0, 69.0, 70.5]):
            t.record(Reading(at=f"2026-10-19T{12+i}:00:00+08:00", visit=i, availability_pct=pct))
        assert t.direction() == "stable"

    def test_two_readings_improving(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=50.0))
        t.record(Reading(at="2026-10-19T13:00:00+08:00", visit=2, availability_pct=60.0))
        assert t.direction() == "improving"

    def test_two_readings_degrading(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=80.0))
        t.record(Reading(at="2026-10-19T13:00:00+08:00", visit=2, availability_pct=70.0))
        assert t.direction() == "degrading"


# ─── regime / regime_changed ────────────────────────────────────────


class TestRegime:
    def test_no_readings(self):
        t = AvailabilityTrend()
        assert t.regime() == "unknown"

    def test_regime_healthy(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=92.0))
        assert t.regime() == "healthy"

    def test_regime_strained(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=65.0))
        assert t.regime() == "strained"

    def test_regime_critical(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=40.0))
        assert t.regime() == "critical"

    def test_regime_changed_healthy_to_strained(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=90.0))
        t.record(Reading(at="2026-10-19T13:00:00+08:00", visit=2, availability_pct=70.0))
        assert t.regime_changed() is True

    def test_regime_changed_strained_to_critical(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=65.0))
        t.record(Reading(at="2026-10-19T13:00:00+08:00", visit=2, availability_pct=50.0))
        assert t.regime_changed() is True

    def test_no_regime_change_same_regime(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=70.0))
        t.record(Reading(at="2026-10-19T13:00:00+08:00", visit=2, availability_pct=65.0))
        assert t.regime_changed() is False  # both strained

    def test_no_regime_change_single_reading(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=70.0))
        assert t.regime_changed() is False

    def test_no_regime_change_empty(self):
        t = AvailabilityTrend()
        assert t.regime_changed() is False


# ─── min / max availability ──────────────────────────────────────────


class TestMinMax:
    def test_empty(self):
        t = AvailabilityTrend()
        assert t.min_availability() == 0.0
        assert t.max_availability() == 0.0

    def test_min_max_basic(self):
        t = AvailabilityTrend()
        for i, pct in enumerate([70.0, 50.0, 90.0, 60.0]):
            t.record(Reading(at=f"2026-10-19T{12+i}:00:00+08:00", visit=i, availability_pct=pct))
        assert t.min_availability() == 50.0
        assert t.max_availability() == 90.0

    def test_min_max_windowed(self):
        t = AvailabilityTrend(window=2)
        for i, pct in enumerate([10.0, 70.0, 80.0, 60.0]):
            t.record(Reading(at=f"2026-10-19T{12+i}:00:00+08:00", visit=i, availability_pct=pct))
        # window=2: only last 2 (80, 60)
        assert t.min_availability() == 60.0
        assert t.max_availability() == 80.0

    def test_min_max_explicit_n(self):
        t = AvailabilityTrend()
        for i, pct in enumerate([10.0, 20.0, 90.0, 80.0]):
            t.record(Reading(at=f"2026-10-19T{12+i}:00:00+08:00", visit=i, availability_pct=pct))
        assert t.min_availability(n=2) == 80.0
        assert t.max_availability(n=2) == 90.0


# ─── worst_streak ────────────────────────────────────────────────────


class TestWorstStreak:
    def test_empty(self):
        t = AvailabilityTrend()
        assert t.worst_streak() == 0

    def test_all_healthy(self):
        t = AvailabilityTrend()
        for i, pct in enumerate([90.0, 88.0, 92.0]):
            t.record(Reading(at=f"2026-10-19T{12+i}:00:00+08:00", visit=i, availability_pct=pct))
        assert t.worst_streak() == 0

    def test_constrained_streak(self):
        t = AvailabilityTrend()
        # 3 below 60, then 1 above, then 2 below
        for i, pct in enumerate([55.0, 50.0, 45.0, 70.0, 58.0, 52.0]):
            t.record(Reading(at=f"2026-10-19T{12+i}:00:00+08:00", visit=i, availability_pct=pct))
        assert t.worst_streak() == 3

    def test_custom_threshold(self):
        t = AvailabilityTrend()
        for i, pct in enumerate([70.0, 65.0, 80.0, 72.0]):
            t.record(Reading(at=f"2026-10-19T{12+i}:00:00+08:00", visit=i, availability_pct=pct))
        # default threshold 60: all above → 0
        assert t.worst_streak() == 0
        # threshold 75: 70, 65, (80 breaks), 72 → streak of 2
        assert t.worst_streak(threshold=75.0) == 2

    def test_all_below(self):
        t = AvailabilityTrend()
        for i, pct in enumerate([50.0, 55.0, 40.0, 30.0]):
            t.record(Reading(at=f"2026-10-19T{12+i}:00:00+08:00", visit=i, availability_pct=pct))
        assert t.worst_streak() == 4


# ─── total_loss ──────────────────────────────────────────────────────


class TestTotalLoss:
    def test_empty(self):
        t = AvailabilityTrend()
        assert t.total_loss() == 0

    def test_basic(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=70.0, estimated_loss=100))
        t.record(Reading(at="2026-10-19T13:00:00+08:00", visit=2, availability_pct=65.0, estimated_loss=150))
        assert t.total_loss() == 250

    def test_windowed(self):
        t = AvailabilityTrend(window=1)
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=70.0, estimated_loss=100))
        t.record(Reading(at="2026-10-19T13:00:00+08:00", visit=2, availability_pct=65.0, estimated_loss=200))
        assert t.total_loss() == 200  # only last 1


# ─── report ──────────────────────────────────────────────────────────


class TestReport:
    def test_empty(self):
        t = AvailabilityTrend()
        report = t.report()
        assert "no readings" in report

    def test_normal_report(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=232, availability_pct=65.0, estimated_loss=150))
        t.record(Reading(at="2026-10-19T19:00:00+08:00", visit=233, availability_pct=60.5, estimated_loss=261))
        report = t.report()
        assert "availability trend" in report
        assert "60.5%" in report
        assert "visit 233" in report
        assert "strained" in report
        assert "411 strokes" in report  # 150 + 261

    def test_regime_change_report(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=100, availability_pct=90.0))
        t.record(Reading(at="2026-10-19T13:00:00+08:00", visit=101, availability_pct=55.0))
        report = t.report()
        assert "CHANGED" in report
        assert "regime shift" in report
        assert "healthy → critical" in report

    def test_report_no_regime_change(self):
        t = AvailabilityTrend()
        t.record(Reading(at="2026-10-19T12:00:00+08:00", visit=1, availability_pct=70.0))
        t.report()
        report = t.report()
        assert "CHANGED" not in report
