#!/usr/bin/env python3
"""stale_stash_cleaner.py — identify and optionally drop stale git stash entries.

The IamAI repo accumulates stash entries from caretaker visits (visits 503-509+).
Most are the same two files: data/strokes.jsonl and data/writer_state.qwen.json.
These are dead weight — the writer has already committed those changes in later
catch-up commits.

This tool:
  1. Lists all stash entries with their metadata
  2. Identifies stale ones (matching known caretaker patterns)
  3. Optionally drops them (oldest first, to preserve stash@{N} indexing)

Usage:
    python3 tools/stale_stash_cleaner.py              # dry-run: list stale entries
    python3 tools/stale_stash_cleaner.py --drop       # actually drop them
    python3 tools/stale_stash_cleaner.py --json       # JSON output
    python3 tools/stale_stash_cleaner.py --max-age 7  # only entries older than 7 days

Exit codes:
    0 — success (stale entries found or none)
    1 — not a git repo
    2 — git error
"""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class StashEntry:
    ref: str          # e.g. "stash@{0}"
    index: int        # numeric index
    message: str      # commit message
    is_stale: bool    # matches stale pattern
    reason: str       # why marked stale

    def to_dict(self):
        return {
            "ref": self.ref,
            "index": self.index,
            "message": self.message,
            "is_stale": self.is_stale,
            "reason": self.reason,
        }


# Patterns that indicate a caretaker-created stash that's now dead weight
STALE_PATTERNS = [
    (r"^WIP on main:.*catch-up:", "caretaker catch-up stash"),
    (r"^On main: caretaker-pre-rebase$", "caretaker pre-rebase stash"),
    (r"^On main: pre-rebase-stash$", "caretaker pre-rebase stash"),
    (r"^On main: push-sync-test$", "push-sync test stash"),
    (r"^WIP on main:.*pre-rebase-", "timed pre-rebase stash"),
]


def run_git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        timeout=10,
    )


def list_stashes() -> List[StashEntry]:
    """Parse git stash list output into StashEntry objects."""
    result = run_git("stash", "list")
    if result.returncode != 0:
        return []

    entries = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        # Format: stash@{0}: WIP on main: abc1234 message
        m = re.match(r"^(stash@\{(\d+)\}):\s+(.+)$", line)
        if not m:
            continue
        ref = m.group(1)
        idx = int(m.group(2))
        msg = m.group(3)

        is_stale = False
        reason = ""
        for pattern, desc in STALE_PATTERNS:
            if re.search(pattern, msg):
                is_stale = True
                reason = desc
                break

        entries.append(StashEntry(ref=ref, index=idx, message=msg,
                                   is_stale=is_stale, reason=reason))
    return entries


def drop_stash(ref: str) -> bool:
    """Drop a stash entry by ref. Returns True on success."""
    result = run_git("stash", "drop", ref)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Clean stale caretaker stash entries")
    parser.add_argument("--drop", action="store_true", help="Actually drop stale entries")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--max-age", type=int, default=None,
                        help="Only consider entries older than N days (not yet implemented)")
    args = parser.parse_args()

    # Check we're in a repo
    check = run_git("rev-parse", "--is-inside-work-tree")
    if check.returncode != 0:
        print("error: not a git repository", file=sys.stderr)
        sys.exit(1)

    entries = list_stashes()
    stale = [e for e in entries if e.is_stale]

    if args.json:
        output = {
            "total_stashes": len(entries),
            "stale_count": len(stale),
            "stale": [e.to_dict() for e in stale],
            "action": "drop" if args.drop else "dry-run",
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"total stash entries: {len(entries)}")
        print(f"stale (caretaker):   {len(stale)}")
        print()
        for e in stale:
            print(f"  {e.ref}: {e.message}")
            print(f"    reason: {e.reason}")
        if not stale:
            print("  (none)")

    if args.drop and stale:
        # Drop from highest index to lowest to preserve indexing
        sorted_stale = sorted(stale, key=lambda e: e.index, reverse=True)
        dropped = 0
        for e in sorted_stale:
            if drop_stash(e.ref):
                dropped += 1
                if not args.json:
                    print(f"  dropped {e.ref}")
            else:
                if not args.json:
                    print(f"  FAILED to drop {e.ref}")
        if not args.json:
            print(f"\ndropped {dropped}/{len(stale)} stale entries")


if __name__ == "__main__":
    main()
