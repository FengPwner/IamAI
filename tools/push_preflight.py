#!/usr/bin/env python3
"""Push preflight: checks SSH credential readiness before the batch committer tries to push.

Recurring failure pattern across caretaker visits 411, 414, 418, 438, 439:
the deploy key or known_hosts gets wiped when the container rebuilds, but nobody
notices until the batch committer fails its first push 10 minutes later. This
script runs the same checks the committer needs, in under a second, so a
caretaker can verify push health on arrival instead of discovering it on exit.

Exit codes:
    0 = all clear, push should work
    1 = one or more checks failed (details on stdout)
    2 = called with bad arguments

Usage:
    python3 tools/push_preflight.py [--remote origin] [--host github.com]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=10, **kw)


def check_deploy_key(key_path: Path) -> tuple[bool, str]:
    """Deploy key must exist and be mode 0600 (or 0400)."""
    if not key_path.is_file():
        return False, f"deploy key not found: {key_path}"
    mode = oct(key_path.stat().st_mode & 0o777)
    if mode not in ("0o600", "0o400"):
        return False, f"deploy key permissions {mode} (need 0600 or 0400): {key_path}"
    return True, f"deploy key OK: {key_path} ({mode})"


def check_known_hosts(host: str) -> tuple[bool, str]:
    """At least one of the expected known_hosts paths must contain an entry for `host`."""
    candidates = [
        Path.home() / ".ssh" / "known_hosts",
        REPO.parent / ".ssh" / "known_hosts",
    ]
    env_path = os.environ.get("GIT_SSH_COMMAND", "")
    if "UserKnownHostsFile=" in env_path:
        # extract path from GIT_SSH_COMMAND
        for token in env_path.split():
            if token.startswith("UserKnownHostsFile="):
                p = Path(token.split("=", 1)[1])
                if p not in candidates:
                    candidates.insert(0, p)

    for kh in candidates:
        if kh.is_file():
            try:
                text = kh.read_text(errors="replace")
                if any(line.strip().startswith(host) for line in text.splitlines()):
                    return True, f"known_hosts OK: {kh} has {host}"
            except OSError:
                continue

    return False, f"no known_hosts file contains an entry for {host} (checked {len(candidates)} paths)"


def check_ssh_connectivity(host: str, key_path: Path) -> tuple[bool, str]:
    """Attempt an SSH connection (auth test only, no shell)."""
    ssh_cmd = os.environ.get(
        "GIT_SSH_COMMAND",
        f"ssh -i {key_path} -o StrictHostKeyChecking=accept-new",
    )
    parts = ssh_cmd.split() + ["-T", f"git@{host}"]
    result = _run(parts)
    # GitHub returns exit 1 on successful auth-test (no shell access is normal)
    combined = (result.stdout + result.stderr).lower()
    if "successfully authenticated" in combined or "hi " in combined:
        return True, f"SSH auth OK: authenticated as {combined.split('hi ')[-1].split()[0] if 'hi ' in combined else 'deploy key'}"
    if "permission denied" in combined:
        return False, f"SSH auth FAILED: permission denied (key {key_path})"
    if "could not resolve" in combined:
        return False, f"DNS resolution failed for {host}"
    # Exit 1 with "no shell" is actually success for GitHub deploy keys
    if result.returncode in (0, 1) and "shell access" in combined:
        return True, "SSH auth OK (deploy key, no shell — expected)"
    return False, f"SSH connectivity uncertain (exit {result.returncode}): {combined[:200]}"


def check_remote_url(remote: str) -> tuple[bool, str]:
    """Verify the remote uses SSH (git@) not HTTPS, so deploy key applies."""
    result = _run(["git", "remote", "get-url", remote], cwd=REPO)
    if result.returncode != 0:
        return False, f"git remote '{remote}' not found"
    url = result.stdout.strip()
    if url.startswith("git@"):
        return True, f"remote '{remote}' is SSH: {url}"
    if url.startswith("https://"):
        return False, f"remote '{remote}' is HTTPS ({url}) — deploy key won't be used"
    return True, f"remote '{remote}' URL: {url}"


def run_checks(remote: str = "origin", host: str = "github.com") -> list[tuple[str, bool, str]]:
    """Run all preflight checks, return list of (name, ok, message)."""
    # Determine which key to check
    key_candidates = [
        Path("/tmp/ssh_deploy_key"),
        REPO.parent / ".ssh" / "id_ed25519",
    ]
    key_path = next((k for k in key_candidates if k.is_file()), key_candidates[0])

    checks = [
        ("deploy-key", check_deploy_key(key_path)),
        ("known-hosts", check_known_hosts(host)),
        ("remote-url", check_remote_url(remote)),
        ("ssh-auth", check_ssh_connectivity(host, key_path)),
    ]
    return [(name, ok, msg) for name, (ok, msg) in checks]


def main() -> int:
    parser = argparse.ArgumentParser(description="Push preflight: SSH credential readiness check")
    parser.add_argument("--remote", default="origin", help="Git remote name (default: origin)")
    parser.add_argument("--host", default="github.com", help="SSH host (default: github.com)")
    parser.add_argument("--json", action="store_true", help="Output as JSON lines")
    args = parser.parse_args()

    results = run_checks(remote=args.remote, host=args.host)
    all_ok = True
    for name, ok, msg in results:
        status = "OK" if ok else "FAIL"
        if not ok:
            all_ok = False
        if args.json:
            import json
            print(json.dumps({"check": name, "ok": ok, "message": msg}))
        else:
            print(f"[{status}] {name}: {msg}")

    if all_ok:
        print("\nPush preflight: all clear.")
        return 0
    else:
        print("\nPush preflight: FAILED — fix the issues above before pushing.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
