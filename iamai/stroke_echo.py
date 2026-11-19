"""Stroke echo detector — find near-duplicate content in short windows.

``stroke_novelty`` measures template diversity over a long window.
``stroke_concept_recurrence`` tracks idea return after dormancy.
Neither catches the *short-term echo* problem: the writer producing
three strokes in a row that say almost the same thing in almost the
same words.

An echo is a pair or cluster of adjacent strokes whose word overlap
(Jaccard similarity) exceeds a threshold.  A stream with many echoes
is stuttering — the writer is burning cycles without saying anything
new.

Concepts
--------

==================  ====================================================
term                meaning
==================  ====================================================
**echo pair**       two consecutive strokes whose Jaccard similarity
                    >= echo_threshold
**echo cluster**    a maximal run of consecutive strokes where every
                    adjacent pair is an echo pair
**echo density**    fraction of strokes that belong to any echo cluster
**echo_depth**      max cluster length in the window
==================  ====================================================

Echo density bands
------------------

=====================  ==================================================
band                    description
=====================  ==================================================
**clear**              density < 0.1 — stream is diverse
**mild_echo**          density 0.1–0.3 — occasional repetition
**echo_chamber**       density 0.3–0.6 — writer is stuck in a groove
**stutter**            density > 0.6 — near-total loop, needs intervention
=====================  ==================================================

Algorithm
---------
1. Tokenise each stroke into a set of significant words (len >= 4,
   lowercase, stopwords removed).
2. Compute Jaccard similarity for every adjacent pair.
3. Mark pairs above *echo_threshold* (default 0.6).
4. Merge consecutive echo pairs into clusters.
5. Report: echo_pairs, clusters, echo_density, echo_depth, band.
6. Optionally compare two snapshots via *echo_delta*.

Usage::

    from iamai import stroke_echo
    report = stroke_echo.echo_report(strokes_text, window=50)
    print(report["band"])           # "clear" / "mild_echo" / ...
    print(report["echo_density"])   # 0.0 – 1.0
"""

from __future__ import annotations

from collections import Counter

# ---------------------------------------------------------------------------
# Stopwords (same list as stroke_concept_recurrence)
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    "that this these those from into with your have been will would "
    "could should their there they them than then what when where which "
    "about above after before between through during each other some such "
    "only same also very just more most much many few little".split()
)


def extract_tokens(text: str) -> set[str]:
    """Return significant word tokens from *text*."""
    words = text.lower().split()
    return {w.strip(".,;:!?\"'()-") for w in words if len(w) >= 4 and w not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def find_echo_pairs(token_sets: list[set[str]], threshold: float = 0.6) -> list[int]:
    """Return indices *i* where stroke i and stroke i+1 are an echo pair."""
    pairs = []
    for i in range(len(token_sets) - 1):
        if jaccard(token_sets[i], token_sets[i + 1]) >= threshold:
            pairs.append(i)
    return pairs


def build_clusters(echo_pairs: list[int]) -> list[list[int]]:
    """Merge consecutive echo pairs into stroke-index clusters.

    An echo pair at index i means strokes i and i+1 overlap.
    Consecutive pairs [3, 4, 5] form a single cluster [3, 4, 5, 6].
    """
    if not echo_pairs:
        return []
    clusters: list[list[int]] = []
    current = [echo_pairs[0], echo_pairs[0] + 1]
    for p in echo_pairs[1:]:
        if p == current[-1]:
            current.append(p + 1)
        else:
            clusters.append(current)
            current = [p, p + 1]
    clusters.append(current)
    return clusters


def classify_band(density: float) -> str:
    """Classify echo density into a severity band."""
    if density < 0.1:
        return "clear"
    if density < 0.3:
        return "mild_echo"
    if density < 0.6:
        return "echo_chamber"
    return "stutter"


def echo_report(
    texts: list[str],
    window: int | None = None,
    threshold: float = 0.6,
) -> dict:
    """Compute echo metrics over the stroke stream.

    Parameters
    ----------
    texts : list[str]
        Stroke text bodies in chronological order.
    window : int, optional
        If given, only the last *window* strokes are analysed.
    threshold : float
        Jaccard similarity threshold for echo detection.

    Returns
    -------
    dict with keys:
        total_strokes, analysed_strokes, echo_pairs (int),
        clusters (list[list[int]]), cluster_count (int),
        echo_depth (int — longest cluster),
        echo_strokes (int — strokes in any cluster),
        echo_density (float 0–1),
        band (str),
        top_echo (float — highest pairwise similarity found).
    """
    if window is not None:
        texts = texts[-window:]
    n = len(texts)
    if n < 2:
        return {
            "total_strokes": n,
            "analysed_strokes": n,
            "echo_pairs": 0,
            "clusters": [],
            "cluster_count": 0,
            "echo_depth": 0,
            "echo_strokes": 0,
            "echo_density": 0.0,
            "band": "clear",
            "top_echo": 0.0,
        }

    token_sets = [extract_tokens(t) for t in texts]
    pairs = find_echo_pairs(token_sets, threshold)
    clusters = build_clusters(pairs)

    # Strokes belonging to any cluster
    echo_stroke_indices: set[int] = set()
    for c in clusters:
        echo_stroke_indices.update(c)

    echo_strokes = len(echo_stroke_indices)
    density = echo_strokes / n if n else 0.0

    # Top echo (highest similarity)
    similarities = [
        jaccard(token_sets[i], token_sets[i + 1]) for i in range(n - 1)
    ]
    top_echo = max(similarities) if similarities else 0.0

    return {
        "total_strokes": n,
        "analysed_strokes": n,
        "echo_pairs": len(pairs),
        "clusters": clusters,
        "cluster_count": len(clusters),
        "echo_depth": max((len(c) for c in clusters), default=0),
        "echo_strokes": echo_strokes,
        "echo_density": round(density, 4),
        "band": classify_band(density),
        "top_echo": round(top_echo, 4),
    }


def echo_delta(before: dict, after: dict) -> dict:
    """Compare two echo snapshots and return the change.

    Parameters
    ----------
    before, after : dict
        Reports returned by :func:`echo_report`.

    Returns
    -------
    dict with keys:
        density_change (float), band_before, band_after,
        band_shifted (bool), depth_change (int),
        pair_change (int), direction (str).
    """
    d_before = before.get("echo_density", 0.0)
    d_after = after.get("echo_density", 0.0)
    density_change = round(d_after - d_before, 4)

    depth_change = after.get("echo_depth", 0) - before.get("echo_depth", 0)
    pair_change = after.get("echo_pairs", 0) - before.get("echo_pairs", 0)

    band_before = before.get("band", "clear")
    band_after = after.get("band", "clear")
    band_order = ["clear", "mild_echo", "echo_chamber", "stutter"]
    idx_before = band_order.index(band_before) if band_before in band_order else 0
    idx_after = band_order.index(band_after) if band_after in band_order else 0

    if idx_after > idx_before:
        direction = "worsening"
    elif idx_after < idx_before:
        direction = "improving"
    else:
        direction = "stable"

    return {
        "density_change": density_change,
        "band_before": band_before,
        "band_after": band_after,
        "band_shifted": band_before != band_after,
        "depth_change": depth_change,
        "pair_change": pair_change,
        "direction": direction,
    }
