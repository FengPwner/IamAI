#!/usr/bin/env python3
"""ghost_push_index.py — measure how disconnected local work is from remote.

the ghost push index is the fraction of commits that exist locally but
have never been pushed to the remote. it answers one question:

    "if this container dies right now, what fraction of our history vanishes?"

formula:
    ghost_push_index = unpushed_commits / total_commits

values:
    0.0  — fully pushed, no ghosts. healthy.
    0.1  — minor lag, likely a transient push failure. monitor.
    0.5  — half the work is unpushed. escalate.
    1.0  — every commit is a ghost. the remote has nothing. critical.

usage:
    python3 tools/ghost_push_index.py              # human-readable output
    python3 tools/ghost_push_index.py --json        # machine-readable output
    python3 tools/ghost_push_index.py --remedy      # include recovery instructions

exit codes:
    0 — index < 0.1 (healthy)
    1 — index >= 0.1 and < 0.5 (warning)
    2 — index >= 0.5 (critical)
    3 — error (no git repo, no commits, etc.)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def run_git(*args: str) -> tuple[int, str]:
    """Run a git command and return (exit_code, stdout)."""
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    return result.returncode, result.stdout.strip()


def get_total_commits() -> int:
    """Count total commits on current branch."""
    code, out = run_git("rev-list", "--count", "HEAD")
    if code != 0:
        return 0
    return int(out)


def get_unpushed_commits() -> int:
    """Count commits ahead of origin/main."""
    # try origin/main first, then origin/master, then fall back to total
    for remote_ref in ["origin/main", "origin/master"]:
        code, out = run_git("rev-list", "--count", f"{remote_ref}..HEAD")
        if code == 0:
            return int(out)
    # no remote tracking branch — everything is unpushed
    return get_total_commits()


def get_head_sha() -> str:
    code, out = run_git("rev-parse", "--short", "HEAD")
    return out if code == 0 else "unknown"


def get_public_key_instructions() -> str:
    """Generate copy-paste instructions for registering deploy key on github."""
    key_paths = [
        Path.home() / ".ssh" / "id_ed25519.pub",
        Path.home() / ".ssh" / "id_rsa.pub",
        REPO / ".ssh" / "id_ed25519.pub",
    ]
    for path in key_paths:
        if path.exists():
            pub_key = path.read_text().strip()
            return (
                f"Public key found at: {path}\n\n"
                f"To register on GitHub:\n"
                f"  1. Go to: https://github.com/FengPwner/IamAI/settings/keys\n"
                f"  2. Click 'Add deploy key'\n"
                f"  3. Title: caretaker-deploy-key\n"
                f"  4. Key: paste the following:\n\n"
                f"     {pub_key}\n\n"
                f"  5. Check 'Allow write access'\n"
                f"  6. Click 'Add deploy key'\n\n"
                f"Then run: cd {REPO} && git push origin main"
            )
    return (
        "No public key found. Generate one:\n"
        f"  ssh-keygen -t ed25519 -C 'caretaker@iamai' -f ~/.ssh/id_ed25519 -N ''\n"
        f"Then register it at:\n"
        f"  https://github.com/FengPwner/IamAI/settings/keys"
    )


def severity_label(index: float) -> str:
    if index < 0.1:
        return "HEALTHY"
    elif index < 0.5:
        return "WARNING"
    elif index < 1.0:
        return "CRITICAL"
    else:
        return "TOTAL_GHOST"


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure ghost push index")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--remedy", action="store_true", help="include recovery instructions")
    args = parser.parse_args()

    total = get_total_commits()
    if total == 0:
        if args.json:
            print(json.dumps({"error": "no commits found", "exit_code": 3}))
        else:
            print("error: no commits found in repository")
        return 3

    unpushed = get_unpushed_commits()
    index = unpushed / total
    head = get_head_sha()
    severity = severity_label(index)

    result = {
        "ghost_push_index": round(index, 4),
        "unpushed_commits": unpushed,
        "total_commits": total,
        "head_sha": head,
        "severity": severity,
        "repo_path": str(REPO),
    }

    if args.remedy:
        result["remedy"] = get_public_key_instructions()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"ghost push index: {index:.4f} ({severity})")
        print(f"  unpushed: {unpushed} / {total} commits")
        print(f"  head: {head}")
        if unpushed > 0:
            print(f"  risk: if this container dies, {unpushed} commits vanish")
        if args.remedy:
            print()
            print("recovery:")
            print(get_public_key_instructions())

    # exit code by severity
    if index < 0.1:
        return 0
    elif index < 0.5:
        return 1
    else:
        return 2


if __name__ == "__main__":
    sys.exit(main())
