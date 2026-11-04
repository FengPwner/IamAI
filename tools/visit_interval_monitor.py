#!/usr/bin/env python3
"""visit_interval_monitor.py — measure gaps between caretaker visits.

the caretaker is supposed to check in regularly. if visits cluster too
tightly (a "storm"), the caretaker is probably stuck in a restart loop.
if the gap stretches past a day, the container may have been recycled
without anyone noticing.

this tool parses caretaker visit note filenames to extract visit numbers
and dates, then computes intervals and classifies the pattern.

exit codes:
  0 — healthy (intervals within normal range)
  1 — warning (some intervals outside normal range)
  2 — storm detected (rapid-fire visits < 5 minutes apart)
  3 — neglect detected (gap > 24 hours with no visits)
  4 — insufficient data (< 3 visits to analyze)

usage:
  python3 tools/visit_interval_monitor.py [--json] [--notes-dir NOTES_DIR]
  python3 tools/visit_interval_monitor.py --last 20    # only last 20 visits
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_NOTES = REPO / "notes"

# a caretaker visit filename looks like:
#   caretaker-visit-541-2026-11-04.md
#   caretaker-visit-522-commit-signal.md   (no date)
# we only analyze date-stamped ones.
VISIT_RE = re.compile(
    r"caretaker-visit-(\d+)-(\d{4}-\d{2}-\d{2})\.md$"
)

# thresholds
STORM_THRESHOLD = timedelta(minutes=5)
HEALTHY_MAX = timedelta(hours=6)
NEGLECT_THRESHOLD = timedelta(hours=24)
NORMAL_MIN = timedelta(minutes=30)


def parse_visits(notes_dir: Path) -> list[dict]:
    """scan note files and return sorted list of visit records."""
    visits = []
    if not notes_dir.is_dir():
        return visits

    for fname in os.listdir(notes_dir):
        m = VISIT_RE.match(fname)
        if not m:
            continue
        visit_num = int(m.group(1))
        date_str = m.group(2)
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        visits.append({
            "visit": visit_num,
            "date": date,
            "filename": fname,
        })

    visits.sort(key=lambda v: (v["date"], v["visit"]))
    return visits


def compute_intervals(visits: list[dict]) -> list[dict]:
    """compute intervals between consecutive visits on the same date or nearby."""
    intervals = []
    for i in range(1, len(visits)):
        prev = visits[i - 1]
        curr = visits[i]
        delta = curr["date"] - prev["date"]
        intervals.append({
            "from_visit": prev["visit"],
            "to_visit": curr["visit"],
            "from_date": prev["date"].strftime("%Y-%m-%d"),
            "to_date": curr["date"].strftime("%Y-%m-%d"),
            "gap_days": delta.days,
            "visit_diff": curr["visit"] - prev["visit"],
        })
    return intervals


def classify_interval(interval: dict) -> str:
    """classify a single interval."""
    gap = interval["gap_days"]
    vdiff = interval["visit_diff"]

    if gap == 0 and vdiff <= 2:
        return "cluster"  # many visits same day, small number diff
    elif gap == 0:
        return "dense"  # many visits same day
    elif 1 <= gap <= 2:
        return "healthy"
    elif 3 <= gap <= 7:
        return "sparse"
    else:
        return "neglect"


def analyze(intervals: list[dict]) -> dict:
    """produce a summary analysis of visit intervals."""
    if len(intervals) < 2:
        return {
            "status": "insufficient_data",
            "exit_code": 4,
            "total_intervals": len(intervals),
            "message": "need at least 2 intervals (3 visits) to analyze",
        }

    classifications = [classify_interval(iv) for iv in intervals]

    # count by type
    counts = {}
    for c in classifications:
        counts[c] = counts.get(c, 0) + 1

    # detect storms: many cluster intervals in a row
    max_consecutive_clusters = 0
    current_run = 0
    for c in classifications:
        if c in ("cluster", "dense"):
            current_run += 1
            max_consecutive_clusters = max(max_consecutive_clusters, current_run)
        else:
            current_run = 0

    # detect neglect
    max_gap = max(iv["gap_days"] for iv in intervals)
    has_neglect = max_gap > 7

    # recent trend (last 10 intervals)
    recent = intervals[-10:]
    recent_classifications = [classify_interval(iv) for iv in recent]

    # determine overall status
    if max_consecutive_clusters >= 5:
        status = "storm"
        exit_code = 2
    elif has_neglect:
        status = "neglect"
        exit_code = 3
    elif counts.get("cluster", 0) > len(intervals) * 0.5:
        status = "warning"
        exit_code = 1
    else:
        status = "healthy"
        exit_code = 0

    return {
        "status": status,
        "exit_code": exit_code,
        "total_intervals": len(intervals),
        "classifications": counts,
        "max_consecutive_clusters": max_consecutive_clusters,
        "max_gap_days": max_gap,
        "recent_trend": recent_classifications,
    }


def human_summary(analysis: dict) -> str:
    """one-line human-readable summary."""
    status = analysis["status"]
    total = analysis["total_intervals"]
    if status == "insufficient_data":
        return f"insufficient data ({total} intervals, need 2+)"
    cls = analysis.get("classifications", {})
    max_gap = analysis.get("max_gap_days", 0)
    clusters = analysis.get("max_consecutive_clusters", 0)
    return (
        f"{status} — {total} intervals, "
        f"max gap {max_gap}d, "
        f"max cluster run {clusters}, "
        f"breakdown: {cls}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="emit structured JSON")
    ap.add_argument(
        "--notes-dir",
        type=Path,
        default=DEFAULT_NOTES,
        help="directory containing caretaker visit notes",
    )
    ap.add_argument(
        "--last",
        type=int,
        default=0,
        help="only analyze the last N visits (0 = all)",
    )
    args = ap.parse_args()

    visits = parse_visits(args.notes_dir)
    if args.last > 0:
        visits = visits[-args.last:]

    intervals = compute_intervals(visits)
    analysis = analyze(intervals)

    if args.json:
        print(json.dumps(analysis, indent=2))
    else:
        print(human_summary(analysis))

    return analysis["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
