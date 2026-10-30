#!/usr/bin/env python3
"""stale_stash_scanner.py — find and optionally drop stale git stashes.

The IamAI writer-batch pipeline stashes working-tree changes every time it
needs to rebase before pushing.  Under normal operation this happens rarely,
but during recovery or rapid-fire divergence it can accumulate a dozen or
more entries.  Most of those stashes are one-line state files that will never
be popped; they just sit there forever, cluttering `git stash list` and
slowing down stash operations.

This tool scans all stash entries, reports their age, and optionally drops
entries older than a configurable threshold (default 7 days).

Classifications:
    fresh   — created within the last `fresh_days` days (default 3)
    aging   — between `fresh_days` and `max_age_days`
    stale   — older than `max_age_days` (default 7)

Exit codes:
    0 — scan succeeded (report printed to stdout)
    1 — git error or repo not found
    2 — no stashes found (clean state)

Usage:
    python3 tools/stale_stash_scanner.py
    python3 tools/stale_stash_scanner.py --max-age 3
    python3 tools/stale_stash_scanner.py --drop-stale
    python3 tools/stale_stash_scanner.py --json
    python3 tools/stale_stash_scanner.py --repo /path/to/IamAI
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_FRESH_DAYS = 3
DEFAULT_MAX_AGE_DAYS = 7


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StashEntry:
    index: int
    message: str
    created: str          # ISO-8601 timestamp
    age_days: float
    classification: str   # "fresh" | "aging" | "stale"


@dataclass
class StashReport:
    total: int
    fresh: int
    aging: int
    stale: int
    entries: List[StashEntry]
    dropped: List[int]     # indices of stashes dropped (if --drop-stale)
    scanned_at: str
    repo: str


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def find_repo_root(start: Optional[str] = None) -> str:
    """Walk up from *start* (or cwd) to find the git repo root."""
    cwd = start or os.getcwd()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise FileNotFoundError(f"Not a git repo: {cwd}")
    return result.stdout.strip()


def run_git(args: List[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd, capture_output=True, text=True,
    )


def parse_stash_list(cwd: str) -> List[dict]:
    """Return list of {index, message, timestamp} from `git stash list`."""
    result = run_git(
        ["stash", "list", "--format=%gd|%gs|%ci"],
        cwd=cwd,
    )
    if result.returncode != 0:
        return []

    entries = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue

        ref, message, date_str = parts
        # ref looks like "stash@{0}"
        m = re.search(r"\{(\d+)\}", ref)
        idx = int(m.group(1)) if m else -1

        # Parse the commit date (format: 2026-10-31 03:01:22 +0800)
        try:
            dt = datetime.strptime(
                date_str.strip()[:19], "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=timezone.utc)  # approximate; offset ignored
        except ValueError:
            dt = datetime.now(timezone.utc)

        entries.append({
            "index": idx,
            "message": message.strip(),
            "timestamp": dt.isoformat(),
            "datetime": dt,
        })

    return entries


def drop_stash(index: int, cwd: str) -> bool:
    """Drop stash@{index}. Returns True on success."""
    result = run_git(["stash", "drop", f"stash@{{{index}}}"], cwd=cwd)
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def scan_stashes(
    repo: Optional[str] = None,
    fresh_days: int = DEFAULT_FRESH_DAYS,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    drop_stale: bool = False,
) -> StashReport:
    """Scan all stashes and classify them by age."""
    cwd = find_repo_root(repo)
    now = datetime.now(timezone.utc)

    raw = parse_stash_list(cwd)
    if not raw:
        return StashReport(
            total=0, fresh=0, aging=0, stale=0,
            entries=[], dropped=[],
            scanned_at=now.isoformat(), repo=cwd,
        )

    entries: List[StashEntry] = []
    dropped: List[int] = []

    for item in raw:
        age = (now - item["datetime"]).total_seconds() / 86400
        if age < fresh_days:
            classification = "fresh"
        elif age < max_age_days:
            classification = "aging"
        else:
            classification = "stale"

        entries.append(StashEntry(
            index=item["index"],
            message=item["message"],
            created=item["timestamp"],
            age_days=round(age, 1),
            classification=classification,
        ))

    if drop_stale:
        # Drop from highest index to lowest to avoid re-indexing issues
        stale_indices = sorted(
            [e.index for e in entries if e.classification == "stale"],
            reverse=True,
        )
        for idx in stale_indices:
            if drop_stash(idx, cwd):
                dropped.append(idx)

    fresh_count = sum(1 for e in entries if e.classification == "fresh")
    aging_count = sum(1 for e in entries if e.classification == "aging")
    stale_count = sum(1 for e in entries if e.classification == "stale")

    return StashReport(
        total=len(entries),
        fresh=fresh_count,
        aging=aging_count,
        stale=stale_count,
        entries=entries,
        dropped=sorted(dropped),
        scanned_at=now.isoformat(),
        repo=cwd,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

import os  # noqa: E402 (needed by find_repo_root at module level)


def main():
    parser = argparse.ArgumentParser(
        description="Scan git stashes and classify by age."
    )
    parser.add_argument(
        "--repo", default=None,
        help="Path to git repo (default: auto-detect from cwd)",
    )
    parser.add_argument(
        "--fresh-days", type=int, default=DEFAULT_FRESH_DAYS,
        help=f"Days threshold for 'fresh' (default {DEFAULT_FRESH_DAYS})",
    )
    parser.add_argument(
        "--max-age", type=int, default=DEFAULT_MAX_AGE_DAYS,
        help=f"Days threshold for 'stale' (default {DEFAULT_MAX_AGE_DAYS})",
    )
    parser.add_argument(
        "--drop-stale", action="store_true",
        help="Drop stashes classified as stale",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        report = scan_stashes(
            repo=args.repo,
            fresh_days=args.fresh_days,
            max_age_days=args.max_age,
            drop_stale=args.drop_stale,
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    if report.total == 0:
        print("No stashes found — clean state.")
        sys.exit(2)

    if args.json_output:
        print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    else:
        print(f"Stash scan @ {report.scanned_at[:19]}")
        print(f"  repo:  {report.repo}")
        print(f"  total: {report.total}  "
              f"fresh: {report.fresh}  "
              f"aging: {report.aging}  "
              f"stale: {report.stale}")
        print()
        for e in report.entries:
            marker = {"fresh": "●", "aging": "◐", "stale": "○"}[e.classification]
            print(f"  {marker} stash@{{{e.index}}}  "
                  f"{e.age_days:6.1f}d  {e.classification:6s}  {e.message[:60]}")
        if report.dropped:
            print(f"\n  Dropped {len(report.dropped)} stale stash(es): "
                  f"{report.dropped}")

    sys.exit(0)


if __name__ == "__main__":
    main()
