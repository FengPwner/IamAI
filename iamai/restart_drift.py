"""restart_drift — track container restart frequency and detect acceleration.

The IamAI system runs inside recyclable containers.  When a container is
reclaimed the writer and batch committer die; the caretaker restarts them.
Individual restarts are normal — a *pattern* of accelerating restarts is not.

This module ingests restart timestamps and derives:

  - **intervals**: seconds between consecutive restarts
  - **mean interval**: average gap (seconds)
  - **min interval**: shortest gap — the worst-case recycling cadence
  - **drift direction**: ``accelerating`` / ``stable`` / ``decelerating``
  - **instability score**: 0.0–1.0 composite of frequency and trend
  - **projected next**: estimated time of next restart (if trend holds)

All operations are pure Python (no subprocess, no disk I/O).

usage::

    from iamai.restart_drift import RestartDrift

    drift = RestartDrift()
    drift.record("2026-10-19T06:00:00+08:00")
    drift.record("2026-10-19T12:00:00+08:00")
    drift.record("2026-10-19T16:00:00+08:00")
    drift.record("2026-10-19T19:00:00+08:00")

    drift.mean_interval()     # seconds
    drift.drift_direction()   # 'accelerating' (gaps shrinking)
    drift.instability_score() # 0.0-1.0
    drift.report()            # human-readable summary
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


# Thresholds
HEALTHY_INTERVAL_S = 21600       # 6 hours between restarts → fine
STRAINED_INTERVAL_S = 7200       # 2 hours → concerning
CRITICAL_INTERVAL_S = 3600       # 1 hour → unsustainable

# Drift detection: percentage change in interval to declare acceleration
DRIFT_THRESHOLD = 0.20           # 20% shrinkage → "accelerating"


@dataclass
class RestartEvent:
    """A single container restart timestamp."""
    at: str                      # ISO 8601 timestamp
    visit: Optional[int] = None  # associated caretaker visit (if any)
    cause: str = "unknown"       # known / unknown / container_reclaim / manual

    def ts(self) -> datetime:
        """Parse the ISO timestamp to a datetime."""
        s = self.at
        # Handle +08:00 style offsets for fromisoformat
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            # Fallback: strip trailing Z and assume UTC
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s)


class RestartDrift:
    """Track restart timestamps and detect frequency drift."""

    def __init__(self) -> None:
        self._events: List[RestartEvent] = []

    # ── recording ──────────────────────────────────────────────

    def record(self, at: str, visit: Optional[int] = None,
               cause: str = "unknown") -> RestartEvent:
        """Record a restart event."""
        evt = RestartEvent(at=at, visit=visit, cause=cause)
        self._events.append(evt)
        return evt

    def record_many(self, timestamps: List[str]) -> int:
        """Record multiple timestamps at once. Returns count added."""
        for ts in timestamps:
            self.record(ts)
        return len(timestamps)

    def count(self) -> int:
        return len(self._events)

    def events(self) -> List[RestartEvent]:
        """Return a copy of the events list."""
        return list(self._events)

    def latest(self) -> Optional[RestartEvent]:
        return self._events[-1] if self._events else None

    # ── intervals ──────────────────────────────────────────────

    def intervals(self) -> List[float]:
        """Seconds between consecutive restarts."""
        if len(self._events) < 2:
            return []
        result = []
        for i in range(1, len(self._events)):
            delta = (self._events[i].ts() - self._events[i - 1].ts()).total_seconds()
            result.append(delta)
        return result

    def mean_interval(self) -> Optional[float]:
        """Average seconds between restarts."""
        ivs = self.intervals()
        if not ivs:
            return None
        return sum(ivs) / len(ivs)

    def min_interval(self) -> Optional[float]:
        """Shortest gap between consecutive restarts."""
        ivs = self.intervals()
        return min(ivs) if ivs else None

    def max_interval(self) -> Optional[float]:
        """Longest gap between consecutive restarts."""
        ivs = self.intervals()
        return max(ivs) if ivs else None

    # ── drift detection ────────────────────────────────────────

    def drift_direction(self) -> str:
        """Are restarts getting more frequent, less frequent, or stable?

        Compares the mean of the first half of intervals against the
        second half.  If the second half is >20% shorter → accelerating.
        If >20% longer → decelerating.  Otherwise → stable.
        """
        ivs = self.intervals()
        if len(ivs) < 2:
            return "stable"

        mid = len(ivs) // 2
        first_half = ivs[:mid] if mid > 0 else ivs[:1]
        second_half = ivs[mid:] if mid > 0 else ivs[1:]

        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)

        if avg_first == 0:
            return "stable"

        change = (avg_second - avg_first) / avg_first

        if change < -DRIFT_THRESHOLD:
            return "accelerating"
        elif change > DRIFT_THRESHOLD:
            return "decelerating"
        return "stable"

    # ── instability score ──────────────────────────────────────

    def instability_score(self) -> float:
        """Composite score 0.0 (rock solid) to 1.0 (constant churn).

        Components:
          - frequency: how short is the mean interval vs HEALTHY?
          - trend:     penalty if accelerating
          - variance:  penalty for erratic (unpredictable) intervals
        """
        if len(self._events) < 2:
            return 0.0

        ivs = self.intervals()
        mean_iv = sum(ivs) / len(ivs)

        # Frequency component (0.0–0.4)
        if mean_iv >= HEALTHY_INTERVAL_S:
            freq_score = 0.0
        elif mean_iv >= STRAINED_INTERVAL_S:
            # Linear scale: 6h→0, 2h→0.4
            freq_score = 0.4 * (1 - (mean_iv - STRAINED_INTERVAL_S)
                                / (HEALTHY_INTERVAL_S - STRAINED_INTERVAL_S))
        elif mean_iv >= CRITICAL_INTERVAL_S:
            freq_score = 0.4 + 0.3 * (1 - (mean_iv - CRITICAL_INTERVAL_S)
                                       / (STRAINED_INTERVAL_S - CRITICAL_INTERVAL_S))
        else:
            freq_score = 0.7 + min(0.3, 0.3 * (CRITICAL_INTERVAL_S - mean_iv)
                                   / CRITICAL_INTERVAL_S)

        # Trend component (0.0–0.3)
        direction = self.drift_direction()
        if direction == "accelerating":
            trend_score = 0.3
        elif direction == "decelerating":
            trend_score = 0.0
        else:
            trend_score = 0.1  # stable gets a small baseline

        # Variance component (0.0–0.3)
        if len(ivs) >= 2:
            variance = sum((x - mean_iv) ** 2 for x in ivs) / len(ivs)
            cv = (variance ** 0.5) / max(mean_iv, 1)  # coefficient of variation
            var_score = min(0.3, 0.3 * cv)
        else:
            var_score = 0.0

        return round(min(1.0, freq_score + trend_score + var_score), 3)

    # ── projected next restart ─────────────────────────────────

    def projected_next_interval(self) -> Optional[float]:
        """Estimate seconds until next restart based on recent trend.

        Uses the last 3 intervals (or all if fewer) and extrapolates.
        Returns None if fewer than 2 events.
        """
        ivs = self.intervals()
        if not ivs:
            return None
        recent = ivs[-3:] if len(ivs) >= 3 else ivs
        return sum(recent) / len(recent)

    # ── regime label ───────────────────────────────────────────

    def regime(self) -> str:
        """Classify overall restart health."""
        score = self.instability_score()
        if score >= 0.7:
            return "critical"
        elif score >= 0.4:
            return "strained"
        return "healthy"

    # ── report ─────────────────────────────────────────────────

    def report(self) -> str:
        """Human-readable summary."""
        n = self.count()
        if n == 0:
            return "no restart events recorded"

        lines = [f"restart drift report — {n} event(s)"]

        if n < 2:
            lines.append("  only one event; cannot compute intervals")
            return "\n".join(lines)

        ivs = self.intervals()
        mean_iv = self.mean_interval()
        direction = self.drift_direction()
        score = self.instability_score()
        regime = self.regime()

        # Format mean interval as hours
        mean_h = mean_iv / 3600
        lines.append(f"  mean interval:    {mean_h:.1f}h")
        lines.append(f"  min interval:     {self.min_interval() / 3600:.1f}h")
        lines.append(f"  max interval:     {self.max_interval() / 3600:.1f}h")
        lines.append(f"  drift direction:  {direction}")
        lines.append(f"  instability:      {score:.3f} ({regime})")

        projected = self.projected_next_interval()
        if projected:
            lines.append(f"  projected next:   ~{projected / 3600:.1f}h")

        if direction == "accelerating":
            lines.append("  ⚠ restarts are becoming more frequent")

        return "\n".join(lines)
