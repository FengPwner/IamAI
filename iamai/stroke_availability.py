"""stroke_availability — what fraction of wall-clock time was the writer producing?

Stalls, restarts, and container recycling all steal time from the writer.
This module measures the damage by comparing actual stroke output against
the theoretical maximum.

Core metric: **availability ratio** — the fraction of elapsed time during
which the writer was actively producing strokes at or near its expected
cadence.

    availability = productive_time / wall_clock_time

Where:
- ``wall_clock_time`` = last_stroke_ts - first_stroke_ts
- ``productive_time`` = wall_clock_time - sum(stall_durations)
- A **stall** is any inter-stroke gap exceeding ``stall_threshold``

Public API::

    from iamai.stroke_availability import (
        StrokeAvailability, availability_report,
    )

    sa = StrokeAvailability(
        stroke_times=[t0, t1, t2, ...],
        expected_cadence=15,
        stall_threshold=300,   # seconds; gaps longer than this count as stalls
    )
    s = sa.summary()
    # {"wall_clock_s": 86400, "stall_count": 12,
    #  "total_stall_s": 6000, "productive_s": 80400,
    #  "availability": 0.931, "band": "excellent"}

    print(availability_report(stroke_times, expected_cadence=15))
    # "93.1% available (12 stalls, 100min lost over 24h)"

Availability bands
------------------

============  =========  =============================================
band          range      meaning
============  =========  =============================================
excellent     ≥ 0.95     barely any disruption
good          0.85–0.95  occasional stalls, quick recovery
fair          0.70–0.85  noticeable downtime, room to improve
poor          0.50–0.70  significant time lost to stalls
critical      < 0.50     writer is down more than it's running
============  =========  =============================================

Why this matters
----------------

A writer that spends half its time stalled is a writer that needs
better process supervision.  Availability is the single number that
tells you whether the caretaker loop is doing its job.

Zero dependencies.  stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence


@dataclass
class StallRecord:
    """One observed stall in the stroke stream."""

    index: int  # stroke index where the gap begins
    start_ts: float  # timestamp of the last stroke before the gap
    end_ts: float  # timestamp of the first stroke after the gap
    duration_s: float  # gap duration in seconds

    def lost_strokes(self, cadence: float = 15.0) -> float:
        """Estimated strokes lost during this stall."""
        if cadence <= 0:
            return 0.0
        return self.duration_s / cadence


@dataclass
class StrokeAvailability:
    """Compute availability metrics from a stroke timestamp series.

    Parameters
    ----------
    stroke_times : sequence of float
        Ascending UNIX timestamps of observed strokes.
    expected_cadence : float
        Expected seconds between strokes (default 15).
    stall_threshold : float
        Minimum gap (seconds) to count as a stall (default 300).
    """

    stroke_times: Sequence[float]
    expected_cadence: float = 15.0
    stall_threshold: float = 300.0
    _stalls: List[StallRecord] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._stalls = self._detect_stalls()

    def _detect_stalls(self) -> List[StallRecord]:
        """Find all inter-stroke gaps exceeding the stall threshold."""
        stalls: List[StallRecord] = []
        times = self.stroke_times
        for i in range(len(times) - 1):
            gap = times[i + 1] - times[i]
            if gap > self.stall_threshold:
                stalls.append(
                    StallRecord(
                        index=i,
                        start_ts=times[i],
                        end_ts=times[i + 1],
                        duration_s=gap,
                    )
                )
        return stalls

    @property
    def stalls(self) -> List[StallRecord]:
        """All detected stalls."""
        return list(self._stalls)

    def wall_clock_s(self) -> float:
        """Total elapsed time from first to last stroke."""
        if len(self.stroke_times) < 2:
            return 0.0
        return self.stroke_times[-1] - self.stroke_times[0]

    def total_stall_s(self) -> float:
        """Sum of all stall durations."""
        return sum(s.duration_s for s in self._stalls)

    def productive_s(self) -> float:
        """Wall-clock time minus stall time."""
        return max(0.0, self.wall_clock_s() - self.total_stall_s())

    def availability(self) -> float:
        """Availability ratio in [0.0, 1.0]."""
        wc = self.wall_clock_s()
        if wc <= 0.0:
            return 1.0
        return self.productive_s() / wc

    def band(self) -> str:
        """Classify availability into a human-readable band."""
        a = self.availability()
        if a >= 0.95:
            return "excellent"
        if a >= 0.85:
            return "good"
        if a >= 0.70:
            return "fair"
        if a >= 0.50:
            return "poor"
        return "critical"

    def lost_strokes(self) -> float:
        """Total estimated strokes lost across all stalls."""
        if self.expected_cadence <= 0:
            return 0.0
        return self.total_stall_s() / self.expected_cadence

    def summary(self) -> dict:
        """Return a complete availability summary."""
        return {
            "wall_clock_s": round(self.wall_clock_s(), 2),
            "stall_count": len(self._stalls),
            "total_stall_s": round(self.total_stall_s(), 2),
            "productive_s": round(self.productive_s(), 2),
            "availability": round(self.availability(), 4),
            "band": self.band(),
            "lost_strokes": round(self.lost_strokes(), 1),
            "mean_stall_s": (
                round(self.total_stall_s() / len(self._stalls), 2)
                if self._stalls
                else 0.0
            ),
            "max_stall_s": (
                round(max(s.duration_s for s in self._stalls), 2)
                if self._stalls
                else 0.0
            ),
        }


def availability_report(
    stroke_times: Sequence[float],
    expected_cadence: float = 15.0,
    stall_threshold: float = 300.0,
) -> str:
    """One-line human-readable availability report."""
    sa = StrokeAvailability(
        stroke_times=stroke_times,
        expected_cadence=expected_cadence,
        stall_threshold=stall_threshold,
    )
    s = sa.summary()
    pct = s["availability"] * 100
    lost_min = s["total_stall_s"] / 60
    wc_hours = s["wall_clock_s"] / 3600
    return (
        f"{pct:.1f}% available "
        f"({s['stall_count']} stalls, "
        f"{lost_min:.0f}min lost "
        f"over {wc_hours:.1f}h)"
    )
