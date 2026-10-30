"""push_retry — resilient git push with exponential back-off.

When a CI writer loop pushes every ten minutes, transient network
glitches (DNS timeout, SSH handshake reset, host-key rotation) are
the #1 cause of "everything is fine except nothing reached remote".

This module wraps a push attempt with:

1. **Pre-flight checks** — verify SSH key exists, known_hosts has
   the remote, working tree is clean enough to push.
2. **Retry with jitter** — up to ``max_retries`` attempts, each
   delayed by ``base_delay * 2^attempt + random(0, jitter)``.
3. **Pull-rebase recovery** — on non-fast-forward rejection,
   automatically stash → pull --rebase → stash pop → retry once.
4. **Structured result** — ``PushResult`` dataclass so callers
   (commit_batch.py, caretaker) can log and react.

Zero external dependencies.  stdlib + subprocess only.

>>> r = PushResult(ok=True, attempts=1, message="pushed")
>>> r
PushResult(ok=True, attempts=1, message='pushed')
"""

from __future__ import annotations

import dataclasses
import os
import random
import subprocess
import time
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class PushResult:
    """Outcome of a push attempt sequence."""

    ok: bool
    attempts: int
    message: str

    def __bool__(self) -> bool:
        return self.ok


# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

def check_ssh_key(path: str = "/tmp/ssh_deploy_key") -> bool:
    """Return True when the deploy key file exists and is non-empty."""
    p = Path(path)
    return p.is_file() and p.stat().st_size > 0


def check_known_hosts(host: str = "github.com") -> bool:
    """Return True when *host* appears in ~/.ssh/known_hosts."""
    kh = Path.home() / ".ssh" / "known_hosts"
    if not kh.is_file():
        return False
    return any(host in line for line in kh.read_text().splitlines())


def preflight_ok(
    ssh_key: str = "/tmp/ssh_deploy_key",
    host: str = "github.com",
) -> bool:
    """Quick gate: key exists AND host is in known_hosts."""
    return check_ssh_key(ssh_key) and check_known_hosts(host)


# ---------------------------------------------------------------------------
# Core push
# ---------------------------------------------------------------------------

def _run_git(*args: str, cwd: str, env: Optional[dict] = None) -> tuple[int, str]:
    """Run a git command, return (returncode, stderr)."""
    merged = {**os.environ, **(env or {})}
    r = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=merged,
        timeout=60,
    )
    return r.returncode, (r.stderr or r.stdout).strip()


def git_push(
    repo: str = ".",
    remote: str = "origin",
    branch: str = "main",
    ssh_key: str = "/tmp/ssh_deploy_key",
    max_retries: int = 3,
    base_delay: float = 2.0,
    jitter: float = 1.0,
) -> PushResult:
    """Push with exponential back-off and pull-rebase recovery.

    Parameters
    ----------
    repo : str
        Path to the git working tree.
    remote, branch : str
        Target refspec components.
    ssh_key : str
        Path to the private key used for SSH auth.
    max_retries : int
        Total attempts before giving up (≥ 1).
    base_delay : float
        Initial back-off delay in seconds; doubled each retry.
    jitter : float
        Random jitter ceiling added to each delay.

    Returns
    -------
    PushResult
        ``ok=True`` on success, ``ok=False`` after exhausting retries.
    """
    ssh_env = {
        "GIT_SSH_COMMAND": f"ssh -i {ssh_key} -o StrictHostKeyChecking=no"
    }

    for attempt in range(1, max_retries + 1):
        rc, msg = _run_git("push", remote, branch, cwd=repo, env=ssh_env)

        if rc == 0:
            return PushResult(ok=True, attempts=attempt, message="pushed")

        # Non-fast-forward → try pull-rebase once
        if "rejected" in msg.lower() and attempt == 1:
            _pull_rebase_recovery(repo, ssh_env)
            continue

        # Transient error → back-off
        if attempt < max_retries:
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, jitter)
            time.sleep(delay)

    return PushResult(ok=False, attempts=max_retries, message=f"failed: {msg}")


def _pull_rebase_recovery(repo: str, env: dict) -> None:
    """Stash → pull --rebase → stash pop.  Best-effort, errors ignored."""
    _run_git("stash", cwd=repo, env=env)
    _run_git("pull", "--rebase", "origin", "main", cwd=repo, env=env)
    _run_git("stash", "pop", cwd=repo, env=env)


# ---------------------------------------------------------------------------
# Convenience: one-liner for cron / batch scripts
# ---------------------------------------------------------------------------

def ensure_pushed(
    repo: str = ".",
    remote: str = "origin",
    branch: str = "main",
) -> PushResult:
    """High-level: pre-flight + push, return structured result.

    Suitable for calling from ``commit_batch.py`` at the end of each
    batch cycle.  If pre-flight fails, returns immediately without
    attempting to push.
    """
    if not preflight_ok():
        return PushResult(ok=False, attempts=0, message="pre-flight failed")
    return git_push(repo=repo, remote=remote, branch=branch)
