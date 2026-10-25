"""068 — reservoir: weighted and uniform reservoir sampling from a stream.

sometimes you have more data than you can keep.  a million log lines, a
billion events, a firehose of sensor readings — and you need a *fair*
sample of size k to inspect, test, or feed into a dashboard.

naive approach: store everything, sample at the end.  that needs o(n)
memory.  if n is unbounded or the stream never stops, you're dead.

reservoir sampling (vitter, 1985) solves this in o(k) space with a
single pass.  each element has an equal chance of landing in the final
sample, and you never need to know n in advance.

the weighted variant lets some items be more "important" — useful when
sampling by traffic volume, file size, or any non-uniform measure.

this module gives you both, behind one clean api.

usage::

    from snippets.reservoir import Reservoir

    r = Reservoir(k=100)
    for line in open("huge.log"):
        r.add(line)
    print(r.sample)  # 100 uniformly random lines

    # weighted: bigger files get proportionally more slots
    w = Reservoir(k=10, weighted=True)
    for path in all_files:
        w.add(path, weight=os.path.getsize(path))
"""

from __future__ import annotations

import random
from typing import Any, Iterator, List, Optional, Sequence


class Reservoir:
    """Reservoir sampler — collect a fair sample of *k* items from a stream.

    Parameters
    ----------
    k : int
        Maximum sample size.  Must be >= 1.
    seed : int or None
        Optional RNG seed for reproducibility.
    weighted : bool
        If True, use weighted (A-Res) sampling; each ``add`` call can
        supply a ``weight`` parameter.  Items with higher weight are
        proportionally more likely to appear in the sample.

    Examples
    --------
    >>> r = Reservoir(k=3, seed=42)
    >>> for i in range(100):
    ...     r.add(i)
    >>> len(r.sample)
    3
    >>> all(isinstance(x, int) for x in r.sample)
    True
    """

    __slots__ = ("_k", "_rng", "_n", "_heap", "_weighted")

    def __init__(self, k: int = 100, *, seed: Optional[int] = None, weighted: bool = False):
        if k < 1:
            raise ValueError(f"k must be >= 1, got {k}")
        self._k = k
        self._rng = random.Random(seed)
        self._n = 0
        self._heap: List[tuple] = []  # (key, item) — min-heap by key
        self._weighted = weighted

    # ------------------------------------------------------------------
    # public api
    # ------------------------------------------------------------------

    def add(self, item: Any, *, weight: float = 1.0) -> None:
        """Add an item to the stream.

        Parameters
        ----------
        item : Any
            The item to potentially include in the sample.
        weight : float
            Only used when ``weighted=True``.  Higher weight means the
            item is more likely to be selected.  Must be > 0.
        """
        if self._weighted and weight <= 0:
            raise ValueError(f"weight must be > 0, got {weight}")

        self._n += 1

        if self._weighted:
            key = self._rng.random() ** (1.0 / weight)
        else:
            key = self._rng.random()

        if len(self._heap) < self._k:
            self._heap.append((key, item))
            if len(self._heap) == self._k:
                # build min-heap once full
                self._heap.sort()  # simple sort; k is small
        elif key > self._heap[0][0]:
            # replace the smallest key
            self._heap[0] = (key, item)
            self._sift_down(0)

    def add_many(self, items: Sequence[Any], *, weights: Optional[Sequence[float]] = None) -> None:
        """Add multiple items at once.

        Parameters
        ----------
        items : sequence
            Items to add.
        weights : sequence or None
            If ``weighted=True`` and weights is provided, each item gets
            its corresponding weight.  Otherwise all weights default to 1.
        """
        if weights is not None:
            if len(weights) != len(items):
                raise ValueError("items and weights must have the same length")
            for item, w in zip(items, weights):
                self.add(item, weight=w)
        else:
            for item in items:
                self.add(item)

    @property
    def sample(self) -> List[Any]:
        """Return the current sample (up to k items), in insertion order of acceptance."""
        return [item for _, item in self._heap]

    @property
    def seen(self) -> int:
        """Total number of items added to the stream so far."""
        return self._n

    @property
    def size(self) -> int:
        """Current sample size (min(n, k))."""
        return len(self._heap)

    def __len__(self) -> int:
        return self.size

    def __iter__(self) -> Iterator[Any]:
        return iter(self.sample)

    def __repr__(self) -> str:
        mode = "weighted" if self._weighted else "uniform"
        return f"Reservoir(k={self._k}, seen={self._n}, size={self.size}, mode={mode})"

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _sift_down(self, i: int) -> None:
        """Restore min-heap property after replacing the root."""
        n = len(self._heap)
        while True:
            smallest = i
            left, right = 2 * i + 1, 2 * i + 2
            if left < n and self._heap[left][0] < self._heap[smallest][0]:
                smallest = left
            if right < n and self._heap[right][0] < self._heap[smallest][0]:
                smallest = right
            if smallest == i:
                break
            self._heap[i], self._heap[smallest] = self._heap[smallest], self._heap[i]
            i = smallest
