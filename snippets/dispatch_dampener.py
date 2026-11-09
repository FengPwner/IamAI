"""585 — dispatch_dampener: rate-limit supervisor recovery actions.

supervisor_dispatch routes escalation levels to handlers — but nothing
stops a flapping escalation from firing the same handler twenty times
in a minute. every restart costs warmup time, git state churn, and
credibility with whoever reads the commit log.

this module sits between the escalation relay and the dispatcher as a
gatekeeper:

    escalation ──► relay ──► dampener ──► dispatcher
                              │
                              └── "no, you just did that 30 seconds ago"

it tracks recent dispatch timestamps per action label and suppresses
requests that arrive too soon. the policy is simple: within any window
of `cooldown` seconds, at most `max_burst` dispatches of the same label
are allowed.

design decisions:

  1. **per-label, not global.** a restart and a page-oncall are
     different actions with different costs. the dampener tracks each
     label independently so suppressing a restart doesn't accidentally
     block a legitimate page.

  2. **sliding window via deque.** timestamps live in a bounded deque
     per label. on each `allow()` call, stale entries (older than the
     cooldown) are pruned from the left. if len(deque) < max_burst,
     the dispatch is allowed; otherwise suppressed.

  3. **suppress ≠ forget.** suppressed dispatches are counted in
     `suppressed_count` and recorded in `suppressions` (label,
     timestamp, consecutive suppression count) so monitoring can
     detect "supervisor wanted to act 50 times but was only allowed
     3" — a strong signal of flapping.

  4. **injectable clock.** same pattern as every other module in this
     project: pass `clock=lambda: my_time` for deterministic tests.

  5. **composable with SupervisorDispatch.** wrap any dispatch call:
     `if dampener.allow(action): dispatcher.dispatch(level, ctx)`.
     or use `guard()` which does the check-and-dispatch in one call.

zero dependencies. stdlib only.

>>> d = DispatchDampener(cooldown=60.0, max_burst=2)
>>> d.allow("restart")
True
>>> d.allow("restart")
True
>>> d.allow("restart")   # third within 60s → suppressed
False
>>> d.suppressed_count
1
>>> d.allow("page_oncall")   # different label → independent
True
>>> d.summary()
{'labels': 2, 'allowed': 3, 'suppressed': 1}
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DampenerVerdict:
    """Outcome of a guard() call."""

    label: str
    allowed: bool
    suppressed_consecutive: int = 0
    detail: str = ""

    def __bool__(self) -> bool:
        return self.allowed


# ---------------------------------------------------------------------------
# suppression record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SuppressionRecord:
    """Recorded when a dispatch is suppressed."""

    label: str
    timestamp: float
    consecutive: int
    window_remaining: float  # seconds until the oldest entry expires


# ---------------------------------------------------------------------------
# dampener
# ---------------------------------------------------------------------------


class DispatchDampener:
    """Rate-limit dispatches per action label within a sliding window."""

    __slots__ = (
        "_cooldown",
        "_max_burst",
        "_windows",
        "_suppressed_streak",
        "_suppressed_count",
        "_allowed_count",
        "_suppressions",
        "_clock",
    )

    def __init__(
        self,
        cooldown: float = 300.0,
        max_burst: int = 3,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if cooldown <= 0:
            raise ValueError("cooldown must be positive")
        if max_burst < 1:
            raise ValueError("max_burst must be >= 1")

        self._cooldown = cooldown
        self._max_burst = max_burst
        self._windows: Dict[str, Deque[float]] = {}
        self._suppressed_streak: Dict[str, int] = {}
        self._suppressed_count: int = 0
        self._allowed_count: int = 0
        self._suppressions: List[SuppressionRecord] = []
        self._clock = clock or time.monotonic

    # -- public API ---------------------------------------------------------

    @property
    def cooldown(self) -> float:
        """Window size in seconds."""
        return self._cooldown

    @property
    def max_burst(self) -> int:
        """Maximum dispatches allowed per label within the window."""
        return self._max_burst

    @property
    def suppressed_count(self) -> int:
        """Total number of suppressed dispatches across all labels."""
        return self._suppressed_count

    @property
    def allowed_count(self) -> int:
        """Total number of allowed dispatches across all labels."""
        return self._allowed_count

    @property
    def suppressions(self) -> List[SuppressionRecord]:
        """Copy of all suppression records."""
        return list(self._suppressions)

    @property
    def tracked_labels(self) -> List[str]:
        """Sorted list of labels that have been seen."""
        return sorted(self._windows.keys())

    def allow(self, label: str) -> bool:
        """Check whether a dispatch for *label* is allowed right now.

        If allowed, the current timestamp is recorded and True is returned.
        If suppressed, the suppression counter increments and False is
        returned.
        """
        now = self._clock()
        window = self._windows.setdefault(label, deque())
        self._prune(window, now)

        if len(window) < self._max_burst:
            window.append(now)
            self._allowed_count += 1
            self._suppressed_streak[label] = 0
            return True

        # suppressed
        self._suppressed_count += 1
        streak = self._suppressed_streak.get(label, 0) + 1
        self._suppressed_streak[label] = streak

        oldest = window[0] if window else now
        remaining = max(0.0, self._cooldown - (now - oldest))
        self._suppressions.append(
            SuppressionRecord(
                label=label,
                timestamp=now,
                consecutive=streak,
                window_remaining=round(remaining, 3),
            )
        )
        return False

    def guard(
        self,
        label: str,
        dispatch_fn: Callable[[], Any],
    ) -> DampenerVerdict:
        """Check-then-dispatch in one call.

        If allowed, calls `dispatch_fn()` and returns a verdict with
        allowed=True. If suppressed, dispatch_fn is NOT called and the
        verdict carries the consecutive suppression count.
        """
        if self.allow(label):
            dispatch_fn()
            return DampenerVerdict(
                label=label,
                allowed=True,
                suppressed_consecutive=0,
            )

        return DampenerVerdict(
            label=label,
            allowed=False,
            suppressed_consecutive=self._suppressed_streak.get(label, 0),
            detail=f"suppressed: {self._suppressed_streak.get(label, 0)} consecutive",
        )

    def time_until_next(self, label: str) -> float:
        """Seconds until the next dispatch for *label* would be allowed.

        Returns 0.0 if a dispatch is allowed right now.
        """
        window = self._windows.get(label)
        if not window:
            return 0.0

        now = self._clock()
        self._prune(window, now)

        if len(window) < self._max_burst:
            return 0.0

        oldest = window[0]
        return max(0.0, self._cooldown - (now - oldest))

    def reset(self, label: Optional[str] = None) -> None:
        """Clear state. If label is given, only that label is cleared."""
        if label is not None:
            self._windows.pop(label, None)
            self._suppressed_streak.pop(label, None)
        else:
            self._windows.clear()
            self._suppressed_streak.clear()
            self._suppressed_count = 0
            self._allowed_count = 0
            self._suppressions.clear()

    def summary(self) -> Dict[str, Any]:
        """Compact summary for monitoring."""
        return {
            "labels": len(self._windows),
            "allowed": self._allowed_count,
            "suppressed": self._suppressed_count,
        }

    def __repr__(self) -> str:
        return (
            f"DispatchDampener(cooldown={self._cooldown}, "
            f"max_burst={self._max_burst}, "
            f"allowed={self._allowed_count}, "
            f"suppressed={self._suppressed_count})"
        )

    # -- internals ----------------------------------------------------------

    def _prune(self, window: Deque[float], now: float) -> None:
        """Remove timestamps older than the cooldown window."""
        cutoff = now - self._cooldown
        while window and window[0] <= cutoff:
            window.popleft()
