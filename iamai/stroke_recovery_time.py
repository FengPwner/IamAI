"""Measure writer recovery speed after process restarts.

When the writer loop crashes and a caretaker restarts it, how long
before the first new stroke lands?  This module answers that question
by pairing restart commits with the next stroke timestamp.

Recovery time is a direct measure of caretaker effectiveness:
- **fast** (< 60s): the caretaker loop caught the stall and restarted quickly
- **normal** (60-300s): typical human-noticeed or hourly catch-up restart
- **slow** (> 300s): extended gap, possibly overnight or no caretaker on duty

Usage::

    from iamai.stroke_recovery_time import recovery_times, recovery_summary

    times = recovery_times()
    # [{"restart_at": "...", "first_stroke_at": "...", "gap_seconds": 42, ...}, ...]

    print(recovery_summary())
    # "12 restarts: median 45s, max 312s, 11/12 under 5min"
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO_ROOT / "data" / "strokes.jsonl"

RESTART_MARKERS = [
    "catch-up: hourly caretaker restart",
    "caretaker visit",
    "catch-up: commit pending changes before process restart",
]


def _git_log_restarts(max_count: int = 200) -> list[dict[str, str]]:
    """Find restart-related commits from git log."""
    try:
        raw = subprocess.run(
            [
                "git", "log",
                f"--max-count={max_count}",
                "--format=%H|%aI|%s",
            ],
            capture_output=True, text=True, cwd=REPO_ROOT,
        ).stdout.strip()
    except Exception:
        return []

    restarts = []
    for line in raw.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        sha, ts, subject = parts
        if any(marker in subject for marker in RESTART_MARKERS):
            restarts.append({"sha": sha, "at": ts, "subject": subject})
    return restarts


def _load_strokes(limit: int = 5000) -> list[dict[str, Any]]:
    """Load recent strokes from JSONL."""
    if not STROKES_FILE.exists():
        return []
    strokes = []
    for line in STROKES_FILE.read_text().strip().splitlines()[-limit:]:
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp to datetime."""
    ts_str = ts_str.strip()
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return datetime.fromisoformat(ts_str).astimezone(timezone.utc)


def classify_recovery(gap_seconds: float) -> str:
    """Classify recovery speed.

    Args:
        gap_seconds: seconds between restart commit and first new stroke

    Returns:
        One of: "fast", "normal", "slow", "stalled"

    Examples:
        >>> classify_recovery(30)
        'fast'
        >>> classify_recovery(120)
        'normal'
        >>> classify_recovery(600)
        'slow'
        >>> classify_recovery(-1)
        'stalled'
    """
    if gap_seconds < 0:
        return "stalled"
    if gap_seconds < 60:
        return "fast"
    if gap_seconds < 300:
        return "normal"
    return "slow"


def recovery_times(max_commits: int = 200) -> list[dict[str, Any]]:
    """Compute recovery time for each restart event.

    Returns a list of dicts with keys:
    - restart_sha, restart_at, restart_subject
    - first_stroke_at, gap_seconds, classification
    """
    restarts = _git_log_restarts(max_count=max_commits)
    strokes = _load_strokes()

    if not restarts or not strokes:
        return []

    stroke_times = sorted(
        [_parse_ts(s["at"]) for s in strokes if "at" in s]
    )

    results = []
    for r in restarts:
        restart_dt = _parse_ts(r["at"])
        # Find the first stroke strictly after this restart
        next_stroke = None
        for st in stroke_times:
            if st > restart_dt:
                next_stroke = st
                break

        if next_stroke is None:
            gap = -1
            first_at = None
        else:
            gap = (next_stroke - restart_dt).total_seconds()
            first_at = next_stroke.isoformat()

        results.append({
            "restart_sha": r["sha"][:7],
            "restart_at": r["at"],
            "restart_subject": r["subject"][:80],
            "first_stroke_at": first_at,
            "gap_seconds": round(gap, 1),
            "classification": classify_recovery(gap),
        })

    return results


def recovery_summary(max_commits: int = 200) -> str:
    """One-line summary of recovery performance.

    Returns:
        Human-readable summary string.

    Example:
        >>> s = recovery_summary()
        >>> "restarts" in s
        True
    """
    times = recovery_times(max_commits=max_commits)
    if not times:
        return "no restart events found"

    gaps = [t["gap_seconds"] for t in times if t["gap_seconds"] >= 0]
    if not gaps:
        return f"{len(times)} restarts, all stalled (no subsequent strokes)"

    gaps_sorted = sorted(gaps)
    median = gaps_sorted[len(gaps_sorted) // 2]
    max_gap = max(gaps)
    under_5min = sum(1 for g in gaps if g < 300)
    stalled = len(times) - len(gaps)

    parts = [
        f"{len(times)} restarts",
        f"median {median:.0f}s",
        f"max {max_gap:.0f}s",
        f"{under_5min}/{len(times)} under 5min",
    ]
    if stalled:
        parts.append(f"{stalled} stalled")

    return ", ".join(parts)
