"""
commit_gap_analyzer — measure silence between commits

reads a list of commit timestamps and produces:
  - gap_seconds: list[int]  — seconds between consecutive commits
  - mean_gap: float
  - max_gap: int
  - min_gap: int
  - p95_gap: int
  - stall_ratio: float — fraction of gaps exceeding a threshold (default 600s)
  - trend: str — "accelerating" | "steady" | "decaying"

trend is determined by comparing the mean of the first half of gaps to the
mean of the second half:
  - if second_half_mean < first_half_mean * 0.8 → "accelerating" (faster commits)
  - if second_half_mean > first_half_mean * 1.2 → "decaying" (slower commits)
  - otherwise → "steady"

edge cases:
  - 0 or 1 timestamps → empty result with sensible defaults
  - identical timestamps → gap of 0, trend "steady"
  - negative gaps (rebase/clock skew) → clamped to 0
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
import statistics


@dataclass
class GapReport:
    gap_seconds: List[int] = field(default_factory=list)
    mean_gap: float = 0.0
    max_gap: int = 0
    min_gap: int = 0
    p95_gap: int = 0
    stall_ratio: float = 0.0
    trend: str = "steady"
    total_gaps: int = 0
    stall_count: int = 0

    @property
    def is_healthy(self) -> bool:
        return self.stall_ratio < 0.1 and self.trend != "decaying"


def _parse_timestamp(ts: str) -> datetime:
    """parse ISO 8601 timestamp, tolerant of timezone offsets."""
    # handle +00:00 suffix and Z
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _percentile(data: List[int], pct: float) -> int:
    if not data:
        return 0
    sorted_d = sorted(data)
    k = (len(sorted_d) - 1) * pct / 100.0
    f = int(k)
    c = f + 1
    if c >= len(sorted_d):
        return sorted_d[f]
    return int(sorted_d[f] + (k - f) * (sorted_d[c] - sorted_d[f]))


def analyze_gaps(
    timestamps: List[str],
    stall_threshold: int = 600,
) -> GapReport:
    """
    analyze gaps between consecutive commit timestamps.

    Args:
        timestamps: ISO 8601 datetime strings in chronological order.
        stall_threshold: seconds above which a gap counts as a stall.

    Returns:
        GapReport with computed statistics.
    """
    if len(timestamps) < 2:
        return GapReport()

    parsed = [_parse_timestamp(t) for t in timestamps]
    gaps = []
    for i in range(1, len(parsed)):
        delta = int((parsed[i] - parsed[i - 1]).total_seconds())
        gaps.append(max(0, delta))  # clamp negative gaps to 0

    if not gaps:
        return GapReport()

    total_gaps = len(gaps)
    stall_count = sum(1 for g in gaps if g > stall_threshold)
    mean_gap = statistics.mean(gaps)
    max_gap = max(gaps)
    min_gap = min(gaps)
    p95_gap = _percentile(gaps, 95)
    stall_ratio = stall_count / total_gaps

    # trend detection: compare first half mean to second half mean
    mid = total_gaps // 2
    if mid == 0:
        trend = "steady"
    else:
        first_half = gaps[:mid]
        second_half = gaps[mid:]
        first_mean = statistics.mean(first_half)
        second_mean = statistics.mean(second_half)
        if first_mean == 0:
            trend = "steady" if second_mean == 0 else "decaying"
        elif second_mean < first_mean * 0.8:
            trend = "accelerating"
        elif second_mean > first_mean * 1.2:
            trend = "decaying"
        else:
            trend = "steady"

    return GapReport(
        gap_seconds=gaps,
        mean_gap=mean_gap,
        max_gap=max_gap,
        min_gap=min_gap,
        p95_gap=p95_gap,
        stall_ratio=stall_ratio,
        trend=trend,
        total_gaps=total_gaps,
        stall_count=stall_count,
    )


def analyze_from_log_lines(lines: List[str], stall_threshold: int = 600) -> GapReport:
    """
    extract timestamps from devlog-style lines and analyze gaps.

    each line should start with a dash and a backtick-wrapped ISO timestamp.
    lines that don't match are silently skipped.
    """
    timestamps = []
    for line in lines:
        line = line.strip()
        if line.startswith("- `"):
            end = line.find("`", 3)
            if end > 3:
                ts = line[3:end]
                try:
                    _parse_timestamp(ts)  # validate
                    timestamps.append(ts)
                except (ValueError, TypeError):
                    continue
    return analyze_gaps(timestamps, stall_threshold=stall_threshold)
