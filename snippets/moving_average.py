"""A rolling mean over a stream, O(1) per update after warmup."""


class MovingAverage:
    """Keep a running mean over the last `window` samples.

    >>> m = MovingAverage(3)
    >>> [m.push(v) for v in (1, 2, 3, 4)]
    [1.0, 1.5, 2.0, 3.0]
    >>> m.window
    3
    """

    def __init__(self, window: int):
        if window < 1:
            raise ValueError("window must be at least 1")
        self.window = int(window)
        self._items: list[float] = []
        self._total = 0.0

    def push(self, sample) -> float:
        self._items.append(float(sample))
        self._total += float(sample)
        if len(self._items) > self.window:
            self._total -= self._items.pop(0)
        return round(self.mean, 4)

    @property
    def mean(self) -> float:
        return self._total / len(self._items) if self._items else 0.0

    def __len__(self) -> int:
        return len(self._items)
