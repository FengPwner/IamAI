"""Tests for iamai.recovery_coordinator."""

import time
from unittest.mock import MagicMock

import pytest

from iamai.recovery_coordinator import (
    RecoveryAction,
    RecoveryCoordinator,
    RecoveryEvent,
    default_coordinator,
    _noop_selector,
)
from iamai.writer_circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
)


# ---------------------------------------------------------------------------
# RecoveryAction enum
# ---------------------------------------------------------------------------

class TestRecoveryAction:
    def test_values(self):
        assert RecoveryAction.CONTINUE.value == "continue"
        assert RecoveryAction.PAUSE.value == "pause"
        assert RecoveryAction.WAIT.value == "wait"
        assert RecoveryAction.PROBE.value == "probe"
        assert RecoveryAction.INJECT.value == "inject"

    def test_str(self):
        assert str(RecoveryAction.CONTINUE) == "continue"
        assert str(RecoveryAction.PAUSE) == "pause"

    def test_from_value(self):
        assert RecoveryAction("continue") is RecoveryAction.CONTINUE
        assert RecoveryAction("inject") is RecoveryAction.INJECT


# ---------------------------------------------------------------------------
# RecoveryEvent
# ---------------------------------------------------------------------------

class TestRecoveryEvent:
    def test_to_dict_minimal(self):
        ev = RecoveryEvent(
            action=RecoveryAction.CONTINUE,
            health=0.85,
            breaker_state="closed",
        )
        d = ev.to_dict()
        assert d["action"] == "continue"
        assert d["health"] == 0.85
        assert d["breaker_state"] == "closed"
        assert "prompt_text" not in d

    def test_to_dict_with_prompt(self):
        ev = RecoveryEvent(
            action=RecoveryAction.INJECT,
            health=0.1,
            breaker_state="open",
            prompt_text="What if gravity pushed sideways?",
        )
        d = ev.to_dict()
        assert d["prompt_text"] == "What if gravity pushed sideways?"

    def test_roundtrip(self):
        ev = RecoveryEvent(
            action=RecoveryAction.PAUSE,
            health=0.2,
            breaker_state="open",
            at=1700000000.0,
            reason="breaker tripped",
            consecutive_bad=3,
        )
        ev2 = RecoveryEvent.from_dict(ev.to_dict())
        assert ev2.action == ev.action
        assert ev2.health == ev.health
        assert ev2.reason == ev.reason
        assert ev2.consecutive_bad == 3


# ---------------------------------------------------------------------------
# Noop selector
# ---------------------------------------------------------------------------

class TestNoopSelector:
    def test_returns_none(self):
        assert _noop_selector(["a", "b", "c"]) is None
        assert _noop_selector([]) is None


# ---------------------------------------------------------------------------
# Coordinator — healthy writer
# ---------------------------------------------------------------------------

class TestCoordinatorHealthy:
    def test_healthy_ticks_return_continue(self):
        coord = default_coordinator()
        for _ in range(20):
            ev = coord.tick(0.9)
            assert ev.action == RecoveryAction.CONTINUE
            assert ev.breaker_state == "closed"

    def test_state_property(self):
        coord = default_coordinator()
        coord.tick(0.9)
        assert coord.state == "closed"


# ---------------------------------------------------------------------------
# Coordinator — trip and recovery
# ---------------------------------------------------------------------------

class TestCoordinatorTripAndRecovery:
    def test_trip_emits_pause(self):
        """Default trip_after=3: two bad ticks stay CONTINUE, third trips."""
        coord = default_coordinator()
        ev1 = coord.tick(0.1)
        assert ev1.action == RecoveryAction.CONTINUE
        ev2 = coord.tick(0.1)
        assert ev2.action == RecoveryAction.CONTINUE
        # Third bad tick trips the breaker.
        ev3 = coord.tick(0.1)
        assert ev3.action == RecoveryAction.PAUSE
        assert ev3.breaker_state == "open"

    def test_trip_with_prompt_emits_inject(self):
        selector = lambda strokes: "Imagine a world without mirrors."
        coord = default_coordinator(prompt_selector=selector)
        # Trip the breaker (3 bad ticks with default trip_after=3).
        coord.tick(0.1)
        coord.tick(0.1)
        coord.tick(0.1)
        last = coord.events[-1]
        assert last.action == RecoveryAction.INJECT
        assert last.prompt_text == "Imagine a world without mirrors."

    def test_cooldown_emits_wait(self):
        coord = default_coordinator()
        # Trip the breaker.
        coord.tick(0.1)
        coord.tick(0.1)
        coord.tick(0.1)  # PAUSE
        # Now in OPEN state; further ticks should be WAIT.
        ev = coord.tick(0.1)
        assert ev.action == RecoveryAction.WAIT
        assert "cooldown" in ev.reason

    def test_full_recovery_cycle(self):
        """CLOSED -> trip -> OPEN -> cooldown -> HALF_OPEN -> probe -> CLOSED."""
        coord = default_coordinator(cooldown_ticks=3, trip_after=2)

        # Trip the breaker (2 bad ticks).
        coord.tick(0.1)
        ev_trip = coord.tick(0.1)
        assert ev_trip.action == RecoveryAction.PAUSE

        # Cooldown: tick 3 times. The third tick transitions to HALF_OPEN.
        coord.tick(0.1)  # WAIT (tick 1)
        coord.tick(0.1)  # WAIT (tick 2)
        ev = coord.tick(0.1)  # tick 3 -> should_resume() -> PROBE
        assert ev.action == RecoveryAction.PROBE

        # Feed healthy during probe. probe_window=2, so need 2 good ticks.
        coord.tick(0.9)  # probe_observations=1, not yet at probe_window
        ev = coord.tick(0.9)  # probe_observations=2, good_ratio=1.0 -> CLOSED
        assert ev.action == RecoveryAction.CONTINUE
        assert coord.state == "closed"


# ---------------------------------------------------------------------------
# Coordinator — statistics
# ---------------------------------------------------------------------------

class TestCoordinatorStats:
    def test_total_pauses(self):
        coord = default_coordinator(trip_after=1)
        assert coord.total_pauses == 0
        coord.tick(0.1)  # trips immediately (trip_after=1)
        assert coord.total_pauses == 1

    def test_total_pauses_counts_inject(self):
        selector = lambda s: "prompt"
        coord = default_coordinator(trip_after=1, prompt_selector=selector)
        coord.tick(0.1)
        assert coord.total_pauses == 1  # INJECT counts as pause

    def test_total_probes(self):
        coord = default_coordinator(trip_after=1, cooldown_ticks=1)
        coord.tick(0.1)  # PAUSE (trip_after=1)
        coord.tick(0.1)  # WAIT + tick -> cooldown expires -> PROBE
        assert coord.total_probes >= 1

    def test_recovery_rate_no_probes(self):
        coord = default_coordinator()
        assert coord.recovery_rate == 0.0


# ---------------------------------------------------------------------------
# Coordinator — serialisation
# ---------------------------------------------------------------------------

class TestCoordinatorSerialisation:
    def test_roundtrip_empty(self):
        coord = default_coordinator()
        data = coord.to_dict()
        coord2 = RecoveryCoordinator.from_dict(data)
        assert coord2.state == "closed"
        assert len(coord2.events) == 0

    def test_roundtrip_with_events(self):
        coord = default_coordinator(trip_after=1)
        coord.tick(0.9)
        coord.tick(0.1)  # PAUSE
        coord.tick(0.1)  # WAIT

        data = coord.to_dict()
        coord2 = RecoveryCoordinator.from_dict(data)
        assert len(coord2.events) == len(coord.events)
        assert coord2.events[-1].action == coord.events[-1].action
        assert coord2._pause_issued is True

    def test_roundtrip_preserves_last_action(self):
        coord = default_coordinator()
        coord.tick(0.9)
        data = coord.to_dict()
        coord2 = RecoveryCoordinator.from_dict(data)
        assert coord2._last_action == RecoveryAction.CONTINUE

    def test_max_events_truncation(self):
        coord = default_coordinator(max_events=5)
        for i in range(20):
            coord.tick(0.9)
        assert len(coord.events) == 5


# ---------------------------------------------------------------------------
# Coordinator — prompt selector integration
# ---------------------------------------------------------------------------

class TestPromptSelector:
    def test_selector_called_at_trip(self):
        mock = MagicMock(return_value="test prompt")
        coord = default_coordinator(trip_after=2, prompt_selector=mock)
        coord.tick(0.1)
        assert mock.call_count == 0  # not yet tripped
        coord.tick(0.1)  # trips now
        assert mock.call_count == 1
        assert coord.events[-1].prompt_text == "test prompt"

    def test_selector_not_called_during_cooldown(self):
        mock = MagicMock(return_value="prompt")
        coord = default_coordinator(trip_after=1, prompt_selector=mock)
        coord.tick(0.1)  # trips
        assert mock.call_count == 1
        coord.tick(0.1)  # WAIT
        coord.tick(0.1)  # WAIT
        assert mock.call_count == 1  # not called again

    def test_selector_returns_none_gives_pause(self):
        coord = default_coordinator(trip_after=1, prompt_selector=_noop_selector)
        coord.tick(0.1)
        assert coord.events[-1].action == RecoveryAction.PAUSE

    def test_selector_receives_strokes(self):
        captured = []
        def selector(strokes):
            captured.append(list(strokes))
            return "p"
        coord = default_coordinator(trip_after=1, prompt_selector=selector)
        coord.tick(0.1, ["stroke1", "stroke2"])
        assert captured == [["stroke1", "stroke2"]]


# ---------------------------------------------------------------------------
# Coordinator — edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_max_events_ring(self):
        coord = default_coordinator(max_events=3)
        for _ in range(10):
            coord.tick(0.9)
        assert len(coord.events) == 3

    def test_consecutive_bad_tracked(self):
        coord = default_coordinator(trip_after=5)
        for i in range(4):
            ev = coord.tick(0.1)
            assert ev.consecutive_bad == i + 1

    def test_healthy_resets_consecutive_bad(self):
        coord = default_coordinator(trip_after=5)
        coord.tick(0.1)
        coord.tick(0.1)
        ev = coord.tick(0.9)  # healthy resets
        assert ev.consecutive_bad == 0

    def test_from_dict_mid_cooldown(self):
        """Restore a coordinator that was mid-cooldown when serialised."""
        coord = default_coordinator(trip_after=1, cooldown_ticks=10)
        coord.tick(0.1)  # PAUSE
        for _ in range(5):
            coord.tick(0.1)  # WAIT x5

        data = coord.to_dict()
        coord2 = RecoveryCoordinator.from_dict(data)
        # Next tick should still be WAIT (5 ticks done, need 10).
        ev = coord2.tick(0.1)
        assert ev.action == RecoveryAction.WAIT


# ---------------------------------------------------------------------------
# Coordinator — default factory
# ---------------------------------------------------------------------------

class TestDefaultCoordinator:
    def test_creates_working_instance(self):
        coord = default_coordinator()
        ev = coord.tick(0.9)
        assert ev.action == RecoveryAction.CONTINUE

    def test_override_trip_after(self):
        coord = default_coordinator(trip_after=10)
        assert coord.breaker.trip_after == 10

    def test_override_cooldown(self):
        coord = default_coordinator(cooldown_ticks=50)
        assert coord.breaker.cooldown_ticks == 50

    def test_override_health_threshold(self):
        coord = default_coordinator(health_threshold=0.5)
        assert coord.breaker.health_threshold == 0.5

    def test_override_probe_window(self):
        coord = default_coordinator(probe_window=5)
        assert coord.breaker.probe_window == 5
