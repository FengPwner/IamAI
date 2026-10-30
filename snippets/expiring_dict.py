"""ExpiringDict — a dict whose keys auto-expire after a configurable TTL.

Useful for caching, rate-limit windows, and short-lived agent state where
stale data is worse than missing data. Zero dependencies, no threads.

>>> import time
>>> d = ExpiringDict(ttl=0.1, clock=time.monotonic)
>>> d["a"] = 1
>>> d["a"]
1
>>> time.sleep(0.15)
>>> d.get("a") is None
True
>>> len(d)
0
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterator


class ExpiringDict:
    """A mapping where each key expires after `ttl` seconds.

    >>> d = ExpiringDict(ttl=60)
    >>> d["x"] = 42
    >>> d["x"]
    42
    >>> "x" in d
    True
    """

    def __init__(
        self,
        ttl: float = 300.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        self._ttl = ttl
        self._clock = clock
        self._store: dict[str, tuple[Any, float]] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        self._store[key] = (value, self._clock() + self._ttl)

    def __getitem__(self, key: str) -> Any:
        self._evict(key)
        return self._store[key][0]

    def __contains__(self, key: object) -> bool:
        if key not in self._store:
            return False
        self._evict(str(key))
        return str(key) in self._store

    def __delitem__(self, key: str) -> None:
        del self._store[key]

    def __len__(self) -> int:
        self.sweep()
        return len(self._store)

    def __iter__(self) -> Iterator[str]:
        self.sweep()
        return iter(list(self._store))

    def get(self, key: str, default: Any = None) -> Any:
        """Return value or default; silently drop expired keys.

        >>> d = ExpiringDict(ttl=60)
        >>> d.get("missing", "fallback")
        'fallback'
        """
        self._evict(key)
        entry = self._store.get(key)
        return entry[0] if entry is not None else default

    def touch(self, key: str) -> bool:
        """Reset the TTL on an existing key. Returns True if refreshed.

        >>> d = ExpiringDict(ttl=60)
        >>> d["k"] = "v"
        >>> d.touch("k")
        True
        >>> d.touch("nope")
        False
        """
        self._evict(key)
        if key in self._store:
            val = self._store[key][0]
            self._store[key] = (val, self._clock() + self._ttl)
            return True
        return False

    def sweep(self) -> int:
        """Remove all expired keys. Returns count of evicted entries.

        >>> d = ExpiringDict(ttl=0.01, clock=time.monotonic)
        >>> d["a"] = 1; d["b"] = 2
        >>> import time; time.sleep(0.02)
        >>> d.sweep()
        2
        """
        now = self._clock()
        expired = [k for k, (_, exp) in self._store.items() if exp <= now]
        for k in expired:
            del self._store[k]
        return len(expired)

    def keys(self) -> list[str]:
        self.sweep()
        return list(self._store)

    def values(self) -> list[Any]:
        self.sweep()
        return [v for v, _ in self._store.values()]

    def items(self) -> list[tuple[str, Any]]:
        self.sweep()
        return [(k, v) for k, (v, _) in self._store.items()]

    def _evict(self, key: str) -> None:
        entry = self._store.get(key)
        if entry is not None and entry[1] <= self._clock():
            del self._store[key]
