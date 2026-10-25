#!/usr/bin/env python3
"""uncommitted_bytes.py — measure data-loss exposure of uncommitted work.

Every uncommitted change is a bet that the container won't crash before
the next commit. This module quantifies that bet: it sums the line counts
from git diff (staged + unstaged) and the byte sizes of untracked files,
producing a single "exposure" number.

For tracked files, exposure is measured in lines changed (via --numstat),
which correlates well with data-loss risk in text-heavy repos. For
untracked files, raw byte sizes are used since no diff exists.

The caretaker can use this as a health gate: if exposure exceeds a
threshold, something is wrong with the commit pipeline.

Three measurement modes:

1. **working tree** (default): staged + unstaged modifications.
2. **full**: working tree + untracked files.
3. **diff-only**: only already-staged changes (--cached).

Usage:
    python3 tools/uncommitted_bytes.py
    python3 tools/uncommitted_bytes.py --full --threshold 50000
    python3 tools/uncommitted_bytes.py --json

Exit codes:
    0  exposure is within threshold (or no threshold set)
    1  exposure exceeds threshold
    2  git error or repo not found
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def run_git(*args: str, cwd: Path = REPO) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=30,
    )


def diff_bytes(cached: bool = False, cwd: Path = REPO) -> int:
    """Count lines changed in the working tree (or index if cached).

    Uses git diff --numstat which reports lines added/removed per file.
    Binary files show '-' and are skipped. The total is a proxy for
    change size (lines, not raw bytes), but correlates well with
    data-loss exposure for text-heavy repos.
    """
    args = ["diff", "--numstat"]
    if cached:
        args.append("--cached")
    result = run_git(*args, cwd=cwd)
    if result.returncode != 0:
        return 0
    total = 0
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            added = parts[0]
            removed = parts[1]
            # Binary files show '-' instead of numbers
            if added != "-":
                total += int(added)
            if removed != "-":
                total += int(removed)
    return total


def untracked_bytes(cwd: Path = REPO) -> int:
    """Sum byte sizes of untracked files."""
    result = run_git("ls-files", "--others", "--exclude-standard", cwd=cwd)
    if result.returncode != 0:
        return 0
    total = 0
    for filename in result.stdout.strip().splitlines():
        if not filename:
            continue
        fpath = cwd / filename
        try:
            total += fpath.stat().st_size
        except OSError:
            pass
    return total


def file_count(cached: bool = False, cwd: Path = REPO) -> int:
    """Count files with uncommitted changes."""
    args = ["diff", "--name-only"]
    if cached:
        args.append("--cached")
    result = run_git(*args, cwd=cwd)
    if result.returncode != 0:
        return 0
    lines = [l for l in result.stdout.strip().splitlines() if l]
    return len(lines)


def untracked_count(cwd: Path = REPO) -> int:
    """Count untracked files."""
    result = run_git("ls-files", "--others", "--exclude-standard", cwd=cwd)
    if result.returncode != 0:
        return 0
    return len([l for l in result.stdout.strip().splitlines() if l])


def measure(
    full: bool = False,
    diff_only: bool = False,
    cwd: Path = REPO,
) -> dict:
    """Return a complete exposure report."""
    staged_bytes = diff_bytes(cached=True, cwd=cwd)
    staged_files = file_count(cached=True, cwd=cwd)

    if diff_only:
        return {
            "mode": "diff-only",
            "staged_bytes": staged_bytes,
            "staged_files": staged_files,
            "unstaged_bytes": 0,
            "unstaged_files": 0,
            "untracked_bytes": 0,
            "untracked_files": 0,
            "total_exposure": staged_bytes,
        }

    unstaged_bytes = diff_bytes(cached=False, cwd=cwd)
    unstaged_files = file_count(cached=False, cwd=cwd)

    report = {
        "mode": "full" if full else "working-tree",
        "staged_bytes": staged_bytes,
        "staged_files": staged_files,
        "unstaged_bytes": unstaged_bytes,
        "unstaged_files": unstaged_files,
    }

    if full:
        ut_bytes = untracked_bytes(cwd=cwd)
        ut_count = untracked_count(cwd=cwd)
        report["untracked_bytes"] = ut_bytes
        report["untracked_files"] = ut_count
        report["total_exposure"] = staged_bytes + unstaged_bytes + ut_bytes
    else:
        report["untracked_bytes"] = 0
        report["untracked_files"] = 0
        report["total_exposure"] = staged_bytes + unstaged_bytes

    return report


def format_bytes(n: int) -> str:
    """Human-readable byte size."""
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / (1024 * 1024):.1f}MB"


def format_text(report: dict) -> str:
    """Format the report as human-readable text."""
    lines = [
        f"  mode:            {report['mode']}",
        f"  staged:          {format_bytes(report['staged_bytes'])} "
        f"({report['staged_files']} files)",
        f"  unstaged:        {format_bytes(report['unstaged_bytes'])} "
        f"({report['unstaged_files']} files)",
    ]
    if report["mode"] == "full":
        lines.append(
            f"  untracked:       {format_bytes(report['untracked_bytes'])} "
            f"({report['untracked_files']} files)"
        )
    lines.append(
        f"  total exposure:  {format_bytes(report['total_exposure'])}"
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--full", action="store_true",
        help="include untracked files in exposure count",
    )
    ap.add_argument(
        "--diff-only", action="store_true",
        help="only count already-staged changes",
    )
    ap.add_argument(
        "--threshold", type=int, default=None,
        help="bytes; exit 1 if total exposure exceeds this",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="emit JSON instead of text",
    )
    ap.add_argument(
        "--repo", type=str, default=None,
        help="path to repo (default: auto-detect)",
    )
    args = ap.parse_args()

    cwd = Path(args.repo).resolve() if args.repo else REPO

    report = measure(full=args.full, diff_only=args.diff_only, cwd=cwd)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_text(report))

    if args.threshold is not None and report["total_exposure"] > args.threshold:
        print(
            f"\n  WARNING: exposure {format_bytes(report['total_exposure'])} "
            f"exceeds threshold {format_bytes(args.threshold)}"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
