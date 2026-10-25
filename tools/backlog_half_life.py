#!/usr/bin/env python3
"""CLI: backlog_half_life — measure how quickly the repo drains its backlog.

Usage:
    python3 tools/backlog_half_life.py                    # summary
    python3 tools/backlog_half_life.py --interval 300     # custom batch interval
    python3 tools/backlog_half_life.py --json             # machine-readable

Exit codes:
    0  draining
    1  stagnant
    2  accumulating
    3  no data
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.backlog_half_life import (  # noqa: E402
    BacklogReport,
    compute_half_life,
    report_summary,
)

_VERDICT_EXIT = {"draining": 0, "stagnant": 1, "accumulating": 2, "unknown": 3}


def _git_status_pending() -> list[str]:
    """Return list of uncommitted file paths from git status."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(REPO),
        )
        files = []
        for line in result.stdout.strip().splitlines():
            if len(line) >= 3:
                files.append(line[3:].strip())
        return files
    except Exception:
        return []


def _get_last_commit_time() -> datetime | None:
    """Return timestamp of the most recent commit."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%aI"],
            capture_output=True, text=True, cwd=str(REPO),
        )
        if result.returncode == 0 and result.stdout.strip():
            raw = result.stdout.strip()
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            return datetime.fromisoformat(raw)
    except Exception:
        pass
    return None


def _get_pending_file_ages() -> list[tuple[datetime, None]]:
    """Estimate when each pending file was last modified."""
    now = datetime.now(timezone.utc)
    files = _git_status_pending()
    events = []
    for f in files:
        path = REPO / f
        if path.exists():
            mtime = path.stat().st_mtime
            appeared = datetime.fromtimestamp(mtime, tz=timezone.utc)
        else:
            appeared = now
        events.append((appeared, None))
    return events


def _get_recent_commit_intervals(n: int = 10) -> list[tuple[datetime, datetime]]:
    """Get recent commit intervals from git log."""
    try:
        result = subprocess.run(
            ["git", "log", f"-{n}", "--format=%aI", "--reverse"],
            capture_output=True, text=True, cwd=str(REPO),
        )
        if result.returncode != 0:
            return []
        lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
        events = []
        for line in lines:
            if line.endswith("Z"):
                line = line[:-1] + "+00:00"
            dt = datetime.fromisoformat(line)
            events.append(dt)
        # Pair consecutive commits as (appeared, resolved)
        pairs = []
        for i in range(len(events) - 1):
            pairs.append((events[i], events[i + 1]))
        return pairs
    except Exception:
        return []


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure backlog drainage speed.")
    ap.add_argument("--interval", type=float, default=600.0,
                     help="Batch commit interval in seconds (default: 600)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    # Build events from recent commit history + current pending files
    history_events = _get_recent_commit_intervals(20)
    pending_events = _get_pending_file_ages()
    all_events = history_events + pending_events

    if not all_events:
        if args.json:
            print(json.dumps({"error": "no data", "verdict": "unknown"}))
        else:
            print("no backlog data available")
        return 3

    report = compute_half_life(all_events, batch_interval=args.interval)

    if args.json:
        data = {
            "total_files": report.total_files,
            "resolved": report.resolved,
            "pending": report.pending,
            "median_residence": round(report.median_residence, 1),
            "max_residence": round(report.max_residence, 1),
            "half_life": round(report.half_life, 1) if report.half_life else None,
            "drain_rate_per_min": round(report.drain_rate_per_min, 3),
            "verdict": report.verdict,
        }
        print(json.dumps(data, indent=2))
    else:
        print(report_summary(report))

    return _VERDICT_EXIT.get(report.verdict, 3)


if __name__ == "__main__":
    sys.exit(main())
