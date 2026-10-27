#!/usr/bin/env python3
"""CLI: restart_latency — measure recovery time after process restarts.

Usage:
    python3 tools/restart_latency.py
    python3 tools/restart_latency.py --count 50
    python3 tools/restart_latency.py --json

Exit codes:
    0  healthy or degraded — recovery is fast
    1  slow — recovery takes 15–30 minutes
    2  critical or broken — recovery takes over 30 minutes
    3  no restart events found
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.restart_latency import latency_report  # noqa: E402

_EXIT_MAP = {
    "healthy": 0, "degraded": 0,
    "slow": 1,
    "critical": 2, "broken": 2,
}


def _read_git_log(count: int) -> list[str]:
    """Read the last N commits from git log."""
    result = subprocess.run(
        ["git", "log", f"--format=%h %ai %s", f"-{count}"],
        capture_output=True, text=True,
        cwd=str(REPO),
    )
    if result.returncode != 0:
        print(f"git log failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(3)
    return result.stdout.strip().splitlines()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure recovery latency after process restarts."
    )
    parser.add_argument(
        "--count", "-n", type=int, default=200,
        help="number of recent commits to scan (default: 200)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="output as JSON"
    )
    args = parser.parse_args()

    lines = _read_git_log(args.count)
    report = latency_report(lines)
    summary = report["summary"]

    if summary["count"] == 0:
        print("no restart events found in the scanned commits.")
        return 3

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"restart latency report (scanned {args.count} commits)")
        print(f"{'='*55}")
        print(f"  restart-recovery pairs found:  {summary['count']}")
        print(f"  mean latency:                {summary['mean_latency']}s")
        print(f"  median latency:              {summary['median_latency']}s")
        print(f"  min / max:                   {summary['min_latency']}s / {summary['max_latency']}s")
        print(f"  health score:                {summary['health_score']}/100")
        print()
        print("  band distribution:")
        for band in ("healthy", "degraded", "slow", "critical", "broken"):
            n = summary["band_distribution"].get(band, 0)
            if n > 0:
                print(f"    {band:12s}  {n}")
        print()
        print("  recent restart-recovery pairs:")
        for pair in report["pairs"][:10]:
            print(
                f"    {pair['restart_hash']} → {pair['recovery_hash']}  "
                f"{pair['latency_seconds']:.0f}s ({pair['band']})"
            )

    # determine exit code from overall health
    dominant = max(
        summary["band_distribution"],
        key=lambda b: summary["band_distribution"][b],
        default="healthy",
    )
    return _EXIT_MAP.get(dominant, 0)


if __name__ == "__main__":
    sys.exit(main())
