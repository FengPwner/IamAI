"""061 — latch: a one-shot gate that blocks until released, then stays open.

sometimes you need the inverse of a fuse: instead of "fire once then lock
forever," you want "block everyone until one event happens, then let them
all through." a latch is a single-use barrier. threads (or coroutines, or
processes sharing a flag) wait on it; the moment someone trips it, every
waiter unblocks and future checks pass immediately.

use cases from this codebase:

- "don't commit until the writer has produced at least one stroke"
- "hold push attempts until the lock-cleaner has run"
- "gate the caretaker's first heartbeat until both processes are up"

the implementation is deliberately trivial — a threading.Event under the
hood — because the value is in the *name* and the *contract*. calling code
reads `latch.wait()` and knows: this blocks at most once, then never again.

    latch = Latch()
    latch.is_set          # False
    latch.wait(timeout=1) # False (timed out)
    latch.release()
    latch.is_set          # True
    latch.wait()          # returns instantly

releasing an already-released latch is a no-op, so multiple callers can
race to trip it without coordination.

zero external dependencies. stdlib only.
"""

from __future__ import annotations

import threading
from typing import Optional


class Latch:
    """One-shot barrier: blocks until released, then stays open forever."""

    def __init__(self, *, released: bool = False) -> None:
        self._event = threading.Event()
        if released:
            self._event.set()

    # -- query -----------------------------------------------------------

    @property
    def is_set(self) -> bool:
        """True once the latch has been released."""
        return self._event.is_set()

    @property
    def is_released(self) -> bool:
        """Alias for is_set, for call-sites that prefer the verb."""
        return self._event.is_set()

    # -- mutate ----------------------------------------------------------

    def release(self) -> None:
        """Trip the latch. Idempotent — safe to call multiple times."""
        self._event.set()

    # -- wait ------------------------------------------------------------

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until released or *timeout* seconds elapse.

        Returns True if the latch was (or already is) released, False on
        timeout.  A timeout of None (the default) blocks forever.
        """
        return self._event.wait(timeout=timeout)

    # -- dunder ----------------------------------------------------------

    def __repr__(self) -> str:
        state = "released" if self.is_set else "waiting"
        return f"Latch({state})"

    def __bool__(self) -> bool:
        """Truthy when released, falsy when still blocking."""
        return self.is_set
