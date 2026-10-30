#!/usr/bin/env python3
"""CLI: caretaker_overhead_ratio — measure maintenance vs substantive work.

Usage:
    python3 tools/caretaker_overhead_ratio.py
    python3 tools/caretaker_overhead_ratio.py --count 50
    python3 tools/caretaker_overhead_ratio.py --json

Exit codes:
    0  lean (ratio < 0.20)
    1  moderate (ratio 0.20–0.39)
    2  heavy (ratio 0.40–0.59)
    3  critical (ratio >= 0.60)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.caretaker_overhead_ratio import overhead_report  # noqa: E402


def _recent_messages(count: int = 30) -> list[str]:
    """Get the most recent commit messages from git log."""
    try:
        out = subprocess.check_output(
            ["git", "log", "--format=%s", f"-{count}"],
            cwd=REPO, stderr=subprocess.DEVNULL, text=True,
        )
        return [line.strip() for line in out.strip().splitlines() if line.strip()]
    except Exception as e:
        print(f"error reading git log: {e}", file=sys.stderr)
        sys.exit(4)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure caretaker overhead ratio in recent commits."
    )
    parser.add_argument(
        "--count", "-n", type=int, default=30,
        help="number of recent commits to analyse (default: 30)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="output as JSON"
    )
    args = parser.parse_args()

    messages = _recent_messages(args.count)
    if not messages:
        print("no commits found", file=sys.stderr)
        return 4

    report = overhead_report(messages)

    if args.json:
        # strip breakdown (too verbose for CLI JSON)
        out = {k: v for k, v in report.items() if k != "breakdown"}
        print(json.dumps(out, indent=2))
    else:
        print(f"caretaker overhead ratio — last {report['total']} commits")
        print(f"  substantive: {report['substantive']}")
        print(f"  overhead:    {report['overhead']}")
        print(f"  hybrid:      {report['hybrid']}")
        print(f"  ratio:       {report['ratio']:.2f}")
        print(f"  band:        {report['band']}")
        print(f"  → {report['summary']}")

    # exit code by band
    band_exit = {"lean": 0, "moderate": 1, "heavy": 2, "critical": 3}
    return band_exit.get(report["band"], 3)


if __name__ == "__main__":
    sys.exit(main())
