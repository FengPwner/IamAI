"""push_readiness_probe.py — test push connectivity *before* commits accumulate.

The existing ``push_readiness`` module checks whether the deploy key file
exists and is well-formed. ``push_preflight`` validates host keys in
known_hosts. Neither actually *talks* to the remote before the committer
discovers — too late — that the SSH handshake fails.

This module runs a lightweight ``git ls-remote`` probe to verify that the
full push path works: key present, host key accepted, repository reachable,
authentication succeeds. It is designed to run inside the commit_batch loop
*before* the test gate, so a red probe blocks the commit (and pauses the
writer) rather than letting broken commits pile up.

Probe outcomes:

    READY       probe succeeded, push path is healthy
    NO_KEY      deploy key file missing or unreadable
    HOST_KEY    host key verification failed (the failure mode that bit us
                on 2026-10-29 when the known_hosts file was stale)
    AUTH        key exists and host accepted, but authentication rejected
    UNREACHABLE network error or timeout — remote not reachable
    UNKNOWN     any other failure

Usage::

    from iamai.push_readiness_probe import probe_push, ProbeResult

    result = probe_push(remote="git@github.com:FengPwner/IamAI.git")
    print(result.status)      # "READY"
    print(result.latency_ms)  # 312
    print(result.summary())   # "READY in 312ms"

    # In the committer loop:
    if result.status != "READY":
        # pause writer, don't accumulate commits we can't push
        ...

Design:
    - subprocess calls ``git ls-remote --heads <remote>`` with a timeout.
    - exit code 0 + stdout → READY
    - exit code != 0 → parse stderr for the specific failure mode
    - timeout → UNREACHABLE
    - No mutation: the probe never writes, pushes, or modifies anything.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_REMOTE = os.environ.get(
    "IAMAII_REMOTE", "git@github.com:FengPwner/IamAI.git"
)
DEFAULT_TIMEOUT = 15  # seconds — generous for SSH, short enough to fail fast
DEFAULT_SSH_KEY = "/tmp/ssh_deploy_key"


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

VALID_STATUSES = {"READY", "NO_KEY", "HOST_KEY", "AUTH", "UNREACHABLE", "UNKNOWN"}


@dataclass
class ProbeResult:
    """Outcome of a single push-readiness probe."""

    status: str  # one of VALID_STATUSES
    latency_ms: int = 0
    stderr_snippet: str = ""
    remote: str = ""

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            self.status = "UNKNOWN"

    @property
    def ok(self) -> bool:
        return self.status == "READY"

    def summary(self) -> str:
        if self.ok:
            return f"READY in {self.latency_ms}ms"
        detail = f": {self.stderr_snippet[:80]}" if self.stderr_snippet else ""
        return f"{self.status} after {self.latency_ms}ms{detail}"


# ---------------------------------------------------------------------------
# Key presence check (fast, no network)
# ---------------------------------------------------------------------------

def _check_key(key_path: str) -> Optional[ProbeResult]:
    """Return a NO_KEY result if the deploy key is missing or world-readable."""
    p = Path(key_path)
    if not p.exists():
        return ProbeResult(status="NO_KEY", stderr_snippet=f"key not found: {key_path}")
    try:
        st = p.stat()
        # SSH refuses keys readable by others (mode > 0600)
        if st.st_mode & 0o077:
            return ProbeResult(
                status="NO_KEY",
                stderr_snippet=f"key permissions too open: {oct(st.st_mode)}",
            )
    except OSError as e:
        return ProbeResult(status="NO_KEY", stderr_snippet=str(e))
    return None  # key looks fine


# ---------------------------------------------------------------------------
# Classify stderr
# ---------------------------------------------------------------------------

_HOST_KEY_SIGNALS = [
    "host key verification failed",
    "remote host identification has changed",
    "warning: remote host identification has changed",
    "add correct host key",
    "offending key",
]

_AUTH_SIGNALS = [
    "permission denied",
    "publickey",
    "authentication failed",
    "could not read from remote repository",
    "access rights",
]

_NETWORK_SIGNALS = [
    "could not resolve hostname",
    "connection timed out",
    "network is unreachable",
    "no route to host",
    "connection refused",
    "temporary failure in name resolution",
]


def _classify(stderr: str) -> str:
    """Map stderr text to a status code."""
    low = stderr.lower()
    for sig in _HOST_KEY_SIGNALS:
        if sig in low:
            return "HOST_KEY"
    for sig in _AUTH_SIGNALS:
        if sig in low:
            return "AUTH"
    for sig in _NETWORK_SIGNALS:
        if sig in low:
            return "UNREACHABLE"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------

def probe_push(
    remote: str = DEFAULT_REMOTE,
    ssh_key: str = DEFAULT_SSH_KEY,
    timeout: int = DEFAULT_TIMEOUT,
) -> ProbeResult:
    """Run a push-readiness probe against *remote*.

    1. Check that the SSH key file exists and has safe permissions.
    2. Run ``git ls-remote --heads <remote>`` with the deploy key.
    3. Classify the outcome.
    """
    # Fast key check first — no point hitting the network if the key is gone.
    key_problem = _check_key(ssh_key)
    if key_problem is not None:
        key_problem.remote = remote
        return key_problem

    ssh_cmd = (
        f"ssh -i {ssh_key} -o StrictHostKeyChecking=accept-new "
        f"-o IdentitiesOnly=yes -o ConnectTimeout={timeout} "
        f"-o BatchMode=yes"
    )

    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = ssh_cmd
    # Prevent ssh-askpass from popping up in headless environments.
    env.pop("SSH_ASKPASS", None)
    env["DISPLAY"] = ""

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--heads", remote],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - t0) * 1000)
        return ProbeResult(
            status="UNREACHABLE",
            latency_ms=elapsed,
            stderr_snippet=f"timeout after {timeout}s",
            remote=remote,
        )

    elapsed = int((time.monotonic() - t0) * 1000)

    if proc.returncode == 0:
        return ProbeResult(
            status="READY",
            latency_ms=elapsed,
            remote=remote,
        )

    stderr = (proc.stderr or "").strip()
    status = _classify(stderr)

    return ProbeResult(
        status=status,
        latency_ms=elapsed,
        stderr_snippet=stderr[:200],
        remote=remote,
    )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def probe_summary(
    remote: str = DEFAULT_REMOTE,
    ssh_key: str = DEFAULT_SSH_KEY,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """One-line human summary of push readiness."""
    return probe_push(remote=remote, ssh_key=ssh_key, timeout=timeout).summary()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--remote", default=DEFAULT_REMOTE)
    ap.add_argument("--ssh-key", default=DEFAULT_SSH_KEY)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    result = probe_push(remote=args.remote, ssh_key=args.ssh_key, timeout=args.timeout)

    if args.as_json:
        from dataclasses import asdict
        print(_json.dumps(asdict(result), indent=2))
    else:
        print(result.summary())
        if not result.ok:
            print(f"  stderr: {result.stderr_snippet}")

    raise SystemExit(0 if result.ok else 1)
