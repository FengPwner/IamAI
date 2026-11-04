"""178 — token_bucket: a smooth rate limiter that allows bursts.

the problem: you want to cap how fast something happens — API calls, file
writes, notifications — but the world is bursty.  a strict "one per second"
rule rejects legitimate spikes and wastes capacity during quiet periods.

the token bucket solves this with a simple metaphor.  imagine a bucket that
fills at a constant rate (tokens per second).  each action consumes one
token.  if the bucket is empty, the action must wait.  if the bucket is
full, you can spend several tokens at once — absorbing a burst without
violating the average rate.

this implementation provides:

- **try_acquire(n=1)** — non-blocking: returns True if *n* tokens are
  available, consumes them, returns False otherwise.
- **acquire(n=1, timeout=None)** — blocking variant: waits up to *timeout*
  seconds for tokens to become available.
- **tokens** — current token count (snapshot, may be stale by the time
  you read it).
- **capacity** — maximum tokens the bucket can hold.
- **rate** — refill rate in tokens per second.

thread safety comes from a threading.Lock around every state mutation.
the refill is lazy — tokens are computed on demand from elapsed wall
clock time, not by a background thread.  this means zero overhead when
idle and perfect accuracy when checked.

the bucket never exceeds *capacity* even after long idle periods:
``min(capacity, tokens + elapsed * rate)``.  a bucket that sat unused
for a day still only holds *capacity* tokens, not a day's worth.

"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    """A smooth rate limiter that allows controlled bursts."""

    capacity: float
    rate: float  # tokens per second
    _tokens: float = field(init=False, repr=False)
    _last_refill: float = field(init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError("capacity must be positive")
        if self.rate <= 0:
            raise ValueError("rate must be positive")
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(
                self.capacity, self._tokens + elapsed * self.rate
            )
            self._last_refill = now

    @property
    def tokens(self) -> float:
        """Current available tokens (refills lazily on read)."""
        with self._lock:
            self._refill()
            return self._tokens

    def try_acquire(self, n: int = 1) -> bool:
        """Try to consume *n* tokens. Returns True on success, False if insufficient."""
        if n <= 0:
            raise ValueError("n must be positive")
        with self._lock:
            self._refill()
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False

    def acquire(self, n: int = 1, timeout: float | None = None) -> bool:
        """Block until *n* tokens are available or *timeout* expires.

        Returns True if tokens were acquired, False if timed out.
        A timeout of None waits indefinitely.
        """
        if n <= 0:
            raise ValueError("n must be positive")
        if n > self.capacity:
            return False  # will never have enough tokens

        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= n:
                    self._tokens -= n
                    return True
                # How long until enough tokens are available?
                deficit = n - self._tokens
                wait = deficit / self.rate

            # Check timeout before sleeping
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait = min(wait, remaining)

            # Sleep a fraction of the wait to stay responsive
            time.sleep(min(wait, 0.05))

    def drain(self) -> float:
        """Consume all available tokens and return the count consumed."""
        with self._lock:
            self._refill()
            consumed = self._tokens
            self._tokens = 0.0
            return consumed

    def reset(self) -> None:
        """Refill the bucket to full capacity."""
        with self._lock:
            self._tokens = float(self.capacity)
            self._last_refill = time.monotonic()
