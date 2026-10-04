"""052 — gap_analyzer: classify stroke gaps into severity buckets.

a writer that stalls for 30 seconds is probably thinking. a writer that
stalls for 30 minutes is dead. the gap_analyzer turns a list of stroke
timestamps into a severity report: how many gaps were normal, how many
were concerning, and how many crossed the "process is gone" threshold.

the thresholds are multiples of the writer's cadence:

  - OK:        gap <= 2x cadence  (normal variance)
  - WARNING:   gap <= 10x cadence (slow, but might recover)
  - CRITICAL:  gap >  10x cadence (process likely dead)

usage:

>>> from datetime import datetime, timezone, timedelta
>>> now = datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc)
>>> ts = [now - timedelta(seconds=i*15) for i in reversed(range(10))]
>>> ts.append(now + timedelta(seconds=3600))  # one huge gap
>>> report = analyze_gaps(ts, cadence=15)
>>> report.total_gaps
10
>>> report.critical
1
>>> report.ok
9

"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Sequence


@dataclass(frozen=True)
class GapReport:
    """Summary of gap severity across a stroke timeline."""

    total_gaps: int
    ok: int
    warning: int
    critical: int
    max_gap_seconds: float
    mean_gap_seconds: float
    longest_gap_at: Optional[datetime]

    @property
    def health(self) -> str:
        """Single-word health assessment."""
        if self.critical > 0:
            return "critical"
        if self.warning > 0:
            return "degraded"
        return "healthy"


def analyze_gaps(
    timestamps: Sequence[datetime],
    cadence: float = 15.0,
) -> GapReport:
    """Analyze gaps between consecutive stroke timestamps.

    Args:
        timestamps: monotonically increasing datetime sequence.
        cadence: expected seconds between strokes.

    Returns:
        GapReport with severity bucket counts and statistics.
    """
    if len(timestamps) < 2:
        return GapReport(
            total_gaps=0,
            ok=0,
            warning=0,
            critical=0,
            max_gap_seconds=0.0,
            mean_gap_seconds=0.0,
            longest_gap_at=None,
        )

    ok = warning = critical = 0
    max_gap = 0.0
    max_gap_at: Optional[datetime] = None
    total_seconds = 0.0
    gap_count = 0

    warn_threshold = 2 * cadence
    crit_threshold = 10 * cadence

    for i in range(1, len(timestamps)):
        gap = (timestamps[i] - timestamps[i - 1]).total_seconds()
        total_seconds += gap
        gap_count += 1

        if gap > max_gap:
            max_gap = gap
            max_gap_at = timestamps[i]

        if gap > crit_threshold:
            critical += 1
        elif gap > warn_threshold:
            warning += 1
        else:
            ok += 1

    return GapReport(
        total_gaps=gap_count,
        ok=ok,
        warning=warning,
        critical=critical,
        max_gap_seconds=max_gap,
        mean_gap_seconds=total_seconds / gap_count if gap_count else 0.0,
        longest_gap_at=max_gap_at,
    )
