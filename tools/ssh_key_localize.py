#!/usr/bin/env python3
"""ssh_key_localize.py — detect and fix SSH keys on permission-hostile filesystems.

problem:
  the workspace is an OSS-backed FUSE mount that forces mode 0777 on every
  file.  OpenSSH refuses private keys with permissions wider than 0600, so
  `ssh -i <workspace_key>` always fails with "UNPROTECTED PRIVATE KEY FILE".
  copying the key to /tmp (tmpfs) restores proper permission semantics.

what this tool does:
  1. scans candidate key paths (workspace .ssh/, home .ssh/, /tmp/)
  2. checks whether each key lives on a filesystem that honours chmod
  3. if the active key is on a hostile fs, copies it to /tmp/<name> with 0600
  4. optionally writes core.sshCommand into .git/config so every git
     subprocess picks up the localised key automatically

exit codes:
  0 — key already localised (no action needed) or fix applied successfully
  1 — no key found anywhere
  2 — copy or chmod failed (e.g. /tmp read-only)
  3 — git config write failed

usage:
  python3 tools/ssh_key_localize.py [--dry-run] [--json] [--configure-git]
  --dry-run        show what would be done without doing it
  --json           output machine-readable report
  --configure-git  also set core.sshCommand in .git/config
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GITHUB_HOST = "github.com"
DRY_RUN = "--dry-run" in sys.argv
JSON_OUT = "--json" in sys.argv
CONFIGURE_GIT = "--configure-git" in sys.argv

# ── helpers ──────────────────────────────────────────────────────────────


def _chmod_works(path: str) -> bool:
    """return True if the filesystem at *path* honours chmod."""
    probe = os.path.join(path, ".chmod_probe")
    try:
        with open(probe, "w") as f:
            f.write("")
        os.chmod(probe, 0o600)
        mode = os.stat(probe).st_mode & 0o777
        os.unlink(probe)
        return mode == 0o600
    except OSError:
        return False


def _find_keys() -> list[dict]:
    """scan well-known locations for SSH private keys."""
    candidates = []
    search_dirs = [
        os.path.join(REPO, "..", ".ssh"),
        os.path.expanduser("~/.ssh"),
        "/tmp",
    ]
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            full = os.path.join(d, name)
            if not os.path.isfile(full):
                continue
            try:
                with open(full) as f:
                    head = f.read(32)
            except (OSError, UnicodeDecodeError):
                continue
            if "PRIVATE KEY" in head:
                mode = os.stat(full).st_mode & 0o777
                candidates.append({
                    "path": os.path.realpath(full),
                    "original_path": full,
                    "mode": oct(mode),
                    "mode_int": mode,
                    "fs_chmod_ok": _chmod_works(d),
                    "safe_mode": mode <= 0o600,
                })
    return candidates


def _localize_key(src: str, dest_dir: str = "/tmp") -> str:
    """copy *src* to dest_dir with mode 0600.  return the new path."""
    base = os.path.basename(src)
    if base.startswith("id_"):
        local_name = f"localised_{base}"
    else:
        local_name = f"localised_{base}"
    dest = os.path.join(dest_dir, local_name)
    if DRY_RUN:
        return dest
    shutil.copy2(src, dest)
    os.chmod(dest, 0o600)
    return dest


def _git_ssh_command(key_path: str) -> str:
    """build the GIT_SSH_COMMAND value for a given key."""
    return (
        f"ssh -i {key_path} "
        f"-o StrictHostKeyChecking=no "
        f"-o BatchMode=yes"
    )


# ── main ─────────────────────────────────────────────────────────────────


def run() -> dict:
    keys = _find_keys()
    report: dict = {
        "keys_found": len(keys),
        "keys": keys,
        "action": "none",
        "localised_path": None,
        "git_configured": False,
    }

    if not keys:
        report["error"] = "no SSH private key found in any candidate directory"
        return report

    # prefer a key that already has safe permissions
    safe_keys = [k for k in keys if k["safe_mode"]]
    if safe_keys:
        report["action"] = "none"
        report["localised_path"] = safe_keys[0]["path"]
        if CONFIGURE_GIT:
            cmd = _git_ssh_command(safe_keys[0]["path"])
            if not DRY_RUN:
                subprocess.run(
                    ["git", "config", "core.sshCommand", cmd],
                    cwd=REPO,
                    check=True,
                )
            report["git_configured"] = True
            report["ssh_command"] = cmd
        return report

    # all keys are on hostile fs — localise the first one
    src = keys[0]["original_path"]
    dest = _localize_key(src)
    report["action"] = "localised"
    report["localised_path"] = dest
    report["source"] = src

    if CONFIGURE_GIT:
        cmd = _git_ssh_command(dest)
        if not DRY_RUN:
            try:
                subprocess.run(
                    ["git", "config", "core.sshCommand", cmd],
                    cwd=REPO,
                    check=True,
                )
                report["git_configured"] = True
            except subprocess.CalledProcessError:
                report["git_configured"] = False
                report["error"] = "git config failed"
                report["_exit"] = 3
                return report
        report["ssh_command"] = cmd

    return report


def main() -> None:
    report = run()
    if JSON_OUT:
        print(json.dumps(report, indent=2))
    else:
        action = report["action"]
        if action == "none" and report.get("localised_path"):
            print(f"key already safe: {report['localised_path']}")
        elif action == "localised":
            print(f"localised {report.get('source', '?')} → {report['localised_path']}")
        else:
            print(f"no fixable key: {report.get('error', 'unknown')}")
        if report.get("git_configured"):
            print(f"git core.sshCommand set: {report.get('ssh_command', '')}")

    exit_code = report.get("_exit", 0 if report["action"] != "none" or report.get("localised_path") else 1)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
