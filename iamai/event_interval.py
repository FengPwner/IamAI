#!/usr/bin/env python3
"""event_interval — compute interval statistics from a sorted timestamp list.

given a sequence of event timestamps, produce:
  - count of events
  - list of intervals (seconds between consecutive events)
  - min, max, mean, median, p95, p99 of intervals
  - coefficient of variation (stddev / mean) — measures rhythm stability

designed for stroke timestamps, commit timestamps, or any monotonic
event series where you want to answer "how regular is this?"

exit codes (CLI wrapper):
  0 — success
  1 — not enough data (need ≥ 2 timestamps for intervals)
  2 — input error
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class IntervalStats:
    count: int
    intervals: list[float]
    min_s: float
    max_s: float
    mean_s: float
    median_s: float
    p95_s: float
    p99_s: float
    cv: float  # coefficient of variation

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("intervals", None)
        return d


def _percentile(sorted_data: list[float], p: float) -> float:
    """linear interpolation percentile, matching numpy's default."""
    if not sorted_data:
        return 0.0
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]
    k = (n - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= n:
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def compute_intervals(timestamps: list[datetime]) -> IntervalStats:
    """compute interval statistics from a list of datetime objects.

    timestamps must be sorted in ascending order; if not, sort them first.
    raises ValueError if fewer than 2 timestamps provided.
    """
    if len(timestamps) < 2:
        raise ValueError(f"need ≥ 2 timestamps, got {len(timestamps)}")

    ts_sorted = sorted(timestamps)
    intervals = [
        (ts_sorted[i + 1] - ts_sorted[i]).total_seconds()
        for i in range(len(ts_sorted) - 1)
    ]

    mean_val = statistics.mean(intervals)
    std_val = statistics.stdev(intervals) if len(intervals) > 1 else 0.0
    cv = std_val / mean_val if mean_val > 0 else 0.0

    return IntervalStats(
        count=len(timestamps),
        intervals=intervals,
        min_s=min(intervals),
        max_s=max(intervals),
        mean_s=round(mean_val, 2),
        median_s=round(statistics.median(intervals), 2),
        p95_s=round(_percentile(sorted(intervals), 95), 2),
        p99_s=round(_percentile(sorted(intervals), 99), 2),
        cv=round(cv, 4),
    )


def classify_rhythm(cv: float) -> str:
    """classify rhythm stability by coefficient of variation.

    cv < 0.15  → metronomic  (very regular)
    cv < 0.40  → steady      (mostly regular)
    cv < 0.80  → uneven      (noticeable variation)
    cv >= 0.80 → erratic     (highly irregular)
    """
    if cv < 0.15:
        return "metronomic"
    elif cv < 0.40:
        return "steady"
    elif cv < 0.80:
        return "uneven"
    else:
        return "erratic"
