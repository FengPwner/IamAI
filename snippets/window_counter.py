"""Sliding-window counter — track event rates without storing every timestamp."""

from __future__ import annotations

import time
from collections import deque
from typing import Callable


class WindowCounter:
    """Count events within a sliding time window.

    Keeps only timestamps inside the window, evicting stale ones on each
    call to ``tick`` or ``count``.  Useful for rate-limiting dashboards,
    cadence monitors, or any "how many things happened in the last N
    seconds?" question.

    >>> c = WindowCounter(window=5.0, clock=lambda: 100.0)
    >>> c.tick(); c.tick(); c.tick()
    >>> c.count()
    3
    """

    def __init__(
        self,
        *,
        window: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if window <= 0:
            raise ValueError("window must be > 0")
        self._window = window
        self._clock = clock
        self._timestamps: deque[float] = deque()

    def tick(self, n: int = 1) -> None:
        """Record *n* events at the current time."""
        if n < 1:
            raise ValueError("n must be >= 1")
        now = self._clock()
        self._timestamps.extend([now] * n)
        self._evict()

    def count(self) -> int:
        """Return the number of events within the current window."""
        self._evict()
        return len(self._timestamps)

    def rate(self) -> float:
        """Events per second over the current window.

        Returns 0.0 when the window is empty.
        """
        c = self.count()
        if c == 0:
            return 0.0
        if len(self._timestamps) < 2:
            return c / self._window
        span = self._timestamps[-1] - self._timestamps[0]
        effective = max(span, self._window)
        return c / effective

    @property
    def window(self) -> float:
        return self._window

    def reset(self) -> None:
        """Drop all recorded timestamps."""
        self._timestamps.clear()

    # -- internal --

    def _evict(self) -> None:
        cutoff = self._clock() - self._window
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()
