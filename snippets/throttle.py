"""Throttle a callable — at most one invocation per interval, no threads."""

import time
from typing import Callable, TypeVar

T = TypeVar("T")


class Throttle:
    """Allow `fn` to fire at most once every `interval` seconds.

    Unlike Debouncer (which waits for silence), Throttle fires immediately on
    the first call and then suppresses until the interval elapses.

    >>> calls = []
    >>> t = Throttle(lambda: calls.append(1), interval=2.0)
    >>> t()   # first call always fires
    True
    >>> t()   # immediate second call is suppressed
    False
    >>> len(calls)
    1
    """

    def __init__(
        self,
        fn: Callable[[], T],
        *,
        interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if interval < 0:
            raise ValueError("interval must be >= 0")
        self._fn = fn
        self._interval = interval
        self._clock = clock
        self._last_fire: float | None = None

    def __call__(self) -> bool:
        """Try to fire. Returns True if fn was called, False if throttled."""
        now = self._clock()
        if self._last_fire is not None and (now - self._last_fire) < self._interval:
            return False
        self._last_fire = now
        self._fn()
        return True

    @property
    def remaining(self) -> float:
        """Seconds until the next call would be allowed."""
        if self._last_fire is None:
            return 0.0
        elapsed = self._clock() - self._last_fire
        return max(0.0, self._interval - elapsed)
