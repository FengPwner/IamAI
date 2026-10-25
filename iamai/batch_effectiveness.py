"""batch_effectiveness — is the batch committer actually succeeding?

A batch committer process can be alive (pid exists, CPU ticking) yet
failing every single commit attempt.  The classic case: a stale
``index.lock`` blocks every ``git commit`` with a fatal error, the
process logs the failure, sleeps, retries — and fails again.  From
the outside, the process looks healthy; from the inside, nothing is
getting committed.

This module tracks a sliding window of commit *attempts* and their
outcomes (success / failure), then classifies the committer's
effectiveness:

===========  =================================================
verdict      meaning
===========  =================================================
``healthy``  failure ratio below threshold — commits flowing
``degraded`` some failures, but successes still happening
``failing``  mostly failures; committer stuck in retry loop
``dead``     no attempts at all in the observation window
===========  =================================================

Design notes
------------

1. **Ring buffer** — we store the last N attempts (default 20) in a
   simple list, oldest first.  No external dependencies.

2. **Timestamps in epoch seconds** — caller passes ``time.time()``
   values so the module is testable without monkeypatching ``time``.

3. **Failure ratio** — ``failures / total_attempts`` over the window.
   Thresholds:

   - < 0.2  → healthy
   - < 0.6  → degraded
   - ≥ 0.6  → failing
   - 0 attempts → dead

4. **Streak detection** — if the last K attempts (default 5) are all
   failures, that's a ``stuck_streak`` regardless of the overall
   ratio.  A committer that was healthy an hour ago but just hit a
   lock file will show "healthy" by ratio but "stuck_streak" by
   recency.  The verdict function takes the worse of the two.

Usage::

    from iamai.batch_effectiveness import (
        BatchTracker, effectiveness, effectiveness_report,
    )

    tracker = BatchTracker(window=20)
    tracker.record(success=True,  at=1697700000.0)
    tracker.record(success=False, at=1697700600.0, reason="index.lock")
    tracker.record(success=False, at=1697701200.0, reason="index.lock")

    verdict = effectiveness(tracker)
    print(verdict)          # "failing"
    print(effectiveness_report(tracker))
    # "batch: failing — 1/3 success (33%), last 2 stuck, reason: index.lock"
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
DEGRADED_THRESHOLD = 0.2   # failure ratio above this → degraded
FAILING_THRESHOLD = 0.6    # failure ratio above this → failing
STREAK_LENGTH = 5          # consecutive failures to flag stuck_streak
DEFAULT_WINDOW = 20        # how many attempts to remember


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Attempt:
    """A single commit attempt."""
    success: bool
    at: float                      # epoch seconds
    reason: Optional[str] = None   # failure reason, if any


@dataclass
class BatchTracker:
    """Sliding-window tracker for batch committer effectiveness.

    Parameters
    ----------
    window : int
        Maximum number of attempts to retain (oldest evicted first).
    streak_length : int
        How many consecutive tail-failures constitute a stuck streak.
    """
    window: int = DEFAULT_WINDOW
    streak_length: int = STREAK_LENGTH
    _attempts: Deque[Attempt] = field(default_factory=lambda: deque())

    def record(
        self,
        success: bool,
        at: float,
        reason: Optional[str] = None,
    ) -> None:
        """Record one commit attempt."""
        self._attempts.append(Attempt(success=success, at=at, reason=reason))
        while len(self._attempts) > self.window:
            self._attempts.popleft()

    @property
    def attempts(self) -> List[Attempt]:
        return list(self._attempts)

    @property
    def total(self) -> int:
        return len(self._attempts)

    @property
    def successes(self) -> int:
        return sum(1 for a in self._attempts if a.success)

    @property
    def failures(self) -> int:
        return self.total - self.successes

    @property
    def failure_ratio(self) -> Optional[float]:
        if self.total == 0:
            return None
        return self.failures / self.total

    @property
    def last_reason(self) -> Optional[str]:
        """Most recent failure reason, or None if last attempt succeeded."""
        for a in reversed(self._attempts):
            if not a.success:
                return a.reason
        return None

    @property
    def is_stuck_streak(self) -> bool:
        """True if the last *streak_length* attempts are all failures."""
        if self.total < self.streak_length:
            return False
        tail = list(self._attempts)[-self.streak_length:]
        return all(not a.success for a in tail)

    @property
    def consecutive_failures(self) -> int:
        """Count of consecutive failures at the tail."""
        count = 0
        for a in reversed(self._attempts):
            if a.success:
                break
            count += 1
        return count

    def seconds_since_last_success(self, now: Optional[float] = None) -> Optional[float]:
        """Seconds since the last successful attempt, or None if none."""
        import time as _time
        _now = now if now is not None else _time.time()
        for a in reversed(self._attempts):
            if a.success:
                return _now - a.at
        return None

    def clear(self) -> None:
        self._attempts.clear()


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def effectiveness(tracker: BatchTracker) -> str:
    """Classify the batch committer's current effectiveness.

    Returns one of: ``"healthy"``, ``"degraded"``, ``"failing"``,
    ``"dead"``.
    """
    if tracker.total == 0:
        return "dead"

    ratio = tracker.failure_ratio

    # Stuck streak overrides ratio — even if the window is mostly
    # successes, five consecutive failures right now means trouble.
    if tracker.is_stuck_streak:
        return "failing"

    if ratio is None or ratio < DEGRADED_THRESHOLD:
        return "healthy"
    elif ratio < FAILING_THRESHOLD:
        return "degraded"
    else:
        return "failing"


def effectiveness_stats(tracker: BatchTracker, now: Optional[float] = None) -> dict:
    """Return detailed stats for dashboard consumption."""
    import time as _time
    _now = now if now is not None else _time.time()

    return {
        "verdict": effectiveness(tracker),
        "total_attempts": tracker.total,
        "successes": tracker.successes,
        "failures": tracker.failures,
        "failure_ratio": round(tracker.failure_ratio, 3) if tracker.failure_ratio is not None else None,
        "stuck_streak": tracker.is_stuck_streak,
        "consecutive_failures": tracker.consecutive_failures,
        "last_failure_reason": tracker.last_reason,
        "seconds_since_last_success": (
            round(tracker.seconds_since_last_success(now=_now), 1)
            if tracker.seconds_since_last_success(now=_now) is not None
            else None
        ),
    }


def effectiveness_report(tracker: BatchTracker, now: Optional[float] = None) -> str:
    """One-liner suitable for caretaker logs."""
    s = effectiveness_stats(tracker, now=now)

    if s["verdict"] == "dead":
        return f"batch: dead — no attempts in window ({tracker.window})"

    success_pct = round((1 - s["failure_ratio"]) * 100) if s["failure_ratio"] is not None else 0
    parts = [f"batch: {s['verdict']}"]
    parts.append(f"{s['successes']}/{s['total_attempts']} success ({success_pct}%)")

    if s["consecutive_failures"] > 0:
        parts.append(f"last {s['consecutive_failures']} stuck")

    if s["last_failure_reason"]:
        parts.append(f"reason: {s['last_failure_reason']}")

    if s["seconds_since_last_success"] is not None:
        parts.append(f"last ok {s['seconds_since_last_success']}s ago")
    else:
        parts.append("no successes in window")

    return " — ".join(parts)
