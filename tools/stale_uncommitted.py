#!/usr/bin/env python3
"""stale_uncommitted.py — detect uncommitted files older than a threshold.

Problem: the batch committer runs every 600s. When it fails silently,
modified files accumulate in the working tree. By the time the caretaker
notices, dozens of files may be hours old and the writer has stalled
waiting for disk space or git locks.

Existing tools (process_health.py, commit_health_pulse.py) check whether
processes are alive or whether commits are recent. Neither answers the
question: "how long has that specific file been sitting here uncommitted?"

This tool fills that gap. It reports each modified/untracked file's age
(modification time vs. now) and flags anything older than a configurable
threshold.

Usage:
    python3 tools/stale_uncommitted.py
    python3 tools/stale_uncommitted.py --warn 900 --crit 3600
    python3 tools/stale_uncommitted.py --json
    python3 tools/stale_uncommitted.py --repo /path/to/IamAI

Exit codes:
    0 — all uncommitted files are fresh (or nothing to commit)
    1 — at least one file exceeds --crit threshold
    2 — warning level only
    3 — not a git repo or other precondition failure

Output (text):
    OK   data/strokes.jsonl         42s
    WARN notes/handwritten.md     1234s
    CRIT snippets/foo.py          7200s
    ---
    3 uncommitted | 1 ok | 1 warn | 1 crit | stale_ratio 0.67

Output (json):
    {"files": [...], "summary": {...}, "verdict": "critical"}
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class FileAge:
    path: str
    status: str          # M / A / ?? / etc.
    age_seconds: float
    level: str           # ok / warn / crit


@dataclass
class StaleReport:
    files: List[FileAge]
    total_uncommitted: int
    ok_count: int
    warn_count: int
    crit_count: int
    stale_ratio: float   # (warn + crit) / total, 0.0 if no files
    verdict: str         # clean / ok / warning / critical
    checked_at: str      # ISO-8601


def _git_porcelain(repo: str) -> List[tuple[str, str]]:
    """Return [(status_flag, path), ...] from git status --porcelain."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"error: git not available or timed out: {exc}", file=sys.stderr)
        sys.exit(3)

    if result.returncode != 0:
        print(f"error: git status failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(3)

    entries = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        flag = line[:2].strip()
        path = line[3:].strip()
        # Handle renames: "R  old -> new"
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entries.append((flag, path))
    return entries


def _file_age_seconds(repo: str, path: str, now: float) -> float:
    """Return age in seconds of a file relative to repo root."""
    full = os.path.join(repo, path)
    try:
        mtime = os.path.getmtime(full)
    except OSError:
        return 0.0
    return max(0.0, now - mtime)


def _classify(age: float, warn: float, crit: float) -> str:
    if age >= crit:
        return "crit"
    if age >= warn:
        return "warn"
    return "ok"


def check(
    repo: str = ".",
    warn_threshold: float = 900.0,
    crit_threshold: float = 3600.0,
) -> StaleReport:
    repo = os.path.abspath(repo)
    if not os.path.isdir(os.path.join(repo, ".git")):
        print(f"error: {repo} is not a git repository", file=sys.stderr)
        sys.exit(3)

    entries = _git_porcelain(repo)
    now = time.time()

    files: List[FileAge] = []
    for flag, path in entries:
        age = _file_age_seconds(repo, path, now)
        level = _classify(age, warn_threshold, crit_threshold)
        files.append(FileAge(path=path, status=flag, age_seconds=round(age, 1), level=level))

    # Sort: oldest first (most urgent at top)
    files.sort(key=lambda f: -f.age_seconds)

    ok = sum(1 for f in files if f.level == "ok")
    warn = sum(1 for f in files if f.level == "warn")
    crit = sum(1 for f in files if f.level == "crit")
    total = len(files)
    stale_ratio = round((warn + crit) / total, 2) if total > 0 else 0.0

    if crit > 0:
        verdict = "critical"
    elif warn > 0:
        verdict = "warning"
    elif total > 0:
        verdict = "ok"
    else:
        verdict = "clean"

    from datetime import datetime, timezone
    checked_at = datetime.now(timezone.utc).isoformat()

    return StaleReport(
        files=files,
        total_uncommitted=total,
        ok_count=ok,
        warn_count=warn,
        crit_count=crit,
        stale_ratio=stale_ratio,
        verdict=verdict,
        checked_at=checked_at,
    )


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        mins = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{mins}m{secs}s"
    return f"{seconds / 3600:.1f}h"


def _print_text(report: StaleReport) -> None:
    level_tag = {"ok": "OK  ", "warn": "WARN", "crit": "CRIT"}
    for f in report.files:
        tag = level_tag.get(f.level, "????")
        print(f"  {tag}  {f.path:<40s} {_format_age(f.age_seconds):>8s}")
    if not report.files:
        print("  (nothing uncommitted)")
    print("---")
    print(
        f"  {report.total_uncommitted} uncommitted | "
        f"{report.ok_count} ok | {report.warn_count} warn | {report.crit_count} crit | "
        f"stale_ratio {report.stale_ratio:.2f} | verdict: {report.verdict}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect stale uncommitted files.")
    parser.add_argument("--repo", default=".", help="Path to git repo (default: cwd)")
    parser.add_argument("--warn", type=float, default=900, help="Warning threshold in seconds (default: 900)")
    parser.add_argument("--crit", type=float, default=3600, help="Critical threshold in seconds (default: 3600)")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args()

    report = check(repo=args.repo, warn_threshold=args.warn, crit_threshold=args.crit)

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        _print_text(report)

    if report.verdict == "critical":
        sys.exit(1)
    if report.verdict == "warning":
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
