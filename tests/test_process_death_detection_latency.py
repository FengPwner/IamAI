"""tests for process_death_detection_latency module — 45 tests."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import pytest
from datetime import datetime, timedelta, timezone

from process_death_detection_latency import (
    DeathEvent,
    DetectionLatency,
    DeathDetectionReport,
    measure_latency,
    build_report,
    report_to_text,
    DEFAULT_CHECK_INTERVAL_MIN,
)


# ============================================================
# helpers
# ============================================================

def _dt(minutes_from_now: float = 0, base: datetime = None) -> datetime:
    """create a timezone-aware datetime offset from base."""
    if base is None:
        base = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(minutes=minutes_from_now)


def _make_event(
    died_min: float = 0,
    detected_min: float = 5,
    restart_min: float = None,
    process: str = "writer",
    pid: int = 1000,
) -> DeathEvent:
    base = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
    restart_at = _dt(restart_min, base) if restart_min is not None else None
    return DeathEvent(
        process=process,
        pid=pid,
        died_at=_dt(died_min, base),
        detected_at=_dt(detected_min, base),
        restart_at=restart_at,
    )


# ============================================================
# DeathEvent
# ============================================================

class TestDeathEvent:
    def test_basic_fields(self):
        e = _make_event(died_min=0, detected_min=5, restart_min=7)
        assert e.process == "writer"
        assert e.pid == 1000
        assert e.died_at < e.detected_at < e.restart_at

    def test_no_restart(self):
        e = _make_event(died_min=0, detected_min=5)
        assert e.restart_at is None

    def test_frozen(self):
        e = _make_event()
        with pytest.raises(AttributeError):
            e.process = "batch"

    def test_different_process(self):
        e = _make_event(process="batch", pid=2000)
        assert e.process == "batch"
        assert e.pid == 2000

    def test_custom_pid(self):
        e = _make_event(pid=99999)
        assert e.pid == 99999


# ============================================================
# DetectionLatency
# ============================================================

class TestDetectionLatency:
    def test_within_budget_true(self):
        lat = measure_latency(_make_event(died_min=0, detected_min=3))
        assert lat.within_budget()  # 3 min < 5 min budget

    def test_within_budget_false(self):
        lat = measure_latency(_make_event(died_min=0, detected_min=8))
        assert not lat.within_budget()  # 8 min > 5 min budget

    def test_within_budget_boundary(self):
        lat = measure_latency(_make_event(died_min=0, detected_min=5))
        assert lat.within_budget()  # exactly at budget

    def test_efficiency_instant(self):
        lat = measure_latency(_make_event(died_min=0, detected_min=0))
        assert lat.efficiency() == 1.0

    def test_efficiency_full_interval(self):
        lat = measure_latency(_make_event(died_min=0, detected_min=10))
        assert lat.efficiency() == 0.0

    def test_efficiency_half(self):
        lat = measure_latency(_make_event(died_min=0, detected_min=5))
        assert 0.4 < lat.efficiency() < 0.6

    def test_efficiency_clamped_above(self):
        """negative gap shouldn't happen but clamp to [0,1]."""
        lat = DetectionLatency(
            event=_make_event(),
            detection_gap_sec=-10,
        )
        assert lat.efficiency() == 1.0

    def test_efficiency_clamped_below(self):
        lat = DetectionLatency(
            event=_make_event(),
            detection_gap_sec=9999,
        )
        assert lat.efficiency() == 0.0

    def test_custom_interval(self):
        lat = measure_latency(_make_event(died_min=0, detected_min=3))
        assert lat.within_budget(check_interval_min=6)   # 3 < 3 budget? no, 3 = 3
        assert lat.within_budget(check_interval_min=6)   # budget = 3 min, gap = 3 min
        assert not lat.within_budget(check_interval_min=4)  # budget = 2 min, gap = 3 min

    def test_restart_gap_present(self):
        lat = measure_latency(_make_event(died_min=0, detected_min=5, restart_min=7))
        assert lat.restart_gap_sec == 420.0  # 7 minutes

    def test_restart_gap_absent(self):
        lat = measure_latency(_make_event(died_min=0, detected_min=5))
        assert lat.restart_gap_sec is None

    def test_detection_gap_sec(self):
        lat = measure_latency(_make_event(died_min=0, detected_min=4))
        assert lat.detection_gap_sec == 240.0


# ============================================================
# measure_latency
# ============================================================

class TestMeasureLatency:
    def test_basic(self):
        event = _make_event(died_min=0, detected_min=3, restart_min=5)
        lat = measure_latency(event)
        assert lat.event is event
        assert lat.detection_gap_sec == 180.0
        assert lat.restart_gap_sec == 300.0

    def test_negative_gap_clamped(self):
        """if detected_before died (clock skew), clamp to 0."""
        event = _make_event(died_min=10, detected_min=0)
        lat = measure_latency(event)
        assert lat.detection_gap_sec == 0.0

    def test_no_restart(self):
        event = _make_event(died_min=0, detected_min=5)
        lat = measure_latency(event)
        assert lat.restart_gap_sec is None
        assert lat.total_downtime_sec is None


# ============================================================
# DeathDetectionReport
# ============================================================

class TestDeathDetectionReport:
    def test_empty_report(self):
        report = build_report([])
        assert report.count == 0
        assert report.mean_detection_sec == 0.0
        assert report.max_detection_sec == 0.0
        assert report.mean_efficiency == 0.0
        assert report.budget_compliance == 1.0  # vacuously true
        assert report.verdict() == "no_data"

    def test_single_event(self):
        events = [_make_event(died_min=0, detected_min=3)]
        report = build_report(events)
        assert report.count == 1
        assert report.mean_detection_sec == 180.0
        assert report.max_detection_sec == 180.0

    def test_multiple_events(self):
        events = [
            _make_event(died_min=0, detected_min=2, pid=1),
            _make_event(died_min=10, detected_min=14, pid=2),
            _make_event(died_min=20, detected_min=28, pid=3),
        ]
        report = build_report(events)
        assert report.count == 3
        assert report.max_detection_sec == 480.0  # 8 min
        expected_mean = (120 + 240 + 480) / 3
        assert abs(report.mean_detection_sec - expected_mean) < 0.1

    def test_budget_compliance_all_good(self):
        events = [
            _make_event(died_min=0, detected_min=2, pid=1),
            _make_event(died_min=10, detected_min=13, pid=2),
        ]
        report = build_report(events)
        assert report.budget_compliance == 1.0

    def test_budget_compliance_mixed(self):
        events = [
            _make_event(died_min=0, detected_min=2, pid=1),    # within
            _make_event(died_min=10, detected_min=18, pid=2),  # over
        ]
        report = build_report(events)
        assert report.budget_compliance == 0.5

    def test_budget_compliance_all_bad(self):
        events = [
            _make_event(died_min=0, detected_min=8, pid=1),
            _make_event(died_min=10, detected_min=19, pid=2),
        ]
        report = build_report(events)
        assert report.budget_compliance == 0.0

    def test_trend_insufficient(self):
        events = [_make_event(died_min=0, detected_min=3)]
        report = build_report(events)
        assert report.trend() == "insufficient_data"

    def test_trend_steady(self):
        events = [
            _make_event(died_min=i*10, detected_min=i*10 + 3, pid=i)
            for i in range(6)
        ]
        report = build_report(events)
        assert report.trend() == "steady"

    def test_trend_improving(self):
        events = []
        for i in range(6):
            gap = 8 - i  # 8, 7, 6, 5, 4, 3 minutes
            events.append(_make_event(died_min=i*20, detected_min=i*20 + gap, pid=i))
        report = build_report(events)
        assert report.trend() == "improving"

    def test_trend_worsening(self):
        events = []
        for i in range(6):
            gap = 2 + i  # 2, 3, 4, 5, 6, 7 minutes
            events.append(_make_event(died_min=i*20, detected_min=i*20 + gap, pid=i))
        report = build_report(events)
        assert report.trend() == "worsening"

    def test_verdict_healthy(self):
        events = [
            _make_event(died_min=0, detected_min=2, pid=i)
            for i in range(5)
        ]
        report = build_report(events)
        assert report.verdict() == "healthy"

    def test_verdict_degraded(self):
        events = [
            _make_event(died_min=0, detected_min=9, pid=i)
            for i in range(5)
        ]
        report = build_report(events)
        assert report.verdict() == "degraded"

    def test_summary_keys(self):
        report = build_report([_make_event()])
        s = report.summary()
        for key in ("count", "mean_detection_sec", "max_detection_sec",
                     "mean_efficiency", "budget_compliance", "trend",
                     "verdict", "check_interval_min"):
            assert key in s

    def test_summary_empty(self):
        report = build_report([])
        s = report.summary()
        assert s["count"] == 0
        assert s["verdict"] == "no_data"

    def test_custom_check_interval(self):
        events = [_make_event(died_min=0, detected_min=3)]
        report = build_report(events, check_interval_min=6)
        # budget = 3 min, gap = 3 min → within budget
        assert report.budget_compliance == 1.0

    def test_within_budget_count(self):
        events = [
            _make_event(died_min=0, detected_min=2, pid=1),
            _make_event(died_min=10, detected_min=18, pid=2),
            _make_event(died_min=20, detected_min=23, pid=3),
        ]
        report = build_report(events)
        assert report.within_budget_count == 2  # 2 min and 3 min are within, 8 min is not


# ============================================================
# report_to_text
# ============================================================

class TestReportToText:
    def test_empty(self):
        report = build_report([])
        text = report_to_text(report)
        assert "no events" in text

    def test_basic(self):
        events = [_make_event(died_min=0, detected_min=3)]
        report = build_report(events)
        text = report_to_text(report)
        assert "1 events" in text
        assert "mean=" in text
        assert "verdict=" in text

    def test_includes_trend(self):
        events = [
            _make_event(died_min=i*10, detected_min=i*10 + 3, pid=i)
            for i in range(6)
        ]
        report = build_report(events)
        text = report_to_text(report)
        assert "trend=" in text

    def test_includes_efficiency(self):
        events = [_make_event(died_min=0, detected_min=2)]
        report = build_report(events)
        text = report_to_text(report)
        assert "efficiency=" in text


# ============================================================
# edge cases
# ============================================================

class TestEdgeCases:
    def test_zero_gap(self):
        """death and detection at the same instant."""
        event = _make_event(died_min=5, detected_min=5)
        lat = measure_latency(event)
        assert lat.detection_gap_sec == 0.0
        assert lat.efficiency() == 1.0
        assert lat.within_budget()

    def test_very_large_gap(self):
        """54-minute gap like the real incident."""
        event = _make_event(died_min=0, detected_min=54)
        lat = measure_latency(event)
        assert lat.detection_gap_sec == 3240.0
        assert not lat.within_budget()
        assert lat.efficiency() == 0.0

    def test_fractional_minutes(self):
        event = _make_event(died_min=0, detected_min=2.5)
        lat = measure_latency(event)
        assert abs(lat.detection_gap_sec - 150.0) < 0.01

    def test_timezone_aware(self):
        base = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
        event = DeathEvent(
            process="writer",
            pid=100,
            died_at=base,
            detected_at=base + timedelta(minutes=3),
        )
        lat = measure_latency(event)
        assert lat.detection_gap_sec == 180.0

    def test_many_events_efficiency(self):
        events = [
            _make_event(died_min=i*10, detected_min=i*10 + 2, pid=i)
            for i in range(20)
        ]
        report = build_report(events)
        # all 2-minute gaps → efficiency ≈ 0.8 each
        assert 0.75 < report.mean_efficiency < 0.85
        assert report.verdict() == "healthy"
