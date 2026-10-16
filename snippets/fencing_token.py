"""072 — fencing token: defeat zombie writers after crash-recovery.

when a process is recycled (container kill, OOM, network partition),
a new instance takes over.  but the old one might still be alive for
a few milliseconds — long enough to corrupt shared state with a
stale write.  fencing tokens solve this the way lamport clocks
solved causality: with a monotonic number.

the rule is simple:

    every new epoch gets a strictly increasing token.
    writes must carry the current token.
    a write with token < current is rejected as stale.

this is orthogonal to leases (time-bounded) and WAL (crash-recovery).
a lease says "you own this until T".  a WAL says "here is what you
intended to do".  a fencing token says "you are the latest writer,
and here is proof".

typical flow:

    epoch = FencingEpoch()
    t1 = epoch.advance()          # first writer gets token 1
    epoch.check(t1)               # → True
    # crash!  new writer starts:
    t2 = epoch.advance()          # token 2
    epoch.check(t1)               # → False  (stale!)
    epoch.check(t2)               # → True

design choices:

- **monotonic, not sequential**: tokens increase but gaps are fine.
  what matters is "newer > older", not "next == prev + 1".
- **zero dependencies**: stdlib only.
- **history ring**: last N tokens are kept for diagnostics.
  ``stale_tokens()`` tells you how many zombie writes were caught.

>>> epoch = FencingEpoch()
>>> t1 = epoch.advance()
>>> t1
1
>>> epoch.check(t1)
True
>>> t2 = epoch.advance()
>>> epoch.check(t1)
False
>>> epoch.check(t2)
True
>>> epoch.stale_count()
1
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FencingEpoch:
    """Monotonic token generator that rejects stale writers."""

    _counter: int = field(default=0, init=False, repr=False)
    _current: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _history: deque = field(default_factory=lambda: deque(maxlen=64), init=False, repr=False)
    _stale_count: int = field(default=0, init=False, repr=False)
    _advance_count: int = field(default=0, init=False, repr=False)

    # ── core API ──────────────────────────────────────────────

    def advance(self) -> int:
        """Open a new epoch and return its fencing token.

        Each call invalidates all previous tokens.  The returned
        token is the *only* valid one until the next advance().

        >>> e = FencingEpoch()
        >>> e.advance() < e.advance()
        True
        """
        with self._lock:
            self._counter += 1
            self._current = self._counter
            self._advance_count += 1
            self._history.append(self._current)
            return self._current

    def check(self, token: int) -> bool:
        """Return True if *token* is the current (non-stale) epoch token.

        Returns False when no epoch has been opened (current == 0).

        >>> e = FencingEpoch()
        >>> e.check(0)
        False
        >>> t = e.advance()
        >>> e.check(t)
        True
        >>> e.advance()
        2
        >>> e.check(t)
        False
        """
        with self._lock:
            if self._current == 0:
                return False
            is_current = token == self._current
            if not is_current and token > 0:
                self._stale_count += 1
            return is_current

    def guard(self, token: int) -> None:
        """Raise ``StaleTokenError`` if *token* is not current.

        Use this at the top of any function that must refuse stale writes.

        >>> e = FencingEpoch()
        >>> t = e.advance()
        >>> e.guard(t)  # passes silently
        >>> e.advance()
        2
        >>> passed = False
        >>> try:
        ...     e.guard(t)
        ... except StaleTokenError as exc:
        ...     passed = "stale token 1" in str(exc)
        >>> passed
        True
        """
        if not self.check(token):
            raise StaleTokenError(
                f"stale token {token} (current is {self._current})"
            )

    # ── queries ───────────────────────────────────────────────

    @property
    def current(self) -> int:
        """The latest valid token.  0 means no epoch has been opened."""
        return self._current

    @property
    def total_advances(self) -> int:
        """How many times advance() has been called."""
        return self._advance_count

    def stale_count(self) -> int:
        """Number of check()/guard() calls that were rejected as stale.

        >>> e = FencingEpoch()
        >>> t1 = e.advance()
        >>> _ = e.advance()
        >>> e.check(t1)
        False
        >>> e.stale_count()
        1
        """
        return self._stale_count

    def history(self) -> list:
        """Return recent tokens (newest last), up to 64 entries.

        >>> e = FencingEpoch()
        >>> [e.advance() for _ in range(3)]
        [1, 2, 3]
        >>> e.history()
        [1, 2, 3]
        """
        return list(self._history)

    def reset(self) -> int:
        """Reset to epoch zero and return the new (invalid) current token.

        Useful in tests; production code should never reset a live epoch.

        >>> e = FencingEpoch()
        >>> e.advance()
        1
        >>> e.reset()
        0
        >>> e.current
        0
        """
        with self._lock:
            self._counter = 0
            self._current = 0
            self._stale_count = 0
            self._advance_count = 0
            self._history.clear()
            return self._current

    def __repr__(self) -> str:
        return (
            f"FencingEpoch(current={self._current}, "
            f"advances={self._advance_count}, "
            f"stale={self._stale_count})"
        )


class StaleTokenError(Exception):
    """Raised when a write presents an outdated fencing token."""
