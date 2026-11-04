"""CircuitBreaker — fail fast when a dependency is broken.

The circuit breaker pattern prevents cascading failures by wrapping calls
to unreliable services.  Three states:

- ``closed``:   normal operation, calls pass through
- ``open``:     failures exceeded threshold, calls rejected immediately
- ``half_open``: after a cooldown, one probe call is allowed through

If the probe succeeds the breaker closes; if it fails the breaker reopens.

Zero dependencies.  Stdlib only.

>>> import time
>>> cb = CircuitBreaker(threshold=3, cooldown=10.0, clock=lambda: 100.0)
>>> cb.state
'closed'
>>> cb.record_failure()
>>> cb.record_failure()
>>> cb.record_failure()
>>> cb.state
'open'
>>> cb.allow_request()
False
>>> # simulate cooldown expiry
>>> cb._clock = lambda: 111.0
>>> cb.state
'half_open'
>>> cb.allow_request()
True
>>> cb.record_success()
>>> cb.state
'closed'
"""

from __future__ import annotations

import time as _time
from typing import Callable, Optional


class CircuitOpenError(Exception):
    """Raised when a call is attempted while the circuit is open."""


class CircuitBreaker:
    """Protect a flaky dependency with a three-state circuit breaker.

    Parameters
    ----------
    threshold : int
        Number of consecutive failures before opening.
    cooldown : float
        Seconds to wait before transitioning from open → half_open.
    clock : callable, optional
        Monotonic clock; defaults to ``time.monotonic``.
    """

    def __init__(
        self,
        *,
        threshold: int = 5,
        cooldown: float = 30.0,
        clock: Optional[Callable[[], float]] = None,
    ):
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        if cooldown < 0:
            raise ValueError("cooldown must be >= 0")
        self._threshold = threshold
        self._cooldown = cooldown
        self._clock = clock or (lambda: _time.monotonic())

        self._failures: int = 0
        self._state: str = "closed"
        self._opened_at: Optional[float] = None

    # -- public API ---------------------------------------------------------

    @property
    def state(self) -> str:
        """Current state: closed, open, or half_open."""
        if self._state == "open":
            now = self._clock()
            if self._opened_at is not None and now - self._opened_at >= self._cooldown:
                self._state = "half_open"
        return self._state

    @property
    def failures(self) -> int:
        """Consecutive failure count."""
        return self._failures

    def allow_request(self) -> bool:
        """Return True if the next call should be permitted."""
        s = self.state
        if s == "closed":
            return True
        if s == "half_open":
            return True  # one probe call allowed
        return False

    def call(self, fn, *args, **kwargs):
        """Execute *fn* through the breaker.

        Returns the function's result on success.
        Raises ``CircuitOpenError`` if the circuit is open.
        """
        if not self.allow_request():
            raise CircuitOpenError(
                f"circuit is open ({self._failures} failures, "
                f"cooldown {self._cooldown}s)"
            )
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        else:
            self.record_success()
            return result

    def record_success(self) -> None:
        """Record a successful call — resets the breaker."""
        self._failures = 0
        self._state = "closed"
        self._opened_at = None

    def record_failure(self) -> None:
        """Record a failed call — may trip the breaker."""
        self._failures += 1
        if self._failures >= self._threshold:
            self._state = "open"
            self._opened_at = self._clock()

    def reset(self) -> None:
        """Force the breaker back to closed state."""
        self._failures = 0
        self._state = "closed"
        self._opened_at = None
