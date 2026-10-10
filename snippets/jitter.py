"""Jitter — add controlled randomness to fixed intervals.

Thundering-herd prevention: when N workers all wake every 60 s, they
stampede the shared resource at the same instant.  Adding ±jitter
spreads the load without changing the *average* cadence.

Three strategies, each suited to a different mood:

- ``full``:     uniform in [0, interval]   — aggressive spread
- ``equal``:    uniform in [interval/2, interval] — never too early
- ``decorr``:   exponential back-off with decorrelation (AWS style)

Zero dependencies.  Inject your own ``random`` for determinism in tests.

>>> import random
>>> rng = random.Random(42)
>>> j = Jitter(interval=10.0, strategy="equal", rng=rng)
>>> j.next()  # doctest: +ELLIPSIS
7...
>>> j.next()  # doctest: +ELLIPSIS
8...
"""

from __future__ import annotations

import random as _random
from typing import Callable


class Jitter:
    """Produce jittered intervals.

    Parameters
    ----------
    interval : float
        The base (nominal) interval in seconds.  Must be > 0.
    strategy : str
        One of ``"full"``, ``"equal"``, ``"decorr"``.
    rng : random.Random | None
        Inject a seeded RNG for reproducibility; defaults to module-level
        ``random.Random()`` (OS-seeded).

    Raises
    ------
    ValueError
        If *interval* ≤ 0 or *strategy* is unknown.
    """

    STRATEGIES = frozenset({"full", "equal", "decorr"})

    def __init__(
        self,
        *,
        interval: float = 60.0,
        strategy: str = "equal",
        rng: _random.Random | None = None,
    ) -> None:
        if interval <= 0:
            raise ValueError(f"interval must be > 0, got {interval}")
        if strategy not in self.STRATEGIES:
            raise ValueError(
                f"unknown strategy {strategy!r}; pick from {sorted(self.STRATEGIES)}"
            )
        self._interval = interval
        self._strategy = strategy
        self._rng = rng or _random.Random()
        self._prev: float = interval  # for decorr

    @property
    def interval(self) -> float:
        """The nominal base interval."""
        return self._interval

    @property
    def strategy(self) -> str:
        return self._strategy

    def next(self) -> float:
        """Return the next jittered interval in seconds."""
        if self._strategy == "full":
            return self._rng.uniform(0, self._interval)
        if self._strategy == "equal":
            half = self._interval / 2
            return self._rng.uniform(half, self._interval)
        # decorr: pick from [interval/2, prev * 3), clamped to [interval/2, interval*2]
        lo = self._interval / 2
        hi = min(self._prev * 3, self._interval * 2)
        val = self._rng.uniform(lo, max(lo, hi))
        self._prev = val
        return val

    def reset(self) -> None:
        """Reset internal state (only affects ``decorr``)."""
        self._prev = self._interval


def jittered_sleep(
    interval: float,
    *,
    strategy: str = "equal",
    sleep_fn: Callable[[float], None] | None = None,
    rng: _random.Random | None = None,
) -> float:
    """Sleep for one jittered interval; return the actual duration slept.

    Convenience wrapper for fire-and-forget use.  Pass a custom *sleep_fn*
    (e.g. ``time.sleep``) or leave ``None`` to use ``time.sleep``.

    >>> import random
    >>> dur = jittered_sleep(1.0, strategy="full", sleep_fn=lambda t: None, rng=random.Random(0))
    >>> 0 <= dur <= 1.0
    True
    """
    import time

    _sleep = sleep_fn or time.sleep
    j = Jitter(interval=interval, strategy=strategy, rng=rng)
    dur = j.next()
    _sleep(dur)
    return dur
