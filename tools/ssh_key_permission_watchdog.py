#!/usr/bin/env python3
"""ssh_key_permission_watchdog.py — detect and rescue SSH keys with broken permissions.

the workspace filesystem (FUSE / network mount) forces mode 0777 on all files,
making OpenSSH refuse the deploy key. this tool:

1. detects when the primary key has mode > 0600
2. copies it to a rescued location (/tmp) with proper 0600 permissions
3. optionally verifies the rescued key authenticates against GitHub
4. prints the GIT_SSH_COMMAND needed to use the rescued copy

exit codes:
  0 — key permissions are fine, no rescue needed
  1 — key rescued successfully
  2 — primary key file not found
  3 — rescue copy failed
  4 — rescued key failed SSH authentication

usage:
  python3 tools/ssh_key_permission_watchdog.py [--verify] [--json]
  --verify  test SSH connection to github.com after rescue
  --json    output structured JSON report
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIMARY_KEY = os.path.expanduser("~/.ssh/id_ed25519")
RESCUE_KEY = "/tmp/ssh_deploy_key"
GITHUB_HOST = "github.com"
VERIFY = "--verify" in sys.argv
JSON_OUT = "--json" in sys.argv


def log(msg, level="info"):
    if not JSON_OUT:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        print(f"[{ts}] [{level}] {msg}")


def get_file_mode(path):
    """return the octal permission bits of a file."""
    return stat.S_IMODE(os.stat(path).st_mode)


def check_primary_key():
    """check if the primary key exists and has correct permissions."""
    if not os.path.isfile(PRIMARY_KEY):
        return {"status": "missing", "path": PRIMARY_KEY}
    mode = get_file_mode(PRIMARY_KEY)
    return {
        "status": "ok" if mode <= 0o600 else "too_open",
        "path": PRIMARY_KEY,
        "mode": oct(mode),
    }


def rescue_key():
    """copy the primary key to a tmpfs location with proper permissions."""
    if not os.path.isfile(PRIMARY_KEY):
        return None
    try:
        shutil.copy2(PRIMARY_KEY, RESCUE_KEY)
        os.chmod(RESCUE_KEY, 0o600)
        rescued_mode = get_file_mode(RESCUE_KEY)
        if rescued_mode != 0o600:
            log(f"rescue copy also has bad permissions: {oct(rescued_mode)}", "error")
            return None
        log(f"key rescued to {RESCUE_KEY} with mode {oct(rescued_mode)}")
        return RESCUE_KEY
    except (OSError, shutil.Error) as e:
        log(f"rescue failed: {e}", "error")
        return None


def verify_ssh(key_path):
    """test SSH connection to GitHub with the given key."""
    env = os.environ.copy()
    cmd = [
        "ssh", "-i", key_path,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        "-T", f"git@{GITHUB_HOST}",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, env=env
        )
        # GitHub returns exit 1 on successful auth (no shell access)
        authenticated = (
            result.returncode in (0, 1)
            and "successfully authenticated" in result.stderr
        )
        return {
            "authenticated": authenticated,
            "exit_code": result.returncode,
            "stderr": result.stderr.strip()[:500],
        }
    except subprocess.TimeoutExpired:
        return {"authenticated": False, "exit_code": -1, "stderr": "timeout"}
    except FileNotFoundError:
        return {"authenticated": False, "exit_code": -2, "stderr": "ssh not found"}


def git_ssh_command(key_path):
    """return the GIT_SSH_COMMAND env var value for the rescued key."""
    return f"ssh -i {key_path} -o StrictHostKeyChecking=accept-new"


def main():
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "primary_key": check_primary_key(),
        "rescue_needed": False,
        "rescue_path": None,
        "git_ssh_command": None,
        "verification": None,
        "exit_code": 0,
    }

    pk = report["primary_key"]

    if pk["status"] == "missing":
        log(f"primary key not found: {PRIMARY_KEY}", "error")
        report["exit_code"] = 2
        if JSON_OUT:
            print(json.dumps(report, indent=2))
        return report["exit_code"]

    if pk["status"] == "ok":
        log(f"primary key permissions OK: {pk['mode']}")
        if JSON_OUT:
            print(json.dumps(report, indent=2))
        return 0

    # permissions too open — attempt rescue
    report["rescue_needed"] = True
    log(f"primary key mode {pk['mode']} is too open, attempting rescue")

    rescued = rescue_key()
    if not rescued:
        log("rescue failed", "error")
        report["exit_code"] = 3
        if JSON_OUT:
            print(json.dumps(report, indent=2))
        return report["exit_code"]

    report["rescue_path"] = rescued
    report["git_ssh_command"] = git_ssh_command(rescued)
    report["exit_code"] = 1

    if VERIFY:
        log("verifying rescued key against GitHub...")
        v = verify_ssh(rescued)
        report["verification"] = v
        if not v["authenticated"]:
            log(f"verification failed: {v['stderr'][:200]}", "error")
            report["exit_code"] = 4
        else:
            log("rescued key authenticated successfully")

    if JSON_OUT:
        print(json.dumps(report, indent=2))
    else:
        if report["exit_code"] == 1:
            print(f"\nexport GIT_SSH_COMMAND='{report['git_ssh_command']}'")

    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
