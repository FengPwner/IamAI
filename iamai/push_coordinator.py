"""Push coordinator: serialize pushes among multiple agents.

When four agents push to the same branch every ten minutes, push races
are not a bug — they are a scheduling problem. The existing recovery
modules (``push``, ``remote_sync``, ``rebase_lock``) handle the aftermath
of a race. This module prevents the race from happening in the first place.

The protocol is a file-based mutex:

    1. Agent writes its name + PID + expiry to ``data/push.lock``.
    2. If the file already exists and the lock has not expired, the
       agent waits (with a timeout) for the holder to finish.
    3. If the lock has expired (holder crashed or took too long), the
       new agent steals it.
    4. After pushing, the agent deletes the lock file.

This is not a distributed lock — it only coordinates agents that share
the same working tree (same clone). But that is exactly the deployment
here: multiple writer processes in one repo, all pushing through the
same batch committer.

Design choices:
- File-based: survives process crashes (stale locks are detected by expiry).
- Non-blocking by default: ``acquire`` returns immediately with success
  or failure; callers decide whether to retry.
- Explicit steal: an expired lock is treated as abandoned, not as a
  conflict. The stealer logs the previous holder for post-mortem.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


DEFAULT_LOCK_PATH = "data/push.lock"
DEFAULT_HOLD_SECONDS = 120  # max time a lock can be held
DEFAULT_WAIT_SECONDS = 30   # max time to wait for a lock


@dataclass
class LockInfo:
    """Contents of a push lock file."""

    agent: str
    pid: int
    acquired_at: float
    expires_at: float

    def is_expired(self, now: Optional[float] = None) -> bool:
        """Check whether the lock has expired."""
        t = now if now is not None else time.time()
        return t >= self.expires_at

    def is_held_by(self, agent: str, pid: int) -> bool:
        """Check whether this lock belongs to the given agent+pid."""
        return self.agent == agent and self.pid == pid


@dataclass
class AcquireResult:
    """Outcome of a lock acquisition attempt."""

    acquired: bool
    lock_path: str = ""
    previous_holder: Optional[LockInfo] = None
    stolen: bool = False
    error: Optional[str] = None


def _read_lock(path: Path) -> Optional[LockInfo]:
    """Read and parse a lock file. Returns None if missing or corrupt."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return LockInfo(**data)
    except (json.JSONDecodeError, TypeError, KeyError, OSError):
        return None


def _write_lock(path: Path, info: LockInfo) -> None:
    """Atomically write a lock file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(info), indent=2), encoding="utf-8")
    tmp.replace(path)


def _remove_lock(path: Path, info: LockInfo) -> bool:
    """Remove a lock file only if it still belongs to the given holder.

    Returns True if the lock was removed, False if someone else holds it.
    """
    current = _read_lock(path)
    if current is None:
        return True  # already gone
    if not current.is_held_by(info.agent, info.pid):
        return False  # someone else took over
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def acquire(
    agent: str,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    hold_seconds: int = DEFAULT_HOLD_SECONDS,
    wait_seconds: int = DEFAULT_WAIT_SECONDS,
    now_fn=None,
) -> AcquireResult:
    """Attempt to acquire the push lock.

    Args:
        agent: identifier for the acquiring agent (e.g. "qwen", "guoban")
        lock_path: path to the lock file
        hold_seconds: how long the lock is valid for
        wait_seconds: how long to wait if the lock is held
        now_fn: callable returning current time (for testing)

    Returns:
        AcquireResult indicating success, failure, or stolen lock.
    """
    path = Path(lock_path)
    pid = os.getpid()
    _now = now_fn or time.time

    deadline = _now() + wait_seconds
    previous_stolen: Optional[LockInfo] = None

    while True:
        now = _now()
        existing = _read_lock(path)

        if existing is None:
            # No lock — acquire it
            info = LockInfo(
                agent=agent,
                pid=pid,
                acquired_at=now,
                expires_at=now + hold_seconds,
            )
            _write_lock(path, info)
            return AcquireResult(
                acquired=True,
                lock_path=str(path),
                previous_holder=previous_stolen,
                stolen=previous_stolen is not None,
            )

        if existing.is_expired(now):
            # Stale lock — steal it
            previous_stolen = existing
            info = LockInfo(
                agent=agent,
                pid=pid,
                acquired_at=now,
                expires_at=now + hold_seconds,
            )
            _write_lock(path, info)
            return AcquireResult(
                acquired=True,
                lock_path=str(path),
                previous_holder=previous_stolen,
                stolen=True,
            )

        if existing.is_held_by(agent, pid):
            # Already hold it — refresh
            info = LockInfo(
                agent=agent,
                pid=pid,
                acquired_at=existing.acquired_at,
                expires_at=now + hold_seconds,
            )
            _write_lock(path, info)
            return AcquireResult(
                acquired=True,
                lock_path=str(path),
            )

        # Lock is held by someone else and not expired
        if now >= deadline:
            return AcquireResult(
                acquired=False,
                lock_path=str(path),
                previous_holder=existing,
                error=f"timed out after {wait_seconds}s waiting for lock held by {existing.agent} (pid {existing.pid})",
            )

        # Brief sleep before retrying
        time.sleep(0.5)


def release(
    agent: str,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
) -> bool:
    """Release a previously acquired lock.

    Only removes the lock if it still belongs to this agent+pid.
    Returns True if released, False if the lock was already stolen.
    """
    path = Path(lock_path)
    pid = os.getpid()
    info = LockInfo(agent=agent, pid=pid, acquired_at=0, expires_at=0)
    return _remove_lock(path, info)
