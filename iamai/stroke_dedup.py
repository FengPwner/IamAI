"""stroke_dedup — detect near-duplicate strokes in writer output.

The automated writer appends a short aphorism or observation to one
of six note files every ~15 seconds.  Because the pool of aphorisms
is finite and the writer occasionally re-selects a recent one, the
notes accumulate near-duplicates: the same sentence with a different
stroke number or line count tacked on.

This module provides lightweight, token-set based duplicate detection
that can run inline during the write loop:

  - ``tokenize(text)``: whitespace + punctuation split, lowercased,
    with stopwords and bare numbers stripped.
  - ``jaccard(a, b)``: set-intersection over set-union of two token
    sets.  Returns 0.0 for two empty sets.
  - ``StrokeFingerprint``: immutable record of a stroke's token set
    and its source text hash, suitable for ring-buffer storage.
  - ``DedupResult``: outcome of a duplicate check — is_duplicate flag,
    similarity score, index of the best match (or -1), and a short
    human-readable reason.
  - ``StrokeDedup``: stateful detector with a sliding window.
    ``check(text)`` returns a DedupResult; ``record(text)`` adds a
    fingerprint to the window without checking.

Design decisions:
  - Token-set (not token-bag): word frequency doesn't matter for
    short aphorisms; presence/absence is sufficient and faster.
  - Numbers stripped: "tree is 2380 files" and "tree is 2395 files"
    should match despite different counts.
  - Ring buffer (fixed max size): memory-bounded even in long runs.
  - No external dependencies: pure stdlib so the writer loop never
    blocks on a missing package.

Usage::

    from iamai.stroke_dedup import StrokeDedup

    dedup = StrokeDedup(window=100, threshold=0.7)
    result = dedup.check("automation fails quietly, so the log …")
    if result.is_duplicate:
        skip_this_stroke()
    else:
        dedup.record("automation fails quietly, so the log …")
"""

from __future__ import annotations

import re
import hashlib
from collections import deque
from dataclasses import dataclass, field
from typing import FrozenSet, Optional

# ── constants ────────────────────────────────────────────────────────

#: Words stripped during tokenization — articles, copulas, and other
#: function words that add noise to similarity scoring.
STOPWORDS: FrozenSet[str] = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been",
    "am", "it", "its", "this", "that", "and", "or", "not", "no",
    "so", "if", "in", "on", "at", "to", "of", "by", "for", "as",
})

#: Default Jaccard similarity threshold above which two strokes are
#: considered near-duplicates.
DEFAULT_THRESHOLD: float = 0.7

#: Default sliding window size (number of fingerprints kept).
DEFAULT_WINDOW: int = 200

# ── tokenization ────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-z']+")


def tokenize(text: str) -> FrozenSet[str]:
    """Return the set of meaningful lower-case tokens in *text*.

    - Splits on non-alpha boundaries.
    - Lowercases everything.
    - Strips stopwords.
    - Strips bare-number tokens (e.g. "2380", "608917").
    - Strips tokens shorter than 2 characters.
    """
    raw = _TOKEN_RE.findall(text.lower())
    return frozenset(
        t for t in raw
        if t not in STOPWORDS
        and not t.isdigit()
        and len(t) >= 2
    )


# ── similarity ──────────────────────────────────────────────────────


def jaccard(a: FrozenSet[str], b: FrozenSet[str]) -> float:
    """Jaccard similarity of two sets.

    Returns 0.0 when both sets are empty (avoids ZeroDivisionError).
    """
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union


# ── data classes ────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrokeFingerprint:
    """Immutable fingerprint of a single stroke."""

    tokens: FrozenSet[str]
    text_hash: str  # sha256 hex-digest of the original text

    @classmethod
    def from_text(cls, text: str) -> "StrokeFingerprint":
        return cls(
            tokens=tokenize(text),
            text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        )


@dataclass(frozen=True)
class DedupResult:
    """Outcome of a duplicate check."""

    is_duplicate: bool
    similarity: float
    match_index: int          # index in the window, -1 if no match
    reason: str

    def __str__(self) -> str:
        if self.is_duplicate:
            return f"DUPLICATE (sim={self.similarity:.2f}, match@{self.match_index}): {self.reason}"
        return f"unique (sim={self.similarity:.2f}): {self.reason}"


# ── stateful detector ──────────────────────────────────────────────


class StrokeDedup:
    """Sliding-window near-duplicate detector for writer strokes.

    Parameters
    ----------
    window:
        Maximum number of fingerprints to keep.  Older entries are
        evicted FIFO.
    threshold:
        Jaccard similarity at or above which a stroke is flagged as
        a near-duplicate.
    """

    def __init__(
        self,
        window: int = DEFAULT_WINDOW,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self._window = max(1, window)
        self._threshold = threshold
        self._buffer: deque[StrokeFingerprint] = deque(maxlen=self._window)

    # ── public API ──────────────────────────────────────────────────

    def check(self, text: str) -> DedupResult:
        """Check *text* against the window **without** recording it.

        Returns a :class:`DedupResult` describing whether *text* is a
        near-duplicate of any stroke currently in the window.
        """
        fp = StrokeFingerprint.from_text(text)
        return self._compare(fp)

    def record(self, text: str) -> None:
        """Add *text* to the window without checking for duplicates."""
        self._buffer.append(StrokeFingerprint.from_text(text))

    def check_and_record(self, text: str) -> DedupResult:
        """Check *text* and, if **not** a duplicate, record it.

        If the text *is* a duplicate it is **not** recorded (to avoid
        polluting the window with repeated content).
        """
        result = self.check(text)
        if not result.is_duplicate:
            self.record(text)
        return result

    def clear(self) -> None:
        """Drop all fingerprints from the window."""
        self._buffer.clear()

    # ── introspection ───────────────────────────────────────────────

    @property
    def size(self) -> int:
        """Number of fingerprints currently in the window."""
        return len(self._buffer)

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def window_max(self) -> int:
        return self._window

    # ── internals ───────────────────────────────────────────────────

    def _compare(self, fp: StrokeFingerprint) -> DedupResult:
        # Exact-hash fast path: identical text → always duplicate.
        for idx, existing in enumerate(self._buffer):
            if existing.text_hash == fp.text_hash:
                return DedupResult(
                    is_duplicate=True,
                    similarity=1.0,
                    match_index=idx,
                    reason="exact text match",
                )

        # Token-set similarity scan.
        best_sim = 0.0
        best_idx = -1
        for idx, existing in enumerate(self._buffer):
            sim = jaccard(fp.tokens, existing.tokens)
            if sim > best_sim:
                best_sim = sim
                best_idx = idx

        if best_sim >= self._threshold and best_idx >= 0:
            return DedupResult(
                is_duplicate=True,
                similarity=best_sim,
                match_index=best_idx,
                reason="token-set similarity above threshold",
            )

        return DedupResult(
            is_duplicate=False,
            similarity=best_sim,
            match_index=best_idx,
            reason="below threshold" if self._buffer else "empty window",
        )
