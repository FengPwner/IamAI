"""Atomic checkpoint — save and resume progress across crashes."""

import hashlib
import hmac
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


class Checkpoint:
    """Persist a progress marker atomically so a restarted process can resume.

    The file is written to a sibling temp file first, then renamed into place.
    A SHA-256 digest guards against partial-write corruption.

    >>> import tempfile, pathlib
    >>> p = pathlib.Path(tempfile.mkdtemp()) / "cp.json"
    >>> cp = Checkpoint(p)
    >>> cp.save({"stroke": 42, "file": "notes/a.md"})
    >>> loaded = cp.load()
    >>> loaded["stroke"]
    42
    >>> loaded["file"]
    'notes/a.md'
    >>> cp.age() < 2  # seconds since save
    True
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    # ---- public API ----

    def save(self, data: dict[str, Any]) -> None:
        """Atomically write *data* as JSON with an integrity digest."""
        if not isinstance(data, dict):
            raise TypeError("checkpoint data must be a dict")

        payload = {
            "ts": time.time(),
            "data": data,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        payload["sha256"] = digest
        final = json.dumps(payload, ensure_ascii=False, sort_keys=True)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self.path.parent), suffix=".tmp"
        )
        try:
            os.write(fd, final.encode())
            os.fsync(fd)
            os.close(fd)
            os.replace(tmp, str(self.path))
        except BaseException:
            os.close(fd) if not self._fd_closed(fd) else None
            Path(tmp).unlink(missing_ok=True)
            raise

    def load(self) -> dict[str, Any] | None:
        """Load the last saved checkpoint, or None if missing/corrupt."""
        if not self.path.exists():
            return None
        try:
            raw = self.path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            stored = payload.pop("sha256", None)
            if stored is None:
                return None
            expected = hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            if not _const_eq(stored, expected):
                return None  # corrupted
            return payload.get("data", {})
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def age(self) -> float | None:
        """Seconds since the checkpoint was saved, or None if absent."""
        if not self.path.exists():
            return None
        try:
            raw = self.path.read_text(encoding="utf-8")
            ts = json.loads(raw).get("ts")
            if ts is None:
                return None
            return time.time() - float(ts)
        except (json.JSONDecodeError, OSError, ValueError):
            return None

    def exists(self) -> bool:
        return self.path.exists()

    def remove(self) -> None:
        """Delete the checkpoint file."""
        self.path.unlink(missing_ok=True)

    # ---- internals ----

    @staticmethod
    def _fd_closed(fd: int) -> bool:
        try:
            os.fstat(fd)
            return False
        except OSError:
            return True


def _const_eq(a: str, b: str) -> bool:
    """Constant-time string comparison to avoid timing side-channels."""
    return hmac.compare_digest(a.encode(), b.encode())
