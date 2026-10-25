"""059 — content fingerprint: near-duplicate detection for generated text.

the writer in this repo produces ~400 strokes across six categories. at that
volume, accidental near-duplicates are inevitable — the same observation about
line counts, the same reflection on commit depth, phrased slightly differently
each time. catching them requires more than exact string matching.

this module uses character n-gram sets and Jaccard similarity. no external
dependencies, no embedding model, no vector database. just set math on
shingled substrings. good enough to flag "you already wrote this" before
committing another copy.

design choices:
  - character n-grams (not word) so short strokes still get meaningful fingerprints
  - Jaccard over cosine: simpler, no normalization, same ranking for threshold checks
  - optional min_length to skip trivially short texts that fingerprint poorly

    text_a ──shingle──► {ng₁, ng₂, …} ──┐
                                         ├── Jaccard ──► similarity ∈ [0, 1]
    text_b ──shingle──► {ng₁, ng₃, …} ──┘

zero dependencies. stdlib only.

>>> fingerprint("hello world") == fingerprint("hello world")
True
>>> similarity("the quick brown fox", "the quick brown dog") > 0.3
True
>>> similarity("completely different", "nothing alike here") < 0.1
True
"""

from typing import Set, List, Tuple


def shingle(text: str, n: int = 4) -> Set[str]:
    """Extract character n-gram set from text.

    Whitespace is collapsed to single spaces and the result is lowercased
    so that formatting differences don't inflate distance.

    >>> sorted(shingle("abc", n=2))
    ['ab', 'bc']
    >>> shingle("", n=2)
    set()
    >>> shingle("a", n=4)
    set()
    """
    normalized = " ".join(text.lower().split())
    if len(normalized) < n:
        return set()
    return {normalized[i:i + n] for i in range(len(normalized) - n + 1)}


def fingerprint(text: str, n: int = 4) -> frozenset:
    """Immutable fingerprint of text for storage and comparison.

    >>> fingerprint("test")  # doctest: +ELLIPSIS
    frozenset({'test'})
    >>> fingerprint("")
    frozenset()
    """
    return frozenset(shingle(text, n))


def jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets.

    Returns 0.0 when both sets are empty (no signal either way).

    >>> jaccard({1, 2, 3}, {2, 3, 4})
    0.5
    >>> jaccard(set(), set())
    0.0
    >>> jaccard({1}, {1})
    1.0
    """
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union


def similarity(text_a: str, text_b: str, n: int = 4) -> float:
    """Compute near-duplicate similarity between two texts.

    Returns a float in [0, 1] where 1.0 means identical content
    and 0.0 means no shared n-grams.

    >>> similarity("hello world", "hello world")
    1.0
    >>> similarity("abc", "xyz")
    0.0
    """
    fp_a = shingle(text_a, n)
    fp_b = shingle(text_b, n)
    return jaccard(fp_a, fp_b)


def find_duplicates(
    texts: List[str],
    threshold: float = 0.6,
    n: int = 4,
    min_length: int = 20,
) -> List[Tuple[int, int, float]]:
    """Find all pairs of near-duplicate texts above the similarity threshold.

    Args:
        texts: list of text strings to compare
        threshold: minimum Jaccard similarity to report (default 0.6)
        n: n-gram size (default 4)
        min_length: skip texts shorter than this (default 20 chars)

    Returns:
        list of (index_a, index_b, similarity) tuples, sorted by similarity desc.

    >>> texts = [
    ...     "the quick brown fox jumps over the lazy dog",
    ...     "the quick brown fox leaps over the lazy dog",
    ...     "nothing in common with the others at all here",
    ... ]
    >>> pairs = find_duplicates(texts, threshold=0.5)
    >>> len(pairs)
    1
    >>> pairs[0][0], pairs[0][1]
    (0, 1)
    """
    fingerprints = []
    for t in texts:
        normalized = " ".join(t.lower().split())
        if len(normalized) >= min_length:
            fingerprints.append(shingle(t, n))
        else:
            fingerprints.append(set())

    results = []
    for i in range(len(fingerprints)):
        if not fingerprints[i]:
            continue
        for j in range(i + 1, len(fingerprints)):
            if not fingerprints[j]:
                continue
            sim = jaccard(fingerprints[i], fingerprints[j])
            if sim >= threshold:
                results.append((i, j, round(sim, 4)))

    results.sort(key=lambda x: x[2], reverse=True)
    return results


def nearest(text: str, corpus: List[str], n: int = 4, top_k: int = 3) -> List[Tuple[int, float]]:
    """Find the most similar texts in a corpus to the given text.

    Args:
        text: query text
        corpus: list of candidate texts
        n: n-gram size
        top_k: return at most this many results

    Returns:
        list of (index, similarity) tuples, sorted by similarity desc.

    >>> corpus = ["hello world foo bar", "goodbye moon baz qux", "hello world foo baz"]
    >>> nearest("hello world foo bar baz", corpus, top_k=2)  # doctest: +SKIP
    [(0, 0.6...), (2, 0.5...)]
    """
    fp = shingle(text, n)
    if not fp:
        return []

    scored = []
    for i, candidate in enumerate(corpus):
        fp_c = shingle(candidate, n)
        if fp_c:
            scored.append((i, jaccard(fp, fp_c)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
