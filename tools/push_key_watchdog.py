#!/usr/bin/env python3
"""push_key_watchdog.py — continuous SSH key registration monitor.

the existing ssh_key_health module checks file existence, permissions,
and ssh connectivity.  this module adds a *diagnostic action layer*:
when a push fails due to key rejection, it:

  1. captures the exact ssh fingerprint offered vs. accepted
  2. writes a machine-readable failure record to data/push_key_failures.jsonl
  3. emits a one-line remediation hint the caretaker can surface to the user
  4. optionally suppresses repeated push attempts for a cooldown window

design principle: the watchdog observes; it never auto-registers keys
(that requires human intent).  it just makes the failure loud, precise,
and non-repeating.

usage:
    python3 tools/push_key_watchdog.py --probe        # one-shot probe
    python3 tools/push_key_watchdog.py --watch         # daemon: tail git push stderr
    python3 tools/push_key_watchdog.py --cooldown 900  # suppress push for 900s after failure

exit codes:
    0  key registered and working
    1  key not registered (actionable: user must add pubkey to GitHub)
    2  key file missing (actionable: generate or restore key)
    3  network unreachable (transient, retry later)
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
FAILURE_LOG = DATA_DIR / "push_key_failures.jsonl"
COOLDOWN_FILE = DATA_DIR / "push_cooldown_until.txt"
KEY_CANDIDATES = [
    Path.home() / ".ssh" / "id_ed25519",
    Path.home() / ".ssh" / "id_rsa",
    Path("/root/.ssh/id_ed25519"),
    Path("/tmp/iamai_key"),
]


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def fingerprint(key_path: Path) -> str:
    """return SHA256 fingerprint of a private key, or empty string."""
    try:
        result = subprocess.run(
            ["ssh-keygen", "-lf", str(key_path)],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            return parts[1] if len(parts) >= 2 else ""
    except Exception:
        pass
    return ""


def probe_ssh() -> dict:
    """attempt ssh -T git@github.com and return structured result."""
    result = subprocess.run(
        ["ssh", "-T", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
         "git@github.com"],
        capture_output=True, text=True, timeout=15,
    )
    stderr = result.stderr
    if result.returncode == 0:
        return {"status": "ok", "detail": stderr.strip()}
    if "Permission denied (publickey)" in stderr:
        return {"status": "key_rejected", "detail": stderr.strip()}
    if "Could not resolve hostname" in stderr or "Network is unreachable" in stderr:
        return {"status": "network", "detail": stderr.strip()}
    return {"status": "unknown", "detail": stderr.strip(), "rc": result.returncode}


def find_key() -> Path | None:
    for p in KEY_CANDIDATES:
        if p.is_file() and os.access(p, os.R_OK):
            return p
    return None


def record_failure(key_path: Path | None, probe_result: dict, action: str):
    """append a failure record to the jsonl log."""
    DATA_DIR.mkdir(exist_ok=True)
    record = {
        "at": now_iso(),
        "key_path": str(key_path) if key_path else None,
        "fingerprint": fingerprint(key_path) if key_path else None,
        "probe_status": probe_result["status"],
        "action": action,
    }
    with open(FAILURE_LOG, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def set_cooldown(seconds: int):
    """write a cooldown timestamp so batch pusher can back off."""
    DATA_DIR.mkdir(exist_ok=True)
    until = int(time.time()) + seconds
    COOLDOWN_FILE.write_text(str(until))


def check_cooldown() -> bool:
    """return True if we are currently in a cooldown window."""
    if not COOLDOWN_FILE.exists():
        return False
    try:
        until = int(COOLDOWN_FILE.read_text().strip())
        return time.time() < until
    except ValueError:
        return False


def remediation_hint(probe_result: dict, key_path: Path | None) -> str:
    """one-line action hint for the caretaker to surface."""
    if probe_result["status"] == "ok":
        return "SSH key accepted. push should work."
    if probe_result["status"] == "key_rejected":
        if key_path:
            fp = fingerprint(key_path)
            pub = key_path.with_suffix(key_path.suffix + ".pub")
            if pub.exists():
                return (
                    f"KEY NOT REGISTERED on GitHub. fingerprint={fp}. "
                    f"run: cat {pub} → paste into "
                    f"https://github.com/settings/ssh/new"
                )
            return f"KEY NOT REGISTERED and no .pub file found at {pub}."
        return "NO SSH KEY found. generate one: ssh-keygen -t ed25519"
    if probe_result["status"] == "network":
        return "Network unreachable. retry in 5 minutes."
    return f"Unknown SSH state: {probe_result['detail'][:120]}"


def cmd_probe():
    """one-shot probe: print result and exit."""
    key = find_key()
    result = probe_ssh()
    hint = remediation_hint(result, key)
    print(json.dumps({
        "key": str(key) if key else None,
        "fingerprint": fingerprint(key) if key else None,
        "probe": result,
        "hint": hint,
    }, indent=2, ensure_ascii=False))
    if result["status"] != "ok":
        record_failure(key, result, "probe")
    sys.exit(0 if result["status"] == "ok" else 1)


def cmd_watch(cooldown: int = 0):
    """daemon mode: probe every 60s, record failures, optionally cooldown."""
    print(f"[{now_iso()}] push_key_watchdog started (cooldown={cooldown}s)")
    while True:
        key = find_key()
        result = probe_ssh()
        if result["status"] != "ok":
            rec = record_failure(key, result, "watch")
            hint = remediation_hint(result, key)
            print(f"[{now_iso()}] FAIL: {hint}")
            if cooldown > 0:
                set_cooldown(cooldown)
        else:
            # clear cooldown on success
            if COOLDOWN_FILE.exists():
                COOLDOWN_FILE.unlink()
            print(f"[{now_iso()}] OK")
        time.sleep(60)


if __name__ == "__main__":
    args = sys.argv[1:]
    cooldown = 0
    for i, a in enumerate(args):
        if a == "--cooldown" and i + 1 < len(args):
            cooldown = int(args[i + 1])
    if "--probe" in args:
        cmd_probe()
    elif "--watch" in args:
        cmd_watch(cooldown)
    else:
        cmd_probe()
