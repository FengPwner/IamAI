"""stroke_dedup — detect and flag repetitive strokes in the writer output.

The writer occasionally enters a degenerate loop, emitting near-identical
strokes in rapid succession (e.g. "retry.py is already in the pool of
9 modules, nothing new to add there" repeated dozens of times).  Existing
cadence and backlog modules measure *timing* and *volume* but not
*content redundancy*.

This module fills that gap:

- ``fingerprint(stroke)`` — normalise a stroke's text to a comparable hash
- ``is_duplicate(prev, curr, threshold)`` — decide if two consecutive
  strokes are "the same" by fingerprint distance
- ``scan_window(strokes, window, threshold)`` — slide a window over a
  sequence and return indices of strokes that are duplicates of their
  predecessor
- ``dedup_report(strokes, window, threshold)`` — produce a summary dict
  with duplicate count, ratio, and the longest consecutive run

Design choices
--------------

- Fingerprints use lowercased, whitespace-collapsed text hashed with
  SHA-256 (first 16 hex chars).  Cheap, collision-resistant for this
  use case, and deterministic across runs.
- "Duplicate" means the fingerprint of the current stroke matches the
  fingerprint of its immediate predecessor.  No fuzzy matching — the
  degenerate loops we care about produce *exact* repeats.
- ``window`` is a look-back limit so ``scan_window`` can run on
  arbitrarily long streams without unbounded memory.

Zero dependencies beyond stdlib.

>>> strokes = [
...     "retry.py is already in the pool of 9 modules, nothing new to add there",
...     "retry.py is already in the pool of 9 modules, nothing new to add there",
...     "a genuinely new thought about the project's direction",
...     "retry.py is already in the pool of 9 modules, nothing new to add there",
... ]
>>> r = dedup_report(strokes)
>>> r["duplicate_count"]
2
>>> r["duplicate_ratio"] == 2 / 4
True
>>> r["longest_run"]
2
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

_WS_COLLAPSE = re.compile(r"\s+")


def fingerprint(text: str) -> str:
    """Return a 16-char hex fingerprint for *text*.

    Whitespace is collapsed, case is lowered, and the result is the
    first 16 hex characters of the SHA-256 digest.

    >>> len(fingerprint("hello world"))
    16
    >>> fingerprint("Hello  World") == fingerprint("hello world")
    True
    >>> fingerprint("") == fingerprint("  ")
    True
    """
    normalised = _WS_COLLAPSE.sub(" ", text.strip().lower())
    digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    return digest[:16]


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


def is_duplicate(prev_text: str, curr_text: str) -> bool:
    """Return True if *curr_text* is a fingerprint match for *prev_text*.

    >>> is_duplicate("hello", "hello")
    True
    >>> is_duplicate("hello", "world")
    False
    >>> is_duplicate("  Hello  ", "hello")
    True
    """
    return fingerprint(prev_text) == fingerprint(curr_text)


# ---------------------------------------------------------------------------
# Window scan
# ---------------------------------------------------------------------------


def scan_window(
    strokes: Sequence[str],
    window: int = 1,
) -> List[int]:
    """Return indices of strokes that duplicate their predecessor.

    Only ``window`` look-back is supported (default 1 = immediate
    predecessor).  The first stroke (index 0) is never flagged.

    >>> scan_window(["a", "b", "b", "c", "c", "c"])
    [2, 4, 5]
    >>> scan_window(["unique", "thoughts", "only"])
    []
    >>> scan_window([])
    []
    >>> scan_window(["solo"])
    []
    """
    if len(strokes) < 2:
        return []

    dupes: List[int] = []
    for i in range(1, len(strokes)):
        look_back = min(i, window)
        for j in range(i - look_back, i):
            if is_duplicate(strokes[j], strokes[i]):
                dupes.append(i)
                break
    return dupes


# ---------------------------------------------------------------------------
# Consecutive-run tracker
# ---------------------------------------------------------------------------


def _longest_consecutive_run(strokes: Sequence[str]) -> int:
    """Return the length of the longest run of identical consecutive strokes.

    A single stroke counts as a run of 1.

    >>> _longest_consecutive_run(["a", "a", "a", "b", "b"])
    3
    >>> _longest_consecutive_run(["x"])
    1
    >>> _longest_consecutive_run([])
    0
    >>> _longest_consecutive_run(["a", "b", "c"])
    1
    """
    if not strokes:
        return 0
    best = 1
    run = 1
    for i in range(1, len(strokes)):
        if is_duplicate(strokes[i - 1], strokes[i]):
            run += 1
            if run > best:
                best = run
        else:
            run = 1
    return best


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------


@dataclass
class DedupReport:
    """Structured deduplication report.

    Attributes
    ----------
    total : int
        Total strokes examined.
    duplicate_count : int
        Number of strokes flagged as duplicates.
    duplicate_ratio : float
        Fraction of strokes that are duplicates (0.0–1.0).
    longest_run : int
        Longest consecutive run of identical strokes.
    flagged_indices : list[int]
        Indices of all flagged strokes.
    """

    total: int
    duplicate_count: int
    duplicate_ratio: float
    longest_run: int
    flagged_indices: List[int] = field(default_factory=list)

    @property
    def is_degenerate(self) -> bool:
        """True when duplicate_ratio exceeds 50 % — writer is looping."""
        return self.duplicate_ratio > 0.5

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "duplicate_count": self.duplicate_count,
            "duplicate_ratio": self.duplicate_ratio,
            "longest_run": self.longest_run,
            "flagged_indices": self.flagged_indices,
            "is_degenerate": self.is_degenerate,
        }


def dedup_report(
    strokes: Sequence[str],
    window: int = 1,
) -> DedupReport:
    """Produce a :class:`DedupReport` for *strokes*.

    >>> r = dedup_report(["a", "a", "b", "a", "a", "a"])
    >>> r.total
    6
    >>> r.duplicate_count
    3
    >>> r.longest_run
    3
    >>> r.is_degenerate
    False

    Empty input is safe:

    >>> r = dedup_report([])
    >>> r.total
    0
    >>> r.duplicate_ratio
    0.0
    """
    flagged = scan_window(strokes, window)
    total = len(strokes)
    count = len(flagged)
    ratio = count / total if total else 0.0
    run = _longest_consecutive_run(strokes)
    return DedupReport(
        total=total,
        duplicate_count=count,
        duplicate_ratio=ratio,
        longest_run=run,
        flagged_indices=flagged,
    )
