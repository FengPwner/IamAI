#!/usr/bin/env python3
"""push_gate.py — check whether a push would succeed before attempting it.

The commit batch loop pushes every N seconds. When origin/main has moved
ahead (another agent, a CI bot, a human), the push fails with "rejected
(fetch first)" and the batch retries uselessly until the next caretaker
intervention. This gate runs before the push: it fetches, compares heads,
and reports whether the local branch is ready to push or needs a pull.

Usage:
    python3 tools/push_gate.py                  # human-readable, exit 0 = safe to push
    python3 tools/push_gate.py --json           # machine-readable
    python3 tools/push_gate.py --remote origin  # custom remote
    python3 tools/push_gate.py --branch main    # custom branch
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """Run a command, return (returncode, stdout). Never raises."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or REPO,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 128, str(exc)


def fetch(remote: str = "origin", cwd: Path | None = None) -> tuple[bool, str]:
    """Fetch from remote. Returns (ok, message)."""
    rc, out = _run(["git", "fetch", remote], cwd=cwd)
    if rc != 0:
        return False, f"fetch failed: {out}"
    return True, "fetched"


def local_head(cwd: Path | None = None) -> str | None:
    """Return the SHA of HEAD, or None if detached/empty."""
    rc, out = _run(["git", "rev-parse", "HEAD"], cwd=cwd)
    return out if rc == 0 else None


def remote_head(remote: str = "origin", branch: str = "main", cwd: Path | None = None) -> str | None:
    """Return the SHA of remote/branch, or None if unavailable."""
    rc, out = _run(["git", "rev-parse", f"{remote}/{branch}"], cwd=cwd)
    return out if rc == 0 else None


def merge_base(a: str, b: str, cwd: Path | None = None) -> str | None:
    """Return the merge-base of two commits, or None."""
    rc, out = _run(["git", "merge-base", a, b], cwd=cwd)
    return out if rc == 0 else None


def is_ancestor(ancestor: str, descendant: str, cwd: Path | None = None) -> bool:
    """True if ancestor is an ancestor of descendant."""
    rc, _ = _run(["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=cwd)
    return rc == 0


def check_push_gate(
    remote: str = "origin",
    branch: str = "main",
    fetch_first: bool = True,
    cwd: Path | None = None,
) -> dict:
    """Return a structured report on whether push is safe.

    Keys:
        safe_to_push: bool
        local_sha: str | None
        remote_sha: str | None
        status: one of "up_to_date", "ahead", "behind", "diverged", "unknown"
        message: human-readable summary
        behind_count: int — commits remote has that local does not
        ahead_count: int — commits local has that remote does not
    """
    if fetch_first:
        ok, msg = fetch(remote, cwd=cwd)
        if not ok:
            return {
                "safe_to_push": False,
                "local_sha": None,
                "remote_sha": None,
                "status": "unknown",
                "message": msg,
                "behind_count": 0,
                "ahead_count": 0,
            }

    local = local_head(cwd=cwd)
    remote = remote_head(remote, branch, cwd=cwd)

    if local is None or remote is None:
        return {
            "safe_to_push": False,
            "local_sha": local,
            "remote_sha": remote,
            "status": "unknown",
            "message": "could not resolve local or remote HEAD",
            "behind_count": 0,
            "ahead_count": 0,
        }

    if local == remote:
        return {
            "safe_to_push": True,
            "local_sha": local,
            "remote_sha": remote,
            "status": "up_to_date",
            "message": "local is up to date with remote",
            "behind_count": 0,
            "ahead_count": 0,
        }

    # Count commits in each direction
    rc_ahead, ahead_str = _run(
        ["git", "rev-list", "--count", f"{remote}..{local}"], cwd=cwd
    )
    rc_behind, behind_str = _run(
        ["git", "rev-list", "--count", f"{local}..{remote}"], cwd=cwd
    )
    ahead_count = int(ahead_str) if rc_ahead == 0 and ahead_str.isdigit() else 0
    behind_count = int(behind_str) if rc_behind == 0 and behind_str.isdigit() else 0

    if behind_count == 0 and ahead_count > 0:
        return {
            "safe_to_push": True,
            "local_sha": local,
            "remote_sha": remote,
            "status": "ahead",
            "message": f"local is {ahead_count} commit(s) ahead of remote — safe to push",
            "behind_count": 0,
            "ahead_count": ahead_count,
        }

    if behind_count > 0 and ahead_count == 0:
        return {
            "safe_to_push": False,
            "local_sha": local,
            "remote_sha": remote,
            "status": "behind",
            "message": f"local is {behind_count} commit(s) behind remote — pull first",
            "behind_count": behind_count,
            "ahead_count": 0,
        }

    # Both ahead and behind: diverged
    return {
        "safe_to_push": False,
        "local_sha": local,
        "remote_sha": remote,
        "status": "diverged",
        "message": f"diverged: {ahead_count} ahead, {behind_count} behind — merge or rebase needed",
        "behind_count": behind_count,
        "ahead_count": ahead_count,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--remote", default="origin", help="remote name")
    ap.add_argument("--branch", default="main", help="branch name")
    ap.add_argument("--no-fetch", action="store_true", help="skip git fetch")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    report = check_push_gate(
        remote=args.remote,
        branch=args.branch,
        fetch_first=not args.no_fetch,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = report["status"].upper()
        marker = "✓" if report["safe_to_push"] else "✗"
        print(f"[{marker}] {status}: {report['message']}")

    return 0 if report["safe_to_push"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
