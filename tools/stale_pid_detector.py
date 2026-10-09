#!/usr/bin/env python3
"""CLI wrapper for iamai.stale_pid_detector — are writer/batch PIDs alive or ghosts?

Checks PID files left behind by writer_loop.py and commit_batch.py.
Reports status and optionally cleans stale files so a restart can proceed.

Usage:
    python3 tools/stale_pid_detector.py                    # check all known PID files
    python3 tools/stale_pid_detector.py --writer qwen      # check a specific writer
    python3 tools/stale_pid_detector.py --clear            # remove stale PID files
    python3 tools/stale_pid_detector.py --json             # machine-readable output

Exit codes:
    0  all PIDs are live (or missing — nothing stale)
    1  at least one stale PID file found — restart blocked
"""

import argparse
import json
import sys
from pathlib import Path

# Allow imports from the repo root when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.stale_pid_detector import PidStatus, check_pid_file, clear_stale

# Default PID file locations relative to repo root.
DEFAULT_PID_DIR = Path("/tmp")
PID_PATTERNS = {
    "writer": "iamai-writer-{writer}.pid",
    "batch": "iamai-batch-{writer}.pid",
}


def discover_pid_files(writer: str | None = None) -> dict[str, Path]:
    """Return a mapping of logical name → PID file path."""
    writers = [writer] if writer else ["qwen", "doubao", "kimi"]
    found = {}
    for w in writers:
        for kind, pattern in PID_PATTERNS.items():
            name = f"{kind}:{w}"
            found[name] = DEFAULT_PID_DIR / pattern.format(writer=w)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect stale writer/batch PID files.")
    parser.add_argument("--writer", help="Check only this writer (e.g. qwen)")
    parser.add_argument("--clear", action="store_true", help="Remove stale PID files")
    parser.add_argument("--json", dest="use_json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)

    pid_files = discover_pid_files(args.writer)
    results = []
    has_stale = False

    for name, path in sorted(pid_files.items()):
        check = check_pid_file(path)
        entry = {
            "name": name,
            "path": str(path),
            "status": check.status.value,
            "pid": check.pid,
            "reason": check.reason,
        }

        if args.clear and check.status == PidStatus.STALE:
            removed = clear_stale(path)
            entry["cleared"] = removed
            if removed:
                entry["status"] = "cleared"

        results.append(entry)
        if check.status == PidStatus.STALE:
            has_stale = True

    if args.use_json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            tag = r["status"].upper()
            pid_str = f" (pid {r['pid']})" if r["pid"] else ""
            cleared = " [CLEARED]" if r.get("cleared") else ""
            print(f"  {tag:8s} {r['name']:16s}{pid_str} — {r['reason']}{cleared}")

    return 1 if has_stale else 0


if __name__ == "__main__":
    sys.exit(main())
