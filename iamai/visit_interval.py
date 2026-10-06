"""Analyze intervals between caretaker visits.

Caretaker visit notes live in ``notes/caretaker-visit-<N>-<date>.md``.
The filenames encode a visit number and a date; parsing them gives us
a timeline of human attention on this repo.

Why this matters: if visits cluster (many visits in a short window),
something is unstable. If gaps grow long and nothing breaks, the
processes are self-sustaining. This module turns a directory listing
into that signal.

Usage::

    from iamai.visit_interval import visit_stats
    stats = visit_stats("notes/")
    print(stats["mean_interval_hours"])  # e.g., 2.3
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any


_VISIT_RE = re.compile(
    r"caretaker-visit-(\d+)-(\d{4}-\d{2}-\d{2})\.md$"
)


def parse_visit_files(notes_dir: str | Path) -> list[dict[str, Any]]:
    """Scan a directory for caretaker visit notes.

    Returns a list of dicts sorted by visit number, each containing:
        - visit_number: int
        - date: str (YYYY-MM-DD)
        - filename: str (basename)

    Files that don't match the pattern are silently skipped.
    """
    notes_dir = Path(notes_dir)
    if not notes_dir.is_dir():
        return []

    visits = []
    for entry in notes_dir.iterdir():
        m = _VISIT_RE.match(entry.name)
        if m:
            visits.append({
                "visit_number": int(m.group(1)),
                "date": m.group(2),
                "filename": entry.name,
            })

    visits.sort(key=lambda v: v["visit_number"])
    return visits


def visit_intervals(notes_dir: str | Path) -> list[float]:
    """Compute hours between consecutive visits.

    Returns a list of interval values (hours). Length is N-1 where N
    is the number of visit files found.
    """
    visits = parse_visit_files(notes_dir)
    if len(visits) < 2:
        return []

    intervals = []
    for i in range(1, len(visits)):
        d_prev = datetime.strptime(visits[i - 1]["date"], "%Y-%m-%d")
        d_curr = datetime.strptime(visits[i]["date"], "%Y-%m-%d")
        delta_hours = (d_curr - d_prev).total_seconds() / 3600.0
        intervals.append(delta_hours)

    return intervals


def visit_stats(notes_dir: str | Path) -> dict[str, Any]:
    """Summary statistics for caretaker visit intervals.

    Returns:
        - count: total number of visit notes found
        - first_visit: visit number of the earliest note
        - last_visit: visit number of the latest note
        - date_span_days: days between first and last visit date
        - mean_interval_hours: average hours between consecutive visits
        - min_interval_hours: shortest gap
        - max_interval_hours: longest gap
        - same_day_visits: count of intervals that are 0 days (same date)

    Returns zeroed stats if fewer than 2 visits found.
    """
    visits = parse_visit_files(notes_dir)

    if len(visits) < 2:
        return {
            "count": len(visits),
            "first_visit": visits[0]["visit_number"] if visits else 0,
            "last_visit": visits[-1]["visit_number"] if visits else 0,
            "date_span_days": 0,
            "mean_interval_hours": 0.0,
            "min_interval_hours": 0.0,
            "max_interval_hours": 0.0,
            "same_day_visits": 0,
        }

    intervals = visit_intervals(notes_dir)
    first_date = datetime.strptime(visits[0]["date"], "%Y-%m-%d")
    last_date = datetime.strptime(visits[-1]["date"], "%Y-%m-%d")
    span = (last_date - first_date).days

    return {
        "count": len(visits),
        "first_visit": visits[0]["visit_number"],
        "last_visit": visits[-1]["visit_number"],
        "date_span_days": span,
        "mean_interval_hours": round(sum(intervals) / len(intervals), 2),
        "min_interval_hours": round(min(intervals), 2),
        "max_interval_hours": round(max(intervals), 2),
        "same_day_visits": sum(1 for h in intervals if h == 0.0),
    }
