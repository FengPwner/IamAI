"""583 — escalation_relay: wire heartbeat escalation to supervisor actions.

heartbeat_escalation records severity changes beautifully — but it only
records them. if nobody reads the history, the escalation is invisible.
this module closes the loop: it watches an escalation instance and fires
a registered callback whenever the level changes, so the supervisor can
actually *do* something.

the relay is intentionally dumb:

    escalation ──► relay ──► callback(level, misses, timestamp)
                    │
                    └── if the callback raises, log it and keep going.
                        the show must go on.

design decisions:

  1. **poll, don't wrap.** the relay does not monkey-patch miss()/ping().
     it polls the escalation's current level on a configurable tick. this
     means you can drop it onto any existing escalation instance without
     rewiring the call sites.

  2. **deduplicate transitions.** firing the callback on every poll while
     the level stays "red" would spam the supervisor. the relay only fires
     on actual transitions (ok→yellow, yellow→red, red→ok, etc.).

  3. **callback failures are isolated.** a broken callback must not kill
     the relay. exceptions are caught, counted, and surfaced via
     `error_count` for monitoring — but the relay keeps running.

  4. **suppress_during_ok.** by default the relay does not fire when the
     level is "ok". set `fire_on_ok=True` to override (useful for
     integration tests and audit trails).

zero dependencies beyond heartbeat_escalation. stdlib only.

>>> from heartbeat_escalation import HeartbeatEscalation
>>> events = []
>>> relay = EscalationRelay(
...     EscalationDemo(),
...     callback=lambda lvl, m, ts: events.append((lvl, m)),
... )
>>> relay.tick()  # level=ok, no fire by default
>>> relay.esc.miss()
'yellow'
>>> relay.tick()
>>> events
[('yellow', 1)]
>>> relay.esc.miss()
'red'
>>> relay.tick()
>>> events
[('yellow', 1), ('red', 2)]
>>> relay.esc.ping()
'ok'
>>> relay.tick()
>>> events
[('yellow', 1), ('red', 2), ('ok', 0)]
"""

from __future__ import annotations

import time
from typing import Any, Callable, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from heartbeat_escalation import HeartbeatEscalation

# callback signature: (level: str, consecutive_misses: int, timestamp: float) -> Any
EscalationCallback = Callable[[str, int, float], Any]


class EscalationRelay:
    """Bridge between HeartbeatEscalation and supervisor callbacks."""

    __slots__ = (
        "_esc",
        "_callback",
        "_last_level",
        "_fire_on_ok",
        "_error_count",
        "_tick_count",
        "_last_fire_time",
        "_clock",
        "_transitions",
    )

    def __init__(
        self,
        escalation: "HeartbeatEscalation",
        callback: EscalationCallback,
        fire_on_ok: bool = False,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if callback is None:
            raise ValueError("callback must not be None")

        self._esc = escalation
        self._callback = callback
        self._last_level: str = escalation.level
        self._fire_on_ok = fire_on_ok
        self._error_count: int = 0
        self._tick_count: int = 0
        self._last_fire_time: Optional[float] = None
        self._clock = clock or time.monotonic
        self._transitions: List[tuple] = []

    # -- public API ---------------------------------------------------------

    @property
    def esc(self) -> "HeartbeatEscalation":
        """The underlying escalation instance."""
        return self._esc

    @property
    def error_count(self) -> int:
        """Number of callback invocations that raised exceptions."""
        return self._error_count

    @property
    def tick_count(self) -> int:
        """Total number of tick() calls."""
        return self._tick_count

    @property
    def last_fire_time(self) -> Optional[float]:
        """Timestamp of the last callback fire, or None if never fired."""
        return self._last_fire_time

    @property
    def transitions(self) -> List[tuple]:
        """List of (from_level, to_level, timestamp) transitions observed."""
        return list(self._transitions)

    def tick(self) -> bool:
        """Poll the escalation level and fire callback on transition.

        Returns True if the callback was fired, False otherwise.
        """
        self._tick_count += 1
        current = self._esc.level

        if current == self._last_level:
            return False

        # level changed — record transition
        from_level = self._last_level
        self._last_level = current
        now = self._clock()
        self._transitions.append((from_level, current, now))

        # suppress ok unless explicitly enabled
        if current == "ok" and not self._fire_on_ok:
            return False

        self._fire_callback(current, now)
        return True

    def force_fire(self) -> None:
        """Force-fire the callback with the current state, regardless of transition.

        Useful for supervisor startup: "tell me the state right now even if
        nothing changed."
        """
        now = self._clock()
        self._fire_callback(self._esc.level, now)

    def reset(self) -> None:
        """Reset the relay's internal tracking. Does NOT reset the escalation."""
        self._last_level = self._esc.level
        self._error_count = 0
        self._tick_count = 0
        self._last_fire_time = None
        self._transitions.clear()

    def __repr__(self) -> str:
        return (
            f"EscalationRelay(level={self._esc.level!r}, "
            f"ticks={self._tick_count}, errors={self._error_count}, "
            f"transitions={len(self._transitions)})"
        )

    # -- internals ----------------------------------------------------------

    def _fire_callback(self, level: str, timestamp: float) -> None:
        try:
            self._callback(level, self._esc.consecutive_misses, timestamp)
            self._last_fire_time = timestamp
        except Exception:
            self._error_count += 1
            self._last_fire_time = timestamp


# ---------------------------------------------------------------------------
# demo helper for docstring (not exported)
# ---------------------------------------------------------------------------

class EscalationDemo:
    """Minimal HeartbeatEscalation stand-in for doctest."""

    def __init__(self) -> None:
        self.level = "ok"
        self.consecutive_misses = 0

    def miss(self) -> str:
        self.consecutive_misses += 1
        if self.consecutive_misses >= 2:
            self.level = "red"
        elif self.consecutive_misses >= 1:
            self.level = "yellow"
        return self.level

    def ping(self) -> str:
        self.consecutive_misses = 0
        self.level = "ok"
        return "ok"
