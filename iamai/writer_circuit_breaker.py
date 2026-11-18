"""writer_circuit_breaker — automatic trip switch for degenerate writers.

The monitoring stack (dedup, echo, loop, novelty injector) detects stalls
and can inject novelty, but no component *decides* to stop the writer
when detection alone is not enough.  A stuck writer that burns through
the novelty pool without recovering is worse than a stopped writer: it
pollutes the stroke stream with low-quality filler while consuming
compute.

This module provides a **circuit breaker** — the same pattern used in
electrical systems and microservice architectures.  It monitors a
health signal (diversity ratio), trips when the signal degrades past a
threshold for a configurable number of consecutive windows, and
automatically resets after a cooldown period.

State machine
-------------

::

    CLOSED ──▶ (health drops for N windows) ──▶ OPEN
      ▲                                          │
      │                              (cooldown expires)
      │                                          ▼
      └──────── (health recovers) ────────── HALF_OPEN


- **CLOSED**: normal operation, writer running freely.
- **OPEN**: writer paused, cooldown timer ticking.
- **HALF_OPEN**: cooldown expired, writer tentatively unpaused;
  if health drops again within the probe window, trip back to OPEN
  immediately (no consecutive-window requirement).

Public API
----------

- ``CircuitBreakerState`` — enum-like constants (CLOSED, OPEN, HALF_OPEN)
- ``CircuitBreaker`` — main class with ``observe(health)``, ``should_pause()``,
  ``should_resume()``, ``trip()``, ``reset()``, ``tick()``
- ``from_dict`` / ``to_dict`` — serialise state for persistence
- ``default_breaker`` — factory with tuned defaults for the IamAI writer

Design choices
--------------

- The breaker does **not** touch the pause file or git directly.
  It is a pure decision engine: call ``observe()``, check
  ``should_pause()`` / ``should_resume()``, and let the caller
  (caretaker, batch committer, or writer loop) act on the verdict.
- Consecutive-window counting avoids flapping on a single bad
  measurement.  Default ``trip_after=3`` means the writer must
  show degraded diversity for three consecutive windows before
  the breaker trips.
- Cooldown is measured in ticks (calls to ``tick()``), not wall
  seconds, so the caller controls the time base.
- HALF_OPEN uses a short probe window (``probe_window=2``) — if
  health drops during the probe, the breaker trips immediately
  without waiting for ``trip_after`` consecutive bad windows.

Usage::

    from iamai.writer_circuit_breaker import default_breaker

    cb = default_breaker()
    for window_health in [0.8, 0.2, 0.15, 0.1]:
        cb.observe(window_health)
        cb.tick()
        if cb.should_pause():
            # pause the writer
            pass
        elif cb.should_resume():
            # unpause the writer
            pass

"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class CircuitBreakerState(str, Enum):
    """Three-state machine for the circuit breaker."""
    CLOSED = "closed"       # normal — writer runs
    OPEN = "open"           # tripped — writer paused
    HALF_OPEN = "half_open" # probing — writer tentatively resumed


# Module-level defaults tuned for the IamAI writer cadence.
DEFAULT_HEALTH_THRESHOLD = 0.30   # below this = unhealthy window
DEFAULT_TRIP_AFTER = 3            # consecutive unhealthy windows → trip
DEFAULT_COOLDOWN_TICKS = 20       # ticks to wait in OPEN before → HALF_OPEN
DEFAULT_PROBE_WINDOW = 2          # windows to probe in HALF_OPEN
DEFAULT_RECOVERY_THRESHOLD = 0.50 # health must exceed this to close from HALF_OPEN


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class CircuitBreaker:
    """Stateful circuit breaker for writer health monitoring.

    Parameters
    ----------
    health_threshold : float
        Diversity ratio below which a window is considered unhealthy.
    trip_after : int
        Number of consecutive unhealthy windows before tripping to OPEN.
    cooldown_ticks : int
        Number of ``tick()`` calls to remain in OPEN before transitioning
        to HALF_OPEN.
    probe_window : int
        Number of windows to observe in HALF_OPEN before deciding to
        close (recover) or re-trip.
    recovery_threshold : float
        Health must exceed this to transition from HALF_OPEN → CLOSED.
    """

    health_threshold: float = DEFAULT_HEALTH_THRESHOLD
    trip_after: int = DEFAULT_TRIP_AFTER
    cooldown_ticks: int = DEFAULT_COOLDOWN_TICKS
    probe_window: int = DEFAULT_PROBE_WINDOW
    recovery_threshold: float = DEFAULT_RECOVERY_THRESHOLD

    # Internal state — not part of the constructor signature.
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    consecutive_bad: int = 0
    consecutive_good: int = 0
    ticks_in_open: int = 0
    probe_observations: int = 0
    probe_good_count: int = 0
    trip_count: int = 0
    last_health: Optional[float] = None
    last_transition: Optional[float] = None
    history: List[Dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observe(self, health: float) -> None:
        """Record a health measurement for the current window.

        Updates internal consecutive-good/bad counters based on whether
        ``health`` is above or below ``health_threshold``.
        """
        self.last_health = health
        if health < self.health_threshold:
            self.consecutive_bad += 1
            self.consecutive_good = 0
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.probe_observations += 1
        else:
            self.consecutive_good += 1
            self.consecutive_bad = 0
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.probe_observations += 1
                self.probe_good_count += 1

    def tick(self) -> None:
        """Advance the cooldown clock by one tick.

        Only meaningful in the OPEN state.  In other states this is
        a no-op (but safe to call).
        """
        if self.state == CircuitBreakerState.OPEN:
            self.ticks_in_open += 1

    def should_pause(self) -> bool:
        """Return True if the breaker just tripped to OPEN.

        The caller should pause the writer and commit pending changes.
        This is a one-shot signal: once read, it resets the trip
        notification flag so subsequent calls return False until the
        next trip.
        """
        if self.state == CircuitBreakerState.CLOSED:
            if self.consecutive_bad >= self.trip_after:
                self.trip()
                return True
        if self.state == CircuitBreakerState.HALF_OPEN:
            if self.probe_observations >= self.probe_window:
                good_ratio = (
                    self.probe_good_count / self.probe_observations
                    if self.probe_observations > 0
                    else 0.0
                )
                if good_ratio < self.recovery_threshold:
                    self.trip()
                    return True
        return False

    def should_resume(self) -> bool:
        """Return True if the breaker is ready to transition from OPEN
        to HALF_OPEN (cooldown expired) or from HALF_OPEN to CLOSED
        (probe succeeded).

        One-shot: resets the relevant counters on True.
        """
        if self.state == CircuitBreakerState.OPEN:
            if self.ticks_in_open >= self.cooldown_ticks:
                self._transition(CircuitBreakerState.HALF_OPEN)
                self.probe_observations = 0
                self.probe_good_count = 0
                return True
        if self.state == CircuitBreakerState.HALF_OPEN:
            if self.probe_observations >= self.probe_window:
                good_ratio = (
                    self.probe_good_count / self.probe_observations
                    if self.probe_observations > 0
                    else 0.0
                )
                if good_ratio >= self.recovery_threshold:
                    self._transition(CircuitBreakerState.CLOSED)
                    self.consecutive_bad = 0
                    self.consecutive_good = 0
                    return True
        return False

    def trip(self) -> None:
        """Force-trip the breaker to OPEN regardless of current state."""
        self._transition(CircuitBreakerState.OPEN)
        self.ticks_in_open = 0
        self.consecutive_bad = 0
        self.trip_count += 1

    def reset(self) -> None:
        """Force-reset the breaker to CLOSED."""
        self._transition(CircuitBreakerState.CLOSED)
        self.consecutive_bad = 0
        self.consecutive_good = 0
        self.ticks_in_open = 0
        self.probe_observations = 0
        self.probe_good_count = 0

    def snapshot(self) -> Dict[str, Any]:
        """Return a read-only snapshot of the current state."""
        return {
            "state": self.state.value,
            "consecutive_bad": self.consecutive_bad,
            "consecutive_good": self.consecutive_good,
            "ticks_in_open": self.ticks_in_open,
            "trip_count": self.trip_count,
            "last_health": self.last_health,
            "last_transition": self.last_transition,
            "health_threshold": self.health_threshold,
            "trip_after": self.trip_after,
            "cooldown_ticks": self.cooldown_ticks,
        }

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the full state for persistence."""
        return {
            "state": self.state.value,
            "health_threshold": self.health_threshold,
            "trip_after": self.trip_after,
            "cooldown_ticks": self.cooldown_ticks,
            "probe_window": self.probe_window,
            "recovery_threshold": self.recovery_threshold,
            "consecutive_bad": self.consecutive_bad,
            "consecutive_good": self.consecutive_good,
            "ticks_in_open": self.ticks_in_open,
            "probe_observations": self.probe_observations,
            "probe_good_count": self.probe_good_count,
            "trip_count": self.trip_count,
            "last_health": self.last_health,
            "last_transition": self.last_transition,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CircuitBreaker":
        """Deserialise from a dict produced by ``to_dict()``."""
        cb = cls(
            health_threshold=data.get("health_threshold", DEFAULT_HEALTH_THRESHOLD),
            trip_after=data.get("trip_after", DEFAULT_TRIP_AFTER),
            cooldown_ticks=data.get("cooldown_ticks", DEFAULT_COOLDOWN_TICKS),
            probe_window=data.get("probe_window", DEFAULT_PROBE_WINDOW),
            recovery_threshold=data.get("recovery_threshold", DEFAULT_RECOVERY_THRESHOLD),
        )
        cb.state = CircuitBreakerState(data.get("state", "closed"))
        cb.consecutive_bad = data.get("consecutive_bad", 0)
        cb.consecutive_good = data.get("consecutive_good", 0)
        cb.ticks_in_open = data.get("ticks_in_open", 0)
        cb.probe_observations = data.get("probe_observations", 0)
        cb.probe_good_count = data.get("probe_good_count", 0)
        cb.trip_count = data.get("trip_count", 0)
        cb.last_health = data.get("last_health")
        cb.last_transition = data.get("last_transition")
        return cb

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _transition(self, new_state: CircuitBreakerState) -> None:
        """Record a state transition."""
        old = self.state
        self.state = new_state
        self.last_transition = time.time()
        self.history.append({
            "from": old.value,
            "to": new_state.value,
            "at": self.last_transition,
            "last_health": self.last_health,
        })


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def default_breaker(**overrides: Any) -> CircuitBreaker:
    """Create a ``CircuitBreaker`` with defaults tuned for the IamAI writer.

    Any keyword argument overrides the corresponding constructor parameter.
    """
    return CircuitBreaker(**overrides)
