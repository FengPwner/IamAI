"""058 — deadman: a dead man's switch for processes that fail silently.

the writer in this repo dies without a sound. no crash, no traceback, no exit
code — just silence. the commit log stops and nobody notices for hours. a dead
man's switch solves this: you must ping it before the timeout, or it declares
you dead.

the design is deliberately minimal: no threads, no signals, no subprocesses.
the caller is responsible for checking. this keeps it composable — you can wire
it into a heartbeat probe, a supervisor loop, or a cron job.

    ping ─── ping ─── ping ─── (silence) ─── EXPIRED
     │        │        │                        │
     ▼        ▼        ▼                        ▼
   reset    reset    reset                  check() → True

zero dependencies. stdlib only.

>>> d = Deadman(timeout=10.0, clock=lambda: 0.0)
>>> d.ping(clock=lambda: 0.0)
>>> d.alive(clock=lambda: 5.0)
True
>>> d.alive(clock=lambda: 10.0)
True
>>> d.alive(clock=lambda: 10.1)
False
>>> d.expired(clock=lambda: 10.1)
True
>>> d.seconds_since_ping(clock=lambda: 10.1)
10.1

the switch also tracks consecutive pings and total pings for observability:

>>> d2 = Deadman(timeout=5.0, clock=lambda: 0.0)
>>> d2.ping(clock=lambda: 0.0)
>>> d2.ping(clock=lambda: 1.0)
>>> d2.ping(clock=lambda: 2.0)
>>> d2.total_pings
3
"""

from __future__ import annotations

import time
from typing import Callable


class Deadman:
    """Dead man's switch: expires if not pinged within timeout seconds."""

    def __init__(
        self,
        timeout: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if timeout <= 0:
            raise ValueError("timeout must be > 0")
        self._timeout = timeout
        self._last_ping: float | None = None
        self.total_pings: int = 0
        # record the initial creation time so check() before any ping is honest
        self._created = clock()

    @property
    def timeout(self) -> float:
        return self._timeout

    def ping(self, clock: Callable[[], float] = time.monotonic) -> None:
        """Record a heartbeat."""
        self._last_ping = clock()
        self.total_pings += 1

    def seconds_since_ping(self, clock: Callable[[], float] = time.monotonic) -> float:
        """Seconds since the last ping, or since creation if never pinged."""
        ref = self._last_ping if self._last_ping is not None else self._created
        return clock() - ref

    def alive(self, clock: Callable[[], float] = time.monotonic) -> bool:
        """True if the last ping is within timeout."""
        return self.seconds_since_ping(clock) <= self._timeout

    def expired(self, clock: Callable[[], float] = time.monotonic) -> bool:
        """True if the last ping exceeded timeout."""
        return not self.alive(clock)

    def reset(self, clock: Callable[[], float] = time.monotonic) -> None:
        """Reset the switch as if freshly created, clearing ping state."""
        self._last_ping = None
        self._created = clock()
        self.total_pings = 0

    def __repr__(self) -> str:
        state = "alive" if self._last_ping is not None else "never-pinged"
        return (
            f"Deadman(timeout={self._timeout}, state={state}, "
            f"pings={self.total_pings})"
        )
