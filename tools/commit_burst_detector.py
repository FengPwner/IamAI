#!/usr/bin/env python3
"""CLI wrapper for iamai.commit_burst_detector — are commits arriving in bursts?

Reads the git log, computes inter-commit gaps, and detects burst patterns:

    quiet    zero bursts in the observation window
    steady   1-2 bursts, short and healthy
    surging  3+ bursts or a burst longer than --long-burst
    panic    any burst with mean gap < --panic-gap (likely retry loop)

Usage:
    python3 tools/commit_burst_detector.py                  # human-readable
    python3 tools/commit_burst_detector.py --json           # machine-readable
    python3 tools/commit_burst_detector.py --window 50      # last 50 commits
    python3 tools/commit_burst_detector.py --threshold 60   # 60s burst threshold

Exit codes:
    0  quiet or steady — healthy commit rhythm
    1  surging or panic — caretaker should investigate
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

from iamai.commit_burst_detector import (  # noqa: E402
    DEFAULT_BURST_THRESHOLD,
    DEFAULT_LONG_BURST,
    DEFAULT_PANIC_MEAN_GAP,
    burst_summary,
    burst_verdict,
    detect_bursts,
)


def _commit_timestamps(n: int) -> list[datetime]:
    """Return the last `n` commit timestamps from git log (newest first)."""
    result = subprocess.run(
        ["git", "log", "--format=%aI", f"-{n}"],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=15,
    )
    if result.returncode != 0:
        return []
    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    timestamps = []
    for line in lines:
        try:
            timestamps.append(datetime.fromisoformat(line))
        except ValueError:
            continue
    return timestamps


def _gaps_from_timestamps(timestamps: list[datetime]) -> list[float]:
    """Compute inter-commit gaps in seconds from a newest-first timestamp list.

    Returns gaps oldest-first (as detect_bursts expects).
    """
    if len(timestamps) < 2:
        return []
    # timestamps are newest-first; reverse to oldest-first for gap computation
    ts_oldest_first = list(reversed(timestamps))
    gaps = []
    for i in range(1, len(ts_oldest_first)):
        gap = (ts_oldest_first[i] - ts_oldest_first[i - 1]).total_seconds()
        gaps.append(abs(gap))  # abs to handle clock skew
    return gaps


def _burst_to_dict(burst) -> dict:
    """Serialise a Burst dataclass to a JSON-friendly dict."""
    return {
        "start_index": burst.start_index,
        "length": burst.length,
        "duration_seconds": round(burst.duration, 1),
        "mean_gap_seconds": round(burst.mean_gap, 2),
    }


def _human_line(summary: dict, window: int) -> str:
    """Format a single human-readable summary line."""
    v = summary["verdict"]
    count = summary["count"]
    longest = summary["longest"]
    total = summary["total_burst_commits"]
    line = f"{v}: {count} burst(s) in last {window} commits"
    if count > 0:
        line += f", longest={longest} commits, {total} total burst commits"
    return line


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--window",
        type=int,
        default=100,
        help="number of recent commits to analyse (default 100)",
    )
    ap.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_BURST_THRESHOLD,
        help=f"seconds between commits to count as burst (default {DEFAULT_BURST_THRESHOLD})",
    )
    ap.add_argument(
        "--long-burst",
        type=int,
        default=DEFAULT_LONG_BURST,
        help=f"burst length that triggers 'surging' (default {DEFAULT_LONG_BURST})",
    )
    ap.add_argument(
        "--panic-gap",
        type=float,
        default=DEFAULT_PANIC_MEAN_GAP,
        help=f"mean gap below which a burst is 'panic' (default {DEFAULT_PANIC_MEAN_GAP})",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit JSON instead of a human-readable line",
    )
    args = ap.parse_args()

    timestamps = _commit_timestamps(args.window)
    gaps = _gaps_from_timestamps(timestamps)
    summary = burst_summary(gaps, burst_threshold=args.threshold)

    # Override verdict with custom thresholds if provided
    if summary["bursts"]:
        verdict = burst_verdict(
            summary["bursts"],
            long_burst=args.long_burst,
            panic_mean_gap=args.panic_gap,
        )
        summary["verdict"] = verdict

    if args.json_output:
        out = {
            "verdict": summary["verdict"],
            "count": summary["count"],
            "longest": summary["longest"],
            "total_burst_commits": summary["total_burst_commits"],
            "bursts": [_burst_to_dict(b) for b in summary["bursts"]],
            "window": args.window,
            "threshold_seconds": args.threshold,
            "commits_analysed": len(timestamps),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(_human_line(summary, args.window))

    return 0 if summary["verdict"] in ("quiet", "steady") else 1


if __name__ == "__main__":
    sys.exit(main())
