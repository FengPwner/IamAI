#!/usr/bin/env python3
"""Drop orphaned git stash entries, keeping the N freshest.

In an automated repo, the caretaker stashes before every rebase.
When the rebase-push cycle fails, the stash is never popped.
Over hundreds of visits, these orphans pile up.

Usage:
    python3 tools/stash_cleanup.py [--keep N] [--dry-run]

Default: keep the 2 freshest stash entries, drop the rest.
Only drops entries classified as "wip" or "autostash" — named
entries (user-created with a message) are always preserved.

Exit 0 even if nothing to clean (idempotent).
"""

import argparse
import json
import subprocess
import sys


def classify(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return "unknown"
    if stripped.endswith(": autostash") or stripped == "autostash":
        return "autostash"
    if ": WIP on " in stripped or ": WIP " in stripped:
        return "wip"
    if ": On " in stripped:
        return "named"
    return "unknown"


def list_stashes() -> list[str]:
    result = subprocess.run(
        ["git", "stash", "list"],
        capture_output=True, text=True
    )
    return [l for l in result.stdout.splitlines() if l.strip()]


def drop(ref: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "stash", "drop", ref],
        capture_output=True, text=True
    )


def main():
    parser = argparse.ArgumentParser(description="Clean orphaned git stash entries.")
    parser.add_argument("--keep", type=int, default=2,
                        help="Number of freshest entries to keep (default: 2)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be dropped without dropping")
    args = parser.parse_args()

    lines = list_stashes()
    total = len(lines)

    if total <= args.keep:
        report = {"total": total, "kept": total, "dropped": 0, "entries": []}
        print(json.dumps(report, indent=2))
        return

    to_drop = []
    for i, line in enumerate(lines):
        if i < args.keep:
            continue
        kind = classify(line)
        if kind in ("wip", "autostash"):
            ref = f"stash@{{{i}}}"
            to_drop.append({"ref": ref, "kind": kind, "line": line})

    if not args.dry_run:
        # Drop from highest index first to avoid index shifting
        for entry in reversed(to_drop):
            drop(entry["ref"])

    report = {
        "total": total,
        "kept": args.keep,
        "dropped": len(to_drop),
        "dry_run": args.dry_run,
        "entries": to_drop,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
