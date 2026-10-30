"""Circuit breaker — stop calling something that keeps failing, try again later.

Three states: CLOSED (normal), OPEN (failing, reject calls), HALF_OPEN (probing).
No threads, no deps, injectable clock for deterministic tests.

    >>> cb = CircuitBreaker(fail_threshold=3, recovery_timeout=60.0,
    ...                     now=lambda: 100.0)
    >>> cb.state
    'closed'

Three failures trip it open:

    >>> def bad(): raise RuntimeError("down")
    >>> for _ in range(3):
    ...     try: cb(bad)
    ...     except RuntimeError: pass
    >>> cb.state
    'open'

While open, calls are rejected immediately without touching the target:

    >>> probes = []
    >>> def probe(): probes.append(1); return "ok"
    >>> try: cb(probe)
    ... except CircuitOpen: pass
    >>> len(probes)
    0

After recovery_timeout the breaker goes half-open and allows one probe:

    >>> cb2 = CircuitBreaker(fail_threshold=2, recovery_timeout=10.0,
    ...                      now=lambda: 100.0)
    >>> for _ in range(2):
    ...     try: cb2(bad)
    ...     except RuntimeError: pass
    >>> cb2._now = lambda: 200.0   # time advanced past recovery
    >>> cb2.state
    'half-open'
    >>> cb2(lambda: "recovered")
    'recovered'
    >>> cb2.state
    'closed'
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


class CircuitOpen(Exception):
    """Raised when the breaker is open and rejects a call."""

    def __init__(self, failures: int, opened_at: float):
        self.failures = failures
        self.opened_at = opened_at
        super().__init__(f"circuit open after {failures} failures (opened at {opened_at:.1f})")


class CircuitBreaker:
    """Protect a callable from being hammered while it is broken.

    Args:
        fail_threshold: consecutive failures before opening the circuit.
        recovery_timeout: seconds to wait before allowing a probe call.
        now: injectable clock; defaults to time.monotonic.
    """

    def __init__(
        self,
        *,
        fail_threshold: int = 5,
        recovery_timeout: float = 30.0,
        now: Callable[[], float] = time.monotonic,
    ):
        if fail_threshold < 1:
            raise ValueError("fail_threshold must be >= 1")
        if recovery_timeout < 0:
            raise ValueError("recovery_timeout must be >= 0")
        self._fail_threshold = fail_threshold
        self._recovery_timeout = recovery_timeout
        self._now = now
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._failures < self._fail_threshold:
            return "closed"
        if self._opened_at is None:
            return "open"
        elapsed = self._now() - self._opened_at
        if elapsed >= self._recovery_timeout:
            return "half-open"
        return "open"

    @property
    def failures(self) -> int:
        return self._failures

    def reset(self) -> None:
        """Manually close the circuit and clear failure count."""
        self._failures = 0
        self._opened_at = None

    def __call__(self, fn: Callable[[], T]) -> T:
        state = self.state
        if state == "open":
            raise CircuitOpen(self._failures, self._opened_at or 0.0)

        try:
            result = fn()
        except Exception:
            self._failures += 1
            if self._failures >= self._fail_threshold:
                self._opened_at = self._now()
            raise

        # success — if we were half-open, close the circuit
        self._failures = 0
        self._opened_at = None
        return result
