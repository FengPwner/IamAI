#!/usr/bin/env python3
"""Tests for iamai/writer_heartbeat.py — writer liveness detection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_heartbeat import (
    HeartbeatMonitor,
    DEFAULT_HEALTHY_S,
    DEFAULT_DEGRADED_S,
    MAX_HISTORY,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def monitor() -> HeartbeatMonitor:
    """Fresh monitor with default thresholds."""
    return HeartbeatMonitor(now=1000.0)


@pytest.fixture
def tight_monitor() -> HeartbeatMonitor:
    """Monitor with tight thresholds for boundary testing."""
    return HeartbeatMonitor(healthy_s=10.0, degraded_s=20.0, now=1000.0)


# ---------------------------------------------------------------------------
# initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_state_is_dead(self, monitor: HeartbeatMonitor) -> None:
        status = monitor.check(now=1000.0)
        assert status["state"] == "dead"

    def test_gap_is_none(self, monitor: HeartbeatMonitor) -> None:
        status = monitor.check(now=1000.0)
        assert status["gap_s"] is None

    def test_seq_is_none(self, monitor: HeartbeatMonitor) -> None:
        status = monitor.check(now=1000.0)
        assert status["seq"] is None

    def test_stroke_count_zero(self, monitor: HeartbeatMonitor) -> None:
        status = monitor.check(now=1000.0)
        assert status["stroke_count"] == 0

    def test_detail_message(self, monitor: HeartbeatMonitor) -> None:
        status = monitor.check(now=1000.0)
        assert "no strokes" in status["detail"]

    def test_is_dead_property(self, monitor: HeartbeatMonitor) -> None:
        assert monitor.is_dead

    def test_is_healthy_property(self, monitor: HeartbeatMonitor) -> None:
        assert not monitor.is_healthy


# ---------------------------------------------------------------------------
# record_stroke
# ---------------------------------------------------------------------------


class TestRecordStroke:
    def test_accepts_first_stroke(self, monitor: HeartbeatMonitor) -> None:
        assert monitor.record_stroke(seq=1, at=1000.0, now=1000.0)

    def test_accepts_increasing_seq(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        assert monitor.record_stroke(seq=2, at=1015.0, now=1015.0)

    def test_rejects_duplicate_seq(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=5, at=1000.0, now=1000.0)
        assert not monitor.record_stroke(seq=5, at=1015.0, now=1015.0)

    def test_rejects_lower_seq(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=10, at=1000.0, now=1000.0)
        assert not monitor.record_stroke(seq=9, at=1015.0, now=1015.0)

    def test_rejects_future_timestamp(self, monitor: HeartbeatMonitor) -> None:
        # at=2000 is far in the future relative to now=1000
        assert not monitor.record_stroke(seq=1, at=2000.0, now=1000.0)

    def test_tolerates_small_clock_skew(self, monitor: HeartbeatMonitor) -> None:
        # 1s tolerance for clock skew
        assert monitor.record_stroke(seq=1, at=1000.5, now=1000.0)

    def test_updates_last_seq(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=42, at=1000.0, now=1000.0)
        status = monitor.check(now=1000.0)
        assert status["seq"] == 42

    def test_increments_stroke_count(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        monitor.record_stroke(seq=2, at=1015.0, now=1015.0)
        monitor.record_stroke(seq=3, at=1030.0, now=1030.0)
        status = monitor.check(now=1030.0)
        assert status["stroke_count"] == 3

    def test_uses_current_time_defaults(self) -> None:
        """When at/now are omitted, time.time() is used."""
        m = HeartbeatMonitor()
        m.record_stroke(seq=1)
        status = m.check()
        assert status["state"] == "healthy"
        assert status["stroke_count"] == 1


# ---------------------------------------------------------------------------
# state classification — healthy
# ---------------------------------------------------------------------------


class TestHealthyState:
    def test_immediate_is_healthy(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        status = monitor.check(now=1000.0)
        assert status["state"] == "healthy"
        assert status["gap_s"] == pytest.approx(0.0)

    def test_one_cadence_gap_is_healthy(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        status = monitor.check(now=1015.0)  # 15s gap (one cadence)
        assert status["state"] == "healthy"
        assert status["gap_s"] == pytest.approx(15.0)

    def test_two_cadences_gap_is_healthy(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        status = monitor.check(now=1030.0)  # 30s gap (two cadences)
        assert status["state"] == "healthy"

    def test_boundary_at_healthy_s(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        status = monitor.check(now=1000.0 + DEFAULT_HEALTHY_S)
        assert status["state"] == "healthy"

    def test_just_past_healthy_s(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        status = monitor.check(now=1000.0 + DEFAULT_HEALTHY_S + 0.1)
        assert status["state"] == "degraded"

    def test_is_healthy_property(self) -> None:
        import time as _time
        m = HeartbeatMonitor()
        now = _time.time()
        m.record_stroke(seq=1, at=now, now=now)
        assert m.is_healthy
        assert not m.is_dead


# ---------------------------------------------------------------------------
# state classification — degraded
# ---------------------------------------------------------------------------


class TestDegradedState:
    def test_one_minute_gap_is_degraded(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        status = monitor.check(now=1060.0)  # 60s gap
        assert status["state"] == "degraded"

    def test_boundary_at_degraded_s(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        status = monitor.check(now=1000.0 + DEFAULT_DEGRADED_S)
        assert status["state"] == "degraded"

    def test_just_past_degraded_s(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        status = monitor.check(now=1000.0 + DEFAULT_DEGRADED_S + 0.1)
        assert status["state"] == "dead"

    def test_tight_threshold_degraded(self, tight_monitor: HeartbeatMonitor) -> None:
        tight_monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        status = tight_monitor.check(now=1015.0)  # 15s gap, degraded (10-20)
        assert status["state"] == "degraded"


# ---------------------------------------------------------------------------
# state classification — dead
# ---------------------------------------------------------------------------


class TestDeadState:
    def test_five_minute_gap_is_dead(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        status = monitor.check(now=1300.0)  # 300s gap
        assert status["state"] == "dead"

    def test_is_dead_property(self) -> None:
        import time as _time
        m = HeartbeatMonitor()
        old = _time.time() - 500  # 500s ago, well past degraded
        m.record_stroke(seq=1, at=old, now=old + 0.01)
        assert m.is_dead

    def test_tight_threshold_dead(self, tight_monitor: HeartbeatMonitor) -> None:
        tight_monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        status = tight_monitor.check(now=1025.0)  # 25s gap, dead (>20)
        assert status["state"] == "dead"


# ---------------------------------------------------------------------------
# constructor validation
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_healthy_ge_degraded_raises(self) -> None:
        with pytest.raises(ValueError, match="healthy_s.*degraded_s"):
            HeartbeatMonitor(healthy_s=120.0, degraded_s=120.0)

    def test_healthy_gt_degraded_raises(self) -> None:
        with pytest.raises(ValueError, match="healthy_s.*degraded_s"):
            HeartbeatMonitor(healthy_s=200.0, degraded_s=100.0)

    def test_custom_thresholds(self) -> None:
        m = HeartbeatMonitor(healthy_s=5.0, degraded_s=10.0, now=0.0)
        assert m.healthy_s == 5.0
        assert m.degraded_s == 10.0

    def test_default_thresholds(self, monitor: HeartbeatMonitor) -> None:
        assert monitor.healthy_s == DEFAULT_HEALTHY_S
        assert monitor.degraded_s == DEFAULT_DEGRADED_S


# ---------------------------------------------------------------------------
# gap analysis
# ---------------------------------------------------------------------------


class TestGapStats:
    def test_no_strokes(self, monitor: HeartbeatMonitor) -> None:
        stats = monitor.gap_stats()
        assert stats["count"] == 0
        assert stats["mean_gap_s"] is None
        assert stats["max_gap_s"] is None

    def test_one_stroke(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        stats = monitor.gap_stats()
        assert stats["count"] == 1
        assert stats["mean_gap_s"] is None

    def test_two_strokes(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        monitor.record_stroke(seq=2, at=1015.0, now=1015.0)
        stats = monitor.gap_stats()
        assert stats["count"] == 2
        assert stats["mean_gap_s"] == pytest.approx(15.0)
        assert stats["max_gap_s"] == pytest.approx(15.0)
        assert stats["min_gap_s"] == pytest.approx(15.0)

    def test_variable_gaps(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        monitor.record_stroke(seq=2, at=1010.0, now=1010.0)  # 10s
        monitor.record_stroke(seq=3, at=1040.0, now=1040.0)  # 30s
        monitor.record_stroke(seq=4, at=1055.0, now=1055.0)  # 15s
        stats = monitor.gap_stats()
        assert stats["count"] == 4
        assert stats["mean_gap_s"] == pytest.approx((10 + 30 + 15) / 3, rel=1e-2)
        assert stats["max_gap_s"] == pytest.approx(30.0)
        assert stats["min_gap_s"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# bounded history
# ---------------------------------------------------------------------------


class TestBoundedHistory:
    def test_history_bounded_at_max(self, monitor: HeartbeatMonitor) -> None:
        for i in range(MAX_HISTORY + 50):
            monitor.record_stroke(seq=i + 1, at=1000.0 + i * 15.0, now=1000.0 + i * 15.0)
        stats = monitor.gap_stats()
        assert stats["count"] == MAX_HISTORY

    def test_stroke_count_unbounded(self, monitor: HeartbeatMonitor) -> None:
        for i in range(MAX_HISTORY + 50):
            monitor.record_stroke(seq=i + 1, at=1000.0 + i * 15.0, now=1000.0 + i * 15.0)
        status = monitor.check(now=1000.0 + (MAX_HISTORY + 50) * 15.0)
        assert status["stroke_count"] == MAX_HISTORY + 50


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_state(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=42, at=1000.0, now=1000.0)
        monitor.record_stroke(seq=43, at=1015.0, now=1015.0)
        monitor.reset()
        status = monitor.check(now=1015.0)
        assert status["state"] == "dead"
        assert status["seq"] is None
        assert status["stroke_count"] == 0

    def test_reset_clears_history(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        monitor.record_stroke(seq=2, at=1015.0, now=1015.0)
        monitor.reset()
        stats = monitor.gap_stats()
        assert stats["count"] == 0

    def test_accepts_strokes_after_reset(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=100, at=1000.0, now=1000.0)
        monitor.reset()
        # seq=1 is less than 100 but after reset the high-water mark is -1
        assert monitor.record_stroke(seq=1, at=1100.0, now=1100.0)
        status = monitor.check(now=1100.0)
        assert status["seq"] == 1
        assert status["stroke_count"] == 1


# ---------------------------------------------------------------------------
# status dict structure
# ---------------------------------------------------------------------------


class TestStatusStructure:
    def test_healthy_keys(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        status = monitor.check(now=1010.0)
        expected_keys = {"state", "gap_s", "seq", "stroke_count", "healthy_s", "degraded_s"}
        assert set(status.keys()) == expected_keys

    def test_dead_no_strokes_keys(self, monitor: HeartbeatMonitor) -> None:
        status = monitor.check(now=1000.0)
        expected_keys = {"state", "gap_s", "seq", "stroke_count", "detail"}
        assert set(status.keys()) == expected_keys

    def test_gap_s_is_rounded(self, monitor: HeartbeatMonitor) -> None:
        monitor.record_stroke(seq=1, at=1000.0, now=1000.0)
        status = monitor.check(now=1015.12345)
        # gap_s should be rounded to 2 decimal places
        assert status["gap_s"] == 15.12
