"""071 — write-ahead log: crash-safe durability for in-flight work.

a write-ahead log (WAL) answers the oldest question in systems:
"what happens if the power goes out *right now*?"

the answer here is simple: every piece of work gets logged *before*
it happens.  if the process crashes, the log survives.  on restart,
you replay what was committed but never applied, and discard what
was never committed.

lifecycle of a WAL entry:

    append(data)  →  pending   (logged, not yet safe to apply)
    commit(lsn)   →  committed (safe to apply; crash → replay)
    checkpoint()  →  done      (applied; can be pruned)

three queries tell you everything:

    pending()     → list of entries waiting for commit
    recover()     → list of committed entries not yet checkpointed
    stats()       → dict with counts per status + total

design choices:

- **in-memory**: this is a snippet, not a database.  swap the dict
  for a file-backed store in production.
- **monotonic LSN**: each append gets a strictly increasing sequence
  number.  no reuse, no gaps (unless you skip-commit, which is fine).
- **idempotent commit/checkpoint**: committing an already-committed
  LSN is a no-op, not an error.  same for checkpoint.
- **zero dependencies**: stdlib only.

>>> wal = WriteAheadLog()
>>> lsn1 = wal.append("stroke: hello world")
>>> lsn2 = wal.append("stroke: second thought")
>>> wal.pending()
[1, 2]
>>> wal.commit(lsn1)
>>> wal.recover()
[1]
>>> wal.checkpoint(lsn1)
1
>>> wal.recover()
[]
>>> wal.stats()
{'pending': 1, 'committed': 0, 'checkpointed': 1, 'total': 2}
>>> # idempotent commit
>>> wal.commit(lsn1)
>>> wal.stats()['committed']
0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class Status(Enum):
    """Lifecycle phase of a WAL entry."""
    PENDING = "pending"
    COMMITTED = "committed"
    CHECKPOINTED = "checkpointed"


@dataclass
class _Entry:
    """Internal representation of a WAL record."""
    lsn: int
    data: Any
    status: Status = Status.PENDING


@dataclass
class WriteAheadLog:
    """Crash-safe write-ahead log.

    Every piece of work passes through three phases:
    pending → committed → checkpointed.

    >>> wal = WriteAheadLog()
    >>> len(wal)
    0
    """

    _entries: Dict[int, _Entry] = field(default_factory=dict)
    _next_lsn: int = field(default=1)

    # ------------------------------------------------------------------
    # write path
    # ------------------------------------------------------------------

    def append(self, data: Any) -> int:
        """Log a new entry and return its sequence number.

        The entry starts as *pending* — logged but not yet safe to
        apply.  Call :meth:`commit` when the work is durable.

        >>> wal = WriteAheadLog()
        >>> lsn = wal.append("first stroke")
        >>> lsn
        1
        >>> wal.append("second stroke")
        2
        """
        lsn = self._next_lsn
        self._entries[lsn] = _Entry(lsn=lsn, data=data)
        self._next_lsn += 1
        return lsn

    def commit(self, lsn: int) -> None:
        """Mark *lsn* as committed (safe to apply).

        Idempotent: committing an already-committed or checkpointed
        entry is a silent no-op.

        >>> wal = WriteAheadLog()
        >>> lsn = wal.append("work")
        >>> wal.commit(lsn)
        >>> wal.commit(lsn)  # no-op, no error

        Raises
        ------
        KeyError
            If *lsn* was never appended.
        """
        entry = self._entries.get(lsn)
        if entry is None:
            raise KeyError(f"lsn {lsn} not found in WAL")
        if entry.status == Status.PENDING:
            entry.status = Status.COMMITTED

    def checkpoint(self, lsn: int | None = None) -> int:
        """Mark entries as applied and eligible for pruning.

        If *lsn* is given, mark that single entry.  If omitted,
        checkpoint every committed entry.  Returns the count of
        newly checkpointed entries.

        >>> wal = WriteAheadLog()
        >>> a = wal.append("x")
        >>> b = wal.append("y")
        >>> wal.commit(a); wal.commit(b)
        >>> wal.checkpoint()
        2
        >>> wal.checkpoint()  # already done
        0

        Raises
        ------
        KeyError
            If *lsn* is given but was never appended.
        ValueError
            If *lsn* is given but is still pending (not committed).
        """
        if lsn is not None:
            entry = self._entries.get(lsn)
            if entry is None:
                raise KeyError(f"lsn {lsn} not found in WAL")
            if entry.status == Status.PENDING:
                raise ValueError(
                    f"lsn {lsn} is still pending; commit before checkpoint"
                )
            if entry.status == Status.COMMITTED:
                entry.status = Status.CHECKPOINTED
                return 1
            return 0  # already checkpointed

        # checkpoint all committed entries
        count = 0
        for entry in self._entries.values():
            if entry.status == Status.COMMITTED:
                entry.status = Status.CHECKPOINTED
                count += 1
        return count

    # ------------------------------------------------------------------
    # recovery
    # ------------------------------------------------------------------

    def recover(self) -> List[int]:
        """Return LSNs of committed-but-not-checkpointed entries.

        After a crash, these are the entries whose work must be
        replayed (or verified) before the system is consistent.

        >>> wal = WriteAheadLog()
        >>> a = wal.append("x")
        >>> b = wal.append("y")
        >>> wal.commit(a)
        >>> wal.recover()
        [1]
        >>> wal.checkpoint(a)
        1
        >>> wal.recover()
        []
        """
        return sorted(
            lsn for lsn, e in self._entries.items()
            if e.status == Status.COMMITTED
        )

    def pending(self) -> List[int]:
        """Return LSNs of entries that haven't been committed yet.

        >>> wal = WriteAheadLog()
        >>> wal.append("a"); wal.append("b")
        1
        2
        >>> wal.pending()
        [1, 2]
        """
        return sorted(
            lsn for lsn, e in self._entries.items()
            if e.status == Status.PENDING
        )

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------

    def get(self, lsn: int) -> Any:
        """Return the data stored at *lsn*.

        >>> wal = WriteAheadLog()
        >>> lsn = wal.append({"stroke": "hello"})
        >>> wal.get(lsn)
        {'stroke': 'hello'}

        Raises
        ------
        KeyError
            If *lsn* was never appended.
        """
        return self._entries[lsn].data

    def status(self, lsn: int) -> str:
        """Return the lifecycle status of *lsn* as a string.

        >>> wal = WriteAheadLog()
        >>> lsn = wal.append("work")
        >>> wal.status(lsn)
        'pending'
        >>> wal.commit(lsn)
        >>> wal.status(lsn)
        'committed'

        Raises
        ------
        KeyError
            If *lsn* was never appended.
        """
        entry = self._entries.get(lsn)
        if entry is None:
            raise KeyError(f"lsn {lsn} not found in WAL")
        return entry.status.value

    def stats(self) -> dict:
        """Return counts per status and total entries.

        >>> wal = WriteAheadLog()
        >>> wal.append("a"); wal.append("b"); wal.append("c")
        1
        2
        3
        >>> wal.commit(1)
        >>> wal.commit(2)
        >>> wal.checkpoint(1)
        1
        >>> wal.stats()
        {'pending': 1, 'committed': 1, 'checkpointed': 1, 'total': 3}
        """
        counts = {s.value: 0 for s in Status}
        for entry in self._entries.values():
            counts[entry.status.value] += 1
        counts["total"] = len(self._entries)
        return counts

    def prune(self) -> int:
        """Remove all checkpointed entries from the log.

        Returns the number of entries removed.  This is how you
        reclaim memory once work is fully applied.

        >>> wal = WriteAheadLog()
        >>> lsn = wal.append("done")
        >>> wal.commit(lsn); wal.checkpoint(lsn)
        1
        >>> wal.prune()
        1
        >>> len(wal)
        0
        """
        to_remove = [
            lsn for lsn, e in self._entries.items()
            if e.status == Status.CHECKPOINTED
        ]
        for lsn in to_remove:
            del self._entries[lsn]
        return len(to_remove)

    # ------------------------------------------------------------------
    # dunder
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Total entries in the log (all statuses).

        >>> wal = WriteAheadLog()
        >>> len(wal)
        0
        >>> wal.append("x")
        1
        >>> len(wal)
        1
        """
        return len(self._entries)

    def __contains__(self, lsn: int) -> bool:
        """Check whether *lsn* exists in the log.

        >>> wal = WriteAheadLog()
        >>> lsn = wal.append("x")
        >>> lsn in wal
        True
        >>> 999 in wal
        False
        """
        return lsn in self._entries

    def __repr__(self) -> str:
        s = self.stats()
        return (
            f"WriteAheadLog(pending={s['pending']}, "
            f"committed={s['committed']}, "
            f"checkpointed={s['checkpointed']})"
        )


if __name__ == "__main__":
    import doctest

    doctest.testmod()
