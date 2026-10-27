#!/usr/bin/env python3
"""commit_attention_map — CLI wrapper for repo attention analysis.

Reads the most recent commits from the local git repo and classifies
what the repository is paying attention to.

Usage:
    python3 tools/commit_attention_map.py
    python3 tools/commit_attention_map.py --commits 50
    python3 tools/commit_attention_map.py --json

Exit codes:
    0 — analysis complete
    2 — unexpected error
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.commit_attention_map import attention_report  # noqa: E402


def get_recent_file_lists(n: int = 20) -> list[list[str]]:
    """Parse ``git log --name-only`` into per-commit file lists."""
    try:
        out = subprocess.check_output(
            ["git", "log", "--name-only", f"--max-count={n}",
             "--pretty=format:"],
            cwd=REPO,
            text=True,
            timeout=15,
        )
    except subprocess.CalledProcessError as exc:
        print(f"git error: {exc}", file=sys.stderr)
        return []

    file_lists: list[list[str]] = []
    current: list[str] = []
    for line in out.splitlines():
        stripped = line.strip()
        if stripped == "" and current:
            file_lists.append(current)
            current = []
        elif stripped:
            current.append(stripped)
    if current:
        file_lists.append(current)
    return file_lists


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyse repo attention focus from recent commits.",
    )
    parser.add_argument(
        "--commits", "-n", type=int, default=20,
        help="Number of recent commits to analyse (default: 20)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON instead of human-readable text",
    )
    args = parser.parse_args()

    file_lists = get_recent_file_lists(args.commits)
    if not file_lists:
        print("no commits found", file=sys.stderr)
        return 2

    report = attention_report(file_lists, window=args.commits)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"attention focus report — {report['sample_size']} commits")
        print(f"{'=' * 50}")
        print(f"focus entropy : {report['focus']:.4f}")
        print(f"band          : {report['band']}")
        print(f"dominant      : {report['dominant']} "
              f"({report['dominant_share']}%)")
        print()
        print("category distribution:")
        for cat, count in sorted(
            report["distribution"].items(),
            key=lambda x: -x[1],
        ):
            print(f"  {cat:<12} {count:>5}")
        print()
        print(f"recommendation: {report['recommendation']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
