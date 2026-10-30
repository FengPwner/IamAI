"""A token bucket you can drive with a fake clock."""


class TokenBucket:
    """capacity tokens, refilled at `rate` per second.

    >>> b = TokenBucket(capacity=2, rate=1, clock=lambda: 0)
    >>> b.take(), b.take(), b.take()
    (True, True, False)
    >>> b.advance_to(1.5)
    >>> b.take()
    True
    """

    def __init__(self, capacity: int, rate: float, clock=None):
        if capacity < 1 or rate <= 0:
            raise ValueError("need capacity >= 1 and rate > 0")
        self.capacity = int(capacity)
        self.rate = float(rate)
        self.tokens = float(capacity)
        self._clock = clock or (lambda: 0.0)
        self._last = self._clock()

    def _refill(self) -> None:
        current = self._clock()
        self.tokens = min(self.capacity, self.tokens + (current - self._last) * self.rate)
        self._last = current

    def take(self, n: int = 1) -> bool:
        self._refill()
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def advance_to(self, moment: float) -> None:
        """Move the fake clock forward. Returns nothing -- this only mutates."""

        self._clock = lambda moment=moment: moment
        self._refill()
