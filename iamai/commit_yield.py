"""Commit yield — what fraction of expected strokes survived into pushed commits?

``stroke_rate`` measures throughput (strokes per minute).
``push_health`` measures whether pushes succeed.
Neither answers the reliability question: *of the strokes the writer
should have produced in a given window, how many actually made it into
a pushed commit?*

This module computes that ratio — the **commit yield** — by comparing
the stroke count in ``data/strokes.jsonl`` against the theoretical
maximum implied by elapsed wall-clock time and the writer's configured
cadence.

Yield interpretation
--------------------

=======  ============================================================
range    meaning
=======  ============================================================
≥ 0.90   healthy — writer is keeping up and commits are flowing
0.70–0.89 degraded — some strokes lost to stalls or process deaths
0.50–0.69 poor — significant gaps, investigate stall logs
< 0.50   critical — writer is mostly idle or commits are blocked
=======  ============================================================

Formula::

    expected = elapsed_seconds / cadence_seconds
    actual   = strokes written in the window
    yield    = min(actual / expected, 1.0)   # capped at 1.0

The cap at 1.0 matters: after a burst catch-up the raw ratio can
briefly exceed unity, which would confuse trend analysis.

Design choices
--------------

- **Pure computation.**  Reads strokes.jsonl and git log; writes nothing.
- **Window-based.**  Analyses only the last ``window_minutes`` (default 60).
  Older data is irrelevant to "how is the system doing *right now*?"
- **Configurable cadence.**  Defaults to 15 s but respects whatever the
  writer is actually configured for.

Usage::

    from iamai.commit_yield import commit_yield, yield_report

    info = commit_yield(repo_root=".", cadence_seconds=15, window_minutes=60)
    print(info["yield"])        # 0.87
    print(info["actual"])       # 209
    print(info["expected"])     # 240.0

    print(yield_report(repo_root="."))
    # "yield 0.87 — 209/240 strokes in last 60 min"
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_strokes(strokes_path: Path, since: datetime) -> list[dict[str, Any]]:
    """Return strokes with timestamp >= *since*."""
    if not strokes_path.exists():
        return []
    results: list[dict[str, Any]] = []
    with open(strokes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            at_str = record.get("at", "")
            if not at_str:
                continue
            try:
                at = datetime.fromisoformat(at_str)
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if at >= since:
                results.append(record)
    return results


def _count_commits_in_window(
    repo_root: Path, since: datetime
) -> int:
    """Count git commits since a given time."""
    import subprocess

    since_iso = since.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"--since={since_iso}"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=10,
        )
        if result.returncode != 0:
            return 0
        lines = [ln for ln in result.stdout.strip().split("\n") if ln.strip()]
        return len(lines)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return 0


def commit_yield(
    repo_root: str | Path = ".",
    cadence_seconds: float = 15.0,
    window_minutes: float = 60.0,
) -> dict[str, Any]:
    """Compute the commit yield for the given window.

    Parameters
    ----------
    repo_root:
        Path to the repository root.
    cadence_seconds:
        Expected interval between strokes (seconds).  Default 15.
    window_minutes:
        How many minutes of history to analyse.  Default 60.

    Returns
    -------
    dict with keys: ``yield``, ``actual``, ``expected``,
    ``window_minutes``, ``cadence_seconds``, ``verdict``,
    ``commit_count``.
    """
    root = Path(repo_root).resolve()
    now = datetime.now(timezone.utc)
    since = datetime(
        now.year, now.month, now.day, now.hour, now.minute, now.second,
        tzinfo=timezone.utc,
    )
    # compute 'since' by subtracting window_minutes
    from datetime import timedelta

    since = now - timedelta(minutes=window_minutes)

    strokes_path = root / "data" / "strokes.jsonl"
    strokes = _parse_strokes(strokes_path, since)
    actual = len(strokes)

    elapsed = (now - since).total_seconds()
    expected = elapsed / cadence_seconds if cadence_seconds > 0 else 0.0

    if expected <= 0:
        raw_yield = 1.0
    else:
        raw_yield = min(actual / expected, 1.0)

    commit_count = _count_commits_in_window(root, since)

    verdict = _classify(raw_yield)

    return {
        "yield": round(raw_yield, 4),
        "actual": actual,
        "expected": round(expected, 1),
        "window_minutes": window_minutes,
        "cadence_seconds": cadence_seconds,
        "verdict": verdict,
        "commit_count": commit_count,
    }


def _classify(y: float) -> str:
    """Classify a yield ratio into a verdict string."""
    if y >= 0.90:
        return "healthy"
    if y >= 0.70:
        return "degraded"
    if y >= 0.50:
        return "poor"
    return "critical"


def yield_report(
    repo_root: str | Path = ".",
    cadence_seconds: float = 15.0,
    window_minutes: float = 60.0,
) -> str:
    """One-line human-readable yield summary."""
    info = commit_yield(repo_root, cadence_seconds, window_minutes)
    return (
        f"{info['verdict']} — yield {info['yield']:.2f} "
        f"({info['actual']}/{info['expected']:.0f} strokes "
        f"in last {info['window_minutes']:.0f} min, "
        f"{info['commit_count']} commits)"
    )
