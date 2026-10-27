"""push_readiness_probe — pre-flight check before attempting git push.

the batch committer accumulates commits and tries to push on a schedule.
when the SSH key is missing or unregistered, every push attempt fails
silently (exit 128), and the caretaker only discovers the problem when
the unpushed count reaches triple digits.

this module runs a lightweight pre-flight check *before* the push is
attempted, so the failure mode shifts from "119 commits trapped for
four days" to "probe failed at startup, fix before committing more."

checks performed:

1. **key_exists** — does the SSH private key file exist on disk?
2. **key_readable** — can the current process read it?
3. **ssh_agent** — is ssh-agent running and does it hold the key?
4. **github_auth** — does `ssh -T git@github.com` succeed?

each check returns a verdict (pass / fail / skip) and an optional
detail string.  the overall probe is ``ready=True`` only when every
non-skipped check passes.

usage::

    from iamai.push_readiness_probe import probe

    result = probe()
    print(result["ready"])      # False
    print(result["diagnosis"])  # "key file missing: /root/.ssh/id_ed25519"
    for c in result["checks"]:
        print(f"  {c['name']}: {c['verdict']} — {c['detail']}")

design: the core logic is pure where possible (path checks, string
parsing).  the SSH connectivity test is the only side-effect and is
isolated in ``_check_github_auth`` so tests can mock it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# individual checks
# ---------------------------------------------------------------------------

def _check_key_exists(key_path: str) -> Dict[str, str]:
    """check whether the SSH private key file exists."""
    p = Path(key_path)
    if p.exists():
        return {"name": "key_exists", "verdict": "pass",
                "detail": f"found {key_path}"}
    return {"name": "key_exists", "verdict": "fail",
            "detail": f"missing {key_path}"}


def _check_key_readable(key_path: str) -> Dict[str, str]:
    """check whether the key file is readable (permissions)."""
    p = Path(key_path)
    if not p.exists():
        return {"name": "key_readable", "verdict": "skip",
                "detail": "key file does not exist"}
    try:
        p.read_bytes()[:1]  # read one byte to test readability
        return {"name": "key_readable", "verdict": "pass",
                "detail": "key file is readable"}
    except PermissionError:
        return {"name": "key_readable", "verdict": "fail",
                "detail": f"permission denied: {key_path}"}
    except OSError as exc:
        return {"name": "key_readable", "verdict": "fail",
                "detail": f"read error: {exc}"}


def _check_key_permissions(key_path: str) -> Dict[str, str]:
    """check that key file permissions are not too open (max 0o600)."""
    p = Path(key_path)
    if not p.exists():
        return {"name": "key_permissions", "verdict": "skip",
                "detail": "key file does not exist"}
    try:
        mode = p.stat().st_mode & 0o777
        if mode & 0o077:  # group or other has any permission
            return {"name": "key_permissions", "verdict": "fail",
                    "detail": f"too open: {oct(mode)} (should be 0o600)"}
        return {"name": "key_permissions", "verdict": "pass",
                "detail": f"permissions ok: {oct(mode)}"}
    except OSError as exc:
        return {"name": "key_permissions", "verdict": "fail",
                "detail": f"stat error: {exc}"}


def _check_ssh_agent() -> Dict[str, str]:
    """check whether ssh-agent is running and has at least one key loaded."""
    agent_pid = os.environ.get("SSH_AGENT_PID")
    auth_sock = os.environ.get("SSH_AUTH_SOCK")

    if not auth_sock:
        return {"name": "ssh_agent", "verdict": "fail",
                "detail": "SSH_AUTH_SOCK not set — agent not running"}

    try:
        out = subprocess.check_output(
            ["ssh-add", "-l"],
            stderr=subprocess.STDOUT, text=True, timeout=5,
        )
        if "no identities" in out.lower():
            return {"name": "ssh_agent", "verdict": "fail",
                    "detail": "agent running but no keys loaded"}
        count = len(out.strip().splitlines())
        return {"name": "ssh_agent", "verdict": "pass",
                "detail": f"agent has {count} key(s) loaded"}
    except FileNotFoundError:
        return {"name": "ssh_agent", "verdict": "skip",
                "detail": "ssh-add not found"}
    except subprocess.CalledProcessError as exc:
        return {"name": "ssh_agent", "verdict": "fail",
                "detail": f"ssh-add failed: {exc.output.strip()}"}
    except subprocess.TimeoutExpired:
        return {"name": "ssh_agent", "verdict": "fail",
                "detail": "ssh-add timed out (5s)"}


def _check_github_auth(
    ssh_command: Optional[str] = None,
    timeout: int = 10,
) -> Dict[str, str]:
    """test SSH connectivity to github.com.

    parameters
    ----------
    ssh_command : str, optional
        override the SSH binary path (useful for testing).
    timeout : int
        seconds before the connection attempt is abandoned.
    """
    ssh = ssh_command or "ssh"
    try:
        result = subprocess.run(
            [ssh, "-T", "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=5", "git@github.com"],
            capture_output=True, text=True, timeout=timeout,
        )
        combined = (result.stdout + result.stderr).strip()

        # github returns exit 1 on success (no shell access) but prints
        # "Hi <user>! You've successfully authenticated" to stderr.
        if "successfully authenticated" in combined.lower():
            user = _extract_github_user(combined)
            return {"name": "github_auth", "verdict": "pass",
                    "detail": f"authenticated as {user}"}

        if "permission denied" in combined.lower():
            return {"name": "github_auth", "verdict": "fail",
                    "detail": "permission denied — key not registered"}

        if "could not resolve" in combined.lower():
            return {"name": "github_auth", "verdict": "fail",
                    "detail": "DNS resolution failed — no network?"}

        return {"name": "github_auth", "verdict": "fail",
                "detail": combined[:120]}
    except FileNotFoundError:
        return {"name": "github_auth", "verdict": "skip",
                "detail": f"ssh binary not found at {ssh}"}
    except subprocess.TimeoutExpired:
        return {"name": "github_auth", "verdict": "fail",
                "detail": f"connection timed out ({timeout}s)"}


def _extract_github_user(output: str) -> str:
    """parse 'Hi username! You've successfully authenticated' from output."""
    for line in output.splitlines():
        if "hi " in line.lower() and "!" in line:
            # "Hi username! You've..."
            start = line.lower().index("hi ") + 3
            end = line.index("!", start)
            return line[start:end]
    return "unknown"


# ---------------------------------------------------------------------------
# composite probe
# ---------------------------------------------------------------------------

def probe(
    key_path: str = "~/.ssh/id_ed25519",
    skip_agent: bool = False,
    skip_network: bool = False,
    ssh_command: Optional[str] = None,
    network_timeout: int = 10,
) -> Dict[str, Any]:
    """run all readiness checks and return a structured report.

    parameters
    ----------
    key_path : str
        path to the SSH private key (tilde expanded).
    skip_agent : bool
        skip the ssh-agent check (e.g. in CI without an agent).
    skip_network : bool
        skip the github auth test (e.g. in unit tests).
    ssh_command : str, optional
        override SSH binary path for the network check.
    network_timeout : int
        seconds for the github auth timeout.

    returns
    -------
    dict with keys: ready (bool), checks (list of check dicts),
    diagnosis (str summary of failures).
    """
    resolved = os.path.expanduser(key_path)
    checks: List[Dict[str, str]] = []

    # sequential: later checks depend on earlier ones passing
    checks.append(_check_key_exists(resolved))
    checks.append(_check_key_readable(resolved))
    checks.append(_check_key_permissions(resolved))

    if not skip_agent:
        checks.append(_check_ssh_agent())

    if not skip_network:
        checks.append(_check_github_auth(
            ssh_command=ssh_command, timeout=network_timeout,
        ))

    failures = [c for c in checks if c["verdict"] == "fail"]
    ready = len(failures) == 0

    if ready:
        diagnosis = "all checks passed — push should succeed"
    else:
        parts = [f"{c['name']}: {c['detail']}" for c in failures]
        diagnosis = "; ".join(parts)

    return {
        "ready": ready,
        "checks": checks,
        "diagnosis": diagnosis,
    }
