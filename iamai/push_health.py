"""Push health pre-flight checks — catch SSH problems before push fails.

Born from Caretaker Visit 437: a push failed because the deploy key had
mode 0777 (world-readable), which OpenSSH rightly refuses to use.  The
error message (``UNPROTECTED PRIVATE KEY FILE``) is clear once you see it,
but in an automated loop it just looks like "push rejected" and gets
swallowed by generic retry logic.

This module exposes three pure-ish helpers:

* ``key_mode_ok(path)`` → bool — is the key file mode tight enough?
* ``diagnose_push(remote, key_path)`` → PushDiagnosis — full pre-flight
* ``format_diagnosis(d)`` → str — human-readable one-liner for logs

The functions are intentionally simple.  They do not fix anything; they
report.  The caretaker decides what to do with the report.
"""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Maximum allowed permission bits for an SSH private key.
# Owner read+write (0600) is the OpenSSH requirement.
_MAX_KEY_MODE = 0o600


def key_mode_ok(key_path: str | Path) -> bool:
    """Return True if *key_path* exists and its mode is ≤ 0600.

    A missing file returns False (not an error — the caller decides
    whether missing is fatal).
    """
    p = Path(key_path)
    if not p.is_file():
        return False
    mode = stat.S_IMODE(p.stat().st_mode)
    return mode <= _MAX_KEY_MODE


def _ssh_test(remote_host: str, key_path: str | Path, timeout: int = 10) -> bool:
    """Attempt a no-op SSH connection to *remote_host*.

    Returns True if ssh exits 0 (or 1 with "authenticated" in stderr,
    which GitHub returns for successful key auth with no shell).
    """
    cmd = [
        "ssh",
        "-i", str(key_path),
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={timeout}",
        "-T", f"git@{remote_host}",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        # GitHub returns exit 1 with "Hi <user>! You've successfully authenticated"
        combined = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            return True
        if "successfully authenticated" in combined.lower():
            return True
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


@dataclass(frozen=True)
class PushDiagnosis:
    """Result of a push pre-flight check."""
    key_exists: bool
    key_permissions_ok: bool
    ssh_connects: bool
    key_path: str
    remote_host: str

    @property
    def healthy(self) -> bool:
        return self.key_exists and self.key_permissions_ok and self.ssh_connects


def diagnose_push(
    remote_url: str = "git@github.com:FengPwner/IamAI.git",
    key_path: str | Path = "/tmp/ssh_deploy_key",
    timeout: int = 10,
) -> PushDiagnosis:
    """Run all pre-flight checks and return a PushDiagnosis.

    This is the entry point the caretaker should call before attempting
    a push.  If ``diagnosis.healthy`` is False, pushing will fail — fix
    the reported issue first.
    """
    p = Path(key_path)
    exists = p.is_file()
    perms_ok = key_mode_ok(p) if exists else False

    # Extract host from git SSH URL
    host = "github.com"
    if "@" in remote_url and ":" in remote_url:
        host = remote_url.split("@")[1].split(":")[0]

    ssh_ok = _ssh_test(host, p, timeout=timeout) if (exists and perms_ok) else False

    return PushDiagnosis(
        key_exists=exists,
        key_permissions_ok=perms_ok,
        ssh_connects=ssh_ok,
        key_path=str(key_path),
        remote_host=host,
    )


def format_diagnosis(d: PushDiagnosis) -> str:
    """One-line human-readable summary for logs."""
    parts = []
    if not d.key_exists:
        parts.append(f"key missing ({d.key_path})")
    elif not d.key_permissions_ok:
        parts.append(f"key too open ({d.key_path})")
    if not d.ssh_connects:
        parts.append(f"ssh fails → {d.remote_host}")
    if d.healthy:
        return "push pre-flight: OK"
    return f"push pre-flight FAIL: {'; '.join(parts)}"
