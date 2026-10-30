"""sync_fence — serialize concurrent git operations.

The #1 cause of push failures in this repo is two processes touching
.git at the same time: writer commits while batch pushes, or a
caretaker pulls while the batch is mid-push. A SyncFence is a
lightweight, filesystem-backed mutex that any git-touching code
can acquire before proceeding.

Design choices:
  - Filesystem lock (not threading.Lock) because writer and batch
    run in *separate processes*.
  - Stale-lock detection: if the PID in the lockfile is dead,
    the lock is considered expired and can be reclaimed.
  - Context-manager API so callers can't forget to release.
"""

from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _pid_alive(pid: int) -> bool:
    """Return True if *pid* exists (signal 0 doesn't kill)."""
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


@dataclass
class LockInfo:
    """Snapshot of who holds the fence."""

    pid: int
    owner: str
    acquired_at: float
    repo_path: str

    def is_stale(self, max_age: float = 600.0) -> bool:
        """A lock is stale when its PID is dead or it's too old."""
        if not _pid_alive(self.pid):
            return True
        return (time.time() - self.acquired_at) > max_age


@dataclass
class SyncFence:
    """Filesystem-backed mutex for serialising git operations.

    Parameters
    ----------
    lock_path:
        Where to write the lock file.  Defaults to
        ``<repo>/.git/sync_fence.lock``.
    owner:
        Human-readable label (e.g. ``"writer"``, ``"batch"``,
        ``"caretaker"``) stored in the lock for debugging.
    timeout:
        Seconds to wait when ``acquire(block=True)``.
        ``None`` means wait forever.
    stale_after:
        Seconds after which an unattended lock is considered
        abandoned and may be broken.
    """

    repo_path: str | Path
    owner: str = "unknown"
    timeout: Optional[float] = 10.0
    stale_after: float = 600.0
    _lock_path: Path = field(init=False, repr=False)
    _held: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        repo = Path(self.repo_path)
        self._lock_path = repo / ".git" / "sync_fence.lock"

    # -- public API --------------------------------------------------------

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    def info(self) -> Optional[LockInfo]:
        """Read current lock metadata, or None if unlocked."""
        if not self._lock_path.exists():
            return None
        try:
            data = json.loads(self._lock_path.read_text())
            return LockInfo(**data)
        except (json.JSONDecodeError, TypeError, KeyError):
            return None

    def is_locked(self) -> bool:
        return self._lock_path.exists()

    def acquire(self, block: bool = True) -> bool:
        """Try to take the fence.

        Returns True on success.  When *block* is False, returns
        False immediately if the fence is held by a live process.
        """
        deadline = None if self.timeout is None else time.monotonic() + self.timeout

        while True:
            # Fast path: no lock file at all.
            if not self._lock_path.exists():
                return self._try_create()

            # Lock exists — is it stale?
            existing = self.info()
            if existing is not None and existing.is_stale(self.stale_after):
                self.break_lock(reason="stale")
                return self._try_create()

            if not block:
                return False

            if deadline is not None and time.monotonic() >= deadline:
                return False

            time.sleep(0.1)

    def release(self) -> None:
        """Release the fence if we hold it."""
        if not self._held:
            return
        try:
            info = self.info()
            if info is not None and info.pid == os.getpid():
                self._lock_path.unlink(missing_ok=True)
        finally:
            self._held = False

    def break_lock(self, reason: str = "manual") -> Optional[LockInfo]:
        """Forcibly remove the lock regardless of owner.

        Returns the previous LockInfo (if readable) so callers can
        log what they broke.
        """
        old = self.info()
        self._lock_path.unlink(missing_ok=True)
        return old

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> "SyncFence":
        acquired = self.acquire(block=True)
        if not acquired:
            raise TimeoutError(
                f"SyncFence at {self._lock_path} not acquired "
                f"within {self.timeout}s (owner={self.owner!r})"
            )
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    # -- internals ---------------------------------------------------------

    def _try_create(self) -> bool:
        """Atomically create the lock file.  Returns True on success."""
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "owner": self.owner,
                "acquired_at": time.time(),
                "repo_path": str(self.repo_path),
            }
        )
        try:
            # O_EXCL = fail if file already exists (atomic on POSIX).
            fd = os.open(
                str(self._lock_path),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
            )
            with os.fdopen(fd, "w") as f:
                f.write(payload)
            self._held = True
            return True
        except FileExistsError:
            return False
