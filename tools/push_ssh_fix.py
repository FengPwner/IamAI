#!/usr/bin/env python3
"""push_ssh_fix: detect and repair SSH key permission failures on overlay filesystems.

Fourth push failure mode (first seen visit 441, 2026-10-31):

The workspace runs on an overlay/FUSE filesystem that forces all file
permissions to 0777. SSH refuses private keys with world-readable
permissions, so `git push` fails with "UNPROTECTED PRIVATE KEY FILE"
even though the key content is correct.

This script:
1. Detects whether the configured deploy key has broken permissions
2. If so, copies it to /tmp (a tmpfs that respects chmod)
3. Sets git core.sshCommand to use the /tmp copy
4. Verifies authentication with `ssh -T git@github.com`

Complements:
- push_preflight.py  — detects missing keys (credential check)
- push_sync.py       — handles remote divergence (sync check)

Exit codes:
    0 = fixed or already healthy
    1 = could not fix (details on stdout)

Usage:
    python3 tools/push_ssh_fix.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKSPACE_SSH = Path.home() / ".ssh"
TMP_KEY = Path("/tmp/ssh_deploy_key")
KNOWN_KEY_LOCATIONS = [
    WORKSPACE_SSH / "id_ed25519",
    Path("/root/.ssh/id_ed25519"),
    TMP_KEY,
]


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if TMP_KEY.exists():
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {TMP_KEY} -o StrictHostKeyChecking=no "
            f"-o UserKnownHostsFile={WORKSPACE_SSH / 'known_hosts'}"
        )
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=env, **kw)


def find_working_key() -> Path | None:
    """Return the first key path that SSH accepts."""
    for kp in KNOWN_KEY_LOCATIONS:
        if not kp.is_file():
            continue
        r = _run(["ssh", "-i", str(kp), "-o", "StrictHostKeyChecking=no",
                   "-T", "git@github.com"])
        # GitHub returns exit 1 with "Hi <repo>!" on stderr for deploy keys
        if "successfully authenticated" in (r.stderr or ""):
            return kp
    return None


def key_permissions_ok(key_path: Path) -> bool:
    mode = key_path.stat().st_mode & 0o777
    return mode in (stat.S_IRUSR | stat.S_IWUSR, stat.S_IRUSR)  # 0600 or 0400


def chmod_strict(path: Path, mode: int) -> bool:
    """Try chmod; return True if the resulting mode matches."""
    try:
        os.chmod(path, mode)
        return (path.stat().st_mode & 0o777) == mode
    except OSError:
        return False


def rescue_key_to_tmp(source: Path, dry_run: bool = False) -> Path | None:
    """Copy key to /tmp and set 0600. Returns the new path or None."""
    dest = TMP_KEY
    if dry_run:
        print(f"[dry-run] would copy {source} -> {dest} and chmod 0600")
        return dest
    try:
        shutil.copy2(source, dest)
        os.chmod(dest, 0o600)
        if (dest.stat().st_mode & 0o777) == 0o600:
            return dest
        print(f"copy succeeded but chmod did not stick on {dest}")
        return None
    except (OSError, shutil.Error) as e:
        print(f"failed to rescue key: {e}")
        return None


def configure_git_ssh(key_path: Path, dry_run: bool = False) -> bool:
    """Set core.sshCommand in the repo to use the rescued key."""
    ssh_cmd = (
        f"ssh -i {key_path} -o StrictHostKeyChecking=no "
        f"-o UserKnownHostsFile={WORKSPACE_SSH / 'known_hosts'}"
    )
    if dry_run:
        print(f"[dry-run] git config core.sshCommand = {ssh_cmd!r}")
        return True
    r = _run(["git", "config", "core.sshCommand", ssh_cmd], cwd=REPO)
    return r.returncode == 0


def verify_push(dry_run: bool = False) -> bool:
    if dry_run:
        print("[dry-run] would run: git push origin main --dry-run")
        return True
    r = _run(["git", "push", "origin", "main", "--dry-run"], cwd=REPO)
    return r.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Fix SSH key permission on overlay fs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Step 1: find any existing key
    source_key = None
    for kp in KNOWN_KEY_LOCATIONS:
        if kp.is_file():
            source_key = kp
            break
    if source_key is None:
        print("no deploy key found at any known location")
        return 1

    # Step 2: check if it already works
    if key_permissions_ok(source_key):
        print(f"key {source_key} has correct permissions — nothing to fix")
        # Still ensure git config is right
        configure_git_ssh(source_key, dry_run=args.dry_run)
        return 0

    # Step 3: try chmod in place (might work on real fs)
    if chmod_strict(source_key, 0o600):
        print(f"chmod 0600 succeeded on {source_key}")
        configure_git_ssh(source_key, dry_run=args.dry_run)
        return 0

    # Step 4: overlay fs detected — rescue to /tmp
    print(f"overlay fs detected: {source_key} stuck at 0777, rescuing to /tmp")
    rescued = rescue_key_to_tmp(source_key, dry_run=args.dry_run)
    if rescued is None:
        print("rescue failed")
        return 1

    # Step 5: configure git to use rescued key
    if not configure_git_ssh(rescued, dry_run=args.dry_run):
        print("failed to configure git core.sshCommand")
        return 1

    # Step 6: verify
    if verify_push(dry_run=args.dry_run):
        print(f"push verified using key at {rescued}")
        return 0
    else:
        print("push verification failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
