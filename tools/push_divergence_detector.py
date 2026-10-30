#!/usr/bin/env python3
"""Detect push divergence: local and remote have diverged, push will be rejected.

Usage: python3 tools/push_divergence_detector.py [--repo PATH]

Returns JSON:
  {
    "local_ahead": int,     # commits local has that remote doesn't
    "remote_ahead": int,    # commits remote has that local doesn't
    "diverged": bool,       # both sides have unique commits
    "push_will_fail": bool, # push will be rejected
    "fix": str              # recommended action
  }
"""

import argparse
import json
import os
import subprocess
import sys


def run(cmd, cwd=None):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def detect(repo="."):
    # Count commits local is ahead of remote
    rc, out, _ = run("git rev-list --count origin/main..HEAD", cwd=repo)
    local_ahead = int(out) if rc == 0 and out.isdigit() else 0

    # Count commits remote is ahead of local
    rc, out, _ = run("git rev-list --count HEAD..origin/main", cwd=repo)
    remote_ahead = int(out) if rc == 0 and out.isdigit() else 0

    diverged = local_ahead > 0 and remote_ahead > 0
    push_will_fail = remote_ahead > 0 and local_ahead > 0

    if push_will_fail:
        fix = "git fetch origin && git merge -X theirs origin/main && git push"
    elif remote_ahead > 0:
        fix = "git pull origin main"
    elif local_ahead > 0:
        fix = "git push origin main"
    else:
        fix = "nothing to do"

    return {
        "local_ahead": local_ahead,
        "remote_ahead": remote_ahead,
        "diverged": diverged,
        "push_will_fail": push_will_fail,
        "fix": fix,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()
    print(json.dumps(detect(args.repo), indent=2))
