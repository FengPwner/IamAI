#!/usr/bin/env python3
"""stroke_dedup — detect duplicate and near-duplicate strokes.

The writer produces a stroke every 15 seconds.  At that cadence, repetition
is inevitable: the same observation rephrased, the same module name cycling
through a template, the same insight copy-pasted across visits.  This module
provides fast fingerprinting and similarity scoring so the caretaker can
detect **content rot** before it floods the JSONL.

Why this matters
----------------
A stalled writer is obvious — no output.  A *repeating* writer is subtle —
output keeps flowing, metrics look healthy, but the content is stale.  The
limits.md log already shows this pattern: ``retry.py is already in the pool
of 9 modules, nothing new to add there`` repeated verbatim across dozens of
consecutive strokes.  Dedup catches that failure mode.

Approach
--------

1. **Exact fingerprint** — normalize whitespace, lowercase, strip punctuation,
   then hash.  Two strokes with the same fingerprint are byte-identical after
   normalization.

2. **Token-set Jaccard** — tokenize on whitespace + punctuation boundaries,
   compute Jaccard similarity of the token sets.  Score ≥ 0.85 = "near-dup".

3. **Rolling window scan** — given a list of strokes, slide a window and
   report any pair within it that is exact or near-dup.

Public API
----------
- ``fingerprint(text) -> str``
- ``jaccard_similarity(a, b) -> float``
- ``is_near_dup(a, b, threshold=0.85) -> bool``
- ``scan_duplicates(strokes, window=50, threshold=0.85) -> list[DupPair]``
- ``dedup_ratio(strokes, window=200, threshold=0.85) -> float``

Usage::

    from iamai.stroke_dedup import scan_duplicates

    pairs = scan_duplicates(strokes, window=50)
    for p in pairs:
        print(f"stroke {p.index_a} ≈ stroke {p.index_b}: {p.similarity:.2f}")
"""

from __future__ import annotations

import hashlib
import re
import string
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DupPair:
    """A detected duplicate pair."""

    index_a: int
    index_b: int
    similarity: float
    fingerprint_a: str
    fingerprint_b: str
    text_preview_a: str
    text_preview_b: str

    def summary(self) -> str:
        """One-line human-readable summary."""
        kind = "exact" if self.similarity >= 1.0 else "near-dup"
        return (
            f"{kind}: stroke {self.index_a} ≈ {self.index_b} "
            f"(sim={self.similarity:.3f})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "index_a": self.index_a,
            "index_b": self.index_b,
            "similarity": self.similarity,
            "fingerprint_a": self.fingerprint_a,
            "fingerprint_b": self.fingerprint_b,
            "text_preview_a": self.text_preview_a,
            "text_preview_b": self.text_preview_b,
        }


# ---------------------------------------------------------------------------
# Normalization & fingerprinting
# ---------------------------------------------------------------------------

_PUNCT_TABLE = str.maketrans("", "", string.punctuation)
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = text.translate(_PUNCT_TABLE)
    text = _WS_RE.sub(" ", text).strip()
    return text


def fingerprint(text: str) -> str:
    """Compute a stable SHA-256 fingerprint of normalized text.

    Two texts that differ only in case, punctuation, or whitespace
    will produce the same fingerprint.
    """
    normalized = _normalize(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Tokenization & similarity
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Extract lowercase alphanumeric tokens."""
    return set(_TOKEN_RE.findall(text.lower()))


def jaccard_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity of two texts based on token sets.

    Returns a float in [0.0, 1.0].
    Returns 1.0 for two empty texts (both have empty token sets).
    """
    tokens_a = _tokenize(a)
    tokens_b = _tokenize(b)

    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0

    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union > 0 else 0.0


def is_near_dup(a: str, b: str, threshold: float = 0.85) -> bool:
    """Return True if two texts are near-duplicates by Jaccard similarity."""
    return jaccard_similarity(a, b) >= threshold


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_duplicates(
    strokes: list[dict[str, Any]],
    window: int = 50,
    threshold: float = 0.85,
    text_field: str = "text",
) -> list[DupPair]:
    """Scan a list of strokes for duplicate pairs within a rolling window.

    Parameters
    ----------
    strokes : list[dict]
        Each dict should have a text field (default ``text``).
    window : int
        Maximum distance between two stroke indices to compare.
    threshold : float
        Jaccard similarity threshold for near-dup classification.
    text_field : str
        Key in each stroke dict that holds the text content.

    Returns
    -------
    List of DupPair instances, sorted by (index_a, index_b).
    """
    pairs: list[DupPair] = []
    n = len(strokes)

    # Pre-compute fingerprints and texts
    texts = [s.get(text_field, "") for s in strokes]
    fps = [fingerprint(t) for t in texts]

    seen_pairs: set[tuple[int, int]] = set()

    for i in range(n):
        # Compare with the next `window` strokes
        upper = min(i + window + 1, n)
        for j in range(i + 1, upper):
            key = (i, j)
            if key in seen_pairs:
                continue

            # Fast path: fingerprint match = exact dup
            if fps[i] == fps[j]:
                sim = 1.0
            else:
                sim = jaccard_similarity(texts[i], texts[j])

            if sim >= threshold:
                seen_pairs.add(key)
                preview_a = texts[i][:80] if texts[i] else ""
                preview_b = texts[j][:80] if texts[j] else ""
                pairs.append(DupPair(
                    index_a=i,
                    index_b=j,
                    similarity=round(sim, 4),
                    fingerprint_a=fps[i],
                    fingerprint_b=fps[j],
                    text_preview_a=preview_a,
                    text_preview_b=preview_b,
                ))

    pairs.sort(key=lambda p: (p.index_a, p.index_b))
    return pairs


def dedup_ratio(
    strokes: list[dict[str, Any]],
    window: int = 200,
    threshold: float = 0.85,
    text_field: str = "text",
) -> float:
    """Compute the fraction of strokes that are near-duplicates.

    A stroke is "duplicate" if it appears in any DupPair.  The ratio is
    ``unique_dup_indices / total_strokes``.  Returns 0.0 for empty input.
    """
    if not strokes:
        return 0.0

    pairs = scan_duplicates(strokes, window=window, threshold=threshold,
                            text_field=text_field)
    dup_indices: set[int] = set()
    for p in pairs:
        dup_indices.add(p.index_a)
        dup_indices.add(p.index_b)

    return len(dup_indices) / len(strokes)


# ---------------------------------------------------------------------------
# Consecutive-repeat detector
# ---------------------------------------------------------------------------

def find_consecutive_repeats(
    strokes: list[dict[str, Any]],
    min_run: int = 3,
    threshold: float = 0.85,
    text_field: str = "text",
) -> list[list[int]]:
    """Find runs of consecutive strokes that are near-duplicates.

    Returns a list of index lists, each representing a run of ≥ min_run
    consecutive strokes where every adjacent pair has Jaccard ≥ threshold.
    """
    if len(strokes) < min_run:
        return []

    texts = [s.get(text_field, "") for s in strokes]
    runs: list[list[int]] = []
    current_run = [0]

    for i in range(1, len(texts)):
        if is_near_dup(texts[i - 1], texts[i], threshold):
            current_run.append(i)
        else:
            if len(current_run) >= min_run:
                runs.append(current_run)
            current_run = [i]

    if len(current_run) >= min_run:
        runs.append(current_run)

    return runs
