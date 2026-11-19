"""Stroke resonance tracker — measure how strongly ideas propagate forward.

``stroke_persistence`` tracks *which* concepts survive across the stream.
``stroke_transition_tracker`` captures *connections* between consecutive
strokes.  Neither answers a simpler question: **does this particular
stroke's content echo into the ones that follow, and for how long?**

Resonance is the *forward projection* of a single stroke's ideas.  A
stroke with high resonance introduces concepts that the writer keeps
engaging with over the next several strokes; a stroke with zero
resonance drops ideas that are never picked up again.

This is not about repetition — it's about **generative momentum**.  A
resonant stroke seeds the stream; a dissonant one is a dead end.

Concepts
--------

==================  ====================================================
term                meaning
==================  ====================================================
**stroke_concepts** set of concept tokens extracted from one stroke
**forward_echo**    number of subsequent strokes (within window) that
                    share at least one concept with the source stroke
**resonance_score** forward_echo / window_size, range [0, 1]
**decay_curve**     list of per-offset overlap ratios within the window
**half_life**       offset at which overlap first drops below 0.5
==================  ====================================================

Algorithm
---------
1. Extract concept sets for every stroke (same function as
   ``stroke_persistence.extract_concepts``).
2. For each source stroke *i*, scan forward strokes *i+1 … i+W*
   (where *W* is the window size).  At each offset *k*, compute:

       overlap(k) = |concepts[i] ∩ concepts[i+k]| / max(|concepts[i]|, 1)

3. Derive per-stroke metrics:

   - ``forward_echo`` = count of offsets where overlap > 0
   - ``resonance_score`` = mean overlap across the window
   - ``peak_offset`` = offset with maximum overlap
   - ``decay_curve`` = [overlap(1), overlap(2), …, overlap(W)]
   - ``half_life`` = first offset where overlap < 0.5, or W if never

4. Aggregate into stream-level profile:

   - ``mean_resonance`` — mean of all per-stroke resonance scores
   - ``median_resonance`` — median of the same
   - ``resonant_count`` — strokes with resonance_score > threshold
   - ``dissonant_count`` — strokes with resonance_score == 0
   - ``resonance_ratio`` — resonant_count / total strokes
   - ``mean_half_life`` — mean half_life across resonant strokes
   - ``peak_distribution`` — Counter of peak_offset values

5. Classify stream resonance pattern:

===================  ==================================================
pattern              description
===================  ==================================================
**resonant**         mean_resonance > 0.3, most strokes propagate
**cascading**        half_life trending up — ideas gaining momentum
**fragmented**       most strokes are dissonant — ideas don't connect
**pulsing**          alternating high/low resonance — bursty engagement
===================  ==================================================

Zero dependencies.  stdlib only.

>>> texts = [
...     "machine learning algorithms process data efficiently",
...     "learning algorithms improve with more training data",
...     "training data quality affects algorithm performance",
...     "algorithm performance metrics guide optimization",
...     "optimization techniques enhance learning outcomes",
...     "completely unrelated thoughts about weather patterns",
...     "weather forecasting uses different methods entirely",
...     "sunny days make people happy in northern climates",
...     "nothing connects to anything else here today",
...     "random musings about coffee and afternoon naps",
... ]
>>> report = resonance_report(texts, window=3)
>>> report["stream_pattern"] in ("resonant", "cascading", "fragmented", "pulsing")
True
>>> report["total_strokes"]
10
>>> 0.0 <= report["mean_resonance"] <= 1.0
True
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, List, Sequence, Tuple


# ---------------------------------------------------------------------------
# Shared concept extraction (mirrors stroke_persistence for consistency)
# ---------------------------------------------------------------------------

_STOPWORDS: frozenset[str] = frozenset({
    "able", "also", "been", "both", "come", "could", "each", "even",
    "every", "find", "found", "from", "give", "given", "going", "have",
    "here", "into", "just", "keep", "kind", "know", "known", "last",
    "like", "long", "look", "made", "make", "many", "more", "most",
    "much", "must", "need", "next", "only", "other", "over", "part",
    "same", "said", "seen", "seem", "show", "side", "some", "such",
    "sure", "take", "tell", "than", "that", "their", "them", "then",
    "there", "these", "they", "thing", "think", "this", "those",
    "through", "time", "turn", "upon", "used", "very", "want", "well",
    "what", "when", "where", "which", "while", "will", "with", "word",
    "work", "would", "year",
})

_MIN_WORD_LEN = 4
_WORD_RE = re.compile(r"[a-z][a-z'_-]{3,}", re.IGNORECASE)

_DEFAULT_WINDOW = 5
_RESONANCE_THRESHOLD = 0.1  # above this -> "resonant" stroke


def extract_concepts(text: str) -> set[str]:
    """Extract significant concept tokens from text.

    Args:
        text: free-form stroke text.

    Returns:
        Set of lowercase concept words (len >= 4, not stopwords).

    >>> sorted(extract_concepts("machine learning algorithms process data"))
    ['algorithms', 'data', 'learning', 'machine', 'process']
    >>> extract_concepts("a b c")
    set()
    >>> extract_concepts("")
    set()
    """
    words = _WORD_RE.findall(text.lower())
    return {w for w in words if len(w) >= _MIN_WORD_LEN and w not in _STOPWORDS}


# ---------------------------------------------------------------------------
# Per-stroke resonance computation
# ---------------------------------------------------------------------------

def stroke_resonance(
    source_concepts: set[str],
    forward_concepts_list: list[set[str]],
) -> dict[str, Any]:
    """Compute forward resonance of one stroke against subsequent strokes.

    Args:
        source_concepts: concept set of the source stroke.
        forward_concepts_list: ordered list of concept sets for strokes
            following the source (typically length == window).

    Returns:
        Dict with keys: forward_echo, resonance_score, peak_offset,
        decay_curve, half_life.

    >>> src = {"alpha", "beta", "gamma"}
    >>> fwd = [
    ...     {"alpha", "beta", "delta"},
    ...     {"alpha", "epsilon"},
    ...     {"zeta", "eta"},
    ... ]
    >>> r = stroke_resonance(src, fwd)
    >>> r["forward_echo"]
    2
    >>> r["peak_offset"]
    1
    >>> r["half_life"]
    2
    """
    if not source_concepts or not forward_concepts_list:
        return {
            "forward_echo": 0,
            "resonance_score": 0.0,
            "peak_offset": 0,
            "decay_curve": [],
            "half_life": len(forward_concepts_list) if forward_concepts_list else 0,
        }

    src_size = len(source_concepts)
    overlaps: list[float] = []

    for fwd in forward_concepts_list:
        shared = len(source_concepts & fwd)
        overlaps.append(shared / src_size)

    forward_echo = sum(1 for o in overlaps if o > 0)
    resonance_score = sum(overlaps) / len(overlaps) if overlaps else 0.0

    peak_offset = overlaps.index(max(overlaps)) + 1 if overlaps else 0

    # Half-life: first offset where overlap drops below 0.5
    half_life = len(overlaps)  # default: never decays
    for i, o in enumerate(overlaps):
        if o < 0.5:
            half_life = i + 1
            break

    return {
        "forward_echo": forward_echo,
        "resonance_score": round(resonance_score, 4),
        "peak_offset": peak_offset,
        "decay_curve": [round(o, 4) for o in overlaps],
        "half_life": half_life,
    }


# ---------------------------------------------------------------------------
# Stream-level resonance profile
# ---------------------------------------------------------------------------

def _classify_stream(
    mean_resonance: float,
    resonance_ratio: float,
    half_life_trend: str,
    alternation_score: float,
) -> str:
    """Classify the overall resonance pattern of the stream.

    Args:
        mean_resonance: average resonance score across strokes.
        resonance_ratio: fraction of strokes that are resonant.
        half_life_trend: 'increasing', 'decreasing', or 'stable'.
        alternation_score: how much resonance alternates high/low (0-1).

    Returns:
        One of: 'resonant', 'cascading', 'fragmented', 'pulsing'.
    """
    # Pulsing: strong alternation between resonant and dissonant strokes
    if alternation_score > 0.5:
        return "pulsing"

    # Cascading: half-lives are getting longer
    if half_life_trend == "increasing" and mean_resonance > 0.15:
        return "cascading"

    # Resonant: most strokes propagate ideas forward
    if mean_resonance > 0.3 or resonance_ratio > 0.6:
        return "resonant"

    # Fragmented: ideas don't connect
    return "fragmented"


def _half_life_trend(half_lives: list[int]) -> str:
    """Determine trend of half-life values over the stream.

    Args:
        half_lives: ordered list of per-stroke half-life values.

    Returns:
        'increasing', 'decreasing', or 'stable'.

    >>> _half_life_trend([1, 2, 3, 4, 5])
    'increasing'
    >>> _half_life_trend([5, 4, 3, 2, 1])
    'decreasing'
    >>> _half_life_trend([3, 3, 3, 3])
    'stable'
    >>> _half_life_trend([])
    'stable'
    """
    if len(half_lives) < 3:
        return "stable"

    mid = len(half_lives) // 2
    first_half = statistics.mean(half_lives[:mid]) if mid > 0 else 0
    second_half = statistics.mean(half_lives[mid:]) if mid > 0 else 0

    if second_half > first_half * 1.2:
        return "increasing"
    if second_half < first_half * 0.8:
        return "decreasing"
    return "stable"


def _alternation_score(scores: list[float]) -> float:
    """Measure how much resonance alternates between high and low.

    Uses sign changes in the deviation from mean as a proxy for
    alternation.  Returns a value in [0, 1].

    Args:
        scores: ordered list of per-stroke resonance scores.

    Returns:
        Alternation intensity, 0 = smooth, 1 = fully alternating.

    >>> _alternation_score([0.8, 0.1, 0.7, 0.1, 0.8])
    1.0
    >>> _alternation_score([0.5, 0.5, 0.5, 0.5])
    0.0
    >>> _alternation_score([])
    0.0
    """
    if len(scores) < 3:
        return 0.0

    mean = statistics.mean(scores)
    signs = [1 if s >= mean else -1 for s in scores]
    changes = sum(
        1 for i in range(1, len(signs)) if signs[i] != signs[i - 1]
    )
    max_changes = len(signs) - 1
    return round(changes / max_changes, 4) if max_changes > 0 else 0.0


# ---------------------------------------------------------------------------
# Main report function
# ---------------------------------------------------------------------------

def resonance_report(
    stroke_texts: Sequence[str],
    *,
    window: int = _DEFAULT_WINDOW,
    threshold: float = _RESONANCE_THRESHOLD,
) -> dict[str, Any]:
    """Generate a resonance report for a stream of strokes.

    Args:
        stroke_texts: ordered sequence of stroke text strings.
        window: how many strokes forward to scan (default 5).
        threshold: resonance score above which a stroke is "resonant".

    Returns:
        Dict with keys:

        - ``total_strokes``: number of strokes in the stream.
        - ``window``: window size used.
        - ``per_stroke``: list of per-stroke resonance dicts.
        - ``mean_resonance``: mean of all per-stroke resonance scores.
        - ``median_resonance``: median of the same.
        - ``resonant_count``: strokes above threshold.
        - ``dissonant_count``: strokes with score == 0.
        - ``resonance_ratio``: resonant_count / total_strokes.
        - ``mean_half_life``: mean half-life of resonant strokes.
        - ``peak_distribution``: Counter of peak_offset values.
        - ``stream_pattern``: overall pattern classification.
        - ``top_resonant``: top 5 stroke indices by resonance score.

    >>> texts = ["alpha beta gamma"] * 8
    >>> r = resonance_report(texts, window=3)
    >>> r["stream_pattern"]
    'resonant'
    >>> r["mean_resonance"] >= 0.85
    True
    """
    total = len(stroke_texts)
    if total == 0:
        return {
            "total_strokes": 0,
            "window": window,
            "per_stroke": [],
            "mean_resonance": 0.0,
            "median_resonance": 0.0,
            "resonant_count": 0,
            "dissonant_count": 0,
            "resonance_ratio": 0.0,
            "mean_half_life": 0.0,
            "peak_distribution": {},
            "stream_pattern": "fragmented",
            "top_resonant": [],
        }

    # Step 1: extract concept sets
    concept_sets = [extract_concepts(t) for t in stroke_texts]

    # Step 2: compute per-stroke resonance
    per_stroke: list[dict[str, Any]] = []
    for i in range(total):
        fwd_end = min(i + window, total)
        fwd_list = concept_sets[i + 1: fwd_end + 1]
        result = stroke_resonance(concept_sets[i], fwd_list)
        result["stroke_index"] = i
        result["is_resonant"] = result["resonance_score"] > threshold
        per_stroke.append(result)

    # Step 3: aggregate
    scores = [s["resonance_score"] for s in per_stroke]
    mean_res = statistics.mean(scores) if scores else 0.0
    median_res = statistics.median(scores) if scores else 0.0

    resonant_strokes = [s for s in per_stroke if s["is_resonant"]]
    dissonant_strokes = [s for s in per_stroke if s["resonance_score"] == 0]
    resonant_count = len(resonant_strokes)
    dissonant_count = len(dissonant_strokes)
    resonance_ratio = resonant_count / total if total > 0 else 0.0

    half_lives = [s["half_life"] for s in resonant_strokes]
    mean_hl = statistics.mean(half_lives) if half_lives else 0.0

    peak_counts: Counter = Counter()
    for s in per_stroke:
        if s["peak_offset"] > 0:
            peak_counts[s["peak_offset"]] += 1

    # Step 4: classify stream pattern
    hl_trend = _half_life_trend(half_lives)
    alt_score = _alternation_score(scores)
    pattern = _classify_stream(mean_res, resonance_ratio, hl_trend, alt_score)

    # Step 5: top resonant strokes
    top_resonant = sorted(
        per_stroke, key=lambda s: s["resonance_score"], reverse=True
    )[:5]

    return {
        "total_strokes": total,
        "window": window,
        "per_stroke": per_stroke,
        "mean_resonance": round(mean_res, 4),
        "median_resonance": round(median_res, 4),
        "resonant_count": resonant_count,
        "dissonant_count": dissonant_count,
        "resonance_ratio": round(resonance_ratio, 4),
        "mean_half_life": round(mean_hl, 2),
        "peak_distribution": dict(peak_counts),
        "stream_pattern": pattern,
        "top_resonant": [
            {
                "stroke_index": s["stroke_index"],
                "resonance_score": s["resonance_score"],
                "forward_echo": s["forward_echo"],
                "half_life": s["half_life"],
            }
            for s in top_resonant
        ],
    }


# ---------------------------------------------------------------------------
# Convenience: resonance health check
# ---------------------------------------------------------------------------

def resonance_health(report: dict[str, Any]) -> str:
    """Return a one-word health assessment from a resonance report.

    Args:
        report: output of :func:`resonance_report`.

    Returns:
        One of: 'coherent', 'scattered', 'building', 'uneven'.

    >>> resonance_health({"stream_pattern": "resonant", "mean_resonance": 0.5})
    'coherent'
    >>> resonance_health({"stream_pattern": "fragmented", "mean_resonance": 0.05})
    'scattered'
    >>> resonance_health({"stream_pattern": "cascading", "mean_resonance": 0.3})
    'building'
    >>> resonance_health({"stream_pattern": "pulsing", "mean_resonance": 0.25})
    'uneven'
    """
    pattern = report.get("stream_pattern", "fragmented")
    if pattern == "resonant":
        return "coherent"
    if pattern == "cascading":
        return "building"
    if pattern == "pulsing":
        return "uneven"
    return "scattered"


# ---------------------------------------------------------------------------
# Utility: compare resonance between two sub-streams
# ---------------------------------------------------------------------------

def resonance_delta(
    earlier: Sequence[str],
    later: Sequence[str],
    *,
    window: int = _DEFAULT_WINDOW,
) -> dict[str, Any]:
    """Compare resonance between two halves of a stream.

    Useful for detecting whether the writer's ideas are becoming *more*
    or *less* connected over time.

    Args:
        earlier: stroke texts from the earlier period.
        later: stroke texts from the later period.
        window: forward window size.

    Returns:
        Dict with earlier/later resonance metrics and the delta.

    >>> early = ["alpha beta gamma"] * 5
    >>> late = ["alpha beta gamma", "delta epsilon zeta"] * 3
    >>> d = resonance_delta(early, late)
    >>> d["delta"] < 0  # later is less resonant
    True
    """
    r_early = resonance_report(earlier, window=window)
    r_late = resonance_report(later, window=window)

    delta = r_late["mean_resonance"] - r_early["mean_resonance"]

    return {
        "earlier_mean_resonance": r_early["mean_resonance"],
        "earlier_pattern": r_early["stream_pattern"],
        "later_mean_resonance": r_late["mean_resonance"],
        "later_pattern": r_late["stream_pattern"],
        "delta": round(delta, 4),
        "trend": "improving" if delta > 0.05 else (
            "declining" if delta < -0.05 else "stable"
        ),
    }


if __name__ == "__main__":
    import doctest
    doctest.testmod()
