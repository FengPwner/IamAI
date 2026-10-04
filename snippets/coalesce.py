"""057 — coalesce: merge rapid-fire events into one callback per window.

the batch committer in this repo faces a scheduling problem: strokes arrive
every 15 seconds, but committing every 15 seconds is wasteful (and pushes are
expensive). coalesce solves the general form — collect events, fire once when
the window closes.

debounce resets its timer on every new event (fire after quiet). coalesce does
not reset: it opens a window on the first event and closes it after `window`
seconds, regardless of how many events arrive in between.

    first event ───── window ───── fire
    │  │  │  │  │                   │
    ▼  ▼  ▼  ▼  ▼                   ▼
    collect, collect, collect     deliver all at once

zero dependencies. stdlib only. the callback receives the full batch.

>>> results = []
>>> c = Coalescer(lambda batch: results.append(batch), window=1.0, clock=lambda: 0.0)
>>> c.add("a")                     # opens the window
>>> c.add("b")                     # still inside
>>> c.tick(clock=lambda: 0.5)      # half the window elapsed
>>> c.add("c")                     # still inside
>>> len(results)
0
>>> c.tick(clock=lambda: 1.1)      # window expired
>>> results
[['a', 'b', 'c']]
"""

from __future__ import annotations

from typing import Any, Callable


class Coalescer:
    """Collect events; deliver as a batch after a fixed time window.

    Parameters
    ----------
    callback : callable
        Receives a list of accumulated items when the window closes.
    window : float
        Window duration in seconds (must be >= 0).
    clock : callable, optional
        Returns the current time. Defaults to ``time.monotonic``.
        Override for deterministic tests.
    """

    def __init__(
        self,
        callback: Callable[[list[Any]], None],
        *,
        window: float = 10.0,
        clock: Callable[[], float] | None = None,
    ):
        if window < 0:
            raise ValueError("window must be >= 0")
        self._callback = callback
        self._window = window
        self._clock = clock or self._default_clock
        self._batch: list[Any] = []
        self._window_start: float | None = None

    # -- public API ----------------------------------------------------------

    def add(self, item: Any) -> bool:
        """Add an item. Opens the window if this is the first item.

        Returns True if the window just opened (first item), False otherwise.
        """
        first = not self._batch and self._window_start is None
        self._batch.append(item)
        if self._window_start is None:
            self._window_start = self._clock()
        return first

    def tick(self, *, clock: Callable[[], float] | None = None) -> list[Any] | None:
        """Check if the window has expired. If so, deliver the batch and return it.

        Returns None if the window is still open or there are no items.
        Accepts an optional clock override for inline testing.
        """
        if not self._batch or self._window_start is None:
            return None
        now_fn = clock or self._clock
        elapsed = now_fn() - self._window_start
        if elapsed >= self._window:
            delivered = list(self._batch)
            self._batch.clear()
            self._window_start = None
            self._callback(list(delivered))
            return delivered
        return None

    def flush(self) -> list[Any] | None:
        """Deliver the current batch immediately, regardless of timing."""
        if not self._batch:
            return None
        delivered = list(self._batch)
        self._batch.clear()
        self._window_start = None
        self._callback(list(delivered))
        return delivered

    @property
    def pending(self) -> int:
        """Number of items currently buffered."""
        return len(self._batch)

    @property
    def window_open(self) -> bool:
        """True if a window is currently open (items buffered, not yet delivered)."""
        return self._window_start is not None and bool(self._batch)

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _default_clock() -> float:
        import time
        return time.monotonic()
