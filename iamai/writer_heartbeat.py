#!/usr/bin/env python3
"""writer_heartbeat — detect a silent writer before the batch committer notices.

The IamAI writer emits a stroke every 15 seconds.  When it stops,
the batch committer keeps running on stale data, committing nothing
useful, and the caretaker only learns about the failure on its next
scheduled visit — potentially hours later.

This module provides a lightweight heartbeat monitor that:

1. **Records** each stroke as it arrives (timestamp + sequence number).
2. **Evaluates** whether the writer is alive based on the gap between
   the most recent stroke and the current time.
3. **Classifies** the writer's state into one of three bands:

   - ``healthy`` — last stroke within ``healthy_s`` seconds (default 45).
   - ``degraded`` — last stroke within ``degraded_s`` seconds (default 120).
   - ``dead`` — last stroke older than ``degraded_s``, or no stroke ever.

4. **Reports** a structured dict suitable for logging or alerting.

Public API::

    from iamai.writer_heartbeat import HeartbeatMonitor

    monitor = HeartbeatMonitor()
    monitor.record_stroke(seq=6700, at=1000.0)
    monitor.record_stroke(seq=6701, at=1015.0)

    status = monitor.check(now=1020.0)
    # {"state": "healthy", "gap_s": 5.0, "seq": 6701, ...}

    if status["state"] == "dead":
        # trigger restart
        ...

Thresholds
----------
- **healthy_s** (default 45 s): three cadence cycles.  A healthy writer
  may skip one or two strokes due to transient load; three consecutive
  misses is unusual but not yet alarming.
- **degraded_s** (default 120 s): eight cadence cycles.  Beyond this,
  the writer is almost certainly stuck — the process may still exist
  but is hung (deadlock, I/O wait, OOM thrashing).
- **dead** (anything beyond degraded_s): time to restart.

Design decisions
----------------
- **Stroke-driven, not timer-driven.**  The monitor does not run its
  own clock.  It is updated passively when the batch committer or
  caretaker calls ``record_stroke()``.  This avoids spawning another
  long-lived thread in a system that already has two.
- **Monotonic sequence check.**  ``record_stroke()`` rejects strokes
  with a sequence number lower than the current high-water mark.  This
  protects against out-of-order delivery from concurrent writers.
- **Bounded history.**  The monitor retains the last 100 stroke
  timestamps for gap analysis.  This is enough to detect patterns
  (e.g., gradually increasing gaps before a crash) without unbounded
  memory growth.
- **No side effects.**  The monitor never restarts processes or sends
  alerts itself.  It returns a status dict; the caller decides what
  to do.  This keeps it composable with ``restart_convergence`` and
  ``git_lock_monitor``.

Relationship to other modules
-----------------------------
- ``restart_convergence`` tracks recovery *after* a restart.
- ``writer_heartbeat`` detects the *need* for a restart.
- ``git_lock_monitor`` handles a common *cause* of writer silence.

Together they form a detect → clean → restart → verify pipeline.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Deque, Dict, Optional


# Default thresholds in seconds.
DEFAULT_HEALTHY_S = 45.0
DEFAULT_DEGRADED_S = 120.0
MAX_HISTORY = 100


class HeartbeatMonitor:
    """Track writer heartbeat and classify liveness state."""

    def __init__(
        self,
        healthy_s: float = DEFAULT_HEALTHY_S,
        degraded_s: float = DEFAULT_DEGRADED_S,
        now: Optional[float] = None,
    ) -> None:
        if healthy_s >= degraded_s:
            raise ValueError(
                f"healthy_s ({healthy_s}) must be less than degraded_s ({degraded_s})"
            )
        self.healthy_s = healthy_s
        self.degraded_s = degraded_s
        self._last_seq: int = -1
        self._last_at: Optional[float] = None
        self._stroke_count: int = 0
        self._history: Deque[float] = deque(maxlen=MAX_HISTORY)
        self._created_at: float = now if now is not None else time.time()

    # -- recording ---------------------------------------------------------

    def record_stroke(
        self,
        seq: int,
        at: Optional[float] = None,
        now: Optional[float] = None,
    ) -> bool:
        """Record a stroke.  Returns True if accepted, False if rejected.

        Rejection reasons:
        - ``seq`` is not greater than the current high-water mark.
        - ``at`` is in the future relative to ``now``.
        """
        if at is None:
            at = time.time()
        if now is None:
            now = time.time()

        # Reject out-of-order or duplicate sequence numbers.
        if seq <= self._last_seq:
            return False

        # Reject future timestamps (with 1s tolerance for clock skew).
        if at > now + 1.0:
            return False

        self._last_seq = seq
        self._last_at = at
        self._stroke_count += 1
        self._history.append(at)
        return True

    # -- checking ----------------------------------------------------------

    def check(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Return the current heartbeat status."""
        if now is None:
            now = time.time()

        if self._last_at is None:
            return {
                "state": "dead",
                "gap_s": None,
                "seq": None,
                "stroke_count": 0,
                "detail": "no strokes recorded",
            }

        gap_s = now - self._last_at

        if gap_s <= self.healthy_s:
            state = "healthy"
        elif gap_s <= self.degraded_s:
            state = "degraded"
        else:
            state = "dead"

        return {
            "state": state,
            "gap_s": round(gap_s, 2),
            "seq": self._last_seq,
            "stroke_count": self._stroke_count,
            "healthy_s": self.healthy_s,
            "degraded_s": self.degraded_s,
        }

    @property
    def is_healthy(self) -> bool:
        """Quick check: is the writer currently healthy?"""
        return self.check()["state"] == "healthy"

    @property
    def is_dead(self) -> bool:
        """Quick check: is the writer currently dead?"""
        return self.check()["state"] == "dead"

    # -- gap analysis ------------------------------------------------------

    def gap_stats(self) -> Dict[str, Any]:
        """Return statistics on recent inter-stroke gaps.

        Useful for detecting gradual degradation: if the mean gap is
        creeping upward, the writer may be under load even though it
        hasn't fully stopped.
        """
        if len(self._history) < 2:
            return {
                "count": len(self._history),
                "mean_gap_s": None,
                "max_gap_s": None,
                "min_gap_s": None,
            }

        timestamps = sorted(self._history)
        gaps = [
            timestamps[i + 1] - timestamps[i]
            for i in range(len(timestamps) - 1)
        ]

        return {
            "count": len(self._history),
            "mean_gap_s": round(sum(gaps) / len(gaps), 2),
            "max_gap_s": round(max(gaps), 2),
            "min_gap_s": round(min(gaps), 2),
        }

    # -- reset -------------------------------------------------------------

    def reset(self) -> None:
        """Clear all state.  Useful after a confirmed restart."""
        self._last_seq = -1
        self._last_at = None
        self._stroke_count = 0
        self._history.clear()
