"""Tests for iamai.push_health module."""

from __future__ import annotations

import pytest

from iamai.push_health import (
    CRITICAL,
    DEGRADED,
    HEALTHY,
    PushHealth,
)


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------

class TestInit:
    def test_defaults(self):
        ph = PushHealth()
        assert ph.window == 20
        assert ph.attempts == 0
        assert ph.score() == 1.0
        assert ph.consecutive_failures == 0

    def test_custom_window(self):
        ph = PushHealth(window=5)
        assert ph.window == 5

    def test_custom_thresholds(self):
        ph = PushHealth(degrade_threshold=0.8, critical_threshold=0.5)
        assert ph.degrade_threshold == 0.8
        assert ph.critical_threshold == 0.5


# ---------------------------------------------------------------------------
# recording
# ---------------------------------------------------------------------------

class TestRecord:
    def test_single_success(self):
        ph = PushHealth()
        ph.record(True)
        assert ph.attempts == 1
        assert ph.successes == 1
        assert ph.failures == 0
        assert ph.consecutive_failures == 0

    def test_single_failure(self):
        ph = PushHealth()
        ph.record(False)
        assert ph.attempts == 1
        assert ph.successes == 0
        assert ph.failures == 1
        assert ph.consecutive_failures == 1

    def test_mixed(self):
        ph = PushHealth()
        for s in [True, False, True, True, False]:
            ph.record(s)
        assert ph.attempts == 5
        assert ph.successes == 3
        assert ph.failures == 2

    def test_consecutive_failures_reset_on_success(self):
        ph = PushHealth()
        ph.record(False)
        ph.record(False)
        assert ph.consecutive_failures == 2
        ph.record(True)
        assert ph.consecutive_failures == 0

    def test_consecutive_failures_streak(self):
        ph = PushHealth()
        ph.record(True)
        for _ in range(5):
            ph.record(False)
        assert ph.consecutive_failures == 5


# ---------------------------------------------------------------------------
# window eviction
# ---------------------------------------------------------------------------

class TestWindowEviction:
    def test_evicts_oldest(self):
        ph = PushHealth(window=3)
        ph.record(False)
        ph.record(False)
        ph.record(False)
        assert ph.failures == 3
        # This push evicts the oldest (first False)
        ph.record(True)
        assert ph.attempts == 3
        assert ph.successes == 1
        assert ph.failures == 2

    def test_large_window(self):
        ph = PushHealth(window=50)
        for i in range(100):
            ph.record(i % 2 == 0)
        # Only last 50 kept
        assert ph.attempts == 50
        # Last 50: 50..99, even numbers succeed -> 25 successes
        assert ph.successes == 25


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------

class TestScore:
    def test_empty_window_score(self):
        ph = PushHealth()
        assert ph.score() == 1.0

    def test_all_success(self):
        ph = PushHealth()
        for _ in range(10):
            ph.record(True)
        assert ph.score() == 1.0

    def test_all_failure(self):
        ph = PushHealth()
        for _ in range(5):
            ph.record(False)
        assert ph.score() == 0.0

    def test_half_half(self):
        ph = PushHealth()
        for i in range(10):
            ph.record(i % 2 == 0)
        assert ph.score() == 0.5

    def test_score_after_eviction(self):
        ph = PushHealth(window=4)
        # 4 failures -> score 0.0
        for _ in range(4):
            ph.record(False)
        assert ph.score() == 0.0
        # 4 successes evict all failures -> score 1.0
        for _ in range(4):
            ph.record(True)
        assert ph.score() == 1.0


# ---------------------------------------------------------------------------
# lifetime rate
# ---------------------------------------------------------------------------

class TestLifetimeRate:
    def test_no_pushes(self):
        ph = PushHealth()
        assert ph.lifetime_rate == 1.0

    def test_basic(self):
        ph = PushHealth()
        ph.record(True)
        ph.record(False)
        assert ph.lifetime_rate == 0.5

    def test_not_affected_by_eviction(self):
        ph = PushHealth(window=2)
        ph.record(True)
        ph.record(True)
        ph.record(False)
        # Window has only 2 items (True, False), but lifetime tracks all 3
        assert ph.attempts == 2
        assert abs(ph.lifetime_rate - 2 / 3) < 1e-9


# ---------------------------------------------------------------------------
# diagnose
# ---------------------------------------------------------------------------

class TestDiagnose:
    def test_healthy_empty(self):
        ph = PushHealth()
        assert ph.diagnose() == HEALTHY

    def test_healthy_all_success(self):
        ph = PushHealth()
        for _ in range(10):
            ph.record(True)
        assert ph.diagnose() == HEALTHY

    def test_degraded(self):
        ph = PushHealth()
        # Score = 5/10 = 0.5 < 0.6 -> degraded
        # Interleave so no 3+ consecutive failures at end
        results = [True, False, True, False, True, False, True, False, True, False]
        for r in results:
            ph.record(r)
        assert ph.consecutive_failures < 3
        assert ph.diagnose() == DEGRADED

    def test_critical_low_score(self):
        ph = PushHealth()
        # 2/10 = 0.2 < 0.3 threshold -> critical
        for i in range(10):
            ph.record(i < 2)
        assert ph.diagnose() == CRITICAL

    def test_critical_consecutive_failures_override(self):
        ph = PushHealth(consecutive_alert=3)
        # Score is still 0.7 (7/10) but 3 consecutive failures at the end
        for i in range(7):
            ph.record(True)
        for _ in range(3):
            ph.record(False)
        assert ph.diagnose() == CRITICAL

    def test_consecutive_alert_boundary(self):
        ph = PushHealth(consecutive_alert=4)
        # 3 consecutive failures (below alert threshold) + score ok
        for i in range(7):
            ph.record(True)
        for _ in range(3):
            ph.record(False)
        # Score = 0.7, consecutive = 3 (< 4) -> healthy
        assert ph.diagnose() == HEALTHY

    def test_custom_thresholds_degraded(self):
        ph = PushHealth(degrade_threshold=0.9, critical_threshold=0.5)
        # 8/10 = 0.8 < 0.9 -> degraded
        for i in range(10):
            ph.record(i < 8)
        assert ph.diagnose() == DEGRADED

    def test_custom_thresholds_critical(self):
        ph = PushHealth(degrade_threshold=0.9, critical_threshold=0.5)
        # 4/10 = 0.4 < 0.5 -> critical
        for i in range(10):
            ph.record(i < 4)
        assert ph.diagnose() == CRITICAL


# ---------------------------------------------------------------------------
# advise
# ---------------------------------------------------------------------------

class TestAdvise:
    def test_healthy_advice(self):
        ph = PushHealth()
        assert "fine" in ph.advise().lower()

    def test_degraded_advice(self):
        ph = PushHealth()
        results = [True, False, True, False, True, False, True, False, True, False]
        for r in results:
            ph.record(r)
        assert ph.diagnose() == DEGRADED
        assert "rebase" in ph.advise().lower()

    def test_critical_consecutive_advice(self):
        ph = PushHealth()
        for _ in range(5):
            ph.record(False)
        assert ph.diagnose() == CRITICAL
        advice = ph.advise()
        assert "stop" in advice.lower() or "fetch" in advice.lower()

    def test_critical_low_rate_advice(self):
        ph = PushHealth(consecutive_alert=99)  # disable consecutive trigger
        for i in range(10):
            ph.record(i < 2)  # 2/10 = 0.2 -> critical
        assert ph.diagnose() == CRITICAL
        assert "credentials" in ph.advise().lower() or "remote" in ph.advise().lower()


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_everything(self):
        ph = PushHealth()
        for _ in range(5):
            ph.record(False)
        ph.reset()
        assert ph.attempts == 0
        assert ph.score() == 1.0
        assert ph.consecutive_failures == 0
        assert ph.lifetime_rate == 1.0
        assert ph.diagnose() == HEALTHY


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------

class TestRepr:
    def test_repr_contains_key_info(self):
        ph = PushHealth()
        ph.record(True)
        ph.record(False)
        r = repr(ph)
        assert "PushHealth" in r
        assert "score=" in r
        assert "tier=" in r

    def test_repr_after_failures(self):
        ph = PushHealth()
        for _ in range(5):
            ph.record(False)
        r = repr(ph)
        assert "critical" in r
        assert "streak_fails=5" in r
