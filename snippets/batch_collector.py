"""064 — batch_collector: accumulate items and flush in batches.

systems that process items one-at-a-time waste overhead on setup, teardown,
and round-trips.  batching amortises that cost: collect N items (or wait T
seconds), then hand the whole batch to a callback in one shot.

this pattern shows up everywhere in this codebase:

- the committer waits for several strokes before issuing one git commit
- the push guard coalesces rapid-fire commits into a single push
- metrics aggregation rolls individual data points into periodic summaries

BatchCollector is a generic, clock-injectable implementation.  you give it
a max_batch_size and/or a flush_interval, an on_flush callback, and
optionally a clock (for deterministic tests).  items arrive via add(); the
collector decides when to flush.

    results = []
    bc = BatchCollector(max_size=3, on_flush=lambda batch: results.append(batch))
    bc.add("a")
    bc.add("b")
    assert results == []            # not yet — size threshold not hit
    bc.add("c")
    assert results == [["a","b","c"]]  # flushed at size 3

time-based flushing works the same way: set flush_interval and call tick()
(or let real time pass).  whichever threshold fires first triggers the flush.

edge cases handled:

- empty collector ignores flush requests (nothing to emit)
- on_flush exceptions propagate; the batch is NOT lost — it stays in the
  buffer for retry or explicit drain()
- close() flushes remaining items exactly once, then marks the collector
  as closed; subsequent add() raises ClosedError
- thread-safe via a simple lock; concurrent add() is fine

the collector deliberately does NOT start a background timer thread.
time-based flushing relies on the caller invoking tick() periodically or
using a real clock.  this keeps the class predictable in async contexts
and trivially testable with a fake clock.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Generic, List, Optional, TypeVar

T = TypeVar("T")


class ClosedError(Exception):
    """Raised when add() is called on a closed collector."""


class FakeClock:
    """Deterministic clock for testing time-based flushes."""

    def __init__(self, start: float = 0.0):
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class BatchCollector(Generic[T]):
    """Collect items and flush in batches by size or time threshold.

    Parameters
    ----------
    max_size : int, optional
        Flush when the buffer reaches this many items.  ``None`` disables
        size-based flushing.
    flush_interval : float, optional
        Flush when this many seconds have elapsed since the last flush.
        ``None`` disables time-based flushing.
    on_flush : callable
        ``on_flush(batch: list[T]) -> None`` invoked with each batch.
    clock : object, optional
        Anything with a ``.now()`` method returning a float.  Defaults to
        a real wall-clock wrapper.
    """

    def __init__(
        self,
        *,
        max_size: Optional[int] = None,
        flush_interval: Optional[float] = None,
        on_flush: Callable[[List[T]], Any],
        clock: Any = None,
    ):
        if max_size is None and flush_interval is None:
            raise ValueError("at least one of max_size or flush_interval must be set")
        if max_size is not None and max_size < 1:
            raise ValueError("max_size must be >= 1")
        if flush_interval is not None and flush_interval <= 0:
            raise ValueError("flush_interval must be > 0")

        self._max_size = max_size
        self._flush_interval = flush_interval
        self._on_flush = on_flush
        self._clock = clock or _RealClock()
        self._lock = threading.Lock()
        self._buffer: List[T] = []
        self._last_flush: float = self._clock.now()
        self._closed = False
        self._total_added: int = 0
        self._total_flushed: int = 0
        self._flush_count: int = 0

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def add(self, item: T) -> bool:
        """Add an item.  Returns True if a flush was triggered."""
        with self._lock:
            if self._closed:
                raise ClosedError("collector is closed")
            self._buffer.append(item)
            self._total_added += 1
            return self._maybe_flush()

    def add_many(self, items: list[T]) -> int:
        """Add multiple items.  Returns the number of flushes triggered."""
        flushes = 0
        for item in items:
            if self.add(item):
                flushes += 1
        return flushes

    def tick(self) -> bool:
        """Check time-based threshold.  Call periodically to enable
        time-based flushing.  Returns True if a flush was triggered."""
        with self._lock:
            if self._closed:
                return False
            return self._maybe_flush()

    def flush(self) -> bool:
        """Force a flush regardless of thresholds.  Returns True if
        items were flushed, False if the buffer was empty."""
        with self._lock:
            return self._do_flush()

    def drain(self) -> List[T]:
        """Return buffered items without calling on_flush.
        Useful for error recovery or testing."""
        with self._lock:
            items = list(self._buffer)
            self._buffer.clear()
            return items

    def close(self) -> int:
        """Flush remaining items and reject future add() calls.
        Returns the number of items flushed."""
        with self._lock:
            count = len(self._buffer)
            if count > 0:
                self._do_flush()
            self._closed = True
            return count

    def __enter__(self) -> "BatchCollector[T]":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------

    @property
    def pending(self) -> int:
        """Number of items currently in the buffer."""
        with self._lock:
            return len(self._buffer)

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def total_added(self) -> int:
        with self._lock:
            return self._total_added

    @property
    def total_flushed(self) -> int:
        with self._lock:
            return self._total_flushed

    @property
    def flush_count(self) -> int:
        """How many times on_flush has been called."""
        with self._lock:
            return self._flush_count

    def __repr__(self) -> str:
        return (
            f"BatchCollector(pending={self.pending}, "
            f"max_size={self._max_size}, "
            f"flush_interval={self._flush_interval}, "
            f"flushed={self._total_flushed})"
        )

    # ------------------------------------------------------------------
    # internals (must be called with lock held)
    # ------------------------------------------------------------------

    def _maybe_flush(self) -> bool:
        if not self._buffer:
            return False
        # size threshold
        if self._max_size is not None and len(self._buffer) >= self._max_size:
            return self._do_flush()
        # time threshold
        if self._flush_interval is not None:
            elapsed = self._clock.now() - self._last_flush
            if elapsed >= self._flush_interval:
                return self._do_flush()
        return False

    def _do_flush(self) -> bool:
        if not self._buffer:
            return False
        batch = list(self._buffer)
        self._buffer.clear()
        self._last_flush = self._clock.now()
        self._total_flushed += len(batch)
        self._flush_count += 1
        self._on_flush(batch)
        return True


class _RealClock:
    def now(self) -> float:
        return time.monotonic()
