"""A minimal LRU cache — evict the least-recently-used entry when full."""

from __future__ import annotations

from collections import OrderedDict
from typing import Callable, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LRUCache:
    """Bounded cache that drops the oldest untouched entry first.

    >>> c = LRUCache(capacity=2)
    >>> c.put("a", 1)
    >>> c.put("b", 2)
    >>> c.get("a")
    1
    >>> c.put("c", 3)          # evicts "b" (least recently used)
    >>> c.get("b") is None
    True
    >>> c.get("c")
    3
    """

    def __init__(self, capacity: int = 128):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._store: OrderedDict = OrderedDict()

    def get(self, key: K) -> V | None:
        """Return value for `key`, marking it as recently used. None on miss."""
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def put(self, key: K, value: V) -> None:
        """Insert or update `key`. Evicts LRU entry if at capacity."""
        if key in self._store:
            self._store.move_to_end(key)
            self._store[key] = value
            return
        if len(self._store) >= self._capacity:
            self._store.popitem(last=False)
        self._store[key] = value

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: K) -> bool:
        return key in self._store

    def keys(self) -> list:
        """Keys in LRU order (oldest first)."""
        return list(self._store.keys())

    def clear(self) -> None:
        self._store.clear()


def lru_memoize(capacity: int = 128) -> Callable:
    """Decorator: cache return values of a single-argument function.

    >>> @lru_memoize(capacity=2)
    ... def square(n):
    ...     return n * n
    >>> square(3)
    9
    >>> square(3)   # cached
    9
    """

    def decorator(fn: Callable[[K], V]) -> Callable[[K], V]:
        cache = LRUCache(capacity=capacity)

        def wrapper(key: K) -> V:
            hit = cache.get(key)
            if hit is not None:
                return hit
            result = fn(key)
            cache.put(key, result)
            return result

        wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
        wrapper.cache = cache  # type: ignore[attr-defined]
        return wrapper

    return decorator
