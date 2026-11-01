#!/usr/bin/env python3
"""Quiesce the writer process before destructive git operations.

The pause file (/tmp/iamai-writer-pause-<id>) tells the writer to idle,
but there is a race: the writer may be mid-stroke when the pause lands.
This script:

    1. Touches the pause file.
    2. Snapshots the working tree (git status hash).
    3. Waits for two consecutive identical snapshots separated by
       --quiet-seconds (default 5), proving nothing is writing.
    4. Prints QUIESCENT and exits 0.

If the writer is not running (pid file absent or stale), it prints
WRITER_NOT_RUNNING and exits 0 immediately — nothing to quiesce.

Usage:
    python3 tools/quiesce.py [--writer qwen] [--quiet-seconds 5] [--timeout 60]

Exit codes:
    0 — tree is quiescent (safe for git ops)
    1 — timeout waiting for quiescence (writer may be stuck mid-write)
    2 — writer pid file exists but process is dead (stale pid)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai import writer as writer_mod  # noqa: E402


def snapshot_tree() -> str:
    """Return a hash of the current git status + mtimes of dirty files."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    lines = result.stdout.strip().splitlines()
    parts = []
    for line in lines:
        path = line[3:]  # strip XY status prefix
        full = REPO / path
        try:
            st = full.stat()
            parts.append(f"{path}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{path}:missing")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def pid_alive(pidfile: Path) -> bool:
    if not pidfile.exists():
        return False
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default=None, help="writer id (default: env IAMAII_WRITER or 'qwen')")
    ap.add_argument("--quiet-seconds", type=int, default=5, help="seconds of tree stability required")
    ap.add_argument("--timeout", type=int, default=60, help="max seconds to wait for quiescence")
    args = ap.parse_args()

    writer_id = args.writer or os.environ.get("IAMAII_WRITER", "qwen")
    pause_file = writer_mod.pause_file(writer_id)
    pidfile = writer_mod.pid_file(writer_id)

    # If writer is not running, nothing to quiesce.
    if not pid_alive(pidfile):
        print("WRITER_NOT_RUNNING")
        return 0

    # Touch the pause file.
    pause_file.touch()
    print(f"pause file touched: {pause_file}")

    deadline = time.monotonic() + args.timeout
    prev_hash = None
    prev_time = 0.0

    while time.monotonic() < deadline:
        current_hash = snapshot_tree()
        now = time.monotonic()

        if current_hash == prev_hash:
            stable_for = now - prev_time
            if stable_for >= args.quiet_seconds:
                print(f"QUIESCENT (stable for {stable_for:.1f}s)")
                return 0
        else:
            prev_hash = current_hash
            prev_time = now

        time.sleep(1)

    print(f"TIMEOUT after {args.timeout}s — tree never settled")
    return 1


if __name__ == "__main__":
    sys.exit(main())
