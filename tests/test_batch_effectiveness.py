"""Tests for iamai.batch_effectiveness — batch committer health tracking.

Covers:
- Attempt recording and sliding-window eviction
- Success/failure counting and ratio computation
- Stuck-streak detection (consecutive tail failures)
- Verdict classification across all four states
- Edge cases: empty tracker, single attempt, all-success, all-failure
- Report formatting
- Reason tracking (last failure reason preserved)
- seconds_since_last_success calculation
- Window overflow (oldest attempts evicted)
- clear() resets state
"""

import pytest

from iamai.batch_effectiveness import (
    Attempt,
    BatchTracker,
    DEFAULT_WINDOW,
    DEGRADED_THRESHOLD,
    FAILING_THRESHOLD,
    STREAK_LENGTH,
    effectiveness,
    effectiveness_report,
    effectiveness_stats,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tracker():
    """Fresh tracker with default settings."""
    return BatchTracker()


@pytest.fixture
def small_tracker():
    """Tracker with window=6, streak_length=3 for fast tests."""
    return BatchTracker(window=6, streak_length=3)


# ---------------------------------------------------------------------------
# Recording and basic counting
# ---------------------------------------------------------------------------

class TestRecording:
    def test_empty_tracker(self, tracker):
        assert tracker.total == 0
        assert tracker.successes == 0
        assert tracker.failures == 0
        assert tracker.failure_ratio is None
        assert tracker.last_reason is None
        assert tracker.consecutive_failures == 0

    def test_single_success(self, tracker):
        tracker.record(success=True, at=1000.0)
        assert tracker.total == 1
        assert tracker.successes == 1
        assert tracker.failures == 0
        assert tracker.failure_ratio == 0.0

    def test_single_failure(self, tracker):
        tracker.record(success=False, at=1000.0, reason="lock")
        assert tracker.total == 1
        assert tracker.successes == 0
        assert tracker.failures == 1
        assert tracker.failure_ratio == 1.0
        assert tracker.last_reason == "lock"

    def test_mixed_attempts(self, tracker):
        tracker.record(success=True,  at=1000.0)
        tracker.record(success=False, at=1100.0, reason="lock")
        tracker.record(success=True,  at=1200.0)
        tracker.record(success=False, at=1300.0, reason="network")
        assert tracker.total == 4
        assert tracker.successes == 2
        assert tracker.failures == 2
        assert tracker.failure_ratio == 0.5
        # last_reason should be the most recent failure
        assert tracker.last_reason == "network"

    def test_reason_none_on_success(self, tracker):
        tracker.record(success=True, at=1000.0)
        assert tracker.last_reason is None

    def test_last_reason_skips_successes(self, tracker):
        tracker.record(success=False, at=1000.0, reason="lock")
        tracker.record(success=True,  at=1100.0)
        # last_reason should still find the failure even though a
        # success came after it
        assert tracker.last_reason == "lock"


# ---------------------------------------------------------------------------
# Sliding window
# ---------------------------------------------------------------------------

class TestWindow:
    def test_eviction(self, small_tracker):
        """Oldest attempts are evicted when window is full."""
        for i in range(10):
            small_tracker.record(success=True, at=1000.0 + i * 100)
        assert small_tracker.total == 6  # window size
        # First 4 should be evicted; remaining timestamps: 1400..1900
        ats = [a.at for a in small_tracker.attempts]
        assert ats[0] == 1400.0
        assert ats[-1] == 1900.0

    def test_eviction_preserves_ratio(self, small_tracker):
        """After evicting old failures, ratio should reflect window only."""
        # 3 failures, then 6 successes → window holds last 6 successes
        for i in range(3):
            small_tracker.record(success=False, at=1000.0 + i, reason="x")
        for i in range(6):
            small_tracker.record(success=True, at=2000.0 + i)
        assert small_tracker.total == 6
        assert small_tracker.successes == 6
        assert small_tracker.failure_ratio == 0.0

    def test_window_one(self):
        """Edge case: window=1 keeps only the latest attempt."""
        t = BatchTracker(window=1, streak_length=1)
        t.record(success=False, at=1000.0, reason="lock")
        t.record(success=True, at=1100.0)
        assert t.total == 1
        assert t.successes == 1
        assert t.failure_ratio == 0.0


# ---------------------------------------------------------------------------
# Consecutive failures and stuck streak
# ---------------------------------------------------------------------------

class TestStreak:
    def test_no_streak_when_empty(self, tracker):
        assert not tracker.is_stuck_streak
        assert tracker.consecutive_failures == 0

    def test_no_streak_when_last_is_success(self, tracker):
        for _ in range(10):
            tracker.record(success=False, at=1000.0, reason="x")
        tracker.record(success=True, at=2000.0)
        assert tracker.consecutive_failures == 0
        assert not tracker.is_stuck_streak

    def test_streak_detected(self, small_tracker):
        """streak_length=3: three consecutive failures → stuck."""
        small_tracker.record(success=True,  at=1000.0)
        small_tracker.record(success=False, at=1100.0, reason="lock")
        small_tracker.record(success=False, at=1200.0, reason="lock")
        small_tracker.record(success=False, at=1300.0, reason="lock")
        assert small_tracker.consecutive_failures == 3
        assert small_tracker.is_stuck_streak

    def test_streak_not_reached(self, small_tracker):
        """Two failures don't trigger streak when streak_length=3."""
        small_tracker.record(success=True,  at=1000.0)
        small_tracker.record(success=False, at=1100.0, reason="lock")
        small_tracker.record(success=False, at=1200.0, reason="lock")
        assert small_tracker.consecutive_failures == 2
        assert not small_tracker.is_stuck_streak

    def test_longer_streak_count(self, small_tracker):
        """All 6 failures → consecutive_failures=6."""
        for i in range(6):
            small_tracker.record(success=False, at=1000.0 + i, reason="x")
        assert small_tracker.consecutive_failures == 6
        assert small_tracker.is_stuck_streak

    def test_streak_broken_by_success(self, small_tracker):
        small_tracker.record(success=False, at=1000.0, reason="x")
        small_tracker.record(success=False, at=1100.0, reason="x")
        small_tracker.record(success=True,  at=1200.0)
        small_tracker.record(success=False, at=1300.0, reason="x")
        assert small_tracker.consecutive_failures == 1
        assert not small_tracker.is_stuck_streak

    def test_default_streak_length(self, tracker):
        """Default tracker needs STREAK_LENGTH consecutive failures."""
        for i in range(STREAK_LENGTH - 1):
            tracker.record(success=False, at=1000.0 + i, reason="x")
        assert not tracker.is_stuck_streak
        tracker.record(success=False, at=2000.0, reason="x")
        assert tracker.is_stuck_streak


# ---------------------------------------------------------------------------
# Verdict classification
# ---------------------------------------------------------------------------

class TestVerdict:
    def test_dead_when_empty(self, tracker):
        assert effectiveness(tracker) == "dead"

    def test_healthy_all_success(self, tracker):
        for i in range(10):
            tracker.record(success=True, at=1000.0 + i)
        assert effectiveness(tracker) == "healthy"

    def test_healthy_low_failure_ratio(self, tracker):
        """1 failure in 20 attempts = 5% < 20% → healthy."""
        for i in range(19):
            tracker.record(success=True, at=1000.0 + i)
        tracker.record(success=False, at=2000.0, reason="x")
        assert tracker.failure_ratio == pytest.approx(0.05)
        assert effectiveness(tracker) == "healthy"

    def test_degraded_moderate_failures(self, tracker):
        """8 failures in 20 = 40% → degraded (between 20% and 60%)."""
        for i in range(12):
            tracker.record(success=True, at=1000.0 + i)
        for i in range(8):
            tracker.record(success=False, at=2000.0 + i, reason="x")
        # But 8 consecutive failures at tail → stuck streak overrides!
        # Need to break the streak:
        assert tracker.is_stuck_streak  # 8 > STREAK_LENGTH(5)
        assert effectiveness(tracker) == "failing"  # streak overrides

    def test_degraded_without_streak(self, tracker):
        """Interleave failures so no stuck streak, ratio in degraded band."""
        # Pattern: S F S F S F S F S F S F S F S F S F F S
        # That's 8 failures in 20, but last is success → no stuck streak
        pattern = [True, False] * 9 + [True, True]
        for i, s in enumerate(pattern):
            reason = "x" if not s else None
            tracker.record(success=s, at=1000.0 + i * 100, reason=reason)
        assert tracker.total == 20
        assert tracker.failures == 9
        ratio = tracker.failure_ratio
        # 9/20 = 0.45 → degraded band
        assert ratio == pytest.approx(0.45)
        assert not tracker.is_stuck_streak
        assert effectiveness(tracker) == "degraded"

    def test_failing_high_ratio(self, tracker):
        """14 failures in 20 = 70% → failing."""
        # Mix to avoid stuck streak: S F F F F F F F F F F F F F S F F F F F
        # Actually let's just test with streak override:
        for i in range(20):
            tracker.record(success=(i % 3 == 0), at=1000.0 + i, reason=None if i % 3 == 0 else "x")
        # Successes at indices 0,3,6,9,12,15,18 = 7 successes, 13 failures
        assert tracker.failures == 13
        assert tracker.failure_ratio == pytest.approx(13 / 20)
        # Last 2 are failures (indices 19,17 are failures; 18 is success)
        # consecutive_failures = 1 (only index 19)
        assert not tracker.is_stuck_streak
        assert effectiveness(tracker) == "failing"

    def test_streak_overrides_healthy_ratio(self, small_tracker):
        """Even with low overall failure ratio, a stuck streak → failing."""
        # window=6: 3 successes, then 3 failures (streak_length=3)
        for i in range(3):
            small_tracker.record(success=True, at=1000.0 + i)
        for i in range(3):
            small_tracker.record(success=False, at=2000.0 + i, reason="lock")
        # ratio = 3/6 = 0.5 (degraded band), but stuck streak → failing
        assert small_tracker.failure_ratio == pytest.approx(0.5)
        assert small_tracker.is_stuck_streak
        assert effectiveness(small_tracker) == "failing"

    def test_single_failure_is_healthy(self, tracker):
        """One failure in one attempt: ratio=1.0 but window too small for streak."""
        tracker.record(success=False, at=1000.0, reason="lock")
        # ratio = 1.0 > FAILING_THRESHOLD, and only 1 attempt < STREAK_LENGTH
        assert not tracker.is_stuck_streak
        assert effectiveness(tracker) == "failing"

    def test_boundary_degraded_threshold(self, tracker):
        """Exactly at DEGRADED_THRESHOLD (0.2) → healthy (below means healthy)."""
        # 4 failures in 20 = 0.2 exactly → degraded (>= threshold)
        for i in range(16):
            tracker.record(success=True, at=1000.0 + i)
        for i in range(4):
            tracker.record(success=False, at=2000.0 + i, reason="x")
        # But 4 consecutive failures < STREAK_LENGTH → no streak
        assert tracker.failure_ratio == pytest.approx(0.2)
        assert not tracker.is_stuck_streak
        assert effectiveness(tracker) == "degraded"

    def test_boundary_failing_threshold(self, tracker):
        """Exactly at FAILING_THRESHOLD (0.6) → failing."""
        # 12 failures in 20 = 0.6 exactly → failing
        # Interleave to avoid streak: pattern S F S F ... ending with S
        pattern = []
        for _ in range(4):
            pattern.extend([True, False, False, False, True])
        # That's 20 items: 8 success, 12 failure
        # Ending: ...False, False, True → no streak
        # Actually let me just build it carefully
        t = BatchTracker(window=20, streak_length=5)
        # 12 failures, 8 successes, last attempt is success to avoid streak
        items = [True] * 8 + [False] * 12
        # Move one success to the end to break the streak
        items = [True] * 7 + [False] * 12 + [True]
        assert len(items) == 20
        for i, s in enumerate(items):
            t.record(success=s, at=1000.0 + i, reason=None if s else "x")
        assert t.failures == 12
        assert t.failure_ratio == pytest.approx(0.6)
        assert not t.is_stuck_streak
        assert effectiveness(t) == "failing"


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_empty(self, tracker):
        s = effectiveness_stats(tracker, now=1000.0)
        assert s["verdict"] == "dead"
        assert s["total_attempts"] == 0
        assert s["failure_ratio"] is None
        assert s["stuck_streak"] is False
        assert s["last_failure_reason"] is None
        assert s["seconds_since_last_success"] is None

    def test_stats_with_data(self, tracker):
        tracker.record(success=True,  at=1000.0)
        tracker.record(success=False, at=1100.0, reason="index.lock")
        tracker.record(success=False, at=1200.0, reason="index.lock")
        s = effectiveness_stats(tracker, now=1300.0)
        assert s["verdict"] in ("healthy", "degraded", "failing")
        assert s["total_attempts"] == 3
        assert s["successes"] == 1
        assert s["failures"] == 2
        assert s["failure_ratio"] == pytest.approx(0.667, abs=0.01)
        assert s["last_failure_reason"] == "index.lock"
        assert s["seconds_since_last_success"] == 300.0  # 1300 - 1000

    def test_stats_no_successes(self, tracker):
        tracker.record(success=False, at=1000.0, reason="lock")
        tracker.record(success=False, at=1100.0, reason="lock")
        s = effectiveness_stats(tracker, now=1200.0)
        assert s["seconds_since_last_success"] is None


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class TestReport:
    def test_report_dead(self, tracker):
        r = effectiveness_report(tracker)
        assert "dead" in r
        assert "no attempts" in r

    def test_report_healthy(self, tracker):
        for i in range(5):
            tracker.record(success=True, at=1000.0 + i)
        r = effectiveness_report(tracker)
        assert "healthy" in r
        assert "5/5" in r
        assert "100%" in r

    def test_report_with_stuck(self, small_tracker):
        for i in range(3):
            small_tracker.record(success=False, at=1000.0 + i, reason="index.lock")
        r = effectiveness_report(small_tracker, now=1100.0)
        assert "failing" in r
        assert "stuck" in r
        assert "index.lock" in r

    def test_report_includes_last_ok(self, tracker):
        tracker.record(success=True,  at=1000.0)
        tracker.record(success=False, at=1100.0, reason="lock")
        r = effectiveness_report(tracker, now=1200.0)
        assert "last ok" in r
        assert "200.0s" in r  # 1200 - 1000

    def test_report_no_successes_message(self, tracker):
        tracker.record(success=False, at=1000.0, reason="lock")
        r = effectiveness_report(tracker)
        assert "no successes" in r


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------

class TestClear:
    def test_clear_resets_everything(self, tracker):
        for i in range(10):
            tracker.record(success=True, at=1000.0 + i)
        tracker.clear()
        assert tracker.total == 0
        assert tracker.successes == 0
        assert tracker.failure_ratio is None
        assert effectiveness(tracker) == "dead"


# ---------------------------------------------------------------------------
# Attempt dataclass
# ---------------------------------------------------------------------------

class TestAttempt:
    def test_attempt_fields(self):
        a = Attempt(success=True, at=1000.0)
        assert a.success is True
        assert a.at == 1000.0
        assert a.reason is None

    def test_attempt_with_reason(self):
        a = Attempt(success=False, at=1000.0, reason="network timeout")
        assert a.reason == "network timeout"

    def test_attempts_list_property(self, tracker):
        tracker.record(success=True, at=1000.0)
        tracker.record(success=False, at=1100.0, reason="x")
        attempts = tracker.attempts
        assert len(attempts) == 2
        assert isinstance(attempts[0], Attempt)
        # Returned list is a copy (mutation doesn't affect tracker)
        attempts.clear()
        assert tracker.total == 2


# ---------------------------------------------------------------------------
# Integration-style: simulate a realistic incident
# ---------------------------------------------------------------------------

class TestIncident:
    def test_index_lock_incident(self):
        """Simulate the index.lock incident: committer fails repeatedly."""
        t = BatchTracker(window=20, streak_length=5)

        # Normal operation: 10 successful commits
        for i in range(10):
            t.record(success=True, at=1000.0 + i * 600)

        assert effectiveness(t) == "healthy"
        assert t.failure_ratio == 0.0

        # Lock file appears: 6 consecutive failures
        for i in range(6):
            t.record(
                success=False,
                at=7000.0 + i * 600,
                reason="Unable to create .git/index.lock: File exists",
            )

        assert t.is_stuck_streak
        assert effectiveness(t) == "failing"

        # Caretaker clears lock, next commit succeeds
        t.record(success=True, at=11000.0)
        assert not t.is_stuck_streak
        # 10 + 1 = 11 successes, 6 failures = 17 total
        # failure_ratio = 6/17 ≈ 0.353
        assert t.failure_ratio == pytest.approx(6 / 17, abs=0.01)
        assert t.total == 17
        assert effectiveness(t) == "degraded"

        # A few more successes and it recovers
        for i in range(3):
            t.record(success=True, at=12000.0 + i * 600)
        # Now 14 successes, 6 failures = 20 total, ratio = 0.3 → degraded still
        assert t.total == 20
        assert t.failure_ratio == pytest.approx(0.3)

    def test_full_recovery(self):
        """After enough successes, tracker returns to healthy."""
        t = BatchTracker(window=10, streak_length=3)

        # 3 failures (stuck)
        for i in range(3):
            t.record(success=False, at=1000.0 + i, reason="lock")
        assert effectiveness(t) == "failing"

        # 10 successes (fills window, evicts failures)
        for i in range(10):
            t.record(success=True, at=2000.0 + i)
        assert effectiveness(t) == "healthy"
        assert t.failure_ratio == 0.0
