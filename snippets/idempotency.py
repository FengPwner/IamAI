"""Idempotency key store — reject duplicate work before it starts."""

import time
from typing import Any


class IdempotencyStore:
    """Track processed keys so the same request isn't handled twice.

    >>> s = IdempotencyStore(ttl=60.0, clock=lambda: 100.0)
    >>> s.accept("req-1")
    True
    >>> s.accept("req-1")          # duplicate
    False
    >>> s.result("req-1") is None  # no result stored yet
    True
    >>> s.record("req-1", {"ok": True})
    >>> s.result("req-1")
    {'ok': True}
    """

    def __init__(
        self,
        *,
        ttl: float = 300.0,
        clock: "Any | None" = None,
    ):
        if ttl < 0:
            raise ValueError("ttl must be >= 0")
        self._ttl = ttl
        self._clock = clock or time.monotonic
        self._store: dict[str, tuple[float, Any]] = {}

    def accept(self, key: str) -> bool:
        """Return True if `key` is new (or expired), False if duplicate."""
        now = self._clock()
        if key in self._store:
            ts, _ = self._store[key]
            if now - ts < self._ttl:
                return False
        self._store[key] = (now, None)
        return True

    def record(self, key: str, result: Any) -> None:
        """Attach a result to a previously accepted key."""
        if key not in self._store:
            raise KeyError(f"unknown key: {key}")
        ts, _ = self._store[key]
        self._store[key] = (ts, result)

    def result(self, key: str) -> Any:
        """Return the stored result, or None if absent."""
        entry = self._store.get(key)
        return entry[1] if entry else None

    def evict(self) -> int:
        """Remove expired entries; return how many were purged."""
        now = self._clock()
        expired = [k for k, (ts, _) in self._store.items() if now - ts >= self._ttl]
        for k in expired:
            del self._store[k]
        return len(expired)

    def __len__(self) -> int:
        return len(self._store)
