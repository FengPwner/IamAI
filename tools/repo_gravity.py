#!/usr/bin/env python3
"""repo_gravity CLI — quick check of file-change concentration.

Usage:
    python3 tools/repo_gravity.py              # analyse current repo
    python3 tools/repo_gravity.py --top 20     # show top 20 attractors
    git log --name-only | python3 tools/repo_gravity.py  # pipe mode
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.repo_gravity import gravity_report, parse_commit_file_counts


def _get_git_log() -> str:
    """Run git log and return raw output."""
    result = subprocess.run(
        ["git", "log", "--name-only", "--pretty=format:"],
        capture_output=True, text=True, timeout=30,
        cwd=str(REPO),
    )
    if result.returncode != 0:
        print(f"git log failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def main() -> None:
    top_n = 10
    if "--top" in sys.argv:
        idx = sys.argv.index("--top")
        if idx + 1 < len(sys.argv):
            top_n = int(sys.argv[idx + 1])

    # try stdin first (pipe mode), fall back to running git log
    if not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        text = _get_git_log()

    counts = parse_commit_file_counts(text)
    if not counts:
        print("no commit data found")
        sys.exit(0)

    report = gravity_report(counts, n=top_n)
    print(report["summary"])
    print()
    print("Top attractors:")
    for a in report["top_attractors"]:
        print(f"  {a['path']:50s}  {a['commits']:4d} commits  ({a['share']:.1%})")


if __name__ == "__main__":
    main()
