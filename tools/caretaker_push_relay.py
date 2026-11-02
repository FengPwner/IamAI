#!/usr/bin/env python3
"""caretaker_push_relay — one-command push that respects the writer.

Visit 484 observed the recurring problem: rebase during an active writer
causes mid-operation tree mutations, forcing caretakers into a manual
stash→rebase→pop dance every single visit.  This tool does the whole
relay in one call:

    1. Quiesce the writer (touch pause file, wait for tree stability).
    2. Commit any uncommitted changes with a given message.
    3. Fetch origin and rebase onto origin/main.
    4. Push.
    5. Clear the pause file so the writer resumes.

If any step fails, the pause file is still cleared (finally block) so
the writer never stays stalled because a push failed halfway.

Usage:
    python3 tools/caretaker_push_relay.py [--writer qwen] [--message "commit msg"]

Exit codes:
    0 — pushed successfully
    1 — quiesce failed (writer stuck)
    2 — commit failed
    3 — rebase failed (conflict; pause file cleared, human needed)
    4 — push failed (network or auth; pause file cleared)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai import writer as writer_mod  # noqa: E402


def _run(cmd, cwd=None, timeout=120):
    """Run a command, return (returncode, stdout, stderr). Never raises."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=cwd or str(REPO), timeout=timeout,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 1, "", str(exc)


def pause_writer(writer_id: str) -> Path:
    """Touch the pause file. Returns the path."""
    pf = writer_mod.pause_file(writer_id)
    pf.touch()
    return pf


def clear_pause(writer_id: str) -> None:
    """Remove the pause file so the writer resumes."""
    pf = writer_mod.pause_file(writer_id)
    if pf.exists():
        pf.unlink()


def wait_quiet(writer_id: str, quiet_seconds: int = 5, timeout: int = 60) -> bool:
    """Wait for the tree to stop changing. Returns True if quiet."""
    import hashlib
    pidfile = writer_mod.pid_file(writer_id)
    # If writer is not running, tree is trivially quiet.
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, PermissionError):
            return True  # writer dead, nothing to wait for

    deadline = time.monotonic() + timeout
    prev_hash = None
    prev_time = 0.0

    while time.monotonic() < deadline:
        rc, out, _ = _run(["git", "status", "--porcelain"])
        current_hash = hashlib.sha256(out.encode()).hexdigest()
        now = time.monotonic()
        if current_hash == prev_hash:
            if (now - prev_time) >= quiet_seconds:
                return True
        else:
            prev_hash = current_hash
            prev_time = now
        time.sleep(1)
    return False


def commit_all(message: str) -> bool:
    """Stage everything and commit. Returns True on success or nothing-to-commit."""
    _run(["git", "add", "-A"])
    rc, out, _ = _run(["git", "diff", "--cached", "--quiet"])
    if rc == 0:
        return True  # nothing staged
    rc, _, err = _run(["git", "commit", "-m", message])
    return rc == 0


def fetch_and_rebase() -> tuple[bool, str]:
    """Fetch origin and rebase current branch onto origin/main."""
    rc, _, err = _run(["git", "fetch", "origin"])
    if rc != 0:
        return False, f"fetch failed: {err}"
    rc, out, err = _run(["git", "rebase", "origin/main"])
    if rc != 0:
        # Abort the rebase to leave tree clean.
        _run(["git", "rebase", "--abort"])
        return False, f"rebase conflict: {err}"
    return True, "rebased cleanly"


def push() -> tuple[bool, str]:
    """Push current branch to origin."""
    rc, out, err = _run(["git", "push", "origin", "main"])
    if rc != 0:
        return False, f"push rejected: {err}"
    return True, "pushed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default=None)
    ap.add_argument("--message", default="caretaker relay: commit + push",
                    help="commit message for any uncommitted changes")
    args = ap.parse_args()

    writer_id = args.writer or os.environ.get("IAMAII_WRITER", "qwen")

    try:
        # Step 1: quiesce
        pause_writer(writer_id)
        print(f"[relay] pause file set, waiting for writer to settle...")
        if not wait_quiet(writer_id):
            print(f"[relay] TIMEOUT: tree never settled after 60s")
            return 1

        # Step 2: commit
        print(f"[relay] committing pending changes...")
        if not commit_all(args.message):
            print(f"[relay] commit failed")
            return 2

        # Step 3: rebase
        print(f"[relay] fetching and rebasing...")
        ok, msg = fetch_and_rebase()
        if not ok:
            print(f"[relay] {msg}")
            return 3

        # Step 4: push
        print(f"[relay] pushing...")
        ok, msg = push()
        if not ok:
            print(f"[relay] {msg}")
            return 4

        print(f"[relay] done — pushed cleanly")
        return 0

    finally:
        clear_pause(writer_id)
        print(f"[relay] pause file cleared, writer resumed")


if __name__ == "__main__":
    sys.exit(main())
