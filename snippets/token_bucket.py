"""TokenBucket — a simple rate limiter using the token bucket algorithm.

Allows bursts up to `capacity`, refills at `refill_rate` tokens per second.
Useful for throttling API calls, push operations, or any action where you
need to cap throughput while still allowing short bursts.

Zero dependencies, no threads. Uses `time.monotonic` by default but
accepts an injectable clock for testing.

>>> import time
>>> bucket = TokenBucket(capacity=3, refill_rate=1.0, clock=time.monotonic)
>>> bucket.consume()
True
>>> bucket.consume()
True
>>> bucket.consume()
True
>>> bucket.consume()          # bucket empty
False
>>> time.sleep(1.1)
>>> bucket.consume()          # one token refilled
True
"""

from __future__ import annotations

import time
from typing import Callable


class TokenBucket:
    """A token bucket rate limiter.

    >>> b = TokenBucket(capacity=2, refill_rate=10.0)
    >>> b.consume()
    True
    >>> b.consume()
    True
    >>> b.consume()
    False
    >>> b.tokens >= 0
    True
    """

    def __init__(
        self,
        capacity: int,
        refill_rate: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if refill_rate <= 0:
            raise ValueError("refill_rate must be > 0")
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._clock = clock
        self._tokens: float = float(capacity)
        self._last_refill: float = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        new_tokens = elapsed * self._refill_rate
        self._tokens = min(self._capacity, self._tokens + new_tokens)
        self._last_refill = now

    def consume(self, count: int = 1) -> bool:
        """Try to consume `count` tokens. Return True if allowed, False if not."""
        if count < 1:
            raise ValueError("count must be >= 1")
        self._refill()
        if self._tokens >= count:
            self._tokens -= count
            return True
        return False

    def wait_time(self, count: int = 1) -> float:
        """Return seconds until `count` tokens would be available.

        Returns 0.0 if tokens are already available.
        """
        if count < 1:
            raise ValueError("count must be >= 1")
        self._refill()
        if self._tokens >= count:
            return 0.0
        deficit = count - self._tokens
        return deficit / self._refill_rate

    @property
    def tokens(self) -> float:
        """Current token count (after refill)."""
        self._refill()
        return self._tokens

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def refill_rate(self) -> float:
        return self._refill_rate

    def reset(self) -> None:
        """Refill the bucket to full capacity."""
        self._tokens = float(self._capacity)
        self._last_refill = self._clock()
