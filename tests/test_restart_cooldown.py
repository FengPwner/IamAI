"""Tests for iamai.restart_cooldown — restart cooldown gate."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.restart_cooldown import RestartCooldownGate, RestartDecision


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_gate(
    tmp_path: Path,
    max_restarts: int = 3,
    window_s: int = 3600,
    cooldown_s: int = 1800,
) -> RestartCooldownGate:
    """Create a gate with a temp log file."""
    filepath = tmp_path / "restart_cooldown.jsonl"
    return RestartCooldownGate(
        filepath=filepath,
        max_restarts=max_restarts,
        window_s=window_s,
        cooldown_s=cooldown_s,
    )


def _preseed(gate: RestartCooldownGate, events: list[dict]) -> None:
    """Write events directly to the log file."""
    with open(gate.filepath, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


# ---------------------------------------------------------------------------
# RestartDecision dataclass
# ---------------------------------------------------------------------------

class TestRestartDecision:
    def test_allowed_decision(self):
        d = RestartDecision(allowed=True, remaining_s=0.0, restarts_in_window=1, reason="ok")
        assert d.allowed
        assert d.remaining_s == 0.0

    def test_denied_decision(self):
        d = RestartDecision(allowed=False, remaining_s=300.5, restarts_in_window=3, reason="budget")
        assert not d.allowed
        assert d.remaining_s > 0

    def test_to_dict(self):
        d = RestartDecision(allowed=True, remaining_s=0.0, restarts_in_window=1, reason="ok")
        out = d.to_dict()
        assert out["allowed"] is True
        assert out["restarts_in_window"] == 1
        assert "reason" in out

    def test_frozen(self):
        d = RestartDecision(allowed=True, remaining_s=0.0, restarts_in_window=1, reason="ok")
        with pytest.raises(AttributeError):
            d.allowed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# should_restart — budget enforcement
# ---------------------------------------------------------------------------

class TestShouldRestartBudget:
    def test_first_restart_allowed(self, tmp_path):
        gate = _make_gate(tmp_path)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        decision = gate.should_restart(reason="test", now=now)
        assert decision.allowed
        assert decision.restarts_in_window == 1

    def test_within_budget_allowed(self, tmp_path):
        gate = _make_gate(tmp_path, max_restarts=3)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        # Use 2 of 3 budget slots
        gate.should_restart(reason="r1", now=now)
        gate.should_restart(reason="r2", now=now + timedelta(seconds=10))
        decision = gate.should_restart(reason="r3", now=now + timedelta(seconds=20))
        assert decision.allowed
        assert decision.restarts_in_window == 3

    def test_budget_exhausted_denied(self, tmp_path):
        gate = _make_gate(tmp_path, max_restarts=2)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        gate.should_restart(reason="r1", now=now)
        gate.should_restart(reason="r2", now=now + timedelta(seconds=10))
        # Third attempt should be denied
        decision = gate.should_restart(reason="r3", now=now + timedelta(seconds=20))
        assert not decision.allowed
        assert "budget" in decision.reason.lower() or "exhausted" in decision.reason.lower()

    def test_denied_events_not_counted(self, tmp_path):
        """Denied restarts should not consume budget on subsequent checks."""
        gate = _make_gate(tmp_path, max_restarts=2, cooldown_s=10)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        gate.should_restart(reason="r1", now=now)
        gate.should_restart(reason="r2", now=now + timedelta(seconds=10))
        # Third denied
        gate.should_restart(reason="r3", now=now + timedelta(seconds=20))
        # After cooldown expires, budget resets (old restarts out of window)
        future = now + timedelta(seconds=3700)  # past window_s=3600
        decision = gate.should_restart(reason="r4", now=future)
        assert decision.allowed


# ---------------------------------------------------------------------------
# should_restart — cooldown enforcement
# ---------------------------------------------------------------------------

class TestShouldRestartCooldown:
    def test_cooldown_active_blocks(self, tmp_path):
        gate = _make_gate(tmp_path, max_restarts=1, cooldown_s=600)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        # Exhaust budget
        gate.should_restart(reason="r1", now=now)
        denied = gate.should_restart(reason="r2", now=now + timedelta(seconds=10))
        assert not denied.allowed
        # Still in cooldown 5 minutes later
        decision = gate.should_restart(reason="r3", now=now + timedelta(minutes=5))
        assert not decision.allowed
        assert decision.remaining_s > 0

    def test_cooldown_expires(self, tmp_path):
        gate = _make_gate(tmp_path, max_restarts=1, window_s=100, cooldown_s=60)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        gate.should_restart(reason="r1", now=now)
        gate.should_restart(reason="r2", now=now + timedelta(seconds=5))
        # After cooldown (60s) + past window (100s), should be allowed
        future = now + timedelta(seconds=120)
        decision = gate.should_restart(reason="r3", now=future)
        assert decision.allowed

    def test_remaining_decreases(self, tmp_path):
        gate = _make_gate(tmp_path, max_restarts=1, cooldown_s=600)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        gate.should_restart(reason="r1", now=now)
        d1 = gate.should_restart(reason="r2", now=now + timedelta(seconds=5))
        d2 = gate.should_restart(reason="r3", now=now + timedelta(seconds=100))
        # d2 should have less remaining cooldown than d1
        # (but both may be denied — d1 is the initial denial with full cooldown_s,
        #  d2 is checking the same denied state but later)
        # The first denial sets cooldown_s, the second check finds the denial
        # and calculates remaining = cooldown_s - elapsed
        assert d1.remaining_s >= d2.remaining_s


# ---------------------------------------------------------------------------
# sliding window
# ---------------------------------------------------------------------------

class TestSlidingWindow:
    def test_old_restarts_drop_out(self, tmp_path):
        gate = _make_gate(tmp_path, max_restarts=2, window_s=60, cooldown_s=60)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        # Two restarts at t=0 and t=10
        gate.should_restart(reason="r1", now=now)
        gate.should_restart(reason="r2", now=now + timedelta(seconds=10))
        # Third at t=30 would be denied
        d = gate.should_restart(reason="r3", now=now + timedelta(seconds=30))
        assert not d.allowed
        # Wait for both cooldown (60s from denial at t=30) and window (60s
        # from the restarts) to expire. At t=100: denial at t=30 is 70s ago
        # (> cooldown_s=60), r1 at t=0 is 100s ago (> window_s=60),
        # r2 at t=10 is 90s ago (> window_s=60). All clear.
        future = now + timedelta(seconds=100)
        decision = gate.should_restart(reason="r4", now=future)
        assert decision.allowed

    def test_empty_log_allows(self, tmp_path):
        gate = _make_gate(tmp_path)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        decision = gate.should_restart(reason="first", now=now)
        assert decision.allowed

    def test_corrupt_log_tolerated(self, tmp_path):
        """Corrupt log should not crash should_restart."""
        gate = _make_gate(tmp_path)
        gate.filepath.write_text("{bad json\nnot a line\n", encoding="utf-8")
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        decision = gate.should_restart(reason="test", now=now)
        assert decision.allowed


# ---------------------------------------------------------------------------
# history and reset
# ---------------------------------------------------------------------------

class TestHistoryAndReset:
    def test_history_returns_events(self, tmp_path):
        gate = _make_gate(tmp_path)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        gate.should_restart(reason="r1", now=now)
        gate.should_restart(reason="r2", now=now + timedelta(seconds=10))
        history = gate.history()
        assert len(history) == 2
        assert history[0]["reason"] == "r1"
        assert history[1]["reason"] == "r2"

    def test_history_limit(self, tmp_path):
        gate = _make_gate(tmp_path, max_restarts=10)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        for i in range(8):
            gate.should_restart(reason=f"r{i}", now=now + timedelta(seconds=i))
        history = gate.history(limit=3)
        assert len(history) == 3

    def test_reset_clears_log(self, tmp_path):
        gate = _make_gate(tmp_path)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        gate.should_restart(reason="r1", now=now)
        gate.reset()
        assert gate.history() == []
        # After reset, restart should be allowed
        decision = gate.should_restart(reason="after_reset", now=now)
        assert decision.allowed

    def test_reset_nonexistent_file(self, tmp_path):
        gate = _make_gate(tmp_path)
        gate.reset()  # should not raise


# ---------------------------------------------------------------------------
# event recording
# ---------------------------------------------------------------------------

class TestEventRecording:
    def test_events_are_jsonl(self, tmp_path):
        gate = _make_gate(tmp_path)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        gate.should_restart(reason="test", now=now)
        lines = gate.filepath.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["reason"] == "test"
        assert event["decision"] == "allowed"
        assert "at" in event

    def test_denied_events_recorded(self, tmp_path):
        gate = _make_gate(tmp_path, max_restarts=1, cooldown_s=600)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        gate.should_restart(reason="ok", now=now)
        gate.should_restart(reason="blocked", now=now + timedelta(seconds=5))
        events = gate.history()
        decisions = [e["decision"] for e in events]
        assert "allowed" in decisions
        assert "denied" in decisions

    def test_timestamps_are_iso(self, tmp_path):
        gate = _make_gate(tmp_path)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        gate.should_restart(reason="test", now=now)
        events = gate.history()
        ts = events[0]["at"]
        # Should be parseable as ISO format
        parsed = datetime.fromisoformat(ts)
        assert parsed.year == 2026


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_max_restarts(self, tmp_path):
        """Zero budget means no restarts ever allowed."""
        gate = _make_gate(tmp_path, max_restarts=0, cooldown_s=10)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        decision = gate.should_restart(reason="test", now=now)
        assert not decision.allowed

    def test_very_large_window(self, tmp_path):
        gate = _make_gate(tmp_path, max_restarts=2, window_s=86400)
        now = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        gate.should_restart(reason="r1", now=now)
        gate.should_restart(reason="r2", now=now + timedelta(seconds=10))
        # Even an hour later, still within window
        decision = gate.should_restart(reason="r3", now=now + timedelta(hours=1))
        # Should be denied (in cooldown from the denial at r3 time)
        assert not decision.allowed

    def test_now_defaults_to_utcnow(self, tmp_path):
        """should_restart with no now= should still work."""
        gate = _make_gate(tmp_path)
        decision = gate.should_restart(reason="test")
        assert decision.allowed
