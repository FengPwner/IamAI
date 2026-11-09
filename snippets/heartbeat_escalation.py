"""582 — heartbeat_escalation: tiered alerts when a process stops responding.

a single missed heartbeat is noise. three in a row is a pattern. ten is a
crisis. this module turns silence into escalating severity levels so that
supervisors can match response intensity to problem duration.

    ●────────●────────●────────○────────○────────○────────○
    OK      OK      OK    YELLOW    YELLOW     RED      RED
   (ping)  (ping)  (ping) (miss 1) (miss 2)  (miss 3) (miss 4)

the design philosophy: thresholds are configurable, but the escalation
curve is fixed — each level is strictly worse than the one before it.
there is no de-escalation without a fresh ping. this mirrors how real
incidents work: once things are bad, only fixing them makes them better.

    ping ── miss ── miss ── miss ── ping
     │       │       │       │       │
     ▼       ▼       ▼       ▼       ▼
    OK    YELLOW   YELLOW    RED     OK
                      ▲               │
                      └── level ratchets up
                          until a ping arrives

zero dependencies. stdlib only.

>>> h = HeartbeatEscalation(
...     yellow_after=2, red_after=4, critical_after=6,
...     clock=lambda: 0.0,
... )
>>> h.level
'ok'
>>> h.miss()  # miss 1
'ok'
>>> h.miss()  # miss 2
'yellow'
>>> h.miss()  # miss 3
'yellow'
>>> h.miss()  # miss 4
'red'
>>> h.ping()  # reset
'ok'

escalation history is preserved for post-mortem:

>>> h2 = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
>>> h2.miss()
'yellow'
>>> h2.miss()
'red'
>>> h2.miss()
'critical'
>>> h2.history
['yellow', 'red', 'critical']
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional


LEVELS = ("ok", "yellow", "red", "critical")


class HeartbeatEscalation:
    """Tiered alert escalation driven by consecutive missed heartbeats."""

    __slots__ = (
        "_yellow_after",
        "_red_after",
        "_critical_after",
        "_consecutive_misses",
        "_level",
        "_level_index",
        "_history",
        "_clock",
    )

    def __init__(
        self,
        yellow_after: int = 2,
        red_after: int = 4,
        critical_after: int = 8,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if yellow_after < 1:
            raise ValueError("yellow_after must be >= 1")
        if red_after <= yellow_after:
            raise ValueError("red_after must be > yellow_after")
        if critical_after <= red_after:
            raise ValueError("critical_after must be > red_after")

        self._yellow_after = yellow_after
        self._red_after = red_after
        self._critical_after = critical_after
        self._consecutive_misses = 0
        self._level = "ok"
        self._level_index = 0
        self._history: List[str] = []
        self._clock = clock or time.monotonic

    # -- public API ---------------------------------------------------------

    @property
    def level(self) -> str:
        """Current escalation level."""
        return self._level

    @property
    def consecutive_misses(self) -> int:
        """Number of consecutive missed heartbeats since last ping."""
        return self._consecutive_misses

    @property
    def history(self) -> List[str]:
        """Ordered list of escalation events (level-ups only)."""
        return list(self._history)

    def miss(self) -> str:
        """Record a missed heartbeat. Returns the (possibly escalated) level."""
        self._consecutive_misses += 1
        new_level = self._compute_level()
        if LEVELS.index(new_level) > self._level_index:
            self._level_index = LEVELS.index(new_level)
            self._level = new_level
            self._history.append(new_level)
        return self._level

    def ping(self) -> str:
        """Record a successful heartbeat. Resets to ok."""
        self._consecutive_misses = 0
        if self._level != "ok":
            self._history.append("ok")
        self._level = "ok"
        self._level_index = 0
        return "ok"

    def seconds_since(self, last_ping_time: float) -> float:
        """How long since the last ping, using the configured clock."""
        return self._clock() - last_ping_time

    def __repr__(self) -> str:
        return (
            f"HeartbeatEscalation(level={self._level!r}, "
            f"misses={self._consecutive_misses})"
        )

    # -- internals ----------------------------------------------------------

    def _compute_level(self) -> str:
        m = self._consecutive_misses
        if m >= self._critical_after:
            return "critical"
        if m >= self._red_after:
            return "red"
        if m >= self._yellow_after:
            return "yellow"
        return "ok"
