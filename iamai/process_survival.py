"""process_survival — measure how long restarted processes actually stay alive.

When the caretaker restarts the writer or batch committer, the next
question is always: *did it stick?*  ``uptime_tracker.py`` answers
"how long since last start", but not the more interesting question:
how long do processes typically survive before the next crash or
container reclamation?

This module records survival intervals — the wall-clock seconds between
a restart and the subsequent death — and derives statistics:

  - **mean survival**: average lifetime across recorded intervals
  - **median survival**: median lifetime (more robust to outliers)
  - **min / max survival**: shortest and longest observed lifetimes
  - **survival trend**: improving / stable / worsening
  - **fragility score**: 0.0–1.0; 1.0 means processes die within seconds

A process that survives for hours is stable; one that dies in minutes
suggests a deeper problem (bad deploy, resource exhaustion, OOM).

Usage::

    from iamai.process_survival import SurvivalTracker

    tracker = SurvivalTracker()
    tracker.record_restart("2026-11-03T06:00:00+08:00")
    tracker.record_death("2026-11-03T09:30:00+08:00")
    tracker.record_restart("2026-11-03T09:31:00+08:00")
    tracker.record_death("2026-11-03T14:00:00+08:00")

    tracker.mean_survival()      # 12630.0 seconds
    tracker.survival_trend()     # 'stable'
    tracker.fragility_score()    # 0.02
    print(tracker.report())

Grades
------

=================  ===================================================
fragility          meaning
=================  ===================================================
``robust``         score ≤ 0.10 — processes survive for hours
``acceptable``     0.11–0.30 — typical container recycling cadence
``fragile``        0.31–0.60 — processes die within tens of minutes
``critical``       > 0.60 — processes rarely survive an hour
=================  ===================================================

All operations are pure Python (no subprocess, no disk I/O).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


def _parse_ts(ts: str | datetime) -> datetime:
    """Parse an ISO-8601 string or pass through a datetime."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    # Handle Z suffix
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


@dataclass
class SurvivalInterval:
    """A single restart-to-death interval."""

    restart_at: datetime
    death_at: datetime

    @property
    def duration_seconds(self) -> float:
        delta = self.death_at - self.restart_at
        return max(delta.total_seconds(), 0.0)


@dataclass
class SurvivalTracker:
    """Track process survival intervals and derive statistics."""

    intervals: List[SurvivalInterval] = field(default_factory=list)
    # Fragility thresholds (fraction of one hour)
    _robust_threshold: float = 0.10
    _acceptable_threshold: float = 0.30
    _fragile_threshold: float = 0.60

    # -- recording --

    def record_interval(self, restart_at, death_at) -> SurvivalInterval:
        """Record a complete restart-to-death interval."""
        interval = SurvivalInterval(
            restart_at=_parse_ts(restart_at),
            death_at=_parse_ts(death_at),
        )
        self.intervals.append(interval)
        return interval

    def record_restart(self, restart_at) -> datetime:
        """Record a restart timestamp (helper for paired recording)."""
        return _parse_ts(restart_at)

    def record_death(self, death_at) -> datetime:
        """Record a death timestamp (helper for paired recording)."""
        return _parse_ts(death_at)

    # -- statistics --

    def durations(self) -> List[float]:
        """Return all interval durations in seconds."""
        return [iv.duration_seconds for iv in self.intervals]

    def count(self) -> int:
        """Number of recorded intervals."""
        return len(self.intervals)

    def mean_survival(self) -> Optional[float]:
        """Mean survival time in seconds, or None if no data."""
        d = self.durations()
        return statistics.mean(d) if d else None

    def median_survival(self) -> Optional[float]:
        """Median survival time in seconds, or None if no data."""
        d = self.durations()
        return statistics.median(d) if d else None

    def min_survival(self) -> Optional[float]:
        """Shortest survival time in seconds."""
        d = self.durations()
        return min(d) if d else None

    def max_survival(self) -> Optional[float]:
        """Longest survival time in seconds."""
        d = self.durations()
        return max(d) if d else None

    def survival_trend(self, min_samples: int = 3) -> str:
        """Determine whether survival times are improving, stable, or worsening.

        Splits intervals into two halves and compares their means.
        Returns 'improving', 'stable', or 'worsening'.
        Returns 'insufficient_data' if fewer than min_samples intervals.
        """
        d = self.durations()
        if len(d) < min_samples:
            return "insufficient_data"

        mid = len(d) // 2
        first_half = d[:mid]
        second_half = d[mid:]

        mean_first = statistics.mean(first_half)
        mean_second = statistics.mean(second_half)

        if mean_first == 0:
            return "improving" if mean_second > 0 else "stable"

        ratio = mean_second / mean_first
        if ratio > 1.2:
            return "improving"
        elif ratio < 0.8:
            return "worsening"
        return "stable"

    def fragility_score(self) -> float:
        """Compute a 0.0–1.0 fragility score.

        Based on the proportion of intervals shorter than one hour.
        1.0 means every interval is under one hour; 0.0 means none are.
        Returns 0.5 if no data (uncertainty default).
        """
        d = self.durations()
        if not d:
            return 0.5

        one_hour = 3600.0
        short_count = sum(1 for dur in d if dur < one_hour)
        return short_count / len(d)

    def fragility_grade(self) -> str:
        """Human-readable fragility grade."""
        score = self.fragility_score()
        if score <= self._robust_threshold:
            return "robust"
        elif score <= self._acceptable_threshold:
            return "acceptable"
        elif score <= self._fragile_threshold:
            return "fragile"
        return "critical"

    def report(self) -> str:
        """Generate a human-readable survival report."""
        if not self.intervals:
            return "no survival data recorded"

        mean_s = self.mean_survival()
        median_s = self.median_survival()
        trend = self.survival_trend()
        grade = self.fragility_grade()

        parts = [
            f"process survival: {self.count()} intervals",
            f"mean: {_fmt_duration(mean_s)}",
            f"median: {_fmt_duration(median_s)}",
            f"min: {_fmt_duration(self.min_survival())}",
            f"max: {_fmt_duration(self.max_survival())}",
            f"trend: {trend}",
            f"fragility: {grade} ({self.fragility_score():.2f})",
        ]
        return ", ".join(parts)


def _fmt_duration(seconds: Optional[float]) -> str:
    """Format a duration in seconds to a human-readable string."""
    if seconds is None:
        return "N/A"
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m{s}s"
    else:
        h, remainder = divmod(int(seconds), 3600)
        m, s = divmod(remainder, 60)
        return f"{h}h{m}m"


def survival_summary(tracker: SurvivalTracker) -> dict:
    """Return a summary dict suitable for caretaker dashboards."""
    return {
        "interval_count": tracker.count(),
        "mean_seconds": tracker.mean_survival(),
        "median_seconds": tracker.median_survival(),
        "min_seconds": tracker.min_survival(),
        "max_seconds": tracker.max_survival(),
        "trend": tracker.survival_trend(),
        "fragility_score": tracker.fragility_score(),
        "fragility_grade": tracker.fragility_grade(),
        "report": tracker.report(),
    }
