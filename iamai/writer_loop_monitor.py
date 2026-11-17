"""writer_loop_monitor — writer loop tick health monitor.

Tracks the writer_loop's actual tick timing and compares it against the
expected cadence to detect degradation early:

- **tick jitter**: variance in inter-tick intervals
- **cumulative drift**: how far the loop has drifted from ideal schedule
- **missed ticks**: ticks that should have happened but didn't
- **loop health verdict**: healthy / degraded / critical

Why this matters
----------------

The writer loop targets one stroke every N seconds.  When the system is
under load, ticks get delayed or skipped entirely.  By the time the
caretaker notices a stall, valuable writing time has already been lost.

This module sits *between* the raw writer loop and the caretaker:
it consumes a stream of tick timestamps and emits a structured health
report that the caretaker can act on immediately.

Data model
----------

``TickRecord``: one observed tick.

- ``timestamp`` (float): UNIX epoch of the tick
- ``category`` (str): stroke category (devlog, note, etc.)
- ``expected_at`` (float | None): when the tick *should* have happened

``LoopStats``: aggregate over a rolling window.

- ``tick_count`` (int)
- ``mean_interval`` (float)
- ``jitter_std`` (float)
- ``missed_ticks`` (int)
- ``drift_seconds`` (float)
- ``verdict`` (str): healthy / degraded / critical

Health thresholds
-----------------

===  =======  ============
verdict   jitter_std  missed_pct
=======  ==========  ============
healthy     < 5 s       < 2 %
degraded   < 15 s       < 10 %
critical    >= 15 s     >= 10 %
=======  ==========  ============

Edge cases
----------

- 0 or 1 ticks → cannot compute → verdict ``unknown``
- 2 ticks → jitter is 0.0 (not enough samples)
- All ticks perfectly on time → jitter 0.0, verdict ``healthy``
- Out-of-order ticks → sorted internally before computation
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class TickRecord:
    """One observed writer tick."""

    timestamp: float
    category: str = ""
    expected_at: Optional[float] = None


@dataclass
class LoopStats:
    """Aggregate loop health over a window."""

    tick_count: int = 0
    mean_interval: float = 0.0
    jitter_std: float = 0.0
    missed_ticks: int = 0
    drift_seconds: float = 0.0
    verdict: str = "unknown"

    def summary(self) -> str:
        return (
            f"LoopStats({self.verdict}, ticks={self.tick_count}, "
            f"jitter={self.jitter_std:.2f}s, missed={self.missed_ticks}, "
            f"drift={self.drift_seconds:.1f}s)"
        )


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------

def compute_intervals(ticks: List[TickRecord]) -> List[float]:
    """Compute inter-tick intervals.

    Ticks are sorted by timestamp first; the clamp to 0.0 guards
    against floating-point rounding on duplicate timestamps.
    Returns an empty list if fewer than 2 ticks.
    """
    if len(ticks) < 2:
        return []
    sorted_ticks = sorted(ticks, key=lambda t: t.timestamp)
    intervals = []
    for i in range(1, len(sorted_ticks)):
        delta = sorted_ticks[i].timestamp - sorted_ticks[i - 1].timestamp
        intervals.append(max(0.0, delta))
    return intervals


def compute_jitter(intervals: List[float]) -> float:
    """Standard deviation of intervals.

    - 0 intervals → 0.0
    - 1 interval → 0.0 (cannot compute std of one value)
    - 2+ intervals → population std
    """
    if len(intervals) < 2:
        return 0.0
    return statistics.stdev(intervals)


def compute_missed_ticks(
    ticks: List[TickRecord],
    target_interval: float,
    tolerance: float = 0.5,
) -> int:
    """Count ticks that were expected but not observed.

    Walks the sorted tick list and checks each inter-tick gap.
    If a gap exceeds ``target_interval * (1 + tolerance)``, the gap
    is assumed to contain ``floor(gap / target_interval) - 1`` missed ticks.

    Args:
        ticks: observed tick records
        target_interval: expected seconds between ticks
        tolerance: fractional tolerance (0.5 means gaps > 1.5× target
                   are flagged)

    Returns:
        Total estimated missed ticks across all gaps.
    """
    if len(ticks) < 2 or target_interval <= 0:
        return 0
    sorted_ticks = sorted(ticks, key=lambda t: t.timestamp)
    threshold = target_interval * (1.0 + tolerance)
    missed = 0
    for i in range(1, len(sorted_ticks)):
        gap = sorted_ticks[i].timestamp - sorted_ticks[i - 1].timestamp
        if gap > threshold:
            # How many ticks should have occurred in this gap
            expected_count = int(gap / target_interval)
            # We observed 1 tick (the end of the gap), so missed = expected - 1
            missed += max(0, expected_count - 1)
    return missed


def compute_drift(
    ticks: List[TickRecord],
    target_interval: float,
) -> float:
    """Cumulative drift from ideal schedule.

    Drift = actual elapsed time − (tick_count − 1) × target_interval.

    Positive drift means the loop is running slow (fell behind schedule).
    Negative drift means it's running fast (ahead of schedule).

    Returns 0.0 for fewer than 2 ticks.
    """
    if len(ticks) < 2 or target_interval <= 0:
        return 0.0
    sorted_ticks = sorted(ticks, key=lambda t: t.timestamp)
    elapsed = sorted_ticks[-1].timestamp - sorted_ticks[0].timestamp
    ideal = (len(sorted_ticks) - 1) * target_interval
    return elapsed - ideal


def classify_verdict(
    jitter_std: float,
    missed_pct: float,
) -> str:
    """Map jitter and miss percentage to a health verdict.

    Returns one of: ``healthy``, ``degraded``, ``critical``, ``unknown``.
    """
    if jitter_std < 0 or missed_pct < 0:
        return "unknown"
    if jitter_std >= 15.0 or missed_pct >= 10.0:
        return "critical"
    if jitter_std >= 5.0 or missed_pct >= 2.0:
        return "degraded"
    return "healthy"


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------

def loop_health_report(
    ticks: List[TickRecord],
    target_interval: float = 15.0,
    tolerance: float = 0.5,
) -> LoopStats:
    """Produce a full LoopStats from a list of ticks.

    Args:
        ticks: observed tick records (need not be sorted)
        target_interval: expected seconds between ticks
        tolerance: fractional tolerance for missed-tick detection

    Returns:
        LoopStats with computed metrics and verdict.
    """
    if not ticks:
        return LoopStats(verdict="unknown")

    intervals = compute_intervals(ticks)
    jitter = compute_jitter(intervals)
    missed = compute_missed_ticks(ticks, target_interval, tolerance)
    drift = compute_drift(ticks, target_interval)

    mean_iv = statistics.mean(intervals) if intervals else 0.0
    tick_count = len(ticks)

    # Missed percentage: missed / (observed + missed)
    total_expected = tick_count + missed
    missed_pct = (missed / total_expected * 100.0) if total_expected > 0 else 0.0

    verdict = classify_verdict(jitter, missed_pct)
    if tick_count < 2:
        verdict = "unknown"

    return LoopStats(
        tick_count=tick_count,
        mean_interval=round(mean_iv, 3),
        jitter_std=round(jitter, 3),
        missed_ticks=missed,
        drift_seconds=round(drift, 3),
        verdict=verdict,
    )


def compare_reports(
    before: LoopStats,
    after: LoopStats,
) -> str:
    """Compare two consecutive reports and return a trend label.

    Returns:
        ``improving`` — verdict got better or jitter decreased
        ``stable``    — no change
        ``worsening`` — verdict got worse or jitter increased
        ``unknown``   — insufficient data
    """
    if before.verdict == "unknown" or after.verdict == "unknown":
        return "unknown"

    rank = {"healthy": 0, "degraded": 1, "critical": 2}
    b_rank = rank.get(before.verdict, 3)
    a_rank = rank.get(after.verdict, 3)

    if a_rank < b_rank:
        return "improving"
    if a_rank > b_rank:
        return "worsening"

    # Same verdict — use jitter as tiebreaker
    if after.jitter_std < before.jitter_std - 1.0:
        return "improving"
    if after.jitter_std > before.jitter_std + 1.0:
        return "worsening"
    return "stable"
