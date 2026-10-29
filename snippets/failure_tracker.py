"""067 — failure_tracker: detect consecutive failures and emit alerts.

the problem recurs everywhere: a push fails, a health probe times out, a
deploy key stops working.  each subsystem reinvents the same logic —
count failures, compare against a threshold, decide whether to shout.

this snippet centralises that pattern.  ``FailureTracker`` is a
lightweight, thread-safe counter that:

- **records** successes and failures (``record(ok=True|False)``)
- **alerts** when consecutive failures reach a configurable threshold
- **resets** on success — one green probe clears the alarm
- **remembers** the timestamp of the first failure in the current streak

the design is deliberately minimal.  no async, no callbacks, no plugin
system.  if you need to fire a webhook on threshold breach, wrap
``record()`` in a function that checks ``alerting`` and does the I/O.

thread safety comes from a ``threading.Lock`` around every state mutation.
the lock is never held across user code, so there is no deadlock surface.

usage::

    tracker = FailureTracker(threshold=3)
    tracker.record(False)   # streak: 1
    tracker.record(False)   # streak: 2
    tracker.record(False)   # streak: 3 — alerting!
    tracker.alerting        # True
    tracker.record(True)    # streak: 0 — alert cleared
    tracker.alerting        # False

"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StreakSnapshot:
    """Immutable view of the tracker's state at a point in time."""

    consecutive_failures: int
    total_failures: int
    total_successes: int
    alerting: bool
    first_failure_at: float | None


class FailureTracker:
    """Track consecutive failures and alert when a threshold is breached."""

    def __init__(self, *, threshold: int = 3) -> None:
        if threshold < 1:
            raise ValueError(f"threshold must be >= 1, got {threshold}")
        self._threshold = threshold
        self._lock = threading.Lock()
        self._consecutive = 0
        self._total_failures = 0
        self._total_successes = 0
        self._first_failure_at: float | None = None

    # -- public API ----------------------------------------------------------

    def record(self, ok: bool) -> None:
        """Record one outcome.  ``ok=True`` resets the streak."""
        with self._lock:
            if ok:
                self._total_successes += 1
                self._consecutive = 0
                self._first_failure_at = None
            else:
                self._total_failures += 1
                if self._consecutive == 0:
                    self._first_failure_at = time.monotonic()
                self._consecutive += 1

    @property
    def alerting(self) -> bool:
        """Whether the current streak has reached the threshold."""
        with self._lock:
            return self._consecutive >= self._threshold

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._consecutive

    @property
    def total_failures(self) -> int:
        with self._lock:
            return self._total_failures

    @property
    def total_successes(self) -> int:
        with self._lock:
            return self._total_successes

    def streak_duration(self) -> float:
        """Seconds since the first failure in the current streak, or 0."""
        with self._lock:
            if self._first_failure_at is None:
                return 0.0
            return time.monotonic() - self._first_failure_at

    def snapshot(self) -> StreakSnapshot:
        """Return an immutable snapshot of the current state."""
        with self._lock:
            return StreakSnapshot(
                consecutive_failures=self._consecutive,
                total_failures=self._total_failures,
                total_successes=self._total_successes,
                alerting=self._consecutive >= self._threshold,
                first_failure_at=self._first_failure_at,
            )

    def reset(self) -> None:
        """Clear all counters."""
        with self._lock:
            self._consecutive = 0
            self._total_failures = 0
            self._total_successes = 0
            self._first_failure_at = None
