"""Semaphore — bounded concurrency with optional timeout.

A counting semaphore controls how many workers can hold a permit at once.
Useful for rate-limiting access to a shared resource (database connections,
API calls, file handles) without queuing the callers yourself.

Key design choices:

- **Fair FIFO**: permits are granted in arrival order, preventing starvation.
- **Timeout**: ``acquire(timeout=...)`` returns False if a permit is not
  available within the deadline, instead of blocking forever.
- **Context manager**: ``with sem:`` acquires and releases automatically.
- **Zero dependencies**: stdlib threading only.

>>> sem = Semaphore(permits=2)
>>> sem.available
2
>>> sem.acquire()
True
>>> sem.acquire()
True
>>> sem.available
0
>>> sem.acquire(timeout=0.01)
False
>>> sem.release()
>>> sem.available
1
>>> sem.release()
>>> sem.available
2
"""

from __future__ import annotations

import threading
import time
from typing import Optional


class Semaphore:
    """A counting semaphore with timeout and context-manager support."""

    def __init__(self, permits: int = 1) -> None:
        if permits < 1:
            raise ValueError(f"permits must be >= 1, got {permits}")
        self._permits = permits
        self._available = permits
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._waiters: list[threading.Event] = []

    @property
    def available(self) -> int:
        """Number of permits currently available."""
        with self._lock:
            return self._available

    @property
    def capacity(self) -> int:
        """Total permit count (fixed at construction)."""
        return self._permits

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """Acquire a permit.

        Returns True immediately if one is available.
        If *timeout* is None (default), blocks until a permit is released.
        If *timeout* is a number, blocks up to that many seconds, then
        returns False if no permit became available.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        waiter = threading.Event()

        with self._cond:
            # fast path: permit available and no one ahead in the FIFO queue
            if self._available > 0 and not self._waiters:
                self._available -= 1
                return True

            # slow path: register ourselves and wait for a signal
            self._waiters.append(waiter)

        try:
            while True:
                remaining = None
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False

                # wait for our turn (or timeout)
                got_signal = waiter.wait(timeout=remaining)

                with self._cond:
                    if waiter not in self._waiters:
                        # we were signalled
                        if self._available > 0:
                            self._available -= 1
                            return True
                        # spurious: re-register at front
                        self._waiters.insert(0, waiter)
                        continue

                    if not got_signal:
                        # timed out — remove ourselves and fail
                        try:
                            self._waiters.remove(waiter)
                        except ValueError:
                            pass
                        return False
        except BaseException:
            with self._cond:
                try:
                    self._waiters.remove(waiter)
                except ValueError:
                    pass
            raise

    def release(self) -> None:
        """Release a permit and wake the next waiter (if any)."""
        with self._cond:
            self._available += 1
            # wake the first waiter in FIFO order
            if self._waiters:
                waiter = self._waiters.pop(0)
                waiter.set()
            self._cond.notify_all()

    def __enter__(self) -> "Semaphore":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    def __repr__(self) -> str:
        return f"Semaphore(permits={self._permits}, available={self._available})"
