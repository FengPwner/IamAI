"""Tests for iamai.push_recovery — push failure tracking and strategy."""

from __future__ import annotations

import pytest

from iamai.push_recovery import (
    PushAttempt,
    PushRecoveryTracker,
    FAILURE_MODES,
    ACTIONS,
)


# ---------------------------------------------------------------------------
# PushAttempt — construction
# ---------------------------------------------------------------------------

class TestPushAttempt:
    def test_success(self):
        a = PushAttempt(success=True)
        assert a.success is True
        assert a.failure_mode is None

    def test_failure(self):
        a = PushAttempt(success=False, failure_mode="diverged")
        assert a.success is False
        assert a.failure_mode == "diverged"

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="unknown failure_mode"):
            PushAttempt(success=False, failure_mode="bogus")

    def test_success_with_mode_raises(self):
        with pytest.raises(ValueError, match="successful push"):
            PushAttempt(success=True, failure_mode="network")

    def test_frozen(self):
        a = PushAttempt(success=True)
        with pytest.raises(AttributeError):
            a.success = False

    def test_all_failure_modes_accepted(self):
        for mode in FAILURE_MODES:
            a = PushAttempt(success=False, failure_mode=mode)
            assert a.failure_mode == mode


# ---------------------------------------------------------------------------
# PushRecoveryTracker — fresh state
# ---------------------------------------------------------------------------

class TestTrackerFresh:
    def test_zero_attempts(self):
        t = PushRecoveryTracker()
        assert t.total_attempts == 0
        assert t.consecutive_failures == 0
        assert t.last_failure_mode is None
        assert t.is_escalated is False

    def test_next_action_fresh(self):
        t = PushRecoveryTracker()
        assert t.next_action() == "retry"

    def test_negative_max_retries_raises(self):
        with pytest.raises(ValueError, match="max_retries"):
            PushRecoveryTracker(max_retries=-1)


# ---------------------------------------------------------------------------
# PushRecoveryTracker — success
# ---------------------------------------------------------------------------

class TestTrackerSuccess:
    def test_record_success(self):
        t = PushRecoveryTracker()
        t.record_success()
        assert t.total_attempts == 1
        assert t.consecutive_failures == 0

    def test_next_action_after_success(self):
        t = PushRecoveryTracker()
        t.record_success()
        assert t.next_action() == "retry"

    def test_success_resets_consecutive(self):
        t = PushRecoveryTracker()
        t.record_failure("network")
        t.record_failure("network")
        assert t.consecutive_failures == 2
        t.record_success()
        assert t.consecutive_failures == 0


# ---------------------------------------------------------------------------
# PushRecoveryTracker — diverged
# ---------------------------------------------------------------------------

class TestTrackerDiverged:
    def test_diverged_action(self):
        t = PushRecoveryTracker()
        t.record_failure("diverged")
        assert t.next_action() == "pull_retry"

    def test_diverged_last_failure_mode(self):
        t = PushRecoveryTracker()
        t.record_failure("diverged")
        assert t.last_failure_mode == "diverged"


# ---------------------------------------------------------------------------
# PushRecoveryTracker — network
# ---------------------------------------------------------------------------

class TestTrackerNetwork:
    def test_network_action(self):
        t = PushRecoveryTracker()
        t.record_failure("network")
        assert t.next_action() == "backoff"

    def test_backoff_increases(self):
        t = PushRecoveryTracker()
        t.record_failure("network")
        d1 = t.backoff_seconds()
        t.record_failure("network")
        d2 = t.backoff_seconds()
        assert d2 > d1

    def test_backoff_capped(self):
        t = PushRecoveryTracker(max_retries=20)
        for _ in range(20):
            t.record_failure("network")
        assert t.backoff_seconds() <= 120.0


# ---------------------------------------------------------------------------
# PushRecoveryTracker — auth (hard escalate)
# ---------------------------------------------------------------------------

class TestTrackerAuth:
    def test_auth_escalates_immediately(self):
        t = PushRecoveryTracker(max_retries=5)
        t.record_failure("auth")
        assert t.next_action() == "escalate"
        assert t.is_escalated is True


# ---------------------------------------------------------------------------
# PushRecoveryTracker — rejected_nonfastforward
# ---------------------------------------------------------------------------

class TestTrackerNonFF:
    def test_nonfastforward_escalates(self):
        t = PushRecoveryTracker()
        t.record_failure("rejected_nonfastforward")
        assert t.next_action() == "escalate"
        assert t.is_escalated is True


# ---------------------------------------------------------------------------
# PushRecoveryTracker — unknown
# ---------------------------------------------------------------------------

class TestTrackerUnknown:
    def test_unknown_escalates(self):
        t = PushRecoveryTracker()
        t.record_failure("unknown")
        assert t.next_action() == "escalate"


# ---------------------------------------------------------------------------
# PushRecoveryTracker — retry budget
# ---------------------------------------------------------------------------

class TestTrackerBudget:
    def test_exceed_budget_escalates(self):
        t = PushRecoveryTracker(max_retries=2)
        t.record_failure("diverged")
        assert t.next_action() == "pull_retry"
        t.record_failure("diverged")
        assert t.next_action() == "pull_retry"
        t.record_failure("diverged")
        assert t.next_action() == "escalate"
        assert t.is_escalated is True

    def test_zero_retries(self):
        t = PushRecoveryTracker(max_retries=0)
        t.record_failure("network")
        assert t.next_action() == "escalate"


# ---------------------------------------------------------------------------
# PushRecoveryTracker — reset
# ---------------------------------------------------------------------------

class TestTrackerReset:
    def test_reset_clears(self):
        t = PushRecoveryTracker()
        t.record_failure("auth")
        assert t.is_escalated
        t.reset()
        assert t.total_attempts == 0
        assert t.next_action() == "retry"


# ---------------------------------------------------------------------------
# constants sanity
# ---------------------------------------------------------------------------

class TestConstants:
    def test_failure_modes_frozen(self):
        assert isinstance(FAILURE_MODES, frozenset)
        assert "diverged" in FAILURE_MODES
        assert "auth" in FAILURE_MODES

    def test_actions_frozen(self):
        assert isinstance(ACTIONS, frozenset)
        assert ACTIONS == {"retry", "pull_retry", "backoff", "escalate"}
