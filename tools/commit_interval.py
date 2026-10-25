#!/usr/bin/env python3
"""CLI wrapper for iamai.commit_interval — measure commit regularity.

Reads git log timestamps and reports on how evenly spaced commits are.

Usage:
    python3 tools/commit_interval.py              # last 100 commits
    python3 tools/commit_interval.py -n 500       # last 500 commits
    python3 tools/commit_interval.py --json        # machine-readable
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

from iamai.commit_interval import interval_report, interval_summary  # noqa: E402


def parse_git_timestamps(n: int) -> list[datetime]:
    """Parse `git log --format=%aI` into datetime list."""
    result = subprocess.run(
        ["git", "log", f"--max-count={n}", "--format=%aI"],
        capture_output=True, text=True, cwd=REPO,
    )
    if result.returncode != 0:
        print(f"git log failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    return [datetime.fromisoformat(l) for l in lines]


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure commit interval regularity.")
    ap.add_argument("-n", type=int, default=100, help="Number of commits to analyze")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--burst-threshold", type=float, default=30.0,
                    help="Seconds below which two commits count as a burst (default 30)")
    args = ap.parse_args()

    timestamps = parse_git_timestamps(args.n)
    if not timestamps:
        print("No commits found.", file=sys.stderr)
        sys.exit(1)

    report = interval_report(timestamps, burst_threshold=args.burst_threshold)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(interval_summary(report))
        print()
        print(f"  commits analyzed : {report['count']}")
        print(f"  intervals        : {report['intervals']}")
        print(f"  mean interval    : {report['mean_interval']:.1f}s")
        print(f"  std deviation    : {report['std_interval']:.1f}s")
        print(f"  coeff of var     : {report['cv']:.3f}")
        print(f"  regularity score : {report['regularity']:.3f}")
        print(f"  health label     : {report['label']}")
        print(f"  longest gap      : {report['longest_gap']:.1f}s")
        print(f"  burst pairs      : {report['bursts']}")


if __name__ == "__main__":
    main()
