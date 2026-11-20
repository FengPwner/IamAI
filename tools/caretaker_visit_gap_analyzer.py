#!/usr/bin/env python3
"""caretaker_visit_gap_analyzer.py — measure intervals between caretaker visits.

The caretaker is the external process (human or automated) that checks
on this repo, restarts dead processes, commits stale work, and adds
new content.  Visits are recorded as commits whose message starts with
"caretaker visit N".

This module extracts those timestamps and computes:

  - gaps between consecutive visits (min, max, mean, median, std)
  - visit frequency per day (rolling 7-day window)
  - longest gap (the "absence record")
  - gap trend — are visits getting more or less frequent?
  - reliability class:
      reliable   — median gap < 2h, no gap > 12h
      attentive  — median gap < 6h, no gap > 24h
      sporadic   — median gap < 24h
      absent     — otherwise

The gap distribution tells a story: a tight distribution means the
caretaker runs on a schedule; a wide one means visits are reactive
(triggered by alerts or convenience).  Neither is inherently better —
but the repo's health correlates with visit frequency.

Usage:
    python3 tools/caretaker_visit_gap_analyzer.py
    python3 tools/caretaker_visit_gap_analyzer.py --last 50
    python3 tools/caretaker_visit_gap_analyzer.py --json

Exit codes:
    0  success
    2  insufficient data (< 2 visits found)
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
VISIT_PATTERN = re.compile(r"caretaker visit (\d+)")


@dataclass
class Visit:
    """A single caretaker visit extracted from git log."""
    number: int
    timestamp: datetime
    commit_hash: str
    message: str


@dataclass
class GapReport:
    """Summary of caretaker visit intervals."""
    total_visits: int
    first_visit_iso: str
    last_visit_iso: str
    span_hours: float
    gap_min_hours: float
    gap_max_hours: float
    gap_mean_hours: float
    gap_median_hours: float
    gap_std_hours: float
    visits_per_day: float
    longest_gap_record: str  # "visit N → visit M (Xh Ym)"
    trend: str  # "more_frequent" | "less_frequent" | "stable"
    trend_slope: float  # hours per visit-index; negative = shrinking gaps
    reliability: str  # "reliable" | "attentive" | "sporadic" | "absent"


def extract_visits(
    repo_root: Path = REPO_ROOT,
    last_n: Optional[int] = None,
) -> List[Visit]:
    """Parse git log for caretaker visit commits.

    Returns visits sorted oldest-first.
    """
    cmd = [
        "git", "log",
        "--format=%H|%aI|%s",
        "--all",
    ]
    if last_n:
        cmd.append(f"-{last_n * 3}")  # over-fetch to account for non-visit commits

    try:
        out = subprocess.check_output(
            cmd, cwd=repo_root, stderr=subprocess.DEVNULL, text=True,
        )
    except subprocess.CalledProcessError:
        return []

    visits: List[Visit] = []
    for line in out.strip().splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        commit_hash, ts_str, message = parts
        m = VISIT_PATTERN.search(message)
        if not m:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        visits.append(Visit(
            number=int(m.group(1)),
            timestamp=ts,
            commit_hash=commit_hash[:12],
            message=message.strip(),
        ))

    visits.sort(key=lambda v: v.timestamp)

    if last_n:
        visits = visits[-last_n:]

    return visits


def compute_gaps(visits: List[Visit]) -> List[timedelta]:
    """Compute time deltas between consecutive visits."""
    if len(visits) < 2:
        return []
    return [
        visits[i + 1].timestamp - visits[i].timestamp
        for i in range(len(visits) - 1)
    ]


def _gap_hours(gaps: List[timedelta]) -> List[float]:
    """Convert timedeltas to hours."""
    return [g.total_seconds() / 3600 for g in gaps]


def _linear_regression(xs: List[float], ys: List[float]) -> float:
    """Simple OLS slope. Returns 0.0 if insufficient data."""
    n = len(xs)
    if n < 2:
        return 0.0
    x_mean = statistics.mean(xs)
    y_mean = statistics.mean(ys)
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


def classify_trend(slope: float, threshold: float = 0.01) -> str:
    """Classify gap trend based on slope (hours per visit-index).

    Negative slope → gaps shrinking → visits becoming more frequent.
    Positive slope → gaps growing → visits becoming less frequent.
    """
    if slope < -threshold:
        return "more_frequent"
    elif slope > threshold:
        return "less_frequent"
    return "stable"


def classify_reliability(
    median_hours: float,
    max_hours: float,
) -> str:
    """Classify caretaker reliability from gap statistics."""
    if median_hours < 2 and max_hours < 12:
        return "reliable"
    elif median_hours < 6 and max_hours < 24:
        return "attentive"
    elif median_hours < 24:
        return "sporadic"
    return "absent"


def analyze_gaps(
    visits: List[Visit],
) -> GapReport:
    """Build a full gap report from a list of visits."""
    if len(visits) < 2:
        raise ValueError("need at least 2 visits to compute gaps")

    gaps = compute_gaps(visits)
    hours = _gap_hours(gaps)

    # Find the longest gap
    max_idx = hours.index(max(hours))
    longest_gap_record = (
        f"visit {visits[max_idx].number} → visit {visits[max_idx + 1].number} "
        f"({hours[max_idx]:.1f}h)"
    )

    # Trend: linear regression of gap hours vs visit index
    xs = list(range(len(hours)))
    slope = _linear_regression(xs, hours)
    trend = classify_trend(slope)

    # Span
    span = visits[-1].timestamp - visits[0].timestamp
    span_hours = span.total_seconds() / 3600
    days = span_hours / 24 if span_hours > 0 else 1
    visits_per_day = len(visits) / days

    # Reliability
    median_h = statistics.median(hours)
    max_h = max(hours)
    reliability = classify_reliability(median_h, max_h)

    return GapReport(
        total_visits=len(visits),
        first_visit_iso=visits[0].timestamp.isoformat(),
        last_visit_iso=visits[-1].timestamp.isoformat(),
        span_hours=round(span_hours, 1),
        gap_min_hours=round(min(hours), 2),
        gap_max_hours=round(max_h, 2),
        gap_mean_hours=round(statistics.mean(hours), 2),
        gap_median_hours=round(median_h, 2),
        gap_std_hours=round(statistics.stdev(hours) if len(hours) > 1 else 0.0, 2),
        visits_per_day=round(visits_per_day, 2),
        longest_gap_record=longest_gap_record,
        trend=trend,
        trend_slope=round(slope, 4),
        reliability=reliability,
    )


def format_report(report: GapReport) -> str:
    """Human-readable report."""
    lines = [
        f"caretaker visit gap analysis",
        f"  visits:        {report.total_visits}",
        f"  span:          {report.span_hours:.1f} hours "
        f"({report.first_visit_iso[:10]} → {report.last_visit_iso[:10]})",
        f"  frequency:     {report.visits_per_day:.1f} visits/day",
        f"",
        f"  gap min:       {report.gap_min_hours:.2f}h",
        f"  gap max:       {report.gap_max_hours:.2f}h",
        f"  gap mean:      {report.gap_mean_hours:.2f}h",
        f"  gap median:    {report.gap_median_hours:.2f}h",
        f"  gap std:       {report.gap_std_hours:.2f}h",
        f"  longest gap:   {report.longest_gap_record}",
        f"",
        f"  trend:         {report.trend} (slope {report.trend_slope:+.4f} h/visit)",
        f"  reliability:   {report.reliability}",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze gaps between caretaker visits."
    )
    parser.add_argument(
        "--last", "-n", type=int, default=None,
        help="analyse only the last N visits (default: all)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="output as JSON"
    )
    args = parser.parse_args()

    visits = extract_visits(last_n=args.last)
    if len(visits) < 2:
        print(f"insufficient data: only {len(visits)} visit(s) found",
              file=sys.stderr)
        return 2

    report = analyze_gaps(visits)

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(format_report(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
