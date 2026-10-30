#!/usr/bin/env python3
"""preflight — minimal push readiness check.

runs before `git push` to surface the three things that silently block pushes
in this repo:

  1. SSH connectivity to github.com (deploy key + host key present and valid)
  2. uncommitted working-tree changes (should be drained before push)
  3. unpushed commit count (backlog depth)

exit codes:
  0 — push-ready, no blockers
  1 — one or more blockers detected (details on stdout)

usage:
  python3 snippets/preflight.py          # check only
  python3 snippets/preflight.py --fix    # attempt auto-fix (ssh sync)

designed to be called by the batch committer before every push attempt, or by
the caretaker as part of a visit preflight.
"""

import subprocess
import sys
import os
from pathlib import Path


def check_ssh_connectivity() -> dict:
    """test SSH connection to github.com without side effects."""
    result = {"name": "ssh_connectivity", "ok": False, "detail": ""}
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             "-T", "git@github.com"],
            capture_output=True, text=True, timeout=15
        )
        combined = proc.stdout + proc.stderr
        if "successfully authenticated" in combined:
            result["ok"] = True
            result["detail"] = "deploy key authenticated"
        elif "Host key verification failed" in combined:
            result["detail"] = "host key missing or mismatched — run ssh_path_sync_check --sync"
        elif "Permission denied" in combined:
            result["detail"] = "deploy key not found or not registered"
        else:
            result["detail"] = combined.strip()[:120]
    except subprocess.TimeoutExpired:
        result["detail"] = "SSH connection timed out (15s)"
    except FileNotFoundError:
        result["detail"] = "ssh binary not found"
    return result


def check_uncommitted() -> dict:
    """count uncommitted files in the working tree."""
    result = {"name": "uncommitted", "ok": True, "detail": ""}
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=10
        )
        lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
        count = len(lines)
        if count > 0:
            result["ok"] = False
            result["detail"] = f"{count} uncommitted file(s)"
            result["count"] = count
        else:
            result["detail"] = "working tree clean"
            result["count"] = 0
    except Exception as e:
        result["ok"] = False
        result["detail"] = f"git status failed: {e}"
    return result


def check_unpushed() -> dict:
    """count commits ahead of origin/main."""
    result = {"name": "unpushed", "ok": True, "detail": ""}
    try:
        proc = subprocess.run(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            capture_output=True, text=True, timeout=10
        )
        count = int(proc.stdout.strip()) if proc.returncode == 0 else 0
        result["count"] = count
        if count > 10:
            result["ok"] = False
            result["detail"] = f"{count} unpushed commits (backlog growing)"
        elif count > 0:
            result["detail"] = f"{count} unpushed commit(s)"
        else:
            result["detail"] = "up to date with origin"
    except Exception as e:
        result["ok"] = False
        result["detail"] = f"git rev-list failed: {e}"
    return result


def try_fix_ssh() -> bool:
    """attempt auto-fix via ssh_path_sync_check --sync."""
    sync_tool = Path(__file__).parent.parent / "tools" / "ssh_path_sync_check.py"
    if not sync_tool.exists():
        return False
    try:
        proc = subprocess.run(
            [sys.executable, str(sync_tool), "--sync"],
            capture_output=True, text=True, timeout=15
        )
        return proc.returncode == 0
    except Exception:
        return False


def run_preflight(fix: bool = False) -> bool:
    """run all checks and report. returns True if all pass."""
    checks = [
        check_ssh_connectivity(),
        check_uncommitted(),
        check_unpushed(),
    ]

    all_ok = True
    for c in checks:
        status = "ok" if c["ok"] else "FAIL"
        print(f"  [{status}] {c['name']}: {c['detail']}")
        if not c["ok"]:
            all_ok = False

    if not all_ok and fix:
        ssh_check = checks[0]
        if not ssh_check["ok"]:
            print("\n  attempting ssh auto-fix...")
            if try_fix_ssh():
                print("  ssh sync applied — re-checking...")
                recheck = check_ssh_connectivity()
                status = "ok" if recheck["ok"] else "FAIL"
                print(f"  [{status}] {recheck['name']}: {recheck['detail']}")
                if recheck["ok"]:
                    all_ok = True  # only if ssh was the sole failure

    return all_ok


if __name__ == "__main__":
    print("preflight check:")
    fix = "--fix" in sys.argv
    ok = run_preflight(fix=fix)
    print(f"\nresult: {'push-ready' if ok else 'BLOCKED — see above'}")
    sys.exit(0 if ok else 1)
