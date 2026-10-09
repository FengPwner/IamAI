"""Caretaker rhythm analysis — measure visit regularity.

The IamAI repo is maintained by a rotating cast of caretakers who visit
on a roughly hourly schedule. This module answers the question: *how
regular is that rhythm, and where did it break?*

It parses the git log to find caretaker visits (commits whose message
starts with ``caretaker-NN:`` or ``caretaker:``), computes the intervals
between consecutive visits, and produces regularity statistics:

    {
        "visits": 98,
        "mean_interval_minutes": 62.4,
        "median_interval_minutes": 60.0,
        "std_interval_minutes": 18.7,
        "rhythm_score": 0.70,
        "gaps": [{"index": 44, "minutes": 180.0, ...}],
    }

Design choices:

- Visit detection uses the commit message prefix ``caretaker[-NN]``.
  Catch-up commits (``catch-up: ...``) are *not* caretaker visits —
  they are automated restarts that happen when the hourly caretaker
  fails to run. Including them would mask the gaps we want to see.
- Intervals are measured between consecutive visits in chronological
  order (oldest first), so the first visit has no preceding interval.
- Rhythm score is ``1 - CV`` where CV is the coefficient of variation
  (std / mean) clamped to [0, 1]. A perfectly regular schedule scores
  1.0; high variance drives the score toward 0.
- Gap detection flags intervals exceeding a configurable threshold
  (default 120 minutes = 2× the expected hourly cadence).

Usage::

    from iamai.caretaker_rhythm import caretaker_rhythm, rhythm_report

    info = caretaker_rhythm("/path/to/IamAI", max_visits=50)
    print(f"{info['visits']} visits, mean {info['mean_interval_minutes']:.0f}m")
    print(rhythm_report("/path/to/IamAI"))
    # "98 visits over 4.1d — mean 62m, rhythm 0.70, 3 gaps"
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CARETAKER_RE = re.compile(
    r"^(?:caretaker-(\d+)|caretaker):", re.IGNORECASE
)


def _git_log(repo: Path, max_visits: int) -> str:
    """Fetch git log output for parsing."""
    proc = subprocess.run(
        [
            "git",
            "log",
            f"--max-count={max_visits * 3}",
            "--format=%ai %s",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.stdout


def _extract_visits(log_output: str) -> list[tuple[datetime, str, int | None]]:
    """Parse git log into (timestamp, full_message, visit_number|None).

    Visits are returned newest-first (git log default order).
    """
    visits: list[tuple[datetime, str, int | None]] = []
    for line in log_output.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Format: "2026-10-09 13:00:56 +0800 caretaker-101: ..."
        parts = line.split(" ", 3)
        if len(parts) < 4:
            continue
        date_str = parts[0]
        time_str = parts[1]
        tz_str = parts[2]
        message = parts[3]

        m = _CARETAKER_RE.match(message)
        if not m:
            continue

        visit_num = int(m.group(1)) if m.group(1) else None
        ts_str = f"{date_str} {time_str} {tz_str}"
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            continue

        visits.append((ts, message, visit_num))

    return visits


def _intervals_minutes(
    visits: list[tuple[datetime, str, int | None]],
) -> list[float]:
    """Compute intervals in minutes between consecutive visits.

    Input is newest-first; output intervals are oldest-to-newest
    (reversed so interval[i] = gap before visit[i] chronologically).
    """
    if len(visits) < 2:
        return []

    reversed_visits = list(reversed(visits))
    intervals: list[float] = []
    for i in range(1, len(reversed_visits)):
        prev_ts = reversed_visits[i - 1][0]
        curr_ts = reversed_visits[i][0]
        delta = (curr_ts - prev_ts).total_seconds() / 60.0
        intervals.append(delta)

    return intervals


def _compute_stats(values: list[float]) -> dict[str, float]:
    """Compute mean, median, std, min, max for a list of values."""
    if not values:
        return {
            "mean": 0.0,
            "median": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
        }

    n = len(values)
    mean = sum(values) / n
    sorted_vals = sorted(values)

    if n % 2 == 0:
        median = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0
    else:
        median = sorted_vals[n // 2]

    variance = sum((v - mean) ** 2 for v in values) / n if n > 0 else 0.0
    std = variance**0.5

    return {
        "mean": round(mean, 2),
        "median": round(median, 2),
        "std": round(std, 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }


def _rhythm_score(std: float, mean: float) -> float:
    """Compute rhythm score: 1 - CV, clamped to [0, 1].

    CV (coefficient of variation) = std / mean.
    Perfect regularity → CV = 0 → score = 1.0.
    High variance → CV ≥ 1 → score = 0.0.
    """
    if mean <= 0:
        return 0.0
    cv = std / mean
    return round(max(0.0, min(1.0, 1.0 - cv)), 3)


def _find_gaps(
    intervals: list[float],
    visits: list[tuple[datetime, str, int | None]],
    threshold_minutes: float,
) -> list[dict[str, Any]]:
    """Find intervals exceeding the threshold.

    Intervals are oldest-to-newest; visits are newest-first.
    Interval[i] is the gap before chronological visit[i+1].
    """
    gaps: list[dict[str, Any]] = []
    reversed_visits = list(reversed(visits))

    for i, interval in enumerate(intervals):
        if interval > threshold_minutes:
            visit_idx = i + 1  # chronological index of the later visit
            if visit_idx < len(reversed_visits):
                ts, msg, num = reversed_visits[visit_idx]
                gaps.append(
                    {
                        "index": visit_idx,
                        "minutes": round(interval, 1),
                        "timestamp": ts.isoformat(),
                        "message": msg,
                        "visit_number": num,
                    }
                )

    return gaps


def caretaker_rhythm(
    repo: Path | str,
    max_visits: int = 100,
    gap_threshold_minutes: float = 120.0,
) -> dict[str, Any]:
    """Analyze the rhythm of caretaker visits.

    Parameters
    ----------
    repo : Path or str
        Repository root.
    max_visits : int
        Maximum number of recent caretaker visits to analyze.
    gap_threshold_minutes : float
        Intervals exceeding this are flagged as gaps.
        Default 120 (2× the expected hourly cadence).

    Returns
    -------
    dict with keys: visits, mean_interval_minutes, median_interval_minutes,
    std_interval_minutes, min_interval_minutes, max_interval_minutes,
    rhythm_score, gaps, first_visit_at, last_visit_at, span_hours.
    """
    repo = Path(repo)
    log_output = _git_log(repo, max_visits)
    visits = _extract_visits(log_output)

    if not visits:
        return {
            "visits": 0,
            "mean_interval_minutes": 0.0,
            "median_interval_minutes": 0.0,
            "std_interval_minutes": 0.0,
            "min_interval_minutes": 0.0,
            "max_interval_minutes": 0.0,
            "rhythm_score": 0.0,
            "gaps": [],
            "first_visit_at": None,
            "last_visit_at": None,
            "span_hours": 0.0,
        }

    # Trim to max_visits
    visits = visits[:max_visits]

    intervals = _intervals_minutes(visits)
    stats = _compute_stats(intervals)
    score = _rhythm_score(stats["std"], stats["mean"])
    gaps = _find_gaps(intervals, visits, gap_threshold_minutes)

    # visits[0] is newest, visits[-1] is oldest
    newest_ts = visits[0][0]
    oldest_ts = visits[-1][0]
    span_hours = (newest_ts - oldest_ts).total_seconds() / 3600.0

    return {
        "visits": len(visits),
        "mean_interval_minutes": stats["mean"],
        "median_interval_minutes": stats["median"],
        "std_interval_minutes": stats["std"],
        "min_interval_minutes": stats["min"],
        "max_interval_minutes": stats["max"],
        "rhythm_score": score,
        "gaps": gaps,
        "first_visit_at": oldest_ts.isoformat(),
        "last_visit_at": newest_ts.isoformat(),
        "span_hours": round(span_hours, 1),
    }


def rhythm_report(
    repo: Path | str,
    max_visits: int = 100,
    gap_threshold_minutes: float = 120.0,
) -> str:
    """One-line human-readable rhythm summary.

    Example: ``"98 visits over 4.1d — mean 62m, rhythm 0.70, 3 gaps"``
    """
    info = caretaker_rhythm(
        repo,
        max_visits=max_visits,
        gap_threshold_minutes=gap_threshold_minutes,
    )

    if info["visits"] == 0:
        return "no caretaker visits found"

    span = info["span_hours"]
    if span >= 24:
        span_str = f"{span / 24:.1f}d"
    else:
        span_str = f"{span:.1f}h"

    gap_count = len(info["gaps"])
    gap_str = f"{gap_count} gap{'s' if gap_count != 1 else ''}"

    return (
        f"{info['visits']} visits over {span_str} — "
        f"mean {info['mean_interval_minutes']:.0f}m, "
        f"rhythm {info['rhythm_score']:.2f}, "
        f"{gap_str}"
    )
