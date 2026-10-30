"""Tests for snippets/failure_tracker.py — consecutive-failure alerting."""

from __future__ import annotations

import threading
import time
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from failure_tracker import FailureTracker, StreakSnapshot  # noqa: E402


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_threshold_is_three(self) -> None:
        t = FailureTracker()
        assert t._threshold == 3

    def test_custom_threshold(self) -> None:
        t = FailureTracker(threshold=5)
        assert t._threshold == 5

    def test_zero_threshold_raises(self) -> None:
        with pytest.raises(ValueError, match="threshold"):
            FailureTracker(threshold=0)

    def test_negative_threshold_raises(self) -> None:
        with pytest.raises(ValueError, match="threshold"):
            FailureTracker(threshold=-1)

    def test_fresh_tracker_has_no_failures(self) -> None:
        t = FailureTracker()
        assert t.consecutive_failures == 0
        assert t.total_failures == 0
        assert t.total_successes == 0
        assert not t.alerting


# ---------------------------------------------------------------------------
# recording
# ---------------------------------------------------------------------------


class TestRecording:
    def test_single_failure_increments(self) -> None:
        t = FailureTracker()
        t.record(False)
        assert t.consecutive_failures == 1
        assert t.total_failures == 1

    def test_success_resets_consecutive(self) -> None:
        t = FailureTracker()
        t.record(False)
        t.record(False)
        t.record(True)
        assert t.consecutive_failures == 0
        assert t.total_successes == 1
        # total_failures is NOT reset
        assert t.total_failures == 2

    def test_alerting_at_threshold(self) -> None:
        t = FailureTracker(threshold=3)
        t.record(False)
        t.record(False)
        assert not t.alerting
        t.record(False)
        assert t.alerting

    def test_alerting_clears_on_success(self) -> None:
        t = FailureTracker(threshold=2)
        t.record(False)
        t.record(False)
        assert t.alerting
        t.record(True)
        assert not t.alerting

    def test_threshold_one_alerts_immediately(self) -> None:
        t = FailureTracker(threshold=1)
        t.record(False)
        assert t.alerting

    def test_streak_grows_beyond_threshold(self) -> None:
        t = FailureTracker(threshold=2)
        for _ in range(10):
            t.record(False)
        assert t.consecutive_failures == 10
        assert t.alerting

    def test_mixed_pattern(self) -> None:
        t = FailureTracker(threshold=3)
        # fail, fail, ok, fail, fail, fail -> alert
        t.record(False)
        t.record(False)
        t.record(True)
        assert t.consecutive_failures == 0
        t.record(False)
        t.record(False)
        assert not t.alerting
        t.record(False)
        assert t.alerting
        assert t.consecutive_failures == 3
        assert t.total_failures == 5
        assert t.total_successes == 1


# ---------------------------------------------------------------------------
# streak duration
# ---------------------------------------------------------------------------


class TestStreakDuration:
    def test_no_streak_returns_zero(self) -> None:
        t = FailureTracker()
        assert t.streak_duration() == 0.0

    def test_streak_duration_positive(self) -> None:
        t = FailureTracker()
        t.record(False)
        time.sleep(0.05)
        dur = t.streak_duration()
        assert dur >= 0.04

    def test_streak_duration_resets_on_success(self) -> None:
        t = FailureTracker()
        t.record(False)
        t.record(True)
        assert t.streak_duration() == 0.0


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_is_frozen(self) -> None:
        t = FailureTracker()
        t.record(False)
        snap = t.snapshot()
        assert isinstance(snap, StreakSnapshot)
        with pytest.raises(AttributeError):
            snap.consecutive_failures = 99  # type: ignore[misc]

    def test_snapshot_reflects_state(self) -> None:
        t = FailureTracker(threshold=2)
        t.record(False)
        t.record(False)
        snap = t.snapshot()
        assert snap.consecutive_failures == 2
        assert snap.total_failures == 2
        assert snap.total_successes == 0
        assert snap.alerting is True
        assert snap.first_failure_at is not None

    def test_snapshot_detached_from_tracker(self) -> None:
        t = FailureTracker()
        t.record(False)
        snap = t.snapshot()
        t.record(True)
        # snapshot still shows the old state
        assert snap.consecutive_failures == 1
        # tracker shows new state
        assert t.consecutive_failures == 0


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_everything(self) -> None:
        t = FailureTracker()
        t.record(False)
        t.record(False)
        t.record(True)
        t.record(False)
        t.reset()
        assert t.consecutive_failures == 0
        assert t.total_failures == 0
        assert t.total_successes == 0
        assert not t.alerting
        assert t.streak_duration() == 0.0


# ---------------------------------------------------------------------------
# thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_records(self) -> None:
        t = FailureTracker(threshold=1000)  # high threshold so no alert
        errors = []

        def worker(fail: bool, count: int) -> None:
            try:
                for _ in range(count):
                    t.record(fail)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(False, 500)),
            threading.Thread(target=worker, args=(True, 500)),
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert not errors
        assert t.total_failures == 500
        assert t.total_successes == 500
