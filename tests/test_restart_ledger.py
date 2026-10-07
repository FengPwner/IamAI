"""Tests for iamai.restart_ledger — restart event tracking and classification.

Covers: recording events, restart rate, mean downtime, worst-hour streak,
reason breakdown, classification tiers (stable / flapping / crash-loop),
report structure, edge cases (empty ledger, single event, eviction).
"""

from __future__ import annotations

import pytest

from iamai.restart_ledger import (
    CRASH_LOOP,
    CRASH_LOOP_HOUR_STREAK,
    FLAPPING,
    FLAPPING_MAX_RESTARTS,
    STABLE,
    STABLE_MAX_RESTARTS,
    RestartEvent,
    RestartLedger,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE = 1_696_636_800.0  # arbitrary epoch anchor


def _event(offset: float, reason: str = "unknown", downtime: float = 60.0) -> RestartEvent:
    return RestartEvent(at=BASE + offset, reason=reason, downtime=downtime, writer_id="qwen")


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


class TestRecording:
    def test_empty_ledger(self):
        ledger = RestartLedger()
        assert len(ledger) == 0
        assert ledger.events == []

    def test_record_single_event(self):
        ledger = RestartLedger()
        count = ledger.record(_event(0))
        assert count == 1
        assert len(ledger) == 1

    def test_record_multiple_events(self):
        ledger = RestartLedger()
        for i in range(10):
            ledger.record(_event(i * 3600))
        assert len(ledger) == 10

    def test_eviction_at_max_events(self):
        ledger = RestartLedger(max_events=5)
        for i in range(10):
            ledger.record(_event(i * 3600, reason=f"r{i}"))
        assert len(ledger) == 5
        # oldest surviving event should be r5
        assert ledger.events[0].reason == "r5"
        assert ledger.events[-1].reason == "r9"

    def test_events_chronological_order(self):
        ledger = RestartLedger()
        offsets = [300, 100, 500, 200]
        for o in offsets:
            ledger.record(_event(o))
        # deque appends in insertion order, not sorted
        actual = [e.at for e in ledger.events]
        expected = [BASE + o for o in offsets]
        assert actual == expected


# ---------------------------------------------------------------------------
# Restart rate
# ---------------------------------------------------------------------------


class TestRestartRate:
    def test_empty_ledger_returns_zero(self):
        assert RestartLedger().restart_rate() == 0.0

    def test_single_event(self):
        ledger = RestartLedger()
        ledger.record(_event(0))
        assert ledger.restart_rate() == 1.0

    def test_all_within_24h(self):
        ledger = RestartLedger()
        for i in range(8):
            ledger.record(_event(i * 3600))  # one per hour, 8 total
        assert ledger.restart_rate() == 8.0

    def test_some_outside_window(self):
        ledger = RestartLedger()
        # 3 events 30h ago (clearly outside 24h window), 2 events 1h ago
        for i in range(3):
            ledger.record(_event(-30 * 3600 + i * 60))
        for i in range(2):
            ledger.record(_event(-3600 + i * 60))
        assert ledger.restart_rate() == 2.0

    def test_custom_window(self):
        ledger = RestartLedger()
        for i in range(5):
            ledger.record(_event(i * 1800))  # every 30 min
        # 6-hour window should capture all 5
        assert ledger.restart_rate(window_hours=6.0) == 5.0
        # 1-hour window from last event (at 7200): captures events at 3600, 5400, 7200
        assert ledger.restart_rate(window_hours=1.0) == 3.0


# ---------------------------------------------------------------------------
# Mean downtime
# ---------------------------------------------------------------------------


class TestMeanDowntime:
    def test_empty_ledger(self):
        assert RestartLedger().mean_downtime() == 0.0

    def test_uniform_downtime(self):
        ledger = RestartLedger()
        for i in range(5):
            ledger.record(_event(i * 3600, downtime=120.0))
        assert ledger.mean_downtime() == 120.0

    def test_mixed_downtime(self):
        ledger = RestartLedger()
        ledger.record(_event(0, downtime=60.0))
        ledger.record(_event(3600, downtime=180.0))
        assert ledger.mean_downtime() == pytest.approx(120.0)

    def test_window_excludes_old_events(self):
        ledger = RestartLedger()
        ledger.record(_event(-30 * 3600, downtime=999.0))
        ledger.record(_event(-3600, downtime=30.0))
        # Only the recent one (30s) is in the 24h window
        assert ledger.mean_downtime() == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# Worst hour streak
# ---------------------------------------------------------------------------


class TestWorstHourStreak:
    def test_empty(self):
        assert RestartLedger().worst_hour_streak() == 0

    def test_single_event(self):
        ledger = RestartLedger()
        ledger.record(_event(0))
        assert ledger.worst_hour_streak() == 1

    def test_spread_across_hours(self):
        ledger = RestartLedger()
        for i in range(5):
            ledger.record(_event(i * 3600))
        assert ledger.worst_hour_streak() == 1

    def test_burst_in_one_hour(self):
        ledger = RestartLedger()
        # 4 restarts in 30 minutes
        for i in range(4):
            ledger.record(_event(i * 600))
        # 1 restart 3 hours later
        ledger.record(_event(3 * 3600))
        assert ledger.worst_hour_streak() == 4

    def test_multiple_bursts(self):
        ledger = RestartLedger()
        # 3 in hour 0
        for i in range(3):
            ledger.record(_event(i * 600))
        # 5 in hour 3
        for i in range(5):
            ledger.record(_event(3 * 3600 + i * 600))
        assert ledger.worst_hour_streak() == 5


# ---------------------------------------------------------------------------
# Reason breakdown
# ---------------------------------------------------------------------------


class TestReasonBreakdown:
    def test_empty(self):
        assert RestartLedger().reason_breakdown() == {}

    def test_single_reason(self):
        ledger = RestartLedger()
        for i in range(3):
            ledger.record(_event(i * 3600, reason="sandbox_recycle"))
        bd = ledger.reason_breakdown()
        assert bd == {"sandbox_recycle": 3}

    def test_multiple_reasons_sorted(self):
        ledger = RestartLedger()
        ledger.record(_event(0, reason="crash"))
        ledger.record(_event(3600, reason="sandbox_recycle"))
        ledger.record(_event(7200, reason="crash"))
        ledger.record(_event(10800, reason="oom_kill"))
        bd = ledger.reason_breakdown()
        keys = list(bd.keys())
        assert keys[0] == "crash"  # count=2, should be first
        assert bd["crash"] == 2
        assert bd["sandbox_recycle"] == 1
        assert bd["oom_kill"] == 1

    def test_window_filter(self):
        ledger = RestartLedger()
        ledger.record(_event(-30 * 3600, reason="old"))
        ledger.record(_event(-3600, reason="recent"))
        bd = ledger.reason_breakdown()
        assert "old" not in bd
        assert bd == {"recent": 1}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassification:
    def test_empty_is_stable(self):
        assert RestartLedger().classify() == STABLE

    def test_few_restarts_stable(self):
        ledger = RestartLedger()
        for i in range(STABLE_MAX_RESTARTS):
            ledger.record(_event(i * 3600 * 5))  # spread across 25h
        assert ledger.classify() == STABLE

    def test_flapping(self):
        ledger = RestartLedger()
        # Just above stable threshold, spread across hours
        for i in range(STABLE_MAX_RESTARTS + 3):
            ledger.record(_event(i * 3600 * 2))  # every 2h, well within 24h
        assert ledger.classify() == FLAPPING

    def test_crash_loop_by_24h_count(self):
        ledger = RestartLedger()
        for i in range(FLAPPING_MAX_RESTARTS + 1):
            ledger.record(_event(i * 1800))  # every 30 min, all in ~10h
        assert ledger.classify() == CRASH_LOOP

    def test_crash_loop_by_hour_streak(self):
        ledger = RestartLedger()
        # CRASH_LOOP_HOUR_STREAK restarts in one hour
        for i in range(CRASH_LOOP_HOUR_STREAK):
            ledger.record(_event(i * 600, reason="crash"))
        assert ledger.classify() == CRASH_LOOP

    def test_stable_exactly_at_threshold(self):
        """Exactly STABLE_MAX_RESTARTS should still be stable."""
        ledger = RestartLedger()
        for i in range(STABLE_MAX_RESTARTS):
            ledger.record(_event(i * 3600))
        assert ledger.classify() == STABLE

    def test_flapping_exactly_at_boundary(self):
        """STABLE_MAX_RESTARTS + 1 should be flapping."""
        ledger = RestartLedger()
        for i in range(STABLE_MAX_RESTARTS + 1):
            ledger.record(_event(i * 3600 * 2))  # spread out
        assert ledger.classify() == FLAPPING


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestReport:
    def test_empty_report(self):
        report = RestartLedger().report()
        assert report["total_events"] == 0
        assert report["classification"] == STABLE
        assert report["restarts_24h"] == 0.0
        assert report["mean_downtime_s"] == 0.0
        assert report["worst_hour_streak"] == 0
        assert report["reason_breakdown"] == {}
        assert report["latest_event"] is None

    def test_report_with_events(self):
        ledger = RestartLedger()
        ledger.record(_event(0, reason="sandbox_recycle", downtime=120.0))
        ledger.record(_event(3600, reason="crash", downtime=300.0))
        report = ledger.report()
        assert report["total_events"] == 2
        assert report["classification"] == STABLE
        assert report["restarts_24h"] == 2.0
        assert report["mean_downtime_s"] == 210.0
        assert report["latest_event"]["reason"] == "crash"
        assert report["latest_event"]["downtime"] == 300.0
        assert report["latest_event"]["writer_id"] == "qwen"

    def test_report_custom_now(self):
        ledger = RestartLedger()
        ledger.record(_event(0))
        # With now = BASE + 25h, the event is outside the window
        report = ledger.report(now=BASE + 25 * 3600)
        assert report["restarts_24h"] == 0.0
        assert report["mean_downtime_s"] == 0.0


# ---------------------------------------------------------------------------
# RestartEvent dataclass
# ---------------------------------------------------------------------------


class TestRestartEvent:
    def test_frozen(self):
        event = RestartEvent(at=BASE, reason="test")
        with pytest.raises(AttributeError):
            event.reason = "changed"  # type: ignore[misc]

    def test_defaults(self):
        event = RestartEvent(at=BASE)
        assert event.reason == "unknown"
        assert event.downtime == 0.0
        assert event.writer_id == "qwen"
        assert event.pid == 0

    def test_custom_values(self):
        event = RestartEvent(at=BASE, reason="oom_kill", downtime=42.5, writer_id="guoban", pid=1234)
        assert event.reason == "oom_kill"
        assert event.downtime == 42.5
        assert event.writer_id == "guoban"
        assert event.pid == 1234
