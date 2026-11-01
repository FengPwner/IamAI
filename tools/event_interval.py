#!/usr/bin/env python3
"""CLI: event_interval — interval statistics for git commit timestamps.

reads commit timestamps from `git log` and reports how regular the
commit cadence is. useful for detecting stalls, bursts, and drift
in automated writing pipelines.

usage:
    python3 tools/event_interval.py                  # all commits
    python3 tools/event_interval.py --last 100       # last 100 commits
    python3 tools/event_interval.py --since "7 days ago"
    python3 tools/event_interval.py --json

exit codes:
    0 — success
    1 — not enough data (< 2 commits in range)
    2 — git error
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.event_interval import compute_intervals, classify_rhythm  # noqa: E402


def get_commit_timestamps(
    last_n: int | None = None,
    since: str | None = None,
) -> list[datetime]:
    """parse ISO timestamps from git log."""
    cmd = ["git", "log", "--format=%aI"]
    if last_n:
        cmd.append(f"-{last_n}")
    if since:
        cmd.append(f"--since={since}")
    cmd.append("main")

    result = subprocess.run(
        cmd, cwd=str(REPO), capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"git error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)

    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    # git log returns newest first; reverse for chronological order
    lines.reverse()
    return [datetime.fromisoformat(l) for l in lines]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="interval statistics for git commit timestamps",
    )
    parser.add_argument("--last", type=int, default=None,
                        help="only consider the last N commits")
    parser.add_argument("--since", type=str, default=None,
                        help='git --since filter, e.g. "7 days ago"')
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="output JSON")
    args = parser.parse_args()

    timestamps = get_commit_timestamps(last_n=args.last, since=args.since)

    if len(timestamps) < 2:
        msg = f"need ≥ 2 commits, found {len(timestamps)}"
        if args.as_json:
            print(json.dumps({"error": msg}))
        else:
            print(msg, file=sys.stderr)
        return 1

    stats = compute_intervals(timestamps)
    rhythm = classify_rhythm(stats.cv)

    if args.as_json:
        out = stats.to_dict()
        out["rhythm"] = rhythm
        print(json.dumps(out, indent=2))
    else:
        print(f"commits:  {stats.count}")
        print(f"intervals: {len(stats.intervals)}")
        print(f"min:      {stats.min_s:.1f}s")
        print(f"max:      {stats.max_s:.1f}s")
        print(f"mean:     {stats.mean_s:.1f}s")
        print(f"median:   {stats.median_s:.1f}s")
        print(f"p95:      {stats.p95_s:.1f}s")
        print(f"p99:      {stats.p99_s:.1f}s")
        print(f"cv:       {stats.cv:.4f}")
        print(f"rhythm:   {rhythm}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
