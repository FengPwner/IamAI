"""Time-bounded exclusive lease — auto-expiring lock for process coordination."""

import time
from typing import Callable


class Lease:
    """Grant exclusive access for a bounded duration, then auto-expire.

    Useful when multiple writers share a resource (a file, a branch,
    a push slot) and need to coordinate without a central server.

    >>> ls = Lease(ttl=0.05, clock=time.monotonic)
    >>> ls.acquire("writer-a")
    True
    >>> ls.holder
    'writer-a'
    >>> ls.acquire("writer-b")       # rejected — still held
    False
    >>> import time as _t; _t.sleep(0.06)
    >>> ls.acquire("writer-b")       # lease expired — now available
    True
    >>> ls.holder
    'writer-b'
    >>> ls.release("writer-a")       # wrong holder — no-op
    False
    >>> ls.release("writer-b")
    True
    >>> ls.holder is None
    True
    """

    def __init__(
        self,
        ttl: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        self._ttl = ttl
        self._clock = clock
        self._holder: str | None = None
        self._expires: float = 0.0

    @property
    def holder(self) -> str | None:
        """Current lease holder, or None if expired / released."""
        if self._holder is not None and self._clock() >= self._expires:
            self._holder = None
        return self._holder

    @property
    def ttl(self) -> float:
        return self._ttl

    @property
    def remaining(self) -> float:
        """Seconds left on the current lease (0 if unheld or expired)."""
        if self._holder is None:
            return 0.0
        left = self._expires - self._clock()
        return max(0.0, left)

    def acquire(self, who: str) -> bool:
        """Try to acquire the lease. Returns True on success."""
        # Check expiration via the property accessor
        if self.holder is None:
            self._holder = who
            self._expires = self._clock() + self._ttl
            return True
        # Same holder renewing
        if self._holder == who:
            self._expires = self._clock() + self._ttl
            return True
        return False

    def release(self, who: str) -> bool:
        """Release the lease. Only the current holder can release."""
        if self._holder == who:
            self._holder = None
            self._expires = 0.0
            return True
        return False

    def force_release(self) -> None:
        """Release regardless of holder — for cleanup / tests."""
        self._holder = None
        self._expires = 0.0

    def __repr__(self) -> str:
        state = f"held by {self._holder!r} ({self.remaining:.1f}s)" if self.holder else "free"
        return f"Lease(ttl={self._ttl}, {state})"
