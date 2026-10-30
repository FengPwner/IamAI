#!/usr/bin/env python3
"""push_lag.py — measure commit lag between local and remote.

The push race happens when another process pushes to the same ref
between your last fetch and your push. This tool quantifies the gap:
how many commits the remote has that you don't, how many you have that
the remote doesn't, and whether a push would succeed right now.

Outputs:
  - behind: commits on remote not in local
  - ahead: commits on local not in remote
  - pushable: bool — would `git push` succeed without pull?
  - divergence_point: merge-base commit hash

Why this matters: stall_report tells you the writer stopped.
cadence_drift tells you it's slowing down. push_lag tells you
whether the *pipe* is clear — even a healthy writer can't deliver
if the remote has drifted ahead. A push_lag > 0 means the next
push will fail, and every failed push is a stroke that never
reached the reader.

Usage:
    python3 tools/push_lag.py [--remote origin] [--branch main]
    python3 tools/push_lag.py --json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or REPO,
    )


def fetch(remote: str = "origin", branch: str = "main", cwd: Path | None = None) -> bool:
    """Fetch the remote ref. Returns True on success."""
    result = _git("fetch", remote, branch, cwd=cwd)
    return result.returncode == 0


def count_commits(ref_a: str, ref_b: str, cwd: Path | None = None) -> int:
    """Count commits reachable from ref_b but not from ref_a.

    Uses `git rev-list --count ref_a..ref_b`.
    Returns 0 if the command fails (e.g., unknown ref).
    """
    result = _git("rev-list", "--count", f"{ref_a}..{ref_b}", cwd=cwd)
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def merge_base(ref_a: str, ref_b: str, cwd: Path | None = None) -> str | None:
    """Find the merge-base commit hash between two refs."""
    result = _git("merge-base", ref_a, ref_b, cwd=cwd)
    if result.returncode != 0:
        return None
    return result.stdout.strip()[:12]


def local_head(cwd: Path | None = None) -> str | None:
    """Get the current HEAD commit hash (short)."""
    result = _git("rev-parse", "--short", "HEAD", cwd=cwd)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def compute_lag(
    remote: str = "origin",
    branch: str = "main",
    cwd: Path | None = None,
    do_fetch: bool = True,
) -> dict:
    """Compute the push lag between local and remote.

    Returns a dict with:
      - behind: commits on remote not in local
      - ahead: commits on local not in remote
      - pushable: whether push would succeed (behind == 0)
      - divergence_point: merge-base short hash or None
      - local_head: current HEAD short hash
      - remote_ref: the remote tracking ref used
    """
    remote_ref = f"{remote}/{branch}"

    if do_fetch:
        fetch(remote, branch, cwd=cwd)

    behind = count_commits("HEAD", remote_ref, cwd=cwd)
    ahead = count_commits(remote_ref, "HEAD", cwd=cwd)
    base = merge_base("HEAD", remote_ref, cwd=cwd)
    head = local_head(cwd=cwd)

    return {
        "behind": behind,
        "ahead": ahead,
        "pushable": behind == 0,
        "divergence_point": base,
        "local_head": head,
        "remote_ref": remote_ref,
    }


def format_text(lag: dict) -> str:
    """Format lag data as human-readable text."""
    status = "CLEAR" if lag["pushable"] else "BLOCKED"
    lines = [
        f"push lag [{status}]",
        f"  behind:  {lag['behind']} commit(s) on {lag['remote_ref']}",
        f"  ahead:   {lag['ahead']} commit(s) local-only",
        f"  pushable: {lag['pushable']}",
    ]
    if lag["divergence_point"]:
        lines.append(f"  diverged at: {lag['divergence_point']}")
    if lag["local_head"]:
        lines.append(f"  local HEAD: {lag['local_head']}")
    if not lag["pushable"]:
        lines.append(f"  fix: git pull --rebase {lag['remote_ref'].split('/')[0]} {lag['remote_ref'].split('/')[1]}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Measure push lag")
    parser.add_argument("--remote", default="origin", help="Remote name")
    parser.add_argument("--branch", default="main", help="Branch name")
    parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    parser.add_argument("--no-fetch", action="store_true", help="Skip git fetch")
    args = parser.parse_args()

    lag = compute_lag(
        remote=args.remote,
        branch=args.branch,
        do_fetch=not args.no_fetch,
    )

    if args.json_output:
        print(json.dumps(lag, indent=2))
    else:
        print(format_text(lag))


if __name__ == "__main__":
    main()
