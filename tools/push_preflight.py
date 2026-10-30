#!/usr/bin/env python3
"""push_preflight.py — diagnose push prerequisites before attempting push.

the caretaker calls this before `git push`. if any check fails, the caretaker
skips the push attempt and logs the failure mode. this avoids filling the log
with identical `Permission denied` messages every ten minutes.

exit codes:
  0 — all prerequisites met, push should succeed
  1 — key file missing or unreadable
  2 — key permissions too open (and cannot be fixed)
  3 — known_hosts missing github.com entry
  4 — ssh connection to github failed (network or key not registered)
  5 — git remote not configured

usage:
  python3 tools/push_preflight.py [--fix]
  --fix  attempt automatic fixes (copy key to /tmp, run ssh-keyscan)
"""

import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GITHUB_HOST = "github.com"
FIX = "--fix" in sys.argv


def log(msg, level="info"):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"[{ts}] [{level}] {msg}")


def check_key_file():
    """check that an ssh private key exists and is readable."""
    candidates = [
        os.path.expanduser("~/.ssh/id_ed25519"),
        os.path.expanduser("~/.ssh/id_rsa"),
        "/root/.ssh/id_ed25519",
        "/tmp/iamai_key",
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.R_OK):
            return path
    return None


def check_key_permissions(key_path):
    """check that key permissions are 0600 or stricter."""
    if not key_path:
        return None
    stat = os.stat(key_path)
    mode = stat.st_mode & 0o777
    if mode > 0o600:
        return mode
    return None


def fix_key_permissions(key_path):
    """attempt to fix key permissions by copying to /tmp."""
    tmp_key = "/tmp/iamai_key"
    try:
        import shutil
        shutil.copy2(key_path, tmp_key)
        os.chmod(tmp_key, 0o600)
        log(f"copied key to {tmp_key} with mode 0600", "fix")
        return tmp_key
    except Exception as e:
        log(f"cannot fix permissions: {e}", "error")
        return None


def check_known_hosts():
    """check that github.com is in known_hosts."""
    known_hosts_paths = [
        os.path.expanduser("~/.ssh/known_hosts"),
        "/root/.ssh/known_hosts",
    ]
    for path in known_hosts_paths:
        if os.path.isfile(path):
            with open(path, "r") as f:
                content = f.read()
            if GITHUB_HOST in content:
                return path
    return None


def fix_known_hosts():
    """run ssh-keyscan to populate known_hosts."""
    try:
        result = subprocess.run(
            ["ssh-keyscan", "-t", "ed25519,rsa", GITHUB_HOST],
            capture_output=True, text=True, timeout=10,
        )
        if result.stdout:
            hosts_dir = os.path.expanduser("~/.ssh")
            os.makedirs(hosts_dir, exist_ok=True)
            hosts_file = os.path.join(hosts_dir, "known_hosts")
            with open(hosts_file, "a") as f:
                f.write(result.stdout)
            log(f"added {GITHUB_HOST} to {hosts_file}", "fix")
            return hosts_file
    except Exception as e:
        log(f"ssh-keyscan failed: {e}", "error")
    return None


def check_ssh_connection(key_path):
    """test ssh connection to github."""
    env = os.environ.copy()
    env["DISPLAY"] = ""
    env["SSH_ASKPASS"] = ""
    cmd = [
        "ssh", "-T", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=5",
    ]
    if key_path:
        cmd.extend(["-i", key_path])
    cmd.append(f"git@{GITHUB_HOST}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, env=env,
        )
        # github returns exit 1 with "Hi <user>!" on success
        if "Hi " in result.stderr or "Hi " in result.stdout:
            return True
        if "Permission denied" in result.stderr:
            log("key not registered with github", "error")
            return False
        log(f"ssh returned: {result.stderr.strip()}", "warn")
        return False
    except subprocess.TimeoutExpired:
        log("ssh connection timed out", "error")
        return False
    except Exception as e:
        log(f"ssh check failed: {e}", "error")
        return False


def check_remote():
    """check that git remote is configured."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=REPO,
        )
        if result.returncode == 0 and GITHUB_HOST in result.stdout:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def main():
    report = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checks": {}}

    # check 1: remote
    remote = check_remote()
    report["checks"]["remote"] = {"ok": bool(remote), "value": remote}
    if not remote:
        log("no git remote configured", "error")
        print(json.dumps(report, indent=2))
        return 5

    # check 2: key file
    key_path = check_key_file()
    report["checks"]["key_file"] = {"ok": bool(key_path), "path": key_path}
    if not key_path:
        log("no ssh private key found", "error")
        print(json.dumps(report, indent=2))
        return 1

    # check 3: permissions
    bad_mode = check_key_permissions(key_path)
    if bad_mode:
        log(f"key permissions too open: {oct(bad_mode)}", "warn")
        if FIX:
            fixed = fix_key_permissions(key_path)
            if fixed:
                key_path = fixed
                bad_mode = None
        if bad_mode:
            report["checks"]["permissions"] = {"ok": False, "mode": oct(bad_mode)}
            print(json.dumps(report, indent=2))
            return 2
        else:
            report["checks"]["permissions"] = {"ok": True, "fixed": True}
    else:
        report["checks"]["permissions"] = {"ok": True}

    # check 4: known_hosts
    hosts_file = check_known_hosts()
    if not hosts_file:
        log(f"{GITHUB_HOST} not in known_hosts", "warn")
        if FIX:
            hosts_file = fix_known_hosts()
        report["checks"]["known_hosts"] = {"ok": False}
        if not hosts_file:
            print(json.dumps(report, indent=2))
            return 3
    else:
        report["checks"]["known_hosts"] = {"ok": True, "path": hosts_file}

    # check 5: ssh connection
    connected = check_ssh_connection(key_path)
    report["checks"]["ssh_connection"] = {"ok": connected}
    if not connected:
        log("push preflight failed: ssh connection rejected", "error")
        print(json.dumps(report, indent=2))
        return 4

    log("all push prerequisites met", "ok")
    report["ok"] = True
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
