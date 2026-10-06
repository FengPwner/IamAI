"""Cadence adherence — how consistently the writer hits its tick interval.

``stroke_rate`` answers *how many* strokes per hour.
``stall_classifier`` answers *is the writer dead right now*.
Neither answers *is the writer steady or erratic?*

A writer producing one stroke every 15 seconds on the dot is healthy.
A writer producing 240 strokes per hour but in bursts of 10 followed
by 5-minute silences is not — even though its rate looks fine.

This module reads ``data/strokes.jsonl`` and computes inter-stroke
gap statistics to measure rhythm quality.

Key metrics:

- **mean_gap** — average seconds between consecutive strokes
- **median_gap** — middle value, robust to outlier stalls
- **jitter** — coefficient of variation (stddev / mean); 0 = metronome
- **adherence_pct** — fraction of gaps within 2× expected cadence
- **long_stall_count** — number of gaps exceeding 4× cadence

Usage::

    from iamai.cadence_adherence import cadence_report, adherence_summary

    report = cadence_report(expected_cadence=15, window_hours=1.0)
    print(report["mean_gap"])         # e.g. 18.5
    print(report["adherence_pct"])    # e.g. 0.92
    print(report["jitter"])           # e.g. 0.35

    summary = adherence_summary(expected_cadence=15)
    print(summary)
    # "cadence 15s: mean 18.5s, median 16s, adherence 92%, jitter 0.35, 2 long stalls"
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path


_DEFAULT_STROKES_PATH = Path("data/strokes.jsonl")


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp to a timezone-aware datetime (UTC)."""
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_strokes(path: Path) -> list[dict]:
    """Load strokes from a JSONL file, skipping malformed lines."""
    if not path.exists():
        return []
    strokes = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "at" in obj:
                    strokes.append(obj)
            except (json.JSONDecodeError, ValueError):
                continue
    return strokes


def _strokes_in_window(strokes: list[dict], hours: float) -> list[dict]:
    """Filter strokes to those within the last *hours* hours."""
    if not strokes:
        return []
    now = datetime.now(timezone.utc)
    cutoff_seconds = hours * 3600
    result = []
    for s in strokes:
        try:
            ts = _parse_timestamp(s["at"])
            age = (now - ts).total_seconds()
            if 0 <= age <= cutoff_seconds:
                result.append(s)
        except (ValueError, KeyError):
            continue
    return result


def _compute_gaps(strokes: list[dict]) -> list[float]:
    """Compute inter-stroke gaps in seconds from a sorted stroke list.

    Strokes are sorted by timestamp ascending.
    """
    if len(strokes) < 2:
        return []
    sorted_strokes = sorted(strokes, key=lambda s: s["at"])
    gaps = []
    for i in range(1, len(sorted_strokes)):
        try:
            t_prev = _parse_timestamp(sorted_strokes[i - 1]["at"])
            t_curr = _parse_timestamp(sorted_strokes[i]["at"])
            gap = (t_curr - t_prev).total_seconds()
            if gap >= 0:
                gaps.append(gap)
        except (ValueError, KeyError):
            continue
    return gaps


def cadence_report(
    expected_cadence: int = 15,
    window_hours: float = 1.0,
    strokes_path: str | Path | None = None,
) -> dict:
    """Compute cadence adherence metrics.

    Args:
        expected_cadence: expected seconds between strokes
        window_hours: how many hours of recent history to analyze
        strokes_path: override path to strokes JSONL

    Returns:
        dict with keys: mean_gap, median_gap, jitter, adherence_pct,
        long_stall_count, total_strokes, window_hours, expected_cadence
    """
    path = Path(strokes_path) if strokes_path else _DEFAULT_STROKES_PATH
    all_strokes = _load_strokes(path)
    window_strokes = _strokes_in_window(all_strokes, window_hours)
    gaps = _compute_gaps(window_strokes)

    if not gaps:
        return {
            "mean_gap": None,
            "median_gap": None,
            "jitter": None,
            "adherence_pct": None,
            "long_stall_count": 0,
            "total_strokes": len(window_strokes),
            "window_hours": window_hours,
            "expected_cadence": expected_cadence,
        }

    mean_gap = statistics.mean(gaps)
    median_gap = statistics.median(gaps)
    stddev = statistics.stdev(gaps) if len(gaps) > 1 else 0.0
    jitter = stddev / mean_gap if mean_gap > 0 else 0.0

    within_2x = sum(1 for g in gaps if g <= 2 * expected_cadence)
    adherence_pct = within_2x / len(gaps)

    long_stall_threshold = 4 * expected_cadence
    long_stall_count = sum(1 for g in gaps if g > long_stall_threshold)

    return {
        "mean_gap": round(mean_gap, 2),
        "median_gap": round(median_gap, 2),
        "jitter": round(jitter, 4),
        "adherence_pct": round(adherence_pct, 4),
        "long_stall_count": long_stall_count,
        "total_strokes": len(window_strokes),
        "window_hours": window_hours,
        "expected_cadence": expected_cadence,
    }


def adherence_summary(
    expected_cadence: int = 15,
    window_hours: float = 1.0,
    strokes_path: str | Path | None = None,
) -> str:
    """One-line human-readable cadence adherence summary.

    Args:
        expected_cadence: expected seconds between strokes
        window_hours: analysis window in hours
        strokes_path: override path to strokes JSONL

    Returns:
        A formatted summary string
    """
    report = cadence_report(expected_cadence, window_hours, strokes_path)

    if report["mean_gap"] is None:
        return (
            f"cadence {expected_cadence}s: "
            f"insufficient data ({report['total_strokes']} strokes in "
            f"{window_hours}h window)"
        )

    return (
        f"cadence {expected_cadence}s: "
        f"mean {report['mean_gap']}s, "
        f"median {report['median_gap']}s, "
        f"adherence {report['adherence_pct']:.0%}, "
        f"jitter {report['jitter']:.2f}, "
        f"{report['long_stall_count']} long stall(s) "
        f"({report['total_strokes']} strokes in {window_hours}h)"
    )


def grade_adherence(report: dict) -> str:
    """Assign a letter grade to cadence adherence.

    Args:
        report: output of cadence_report()

    Returns:
        Letter grade: A (excellent), B (good), C (degraded), F (broken)
    """
    pct = report.get("adherence_pct")
    if pct is None:
        return "?"

    if pct >= 0.95:
        return "A"
    if pct >= 0.80:
        return "B"
    if pct >= 0.60:
        return "C"
    return "F"
