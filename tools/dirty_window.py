#!/usr/bin/env python3
"""dirty_window.py — measure working-tree drift during a time window.

Counts how many tracked files were modified between two timestamps by
examining file mtimes.  Useful for answering: "how dirty did the tree
get while the writer was running between the restart and the rebase?"

Usage:
    python3 tools/dirty_window.py                        # last 60 seconds
    python3 tools/dirty_window.py --window 300           # last 5 minutes
    python3 tools/dirty_window.py --since "2026-11-18T01:50:00" --until "2026-11-18T02:00:00"
    python3 tools/dirty_window.py --json                 # machine-readable output

Exit codes:
    0 — measurement completed
    1 — error

The tool is pure: it reads mtimes and tracked-file lists, writes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent


@dataclass
class DriftSnapshot:
    """A point-in-time measurement of working-tree drift."""

    window_seconds: float
    since_iso: str
    until_iso: str
    dirty_files: int
    clean_files: int
    total_tracked: int
    dirty_ratio: float
    files: List[str]
    categories: dict

    def summary(self) -> str:
        ratio_pct = f"{self.dirty_ratio * 100:.1f}%"
        return (
            f"drift: {self.dirty_files}/{self.total_tracked} dirty "
            f"({ratio_pct}) in {self.window_seconds:.0f}s window"
        )


def get_tracked_files(repo: Path = REPO) -> List[str]:
    """Return the list of tracked files relative to repo root."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return []
    return [f for f in result.stdout.strip().split("\n") if f]


def categorize_file(path: str) -> str:
    """Categorize a file by its directory prefix."""
    parts = Path(path).parts
    if not parts:
        return "other"
    top = parts[0]
    mapping = {
        "notes": "notes",
        "docs": "docs",
        "tools": "tools",
        "tests": "tests",
        "data": "data",
        "modules": "modules",
        "src": "src",
    }
    return mapping.get(top, top)


def measure_drift(
    repo: Path = REPO,
    window_seconds: Optional[float] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> DriftSnapshot:
    """Measure working-tree drift in a time window.

    If window_seconds is given (and since/until are not), the window is
    [now - window_seconds, now].

    If since and/or until are given, they define the window explicitly.
    """
    now = datetime.now(timezone.utc)

    if since is None and until is None:
        ws = window_seconds or 60.0
        since = datetime.fromtimestamp(now.timestamp() - ws, tz=timezone.utc)
        until = now
    else:
        since = since or datetime.fromtimestamp(0, tz=timezone.utc)
        until = until or now
        ws = (until - since).total_seconds()

    since_ts = since.timestamp()
    until_ts = until.timestamp()

    tracked = get_tracked_files(repo)
    dirty: List[str] = []
    clean_count = 0
    categories: dict = {}

    for rel_path in tracked:
        full = repo / rel_path
        try:
            mtime = full.stat().st_mtime
        except OSError:
            clean_count += 1
            continue

        if since_ts <= mtime <= until_ts:
            dirty.append(rel_path)
            cat = categorize_file(rel_path)
            categories[cat] = categories.get(cat, 0) + 1
        else:
            clean_count += 1

    total = len(tracked)
    ratio = len(dirty) / total if total > 0 else 0.0

    return DriftSnapshot(
        window_seconds=ws,
        since_iso=since.isoformat(),
        until_iso=until.isoformat(),
        dirty_files=len(dirty),
        clean_files=clean_count,
        total_tracked=total,
        dirty_ratio=ratio,
        files=sorted(dirty),
        categories=dict(sorted(categories.items())),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure working-tree drift during a time window."
    )
    parser.add_argument(
        "--window",
        type=float,
        default=60.0,
        help="Window size in seconds (default: 60)",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="ISO timestamp for window start",
    )
    parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="ISO timestamp for window end",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    since = None
    until = None
    if args.since:
        since = datetime.fromisoformat(args.since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    if args.until:
        until = datetime.fromisoformat(args.until)
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)

    snapshot = measure_drift(
        window_seconds=args.window,
        since=since,
        until=until,
    )

    if args.json:
        print(json.dumps(asdict(snapshot), indent=2))
    else:
        print(snapshot.summary())
        if snapshot.files:
            print(f"\ndirty files ({len(snapshot.files)}):")
            for f in snapshot.files[:20]:
                print(f"  {f}")
            if len(snapshot.files) > 20:
                print(f"  ... and {len(snapshot.files) - 20} more")
        if snapshot.categories:
            print(f"\nby category:")
            for cat, count in snapshot.categories.items():
                print(f"  {cat}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
