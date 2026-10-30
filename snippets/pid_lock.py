"""051 — pid_lock: a PID-based file lock that handles dead owners.

cloud runtimes kill processes without SIGTERM. the PID file stays on disk,
claiming the lock, while the process is long gone. a naive `kill -0` check
would refuse to acquire, and a naive overwrite would race a live owner.

pid_lock does the minimum correct thing:

1. read the PID from the lock file
2. check if that PID is alive (signal 0)
3. if dead, remove the stale file and acquire
4. if alive, refuse

the lock is advisory — it protects against well-behaved writers in the same
host, not across filesystems or hostile actors. that is exactly the guarantee
this project needs: one writer per machine, not one writer per universe.

>>> import tempfile, os
>>> path = os.path.join(tempfile.gettempdir(), "pid_lock_test.pid")
>>> lock = PidLock(path)
>>> lock.acquire()
True
>>> lock.is_held()
True
>>> lock.release()
>>> lock.is_held()
False
>>> os.path.exists(path)
False

zero dependencies. stdlib only. tested with real PIDs.
"""

import os
import signal


class PidLock:
    """File-based lock using the current process's PID.

    Parameters
    ----------
    path : str
        Filesystem path for the PID file.
    pid : int, optional
        PID to write; defaults to os.getpid(). Override for testing or when
        re-acquiring on behalf of a dead process.

    >>> import tempfile, os
    >>> path = os.path.join(tempfile.gettempdir(), "test_lock.pid")
    >>> l = PidLock(path)
    >>> l.acquire()
    True
    >>> l.owner_pid() == os.getpid()
    True
    >>> l.release()
    """

    def __init__(self, path: str, pid: int | None = None):
        self.path = path
        self._pid = pid if pid is not None else os.getpid()

    # -- public API ----------------------------------------------------------

    def acquire(self) -> bool:
        """Try to take the lock. Returns True on success, False if held by a live process.

        Idempotent: if we already hold the lock, returns True without rewriting.
        """
        owner = self._read_owner()
        if owner == self._pid:
            return True  # already ours
        if owner is not None and self._pid_alive(owner):
            return False  # live process holds it
        self._remove_stale()
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write(str(self._pid))
            return True
        except OSError:
            return False

    def release(self) -> None:
        """Release the lock. No-op if the file does not exist or belongs to another PID."""
        owner = self._read_owner()
        if owner is not None and owner == self._pid:
            try:
                os.remove(self.path)
            except FileNotFoundError:
                pass

    def is_held(self) -> bool:
        """True if the lock file exists and its PID is alive."""
        return self._is_live_owner()

    def owner_pid(self) -> int | None:
        """Return the PID recorded in the lock file, or None if absent."""
        return self._read_owner()

    def force_release(self) -> bool:
        """Remove the lock file regardless of owner. Returns True if a file was removed."""
        try:
            os.remove(self.path)
            return True
        except FileNotFoundError:
            return False

    def stale(self) -> bool:
        """True if the lock file exists but its owner is dead."""
        owner = self._read_owner()
        if owner is None:
            return False
        return not self._pid_alive(owner)

    # -- internals -----------------------------------------------------------

    def _read_owner(self) -> int | None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                return int(fh.read().strip())
        except (FileNotFoundError, ValueError, OSError):
            return None

    def _is_live_owner(self) -> bool:
        owner = self._read_owner()
        if owner is None:
            return False
        if owner != self._pid:
            return self._pid_alive(owner)
        # the file exists and names us — treat as held
        return True

    def _remove_stale(self) -> None:
        owner = self._read_owner()
        if owner is not None and not self._pid_alive(owner):
            try:
                os.remove(self.path)
            except FileNotFoundError:
                pass

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """Check whether a PID is alive using signal 0."""
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # process exists but we lack permission to signal it
            return True


if __name__ == "__main__":
    import sys
    import tempfile

    lock_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        tempfile.gettempdir(), "iamai-demo.pid"
    )
    lock = PidLock(lock_path)
    if lock.acquire():
        print(f"acquired lock at {lock_path} (pid {lock.owner_pid()})")
        print(f"stale: {lock.stale()}")
        lock.release()
        print("released")
    else:
        owner = lock.owner_pid()
        print(f"lock held by pid {owner} at {lock_path}")
        if lock.stale():
            print("(stale — owner is dead)")
