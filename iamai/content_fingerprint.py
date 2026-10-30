"""Near-duplicate detection via content fingerprinting.

``stroke_dedup`` catches *exact* seed-phrase matches — the same thought
twice.  But a writer can also repeat itself more subtly: paraphrasing
the same idea, reusing the same metaphor, or copy-pasting a paragraph
with minor edits.  ``content_fingerprint`` catches those.

The approach is deliberately low-tech:

1.  **Tokenise** the text into words (lowercase, strip punctuation).
2.  **Build character n-grams** (default ``n=3``) for each token — this
    catches partial word overlap like "writing" vs "writer".
3.  **Compute Jaccard similarity** between two n-gram sets.
4.  Flag pairs above a configurable threshold (default ``0.6``).

Why not embeddings or TF-IDF?  Because this module runs inside a
15-second writer loop on a shared CPU.  A few hundred set-intersection
calls cost microseconds; a cosine-similarity model costs megabytes and
milliseconds.  Keep it cheap.

Public API
----------

.. code-block:: python

    from iamai.content_fingerprint import (
        fingerprint,
        jaccard_similarity,
        find_near_duplicates,
        near_duplicate_summary,
    )

    fp = fingerprint("the writer keeps writing about writing")
    pairs = find_near_duplicates(threshold=0.6)
    print(near_duplicate_summary())
    # "4 near-duplicate pairs across 1713 strokes (0.23%)"
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

STROKES_PATH = Path("data/strokes.jsonl")
DEFAULT_N = 3
DEFAULT_THRESHOLD = 0.6
MIN_TOKEN_LEN = 2  # skip single-char tokens for n-gram building


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _tokenise(text: str) -> List[str]:
    """Lowercase split on non-alpha, drop empties."""
    return [t for t in re.split(r"[^a-z]+", text.lower()) if t]


def _char_ngrams(token: str, n: int = DEFAULT_N) -> Set[str]:
    """Character n-grams of a single token."""
    if len(token) < n:
        return {token}
    return {token[i : i + n] for i in range(len(token) - n + 1)}


def fingerprint(text: str, n: int = DEFAULT_N) -> Set[str]:
    """Return the character-n-gram fingerprint of *text*.

    >>> sorted(fingerprint("hello world", n=3))
    ['ell', 'hel', 'ld', 'llo', 'lo ', 'o w', 'orl', 'rld', 'wo', 'wor']
    """
    tokens = _tokenise(text)
    ngrams: Set[str] = set()
    for tok in tokens:
        ngrams |= _char_ngrams(tok, n)
    # Also include inter-token bigrams so word boundaries contribute
    for i in range(len(tokens) - 1):
        bridge = tokens[i][-1:] + " " + tokens[i + 1][:1]
        if len(bridge) >= n:
            ngrams.add(bridge[:n])
    return ngrams


def jaccard_similarity(a: Set[str], b: Set[str]) -> float:
    """Jaccard index of two sets.  Returns 0.0 when both are empty."""
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# Stroke-level analysis
# ---------------------------------------------------------------------------


def _load_stroke_texts(path: Path = STROKES_PATH) -> List[Dict]:
    """Read strokes.jsonl, return list of {seq, kind, text, fingerprint}."""
    if not path.exists():
        return []
    entries = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = __import__("json").loads(line)
            except Exception:
                continue
            text = obj.get("text", "") or obj.get("seed", "")
            entries.append(
                {
                    "seq": obj.get("seq", 0),
                    "kind": obj.get("kind", "unknown"),
                    "text": text,
                    "fp": fingerprint(text),
                }
            )
    return entries


def find_near_duplicates(
    threshold: float = DEFAULT_THRESHOLD,
    max_pairs: int = 50,
    path: Path = STROKES_PATH,
) -> List[Tuple[int, int, float]]:
    """Return ``(seq_a, seq_b, similarity)`` pairs above *threshold*.

    Pairs are sorted by descending similarity.  At most *max_pairs* are
    returned to keep output manageable on large stroke logs.
    """
    strokes = _load_stroke_texts(path)
    pairs: List[Tuple[int, int, float]] = []
    for i in range(len(strokes)):
        for j in range(i + 1, len(strokes)):
            sim = jaccard_similarity(strokes[i]["fp"], strokes[j]["fp"])
            if sim >= threshold:
                pairs.append((strokes[i]["seq"], strokes[j]["seq"], sim))
    pairs.sort(key=lambda p: p[2], reverse=True)
    return pairs[:max_pairs]


def near_duplicate_summary(
    threshold: float = DEFAULT_THRESHOLD,
    path: Path = STROKES_PATH,
) -> str:
    """One-line human-readable summary."""
    pairs = find_near_duplicates(threshold=threshold, path=path)
    strokes = _load_stroke_texts(path)
    total = len(strokes)
    n = len(pairs)
    pct = (n / total * 100) if total else 0.0
    return f"{n} near-duplicate pair{'s' if n != 1 else ''} across {total} strokes ({pct:.2f}%)"


# ---------------------------------------------------------------------------
# Batch fingerprint comparison (for cross-kind analysis)
# ---------------------------------------------------------------------------


def kind_fingerprints(path: Path = STROKES_PATH) -> Dict[str, Set[str]]:
    """Aggregate fingerprint per stroke *kind*.

    Returns a dict mapping kind -> union of all fingerprints for that
    kind.  Useful for measuring how much topical overlap exists between
    e.g. "thought" strokes and "garden" strokes.
    """
    result: Dict[str, Set[str]] = {}
    for entry in _load_stroke_texts(path):
        kind = entry["kind"]
        if kind not in result:
            result[kind] = set()
        result[kind] |= entry["fp"]
    return result


def cross_kind_similarity(
    kind_a: str, kind_b: str, path: Path = STROKES_PATH
) -> float:
    """Jaccard similarity between the aggregate fingerprints of two kinds."""
    kfps = kind_fingerprints(path)
    a = kfps.get(kind_a, set())
    b = kfps.get(kind_b, set())
    return jaccard_similarity(a, b)
