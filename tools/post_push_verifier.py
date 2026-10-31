#!/usr/bin/env python3
"""post_push_verifier.py — verify that a push actually landed on the remote.

Problem: after resolving push divergence and pushing, the caretaker assumes
success. But pushes can silently fail — network timeout, SSH key expiry,
rate limiting, or a race condition where another writer pushed between the
rebase and the push. The divergence reappears on the next visit with no
record of what went wrong.

This tool compares local HEAD with remote HEAD (via `git ls-remote`) and
reports whether they match. A mismatch means the push did not land.

Usage:
    python3 tools/post_push_verifier.py
    python3 tools/post_push_verifier.py --json
    python3 tools/post_push_verifier.py --remote upstream --branch main

Exit codes:
    0 — push verified (local and remote HEAD match)
    1 — push NOT verified (divergence detected)
    2 — unable to verify (network error, not a git repo, etc.)
"""

import argparse
import json
import subprocess
import sys
import os
from datetime import datetime, timezone


def run_git(*args, cwd=None):
    """Run a git command and return (stdout, stderr, returncode)."""
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True, text=True, cwd=cwd or ".",
        timeout=30,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def get_local_head(repo_path="."):
    """Return the local HEAD commit hash, or None."""
    stdout, _, rc = run_git("rev-parse", "HEAD", cwd=repo_path)
    return stdout if rc == 0 else None


def get_remote_head(repo_path=".", remote="origin", branch="main"):
    """Return the remote branch HEAD via ls-remote, or None."""
    stdout, stderr, rc = run_git(
        "ls-remote", "--heads", remote, branch, cwd=repo_path
    )
    if rc != 0 or not stdout:
        return None
    # format: "<hash>\trefs/heads/<branch>"
    parts = stdout.split()
    return parts[0] if parts else None


def get_local_branch_head(repo_path=".", remote="origin", branch="main"):
    """Return the local tracking branch HEAD, or None."""
    stdout, _, rc = run_git(
        "rev-parse", f"{remote}/{branch}", cwd=repo_path
    )
    return stdout if rc == 0 else None


def get_ahead_behind(repo_path=".", remote="origin", branch="main"):
    """Return (ahead, behind) counts relative to remote tracking branch."""
    stdout, _, rc = run_git(
        "rev-list", "--left-right", "--count",
        f"{remote}/{branch}...HEAD",
        cwd=repo_path,
    )
    if rc != 0:
        return None, None
    parts = stdout.split()
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return None, None


def verify_push(repo_path=".", remote="origin", branch="main"):
    """
    Verify that local HEAD matches remote HEAD.

    Returns a dict with:
        verified: bool
        local_head: str
        remote_head: str
        local_tracking: str
        ahead: int or None
        behind: int or None
        timestamp: str (ISO 8601)
        error: str or None
    """
    result = {
        "verified": False,
        "local_head": None,
        "remote_head": None,
        "local_tracking": None,
        "ahead": None,
        "behind": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }

    local_head = get_local_head(repo_path)
    if not local_head:
        result["error"] = "not a git repository or no commits"
        return result
    result["local_head"] = local_head

    remote_head = get_remote_head(repo_path, remote, branch)
    if not remote_head:
        result["error"] = f"cannot reach {remote}/{branch} via ls-remote"
        return result
    result["remote_head"] = remote_head

    local_tracking = get_local_branch_head(repo_path, remote, branch)
    result["local_tracking"] = local_tracking

    ahead, behind = get_ahead_behind(repo_path, remote, branch)
    result["ahead"] = ahead
    result["behind"] = behind

    result["verified"] = (local_head == remote_head)
    return result


def format_text(result):
    """Format the result as human-readable text."""
    if result.get("error"):
        return f"ERROR: {result['error']}"

    status = "VERIFIED" if result["verified"] else "DIVERGED"
    lines = [
        f"Push status: {status}",
        f"  Local HEAD:   {result['local_head'][:12]}",
        f"  Remote HEAD:  {result['remote_head'][:12]}",
        f"  Tracking:     {(result.get('local_tracking') or '?')[:12]}",
        f"  Ahead/Behind: {result.get('ahead', '?')}/{result.get('behind', '?')}",
        f"  Checked at:   {result['timestamp']}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Verify that a git push landed on the remote."
    )
    parser.add_argument(
        "--remote", default="origin",
        help="Remote name (default: origin)",
    )
    parser.add_argument(
        "--branch", default="main",
        help="Branch name (default: main)",
    )
    parser.add_argument(
        "--repo", default=".",
        help="Repository path (default: current directory)",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Output as JSON",
    )
    args = parser.parse_args()

    result = verify_push(
        repo_path=args.repo,
        remote=args.remote,
        branch=args.branch,
    )

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print(format_text(result))

    if result.get("error"):
        sys.exit(2)
    elif result["verified"]:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
