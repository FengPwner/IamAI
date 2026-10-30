"""Stroke anchor — checkpoint for resuming batch commits after restart.

When the writer process restarts, the batch committer needs to know
where it left off: which strokes have already been committed and pushed,
and which are new since the last successful push.  Without this anchor,
a restart either re-commits everything (wasteful, noisy) or skips
uncommitted strokes (data loss).

This module persists a small JSON checkpoint — the *anchor* — after each
successful push.  On restart, the batch committer reads the anchor and
processes only strokes appended after the anchored offset.

Anchor format (``data/stroke_anchor.<writer>.json``)::

    {
        "offset": 48210,
        "last_seq": 399,
        "stroke_hash": "a1b2c3d4",
        "pushed_at": "2026-10-17T09:30:00+08:00"
    }

Fields:

- ``offset``      — byte offset in strokes.jsonl after last pushed stroke
- ``last_seq``    — sequence number of the last pushed stroke
- ``stroke_hash`` — first 8 hex chars of SHA-256 of the last pushed stroke
                    line (integrity check: if the file was rewritten or
                    truncated, the hash won't match)
- ``pushed_at``   — ISO-8601 timestamp of the push

Usage::

    from iamai.stroke_anchor import save_anchor, load_anchor, pending_since

    save_anchor(repo, writer="qwen", offset=48210, last_seq=399,
                stroke_line="...")

    anchor = load_anchor(repo, writer="qwen")
    print(anchor["last_seq"])  # 399

    n = pending_since(repo, writer="qwen")
    print(f"{n} strokes pending since anchor")

The anchor file is atomic (write-to-temp + rename) to survive crashes
mid-write.  A corrupt or missing anchor is treated as "no anchor" — the
caller decides whether to start from scratch or from the beginning of
the file.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _anchor_path(repo: str | Path, writer: str = "qwen") -> Path:
    """Return the path to the anchor file for *writer*."""
    return Path(repo) / "data" / f"stroke_anchor.{writer}.json"


def _stroke_hash(line: str) -> str:
    """Return first 8 hex chars of SHA-256 of *line*."""
    return hashlib.sha256(line.encode("utf-8")).hexdigest()[:8]


def save_anchor(
    repo: str | Path,
    writer: str = "qwen",
    offset: int = 0,
    last_seq: int = 0,
    stroke_line: str = "",
) -> dict:
    """Persist a new anchor after a successful push.

    Parameters
    ----------
    repo : path to the repository root
    writer : writer identifier (default ``"qwen"``)
    offset : byte offset in strokes.jsonl after the last pushed stroke
    last_seq : sequence number of the last pushed stroke
    stroke_line : the raw JSONL line of the last pushed stroke (for hashing)

    Returns the anchor dict that was written.
    """
    anchor = {
        "offset": offset,
        "last_seq": last_seq,
        "stroke_hash": _stroke_hash(stroke_line) if stroke_line else "",
        "pushed_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _anchor_path(repo, writer)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: write to temp file in same directory, then rename.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        os.write(fd, json.dumps(anchor, indent=2).encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        os.replace(tmp, str(path))
    except BaseException:
        os.close(fd) if not os.get_inheritable(fd) else None
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return anchor


def load_anchor(repo: str | Path, writer: str = "qwen") -> dict | None:
    """Load the anchor for *writer*, or ``None`` if missing/corrupt."""
    path = _anchor_path(repo, writer)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        # Basic schema validation.
        for key in ("offset", "last_seq", "stroke_hash", "pushed_at"):
            if key not in data:
                return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def verify_anchor(repo: str | Path, writer: str = "qwen") -> bool:
    """Check that the anchor's hash matches the actual stroke at *offset*.

    Returns ``True`` if the anchor is valid and its integrity check passes,
    ``False`` otherwise (missing anchor, corrupt file, hash mismatch).
    """
    anchor = load_anchor(repo, writer)
    if anchor is None:
        return False
    strokes_path = Path(repo) / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        return False
    try:
        content = strokes_path.read_text()
        # Find the line that ends just before the anchor offset.
        prefix = content[: anchor["offset"]]
        lines = prefix.splitlines()
        if not lines:
            return False
        last_line = lines[-1]
        return _stroke_hash(last_line) == anchor["stroke_hash"]
    except OSError:
        return False


def pending_since(repo: str | Path, writer: str = "qwen") -> int:
    """Count JSONL lines appended after the anchor offset.

    Returns 0 if no anchor exists or the file hasn't grown past it.
    """
    anchor = load_anchor(repo, writer)
    if anchor is None:
        return 0
    strokes_path = Path(repo) / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        return 0
    size = strokes_path.stat().st_size
    if size <= anchor["offset"]:
        return 0
    # Read only the tail of the file past the anchor.
    with open(strokes_path, "rb") as f:
        f.seek(anchor["offset"])
        tail = f.read()
    lines = [l for l in tail.splitlines() if l.strip()]
    return len(lines)


def reset_anchor(repo: str | Path, writer: str = "qwen") -> bool:
    """Remove the anchor file.  Returns ``True`` if it existed."""
    path = _anchor_path(repo, writer)
    if path.exists():
        path.unlink()
        return True
    return False
