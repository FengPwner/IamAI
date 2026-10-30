#!/usr/bin/env python3
"""CLI: commit_churn_index — detect writer rewrite loops.

Usage:
    python3 tools/commit_churn_index.py
    python3 tools/commit_churn_index.py --json
    python3 tools/commit_churn_index.py --count 20

Exit codes:
    0  healthy (score < 30)
    1  churning (score 30–59)
    2  stalled (score >= 60)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.commit_churn import churn_index  # noqa: E402


_EXIT_CODES = {"healthy": 0, "churning": 1, "stalled": 2}


def _git_recent_commits(count: int) -> list[dict]:
    """parse the last N commits into dicts with files/ins/del."""
    try:
        log_out = subprocess.check_output(
            ["git", "log", f"--max-count={count}",
             "--format=%H", "--reverse"],
            cwd=REPO, stderr=subprocess.DEVNULL, text=True,
        )
    except subprocess.CalledProcessError:
        return []

    hashes = [h for h in log_out.strip().splitlines() if h]
    commits = []

    for h in hashes:
        # get numstat for this commit
        try:
            stat_out = subprocess.check_output(
                ["git", "diff-tree", "--numstat", "-r", h],
                cwd=REPO, stderr=subprocess.DEVNULL, text=True,
            )
        except subprocess.CalledProcessError:
            continue

        files = set()
        ins = 0
        dels = 0
        for line in stat_out.strip().splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            added, removed, filepath = parts[0], parts[1], parts[2]
            # skip binary files (shown as '-')
            if added == "-" or removed == "-":
                files.add(filepath)
                continue
            files.add(filepath)
            ins += int(added)
            dels += int(removed)

        commits.append({
            "files": files,
            "insertions": ins,
            "deletions": dels,
            "hash": h[:8],
        })

    return commits


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute commit churn index."
    )
    parser.add_argument(
        "--count", type=int, default=30,
        help="Number of recent commits to analyse (default: 30).",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Output JSON instead of human text.",
    )
    args = parser.parse_args()

    commits = _git_recent_commits(args.count)
    result = churn_index(commits)

    if args.as_json:
        # serialise sets for JSON
        output = dict(result)
        print(json.dumps(output, indent=2, default=str))
    else:
        print(
            f"commit churn index: {result['score']}/100  "
            f"[{result['band'].upper()}]"
        )
        print(f"  commits analysed: {len(commits)}")
        print(f"  summary: {result['summary']}")
        if commits and result["per_commit"]:
            # show last 5 per-commit scores
            tail = min(5, len(result["per_commit"]))
            print(f"  last {tail} commit scores:")
            for i, s in enumerate(result["per_commit"][-tail:]):
                h = commits[-(tail - i)]["hash"] if i < len(commits) else "?"
                print(f"    {h}: {s:.2f}")

    return _EXIT_CODES.get(result["band"], 0)


if __name__ == "__main__":
    raise SystemExit(main())
