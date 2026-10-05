"""Tests for iamai.commit_cooldown — push failure backoff tracker."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.commit_cooldown import CooldownTracker


@pytest.fixture
def tmp_state(tmp_path):
    """Provide a temporary state file path."""
    return tmp_path / "push_cooldown.json"


@pytest.fixture
def tracker(tmp_state):
    """Create a fresh tracker with a controllable clock."""
    clock = [1000.0]

    def now_fn():
        return clock[0]

    t = CooldownTracker(state_path=tmp_state, base=60, cap=600, factor=2.0, now_fn=now_fn)
    t._clock = clock  # expose for test manipulation
    return t


def advance(tracker: CooldownTracker, seconds: float) -> None:
    tracker._clock[0] += seconds


# -- initial state --

class TestInitialState:
    def test_not_in_cooldown(self, tracker):
        assert tracker.in_cooldown() is False

    def test_zero_consecutive_failures(self, tracker):
        assert tracker.consecutive_failures() == 0

    def test_zero_total_failures(self, tracker):
        assert tracker.total_failures() == 0

    def test_zero_remaining(self, tracker):
        assert tracker.remaining_seconds() == 0

    def test_cooldown_duration_zero(self, tracker):
        assert tracker.current_cooldown_duration() == 0


# -- recording failures --

class TestRecordFailure:
    def test_first_failure_increments_count(self, tracker):
        tracker.record_failure()
        assert tracker.consecutive_failures() == 1

    def test_first_failure_enters_cooldown(self, tracker):
        tracker.record_failure()
        assert tracker.in_cooldown() is True

    def test_first_failure_cooldown_is_base(self, tracker):
        tracker.record_failure()
        assert tracker.current_cooldown_duration() == 60

    def test_first_failure_remaining_near_base(self, tracker):
        tracker.record_failure()
        rem = tracker.remaining_seconds()
        assert 55 <= rem <= 60

    def test_consecutive_failures_increment(self, tracker):
        tracker.record_failure()
        tracker.record_failure()
        tracker.record_failure()
        assert tracker.consecutive_failures() == 3

    def test_exponential_backoff(self, tracker):
        # failure 1: 60s, failure 2: 120s, failure 3: 240s
        tracker.record_failure()
        assert tracker.current_cooldown_duration() == 60
        advance(tracker, 61)  # let cooldown expire
        tracker.record_failure()
        assert tracker.current_cooldown_duration() == 120
        advance(tracker, 121)
        tracker.record_failure()
        assert tracker.current_cooldown_duration() == 240

    def test_cap_enforced(self, tracker):
        # 10 consecutive failures: 60 * 2^9 = 30720, should cap at 600
        for _ in range(10):
            tracker.record_failure()
        assert tracker.current_cooldown_duration() == 600

    def test_total_failures_accumulate(self, tracker):
        tracker.record_failure()
        tracker.record_failure()
        tracker.record_failure()
        assert tracker.total_failures() == 3

    def test_returns_failure_count(self, tracker):
        result = tracker.record_failure()
        assert result == 1
        result = tracker.record_failure()
        assert result == 2


# -- recording success --

class TestRecordSuccess:
    def test_resets_consecutive_to_zero(self, tracker):
        tracker.record_failure()
        tracker.record_failure()
        tracker.record_success()
        assert tracker.consecutive_failures() == 0

    def test_exits_cooldown(self, tracker):
        tracker.record_failure()
        assert tracker.in_cooldown() is True
        tracker.record_success()
        assert tracker.in_cooldown() is False

    def test_increments_total_successes(self, tracker):
        tracker.record_success()
        tracker.record_success()
        assert tracker.total_successes() == 2

    def test_success_after_multiple_failures(self, tracker):
        for _ in range(5):
            tracker.record_failure()
        tracker.record_success()
        assert tracker.consecutive_failures() == 0
        assert tracker.in_cooldown() is False
        assert tracker.total_failures() == 5
        assert tracker.total_successes() == 1


# -- cooldown expiry --

class TestCooldownExpiry:
    def test_cooldown_expires_after_duration(self, tracker):
        tracker.record_failure()  # 60s cooldown
        assert tracker.in_cooldown() is True
        advance(tracker, 61)
        assert tracker.in_cooldown() is False

    def test_remaining_decreases_over_time(self, tracker):
        tracker.record_failure()
        r1 = tracker.remaining_seconds()
        advance(tracker, 10)
        r2 = tracker.remaining_seconds()
        assert r2 < r1

    def test_remaining_zero_after_expiry(self, tracker):
        tracker.record_failure()
        advance(tracker, 61)
        assert tracker.remaining_seconds() == 0

    def test_consecutive_count_preserved_after_expiry(self, tracker):
        tracker.record_failure()
        tracker.record_failure()
        advance(tracker, 61)
        # consecutive count doesn't reset on expiry, only on success
        assert tracker.consecutive_failures() == 2


# -- persistence --

class TestPersistence:
    def test_state_saved_to_disk(self, tracker, tmp_state):
        tracker.record_failure()
        data = json.loads(tmp_state.read_text(encoding="utf-8"))
        assert data["consecutive_failures"] == 1

    def test_state_loaded_on_init(self, tmp_state):
        clock = [2000.0]
        t1 = CooldownTracker(state_path=tmp_state, now_fn=lambda: clock[0])
        t1.record_failure()
        t1.record_failure()

        # New tracker loads same state
        t2 = CooldownTracker(state_path=tmp_state, now_fn=lambda: clock[0])
        assert t2.consecutive_failures() == 2

    def test_corrupt_state_file_handled(self, tmp_state):
        tmp_state.write_text("not json {{{", encoding="utf-8")
        t = CooldownTracker(state_path=tmp_state)
        assert t.consecutive_failures() == 0

    def test_missing_state_file_handled(self, tmp_path):
        t = CooldownTracker(state_path=tmp_path / "nonexistent.json")
        assert t.consecutive_failures() == 0


# -- reset --

class TestReset:
    def test_reset_clears_all(self, tracker):
        tracker.record_failure()
        tracker.record_failure()
        tracker.record_failure()
        tracker.reset()
        assert tracker.consecutive_failures() == 0
        assert tracker.total_failures() == 0
        assert tracker.total_successes() == 0
        assert tracker.in_cooldown() is False

    def test_reset_persists(self, tracker, tmp_state):
        tracker.record_failure()
        tracker.reset()
        t2 = CooldownTracker(state_path=tmp_state)
        assert t2.consecutive_failures() == 0


# -- summary --

class TestSummary:
    def test_summary_keys(self, tracker):
        s = tracker.summary()
        expected_keys = {
            "in_cooldown", "remaining_seconds", "consecutive_failures",
            "total_failures", "total_successes", "cooldown_duration",
        }
        assert set(s.keys()) == expected_keys

    def test_summary_after_failure(self, tracker):
        tracker.record_failure()
        s = tracker.summary()
        assert s["in_cooldown"] is True
        assert s["consecutive_failures"] == 1
        assert s["cooldown_duration"] == 60

    def test_summary_after_success(self, tracker):
        tracker.record_success()
        s = tracker.summary()
        assert s["in_cooldown"] is False
        assert s["total_successes"] == 1


# -- edge cases --

class TestEdgeCases:
    def test_rapid_failures_then_success_then_failure(self, tracker):
        tracker.record_failure()
        tracker.record_failure()
        tracker.record_success()
        tracker.record_failure()
        assert tracker.consecutive_failures() == 1
        assert tracker.current_cooldown_duration() == 60  # reset to base
        assert tracker.total_failures() == 3
        assert tracker.total_successes() == 1

    def test_custom_base_and_cap(self, tmp_path):
        t = CooldownTracker(
            state_path=tmp_path / "cd.json",
            base=30, cap=300, factor=3.0,
        )
        t.record_failure()
        assert t.current_cooldown_duration() == 30
        t.record_failure()
        assert t.current_cooldown_duration() == 90  # 30 * 3
        t.record_failure()
        assert t.current_cooldown_duration() == 270  # 30 * 9
        t.record_failure()
        assert t.current_cooldown_duration() == 300  # capped

    def test_factor_one_means_linear(self, tmp_path):
        t = CooldownTracker(
            state_path=tmp_path / "cd.json",
            base=60, cap=600, factor=1.0,
        )
        t.record_failure()
        assert t.current_cooldown_duration() == 60
        t.record_failure()
        assert t.current_cooldown_duration() == 60  # 60 * 1^1 = 60
        t.record_failure()
        assert t.current_cooldown_duration() == 60  # 60 * 1^2 = 60
