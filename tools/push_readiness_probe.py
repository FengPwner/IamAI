#!/usr/bin/env python3
"""push_readiness_probe — fast pre-flight check before push.

Unlike push_chain_verifier (which diagnoses the whole write→commit→push
pipeline after the fact), this probe answers one question: *can we push
right now?*  It checks three things in under two seconds:

1. Deploy key exists and has correct permissions (0600)
2. SSH connection to github.com succeeds with the deploy key
3. Local branch is not behind remote (no surprise rebase needed)

Usage:
    python3 tools/push_readiness_probe.py           # human-readable
    python3 tools/push_readiness_probe.py --json     # machine-readable
    python3 tools/push_readiness_probe.py --fix      # attempt auto-repair

Exit codes:
    0 = ready to push
    1 = not ready (see output for what failed)
    2 = environment issue (no git, no ssh, repo not found)

Caretaker notes:
    - The --fix flag rescues the key to /tmp (FUSE permission workaround)
      and runs ssh-keyscan to refresh known_hosts. Both are idempotent.
    - Designed to be called from run_both.sh preflight and from
      caretaker visit scripts as a lightweight gate check.
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional


REPO = Path(__file__).resolve().parent.parent
SSH_KEY_WORKSPACE = REPO.parent / ".ssh" / "id_ed25519"
SSH_KEY_RESCUE = Path("/tmp/ssh_deploy_key")
KNOWN_HOSTS_WORKSPACE = REPO.parent / ".ssh" / "known_hosts"
REMOTE = "origin"


@dataclass
class ProbeResult:
    check: str
    passed: bool
    detail: str
    latency_ms: int = 0
    fixable: bool = False
    fixed: bool = False


def _run(cmd: List[str], timeout: int = 10, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    """Run a command with timeout, return CompletedProcess."""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=merged_env,
    )


def check_key_exists() -> ProbeResult:
    """Check that a deploy key file exists at the expected path."""
    t0 = time.monotonic()
    # Check rescued key first (run_both.sh puts it there)
    if SSH_KEY_RESCUE.exists():
        perms = oct(SSH_KEY_RESCUE.stat().st_mode)[-3:]
        if perms == "600":
            return ProbeResult(
                check="key_exists",
                passed=True,
                detail=f"rescued key at {SSH_KEY_RESCUE} (perms {perms})",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        else:
            return ProbeResult(
                check="key_exists",
                passed=False,
                detail=f"rescued key at {SSH_KEY_RESCUE} but perms={perms} (need 600)",
                latency_ms=int((time.monotonic() - t0) * 1000),
                fixable=True,
            )

    if SSH_KEY_WORKSPACE.exists():
        return ProbeResult(
            check="key_exists",
            passed=False,
            detail=f"workspace key at {SSH_KEY_WORKSPACE} exists but not rescued to /tmp",
            latency_ms=int((time.monotonic() - t0) * 1000),
            fixable=True,
        )

    return ProbeResult(
        check="key_exists",
        passed=False,
        detail=f"no deploy key found at {SSH_KEY_WORKSPACE} or {SSH_KEY_RESCUE}",
        latency_ms=int((time.monotonic() - t0) * 1000),
        fixable=False,
    )


def check_ssh_connection(key_path: str) -> ProbeResult:
    """Test SSH connection to GitHub with the deploy key."""
    t0 = time.monotonic()
    known_hosts = str(KNOWN_HOSTS_WORKSPACE) if KNOWN_HOSTS_WORKSPACE.exists() else "/dev/null"
    ssh_cmd = [
        "ssh",
        "-i", key_path,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={known_hosts}",
        "-o", "ConnectTimeout=5",
        "-T", "git@github.com",
    ]
    try:
        result = _run(ssh_cmd, timeout=10)
        latency = int((time.monotonic() - t0) * 1000)
        # GitHub returns exit 1 for successful auth (no shell access)
        combined = result.stdout + result.stderr
        if "successfully authenticated" in combined.lower():
            return ProbeResult(
                check="ssh_connection",
                passed=True,
                detail="authenticated to github.com via deploy key",
                latency_ms=latency,
            )
        elif "host key verification failed" in combined.lower():
            return ProbeResult(
                check="ssh_connection",
                passed=False,
                detail="host key verification failed — known_hosts needs update",
                latency_ms=latency,
                fixable=True,
            )
        elif "permission denied" in combined.lower():
            return ProbeResult(
                check="ssh_connection",
                passed=False,
                detail="permission denied — key not registered on GitHub",
                latency_ms=latency,
                fixable=False,
            )
        else:
            return ProbeResult(
                check="ssh_connection",
                passed=False,
                detail=f"unexpected SSH output: {combined.strip()[:120]}",
                latency_ms=latency,
                fixable=False,
            )
    except subprocess.TimeoutExpired:
        return ProbeResult(
            check="ssh_connection",
            passed=False,
            detail="SSH connection timed out (10s)",
            latency_ms=10000,
            fixable=False,
        )
    except FileNotFoundError:
        return ProbeResult(
            check="ssh_connection",
            passed=False,
            detail="ssh binary not found",
            latency_ms=int((time.monotonic() - t0) * 1000),
            fixable=False,
        )


def check_branch_sync(key_path: str) -> ProbeResult:
    """Check if local branch is up to date with remote."""
    t0 = time.monotonic()
    known_hosts = str(KNOWN_HOSTS_WORKSPACE) if KNOWN_HOSTS_WORKSPACE.exists() else "/dev/null"
    ssh_env = {
        "GIT_SSH_COMMAND": f"ssh -i {key_path} -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={known_hosts}"
    }
    try:
        # Fetch to update remote tracking refs
        fetch = _run(["git", "fetch", REMOTE, "--quiet"], timeout=15, env=ssh_env)
        if fetch.returncode != 0:
            return ProbeResult(
                check="branch_sync",
                passed=False,
                detail=f"git fetch failed: {fetch.stderr.strip()[:120]}",
                latency_ms=int((time.monotonic() - t0) * 1000),
                fixable=False,
            )

        # Compare local and remote HEAD
        local = _run(["git", "rev-parse", "HEAD"], timeout=5)
        remote = _run(["git", "rev-parse", f"{REMOTE}/main"], timeout=5)

        if local.returncode != 0 or remote.returncode != 0:
            return ProbeResult(
                check="branch_sync",
                passed=False,
                detail="could not resolve local or remote HEAD",
                latency_ms=int((time.monotonic() - t0) * 1000),
                fixable=False,
            )

        local_sha = local.stdout.strip()
        remote_sha = remote.stdout.strip()

        if local_sha == remote_sha:
            return ProbeResult(
                check="branch_sync",
                passed=True,
                detail=f"local and remote at same commit ({local_sha[:8]})",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )

        # Check if local is ahead, behind, or diverged
        merge_base = _run(
            ["git", "merge-base", "HEAD", f"{REMOTE}/main"], timeout=5
        )
        base_sha = merge_base.stdout.strip() if merge_base.returncode == 0 else ""

        latency = int((time.monotonic() - t0) * 1000)

        if base_sha == remote_sha:
            return ProbeResult(
                check="branch_sync",
                passed=True,
                detail=f"local ahead of remote ({local_sha[:8]} > {remote_sha[:8]}), push will fast-forward",
                latency_ms=latency,
            )
        elif base_sha == local_sha:
            return ProbeResult(
                check="branch_sync",
                passed=False,
                detail=f"local behind remote ({remote_sha[:8]}), need pull before push",
                latency_ms=latency,
                fixable=True,
            )
        else:
            return ProbeResult(
                check="branch_sync",
                passed=False,
                detail=f"branches diverged (base {base_sha[:8]}), need merge/rebase",
                latency_ms=latency,
                fixable=True,
            )

    except subprocess.TimeoutExpired:
        return ProbeResult(
            check="branch_sync",
            passed=False,
            detail="branch sync check timed out",
            latency_ms=15000,
            fixable=False,
        )


def fix_key_rescue() -> bool:
    """Rescue the deploy key to /tmp with correct permissions."""
    if SSH_KEY_WORKSPACE.exists():
        try:
            import shutil
            shutil.copy2(str(SSH_KEY_WORKSPACE), str(SSH_KEY_RESCUE))
            os.chmod(str(SSH_KEY_RESCUE), 0o600)
            return SSH_KEY_RESCUE.stat().st_mode & 0o777 == 0o600
        except OSError:
            return False
    return False


def fix_known_hosts() -> bool:
    """Run ssh-keyscan to update known_hosts."""
    if not KNOWN_HOSTS_WORKSPACE.exists():
        KNOWN_HOSTS_WORKSPACE.parent.mkdir(parents=True, exist_ok=True)
        KNOWN_HOSTS_WORKSPACE.touch()
    try:
        result = _run(["ssh-keyscan", "github.com"], timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            with open(str(KNOWN_HOSTS_WORKSPACE), "a") as f:
                f.write(result.stdout)
            return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    return False


def run_probe(fix: bool = False) -> List[ProbeResult]:
    """Run all readiness checks, optionally fix issues."""
    results = []

    # 1. Key existence
    key_check = check_key_exists()
    if not key_check.passed and fix and key_check.fixable:
        if fix_key_rescue():
            key_check = check_key_exists()
            key_check.fixed = True
    results.append(key_check)

    # Determine key path for subsequent checks
    key_path = str(SSH_KEY_RESCUE) if SSH_KEY_RESCUE.exists() else str(SSH_KEY_WORKSPACE)

    # 2. SSH connection
    ssh_check = check_ssh_connection(key_path)
    if not ssh_check.passed and fix and ssh_check.fixable:
        if "host key" in ssh_check.detail.lower():
            if fix_known_hosts():
                ssh_check = check_ssh_connection(key_path)
                ssh_check.fixed = True
    results.append(ssh_check)

    # 3. Branch sync (only if SSH is working)
    if ssh_check.passed:
        sync_check = check_branch_sync(key_path)
        results.append(sync_check)

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Push readiness probe for IamAI repo")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--fix", action="store_true", help="attempt auto-repair")
    args = parser.parse_args()

    if not REPO.is_dir():
        print(f"ERROR: repo not found at {REPO}", file=sys.stderr)
        sys.exit(2)

    results = run_probe(fix=args.fix)

    all_passed = all(r.passed for r in results)
    total_latency = sum(r.latency_ms for r in results)

    if args.json:
        output = {
            "ready": all_passed,
            "total_latency_ms": total_latency,
            "checks": [asdict(r) for r in results],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        print(json.dumps(output, indent=2))
    else:
        for r in results:
            status = "PASS" if r.passed else ("FIXED" if r.fixed else "FAIL")
            fix_tag = " [fixable]" if r.fixable and not r.passed and not r.fixed else ""
            print(f"  [{status}] {r.check}: {r.detail}{fix_tag} ({r.latency_ms}ms)")
        print()
        if all_passed:
            print(f"  READY to push (all checks passed in {total_latency}ms)")
        else:
            failed = [r for r in results if not r.passed]
            fixable = [r for r in failed if r.fixable]
            print(f"  NOT READY: {len(failed)} check(s) failed")
            if fixable and not args.fix:
                print(f"  {len(fixable)} issue(s) are auto-fixable — re-run with --fix")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
