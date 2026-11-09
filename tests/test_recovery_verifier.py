"""tests for recovery_verifier (visit 586).

covers: probe registry, scheduling, delayed fire, retry with backoff,
        failure escalation, eviction, exception handling, summary.
"""

import sys, os, pytest, time as _time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "snippets"))
from recovery_verifier import RecoveryVerifier, VerifyResult


# ── helpers ─────────────────────────────────────────────────────

class FakeClock:
    """deterministic clock that advances manually."""
    def __init__(self, t=1000.0):
        self.t = t
    def __call__(self):
        return self.t
    def advance(self, seconds):
        self.t += seconds


# ── probe registry ──────────────────────────────────────────────

class TestProbeRegistry:

    def test_register_and_has(self):
        v = RecoveryVerifier()
        v.register_probe("restart_writer", lambda: True)
        assert v.has_probe("restart_writer")

    def test_register_duplicate_raises(self):
        v = RecoveryVerifier()
        v.register_probe("restart_writer", lambda: True)
        with pytest.raises(ValueError, match="already registered"):
            v.register_probe("restart_writer", lambda: False)

    def test_unregister(self):
        v = RecoveryVerifier()
        v.register_probe("restart_writer", lambda: True)
        v.unregister_probe("restart_writer")
        assert not v.has_probe("restart_writer")

    def test_unregister_missing_raises(self):
        v = RecoveryVerifier()
        with pytest.raises(KeyError):
            v.unregister_probe("nonexistent")

    def test_registered_labels(self):
        v = RecoveryVerifier()
        v.register_probe("a", lambda: True)
        v.register_probe("b", lambda: False)
        assert sorted(v.registered_labels()) == ["a", "b"]


# ── scheduling ──────────────────────────────────────────────────

class TestScheduling:

    def test_schedule_creates_pending_result(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock)
        v.register_probe("restart", lambda: True)
        r = v.schedule("restart", "d-1")
        assert r.status == "pending"
        assert r.action_label == "restart"
        assert r.dispatch_id == "d-1"
        assert r.attempts == 0

    def test_schedule_no_probe_fails_immediately(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock)
        r = v.schedule("unknown_action", "d-2")
        assert r.status == "failed"
        assert "no probe" in r.detail
        assert r.is_terminal

    def test_pending_count(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock)
        v.register_probe("a", lambda: True)
        v.schedule("a", "d-1")
        v.schedule("a", "d-2")
        assert v.pending_count == 2

    def test_custom_delay(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock, default_delay=10.0)
        v.register_probe("a", lambda: True)
        r = v.schedule("a", "d-1", delay=5.0)
        # not yet
        clock.advance(4.9)
        assert v.tick() == []
        # now
        clock.advance(0.2)
        fired = v.tick()
        assert len(fired) == 1
        assert fired[0].status == "recovered"

    def test_custom_max_retries(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock)
        v.register_probe("a", lambda: False)
        r = v.schedule("a", "d-1", max_retries=0)
        clock.advance(31)
        fired = v.tick()
        assert len(fired) == 1
        assert fired[0].status == "failed"
        assert fired[0].attempts == 1  # initial + 0 retries


# ── delayed fire ────────────────────────────────────────────────

class TestDelayedFire:

    def test_probe_does_not_fire_before_delay(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock, default_delay=30.0)
        v.register_probe("restart", lambda: True)
        v.schedule("restart", "d-1")
        clock.advance(29.9)
        fired = v.tick()
        assert fired == []
        assert v.pending_count == 1

    def test_probe_fires_at_delay(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock, default_delay=30.0)
        v.register_probe("restart", lambda: True)
        v.schedule("restart", "d-1")
        clock.advance(30.0)
        fired = v.tick()
        assert len(fired) == 1
        assert fired[0].status == "recovered"
        assert fired[0].attempts == 1

    def test_probe_fires_after_delay(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock, default_delay=30.0)
        v.register_probe("restart", lambda: True)
        v.schedule("restart", "d-1")
        clock.advance(60.0)
        fired = v.tick()
        assert len(fired) == 1
        assert fired[0].status == "recovered"

    def test_last_probe_at_updated(self):
        clock = FakeClock(500.0)
        v = RecoveryVerifier(clock=clock, default_delay=10.0)
        v.register_probe("a", lambda: True)
        v.schedule("a", "d-1")
        clock.advance(10.0)
        fired = v.tick()
        assert fired[0].last_probe_at == 510.0


# ── retry with backoff ──────────────────────────────────────────

class TestRetryBackoff:

    def test_retry_on_failure_then_success(self):
        clock = FakeClock()
        call_count = [0]
        def flaky():
            call_count[0] += 1
            return call_count[0] >= 2  # fails first, succeeds second
        v = RecoveryVerifier(clock=clock, default_delay=10.0)
        v.register_probe("a", flaky)
        v.schedule("a", "d-1")
        # first attempt fails
        clock.advance(10.0)
        fired = v.tick()
        assert fired == []
        assert v.pending_count == 1
        # retry after backoff (10 * 2^1 = 20s)
        clock.advance(20.0)
        fired = v.tick()
        assert len(fired) == 1
        assert fired[0].status == "recovered"
        assert fired[0].attempts == 2

    def test_exhausted_retries_fail(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock, default_delay=10.0, default_max_retries=1)
        v.register_probe("a", lambda: False)
        v.schedule("a", "d-1")
        # attempt 1: fails
        clock.advance(10.0)
        fired = v.tick()
        assert fired == []
        # attempt 2 (retry): fails → terminal
        clock.advance(20.0)  # 10 * 2^1
        fired = v.tick()
        assert len(fired) == 1
        assert fired[0].status == "failed"
        assert fired[0].attempts == 2

    def test_backoff_doubles(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock, default_delay=5.0, default_max_retries=2)
        v.register_probe("a", lambda: False)
        v.schedule("a", "d-1")
        # attempt 1 at t+5
        clock.advance(5.0)
        v.tick()
        # attempt 2 at t+5+10 (5*2^1)
        clock.advance(10.0)
        v.tick()
        # attempt 3 at t+5+10+20 (5*2^2)
        clock.advance(19.9)
        assert v.tick() == []
        clock.advance(0.1)
        fired = v.tick()
        assert len(fired) == 1
        assert fired[0].attempts == 3

    def test_exception_counts_as_failure(self):
        clock = FakeClock()
        def boom():
            raise RuntimeError("health check exploded")
        v = RecoveryVerifier(clock=clock, default_delay=10.0, default_max_retries=0)
        v.register_probe("a", boom)
        v.schedule("a", "d-1")
        clock.advance(10.0)
        fired = v.tick()
        assert len(fired) == 1
        assert fired[0].status == "failed"
        assert "probe raised" in fired[0].detail


# ── eviction ────────────────────────────────────────────────────

class TestEviction:

    def test_evict_oldest_when_cap_exceeded(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock, default_delay=999.0, max_pending=3)
        v.register_probe("a", lambda: True)
        v.schedule("a", "d-1")
        v.schedule("a", "d-2")
        v.schedule("a", "d-3")
        v.schedule("a", "d-4")  # triggers eviction of d-1
        assert v.pending_count == 3
        # evicted entry should be in history as failed
        evicted = [r for r in v.history if r.dispatch_id == "d-1"]
        assert len(evicted) == 1
        assert evicted[0].status == "failed"
        assert "evicted" in evicted[0].detail


# ── history & summary ──────────────────────────────────────────

class TestHistorySummary:

    def test_history_records_terminal_results(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock, default_delay=10.0)
        v.register_probe("a", lambda: True)
        v.register_probe("b", lambda: False)
        v.schedule("a", "d-1")
        v.schedule("b", "d-2")
        clock.advance(10.0)
        v.tick()
        clock.advance(20.0)
        v.tick()
        clock.advance(40.0)
        v.tick()
        # d-1 recovered, d-2 failed after retries
        assert len(v.history) == 2
        statuses = {r.dispatch_id: r.status for r in v.history}
        assert statuses["d-1"] == "recovered"
        assert statuses["d-2"] == "failed"

    def test_summary_counts(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock, default_delay=10.0, default_max_retries=0)
        v.register_probe("a", lambda: True)
        v.register_probe("b", lambda: False)
        v.schedule("a", "d-1")  # will recover
        v.schedule("b", "d-2")  # will fail
        v.schedule("a", "d-3", delay=9999.0)  # stays pending
        clock.advance(10.0)
        v.tick()  # d-1 recovers, d-2 fails (1 attempt, max_retries=0)
        s = v.summary()
        assert s["recovered"] == 1
        assert s["failed"] == 1
        assert s["pending"] == 1

    def test_no_probe_failure_in_history(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock)
        v.schedule("nonexistent", "d-x")
        assert len(v.history) == 1
        assert v.history[0].status == "failed"


# ── VerifyResult dataclass ──────────────────────────────────────

class TestVerifyResult:

    def test_is_terminal_pending(self):
        r = VerifyResult(action_label="a", dispatch_id="d", status="pending")
        assert not r.is_terminal

    def test_is_terminal_recovered(self):
        r = VerifyResult(action_label="a", dispatch_id="d", status="recovered")
        assert r.is_terminal

    def test_is_terminal_failed(self):
        r = VerifyResult(action_label="a", dispatch_id="d", status="failed")
        assert r.is_terminal

    def test_repr(self):
        r = VerifyResult(action_label="restart", dispatch_id="d-5",
                         status="recovered", attempts=2)
        s = repr(r)
        assert "restart" in s
        assert "d-5" in s
        assert "recovered" in s

    def test_pending_results(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock, default_delay=999.0)
        v.register_probe("a", lambda: True)
        v.schedule("a", "d-1")
        v.schedule("a", "d-2")
        pr = v.pending_results()
        assert len(pr) == 2
        assert all(r.status == "pending" for r in pr)


# ── multiple probes, multiple dispatches ────────────────────────

class TestIntegration:

    def test_two_labels_independent(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock, default_delay=10.0, default_max_retries=0)
        v.register_probe("restart", lambda: True)
        v.register_probe("page", lambda: False)
        r1 = v.schedule("restart", "d-1")
        r2 = v.schedule("page", "d-2")
        clock.advance(10.0)
        fired = v.tick()
        assert len(fired) == 2
        statuses = {r.dispatch_id: r.status for r in fired}
        assert statuses["d-1"] == "recovered"
        assert statuses["d-2"] == "failed"

    def test_same_label_different_dispatch_ids(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock, default_delay=10.0)
        v.register_probe("a", lambda: True)
        v.schedule("a", "d-1")
        v.schedule("a", "d-2")
        clock.advance(10.0)
        fired = v.tick()
        assert len(fired) == 2
        ids = {r.dispatch_id for r in fired}
        assert ids == {"d-1", "d-2"}

    def test_tick_idempotent_when_nothing_due(self):
        clock = FakeClock()
        v = RecoveryVerifier(clock=clock, default_delay=999.0)
        v.register_probe("a", lambda: True)
        v.schedule("a", "d-1")
        v.tick()
        v.tick()
        v.tick()
        assert v.pending_count == 1
        assert v.history == []
