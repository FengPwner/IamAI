"""Debounce a callable — fire only after a quiet period, no threads."""

import time
from typing import Callable, TypeVar

T = TypeVar("T")


class Debouncer:
    """Hold back repeated calls; invoke only after `delay` seconds of silence.

    >>> import time as _t
    >>> calls = []
    >>> d = Debouncer(lambda: calls.append(1), delay=0.05, sleep=lambda _: None)
    >>> d(); d(); d()          # three rapid calls -> nothing fires yet
    >>> len(calls)
    0
    >>> _t.sleep(0.06)         # real sleep here; test uses sleep=lambda _:None
    >>> d()                     # quiet period elapsed -> fires once
    >>> len(calls)
    1
    """

    def __init__(
        self,
        fn: Callable[[], T],
        *,
        delay: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if delay < 0:
            raise ValueError("delay must be >= 0")
        self._fn = fn
        self._delay = delay
        self._sleep = sleep
        self._last_call: float | None = None
        self._pending = False

    def __call__(self) -> T | None:
        now = time.monotonic()
        if self._pending and self._last_call is not None:
            elapsed = now - self._last_call
            if elapsed < self._delay:
                # still within the quiet window, suppress
                self._last_call = now
                return None
            # quiet period passed — fire the previous pending call
            self._pending = False
            result = self._fn()
            self._last_call = now
            self._pending = True
            return result

        self._last_call = now
        self._pending = True
        return None

    def flush(self) -> T | None:
        """Force-fire if there is a pending call, regardless of timing."""
        if self._pending:
            self._pending = False
            return self._fn()
        return None
