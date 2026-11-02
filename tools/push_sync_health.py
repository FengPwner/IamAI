#!/usr/bin/env python3
"""push_sync_health — single-command push-readiness scorer.

Visit 484 identified a gap: no single tool answers "can I push right
now?" without chaining multiple diagnostics.  This tool scores the
repo's push readiness on a 0–3 scale and emits JSON for downstream
consumption (batch committer, caretaker cron, deadman switch).

Scoring:
    3  clean       — nothing pending, nothing ahead, synced with remote
    2  local_debt  — committed but unpushed; safe to push
    1  dirty_tree  — uncommitted changes in working tree
    0  diverged    — remote has commits we don't; needs rebase/merge

Exit code mirrors the score so shell pipelines can gate on it:
    score 3 → exit 0
    score 2 → exit 0  (push will succeed)
    score 1 → exit 1  (commit first)
    score 0 → exit 2  (fetch + rebase first)
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _run(cmd, cwd=None):
    """Run a command, return (returncode, stdout).  Never raises."""
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
        )
        return r.returncode, r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, str(exc)


def uncommitted_bytes(repo):
    """Return the number of bytes changed but not yet committed."""
    rc, out = _run(["git", "diff", "--stat"], cwd=repo)
    if rc != 0 or not out:
        return 0
    # last line looks like " 3 files changed, 12 insertions(+), 5 deletions(-)"
    for token in out.splitlines()[-1].split(","):
        token = token.strip()
        if "insertion" in token:
            try:
                return int(token.split()[0])
            except (ValueError, IndexError):
                pass
    return 0


def unpushed_commits(repo, remote="origin", branch="main"):
    """Count commits ahead of remote tracking branch."""
    rc, out = _run(
        ["git", "rev-list", "--count", f"{remote}/{branch}..HEAD"],
        cwd=repo,
    )
    if rc != 0:
        return -1  # unknown (remote not fetched, branch mismatch)
    try:
        return int(out)
    except ValueError:
        return -1


def remote_diverged(repo, remote="origin", branch="main"):
    """True if remote has commits we don't (needs fetch + rebase)."""
    rc, out = _run(
        ["git", "rev-list", "--count", f"HEAD..{remote}/{branch}"],
        cwd=repo,
    )
    if rc != 0:
        return None  # can't tell
    try:
        return int(out) > 0
    except ValueError:
        return None


def score_push_health(repo, remote="origin", branch="main"):
    """Compute the push-health score and return (score, label, details)."""
    details = {}

    # check uncommitted
    uc = uncommitted_bytes(repo)
    details["uncommitted_bytes"] = uc

    # check unpushed
    up = unpushed_commits(repo, remote, branch)
    details["unpushed_commits"] = up

    # check divergence (requires fetch for accuracy)
    _run(["git", "fetch", remote, branch], cwd=repo)
    div = remote_diverged(repo, remote, branch)
    details["remote_diverged"] = div

    # scoring
    if div is True:
        return 0, "diverged", details
    if uc > 0:
        return 1, "dirty_tree", details
    if up > 0:
        return 2, "local_debt", details
    return 3, "clean", details


def main():
    ap = argparse.ArgumentParser(description="push-readiness health scorer")
    ap.add_argument("--repo", default=".", help="path to git repo (default .)")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--json", action="store_true", help="emit JSON to stdout")
    ap.add_argument(
        "--no-fetch",
        action="store_true",
        help="skip git fetch (faster, but divergence may be stale)",
    )
    args = ap.parse_args()

    repo = str(Path(args.repo).resolve())
    details = {}

    uc = uncommitted_bytes(repo)
    details["uncommitted_bytes"] = uc

    up = unpushed_commits(repo, args.remote, args.branch)
    details["unpushed_commits"] = up

    if not args.no_fetch:
        _run(["git", "fetch", args.remote, args.branch], cwd=repo)

    div = remote_diverged(repo, args.remote, args.branch)
    details["remote_diverged"] = div

    if div is True:
        score, label = 0, "diverged"
    elif uc > 0:
        score, label = 1, "dirty_tree"
    elif up > 0:
        score, label = 2, "local_debt"
    else:
        score, label = 3, "clean"

    result = {
        "score": score,
        "label": label,
        "repo": repo,
        "remote": args.remote,
        "branch": args.branch,
        "details": details,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"push_health: {score}/3 ({label})")
        print(f"  uncommitted: {uc} bytes")
        print(f"  unpushed:    {up} commit(s)")
        print(f"  diverged:    {div}")

    # exit code mirrors score
    if score >= 2:
        sys.exit(0)
    elif score == 1:
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
