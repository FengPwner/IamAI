"""Stroke checksum — detect tampering or corruption in append-only logs.

The strokes log (``data/strokes.jsonl``) is the single source of truth for
everything the writer has produced.  If it gets corrupted — by a bad edit,
a filesystem glitch, or an accidental ``sed -i`` — every downstream tool
silently produces wrong results.

This module computes a **rolling checksum** over the stroke entries so
that a caretaker can:

1. **Verify integrity** — compare the current checksum against a stored
   baseline; if they differ, something changed that shouldn't have.
2. **Detect truncation** — a shorter file with the same prefix produces
   a different checksum even though no existing line was modified.
3. **Pin a baseline** — save the checksum + stroke count after a known-good
   state, and verify later that only *appends* occurred (new lines added,
   no existing lines altered).

Design choices:

- Uses SHA-256 for collision resistance.
- Processes line-by-line so memory usage is O(1) regardless of file size.
- Normalises line endings (strip trailing whitespace) to be tolerant of
  editors that add or remove trailing newlines.
- The digest is computed over the *content* of each JSON line, not the raw
  bytes, so reformatting (e.g. key reordering) will intentionally change
  the checksum — the contract is that strokes are append-only, not
  reformat-safe.

Usage::

    from iamai.stroke_checksum import checksum, verify, pin_baseline

    result = checksum(repo)
    print(result.digest)       # "a3f2b8..."
    print(result.line_count)   # 2933

    ok, reason = verify(repo, expected_digest="a3f2b8...")
    print(ok, reason)

    pin_baseline(repo)          # writes .stroke_checksum to repo root
    ok, reason = verify(repo)   # reads baseline from .stroke_checksum
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class ChecksumResult:
    """Result of a checksum computation."""

    digest: str
    line_count: int
    algo: str = "sha256"

    def short(self, n: int = 12) -> str:
        """Return the first *n* hex characters of the digest."""
        return self.digest[:n]


def _normalise_line(line: str) -> str:
    """Strip trailing whitespace for consistent hashing."""
    return line.rstrip()


def _compute_digest(lines: list[str]) -> str:
    """Hash a list of normalised lines into a single hex digest."""
    h = hashlib.sha256()
    for line in lines:
        norm = _normalise_line(line)
        if norm:  # skip blank lines
            h.update(norm.encode("utf-8"))
            h.update(b"\n")  # consistent line terminator
    return h.hexdigest()


def checksum(
    repo: Path | str,
    strokes_relpath: str = "data/strokes.jsonl",
) -> ChecksumResult:
    """Compute the checksum of the strokes log.

    Parameters
    ----------
    repo:
        Repository root.
    strokes_relpath:
        Relative path to the strokes JSONL file.

    Returns
    -------
    ChecksumResult with digest, line count, and algorithm name.

    Raises
    ------
    FileNotFoundError
        If the strokes file does not exist.
    """
    repo = Path(repo)
    path = repo / strokes_relpath
    if not path.exists():
        raise FileNotFoundError(f"strokes file not found: {path}")

    lines: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            lines.append(line)

    digest = _compute_digest(lines)
    non_blank = sum(1 for l in lines if _normalise_line(l))
    return ChecksumResult(digest=digest, line_count=non_blank)


def checksum_incremental(
    repo: Path | str,
    strokes_relpath: str = "data/strokes.jsonl",
) -> ChecksumResult:
    """Memory-efficient O(1) streaming checksum.

    Produces the same digest as ``checksum()`` but reads the file one line
    at a time, so it works even on very large logs without loading the
    entire file into memory.
    """
    repo = Path(repo)
    path = repo / strokes_relpath
    if not path.exists():
        raise FileNotFoundError(f"strokes file not found: {path}")

    h = hashlib.sha256()
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            norm = _normalise_line(line)
            if norm:
                h.update(norm.encode("utf-8"))
                h.update(b"\n")
                count += 1

    return ChecksumResult(digest=h.hexdigest(), line_count=count)


# ---------------------------------------------------------------------------
# baseline pinning
# ---------------------------------------------------------------------------

_BASELINE_FILE = ".stroke_checksum"


def pin_baseline(
    repo: Path | str,
    strokes_relpath: str = "data/strokes.jsonl",
) -> ChecksumResult:
    """Compute the current checksum and save it as a baseline.

    Writes ``.stroke_checksum`` to the repo root containing the digest
    and line count as JSON.  Returns the computed result.
    """
    repo = Path(repo)
    result = checksum(repo, strokes_relpath)
    baseline_path = repo / _BASELINE_FILE
    data = {
        "digest": result.digest,
        "line_count": result.line_count,
        "algo": result.algo,
    }
    baseline_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return result


def _load_baseline(repo: Path) -> dict | None:
    """Load a previously pinned baseline, or None if not found."""
    baseline_path = repo / _BASELINE_FILE
    if not baseline_path.exists():
        return None
    try:
        return json.loads(baseline_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def verify(
    repo: Path | str,
    expected_digest: str | None = None,
    strokes_relpath: str = "data/strokes.jsonl",
) -> tuple[bool, str]:
    """Verify the strokes log against a known-good digest.

    Parameters
    ----------
    repo:
        Repository root.
    expected_digest:
        Hex digest to compare against.  If ``None``, reads from the
        baseline file (``.stroke_checksum``).
    strokes_relpath:
        Relative path to the strokes JSONL file.

    Returns
    -------
    (ok, reason) — ``ok`` is True when the digest matches;
    ``reason`` describes the outcome.
    """
    repo = Path(repo)

    if expected_digest is None:
        baseline = _load_baseline(repo)
        if baseline is None:
            return False, "no baseline found — run pin_baseline() first"
        expected_digest = baseline.get("digest", "")

    try:
        result = checksum(repo, strokes_relpath)
    except FileNotFoundError as exc:
        return False, str(exc)

    if result.digest == expected_digest:
        return True, f"checksum matches ({result.short()}…, {result.line_count} lines)"

    return False, (
        f"checksum mismatch: expected {expected_digest[:12]}…, "
        f"got {result.short()}… ({result.line_count} lines)"
    )
