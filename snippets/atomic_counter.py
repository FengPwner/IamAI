"""066 — atomic_counter: a crash-safe monotonic counter persisted to disk.

the problem is ancient: you need a counter that survives restarts, but
writing an integer to a file is not atomic.  write ``42`` and crash after
flushing ``4`` — on restart the file says ``4``, which is wrong in the
direction that matters (under-count).

the fix is the oldest trick in the atomic-write playbook: write to a
temporary file in the same directory, fsync, then rename.  POSIX guarantees
that ``rename(2)`` is atomic on the same filesystem, so the counter file
is always either the old value or the new value, never a torn write.

concurrent safety comes from ``fcntl.flock`` — an advisory exclusive lock
on a sidecar ``.lock`` file.  every increment re-reads the counter file
under the lock, so even if two processes open separate ``AtomicCounter``
instances on the same path, they serialise correctly.

this implementation provides:

- **increment()** — bump by *delta* (default 1), persist, return new value.
- **value** — read the current counter without incrementing (snapshot).
- **reset()** — set back to zero.

the file format is a single ASCII integer.  no JSON, no protobuf, no
schema registry.  if you need a counter that speaks XML, you have already
lost.

"""

from __future__ import annotations

import fcntl
import os
import tempfile
from pathlib import Path


class AtomicCounter:
    """A monotonic counter that survives crashes and concurrent access."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._value = self._read()

    @property
    def value(self) -> int:
        """Current counter value (snapshot from last read or increment)."""
        return self._value

    def increment(self, delta: int = 1) -> int:
        """Add *delta* to the counter, persist atomically, return new value.

        Thread-safe and process-safe: holds an exclusive flock on a sidecar
        lock file while reading the current value and writing the new one.

        Raises ``ValueError`` if *delta* would make the counter negative.
        """
        with self._locked():
            current = self._read()
            new = current + delta
            if new < 0:
                raise ValueError(f"counter would go negative: {current} + {delta}")
            self._write(new)
            self._value = new
            return new

    def reset(self) -> None:
        """Set counter back to zero (under lock)."""
        with self._locked():
            self._write(0)
            self._value = 0

    # -- internals -----------------------------------------------------------

    def _read(self) -> int:
        if not self._path.exists():
            return 0
        text = self._path.read_text(encoding="utf-8").strip()
        if not text:
            return 0
        return int(text)

    def _write(self, n: int) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self._path.parent),
            prefix=f".{self._path.name}.",
            suffix=".tmp",
        )
        closed = False
        try:
            os.write(fd, f"{n}\n".encode("utf-8"))
            os.fsync(fd)
            os.close(fd)
            closed = True
            os.replace(tmp, str(self._path))
        except BaseException:
            if not closed:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _locked(self) -> _LockContext:
        """Return a context manager that holds an exclusive flock."""
        return _LockContext(self._lock_path)


class _LockContext:
    """Thin wrapper around fcntl.flock for use as a context manager."""

    __slots__ = ("_path", "_fd")

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def __enter__(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(self._fd, fcntl.LOCK_EX)

    def __exit__(self, *exc: object) -> None:
        assert self._fd is not None
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)
        self._fd = None
