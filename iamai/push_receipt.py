"""Push receipt — tamper-evident record of successful git pushes.

After ``git push`` succeeds, the batch committer creates a *receipt*:
a small JSON document that records exactly which commits were pushed,
to which remote branch, and when.  The receipt includes a SHA-256
digest computed over the sorted list of commit hashes so that any
post-hoc tampering (deleting a commit from the log, or rewriting
history) can be detected.

Receipt format (``data/push_receipts.<writer>.jsonl``)::

    {
        "commits": ["a1b2c3", "d4e5f6"],
        "remote": "origin",
        "branch": "main",
        "digest": "9f86d081884c7d65...",
        "pushed_at": "2026-10-17T11:00:00+08:00",
        "seq": 42
    }

Fields:

- ``commits``   — list of short (7-char) commit hashes included in the push
- ``remote``    — remote name (typically ``"origin"``)
- ``branch``    — branch name (typically ``"main"``)
- ``digest``    — SHA-256 hex digest over the concatenated commit hashes
- ``pushed_at`` — ISO-8601 timestamp of the push
- ``seq``       — monotonically increasing push sequence number

The receipt file uses JSONL (one receipt per line) so that the full push
history is preserved as an append-only audit trail.

Usage::

    from iamai.push_receipt import (
        record_receipt, latest_receipt, verify_receipt,
        push_history, receipt_digest,
    )

    # After a successful push of commits ["a1b2c3", "d4e5f6"]:
    record_receipt(repo, writer="qwen",
                   commits=["a1b2c3", "d4e5f6"],
                   remote="origin", branch="main")

    # Retrieve the most recent receipt:
    r = latest_receipt(repo, writer="qwen")
    print(r["seq"], r["commits"])

    # Verify integrity:
    ok, reason = verify_receipt(repo, writer="qwen")

    # Full history:
    for r in push_history(repo, writer="qwen"):
        print(r["pushed_at"], len(r["commits"]), "commits")
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _receipts_path(repo: str | Path, writer: str = "qwen") -> Path:
    """Return the path to the receipts JSONL file for *writer*."""
    return Path(repo) / "data" / f"push_receipts.{writer}.jsonl"


def receipt_digest(commits: list[str]) -> str:
    """Compute SHA-256 hex digest over a list of commit hashes.

    The hashes are sorted to ensure deterministic output regardless of
    the order in which commits were pushed.
    """
    blob = "\n".join(sorted(commits)).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _next_seq(repo: str | Path, writer: str = "qwen") -> int:
    """Determine the next push sequence number."""
    path = _receipts_path(repo, writer)
    if not path.exists():
        return 1
    seq = 0
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    seq = max(seq, entry.get("seq", 0))
                except (json.JSONDecodeError, TypeError):
                    continue
    except OSError:
        return 1
    return seq + 1


def record_receipt(
    repo: str | Path,
    writer: str = "qwen",
    commits: list[str] | None = None,
    remote: str = "origin",
    branch: str = "main",
    pushed_at: str | None = None,
) -> dict:
    """Append a push receipt to the receipts file.

    Parameters
    ----------
    repo : path to the repository root
    writer : writer identifier (default ``"qwen"``)
    commits : list of commit hash strings included in this push
    remote : remote name (default ``"origin"``)
    branch : branch name (default ``"main"``)
    pushed_at : ISO-8601 timestamp; defaults to current UTC time

    Returns the receipt dict that was written.
    """
    if commits is None:
        commits = []
    if pushed_at is None:
        pushed_at = datetime.now(timezone.utc).isoformat()

    seq = _next_seq(repo, writer)
    receipt = {
        "commits": list(commits),
        "remote": remote,
        "branch": branch,
        "digest": receipt_digest(commits),
        "pushed_at": pushed_at,
        "seq": seq,
    }

    path = _receipts_path(repo, writer)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Append with fsync for crash safety.
    line = json.dumps(receipt, separators=(",", ":")) + "\n"
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)

    return receipt


def latest_receipt(repo: str | Path, writer: str = "qwen") -> dict | None:
    """Return the most recent push receipt, or ``None`` if none exists."""
    path = _receipts_path(repo, writer)
    if not path.exists():
        return None
    last = None
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
    except OSError:
        return None
    return last


def verify_receipt(
    repo: str | Path, writer: str = "qwen", seq: int | None = None
) -> tuple[bool, str]:
    """Verify the integrity of a push receipt.

    If *seq* is given, verify that specific receipt; otherwise verify
    the latest receipt.

    Returns ``(True, "ok")`` if valid, ``(False, reason)`` otherwise.
    """
    path = _receipts_path(repo, writer)
    if not path.exists():
        return False, "no receipts file"

    target = None
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if seq is not None and entry.get("seq") == seq:
                    target = entry
                    break
                if seq is None:
                    target = entry
    except OSError as e:
        return False, f"read error: {e}"

    if target is None:
        if seq is not None:
            return False, f"receipt seq {seq} not found"
        return False, "no valid receipts"

    # Check required fields.
    for key in ("commits", "digest", "pushed_at", "seq"):
        if key not in target:
            return False, f"missing field: {key}"

    # Verify digest.
    expected = receipt_digest(target["commits"])
    if expected != target["digest"]:
        return False, "digest mismatch (possible tampering)"

    return True, "ok"


def push_history(
    repo: str | Path, writer: str = "qwen"
) -> list[dict]:
    """Return all push receipts in chronological order."""
    path = _receipts_path(repo, writer)
    if not path.exists():
        return []
    receipts = []
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    receipts.append(json.loads(line))
                except (json.JSONDecodeError, TypeError):
                    continue
    except OSError:
        return []
    return receipts


def verify_chain(repo: str | Path, writer: str = "qwen") -> tuple[bool, str]:
    """Verify the integrity of the entire push history.

    Checks that:
    1. Every receipt has a valid digest.
    2. Sequence numbers are monotonically increasing.
    3. No gaps in the sequence.

    Returns ``(True, "ok")`` if the chain is valid.
    """
    history = push_history(repo, writer)
    if not history:
        return False, "no receipts"

    prev_seq = 0
    for i, receipt in enumerate(history):
        # Check required fields.
        for key in ("commits", "digest", "pushed_at", "seq"):
            if key not in receipt:
                return False, f"receipt {i}: missing field {key}"

        # Verify digest.
        expected = receipt_digest(receipt["commits"])
        if expected != receipt["digest"]:
            return False, f"receipt {i} (seq {receipt['seq']}): digest mismatch"

        # Check sequence monotonicity.
        if receipt["seq"] <= prev_seq:
            return False, (
                f"receipt {i}: seq {receipt['seq']} <= prev {prev_seq}"
            )

        # Check for gaps.
        if receipt["seq"] != prev_seq + 1:
            return False, (
                f"receipt {i}: seq gap {prev_seq} -> {receipt['seq']}"
            )

        prev_seq = receipt["seq"]

    return True, "ok"


def total_pushes(repo: str | Path, writer: str = "qwen") -> int:
    """Return the number of recorded pushes."""
    return len(push_history(repo, writer))


def total_commits_pushed(repo: str | Path, writer: str = "qwen") -> int:
    """Return the total number of commits across all recorded pushes."""
    return sum(len(r.get("commits", [])) for r in push_history(repo, writer))


def reset_receipts(repo: str | Path, writer: str = "qwen") -> bool:
    """Remove the receipts file.  Returns ``True`` if it existed."""
    path = _receipts_path(repo, writer)
    if path.exists():
        path.unlink()
        return True
    return False
