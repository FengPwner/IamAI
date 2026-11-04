#!/usr/bin/env python3
"""stash_sweep.py — drop stash entries older than a configurable age.

Visit 534 identified 27 historical stash entries accumulated from caretaker
visits since early October. Most are the same two files (strokes.jsonl and
writer_state.qwen.json) that have long since been committed. This tool
automates the cleanup that stale_stash_cleaner.py only does manually.

Difference from stale_stash_cleaner:
  - stale_stash_cleaner matches by message pattern (caretaker-specific)
  - stash_sweep matches by age (anything older than N days is gone)
  - stash_sweep is safe to run in a cron job: default dry-run, --sweep to act

Usage:
    python3 tools/stash_sweep.py                 # dry-run, show what would go
    python3 tools/stash_sweep.py --sweep         # actually drop old entries
    python3 tools/stash_sweep.py --max-age 3     # only entries older than 3 days
    python3 tools/stash_sweep.py --json          # JSON output

Exit codes:
    0 — success
    1 — not a git repo
    2 — git error
"""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import List, Optional


@dataclass
class StashRecord:
    ref: str
    index: int
    message: str
    timestamp: Optional[datetime]
    age_days: Optional[float]
    will_drop: bool
    reason: str

    def to_dict(self):
        d = asdict(self)
        if self.timestamp:
            d["timestamp"] = self.timestamp.isoformat()
        return d


def run_git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        timeout=15,
    )


def parse_stash_list(raw: str) -> List[StashRecord]:
    """Parse `git stash list` output into StashRecord objects."""
    entries = []
    for line in raw.strip().split("\n"):
        if not line:
            continue
        m = re.match(r"^(stash@\{(\d+)\}):\s+(.+)$", line)
        if not m:
            continue
        ref, idx_str, msg = m.group(1), m.group(2), m.group(3)
        entries.append(StashRecord(
            ref=ref,
            index=int(idx_str),
            message=msg,
            timestamp=None,
            age_days=None,
            will_drop=False,
            reason="",
        ))
    return entries


def enrich_timestamps(entries: List[StashRecord]) -> List[StashRecord]:
    """Add timestamps by querying each stash entry's commit date."""
    for entry in entries:
        result = run_git("log", "-1", "--format=%aI", entry.ref)
        if result.returncode == 0 and result.stdout.strip():
            try:
                entry.timestamp = datetime.fromisoformat(result.stdout.strip())
            except ValueError:
                pass
    return entries


def mark_for_drop(entries: List[StashRecord], max_age_days: float,
                  now: Optional[datetime] = None) -> List[StashRecord]:
    """Mark entries older than max_age_days for dropping."""
    if now is None:
        now = datetime.now(timezone.utc)
    for entry in entries:
        if entry.timestamp is None:
            entry.reason = "no timestamp available"
            entry.will_drop = False
            continue
        # Ensure both are timezone-aware for comparison
        ts = entry.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = now - ts
        entry.age_days = age.total_seconds() / 86400
        if entry.age_days >= max_age_days:
            entry.will_drop = True
            entry.reason = f"age {entry.age_days:.1f}d >= {max_age_days}d threshold"
        else:
            entry.will_drop = False
            entry.reason = f"age {entry.age_days:.1f}d < {max_age_days}d threshold"
    return entries


def drop_entries(entries: List[StashRecord]) -> dict:
    """Drop marked entries from highest index to lowest (preserves indexing)."""
    targets = [e for e in entries if e.will_drop]
    # Sort descending by index so stash@{5} drops before stash@{2}
    targets.sort(key=lambda e: e.index, reverse=True)
    dropped = 0
    failed = 0
    for entry in targets:
        result = run_git("stash", "drop", entry.ref)
        if result.returncode == 0:
            dropped += 1
        else:
            failed += 1
    return {"dropped": dropped, "failed": failed, "total_marked": len(targets)}


def main():
    parser = argparse.ArgumentParser(
        description="Sweep old git stash entries by age")
    parser.add_argument("--sweep", action="store_true",
                        help="Actually drop old entries (default: dry-run)")
    parser.add_argument("--max-age", type=float, default=7.0,
                        help="Drop entries older than N days (default: 7)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    # Verify we're in a git repo
    check = run_git("rev-parse", "--is-inside-work-tree")
    if check.returncode != 0:
        print("error: not a git repository", file=sys.stderr)
        sys.exit(1)

    # List stashes
    result = run_git("stash", "list")
    if result.returncode != 0:
        print(f"error: git stash list failed: {result.stderr}", file=sys.stderr)
        sys.exit(2)

    entries = parse_stash_list(result.stdout)
    if not entries:
        output = {
            "total": 0,
            "marked_for_drop": 0,
            "action": "sweep" if args.sweep else "dry-run",
            "entries": [],
        }
        if args.json:
            print(json.dumps(output, indent=2))
        else:
            print("no stash entries found — nothing to sweep")
        sys.exit(0)

    # Enrich with timestamps and mark
    entries = enrich_timestamps(entries)
    entries = mark_for_drop(entries, args.max_age)

    marked = [e for e in entries if e.will_drop]

    # Output
    if args.json:
        output = {
            "total": len(entries),
            "marked_for_drop": len(marked),
            "max_age_days": args.max_age,
            "action": "sweep" if args.sweep else "dry-run",
            "entries": [e.to_dict() for e in entries],
        }
        if args.sweep:
            result = drop_entries(entries)
            output["result"] = result
        print(json.dumps(output, indent=2))
    else:
        print(f"stash entries: {len(entries)}")
        print(f"threshold:     {args.max_age} days")
        print(f"marked to drop: {len(marked)}")
        print(f"mode:          {'SWEEP' if args.sweep else 'dry-run'}")
        print()
        for e in entries:
            marker = "✗" if e.will_drop else " "
            age_str = f"{e.age_days:.1f}d" if e.age_days is not None else "?"
            print(f"  {marker} {e.ref} [{age_str}] {e.message[:60]}")
            if e.reason:
                print(f"      {e.reason}")
        if args.sweep and marked:
            print()
            result = drop_entries(entries)
            print(f"dropped {result['dropped']}/{result['total_marked']} entries"
                  + (f" ({result['failed']} failed)" if result['failed'] else ""))


if __name__ == "__main__":
    main()
