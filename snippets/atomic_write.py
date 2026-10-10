"""052 — atomic_write: write files so readers never see half-finished data.

The pattern is old and reliable:

1. write to a temporary file in the same directory as the target
2. fsync the temp file (so data hits disk, not just kernel buffers)
3. rename the temp file over the target (atomic on POSIX filesystems)

If anything fails — disk full, permission error, process killed mid-write —
the target file is untouched. Readers either see the old version or the new
one, never a torn write.

Use it as a context manager for streaming writes, or as a one-shot function
for simple string/bytes payloads.

>>> import tempfile, os
>>> target = os.path.join(tempfile.mkdtemp(), "config.json")
>>> atomic_write_text(target, '{"version": 2}')
>>> open(target).read()
'{"version": 2}'
>>> # The temp file is gone after the rename:
>>> os.listdir(os.path.dirname(target))
['config.json']
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Union

PathLike = Union[str, os.PathLike]


def _fsync(fd: int) -> None:
    """Flush kernel buffers to disk. No-op on platforms that lack fsync."""
    try:
        os.fsync(fd)
    except (OSError, AttributeError):
        pass


def atomic_write_text(path: PathLike, data: str, *, encoding: str = "utf-8") -> None:
    """Write a string to *path* atomically.

    Creates parent directories if needed. The write goes to a temp file
    first, then is renamed into place.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(data)
            f.flush()
            _fsync(f.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        # Clean up the temp file on any failure (including KeyboardInterrupt).
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: PathLike, data: bytes) -> None:
    """Write raw bytes to *path* atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            _fsync(f.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class AtomicWriter:
    """Context manager for streaming atomic writes.

    >>> import tempfile, os
    >>> target = os.path.join(tempfile.mkdtemp(), "log.txt")
    >>> with AtomicWriter(target) as f:
    ...     _ = f.write("line 1\\n")
    ...     _ = f.write("line 2\\n")
    >>> open(target).read()
    'line 1\\nline 2\\n'
    """

    def __init__(self, path: PathLike, *, encoding: str = "utf-8", mode: str = "w"):
        self._path = Path(path)
        self._encoding = encoding
        self._mode = mode
        self._tmp_path: str | None = None
        self._fd: int | None = None
        self._file = None

    def __enter__(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fd, self._tmp_path = tempfile.mkstemp(
            dir=str(self._path.parent), suffix=".tmp"
        )
        if "b" in self._mode:
            self._file = os.fdopen(self._fd, self._mode)
        else:
            self._file = os.fdopen(self._fd, self._mode, encoding=self._encoding)
        return self._file

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            # Something went wrong — discard the temp file.
            self._file.close()
            try:
                os.unlink(self._tmp_path)
            except OSError:
                pass
            return False

        try:
            self._file.flush()
            _fsync(self._file.fileno())
            self._file.close()
            os.replace(self._tmp_path, str(self._path))
        except BaseException:
            try:
                os.unlink(self._tmp_path)
            except OSError:
                pass
            raise
        return False
