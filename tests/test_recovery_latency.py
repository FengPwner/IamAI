#!/usr/bin/env python3
"""Tests for iamai.recovery_latency — recovery time tracker."""

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from iamai.recovery_latency import RecoveryTracker, RecoveryEvent, RecoveryState


@pytest.fixture
def tmp_state(tmp_path):
    """Provide a temporary state file path."""
    return tmp_path / "recovery_latency.json"


@pytest.fixture
def tracker(tmp_state):
    """Provide a tracker with a temporary state file."""
    return RecoveryTracker(state_file=tmp_state)


class TestRecoveryEvent:
    """RecoveryEvent dataclass tests."""

    def test_create_pending(self):
        e = RecoveryEvent(restart_time=1000.0)
        assert e.is_pending
        assert not e.is_complete
        assert e.latency_seconds is None

    def test_complete_event(self):
        e = RecoveryEvent(restart_time=1000.0)
        e.complete(1005.5)
        assert e.is_complete
        assert not e.is_pending
        assert e.latency_seconds == pytest.approx(5.5)

    def test_complete_with_stroke_count(self):
        e = RecoveryEvent(restart_time=1000.0)
        e.complete(1010.0, stroke_count=42)
        assert e.stroke_count_since == 42

    def test_writer_id_default(self):
        e = RecoveryEvent(restart_time=1000.0)
        assert e.writer_id == "qwen"

    def test_writer_id_custom(self):
        e = RecoveryEvent(restart_time=1000.0, writer_id="doubao")
        assert e.writer_id == "doubao"

    def test_restart_pid(self):
        e = RecoveryEvent(restart_time=1000.0, restart_pid=12345)
        assert e.restart_pid == 12345


class TestRecoveryState:
    """RecoveryState serialization tests."""

    def test_empty_state(self):
        s = RecoveryState()
        d = s.to_dict()
        assert d["current"] is None
        assert d["history"] == []

    def test_roundtrip(self):
        s = RecoveryState()
        s.current = RecoveryEvent(restart_time=1000.0, writer_id="qwen")
        s.history.append(RecoveryEvent(restart_time=900.0))
        s.history[0].complete(905.0)
        d = s.to_dict()
        restored = RecoveryState.from_dict(d)
        assert restored.current.restart_time == 1000.0
        assert len(restored.history) == 1
        assert restored.history[0].latency_seconds == pytest.approx(5.0)

    def test_history_cap(self):
        s = RecoveryState()
        for i in range(100):
            e = RecoveryEvent(restart_time=float(i))
            e.complete(float(i) + 1)
            s.history.append(e)
        d = s.to_dict()
        assert len(d["history"]) == 50  # capped at 50


class TestRecoveryTracker:
    """RecoveryTracker functional tests."""

    def test_mark_restart(self, tracker):
        event = tracker.mark_restart(timestamp=1000.0)
        assert tracker.pending
        assert event.restart_time == 1000.0

    def test_mark_first_stroke(self, tracker):
        tracker.mark_restart(timestamp=1000.0)
        latency = tracker.mark_first_stroke(timestamp=1003.0)
        assert latency == pytest.approx(3.0)
        assert not tracker.pending

    def test_no_restart_returns_none(self, tracker):
        assert tracker.mark_first_stroke(timestamp=1000.0) is None

    def test_double_stroke_returns_none(self, tracker):
        tracker.mark_restart(timestamp=1000.0)
        tracker.mark_first_stroke(timestamp=1003.0)
        assert tracker.mark_first_stroke(timestamp=1005.0) is None

    def test_persistence(self, tmp_state):
        t1 = RecoveryTracker(state_file=tmp_state)
        t1.mark_restart(timestamp=1000.0)

        t2 = RecoveryTracker(state_file=tmp_state)
        assert t2.pending
        assert t2.state.current.restart_time == 1000.0

    def test_last_latency(self, tracker):
        tracker.mark_restart(timestamp=1000.0)
        tracker.mark_first_stroke(timestamp=1007.0)
        assert tracker.last_latency == pytest.approx(7.0)

    def test_average_latency(self, tracker):
        tracker.mark_restart(timestamp=1000.0)
        tracker.mark_first_stroke(timestamp=1004.0)
        tracker.mark_restart(timestamp=2000.0)
        tracker.mark_first_stroke(timestamp=2008.0)
        assert tracker.average_latency == pytest.approx(6.0)

    def test_summary_empty(self, tracker):
        s = tracker.summary()
        assert s["pending"] is False
        assert s["total_recoveries"] == 0
        assert s["avg_latency_s"] is None

    def test_summary_with_data(self, tracker):
        tracker.mark_restart(timestamp=1000.0)
        tracker.mark_first_stroke(timestamp=1005.0)
        s = tracker.summary()
        assert s["completed"] == 1
        assert s["avg_latency_s"] == 5.0
        assert s["min_latency_s"] == 5.0
        assert s["max_latency_s"] == 5.0

    def test_history_count(self, tracker):
        assert tracker.history_count == 0
        tracker.mark_restart(timestamp=1000.0)
        tracker.mark_first_stroke(timestamp=1005.0)
        assert tracker.history_count == 1
        tracker.mark_restart(timestamp=2000.0)
        assert tracker.history_count == 1  # pending doesn't count

    def test_restart_archives_pending(self, tracker):
        tracker.mark_restart(timestamp=1000.0)
        assert tracker.pending
        tracker.mark_restart(timestamp=2000.0)
        assert tracker.history_count == 1  # old pending archived
