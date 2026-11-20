#!/usr/bin/env python3
"""caretaker_visit_counter.py — count and analyze caretaker visit patterns.

scans the notes/ directory for caretaker-visit-*.md files, extracts
visit numbers and dates, and reports:

1. total visit count
2. visit frequency (visits per day over the observation window)
3. longest gap between consecutive visits (in hours)
4. coverage ratio: actual visits / expected visits at 10-min cadence
5. trend: are visits getting more or less frequent?

usage:
    python3 tools/caretaker_visit_counter.py
    python3 tools/caretaker_visit_counter.py --json
    python3 tools/caretaker_visit_counter.py --notes-dir /path/to/notes
    python3 tools/caretaker_visit_counter.py --recent-window 30

exit codes:
    0 — coverage is healthy (gap < 2 days, frequency stable or improving)
    1 — coverage is degraded (gap >= 2 days or frequency declining)
    2 — error (notes directory missing, no visits found)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple


VISIT_PATTERN = re.compile(
    r"caretaker-visit-(\d+)-(\d{4}-\d{2}-\d{2})\.md$"
)


@dataclass
class Visit:
    number: int
    date: datetime
    filename: str


@dataclass
class VisitStats:
    total_visits: int
    first_visit_date: str
    last_visit_date: str
    observation_days: float
    visits_per_day: float
    longest_gap_hours: float
    longest_gap_between: Tuple[int, int]
    median_gap_hours: float
    recent_trend: str
    coverage_ratio_10min: float
    verdict: str


def parse_visits(notes_dir: Path) -> List[Visit]:
    """Scan notes directory for caretaker visit files."""
    visits = []
    if not notes_dir.is_dir():
        return visits
    for entry in notes_dir.iterdir():
        m = VISIT_PATTERN.match(entry.name)
        if m:
            number = int(m.group(1))
            date = datetime.strptime(m.group(2), "%Y-%m-%d")
            visits.append(Visit(number=number, date=date, filename=entry.name))
    visits.sort(key=lambda v: (v.date, v.number))
    return visits


def compute_stats(
    visits: List[Visit],
    recent_window_days: int = 14,
) -> Optional[VisitStats]:
    """Compute visit statistics from a sorted list of visits."""
    if len(visits) < 2:
        return None

    first_date = visits[0].date
    last_date = visits[-1].date
    obs_days = max((last_date - first_date).total_seconds() / 86400, 1.0)

    # gaps between consecutive visits
    gaps_hours: List[float] = []
    gap_pairs: List[Tuple[int, int]] = []
    for i in range(1, len(visits)):
        gap = (visits[i].date - visits[i - 1].date).total_seconds() / 3600
        gaps_hours.append(gap)
        gap_pairs.append((visits[i - 1].number, visits[i].number))

    max_gap_idx = gaps_hours.index(max(gaps_hours))
    longest_gap_hours = gaps_hours[max_gap_idx]
    longest_gap_between = gap_pairs[max_gap_idx]

    sorted_gaps = sorted(gaps_hours)
    n = len(sorted_gaps)
    if n % 2 == 1:
        median_gap = sorted_gaps[n // 2]
    else:
        median_gap = (sorted_gaps[n // 2 - 1] + sorted_gaps[n // 2]) / 2

    # trend: compare visit rate in recent window vs overall
    # clamp recent_window to observation window to avoid skew
    effective_window = min(recent_window_days, obs_days)
    cutoff = last_date - timedelta(days=effective_window)
    recent_visits = [v for v in visits if v.date >= cutoff]
    recent_days = max(effective_window, 1.0)
    recent_rate = len(recent_visits) / recent_days
    overall_rate = len(visits) / obs_days

    if overall_rate > 0:
        trend_ratio = recent_rate / overall_rate
        if trend_ratio > 1.1:
            trend = "improving"
        elif trend_ratio < 0.9:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "unknown"

    # coverage ratio: actual visits vs theoretical 10-min cadence
    theoretical_max = obs_days * 24 * 6
    coverage = len(visits) / theoretical_max if theoretical_max > 0 else 0.0

    visits_per_day = len(visits) / obs_days

    degraded = longest_gap_hours >= 48.0 or trend == "declining"
    verdict = "degraded" if degraded else "healthy"

    return VisitStats(
        total_visits=len(visits),
        first_visit_date=first_date.strftime("%Y-%m-%d"),
        last_visit_date=last_date.strftime("%Y-%m-%d"),
        observation_days=round(obs_days, 1),
        visits_per_day=round(visits_per_day, 2),
        longest_gap_hours=round(longest_gap_hours, 1),
        longest_gap_between=longest_gap_between,
        median_gap_hours=round(median_gap, 1),
        recent_trend=trend,
        coverage_ratio_10min=round(coverage, 4),
        verdict=verdict,
    )


def format_report(stats: VisitStats) -> str:
    """Format stats as a human-readable report."""
    lines = [
        "caretaker visit report",
        "=" * 40,
        f"total visits:       {stats.total_visits}",
        f"date range:         {stats.first_visit_date} → {stats.last_visit_date}",
        f"observation window: {stats.observation_days} days",
        f"visits per day:     {stats.visits_per_day}",
        f"median gap:         {stats.median_gap_hours}h",
        f"longest gap:        {stats.longest_gap_hours}h "
        f"(between visits {stats.longest_gap_between[0]} → "
        f"{stats.longest_gap_between[1]})",
        f"recent trend:       {stats.recent_trend}",
        f"coverage (10min):   {stats.coverage_ratio_10min:.2%}",
        f"verdict:            {stats.verdict}",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="caretaker visit counter")
    parser.add_argument(
        "--notes-dir", type=str, default=None,
        help="path to notes directory (default: ./notes)",
    )
    parser.add_argument(
        "--recent-window", type=int, default=14,
        help="days to use for recent trend comparison (default: 14)",
    )
    parser.add_argument("--json", action="store_true", help="output as JSON")
    args = parser.parse_args(argv)

    if args.notes_dir:
        notes_dir = Path(args.notes_dir)
    else:
        repo_root = Path(__file__).resolve().parent.parent
        notes_dir = repo_root / "notes"

    if not notes_dir.is_dir():
        print(f"error: notes directory not found: {notes_dir}", file=sys.stderr)
        return 2

    visits = parse_visits(notes_dir)
    if len(visits) < 2:
        print(
            f"error: found only {len(visits)} visit(s), need at least 2",
            file=sys.stderr,
        )
        return 2

    stats = compute_stats(visits, recent_window_days=args.recent_window)
    if stats is None:
        print("error: could not compute statistics", file=sys.stderr)
        return 2

    if args.json:
        d = asdict(stats)
        d["longest_gap_between"] = list(stats.longest_gap_between)
        print(json.dumps(d, indent=2))
    else:
        print(format_report(stats))

    return 1 if stats.verdict == "degraded" else 0


if __name__ == "__main__":
    sys.exit(main())
