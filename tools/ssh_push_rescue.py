#!/usr/bin/env python3
"""ssh_push_rescue.py — one-shot SSH fix for git push to github.com.

consolidates three steps that the caretaker has been rediscovering every
visit since 108:

  1. copy the deploy key to /tmp with mode 0600 (FUSE workspace forces 0777)
  2. populate known_hosts with github.com's host keys (ssh-keyscan)
  3. export GIT_SSH_COMMAND so git subprocesses use the rescued key

exit codes:
  0 — rescue complete, push should work
  1 — no key file found anywhere
  2 — permission fix failed (e.g. /tmp not writable)
  3 — ssh-keyscan failed (network issue)
  4 — test push failed (key not registered or network down)

usage:
  python3 tools/ssh_push_rescue.py [--dry-run] [--json]
  --dry-run  show what would be done without doing it
  --json     output machine-readable report
"""

import json
import os
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GITHUB_HOST = "github.com"
DRY_RUN = "--dry-run" in sys.argv
JSON_OUT = "--json" in sys.argv

KEY_CANDIDATES = [
    os.path.join(REPO, "..", ".ssh", "id_ed25519"),
    os.path.expanduser("~/.ssh/id_ed25519"),
    os.path.expanduser("~/.ssh/id_rsa"),
    "/tmp/ssh_deploy_key",
    "/tmp/iamai_key",
]

KNOWN_HOSTS_PATHS = [
    os.path.expanduser("~/.ssh/known_hosts"),
    "/root/.ssh/known_hosts",
]

RESCUED_KEY_PATH = "/tmp/ssh_deploy_key"


def log(msg, level="info"):
    if not JSON_OUT:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        print(f"[{ts}] [{level}] {msg}")


def find_key():
    """return the first readable private key path, or None."""
    for path in KEY_CANDIDATES:
        resolved = os.path.realpath(path)
        if os.path.isfile(resolved) and os.access(resolved, os.R_OK):
            return resolved
    return None


def rescue_key(key_src):
    """copy key to /tmp with mode 0600. return rescued path or None."""
    if DRY_RUN:
        log(f"[dry-run] would copy {key_src} -> {RESCUED_KEY_PATH} with mode 0600")
        return RESCUED_KEY_PATH
    try:
        import shutil
        shutil.copy2(key_src, RESCUED_KEY_PATH)
        os.chmod(RESCUED_KEY_PATH, 0o600)
        mode = os.stat(RESCUED_KEY_PATH).st_mode & 0o777
        if mode != 0o600:
            log(f"permission fix failed: mode is {oct(mode)}", "error")
            return None
        log(f"key rescued: {key_src} -> {RESCUED_KEY_PATH} (mode 0600)")
        return RESCUED_KEY_PATH
    except Exception as e:
        log(f"key rescue failed: {e}", "error")
        return None


def populate_known_hosts():
    """run ssh-keyscan for github.com and append to known_hosts. return True on success."""
    if DRY_RUN:
        log(f"[dry-run] would run ssh-keyscan {GITHUB_HOST} >> known_hosts")
        return True

    # check if github.com is already in any known_hosts file
    for kh_path in KNOWN_HOSTS_PATHS:
        if os.path.isfile(kh_path):
            try:
                with open(kh_path, "r") as f:
                    for line in f:
                        if line.strip().startswith(GITHUB_HOST):
                            log(f"github.com already in {kh_path}")
                            return True
            except Exception:
                pass

    # run ssh-keyscan
    try:
        result = subprocess.run(
            ["ssh-keyscan", GITHUB_HOST],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            log(f"ssh-keyscan failed: {result.stderr.strip()}", "error")
            return False

        keys = result.stdout.strip()
        if not keys:
            log("ssh-keyscan returned empty output", "error")
            return False

        # write to the first writable known_hosts path
        for kh_path in KNOWN_HOSTS_PATHS:
            kh_dir = os.path.dirname(kh_path)
            if not os.path.isdir(kh_dir):
                try:
                    os.makedirs(kh_dir, mode=0o700, exist_ok=True)
                except Exception:
                    continue
            try:
                with open(kh_path, "a") as f:
                    f.write(keys + "\n")
                log(f"appended {len(keys.splitlines())} host keys to {kh_path}")
                return True
            except Exception as e:
                log(f"could not write to {kh_path}: {e}", "warn")
                continue

        log("no writable known_hosts path found", "error")
        return False
    except subprocess.TimeoutExpired:
        log("ssh-keyscan timed out (15s)", "error")
        return False
    except Exception as e:
        log(f"ssh-keyscan exception: {e}", "error")
        return False


def build_ssh_command(key_path):
    """return the GIT_SSH_COMMAND string."""
    return f"ssh -i {key_path} -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={KNOWN_HOSTS_PATHS[0]}"


def test_push(ssh_cmd):
    """attempt a dry-run push test via ssh to github.com. return True if auth succeeds."""
    if DRY_RUN:
        log("[dry-run] would test ssh -T git@github.com")
        return True

    try:
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = ssh_cmd
        result = subprocess.run(
            ["ssh", "-i", RESCUED_KEY_PATH,
             "-o", "StrictHostKeyChecking=accept-new",
             "-T", "git@github.com"],
            capture_output=True, text=True, timeout=15, env=env
        )
        # github returns exit 1 with "Hi <user>! You've successfully authenticated"
        output = (result.stdout + result.stderr).strip()
        if "successfully authenticated" in output.lower():
            log(f"push test passed: {output.splitlines()[0]}")
            return True
        elif "permission denied" in output.lower():
            log(f"push test failed (key not registered): {output.splitlines()[0]}", "error")
            return False
        else:
            log(f"push test inconclusive (exit {result.returncode}): {output[:120]}", "warn")
            return None
    except subprocess.TimeoutExpired:
        log("push test timed out (15s)", "error")
        return False
    except Exception as e:
        log(f"push test exception: {e}", "error")
        return False


def run():
    """main rescue flow. returns (exit_code, report_dict)."""
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dry_run": DRY_RUN,
        "key_found": None,
        "key_rescued": False,
        "known_hosts_ok": False,
        "ssh_command": None,
        "push_test": None,
        "exit_code": 0,
    }

    # step 1: find key
    key_src = find_key()
    if not key_src:
        log("no private key found in any candidate path", "error")
        report["exit_code"] = 1
        return 1, report
    report["key_found"] = key_src
    log(f"found key: {key_src}")

    # step 2: rescue key to /tmp with correct permissions
    rescued = rescue_key(key_src)
    if not rescued:
        report["exit_code"] = 2
        return 2, report
    report["key_rescued"] = True

    # step 3: populate known_hosts
    kh_ok = populate_known_hosts()
    report["known_hosts_ok"] = kh_ok
    if not kh_ok:
        report["exit_code"] = 3
        return 3, report

    # step 4: build and export SSH command
    ssh_cmd = build_ssh_command(RESCUED_KEY_PATH)
    report["ssh_command"] = ssh_cmd
    log(f"GIT_SSH_COMMAND={ssh_cmd}")

    # step 5: test push
    push_ok = test_push(ssh_cmd)
    report["push_test"] = push_ok
    if push_ok is False:
        report["exit_code"] = 4
        return 4, report

    report["exit_code"] = 0
    return 0, report


def main():
    exit_code, report = run()
    if JSON_OUT:
        print(json.dumps(report, indent=2))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
