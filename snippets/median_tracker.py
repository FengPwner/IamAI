"""067 — median_tracker: running median via two heaps, no full sort.

the naive approach to a running median is to keep a sorted list and
re-sort on every insert — O(n log n) per addition, which is fine for a
hundred samples and catastrophic for a million.  the two-heap trick
reduces insert to O(log n) and median lookup to O(1).

the idea: maintain a max-heap for the lower half and a min-heap for the
upper half.  the median is either the top of the max-heap (odd count) or
the average of both tops (even count).  rebalancing after each insert
keeps the heaps within one element of each other.

python's heapq is a min-heap, so the "max-heap" is implemented by
negating values on the way in and out.  simple, no external deps.

this implementation provides:

- **add(x)** — insert a value, rebalance heaps.  O(log n).
- **median** — current median.  O(1).
- **count** — number of values seen.
- **clear()** — reset both heaps.

works with int and float.  not thread-safe; wrap in a lock if you need
concurrent access from multiple threads.

"""

from __future__ import annotations

import heapq


class MedianTracker:
    """Track the running median of a stream of numbers using two heaps."""

    def __init__(self) -> None:
        self._lo: list[float] = []  # max-heap (negated values)
        self._hi: list[float] = []  # min-heap

    @property
    def count(self) -> int:
        """Total number of values added so far."""
        return len(self._lo) + len(self._hi)

    @property
    def median(self) -> float:
        """Current median of all added values.

        Raises ``ValueError`` if no values have been added.
        """
        if not self._lo and not self._hi:
            raise ValueError("no values added — median is undefined")

        if len(self._lo) > len(self._hi):
            return -self._lo[0]
        if len(self._hi) > len(self._lo):
            return self._hi[0]
        # equal sizes: average of both tops
        return (-self._lo[0] + self._hi[0]) / 2.0

    def add(self, x: float) -> None:
        """Insert *x* and rebalance the two heaps.  O(log n)."""
        # decide which heap receives the new value
        if not self._lo or x <= -self._lo[0]:
            heapq.heappush(self._lo, -x)
        else:
            heapq.heappush(self._hi, x)

        self._rebalance()

    def clear(self) -> None:
        """Discard all values."""
        self._lo.clear()
        self._hi.clear()

    # -- internals -----------------------------------------------------------

    def _rebalance(self) -> None:
        """Ensure the two heaps differ in size by at most one."""
        while len(self._lo) - len(self._hi) > 1:
            heapq.heappush(self._hi, -heapq.heappop(self._lo))
        while len(self._hi) - len(self._lo) > 1:
            heapq.heappush(self._lo, -heapq.heappop(self._hi))
