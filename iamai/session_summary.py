"""Session summary — what happened during a caretaker visit?

A caretaker visit is a bounded window: arrival to departure.  This module
answers *what happened in that window* by examining git log, strokes.jsonl,
and the writer state file.

Verdicts
========

===========  ===============================================
verdict      meaning
===========  ===============================================
``productive``  ≥ 3 strokes and ≥ 1 commit during the visit
``quiet``       1–2 strokes, no commits — writer alive but slow
``idle``        0 strokes — writer stalled or paused
``empty``       no visit boundary found (no start marker)
===========  ===============================================

Usage::

    from iamai.session_summary import summarise, report_line

    info = summarise(repo, visit_start_iso="2026-10-21T12:00:00+00:00")
    print(info["verdict"])       # "productive"
    print(info["strokes"])       # 12
    print(info["commits"])       # 2

    print(report_line(info))
    # "productive — 12 strokes, 2 commits, 847s elapsed"
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


_VERDICTS = [
    ("productive", 3, 1),   # min strokes, min commits
    ("quiet",      1, 0),
    ("idle",       0, 0),
]


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware datetime."""
    # Handle both +00:00 and Z suffixes
    ts = ts.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def _count_strokes_since(strokes_path: Path, since: datetime) -> int:
    """Count strokes written after *since*."""
    if not strokes_path.exists():
        return 0
    count = 0
    with open(strokes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                at_str = rec.get("at", "")
                if at_str:
                    at_dt = _parse_iso(at_str)
                    if at_dt >= since:
                        count += 1
            except (json.JSONDecodeError, ValueError, KeyError):
                continue
    return count


def _count_commits_since(repo: Path, since: datetime) -> int:
    """Count git commits after *since* using git log."""
    since_iso = since.isoformat()
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"--since={since_iso}"],
            capture_output=True,
            text=True,
            cwd=str(repo),
            timeout=10,
        )
        if result.returncode != 0:
            return 0
        lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        return len(lines)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0


def _elapsed_seconds(since: datetime, now: datetime | None = None) -> float:
    """Seconds between *since* and *now* (default: utcnow)."""
    if now is None:
        now = datetime.now(timezone.utc)
    return max(0.0, (now - since).total_seconds())


def _classify(strokes: int, commits: int) -> str:
    """Determine the session verdict."""
    for verdict, min_strokes, min_commits in _VERDICTS:
        if strokes >= min_strokes and commits >= min_commits:
            return verdict
    return "idle"


def summarise(
    repo: Path | str,
    visit_start_iso: str | None = None,
    now: datetime | None = None,
    writer: str = "qwen",
) -> dict:
    """Build a session summary dict.

    Parameters
    ----------
    repo : path to the repo root
    visit_start_iso : ISO-8601 timestamp of visit start.
        If None, falls back to the writer state's ``last_visit`` field,
        or 30 minutes ago if that's also unavailable.
    now : override current time (for testing)
    writer : writer id for state file lookup
    """
    repo = Path(repo)
    if now is None:
        now = datetime.now(timezone.utc)

    # Resolve visit start
    if visit_start_iso:
        since = _parse_iso(visit_start_iso)
    else:
        # Try writer state file
        state_path = repo / "data" / f"writer_state.{writer}.json"
        since = None
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                last_visit = state.get("last_visit") or state.get("started_at")
                if last_visit:
                    since = _parse_iso(last_visit)
            except (json.JSONDecodeError, ValueError):
                pass
        if since is None:
            # Default: 30 minutes ago
            from datetime import timedelta
            since = now - timedelta(minutes=30)

    strokes_path = repo / "data" / "strokes.jsonl"
    strokes = _count_strokes_since(strokes_path, since)
    commits = _count_commits_since(repo, since)
    elapsed = _elapsed_seconds(since, now)
    verdict = _classify(strokes, commits)

    return {
        "verdict": verdict,
        "strokes": strokes,
        "commits": commits,
        "elapsed_seconds": round(elapsed, 1),
        "visit_start": since.isoformat(),
        "visit_end": now.isoformat(),
        "writer": writer,
    }


def report_line(info: dict) -> str:
    """One-line human-readable summary."""
    v = info["verdict"]
    s = info["strokes"]
    c = info["commits"]
    e = int(info["elapsed_seconds"])
    return f"{v} — {s} strokes, {c} commits, {e}s elapsed"
