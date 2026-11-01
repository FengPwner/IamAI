#!/usr/bin/env python3
"""Auto-resolve push divergence: fetch, detect, merge (prefer theirs), push.

Designed for the caretaker flow: when the batch committer gets a push rejection,
this tool can be called to resolve it automatically.

Usage: python3 tools/push_auto_merge.py [--repo PATH] [--dry-run]

Returns JSON:
  {
    "diverged": bool,
    "merged": bool,
    "pushed": bool,
    "conflicts": int,
    "strategy": str,
    "error": str | None
  }

Strategy:
  - If only remote is ahead: fast-forward (git pull --ff-only)
  - If both sides diverged: merge with -X theirs (remote wins on conflicts)
  - If only local is ahead: just push
  - If clean: nothing to do

Why -X theirs: in a multi-writer repo, the remote already has consensus.
Our local uncommitted work is more valuable than our local commits, so we
let remote win textual conflicts and fix up by hand only if truly needed.
"""

import argparse
import json
import os
import subprocess
import sys


def run(cmd, cwd=None, env=None):
    merged_env = None
    if env:
        merged_env = os.environ.copy()
        merged_env.update(env)
    r = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=cwd, env=merged_env
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def ssh_env():
    """Build GIT_SSH_COMMAND if deploy key exists at the well-known path."""
    key = "/tmp/ssh_deploy_key"
    if os.path.isfile(key):
        return {
            "GIT_SSH_COMMAND": (
                f"ssh -i {key} -o StrictHostKeyChecking=no "
                "-o UserKnownHostsFile=/dev/null"
            )
        }
    return {}


def auto_merge(repo=".", dry_run=False):
    env = ssh_env()
    result = {
        "diverged": False,
        "merged": False,
        "pushed": False,
        "conflicts": 0,
        "strategy": "none",
        "error": None,
    }

    # 1. Fetch
    rc, _, err = run("git fetch origin main", cwd=repo, env=env)
    if rc != 0:
        result["error"] = f"fetch failed: {err}"
        return result

    # 2. Count ahead/behind
    rc, la, _ = run("git rev-list --count origin/main..HEAD", cwd=repo)
    local_ahead = int(la) if rc == 0 and la.isdigit() else 0

    rc, ra, _ = run("git rev-list --count HEAD..origin/main", cwd=repo)
    remote_ahead = int(ra) if rc == 0 and ra.isdigit() else 0

    if local_ahead == 0 and remote_ahead == 0:
        result["strategy"] = "clean"
        return result

    if local_ahead > 0 and remote_ahead > 0:
        result["diverged"] = True

    if dry_run:
        result["strategy"] = (
            "merge-theirs" if result["diverged"]
            else "ff-only" if remote_ahead > 0
            else "push-only"
        )
        return result

    # 3. Choose strategy
    if remote_ahead > 0 and local_ahead == 0:
        # Fast-forward
        result["strategy"] = "ff-only"
        rc, _, err = run("git merge --ff-only origin/main", cwd=repo)
        if rc != 0:
            result["error"] = f"ff-only failed: {err}"
            return result
        result["merged"] = True

    elif local_ahead > 0 and remote_ahead > 0:
        # Diverged: merge with theirs preference
        result["strategy"] = "merge-theirs"
        rc, out, err = run(
            "git merge -X theirs origin/main --no-edit", cwd=repo
        )
        if rc != 0:
            # Count conflicts if any
            rc2, cout, _ = run(
                "git diff --name-only --diff-filter=U", cwd=repo
            )
            result["conflicts"] = len(cout.splitlines()) if cout else 0
            result["error"] = f"merge failed ({result['conflicts']} conflicts): {err}"
            # Abort the merge to leave the repo clean
            run("git merge --abort", cwd=repo)
            return result
        result["merged"] = True

    elif local_ahead > 0 and remote_ahead == 0:
        result["strategy"] = "push-only"

    # 4. Push
    rc, out, err = run("git push origin main", cwd=repo, env=env)
    if rc != 0:
        result["error"] = f"push failed: {err}"
        return result
    result["pushed"] = True

    return result


def main():
    parser = argparse.ArgumentParser(description="Auto-resolve push divergence")
    parser.add_argument("--repo", default=".", help="path to repo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = auto_merge(repo=args.repo, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("error") is None else 1)


if __name__ == "__main__":
    main()
