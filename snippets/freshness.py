"""177 — freshness: track how stale your content has become.

in a repo that writes itself, staleness is the silent failure mode. the
writer may be alive but producing nothing new. the caretaker may visit but
find nothing to check. freshness makes this visible by scoring recency on
an exponential decay curve: 1.0 means brand new, 0.5 means one half-life
old, 0.0 means ancient.

the model is deliberately simple: score = 2^(-age/half_life). this gives
a smooth, monotonic decay that is easy to reason about and cheap to compute.
no threads, no IO, no dependencies — just arithmetic.

    age=0          → 1.000  (fresh)
    age=half_life  → 0.500  (half stale)
    age=2*half_life → 0.250  (mostly stale)
    age=10*half_life → 0.001  (ancient)

the tracker aggregates multiple items into a single health signal:
the minimum freshness across all tracked items. this surfaces the
worst-case staleness — the part of the system most in need of attention.

zero dependencies. stdlib only.

>>> freshness(seconds=0, half_life=300)
1.0
>>> abs(freshness(seconds=300, half_life=300) - 0.5) < 1e-9
True
>>> abs(freshness(seconds=600, half_life=300) - 0.25) < 1e-9
True
>>> freshness(seconds=3000, half_life=300) < 0.01
True
>>> classify(1.0)
'fresh'
>>> classify(0.4)
'stale'
>>> classify(0.05)
'ancient'
>>> t = FreshnessTracker(half_life=60)
>>> t.touch("writer", clock=lambda: 100.0)
>>> t.touch("caretaker", clock=lambda: 120.0)
>>> abs(t.score(clock=lambda: 130.0) - 0.5) < 0.02
True
"""

from __future__ import annotations

import time
from typing import Callable


def freshness(seconds: float, half_life: float = 300.0) -> float:
    """Compute freshness score on exponential decay curve.

    Returns a float in [0, 1] where 1.0 is brand new and approaches 0
    as age increases relative to half_life.

    >>> freshness(0, half_life=60)
    1.0
    >>> freshness(-10, half_life=60)
    1.0
    """
    if seconds <= 0:
        return 1.0
    if half_life <= 0:
        raise ValueError("half_life must be > 0")
    return 2.0 ** (-seconds / half_life)


def classify(score: float) -> str:
    """Classify a freshness score into a human-readable bucket.

    >>> classify(0.9)
    'fresh'
    >>> classify(0.6)
    'warming'
    >>> classify(0.3)
    'stale'
    >>> classify(0.01)
    'ancient'
    """
    if score >= 0.75:
        return "fresh"
    if score >= 0.5:
        return "warming"
    if score >= 0.2:
        return "stale"
    return "ancient"


class FreshnessTracker:
    """Track freshness of multiple named items.

    The aggregate score is the minimum freshness across all items —
    the worst-case staleness in the system.

    >>> t = FreshnessTracker(half_life=60)
    >>> t.touch("writer", clock=lambda: 0.0)
    >>> t.touch("batch", clock=lambda: 10.0)
    >>> t.items()
    ['batch', 'writer']
    >>> t.score(clock=lambda: 20.0)
    0.7937005259840997
    >>> t.stalest(clock=lambda: 20.0)
    'writer'
    >>> t.report(clock=lambda: 20.0)
    'fresh (min=0.79, stalest=writer)'
    """

    def __init__(self, half_life: float = 300.0):
        if half_life <= 0:
            raise ValueError("half_life must be > 0")
        self._half_life = half_life
        self._last_touch: dict[str, float] = {}

    @property
    def half_life(self) -> float:
        return self._half_life

    def touch(
        self, name: str, clock: Callable[[], float] = time.monotonic
    ) -> None:
        """Record a fresh event for the named item."""
        self._last_touch[name] = clock()

    def score(self, clock: Callable[[], float] = time.monotonic) -> float:
        """Minimum freshness across all tracked items.

        Returns 1.0 if no items are tracked (vacuously fresh).
        """
        if not self._last_touch:
            return 1.0
        now = clock()
        return min(
            freshness(now - ts, self._half_life)
            for ts in self._last_touch.values()
        )

    def stalest(self, clock: Callable[[], float] = time.monotonic) -> str | None:
        """Name of the item with the lowest freshness.

        Returns None if no items are tracked.
        """
        if not self._last_touch:
            return None
        now = clock()
        return min(
            self._last_touch,
            key=lambda name: freshness(now - self._last_touch[name], self._half_life),
        )

    def items(self) -> list[str]:
        """Sorted list of tracked item names."""
        return sorted(self._last_touch.keys())

    def ages(
        self, clock: Callable[[], float] = time.monotonic
    ) -> dict[str, float]:
        """Age in seconds for each tracked item."""
        now = clock()
        return {name: now - ts for name, ts in self._last_touch.items()}

    def report(self, clock: Callable[[], float] = time.monotonic) -> str:
        """One-line human-readable freshness summary."""
        s = self.score(clock)
        label = classify(s)
        worst = self.stalest(clock)
        return f"{label} (min={s:.2f}, stalest={worst})"

    def __repr__(self) -> str:
        return (
            f"FreshnessTracker(half_life={self._half_life}, "
            f"items={len(self._last_touch)})"
        )
