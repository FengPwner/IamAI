#!/usr/bin/env python3
"""restart_convergence — measure how quickly the system recovers after restart.

When a writer or batch committer restarts, the system is not instantly
healthy.  There is a *convergence period* during which:

- The writer produces its first stroke (warmup latency).
- The batch committer completes its first push (push latency).
- Uncommitted backlog drains to zero (backlog drain time).

This module tracks those milestones and produces a structured
convergence report.  A restart that converges quickly is healthy;
one that takes too long (or never converges) signals a deeper
problem — perhaps the same failure that caused the restart is
recurring.

Public API::

    from iamai.restart_convergence import ConvergenceTracker

    tracker = ConvergenceTracker()
    tracker.mark_restart()
    tracker.mark_first_stroke()
    tracker.mark_first_push()
    tracker.mark_backlog_clear()

    report = tracker.report()
    # {"converged": True, "total_s": 145.3, "stroke_s": 12.1, ...}

Thresholds
----------
- **stroke_s** (first stroke after restart): healthy < 60 s.
- **push_s** (first push after restart): healthy < 660 s (11 min).
- **backlog_s** (backlog drains to zero): healthy < 300 s (5 min).
- **total_s** (restart → all milestones): healthy < 720 s (12 min).

These defaults come from the IamAI cadence: writer emits a stroke
every 15 s, batch commits every 600 s.  A healthy restart should
see the first stroke within one cadence cycle and the first push
within two.

Design decisions
----------------
- **Stateless tracker.**  The tracker holds state in memory only.
  Persistence (if needed) is the caller's responsibility — typically
  the caretaker or batch committer writes the report to a JSON file.
- **Idempotent marks.**  Calling ``mark_first_stroke()`` twice is
  safe — only the first call sets the timestamp.
- **Graceful partial convergence.**  If the push never happens,
  ``report()`` still returns a dict with *None* for missing values
  and ``converged: False``.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional


# Default thresholds in seconds.
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "stroke_s": 60.0,
    "push_s": 660.0,
    "backlog_s": 300.0,
    "total_s": 720.0,
}


class ConvergenceTracker:
    """Track milestones from restart to full health."""

    def __init__(
        self,
        thresholds: Optional[Dict[str, float]] = None,
        now: Optional[float] = None,
    ) -> None:
        self._thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self._now_fn = (lambda: now) if now is not None else time.time
        self._restart_t: Optional[float] = None
        self._stroke_t: Optional[float] = None
        self._push_t: Optional[float] = None
        self._backlog_t: Optional[float] = None

    # -- marking milestones ------------------------------------------------

    def mark_restart(self, t: Optional[float] = None) -> float:
        """Record the restart time.  Returns the recorded timestamp."""
        self._restart_t = t if t is not None else self._now_fn()
        # Reset downstream milestones (restart invalidates old marks).
        self._stroke_t = None
        self._push_t = None
        self._backlog_t = None
        return self._restart_t

    def mark_first_stroke(self, t: Optional[float] = None) -> Optional[float]:
        """Record the first stroke after restart.  Idempotent."""
        if self._stroke_t is not None:
            return self._stroke_t
        self._stroke_t = t if t is not None else self._now_fn()
        return self._stroke_t

    def mark_first_push(self, t: Optional[float] = None) -> Optional[float]:
        """Record the first successful push after restart.  Idempotent."""
        if self._push_t is not None:
            return self._push_t
        self._push_t = t if t is not None else self._now_fn()
        return self._push_t

    def mark_backlog_clear(self, t: Optional[float] = None) -> Optional[float]:
        """Record when uncommitted backlog reaches zero.  Idempotent."""
        if self._backlog_t is not None:
            return self._backlog_t
        self._backlog_t = t if t is not None else self._now_fn()
        return self._backlog_t

    # -- queries -----------------------------------------------------------

    @property
    def restarted(self) -> bool:
        return self._restart_t is not None

    @property
    def converged(self) -> bool:
        """True when all three milestones have been reached."""
        return all(
            t is not None
            for t in (self._stroke_t, self._push_t, self._backlog_t)
        )

    def elapsed_since_restart(self, now: Optional[float] = None) -> Optional[float]:
        """Seconds since restart, or None if not restarted."""
        if self._restart_t is None:
            return None
        _now = now if now is not None else self._now_fn()
        return _now - self._restart_t

    def _latency(self, mark: Optional[float]) -> Optional[float]:
        """Seconds from restart to *mark*, or None."""
        if self._restart_t is None or mark is None:
            return None
        return mark - self._restart_t

    def report(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Produce a convergence report.

        Returns a dict with:
        - ``converged`` (bool): all milestones reached.
        - ``restarted`` (bool): restart was recorded.
        - ``elapsed_s`` (float | None): seconds since restart.
        - ``stroke_s`` (float | None): restart → first stroke.
        - ``push_s`` (float | None): restart → first push.
        - ``backlog_s`` (float | None): restart → backlog clear.
        - ``total_s`` (float | None): restart → last milestone.
        - ``healthy`` (bool | None): all latencies within thresholds.
          None if not converged yet.
        - ``detail`` (str): human-readable summary.
        """
        elapsed = self.elapsed_since_restart(now=now)
        stroke_lat = self._latency(self._stroke_t)
        push_lat = self._latency(self._push_t)
        backlog_lat = self._latency(self._backlog_t)

        latencies = [v for v in (stroke_lat, push_lat, backlog_lat) if v is not None]
        total = max(latencies) if latencies else None

        if not self.restarted:
            return {
                "converged": False,
                "restarted": False,
                "elapsed_s": None,
                "stroke_s": None,
                "push_s": None,
                "backlog_s": None,
                "total_s": None,
                "healthy": None,
                "detail": "no restart recorded",
            }

        if not self.converged:
            missing = []
            if self._stroke_t is None:
                missing.append("first_stroke")
            if self._push_t is None:
                missing.append("first_push")
            if self._backlog_t is None:
                missing.append("backlog_clear")
            return {
                "converged": False,
                "restarted": True,
                "elapsed_s": round(elapsed, 1) if elapsed is not None else None,
                "stroke_s": round(stroke_lat, 1) if stroke_lat is not None else None,
                "push_s": round(push_lat, 1) if push_lat is not None else None,
                "backlog_s": round(backlog_lat, 1) if backlog_lat is not None else None,
                "total_s": round(total, 1) if total is not None else None,
                "healthy": None,
                "detail": f"waiting for: {', '.join(missing)} ({elapsed:.0f}s elapsed)",
            }

        # All milestones reached — check health.
        checks = {
            "stroke_s": stroke_lat <= self._thresholds["stroke_s"],
            "push_s": push_lat <= self._thresholds["push_s"],
            "backlog_s": backlog_lat <= self._thresholds["backlog_s"],
            "total_s": total <= self._thresholds["total_s"],
        }
        healthy = all(checks.values())

        slow = [k for k, v in checks.items() if not v]
        if healthy:
            detail = (
                f"converged in {total:.0f}s "
                f"(stroke {stroke_lat:.0f}s, push {push_lat:.0f}s, "
                f"backlog {backlog_lat:.0f}s) — all within thresholds"
            )
        else:
            detail = (
                f"converged in {total:.0f}s but slow on: {', '.join(slow)} "
                f"(stroke {stroke_lat:.0f}s, push {push_lat:.0f}s, "
                f"backlog {backlog_lat:.0f}s)"
            )

        return {
            "converged": True,
            "restarted": True,
            "elapsed_s": round(elapsed, 1) if elapsed is not None else None,
            "stroke_s": round(stroke_lat, 1),
            "push_s": round(push_lat, 1),
            "backlog_s": round(backlog_lat, 1),
            "total_s": round(total, 1),
            "healthy": healthy,
            "detail": detail,
        }
