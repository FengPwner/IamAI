"""process_resurrection — measure how quickly writing resumes after restart.

After a stall, the caretaker (or pre-execution harness) restarts both
the writer and the batch committer.  This module measures the gap
between restart and the *first new stroke*, which is the real signal
that the system is healthy again.

A short resurrection gap (< 2 × writer cadence) means the restart
worked cleanly.  A long gap suggests the writer started but is stuck
in the same degenerate loop or sandbox issue that killed it.

Usage::

    from iamai.process_resurrection import (
        measure_resurrections,
        ResurrectionReport,
    )

    # (restart_time, first_stroke_after_restart) pairs
    events = [
        ("2026-10-19T04:00:30+08:00", "2026-10-19T04:03:45+08:00"),
        ("2026-10-18T03:00:15+08:00", "2026-10-18T03:12:00+08:00"),
    ]

    report = measure_resurrections(events, cadence_seconds=900)
    print(report.mean_gap_seconds)      # average wait
    print(report.healthy_ratio)         # fraction within 2x cadence
    print(report.as_dict())

Design choices:
  - Pure-Python, no subprocess, no git dependency.
  - Accepts ISO-8601 strings, datetime objects, or epoch floats.
  - Frozen dataclass result.
  - "Healthy" threshold defaults to 2x the writer cadence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Sequence, Tuple, Union

Timestamp = Union[str, datetime, float, int]

DEFAULT_CADENCE_SECONDS = 900  # 15 minutes
DEFAULT_HEALTHY_MULTIPLIER = 2.0


def _to_datetime(ts: Timestamp) -> datetime:
    """Normalize a timestamp to a timezone-aware datetime."""
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str):
        s = ts.strip()
        # Handle basic ISO-8601 with or without timezone.
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            pass
        # Fallback: strip trailing Z and treat as UTC.
        if s.endswith("Z"):
            return datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    raise TypeError(f"Unsupported timestamp type: {type(ts)}")


def _gap_seconds(restart: Timestamp, first_stroke: Timestamp) -> float:
    """Seconds between restart and first stroke.  Clamped to >= 0."""
    dt_r = _to_datetime(restart)
    dt_s = _to_datetime(first_stroke)
    return max(0.0, (dt_s - dt_r).total_seconds())


@dataclass(frozen=True)
class ResurrectionReport:
    """Summary of resurrection gap measurements."""

    gaps: Tuple[float, ...]
    cadence_seconds: int
    healthy_multiplier: float

    @property
    def count(self) -> int:
        return len(self.gaps)

    @property
    def mean_gap_seconds(self) -> float:
        if not self.gaps:
            return 0.0
        return sum(self.gaps) / len(self.gaps)

    @property
    def max_gap_seconds(self) -> float:
        return max(self.gaps) if self.gaps else 0.0

    @property
    def min_gap_seconds(self) -> float:
        return min(self.gaps) if self.gaps else 0.0

    @property
    def healthy_threshold_seconds(self) -> float:
        return self.cadence_seconds * self.healthy_multiplier

    @property
    def healthy_count(self) -> int:
        return sum(1 for g in self.gaps if g <= self.healthy_threshold_seconds)

    @property
    def healthy_ratio(self) -> float:
        """Fraction of resurrections that resumed within threshold."""
        if not self.gaps:
            return 1.0  # vacuously healthy
        return self.healthy_count / len(self.gaps)

    @property
    def is_healthy_pattern(self) -> bool:
        """True if >= 80% of resurrections are healthy."""
        return self.healthy_ratio >= 0.80

    def as_dict(self) -> dict:
        return {
            "count": self.count,
            "mean_gap_seconds": round(self.mean_gap_seconds, 1),
            "max_gap_seconds": round(self.max_gap_seconds, 1),
            "min_gap_seconds": round(self.min_gap_seconds, 1),
            "healthy_threshold_seconds": self.healthy_threshold_seconds,
            "healthy_count": self.healthy_count,
            "healthy_ratio": round(self.healthy_ratio, 3),
            "is_healthy_pattern": self.is_healthy_pattern,
            "cadence_seconds": self.cadence_seconds,
        }


def measure_resurrections(
    events: Sequence[Tuple[Timestamp, Timestamp]],
    cadence_seconds: int = DEFAULT_CADENCE_SECONDS,
    healthy_multiplier: float = DEFAULT_HEALTHY_MULTIPLIER,
) -> ResurrectionReport:
    """Measure resurrection gaps from (restart_time, first_stroke) pairs.

    Parameters
    ----------
    events : sequence of (restart, first_stroke_after_restart)
        Each element is a 2-tuple of timestamps.
    cadence_seconds : int
        Expected writer cadence (default 900 = 15 min).
    healthy_multiplier : float
        Multiplied by cadence to get the healthy threshold.

    Returns
    -------
    ResurrectionReport
    """
    gaps = tuple(
        _gap_seconds(restart, stroke)
        for restart, stroke in events
    )
    return ResurrectionReport(
        gaps=gaps,
        cadence_seconds=cadence_seconds,
        healthy_multiplier=healthy_multiplier,
    )
