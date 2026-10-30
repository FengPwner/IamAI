#!/usr/bin/env python3
"""CLI wrapper for iamai.file_fatigue — detect over-edited files.

Usage:
    python3 tools/file_fatigue.py                # full analysis
    python3 tools/file_fatigue.py --top 20       # show top 20 hotspots
    python3 tools/file_fatigue.py --json          # JSON output

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

from iamai.file_fatigue import analyse_fatigue, parse_git_numstat


def _run_git_numstat() -> list[str]:
    """Run git log --numstat and return stdout lines."""
    proc = subprocess.run(
        ["git", "log", "--numstat", "--pretty=format:commit %H"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    if proc.returncode != 0:
        print(f"git log failed: {proc.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return proc.stdout.splitlines()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect over-edited (fatigued) files in the repo."
    )
    parser.add_argument(
        "--top", type=int, default=10,
        help="Number of top hotspots to show (default: 10)."
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Output as JSON."
    )
    args = parser.parse_args()

    lines = _run_git_numstat()
    edit_counts = parse_git_numstat(lines)
    result = analyse_fatigue(edit_counts, top_n=args.top)

    if args.as_json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"=== File Fatigue Report ===")
    print(f"Files: {result['total_files']}  |  "
          f"Total edits: {result['total_edits']}  |  "
          f"Median: {result['median_edits']}  |  "
          f"Max: {result['max_edits']}")
    print(f"Fatigue index: {result['index']}  |  "
          f"State: {result['state']}")
    print()

    bd = result["band_distribution"]
    print("Band distribution:")
    for band in ("fresh", "warm", "hot", "exhausted", "critical"):
        count = bd.get(band, 0)
        if count > 0:
            print(f"  {band:12s}  {count}")
    print()

    print(f"Top {args.top} hotspots:")
    for h in result["hotspots"]:
        print(f"  {h['band']:12s}  score={h['score']:6.2f}  "
              f"edits={h['edits']:5d}  {h['file']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
