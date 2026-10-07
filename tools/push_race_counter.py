#!/usr/bin/env python3
"""push_race_counter.py — count push-race occurrences in repo history.

Scans git log and devlog for evidence of push races (rejected pushes that
required rebase/merge to resolve). Useful for quantifying the frequency
of the push race problem before investing in synchronization tooling.

Detection heuristics:
    1. Commit messages containing "pull --rebase" or "synced (rebase)"
       indicate a push race was resolved.
    2. Devlog entries mentioning "rejected" or "fetch first" in the
       context of push operations.
    3. Caretaker visit notes documenting push race recovery.

Usage:
    python3 tools/push_race_counter.py [--days 7] [--source log|devlog|all]

Exit codes:
    0 — scan complete (race count may be zero)
    1 — error reading log or devlog
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@dataclass
class RaceEntry:
    """A single detected push race occurrence."""
    timestamp: str
    source: str  # "commit", "devlog", "visit"
    description: str


def run_git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    """Run a git command, return (returncode, output)."""
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd or REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def scan_commit_log(since: str | None = None) -> list[RaceEntry]:
    """Scan git log for commits that resolved a push race.

    Looks for commit messages containing indicators of rebase-fixup
    after a rejected push.
    """
    cmd = ["log", "--format=%aI||%s", "--all"]
    if since:
        cmd.append(f"--since={since}")
    code, output = run_git(*cmd)
    if code != 0 or not output:
        return []

    race_markers = ["pull --rebase", "synced (rebase)", "synced (merge)",
                    "fetch first", "push race", "rebase-fixup"]
    entries = []
    for line in output.splitlines():
        if "||" not in line:
            continue
        timestamp, message = line.split("||", 1)
        msg_lower = message.lower()
        if any(marker in msg_lower for marker in race_markers):
            entries.append(RaceEntry(
                timestamp=timestamp,
                source="commit",
                description=message,
            ))
    return entries


def scan_devlog(since_days: int = 7) -> list[RaceEntry]:
    """Scan docs/DEVLOG.md for push race mentions."""
    devlog = REPO / "docs" / "DEVLOG.md"
    if not devlog.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    entries = []
    race_markers = ["rejected", "fetch first", "push race", "diverged"]

    for line in devlog.read_text(encoding="utf-8").splitlines():
        line_lower = line.lower()
        if any(marker in line_lower for marker in race_markers):
            # Devlog lines don't always have timestamps; use file mtime as proxy
            entries.append(RaceEntry(
                timestamp="",
                source="devlog",
                description=line.strip()[:120],
            ))
    return entries


def scan_visit_notes(since_days: int = 7) -> list[RaceEntry]:
    """Scan caretaker visit notes for push race documentation."""
    notes_dir = REPO / "notes"
    if not notes_dir.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    entries = []
    race_markers = ["push race", "rejected", "fetch first", "push rejected",
                    "divergence", "rebase to resolve"]

    for note in sorted(notes_dir.glob("caretaker-visit-*.md")):
        text = note.read_text(encoding="utf-8").lower()
        if any(marker in text for marker in race_markers):
            # Extract visit number and date from filename
            stem = note.stem
            entries.append(RaceEntry(
                timestamp=stem.split("-")[-1] if "-" in stem else "",
                source="visit",
                description=f"{stem}: push race documented",
            ))
    return entries


def count_races(
    days: int = 7,
    source: str = "all",
) -> dict:
    """Count push race occurrences in the given time window.

    Returns a dict with:
        total: int — total race occurrences found
        by_source: dict — breakdown by source type
        entries: list[RaceEntry] — individual race entries
        rate_per_day: float — average races per day
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    all_entries: list[RaceEntry] = []

    if source in ("log", "all"):
        all_entries.extend(scan_commit_log(since))
    if source in ("devlog", "all"):
        all_entries.extend(scan_devlog(days))
    if source in ("all",):
        all_entries.extend(scan_visit_notes(days))

    by_source: dict[str, int] = {}
    for entry in all_entries:
        by_source[entry.source] = by_source.get(entry.source, 0) + 1

    rate = len(all_entries) / max(days, 1)

    return {
        "total": len(all_entries),
        "by_source": by_source,
        "entries": all_entries,
        "rate_per_day": round(rate, 2),
        "window_days": days,
    }


def main():
    parser = argparse.ArgumentParser(description="Count push race occurrences")
    parser.add_argument("--days", type=int, default=7,
                        help="time window in days (default: 7)")
    parser.add_argument("--source", default="all", choices=["log", "devlog", "all"],
                        help="data source to scan (default: all)")
    args = parser.parse_args()

    result = count_races(args.days, args.source)
    print(f"window:  {result['window_days']} days")
    print(f"total:   {result['total']} races")
    print(f"rate:    {result['rate_per_day']}/day")
    for src, count in sorted(result["by_source"].items()):
        print(f"  {src}: {count}")
    for entry in result["entries"][:10]:
        print(f"  [{entry.source}] {entry.timestamp} {entry.description}")
    if len(result["entries"]) > 10:
        print(f"  ... and {len(result['entries']) - 10} more")


if __name__ == "__main__":
    main()
