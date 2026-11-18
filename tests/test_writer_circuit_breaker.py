"""Tests for writer_circuit_breaker module.

Covers:
- CircuitBreakerState: enum values and string representation
- CircuitBreaker: construction, defaults, custom params
- observe: healthy/unhealthy measurements, consecutive counters
- tick: cooldown advancement, no-op in non-OPEN states
- should_pause: trip after consecutive bad windows, HALF_OPEN re-trip
- should_resume: OPEN→HALF_OPEN on cooldown expiry, HALF_OPEN→CLOSED on probe success
- trip / reset: forced state transitions
- snapshot: read-only state dict
- to_dict / from_dict: serialisation round-trip
- default_breaker: factory with overrides
- history: transition logging
- Edge cases: single-window trip, zero cooldown, probe window edge cases
"""

from __future__ import annotations

import time

import pytest

from iamai.writer_circuit_breaker import (
    DEFAULT_COOLDOWN_TICKS,
    DEFAULT_HEALTH_THRESHOLD,
    DEFAULT_PROBE_WINDOW,
    DEFAULT_RECOVERY_THRESHOLD,
    DEFAULT_TRIP_AFTER,
    CircuitBreaker,
    CircuitBreakerState,
    default_breaker,
)


# ===========================================================================
# CircuitBreakerState
# ===========================================================================


class TestCircuitBreakerState:
    def test_closed_value(self):
        assert CircuitBreakerState.CLOSED.value == "closed"

    def test_open_value(self):
        assert CircuitBreakerState.OPEN.value == "open"

    def test_half_open_value(self):
        assert CircuitBreakerState.HALF_OPEN.value == "half_open"

    def test_is_string_enum(self):
        assert isinstance(CircuitBreakerState.CLOSED, str)
        assert CircuitBreakerState.CLOSED == "closed"

    def test_from_string(self):
        assert CircuitBreakerState("closed") == CircuitBreakerState.CLOSED
        assert CircuitBreakerState("open") == CircuitBreakerState.OPEN


# ===========================================================================
# CircuitBreaker construction
# ===========================================================================


class TestCircuitBreakerInit:
    def test_defaults(self):
        cb = CircuitBreaker()
        assert cb.health_threshold == DEFAULT_HEALTH_THRESHOLD
        assert cb.trip_after == DEFAULT_TRIP_AFTER
        assert cb.cooldown_ticks == DEFAULT_COOLDOWN_TICKS
        assert cb.probe_window == DEFAULT_PROBE_WINDOW
        assert cb.recovery_threshold == DEFAULT_RECOVERY_THRESHOLD

    def test_initial_state_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitBreakerState.CLOSED

    def test_initial_counters_zero(self):
        cb = CircuitBreaker()
        assert cb.consecutive_bad == 0
        assert cb.consecutive_good == 0
        assert cb.ticks_in_open == 0
        assert cb.trip_count == 0

    def test_custom_params(self):
        cb = CircuitBreaker(
            health_threshold=0.5,
            trip_after=5,
            cooldown_ticks=100,
            probe_window=4,
            recovery_threshold=0.7,
        )
        assert cb.health_threshold == 0.5
        assert cb.trip_after == 5
        assert cb.cooldown_ticks == 100
        assert cb.probe_window == 4
        assert cb.recovery_threshold == 0.7


# ===========================================================================
# observe
# ===========================================================================


class TestObserve:
    def test_healthy_measurement(self):
        cb = CircuitBreaker(health_threshold=0.3)
        cb.observe(0.8)
        assert cb.last_health == 0.8
        assert cb.consecutive_good == 1
        assert cb.consecutive_bad == 0

    def test_unhealthy_measurement(self):
        cb = CircuitBreaker(health_threshold=0.3)
        cb.observe(0.1)
        assert cb.last_health == 0.1
        assert cb.consecutive_bad == 1
        assert cb.consecutive_good == 0

    def test_consecutive_bad_resets_on_good(self):
        cb = CircuitBreaker(health_threshold=0.3)
        cb.observe(0.1)
        cb.observe(0.1)
        cb.observe(0.8)
        assert cb.consecutive_bad == 0
        assert cb.consecutive_good == 1

    def test_consecutive_good_resets_on_bad(self):
        cb = CircuitBreaker(health_threshold=0.3)
        cb.observe(0.8)
        cb.observe(0.8)
        cb.observe(0.1)
        assert cb.consecutive_good == 0
        assert cb.consecutive_bad == 1

    def test_exact_threshold_is_healthy(self):
        cb = CircuitBreaker(health_threshold=0.3)
        cb.observe(0.3)
        assert cb.consecutive_good == 1
        assert cb.consecutive_bad == 0

    def test_just_below_threshold_is_unhealthy(self):
        cb = CircuitBreaker(health_threshold=0.3)
        cb.observe(0.299)
        assert cb.consecutive_bad == 1


# ===========================================================================
# tick
# ===========================================================================


class TestTick:
    def test_tick_in_open_state(self):
        cb = CircuitBreaker()
        cb.trip()
        cb.tick()
        assert cb.ticks_in_open == 1

    def test_tick_multiple(self):
        cb = CircuitBreaker()
        cb.trip()
        for _ in range(5):
            cb.tick()
        assert cb.ticks_in_open == 5

    def test_tick_noop_in_closed(self):
        cb = CircuitBreaker()
        cb.tick()
        assert cb.ticks_in_open == 0

    def test_tick_noop_in_half_open(self):
        cb = CircuitBreaker(cooldown_ticks=1)
        cb.trip()
        cb.tick()  # ticks_in_open = 1
        cb.should_resume()  # transitions to HALF_OPEN
        cb.tick()  # should not advance ticks_in_open
        # ticks_in_open stays at 1 (from before transition)
        assert cb.state == CircuitBreakerState.HALF_OPEN


# ===========================================================================
# should_pause
# ===========================================================================


class TestShouldPause:
    def test_no_pause_when_healthy(self):
        cb = CircuitBreaker(trip_after=3)
        cb.observe(0.8)
        assert not cb.should_pause()

    def test_no_pause_below_trip_after(self):
        cb = CircuitBreaker(trip_after=3)
        cb.observe(0.1)
        cb.observe(0.1)
        assert not cb.should_pause()

    def test_pause_at_trip_after(self):
        cb = CircuitBreaker(trip_after=3)
        cb.observe(0.1)
        cb.observe(0.1)
        cb.observe(0.1)
        assert cb.should_pause()
        assert cb.state == CircuitBreakerState.OPEN

    def test_pause_single_window_trip(self):
        cb = CircuitBreaker(trip_after=1)
        cb.observe(0.1)
        assert cb.should_pause()

    def test_pause_resets_consecutive_bad(self):
        cb = CircuitBreaker(trip_after=2)
        cb.observe(0.1)
        cb.observe(0.1)
        cb.should_pause()
        assert cb.consecutive_bad == 0

    def test_pause_increments_trip_count(self):
        cb = CircuitBreaker(trip_after=1)
        cb.observe(0.1)
        cb.should_pause()
        assert cb.trip_count == 1

    def test_half_open_re_trip_on_bad_probe(self):
        cb = CircuitBreaker(trip_after=2, cooldown_ticks=1, probe_window=2)
        # Trip
        cb.observe(0.1)
        cb.observe(0.1)
        cb.should_pause()
        # Cooldown
        cb.tick()
        cb.should_resume()  # → HALF_OPEN
        assert cb.state == CircuitBreakerState.HALF_OPEN
        # Bad probe
        cb.observe(0.1)
        cb.observe(0.1)
        assert cb.should_pause()
        assert cb.state == CircuitBreakerState.OPEN


# ===========================================================================
# should_resume
# ===========================================================================


class TestShouldResume:
    def test_no_resume_during_cooldown(self):
        cb = CircuitBreaker(cooldown_ticks=5)
        cb.trip()
        cb.tick()
        cb.tick()
        assert not cb.should_resume()

    def test_resume_after_cooldown(self):
        cb = CircuitBreaker(cooldown_ticks=3)
        cb.trip()
        for _ in range(3):
            cb.tick()
        assert cb.should_resume()
        assert cb.state == CircuitBreakerState.HALF_OPEN

    def test_resume_half_open_to_closed_on_good_probe(self):
        cb = CircuitBreaker(
            cooldown_ticks=1, probe_window=2, recovery_threshold=0.5,
        )
        cb.trip()
        cb.tick()
        cb.should_resume()  # → HALF_OPEN
        cb.observe(0.8)
        cb.observe(0.8)
        assert cb.should_resume()
        assert cb.state == CircuitBreakerState.CLOSED

    def test_no_resume_half_open_on_bad_probe(self):
        cb = CircuitBreaker(
            cooldown_ticks=1, probe_window=2, recovery_threshold=0.5,
        )
        cb.trip()
        cb.tick()
        cb.should_resume()  # → HALF_OPEN
        cb.observe(0.8)
        cb.observe(0.1)
        # 1 good out of 2 = 0.5, which meets threshold
        assert cb.should_resume()

    def test_resume_resets_probe_counters(self):
        cb = CircuitBreaker(cooldown_ticks=1, probe_window=1, recovery_threshold=0.5)
        cb.trip()
        cb.tick()
        cb.should_resume()  # → HALF_OPEN
        assert cb.probe_observations == 0
        assert cb.probe_good_count == 0

    def test_zero_cooldown_immediate_resume(self):
        cb = CircuitBreaker(cooldown_ticks=0)
        cb.trip()
        assert cb.should_resume()
        assert cb.state == CircuitBreakerState.HALF_OPEN


# ===========================================================================
# trip / reset
# ===========================================================================


class TestTripReset:
    def test_trip_from_closed(self):
        cb = CircuitBreaker()
        cb.trip()
        assert cb.state == CircuitBreakerState.OPEN
        assert cb.ticks_in_open == 0

    def test_trip_from_half_open(self):
        cb = CircuitBreaker(cooldown_ticks=1)
        cb.trip()
        cb.tick()
        cb.should_resume()  # → HALF_OPEN
        cb.trip()
        assert cb.state == CircuitBreakerState.OPEN
        assert cb.ticks_in_open == 0

    def test_trip_increments_count(self):
        cb = CircuitBreaker()
        cb.trip()
        cb.trip()
        cb.trip()
        assert cb.trip_count == 3

    def test_reset_from_open(self):
        cb = CircuitBreaker()
        cb.trip()
        cb.reset()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.consecutive_bad == 0
        assert cb.ticks_in_open == 0

    def test_reset_from_half_open(self):
        cb = CircuitBreaker(cooldown_ticks=1)
        cb.trip()
        cb.tick()
        cb.should_resume()
        cb.reset()
        assert cb.state == CircuitBreakerState.CLOSED

    def test_reset_clears_all_counters(self):
        cb = CircuitBreaker()
        cb.observe(0.1)
        cb.observe(0.1)
        cb.trip()
        cb.reset()
        assert cb.consecutive_bad == 0
        assert cb.consecutive_good == 0
        assert cb.ticks_in_open == 0
        assert cb.probe_observations == 0
        assert cb.probe_good_count == 0


# ===========================================================================
# snapshot
# ===========================================================================


class TestSnapshot:
    def test_snapshot_keys(self):
        cb = CircuitBreaker()
        snap = cb.snapshot()
        expected_keys = {
            "state", "consecutive_bad", "consecutive_good",
            "ticks_in_open", "trip_count", "last_health",
            "last_transition", "health_threshold", "trip_after",
            "cooldown_ticks",
        }
        assert set(snap.keys()) == expected_keys

    def test_snapshot_state_value(self):
        cb = CircuitBreaker()
        assert cb.snapshot()["state"] == "closed"

    def test_snapshot_after_trip(self):
        cb = CircuitBreaker()
        cb.trip()
        snap = cb.snapshot()
        assert snap["state"] == "open"
        assert snap["trip_count"] == 1
        assert snap["last_transition"] is not None


# ===========================================================================
# Serialisation
# ===========================================================================


class TestSerialisation:
    def test_to_dict_keys(self):
        cb = CircuitBreaker()
        d = cb.to_dict()
        assert "state" in d
        assert "health_threshold" in d
        assert "trip_count" in d

    def test_round_trip_defaults(self):
        cb = CircuitBreaker()
        cb2 = CircuitBreaker.from_dict(cb.to_dict())
        assert cb2.state == cb.state
        assert cb2.health_threshold == cb.health_threshold
        assert cb2.trip_after == cb.trip_after
        assert cb2.cooldown_ticks == cb.cooldown_ticks

    def test_round_trip_after_trip(self):
        cb = CircuitBreaker(trip_after=2, cooldown_ticks=5)
        cb.observe(0.1)
        cb.observe(0.1)
        cb.should_pause()
        d = cb.to_dict()
        cb2 = CircuitBreaker.from_dict(d)
        assert cb2.state == CircuitBreakerState.OPEN
        assert cb2.trip_count == 1
        assert cb2.trip_after == 2
        assert cb2.cooldown_ticks == 5

    def test_from_dict_missing_keys(self):
        cb = CircuitBreaker.from_dict({})
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.health_threshold == DEFAULT_HEALTH_THRESHOLD

    def test_round_trip_half_open(self):
        cb = CircuitBreaker(cooldown_ticks=1)
        cb.trip()
        cb.tick()
        cb.should_resume()
        d = cb.to_dict()
        cb2 = CircuitBreaker.from_dict(d)
        assert cb2.state == CircuitBreakerState.HALF_OPEN


# ===========================================================================
# default_breaker factory
# ===========================================================================


class TestDefaultBreaker:
    def test_returns_circuit_breaker(self):
        cb = default_breaker()
        assert isinstance(cb, CircuitBreaker)

    def test_override_health_threshold(self):
        cb = default_breaker(health_threshold=0.9)
        assert cb.health_threshold == 0.9

    def test_override_multiple(self):
        cb = default_breaker(trip_after=10, cooldown_ticks=50)
        assert cb.trip_after == 10
        assert cb.cooldown_ticks == 50

    def test_defaults_match_module_constants(self):
        cb = default_breaker()
        assert cb.health_threshold == DEFAULT_HEALTH_THRESHOLD
        assert cb.trip_after == DEFAULT_TRIP_AFTER
        assert cb.cooldown_ticks == DEFAULT_COOLDOWN_TICKS
        assert cb.probe_window == DEFAULT_PROBE_WINDOW
        assert cb.recovery_threshold == DEFAULT_RECOVERY_THRESHOLD


# ===========================================================================
# History / transition logging
# ===========================================================================


class TestHistory:
    def test_empty_initially(self):
        cb = CircuitBreaker()
        assert cb.history == []

    def test_trip_records_transition(self):
        cb = CircuitBreaker()
        cb.trip()
        assert len(cb.history) == 1
        assert cb.history[0]["from"] == "closed"
        assert cb.history[0]["to"] == "open"

    def test_full_cycle_history(self):
        cb = CircuitBreaker(cooldown_ticks=1, probe_window=1)
        cb.trip()               # CLOSED → OPEN
        cb.tick()
        cb.should_resume()      # OPEN → HALF_OPEN
        cb.observe(0.8)
        cb.should_resume()      # HALF_OPEN → CLOSED
        assert len(cb.history) == 3
        assert cb.history[0]["from"] == "closed"
        assert cb.history[1]["from"] == "open"
        assert cb.history[1]["to"] == "half_open"
        assert cb.history[2]["from"] == "half_open"
        assert cb.history[2]["to"] == "closed"

    def test_transition_has_timestamp(self):
        cb = CircuitBreaker()
        before = time.time()
        cb.trip()
        after = time.time()
        assert before <= cb.history[0]["at"] <= after


# ===========================================================================
# Full lifecycle integration
# ===========================================================================


class TestLifecycle:
    def test_closed_open_halfopen_closed(self):
        """Full healthy→degrade→trip→cooldown→probe→recover cycle."""
        cb = CircuitBreaker(
            health_threshold=0.3,
            trip_after=2,
            cooldown_ticks=3,
            probe_window=2,
            recovery_threshold=0.5,
        )
        # Healthy phase
        for h in [0.9, 0.8, 0.7]:
            cb.observe(h)
            assert not cb.should_pause()

        # Degrade → trip
        cb.observe(0.1)
        assert not cb.should_pause()
        cb.observe(0.1)
        assert cb.should_pause()
        assert cb.state == CircuitBreakerState.OPEN

        # Cooldown
        for _ in range(2):
            cb.tick()
            assert not cb.should_resume()
        cb.tick()
        assert cb.should_resume()
        assert cb.state == CircuitBreakerState.HALF_OPEN

        # Probe success
        cb.observe(0.8)
        cb.observe(0.9)
        assert cb.should_resume()
        assert cb.state == CircuitBreakerState.CLOSED

    def test_closed_open_halfopen_open_halfopen_closed(self):
        """Re-trip from HALF_OPEN, then recover on second attempt."""
        cb = CircuitBreaker(
            health_threshold=0.3,
            trip_after=2,
            cooldown_ticks=2,
            probe_window=2,
            recovery_threshold=0.5,
        )
        # Trip
        cb.observe(0.1)
        cb.observe(0.1)
        cb.should_pause()
        assert cb.trip_count == 1

        # Cooldown → HALF_OPEN
        cb.tick()
        cb.tick()
        cb.should_resume()

        # Bad probe → re-trip
        cb.observe(0.1)
        cb.observe(0.1)
        assert cb.should_pause()
        assert cb.trip_count == 2
        assert cb.state == CircuitBreakerState.OPEN

        # Second cooldown → HALF_OPEN
        cb.tick()
        cb.tick()
        cb.should_resume()

        # Good probe → CLOSED
        cb.observe(0.8)
        cb.observe(0.9)
        assert cb.should_resume()
        assert cb.state == CircuitBreakerState.CLOSED
