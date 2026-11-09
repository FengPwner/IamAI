"""Tests for snippets/escalation_relay.py — bridge escalation to supervisor callbacks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from escalation_relay import EscalationRelay  # noqa: E402
from heartbeat_escalation import HeartbeatEscalation  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_relay(callback=None, fire_on_ok=False, clock_val=None):
    """Build a relay with a real HeartbeatEscalation and a controllable clock."""
    counter = {"t": clock_val or 100.0}

    def clock():
        counter["t"] += 1.0
        return counter["t"]

    esc = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
    events = []

    def default_cb(level, misses, ts):
        events.append((level, misses, ts))

    cb = callback if callback is not None else default_cb
    relay = EscalationRelay(esc, callback=cb, fire_on_ok=fire_on_ok, clock=clock)
    return relay, esc, events, counter


# ---------------------------------------------------------------------------
# construction & validation
# ---------------------------------------------------------------------------


def test_construction():
    relay, esc, events, _ = _make_relay()
    assert relay.esc is esc
    assert relay.tick_count == 0
    assert relay.error_count == 0
    assert relay.last_fire_time is None
    assert relay.transitions == []


def test_callback_none_raises():
    esc = HeartbeatEscalation()
    with pytest.raises(ValueError, match="callback must not be None"):
        EscalationRelay(esc, callback=None)


# ---------------------------------------------------------------------------
# tick — no transition
# ---------------------------------------------------------------------------


def test_tick_no_change_returns_false():
    relay, _, _, _ = _make_relay()
    assert relay.tick() is False
    assert relay.tick() is False
    assert relay.tick_count == 2


def test_tick_no_change_does_not_fire():
    relay, _, events, _ = _make_relay()
    relay.tick()
    relay.tick()
    relay.tick()
    assert events == []


# ---------------------------------------------------------------------------
# tick — escalation transition fires callback
# ---------------------------------------------------------------------------


def test_tick_fires_on_ok_to_yellow():
    relay, esc, events, _ = _make_relay()
    esc.miss()  # ok → yellow
    result = relay.tick()
    assert result is True
    assert len(events) == 1
    assert events[0][0] == "yellow"
    assert events[0][1] == 1  # consecutive_misses


def test_tick_fires_on_yellow_to_red():
    relay, esc, events, _ = _make_relay()
    esc.miss()  # yellow
    relay.tick()
    esc.miss()  # red
    result = relay.tick()
    assert result is True
    assert events[-1][0] == "red"
    assert events[-1][1] == 2


def test_tick_fires_on_red_to_critical():
    relay, esc, events, _ = _make_relay()
    esc.miss()  # yellow
    relay.tick()
    esc.miss()  # red
    relay.tick()
    esc.miss()  # critical
    result = relay.tick()
    assert result is True
    assert events[-1][0] == "critical"
    assert events[-1][1] == 3


def test_full_escalation_chain():
    relay, esc, events, _ = _make_relay()
    esc.miss()  # yellow
    relay.tick()
    esc.miss()  # red
    relay.tick()
    esc.miss()  # critical
    relay.tick()
    assert len(events) == 3
    levels = [e[0] for e in events]
    assert levels == ["yellow", "red", "critical"]


# ---------------------------------------------------------------------------
# tick — de-escalation (ping)
# ---------------------------------------------------------------------------


def test_tick_fires_on_red_to_ok_by_default_suppressed():
    """By default, ok transitions are suppressed."""
    relay, esc, events, _ = _make_relay()
    esc.miss()  # yellow
    relay.tick()
    esc.miss()  # red
    relay.tick()
    esc.ping()  # ok
    result = relay.tick()
    assert result is False
    # only yellow and red fired, not ok
    levels = [e[0] for e in events]
    assert levels == ["yellow", "red"]


def test_tick_fires_ok_when_enabled():
    """With fire_on_ok=True, ok transitions fire too."""
    relay, esc, events, _ = _make_relay(fire_on_ok=True)
    esc.miss()  # yellow
    relay.tick()
    esc.ping()  # ok
    result = relay.tick()
    assert result is True
    levels = [e[0] for e in events]
    assert levels == ["yellow", "ok"]


# ---------------------------------------------------------------------------
# tick — repeated same level doesn't re-fire
# ---------------------------------------------------------------------------


def test_repeated_misses_dont_refire():
    """Once at yellow, more misses within yellow range don't re-fire."""
    esc = HeartbeatEscalation(yellow_after=2, red_after=4, critical_after=6)
    events = []
    relay = EscalationRelay(
        esc, callback=lambda l, m, t: events.append((l, m, t)), clock=lambda: 100.0
    )
    esc.miss()  # 1 miss → ok
    relay.tick()
    esc.miss()  # 2 misses → yellow
    relay.tick()  # fires yellow
    esc.miss()  # 3 misses → still yellow
    result = relay.tick()
    assert result is False
    assert len(events) == 1


def test_many_misses_at_critical_only_fires_once():
    relay, esc, events, _ = _make_relay()
    for _ in range(3):
        esc.miss()
        relay.tick()
    # 10 more misses, still critical
    for _ in range(10):
        esc.miss()
        assert relay.tick() is False
    assert len(events) == 3  # yellow, red, critical — no duplicates


# ---------------------------------------------------------------------------
# transitions tracking
# ---------------------------------------------------------------------------


def test_transitions_recorded():
    relay, esc, _, _ = _make_relay()
    esc.miss()  # yellow
    relay.tick()
    esc.miss()  # red
    relay.tick()
    esc.ping()  # ok (suppressed from callback but still a transition)
    relay.tick()
    transitions = relay.transitions
    assert len(transitions) == 3
    # (from, to, timestamp)
    assert transitions[0][0] == "ok"
    assert transitions[0][1] == "yellow"
    assert transitions[1][0] == "yellow"
    assert transitions[1][1] == "red"
    assert transitions[2][0] == "red"
    assert transitions[2][1] == "ok"


def test_transitions_are_copy():
    relay, esc, _, _ = _make_relay()
    esc.miss()
    relay.tick()
    t = relay.transitions
    t.append(("fake", "fake", 0.0))
    assert len(relay.transitions) == 1


# ---------------------------------------------------------------------------
# callback error isolation
# ---------------------------------------------------------------------------


def test_callback_exception_does_not_crash():
    call_count = {"n": 0}

    def bad_callback(level, misses, ts):
        call_count["n"] += 1
        raise RuntimeError("simulated supervisor failure")

    relay, esc, _, _ = _make_relay(callback=bad_callback)
    esc.miss()  # yellow
    relay.tick()  # should not raise
    esc.miss()  # red
    relay.tick()  # should not raise
    assert relay.error_count == 2
    assert call_count["n"] == 2  # callback was still called


def test_error_count_increments():
    relay, esc, _, _ = _make_relay(callback=lambda l, m, t: 1 / 0)
    esc.miss()
    relay.tick()
    esc.miss()
    relay.tick()
    esc.miss()
    relay.tick()
    assert relay.error_count == 3


# ---------------------------------------------------------------------------
# force_fire
# ---------------------------------------------------------------------------


def test_force_fires_current_state():
    relay, esc, events, _ = _make_relay()
    relay.force_fire()
    assert len(events) == 1
    assert events[0][0] == "ok"
    assert events[0][1] == 0


def test_force_fire_at_critical():
    relay, esc, events, _ = _make_relay()
    for _ in range(3):
        esc.miss()
    relay.force_fire()
    assert len(events) == 1
    assert events[0][0] == "critical"
    assert events[0][1] == 3


def test_force_fire_does_not_affect_tick_tracking():
    """force_fire doesn't change last_level, so tick still works normally."""
    relay, esc, events, _ = _make_relay()
    esc.miss()  # yellow
    relay.force_fire()  # fires ok (current state at construction)
    # but tick should still see yellow as a transition from ok
    result = relay.tick()
    assert result is True
    assert events[-1][0] == "yellow"


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


def test_reset_clears_state():
    relay, esc, events, _ = _make_relay()
    esc.miss()
    relay.tick()
    esc.miss()
    relay.tick()
    relay.reset()
    assert relay.tick_count == 0
    assert relay.error_count == 0
    assert relay.last_fire_time is None
    assert relay.transitions == []


def test_reset_syncs_to_current_level():
    """After reset, the relay's last_level matches escalation's current level."""
    relay, esc, events, _ = _make_relay()
    esc.miss()  # yellow
    relay.tick()
    relay.reset()
    # now tick should not fire for yellow (relay thinks we're already at yellow)
    assert relay.tick() is False


# ---------------------------------------------------------------------------
# last_fire_time
# ---------------------------------------------------------------------------


def test_last_fire_time_updates_on_fire():
    relay, esc, _, _ = _make_relay()
    assert relay.last_fire_time is None
    esc.miss()
    relay.tick()
    assert relay.last_fire_time is not None


def test_last_fire_time_updates_on_error():
    relay, esc, _, _ = _make_relay(callback=lambda l, m, t: 1 / 0)
    esc.miss()
    relay.tick()
    assert relay.last_fire_time is not None


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


def test_repr():
    relay, _, _, _ = _make_relay()
    r = repr(relay)
    assert "EscalationRelay" in r
    assert "ticks=0" in r
    assert "errors=0" in r


def test_repr_with_activity():
    relay, esc, _, _ = _make_relay()
    esc.miss()
    relay.tick()
    r = repr(relay)
    assert "yellow" in r
    assert "ticks=1" in r
    assert "transitions=1" in r


# ---------------------------------------------------------------------------
# integration: escalation → relay → callback lifecycle
# ---------------------------------------------------------------------------


def test_full_lifecycle():
    """Complete ok → yellow → red → critical → ok cycle."""
    relay, esc, events, _ = _make_relay(fire_on_ok=True)

    # initial state
    assert relay.tick() is False

    # escalate
    esc.miss()       # yellow
    relay.tick()
    esc.miss()       # red
    relay.tick()
    esc.miss()       # critical
    relay.tick()

    # recover
    esc.ping()       # ok
    relay.tick()

    # re-escalate
    esc.miss()       # yellow
    relay.tick()

    levels = [e[0] for e in events]
    assert levels == ["yellow", "red", "critical", "ok", "yellow"]


def test_rapid_oscillation():
    """Escalate then immediately recover, many times."""
    relay, esc, events, _ = _make_relay()
    for _ in range(20):
        esc.miss()   # yellow
        relay.tick()
        esc.ping()   # ok (suppressed)
        relay.tick()
    assert relay.tick_count == 40
    # only yellow transitions fire (ok suppressed)
    assert len(events) == 20
    assert all(e[0] == "yellow" for e in events)


# visit 583 — escalation relay
