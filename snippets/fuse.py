"""Fuse — a one-shot, non-resettable circuit breaker.

circuit_breaker.py models a *resettable* breaker: it trips on failures,
opens the circuit, then probes for recovery and closes again.  That is
the right metaphor for a transient fault — the downstream service
might come back.

But some conditions are terminal.  A push race that corrupted the
index.  A credentials file that was deleted.  A license that expired.
Once these happen, retrying is not just wasteful — it is wrong.
You want a *fuse*: blow once, stay blown, force a human to inspect.

Fuse tracks a monotonic failure counter.  When it reaches ``limit``,
the fuse blows permanently.  ``allow()`` returns False for every
subsequent call.  There is no reset, no half-open probe, no timeout.
The only way to "fix" a blown fuse is to create a new one — which
is exactly the point: it forces a deliberate restart.

Zero dependencies.  Stdlib only.

>>> f = Fuse(limit=3)
>>> f.allow()
True
>>> f.record_failure()
>>> f.allow()
True
>>> f.record_failure()
>>> f.record_failure()
>>> f.allow()
False
>>> f.blown
True
"""

from __future__ import annotations

from typing import Callable


class Fuse:
    """One-shot failure counter.  Blows at ``limit`` failures, never resets.

    Parameters
    ----------
    limit : int
        Number of failures before the fuse blows.  Must be >= 1.
    on_blow : callable, optional
        Invoked exactly once when the fuse blows (not on subsequent calls).
        Receives no arguments.  Useful for logging, alerts, or stopping
        a process.

    Examples
    --------
    >>> f = Fuse(limit=2)
    >>> f.failures
    0
    >>> f.record_failure()
    >>> f.blown
    False
    >>> f.record_failure()
    >>> f.blown
    True
    >>> f.allow()
    False
    """

    def __init__(
        self,
        limit: int = 3,
        on_blow: Callable[[], None] | None = None,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self._limit = limit
        self._failures = 0
        self._blown = False
        self._on_blow = on_blow

    @property
    def limit(self) -> int:
        """The failure threshold."""
        return self._limit

    @property
    def failures(self) -> int:
        """Current failure count (capped at limit)."""
        return self._failures

    @property
    def blown(self) -> bool:
        """True once the fuse has blown."""
        return self._blown

    @property
    def remaining(self) -> int:
        """How many more failures until the fuse blows."""
        return max(0, self._limit - self._failures)

    def allow(self) -> bool:
        """Return True if the fuse is still intact, False if blown.

        This is the primary gate: call it before attempting the protected
        operation.  If it returns False, skip the operation.
        """
        return not self._blown

    def record_failure(self) -> None:
        """Record one failure.  Blows the fuse when the counter reaches limit.

        The on_blow callback fires exactly once — on the call that crosses
        the threshold.  Subsequent calls are no-ops.
        """
        if self._blown:
            return
        self._failures += 1
        if self._failures >= self._limit:
            self._blown = True
            if self._on_blow is not None:
                self._on_blow()

    def record_success(self) -> None:
        """Record a success.  Does NOT reset the failure counter.

        This is intentional: a fuse is not a circuit breaker.  Successes
        don't heal a blown fuse.  They're tracked for observability only.
        """
        # Successes don't reduce failures.  The fuse only goes one way.
        pass

    def __repr__(self) -> str:
        state = "BLOWN" if self._blown else f"{self.remaining}/{self._limit} remaining"
        return f"Fuse(limit={self._limit}, failures={self._failures}, {state})"
