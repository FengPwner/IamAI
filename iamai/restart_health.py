"""Restart health — measure whether a process restart actually fixed things.

After restarting the writer and batch committer, the caretaker needs to
know: did the restart work?  A successful restart shows strokes resuming
within one cadence period and the first batch commit landing within the
batch interval.  A failed restart shows the same silence gap continuing,
or the new process dying within minutes.

This module compares the cadence *before* the restart (the stalled gap
that triggered it) against the cadence *after* (the first few strokes
from the new process).  It produces a simple verdict:

- **healthy**: post-restart cadence is within 1.5x of target
- **recovering**: post-restart cadence is between 1.5x and 3x of target
  (the process is running but slow — might be catching up on backlog)
- **still_stalled**: post-restart cadence is still > 3x of target
  (the restart didn't fix the underlying issue)
- **dead**: no strokes at all after the restart timestamp

Public API
----------

``RestartReport``
    Dataclass: verdict (str), pre_gap (float), post_gap (float),
    target_gap (float), strokes_after (int), seconds_since_restart (float).

``assess(strokes_path, restart_ts, target_gap=15.0) -> RestartReport``
    Read the strokes log, find strokes before and after the restart
    timestamp, compute gaps, return the verdict.

``is_healthy(report) -> bool``
    Quick predicate: True when verdict is 'healthy'.

Design choices
--------------

- Uses wall-clock time from the strokes log (``ts`` field) rather than
  sequence numbers, because the writer may produce strokes out of order
  during catch-up.
- Requires at least 2 post-restart strokes to compute a gap.  If only
  one exists, the report says 'recovering' with a note.
- The target gap defaults to 15 seconds (the writer's configured cadence)
  but can be overridden for other writers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence


@dataclass(frozen=True)
class RestartReport:
    """Verdict on whether a restart fixed the stall."""

    verdict: str  # healthy | recovering | still_stalled | dead
    pre_gap: float  # seconds of silence before restart
    post_gap: float  # seconds between first two post-restart strokes
    target_gap: float  # expected cadence in seconds
    strokes_after: int  # total strokes produced after restart
    seconds_since_restart: float  # wall-clock seconds since restart_ts


# Thresholds as multiples of target_gap
_HEALTHY_MAX = 1.5
_RECOVERING_MAX = 3.0


def _load_strokes(strokes_path: Path) -> list[dict]:
    """Load all strokes from the JSONL file."""
    strokes = []
    if not strokes_path.exists():
        return strokes
    with open(strokes_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                strokes.append(json.loads(line))
    return strokes


def _parse_ts(ts_str: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a timezone-aware datetime."""
    # Handle both with and without timezone info
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return datetime.fromisoformat(ts_str)


def _stroke_ts(stroke: dict) -> datetime:
    """Extract the timestamp from a stroke record."""
    return _parse_ts(stroke["ts"])


def assess(
    strokes_path: str | Path,
    restart_ts: str | datetime,
    target_gap: float = 15.0,
) -> RestartReport:
    """Assess whether a restart fixed the writer stall.

    Parameters
    ----------
    strokes_path : path to ``data/strokes.jsonl``
    restart_ts : ISO 8601 string or datetime of the restart moment
    target_gap : expected seconds between strokes (default 15)

    Returns
    -------
    RestartReport with verdict and metrics.
    """
    if isinstance(restart_ts, str):
        restart_dt = _parse_ts(restart_ts)
    else:
        restart_dt = restart_ts

    if restart_dt.tzinfo is None:
        restart_dt = restart_dt.replace(tzinfo=timezone.utc)

    strokes = _load_strokes(Path(strokes_path))
    now = datetime.now(timezone.utc)
    seconds_since = (now - restart_dt).total_seconds()

    # Partition strokes into pre- and post-restart
    pre_strokes: list[dict] = []
    post_strokes: list[dict] = []
    for s in strokes:
        try:
            t = _stroke_ts(s)
        except (KeyError, ValueError):
            continue
        if t < restart_dt:
            pre_strokes.append(s)
        else:
            post_strokes.append(s)

    # Compute pre-restart gap (the stall that triggered restart)
    pre_gap = 0.0
    if len(pre_strokes) >= 2:
        t_last = _stroke_ts(pre_strokes[-1])
        t_prev = _stroke_ts(pre_strokes[-2])
        pre_gap = (t_last - t_prev).total_seconds()
    elif len(pre_strokes) == 1:
        pre_gap = (restart_dt - _stroke_ts(pre_strokes[-1])).total_seconds()

    # No strokes after restart at all
    if not post_strokes:
        return RestartReport(
            verdict="dead",
            pre_gap=pre_gap,
            post_gap=float("inf"),
            target_gap=target_gap,
            strokes_after=0,
            seconds_since_restart=seconds_since,
        )

    # Only one stroke after restart — can't compute a gap
    if len(post_strokes) == 1:
        return RestartReport(
            verdict="recovering",
            pre_gap=pre_gap,
            post_gap=float("inf"),
            target_gap=target_gap,
            strokes_after=1,
            seconds_since_restart=seconds_since,
        )

    # Compute post-restart gap from first two post-restart strokes
    t_first = _stroke_ts(post_strokes[0])
    t_second = _stroke_ts(post_strokes[1])
    post_gap = (t_second - t_first).total_seconds()

    # Classify
    ratio = post_gap / target_gap if target_gap > 0 else float("inf")
    if ratio <= _HEALTHY_MAX:
        verdict = "healthy"
    elif ratio <= _RECOVERING_MAX:
        verdict = "recovering"
    else:
        verdict = "still_stalled"

    return RestartReport(
        verdict=verdict,
        pre_gap=pre_gap,
        post_gap=post_gap,
        target_gap=target_gap,
        strokes_after=len(post_strokes),
        seconds_since_restart=seconds_since,
    )


def is_healthy(report: RestartReport) -> bool:
    """True when the restart produced a healthy writer."""
    return report.verdict == "healthy"


def format_report(report: RestartReport) -> str:
    """Human-readable one-liner for logs and visit notes."""
    return (
        f"restart {report.verdict}: "
        f"pre_gap={report.pre_gap:.0f}s  post_gap={report.post_gap:.0f}s  "
        f"target={report.target_gap:.0f}s  "
        f"strokes_after={report.strokes_after}  "
        f"uptime={report.seconds_since_restart:.0f}s"
    )
