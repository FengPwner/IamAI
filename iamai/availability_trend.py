"""availability_trend — track writer availability across caretaker visits.

the stroke_loss_tracker gives a point-in-time availability reading.
this module aggregates those readings into a time series and derives:

  - rolling average availability over the last N visits
  - trend direction: improving / stable / degrading
  - regime classification: healthy (>=85%) / strained (60-85%) / critical (<60%)
  - regime change detection: did the latest reading cross a boundary?

all operations are pure Python (no subprocess, no disk I/O).
callers (caretaker visits, dashboards) pass in readings and get
back structured reports.

usage::

    from iamai.availability_trend import AvailabilityTrend, Reading

    trend = AvailabilityTrend()
    trend.record(Reading(at="2026-10-19T12:00:00+08:00", visit=231, availability_pct=72.3))
    trend.record(Reading(at="2026-10-19T15:00:00+08:00", visit=232, availability_pct=65.1))
    trend.record(Reading(at="2026-10-19T19:00:00+08:00", visit=233, availability_pct=60.5))
    trend.rolling_avg()           # 65.97
    trend.direction()             # 'degrading'
    trend.regime()                # 'strained'
    trend.regime_changed()        # False (still strained)
    trend.report()                # human-readable summary
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Regime boundaries
HEALTHY_THRESHOLD = 85.0    # >= 85% → healthy
STRAINED_THRESHOLD = 60.0   # 60-85% → strained, < 60% → critical

# Direction thresholds (percentage points over the window)
IMPROVING_THRESHOLD = 2.0   # rolling avg rising by >2pp → improving
DEGRADING_THRESHOLD = -2.0  # rolling avg falling by >2pp → degrading


@dataclass
class Reading:
    """A single availability reading from a caretaker visit."""
    at: str                     # ISO 8601 timestamp
    visit: int                  # caretaker visit number
    availability_pct: float     # 0.0 – 100.0
    stall_count: int = 0        # number of stalls detected
    total_stall_seconds: int = 0
    estimated_loss: int = 0     # estimated lost strokes
    observed_strokes: int = 0

    def regime(self) -> str:
        """Classify this single reading."""
        if self.availability_pct >= HEALTHY_THRESHOLD:
            return "healthy"
        elif self.availability_pct >= STRAINED_THRESHOLD:
            return "strained"
        else:
            return "critical"


class AvailabilityTrend:
    """Aggregate availability readings across visits."""

    def __init__(self, window: int = 10):
        self._readings: list[Reading] = []
        self._window = window

    @property
    def readings(self) -> list[Reading]:
        return list(self._readings)

    def record(self, reading: Reading) -> None:
        """Append a reading. Readings are kept in insertion order."""
        self._readings.append(reading)

    def record_many(self, readings: list[Reading]) -> None:
        """Append multiple readings."""
        self._readings.extend(readings)

    def count(self) -> int:
        return len(self._readings)

    def latest(self) -> Optional[Reading]:
        """Return the most recent reading, or None."""
        return self._readings[-1] if self._readings else None

    def rolling_avg(self, n: Optional[int] = None) -> float:
        """Mean availability over the last n readings (default: window).

        Returns 0.0 if no readings exist.
        """
        if not self._readings:
            return 0.0
        n = min(n or self._window, len(self._readings))
        tail = self._readings[-n:]
        return sum(r.availability_pct for r in tail) / len(tail)

    def direction(self, n: Optional[int] = None) -> str:
        """Trend direction over the last n readings.

        Compares the rolling average of the most recent n/2 readings
        against the n/2 before that. Returns one of:
        'improving', 'stable', 'degrading'.

        Returns 'stable' if fewer than 2 readings exist.
        """
        if len(self._readings) < 2:
            return "stable"
        n = min(n or self._window, len(self._readings))
        half = max(1, n // 2)
        recent = self._readings[-half:]
        earlier_end = len(self._readings) - half
        earlier_start = max(0, earlier_end - half)
        earlier = self._readings[earlier_start:earlier_end]
        if not earlier:
            return "stable"

        recent_avg = sum(r.availability_pct for r in recent) / len(recent)
        earlier_avg = sum(r.availability_pct for r in earlier) / len(earlier)
        delta = recent_avg - earlier_avg

        if delta > IMPROVING_THRESHOLD:
            return "improving"
        elif delta < DEGRADING_THRESHOLD:
            return "degrading"
        else:
            return "stable"

    def regime(self) -> str:
        """Current regime based on the latest reading.

        Returns 'unknown' if no readings exist.
        """
        latest = self.latest()
        return latest.regime() if latest else "unknown"

    def regime_changed(self) -> bool:
        """Did the latest reading cross a regime boundary?

        Returns False if fewer than 2 readings exist.
        """
        if len(self._readings) < 2:
            return False
        return self._readings[-1].regime() != self._readings[-2].regime()

    def min_availability(self, n: Optional[int] = None) -> float:
        """Lowest availability in the last n readings."""
        if not self._readings:
            return 0.0
        n = min(n or self._window, len(self._readings))
        return min(r.availability_pct for r in self._readings[-n:])

    def max_availability(self, n: Optional[int] = None) -> float:
        """Highest availability in the last n readings."""
        if not self._readings:
            return 0.0
        n = min(n or self._window, len(self._readings))
        return max(r.availability_pct for r in self._readings[-n:])

    def worst_streak(self, threshold: float = STRAINED_THRESHOLD) -> int:
        """Longest consecutive run of readings below threshold."""
        streak = 0
        worst = 0
        for r in self._readings:
            if r.availability_pct < threshold:
                streak += 1
                worst = max(worst, streak)
            else:
                streak = 0
        return worst

    def total_loss(self, n: Optional[int] = None) -> int:
        """Sum of estimated stroke losses across the last n readings."""
        if not self._readings:
            return 0
        n = min(n or self._window, len(self._readings))
        return sum(r.estimated_loss for r in self._readings[-n:])

    def report(self, n: Optional[int] = None) -> str:
        """Human-readable trend report."""
        if not self._readings:
            return "availability trend: no readings recorded."

        n = min(n or self._window, len(self._readings))
        latest = self._readings[-1]
        avg = self.rolling_avg(n)
        d = self.direction(n)
        regime = self.regime()
        changed = self.regime_changed()
        lo = self.min_availability(n)
        hi = self.max_availability(n)
        loss = self.total_loss(n)

        lines = [
            f"availability trend (last {n} visits)",
            f"  latest:    {latest.availability_pct:.1f}% (visit {latest.visit})",
            f"  rolling avg: {avg:.1f}%",
            f"  direction: {d}",
            f"  regime:    {regime}" + (" (CHANGED)" if changed else ""),
            f"  range:     {lo:.1f}% – {hi:.1f}%",
            f"  total loss: {loss} strokes",
            f"  worst streak below {STRAINED_THRESHOLD}%: {self.worst_streak(STRAINED_THRESHOLD)} consecutive",
        ]

        if changed:
            prev = self._readings[-2]
            lines.append(f"  regime shift: {prev.regime()} → {regime}")

        return "\n".join(lines)
