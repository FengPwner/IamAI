#!/usr/bin/env python3
"""remote_sync_lag.py — measure how stale the local branch is relative to its remote.

Reports the time delta between the latest local commit and the latest
remote commit on the tracked branch.  A growing lag means pushes are
failing silently or the batch committer is spinning without reaching
the remote.

Exit codes:
  0  synced (lag ≤ threshold)
  1  stale  (lag > threshold)
  2  error  (git failure, no remote, etc.)

Usage:
  python3 tools/remote_sync_lag.py [--threshold SECONDS] [--branch BRANCH]
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone


def git(*args: str) -> str:
    """Run a git command and return stripped stdout."""
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def commit_timestamp(ref: str) -> int:
    """Return unix timestamp of a commit ref."""
    return int(git("log", "-1", "--format=%ct", ref))


def remote_sync_lag(branch: str = "main", remote: str = "origin") -> dict:
    """Compute the sync lag between local and remote branch.

    Returns a dict with:
      local_ts     — unix timestamp of latest local commit
      remote_ts    — unix timestamp of latest remote commit
      lag_seconds  — how far ahead local is (negative = remote ahead)
      lag_human    — human-readable lag string
      status       — "synced" | "ahead" | "behind" | "diverged"
    """
    local_ref = branch
    remote_ref = f"{remote}/{branch}"

    local_ts = commit_timestamp(local_ref)

    try:
        remote_ts = commit_timestamp(remote_ref)
    except RuntimeError:
        # remote tracking ref may not exist yet
        return {
            "local_ts": local_ts,
            "remote_ts": None,
            "lag_seconds": None,
            "lag_human": "no remote tracking ref",
            "status": "no_remote",
        }

    lag = local_ts - remote_ts

    if lag == 0:
        status = "synced"
    elif lag > 0:
        status = "ahead"
    else:
        status = "behind"

    abs_lag = abs(lag)
    if abs_lag < 60:
        human = f"{abs_lag}s"
    elif abs_lag < 3600:
        human = f"{abs_lag // 60}m{abs_lag % 60}s"
    else:
        h, rem = divmod(abs_lag, 3600)
        m = rem // 60
        human = f"{h}h{m}m"

    return {
        "local_ts": local_ts,
        "remote_ts": remote_ts,
        "lag_seconds": lag,
        "lag_human": human if lag >= 0 else f"-{human}",
        "status": status,
    }


def format_report(info: dict) -> str:
    """Format the lag info as a short human-readable report."""
    lines = [
        f"sync lag: {info['lag_human']} ({info['status']})",
        f"local:    {datetime.fromtimestamp(info['local_ts'], tz=timezone.utc).isoformat()}",
    ]
    if info["remote_ts"] is not None:
        lines.append(
            f"remote:   {datetime.fromtimestamp(info['remote_ts'], tz=timezone.utc).isoformat()}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check remote sync lag")
    parser.add_argument("--threshold", type=int, default=600, help="Max acceptable lag in seconds (default: 600)")
    parser.add_argument("--branch", default="main", help="Branch to check (default: main)")
    parser.add_argument("--remote", default="origin", help="Remote name (default: origin)")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    try:
        info = remote_sync_lag(branch=args.branch, remote=args.remote)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(format_report(info))

    if info["status"] == "no_remote":
        return 2
    if info["lag_seconds"] is not None and abs(info["lag_seconds"]) > args.threshold:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
