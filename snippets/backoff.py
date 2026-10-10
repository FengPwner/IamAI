"""Backoff — exponential delay sequence with optional jitter.

retry.py hides the backoff inside a call-and-catch loop.  Sometimes you
want the *delays themselves* as a standalone object: feed them to a custom
poll loop, a test harness, or a rate-limit coordinator that isn't a simple
retry.

Backoff generates a sequence of non-decreasing delays:

    base, base*2, base*4, …  capped at max_delay

with three jitter modes to avoid synchronisation:

- ``"none"``:  pure exponential  (deterministic)
- ``"full"``:  uniform in [0, delay]
- ``"equal"``: uniform in [delay/2, delay]  — never less than half

Zero dependencies.  Inject a seeded ``random.Random`` for reproducible
tests.

>>> import random
>>> b = Backoff(base=1.0, max_delay=10.0, strategy="none")
>>> list(b.delays(5))
[1.0, 2.0, 4.0, 8.0, 10.0]

>>> b2 = Backoff(base=2.0, max_delay=20.0, strategy="full", rng=random.Random(42))
>>> d = b2.next()
>>> 0.0 <= d <= 2.0
True
"""

from __future__ import annotations

import random as _random
from typing import Iterator


class Backoff:
    """Produce a sequence of exponential-backoff delays.

    Parameters
    ----------
    base : float
        Initial delay in seconds.  Must be > 0.
    max_delay : float
        Upper cap.  Must be >= base.
    strategy : str
        ``"none"``, ``"full"``, or ``"equal"``.
    rng : random.Random | None
        Inject a seeded RNG for determinism; defaults to OS-seeded.

    Raises
    ------
    ValueError
        On invalid parameters.
    """

    STRATEGIES = frozenset({"none", "full", "equal"})

    def __init__(
        self,
        *,
        base: float = 1.0,
        max_delay: float = 30.0,
        strategy: str = "none",
        rng: _random.Random | None = None,
    ) -> None:
        if base <= 0:
            raise ValueError(f"base must be > 0, got {base}")
        if max_delay < base:
            raise ValueError(f"max_delay must be >= base, got {max_delay} < {base}")
        if strategy not in self.STRATEGIES:
            raise ValueError(
                f"unknown strategy {strategy!r}; pick from {sorted(self.STRATEGIES)}"
            )
        self._base = base
        self._max = max_delay
        self._strategy = strategy
        self._rng = rng or _random.Random()
        self._attempt = 0

    # -- introspection ---------------------------------------------------

    @property
    def base(self) -> float:
        return self._base

    @property
    def max_delay(self) -> float:
        return self._max

    @property
    def strategy(self) -> str:
        return self._strategy

    @property
    def attempt(self) -> int:
        """How many delays have been consumed so far."""
        return self._attempt

    # -- delay generation ------------------------------------------------

    def _raw(self) -> float:
        """Unjittered exponential delay, capped at max."""
        return min(self._base * (2 ** self._attempt), self._max)

    def next(self) -> float:
        """Return the next delay and advance the counter."""
        raw = self._raw()
        self._attempt += 1
        if self._strategy == "none":
            return raw
        if self._strategy == "full":
            return self._rng.uniform(0, raw)
        # equal
        half = raw / 2
        return self._rng.uniform(half, raw)

    def delays(self, n: int) -> Iterator[float]:
        """Yield *n* successive delays without mutating internal state permanently.

        Useful for previews and tests.

        >>> b = Backoff(base=1.0, max_delay=8.0, strategy="none")
        >>> list(b.delays(4))
        [1.0, 2.0, 4.0, 8.0]
        """
        saved = self._attempt
        for _ in range(n):
            yield self.next()
        self._attempt = saved

    def reset(self) -> None:
        """Reset the attempt counter back to zero."""
        self._attempt = 0

    def __repr__(self) -> str:
        return (
            f"Backoff(base={self._base}, max={self._max}, "
            f"strategy={self._strategy!r}, attempt={self._attempt})"
        )
