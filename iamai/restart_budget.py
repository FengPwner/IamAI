"""Track process restart frequency to prevent infinite restart loops.

The caretaker restarts writer and batch when they die. But if a process
crashes immediately after every restart, the caretaker becomes a tight
loop of kill-start-kill-start that burns resources and floods logs.

This module maintains a sliding window of restart timestamps per
process kind and answers one question: *should we restart again?*

Policy:

- **budget**: at most ``max_restarts`` (default 5) within ``window_seconds``
  (default 1800 = 30 min).
- **exhausted**: the window is full — refuse to restart, alert the human.
- **reset**: after the window elapses with no restarts, the budget refills
  automatically (no manual intervention needed).

Usage::

    from iamai.restart_budget import RestartBudget

    b = RestartBudget(max_restarts=5, window_seconds=1800)
    b.record()  # just restarted
    b.allow()   # True — still within budget
    # ... 5 more restarts within 30 min ...
    b.allow()   # False — budget exhausted, escalate

The budget is intentionally in-memory. A process that survives long enough
for the window to slide past earns a fresh start. State files would
persist failures across reboots where the underlying bug may already be
fixed.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque


@dataclass
class RestartBudget:
    """Sliding-window restart rate limiter.

    Args:
        max_restarts: maximum restarts allowed within the window
        window_seconds: window size in seconds
    """

    max_restarts: int = 5
    window_seconds: int = 1800
    _timestamps: Deque[float] = field(default_factory=deque)

    def _prune(self, now: float) -> None:
        """Remove timestamps older than the window."""
        cutoff = now - self.window_seconds
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()

    def record(self, timestamp: float | None = None) -> None:
        """Record a restart event.

        Args:
            timestamp: epoch seconds; defaults to ``time.time()``
        """
        ts = timestamp if timestamp is not None else time.time()
        self._timestamps.append(ts)

    def allow(self, now: float | None = None) -> bool:
        """Check whether another restart is permitted.

        Does NOT consume a slot — call ``record()`` after actually
        restarting.

        Args:
            now: current epoch seconds; defaults to ``time.time()``

        Returns:
            True if the budget has room, False if exhausted.
        """
        current = now if now is not None else time.time()
        self._prune(current)
        return len(self._timestamps) < self.max_restarts

    def remaining(self, now: float | None = None) -> int:
        """How many restarts are left in the current window."""
        current = now if now is not None else time.time()
        self._prune(current)
        return max(0, self.max_restarts - len(self._timestamps))

    def count(self, now: float | None = None) -> int:
        """How many restarts are in the current window."""
        current = now if now is not None else time.time()
        self._prune(current)
        return len(self._timestamps)

    def summary(self, now: float | None = None) -> str:
        """One-line human-readable budget status."""
        current = now if now is not None else time.time()
        n = self.count(current)
        left = self.remaining(current)
        if left == 0:
            return f"EXHAUSTED: {n}/{self.max_restarts} restarts in {self.window_seconds}s — escalate"
        return f"{left}/{self.max_restarts} restarts remaining (window {self.window_seconds}s)"

    def reset(self) -> None:
        """Clear all recorded restarts. Use after manual intervention."""
        self._timestamps.clear()
