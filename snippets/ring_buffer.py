"""Fixed-size ring buffer — overwrites oldest on full, zero deps."""

from typing import Generic, Iterator, TypeVar

T = TypeVar("T")


class RingBuffer(Generic[T]):
    """A circular buffer that overwrites the oldest element when full.

    >>> rb = RingBuffer[int](capacity=3)
    >>> rb.push(1); rb.push(2); rb.push(3)
    >>> list(rb)
    [1, 2, 3]
    >>> rb.push(4)          # overwrites 1; returns the evicted item
    1
    >>> list(rb)
    [2, 3, 4]
    >>> rb.peek()
    2
    >>> rb.pop()
    2
    >>> list(rb)
    [3, 4]
    """

    __slots__ = ("_buf", "_cap", "_write_idx", "_size")

    def __init__(self, *, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._buf: list[T | None] = [None] * capacity
        self._cap = capacity
        self._write_idx = 0  # monotonically increasing; actual slot = % cap
        self._size = 0

    def push(self, item: T) -> T | None:
        """Add an item. Returns the evicted item if the buffer was full, else None."""
        slot = self._write_idx % self._cap
        evicted: T | None = None
        if self._size == self._cap:
            evicted = self._buf[slot]
        else:
            self._size += 1
        self._buf[slot] = item
        self._write_idx += 1
        return evicted

    def _oldest_idx(self) -> int:
        """Index of the oldest element in the backing array."""
        return (self._write_idx - self._size) % self._cap

    def pop(self) -> T:
        """Remove and return the oldest item. Raises IndexError if empty."""
        if self._size == 0:
            raise IndexError("pop from empty ring buffer")
        idx = self._oldest_idx()
        item = self._buf[idx]
        self._buf[idx] = None
        self._size -= 1
        return item  # type: ignore[return-value]

    def peek(self) -> T:
        """Return the oldest item without removing it. Raises IndexError if empty."""
        if self._size == 0:
            raise IndexError("peek at empty ring buffer")
        return self._buf[self._oldest_idx()]  # type: ignore[return-value]

    @property
    def capacity(self) -> int:
        return self._cap

    @property
    def size(self) -> int:
        return self._size

    @property
    def is_full(self) -> bool:
        return self._size == self._cap

    @property
    def is_empty(self) -> bool:
        return self._size == 0

    def __len__(self) -> int:
        return self._size

    def __iter__(self) -> Iterator[T]:
        """Iterate from oldest to newest."""
        for i in range(self._size):
            idx = (self._write_idx - self._size + i) % self._cap
            yield self._buf[idx]  # type: ignore[misc]

    def __repr__(self) -> str:
        return f"RingBuffer({list(self)}, capacity={self._cap})"
