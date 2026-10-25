#!/usr/bin/env python3
"""CLI wrapper for iamai.commit_density — measure commit content density.

Reads recent git log output and scores each commit by how much real
change it carries (vs. timestamp bumps and counter increments).

Usage:
    python3 tools/commit_density.py              # last 50 commits
    python3 tools/commit_density.py -n 200       # last 200 commits
    python3 tools/commit_density.py --json        # machine-readable
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.commit_density import density_report, density_summary  # noqa: E402


def parse_git_log(n: int) -> list[dict]:
    """Parse `git log --numstat` into commit dicts."""
    result = subprocess.run(
        ["git", "log", f"--max-count={n}", "--pretty=format:COMMIT %h %aI",
         "--numstat"],
        capture_output=True, text=True, cwd=REPO,
    )
    commits = []
    current = None
    for line in result.stdout.splitlines():
        if line.startswith("COMMIT "):
            if current:
                commits.append(current)
            parts = line.split(" ", 2)
            current = {
                "hash": parts[1],
                "timestamp": parts[2] if len(parts) > 2 else "",
                "insertions": 0,
                "deletions": 0,
                "files": 0,
            }
        elif current and line.strip():
            cols = line.split("\t")
            if len(cols) >= 2 and cols[0] != "-":
                try:
                    ins = int(cols[0])
                    dels = int(cols[1])
                    current["insertions"] += ins
                    current["deletions"] += dels
                    current["files"] += 1
                except ValueError:
                    pass
    if current:
        commits.append(current)
    return commits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", "--count", type=int, default=50,
                    help="number of recent commits to analyse (default 50)")
    ap.add_argument("--json", action="store_true", dest="json_output",
                    help="emit JSON instead of text")
    args = ap.parse_args()

    commits = parse_git_log(args.count)
    report = density_report(commits)

    if args.json_output:
        # Strip per-commit details for brevity in JSON unless verbose
        summary = {k: v for k, v in report.items() if k != "commits"}
        print(json.dumps(summary, indent=2))
    else:
        print(density_summary(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
