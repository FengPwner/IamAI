"""Weighted random selection — cumulative-sum + bisect approach.

O(n) build, O(log n) per pick.  Zero deps beyond stdlib.
"""

from __future__ import annotations

import bisect
import random
from typing import Generic, Sequence, TypeVar

T = TypeVar("T")


class WeightedChoice(Generic[T]):
    """Pick items with probability proportional to their weight.

    >>> wc = WeightedChoice([("a", 1), ("b", 2), ("c", 3)])
    >>> wc.items()
    ['a', 'b', 'c']
    >>> wc.total_weight
    6.0
    >>> all(wc.pick() in ("a", "b", "c") for _ in range(50))
    True
    """

    __slots__ = ("_items", "_cumulative", "_total")

    def __init__(self, pairs: Sequence[tuple[T, float]]) -> None:
        if not pairs:
            raise ValueError("need at least one (item, weight) pair")
        items: list[T] = []
        cumulative: list[float] = []
        running = 0.0
        for item, weight in pairs:
            if weight < 0:
                raise ValueError(f"weight for {item!r} must be >= 0, got {weight}")
            running += weight
            items.append(item)
            cumulative.append(running)
        if running <= 0:
            raise ValueError("total weight must be > 0")
        self._items = items
        self._cumulative = cumulative
        self._total = running

    # -- public api ----------------------------------------------------------

    def pick(self, rng: random.Random | None = None) -> T:
        """Return one item chosen with probability ∝ weight."""
        _rng = rng or random
        r = _rng.random() * self._total
        idx = bisect.bisect_right(self._cumulative, r)
        return self._items[min(idx, len(self._items) - 1)]

    def pick_n(self, n: int, rng: random.Random | None = None) -> list[T]:
        """Return *n* independent picks (with replacement)."""
        return [self.pick(rng) for _ in range(n)]

    @property
    def total_weight(self) -> float:
        return self._total

    def items(self) -> list[T]:
        return list(self._items)

    def weights(self) -> list[float]:
        prev = 0.0
        out: list[float] = []
        for c in self._cumulative:
            out.append(c - prev)
            prev = c
        return out

    def probability(self, item: T) -> float:
        """Return the exact selection probability for *item*."""
        for i, it in enumerate(self._items):
            if it == item:
                w = self._cumulative[i] - (self._cumulative[i - 1] if i > 0 else 0.0)
                return w / self._total
        raise ValueError(f"{item!r} not in collection")

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        pairs = list(zip(self._items, self.weights()))
        return f"WeightedChoice({pairs!r})"
