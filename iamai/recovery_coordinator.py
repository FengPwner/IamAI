"""recovery_coordinator — orchestrate writer recovery end-to-end.

The circuit breaker decides *when* to pause; the novelty injector
decides *what* to inject.  Neither knows about the other.  This
module closes the loop by providing a single coordinator that:

1. feeds health measurements into the circuit breaker,
2. when the breaker trips, selects a novelty prompt and records
   the recovery event,
3. ticks the breaker through its cooldown,
4. evaluates probe results when the breaker enters HALF_OPEN,
5. returns a single ``RecoveryAction`` verdict each tick so the
   caller (caretaker, batch committer, or writer loop) knows
   exactly what to do next.

Recovery action flow
--------------------

::

    tick(health, strokes)
         |
         v
    +- CLOSED ----------------------------------------+
    |  health OK  -> action = CONTINUE                |
    |  health bad -> breaker counts; still CONTINUE   |
    +-------------------------------------------------+
         | (breaker trips after N consecutive bad windows)
         v
    +- OPEN ------------------------------------------+
    |  action = PAUSE (first tick) or WAIT (later)   |
    |  novelty prompt selected and attached            |
    |  breaker ticks toward cooldown expiry            |
    +-------------------------------------------------+
         | (cooldown expires -> HALF_OPEN)
         v
    +- HALF_OPEN -------------------------------------+
    |  action = PROBE                                |
    |  caller unpauses writer for probe_window ticks  |
    |  if health recovers -> CONTINUE (CLOSED)        |
    |  if health drops    -> PAUSE again (re-OPEN)    |
    +-------------------------------------------------+


Public API
----------

- ``RecoveryAction`` -- enum (CONTINUE, PAUSE, WAIT, PROBE, INJECT)
- ``RecoveryEvent`` -- record of a single recovery decision
- ``RecoveryCoordinator`` -- main class
  - ``tick(health, recent_strokes)`` -> ``RecoveryEvent``
  - ``state`` -- current phase
  - ``events`` -- append-only log of all events
  - ``to_dict`` / ``from_dict`` -- serialise for persistence
- ``default_coordinator`` -- factory with tuned defaults

Design choices
--------------

- The coordinator is a **pure decision engine** like the breaker:
  it does not touch pause files, git, or the writer process.
  The caller reads ``RecoveryEvent.action`` and acts on it.
- Novelty prompt selection happens *at trip time*, not at every
  tick while OPEN.  This avoids burning through the prompt pool
  during cooldown.
- Events are append-only and serialisable, providing a full
  audit trail of every recovery decision.
- The coordinator does not import from ``stroke_novelty_injector``
  directly; instead it accepts a ``prompt_selector`` callable at
  construction time.  This keeps the dependency graph acyclic and
  makes testing trivial.

Usage::

    from iamai.recovery_coordinator import default_coordinator

    coord = default_coordinator()
    while True:
        health = measure_diversity()
        event = coord.tick(health, recent_strokes)
        if event.action == RecoveryAction.PAUSE:
            pause_writer()
            log(f"paused: {event.reason}")
        elif event.action == RecoveryAction.PROBE:
            unpause_writer()
        elif event.action == RecoveryAction.CONTINUE:
            pass  # writer running normally
        time.sleep(15)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence

from iamai.writer_circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
    default_breaker,
)


# ---------------------------------------------------------------------------
# Enums and data classes
# ---------------------------------------------------------------------------

class RecoveryAction(str, Enum):
    """What the caller should do this tick."""
    CONTINUE = "continue"   # writer healthy, keep running
    PAUSE = "pause"         # breaker just tripped, pause writer now
    WAIT = "wait"           # breaker OPEN, cooldown in progress
    PROBE = "probe"         # breaker entered HALF_OPEN, tentatively resume
    INJECT = "inject"       # like PAUSE but with a novelty prompt attached

    def __str__(self) -> str:
        return self.value


@dataclass
class RecoveryEvent:
    """Record of a single recovery decision."""
    action: RecoveryAction
    health: float
    breaker_state: str
    at: float = field(default_factory=time.time)
    reason: str = ""
    prompt_text: Optional[str] = None
    consecutive_bad: int = 0
    ticks_in_cooldown: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "action": self.action.value,
            "health": self.health,
            "breaker_state": self.breaker_state,
            "at": self.at,
            "reason": self.reason,
            "consecutive_bad": self.consecutive_bad,
            "ticks_in_cooldown": self.ticks_in_cooldown,
        }
        if self.prompt_text is not None:
            d["prompt_text"] = self.prompt_text
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecoveryEvent":
        return cls(
            action=RecoveryAction(data["action"]),
            health=data["health"],
            breaker_state=data["breaker_state"],
            at=data.get("at", 0.0),
            reason=data.get("reason", ""),
            prompt_text=data.get("prompt_text"),
            consecutive_bad=data.get("consecutive_bad", 0),
            ticks_in_cooldown=data.get("ticks_in_cooldown", 0),
        )


# ---------------------------------------------------------------------------
# Prompt selector type
# ---------------------------------------------------------------------------

# A prompt selector is a callable that takes recent strokes and returns
# a prompt string (or None if the pool is exhausted).
PromptSelector = Callable[[Sequence[str]], Optional[str]]


def _noop_selector(strokes: Sequence[str]) -> Optional[str]:
    """Default selector that never provides a prompt."""
    return None


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

class RecoveryCoordinator:
    """Orchestrate circuit-breaker decisions with optional novelty injection.

    Parameters
    ----------
    breaker : CircuitBreaker, optional
        The circuit breaker to use.  Defaults to ``default_breaker()``.
    prompt_selector : callable, optional
        A function ``(recent_strokes) -> Optional[str]`` that returns
        a novelty prompt or ``None``.  Called once at trip time.
    max_events : int
        Maximum number of events to retain in the history ring.
    """

    def __init__(
        self,
        breaker: Optional[CircuitBreaker] = None,
        prompt_selector: Optional[PromptSelector] = None,
        max_events: int = 1000,
    ) -> None:
        self.breaker = breaker or default_breaker()
        self._prompt_selector = prompt_selector or _noop_selector
        self._max_events = max_events
        self.events: List[RecoveryEvent] = []
        self._last_action: Optional[RecoveryAction] = None
        self._pause_issued = False  # tracks whether PAUSE was already emitted
        self._probe_issued = False  # tracks whether PROBE was already emitted

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def tick(
        self,
        health: float,
        recent_strokes: Optional[Sequence[str]] = None,
    ) -> RecoveryEvent:
        """Feed a health measurement and get back a recovery verdict.

        This method drives the full breaker lifecycle:
        1. observe(health) to update counters
        2. should_pause() to check for trip conditions
        3. tick() to advance cooldown clock in OPEN state
        4. should_resume() to check for cooldown expiry or probe success

        Parameters
        ----------
        health : float
            Current diversity ratio (0.0-1.0).
        recent_strokes : sequence of str, optional
            Recent stroke texts, used by the prompt selector at trip time.

        Returns
        -------
        RecoveryEvent
            The action the caller should take this tick.
        """
        strokes = recent_strokes or []
        prev_state = self.breaker.state

        # Step 1: Feed health into the breaker.
        self.breaker.observe(health)

        # Step 2: Check if breaker should trip (CLOSED->OPEN or HALF_OPEN->OPEN).
        if self.breaker.should_pause():
            # Breaker just tripped to OPEN.
            self._pause_issued = True
            self._probe_issued = False
            prompt = self._prompt_selector(strokes)
            action = RecoveryAction.INJECT if prompt else RecoveryAction.PAUSE
            event = RecoveryEvent(
                action=action,
                health=health,
                breaker_state=CircuitBreakerState.OPEN.value,
                reason=f"breaker tripped: health={health:.3f}",
                prompt_text=prompt,
                consecutive_bad=self.breaker.consecutive_bad,
            )
        # Step 3 & 4: If in OPEN, tick cooldown and check for resume.
        elif self.breaker.state == CircuitBreakerState.OPEN:
            self.breaker.tick()
            if self.breaker.should_resume():
                # Cooldown expired, transitioning to HALF_OPEN.
                self._probe_issued = True
                event = RecoveryEvent(
                    action=RecoveryAction.PROBE,
                    health=health,
                    breaker_state=CircuitBreakerState.HALF_OPEN.value,
                    reason="cooldown expired, entering probe",
                    ticks_in_cooldown=0,
                )
            else:
                # Still in cooldown.
                event = RecoveryEvent(
                    action=RecoveryAction.WAIT,
                    health=health,
                    breaker_state=CircuitBreakerState.OPEN.value,
                    reason=f"cooldown: tick {self.breaker.ticks_in_open}/{self.breaker.cooldown_ticks}",
                    ticks_in_cooldown=self.breaker.ticks_in_open,
                )
        # Step 4b: If in HALF_OPEN, check if probe succeeded or failed.
        elif self.breaker.state == CircuitBreakerState.HALF_OPEN:
            if self.breaker.should_resume():
                # Probe succeeded -> CLOSED.
                self._pause_issued = False
                self._probe_issued = False
                event = RecoveryEvent(
                    action=RecoveryAction.CONTINUE,
                    health=health,
                    breaker_state=CircuitBreakerState.CLOSED.value,
                    reason="probe succeeded, recovered",
                    consecutive_bad=0,
                )
            elif self.breaker.state == CircuitBreakerState.OPEN:
                # should_resume() may have re-tripped the breaker.
                self._pause_issued = True
                self._probe_issued = False
                prompt = self._prompt_selector(strokes)
                action = RecoveryAction.INJECT if prompt else RecoveryAction.PAUSE
                event = RecoveryEvent(
                    action=action,
                    health=health,
                    breaker_state=CircuitBreakerState.OPEN.value,
                    reason="probe failed, re-tripped",
                    prompt_text=prompt,
                    consecutive_bad=self.breaker.consecutive_bad,
                )
            else:
                # Still probing.
                event = RecoveryEvent(
                    action=RecoveryAction.PROBE,
                    health=health,
                    breaker_state=CircuitBreakerState.HALF_OPEN.value,
                    reason="probe ongoing",
                )
        # CLOSED: normal operation.
        else:
            self._pause_issued = False
            self._probe_issued = False
            event = RecoveryEvent(
                action=RecoveryAction.CONTINUE,
                health=health,
                breaker_state=CircuitBreakerState.CLOSED.value,
                consecutive_bad=self.breaker.consecutive_bad,
            )

        # Append to history.
        self.events.append(event)
        if len(self.events) > self._max_events:
            self.events = self.events[-self._max_events:]

        self._last_action = event.action
        return event

    @property
    def state(self) -> str:
        """Current breaker state as a string."""
        return self.breaker.state.value

    @property
    def total_pauses(self) -> int:
        """Number of PAUSE or INJECT events issued."""
        return sum(
            1 for e in self.events
            if e.action in (RecoveryAction.PAUSE, RecoveryAction.INJECT)
        )

    @property
    def total_probes(self) -> int:
        """Number of PROBE events issued."""
        return sum(1 for e in self.events if e.action == RecoveryAction.PROBE)

    @property
    def recovery_rate(self) -> float:
        """Fraction of probes that led to full recovery (CLOSED).

        Returns 0.0 if no probes have been issued.
        """
        probes = self.total_probes
        if probes == 0:
            return 0.0
        # Count CONTINUE events that follow a PROBE.
        recoveries = 0
        for i, ev in enumerate(self.events):
            if (
                ev.action == RecoveryAction.CONTINUE
                and i > 0
                and self.events[i - 1].breaker_state == CircuitBreakerState.HALF_OPEN.value
            ):
                recoveries += 1
        return recoveries / probes

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "breaker": self.breaker.to_dict(),
            "events": [e.to_dict() for e in self.events[-50:]],  # last 50
            "max_events": self._max_events,
            "last_action": self._last_action.value if self._last_action else None,
            "pause_issued": self._pause_issued,
            "probe_issued": self._probe_issued,
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        prompt_selector: Optional[PromptSelector] = None,
    ) -> "RecoveryCoordinator":
        breaker = CircuitBreaker.from_dict(data["breaker"])
        coord = cls(
            breaker=breaker,
            prompt_selector=prompt_selector,
            max_events=data.get("max_events", 1000),
        )
        coord.events = [RecoveryEvent.from_dict(e) for e in data.get("events", [])]
        la = data.get("last_action")
        coord._last_action = RecoveryAction(la) if la else None
        coord._pause_issued = data.get("pause_issued", False)
        coord._probe_issued = data.get("probe_issued", False)
        return coord

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_prompt(self, strokes: Sequence[str]) -> Optional[str]:
        """Safely invoke the prompt selector."""
        try:
            return self._prompt_selector(strokes)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def default_coordinator(**overrides: Any) -> RecoveryCoordinator:
    """Create a ``RecoveryCoordinator`` with defaults tuned for the IamAI writer."""
    breaker_kwargs = {}
    for k in ("trip_after", "cooldown_ticks", "health_threshold",
              "probe_window", "recovery_threshold"):
        if k in overrides:
            breaker_kwargs[k] = overrides[k]
    breaker = default_breaker(**breaker_kwargs)
    prompt_selector = overrides.get("prompt_selector")
    return RecoveryCoordinator(
        breaker=breaker,
        prompt_selector=prompt_selector,
        max_events=overrides.get("max_events", 1000),
    )
