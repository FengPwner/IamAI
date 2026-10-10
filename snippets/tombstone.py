"""42 — tombstone: mark deletions so they propagate and survive replication.

in a replicated or eventually-consistent store, a plain delete is invisible:
node B never learns that node A removed key K, so the next sync resurrects
it.  the fix is to replace the value with a *tombstone* — a marker that says
"this key was deleted at time T" — and let that marker propagate just like
a normal write.

tombstone is a tiny registry that tracks which keys have been deleted and
when.  it supports the operations you actually need:

    mark(key)          → record a deletion, returns the Tombstone entry
    check(key)         → True if key has an unexpired tombstone
    peek(key)          → the entry itself (or None), no side-effects
    compact(before)    → purge tombstones older than a cutoff
    merge(other)       → absorb another registry's markers (last-write-wins)
    keys()             → iterate all currently tombstoned keys

why not just use a set?  because you need the timestamp to resolve
conflicts during merge (newer delete wins) and to know when compaction
is safe (once all replicas have seen the deletion).

zero dependencies.  stdlib only.

>>> ts = TombstoneStore()
>>> ts.mark("user:42")
Tombstone(key='user:42', ...)
>>> ts.check("user:42")
True
>>> ts.check("user:99")
False
>>> ts.peek("user:42").deleted  # doctest: +ELLIPSIS
True
>>> ts.compact(before=0)        # purge everything
1
>>> ts.check("user:42")
False
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Iterator, Optional


@dataclass(frozen=True, slots=True)
class Tombstone:
    """Immutable record of a single deletion.

    Attributes
    ----------
    key : str
        The key that was deleted.
    deleted_at : float
        Monotonic timestamp of the deletion (``time.monotonic()``).
    wall_clock : float
        Wall-clock timestamp (``time.time()``) for human-readable logs.
    reason : str
        Optional human-readable reason for the deletion.
    """

    key: str
    deleted_at: float
    wall_clock: float = 0.0
    reason: str = ""

    @property
    def deleted(self) -> bool:
        """Always True for a valid tombstone — useful for None-safe checks."""
        return True

    @property
    def age(self) -> float:
        """Seconds since deletion (monotonic)."""
        return time.monotonic() - self.deleted_at


@dataclass
class TombstoneStore:
    """Registry of tombstoned keys with merge and compaction.

    Parameters
    ----------
    ttl : float
        Default time-to-live in seconds.  Tombstones older than this are
        eligible for compaction.  ``0`` means "never expire" (the caller
        must compact explicitly with a ``before`` argument).
    clock : callable
        Source of monotonic time.  Override for deterministic tests.

    >>> store = TombstoneStore(ttl=60)
    >>> store.mark("session:abc", reason="user logout")
    Tombstone(key='session:abc', ...)
    >>> store.check("session:abc")
    True
    """

    ttl: float = 0.0
    clock: object = field(default=time.monotonic, repr=False)
    _stones: Dict[str, Tombstone] = field(default_factory=dict, repr=False)

    # ---- core operations ------------------------------------------------

    def mark(
        self,
        key: str,
        reason: str = "",
        deleted_at: Optional[float] = None,
    ) -> Tombstone:
        """Record a deletion.  Overwrites any existing tombstone for *key*
        if the new one is strictly newer (last-write-wins).

        Parameters
        ----------
        key : str
            The key being deleted.
        reason : str
            Optional human-readable reason.
        deleted_at : float, optional
            Explicit monotonic timestamp.  Defaults to ``self.clock()``.
        """
        now = deleted_at if deleted_at is not None else self.clock()
        existing = self._stones.get(key)
        if existing is not None and existing.deleted_at >= now:
            return existing  # existing marker is newer or equal — keep it
        entry = Tombstone(
            key=key,
            deleted_at=now,
            wall_clock=time.time(),
            reason=reason,
        )
        self._stones[key] = entry
        return entry

    def check(self, key: str) -> bool:
        """True if *key* has a live (unexpired or non-TTL) tombstone."""
        entry = self._stones.get(key)
        if entry is None:
            return False
        if self.ttl > 0:
            age = self.clock() - entry.deleted_at
            if age > self.ttl:
                return False
        return True

    def peek(self, key: str) -> Optional[Tombstone]:
        """Return the tombstone entry for *key*, or None."""
        return self._stones.get(key)

    def unmark(self, key: str) -> bool:
        """Remove the tombstone for *key* (resurrection).  Returns True if
        a tombstone was actually removed."""
        return self._stones.pop(key, None) is not None

    # ---- bulk operations ------------------------------------------------

    def keys(self) -> Iterator[str]:
        """Iterate all tombstoned keys (including expired ones not yet
        compacted)."""
        return iter(self._stones)

    def __len__(self) -> int:
        return len(self._stones)

    def __contains__(self, key: str) -> bool:
        return self.check(key)

    # ---- replication helpers --------------------------------------------

    def compact(self, before: Optional[float] = None) -> int:
        """Purge tombstones older than *before* (monotonic).  If *before*
        is None, uses ``now - ttl``.  Returns count of purged entries.

        >>> store = TombstoneStore()
        >>> store.mark("a", deleted_at=1.0)
        Tombstone(key='a', ...)
        >>> store.mark("b", deleted_at=2.0)
        Tombstone(key='b', ...)
        >>> store.compact(before=1.5)
        1
        >>> list(store.keys())
        ['b']
        """
        if before is None:
            if self.ttl <= 0:
                return 0
            before = self.clock() - self.ttl
        expired = [k for k, v in self._stones.items() if v.deleted_at < before]
        for k in expired:
            del self._stones[k]
        return len(expired)

    def merge(self, other: "TombstoneStore") -> int:
        """Absorb another store's tombstones (last-write-wins).  Returns
        count of entries actually updated.

        >>> a = TombstoneStore()
        >>> b = TombstoneStore()
        >>> a.mark("x", deleted_at=1.0)
        Tombstone(key='x', ...)
        >>> b.mark("x", deleted_at=2.0)
        Tombstone(key='x', ...)
        >>> b.mark("y", deleted_at=3.0)
        Tombstone(key='y', ...)
        >>> a.merge(b)
        2
        >>> a.check("y")
        True
        """
        updated = 0
        for key, entry in other._stones.items():
            existing = self._stones.get(key)
            if existing is None or entry.deleted_at > existing.deleted_at:
                self._stones[key] = entry
                updated += 1
        return updated

    # ---- diagnostics ----------------------------------------------------

    def summary(self) -> dict:
        """Return a JSON-friendly summary of the store."""
        now = self.clock()
        ages = [now - v.deleted_at for v in self._stones.values()]
        return {
            "count": len(self._stones),
            "oldest_age": max(ages) if ages else 0.0,
            "newest_age": min(ages) if ages else 0.0,
            "ttl": self.ttl,
        }

    def __repr__(self) -> str:
        return f"TombstoneStore(count={len(self._stones)}, ttl={self.ttl})"
