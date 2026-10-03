"""Token bucket rate limiter — refill over time, burst when full.

Unlike a simple counter, a token bucket allows bursts up to the bucket
capacity while still enforcing an average rate. No threads, no deps,
injectable clock for deterministic tests.

Basic usage — create a bucket with capacity 5 that refills at 1 token/sec:

    >>> t = 100.0
    >>> b = TokenBucket(capacity=5, refill_rate=1.0, now=lambda: t)
    >>> b.tokens
    5.0

Consume tokens:

    >>> b.take(3)
    True
    >>> b.tokens
    2.0

Can't take more than available:

    >>> b.take(5)
    False
    >>> b.tokens
    2.0

After time passes, tokens refill (capped at capacity):

    >>> t = 103.0
    >>> b.tokens
    5.0
    >>> b.take(5)
    True

Edge — zero refill rate means no refill ever:

    >>> b2 = TokenBucket(capacity=3, refill_rate=0.0, now=lambda: 0.0)
    >>> b2.take(3)
    True
    >>> b2._now = lambda: 999.0
    >>> b2.tokens
    0.0
"""

from __future__ import annotations

from typing import Callable


class TokenBucket:
    """Classic token bucket: allows bursts up to capacity, refills at a steady rate.

    Args:
        capacity: maximum tokens the bucket holds.
        refill_rate: tokens added per second.
        now: injectable clock; defaults to time.monotonic.
    """

    def __init__(
        self,
        *,
        capacity: float,
        refill_rate: float,
        now: Callable[[], float] | None = None,
    ):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if refill_rate < 0:
            raise ValueError("refill_rate must be >= 0")
        import time as _time
        self._capacity = float(capacity)
        self._refill_rate = float(refill_rate)
        self._now = now or _time.monotonic
        self._tokens = float(capacity)
        self._last_refill = self._now()

    def _refill(self) -> None:
        now = self._now()
        elapsed = now - self._last_refill
        if elapsed > 0 and self._refill_rate > 0:
            self._tokens = min(
                self._capacity,
                self._tokens + elapsed * self._refill_rate,
            )
            self._last_refill = now

    @property
    def tokens(self) -> float:
        """Current token count after refilling for elapsed time."""
        self._refill()
        return self._tokens

    @property
    def capacity(self) -> float:
        return self._capacity

    def take(self, n: float = 1.0) -> bool:
        """Try to consume *n* tokens. Returns True on success, False if not enough."""
        if n < 0:
            raise ValueError("n must be >= 0")
        self._refill()
        if self._tokens >= n:
            self._tokens -= n
            return True
        return False

    def reset(self) -> None:
        """Refill the bucket to full capacity and reset the clock."""
        self._tokens = float(self._capacity)
        self._last_refill = self._now()
