"""Stroke saliency scorer — measure how information-dense each stroke is.

``stroke_novelty`` flags template repetition at the corpus level.
``stroke_echo`` catches near-duplicate pairs in short windows.
``stroke_diversity`` tracks category spread.
None of these answer a simpler question: **how much distinctive
information does this particular stroke carry?**

A stroke that says "the garden grew today" is grammatically fine,
topically coherent, and utterly forgettable.  A stroke that says
"exponential decay with half-life 3.2 commits predicts topic
dormancy better than linear ramp" is dense with signal.

Saliency analysis scores each stroke on two axes:

1. **Distinctiveness** — how rare are its words in the corpus?
   (IDF-weighted: rare words score high, common words score low.)
2. **Density** — what fraction of its tokens carry content?
   (Content words / total words, penalising filler-heavy prose.)

The product gives a **saliency score** that separates landmark
insights from background noise.

Concepts
--------

==================  ====================================================
term                meaning
==================  ====================================================
**idf**             inverse-document-frequency of a token across
                    the corpus; log(N / df) where df = number of
                    strokes containing the token
**distinctiveness** mean IDF of a stroke's content tokens,
                    normalised to 0–1 against the corpus max
**density**         content-token count / total token count
**saliency**        distinctiveness × density (0–1)
**band**            qualitative label for the saliency score
==================  ====================================================

Saliency bands
--------------

=====================  ==================================================
band                    description
=====================  ==================================================
**background**         saliency < 0.2 — filler, status updates, noise
**notable**            saliency 0.2–0.4 — ordinary but meaningful
**salient**            saliency 0.4–0.7 — high-information content
**landmark**           saliency > 0.7 — key insight, worth revisiting
=====================  ==================================================

Algorithm
---------
1. Tokenise each stroke into content tokens (len >= 4, lowercase,
   stopwords removed).
2. Build a document-frequency table across all strokes.
3. Compute IDF for each token: log(N / df) where N = total strokes.
4. Per stroke: distinctiveness = mean IDF / max IDF in corpus.
5. Per stroke: density = |content_tokens| / |all_tokens|.
6. saliency = distinctiveness × density.
7. Assign band.
8. Corpus-level summary: mean, median, distribution across bands.

Usage::

    from iamai import stroke_saliency
    report = stroke_saliency.saliency_report(strokes_text_list)
    for item in report["strokes"]:
        print(item["seq"], item["band"], round(item["saliency"], 3))
    print(report["summary"]["mean_saliency"])
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

# ── stopwords ──────────────────────────────────────────────────────────

_STOPWORDS = frozenset({
    "about", "above", "after", "again", "against", "all", "also",
    "am", "an", "and", "any", "are", "aren", "arent", "as", "at",
    "back", "because", "been", "before", "being", "below", "between",
    "both", "but", "by", "can", "cannot", "could", "couldn", "couldnt",
    "did", "didn", "didnt", "does", "doesn", "doesnt", "doing", "don",
    "done", "dont", "down", "during", "each", "few", "for", "from",
    "further", "get", "got", "had", "hadn", "hadnt", "has", "hasn",
    "hasnt", "have", "haven", "havent", "having", "he", "her", "here",
    "hers", "herself", "him", "himself", "his", "how", "however",
    "if", "in", "into", "is", "isn", "isnt", "it", "its", "itself",
    "just", "let", "like", "ll", "me", "might", "mightn", "mightnt",
    "more", "most", "much", "must", "mustn", "mustnt", "my", "myself",
    "need", "needn", "neednt", "no", "nor", "not", "now", "of", "off",
    "on", "once", "only", "or", "other", "our", "ours", "ourselves",
    "out", "over", "own", "re", "really", "right", "said", "same",
    "say", "says", "shall", "shan", "shant", "she", "should", "shouldn",
    "shouldnt", "since", "so", "some", "still", "such", "sure", "than",
    "that", "the", "their", "theirs", "them", "themselves", "then",
    "there", "these", "they", "this", "those", "through", "to", "too",
    "under", "until", "up", "upon", "us", "use", "used", "uses",
    "using", "very", "want", "was", "wasn", "wasnt", "we", "well",
    "were", "weren", "werent", "what", "when", "where", "which",
    "while", "who", "whom", "why", "will", "with", "won", "wont",
    "would", "wouldn", "wouldnt", "yet", "you", "your", "yours",
    "yourself", "yourselves", "also", "one", "two", "three", "four",
    "five", "six", "seven", "eight", "nine", "ten",
})

_TOKEN_RE = re.compile(r"[a-z']{2,}")


# ── tokenisation ───────────────────────────────────────────────────────


def extract_tokens(text: str) -> List[str]:
    """Return lowercase tokens from *text*, keeping only len >= 4 non-stopwords."""
    raw = _TOKEN_RE.findall(text.lower())
    return [t for t in raw if len(t) >= 4 and t not in _STOPWORDS]


def extract_all_tokens(text: str) -> List[str]:
    """Return all lowercase tokens (len >= 2) for density calculation."""
    return _TOKEN_RE.findall(text.lower())


# ── corpus IDF ─────────────────────────────────────────────────────────


def build_idf_table(corpus: Sequence[str]) -> Dict[str, float]:
    """Build IDF scores from a list of stroke texts.

    IDF(t) = log(N / df(t)) where N = number of documents (strokes)
    and df(t) = number of documents containing token t.
    Returns a dict mapping token → IDF score.
    """
    n = len(corpus)
    if n == 0:
        return {}
    df: Counter = Counter()
    for text in corpus:
        tokens = set(extract_tokens(text))
        for tok in tokens:
            df[tok] += 1
    return {tok: math.log(n / freq) for tok, freq in df.items()}


# ── per-stroke scoring ─────────────────────────────────────────────────


def stroke_distinctiveness(tokens: List[str], idf: Dict[str, float],
                           max_idf: float) -> float:
    """Mean IDF of *tokens*, normalised to 0–1 against *max_idf*.

    Returns 0.0 when tokens is empty or max_idf is zero.
    """
    if not tokens or max_idf <= 0:
        return 0.0
    total = sum(idf.get(t, 0.0) for t in tokens)
    return (total / len(tokens)) / max_idf


def stroke_density(text: str) -> float:
    """Fraction of tokens that are content-bearing (len >= 4, not stopword).

    Returns 0.0 for empty or whitespace-only text.
    """
    all_tok = extract_all_tokens(text)
    if not all_tok:
        return 0.0
    content = extract_tokens(text)
    return len(content) / len(all_tok)


def score_stroke(text: str, idf: Dict[str, float],
                 max_idf: float) -> Dict[str, Any]:
    """Score a single stroke for saliency.

    Returns dict with keys: distinctiveness, density, saliency, band,
    content_tokens, total_tokens.
    """
    tokens = extract_tokens(text)
    all_tok = extract_all_tokens(text)
    dist = stroke_distinctiveness(tokens, idf, max_idf)
    dens = stroke_density(text)
    sal = dist * dens
    return {
        "distinctiveness": round(dist, 6),
        "density": round(dens, 6),
        "saliency": round(sal, 6),
        "band": classify_band(sal),
        "content_tokens": len(tokens),
        "total_tokens": len(all_tok),
    }


# ── band classification ────────────────────────────────────────────────


def classify_band(saliency: float) -> str:
    """Map a saliency score to a qualitative band."""
    if saliency < 0.2:
        return "background"
    if saliency < 0.4:
        return "notable"
    if saliency < 0.7:
        return "salient"
    return "landmark"


# ── corpus report ──────────────────────────────────────────────────────


def saliency_report(strokes: Sequence[Dict[str, Any]],
                    window: Optional[int] = None) -> Dict[str, Any]:
    """Build a full saliency report over a sequence of strokes.

    Each element of *strokes* must be a dict with at least ``"text"``
    and ``"seq"`` keys.  If *window* is given, only the last *window*
    strokes are scored (but IDF is built from the full corpus for
    stability).

    Returns
    -------
    dict with keys:
        strokes  — list of per-stroke result dicts (seq, saliency, band, …)
        summary  — corpus-level statistics
    """
    if not strokes:
        return {"strokes": [], "summary": _empty_summary()}

    # Build IDF from full corpus
    all_texts = [s["text"] for s in strokes]
    idf = build_idf_table(all_texts)
    max_idf = max(idf.values()) if idf else 0.0

    # Apply window
    scoped = strokes[-window:] if window and window > 0 else strokes

    results: List[Dict[str, Any]] = []
    for s in scoped:
        sc = score_stroke(s["text"], idf, max_idf)
        sc["seq"] = s["seq"]
        results.append(sc)

    scores = [r["saliency"] for r in results]
    band_counts = Counter(r["band"] for r in results)

    summary = {
        "count": len(results),
        "mean_saliency": round(sum(scores) / len(scores), 6) if scores else 0.0,
        "max_saliency": round(max(scores), 6) if scores else 0.0,
        "min_saliency": round(min(scores), 6) if scores else 0.0,
        "median_saliency": round(_median(scores), 6),
        "band_distribution": dict(band_counts),
        "landmark_count": band_counts.get("landmark", 0),
        "background_ratio": round(
            band_counts.get("background", 0) / len(results), 6
        ) if results else 0.0,
    }

    return {"strokes": results, "summary": summary}


# ── snapshot delta ─────────────────────────────────────────────────────


def saliency_delta(before: Dict[str, Any],
                   after: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two saliency reports and return the delta.

    Both *before* and *after* must be outputs of :func:`saliency_report`.
    """
    bs = before.get("summary", {})
    as_ = after.get("summary", {})
    return {
        "count_change": as_.get("count", 0) - bs.get("count", 0),
        "mean_change": round(
            as_.get("mean_saliency", 0) - bs.get("mean_saliency", 0), 6
        ),
        "max_change": round(
            as_.get("max_saliency", 0) - bs.get("max_saliency", 0), 6
        ),
        "landmark_change": (
            as_.get("landmark_count", 0) - bs.get("landmark_count", 0)
        ),
        "background_ratio_change": round(
            as_.get("background_ratio", 0) - bs.get("background_ratio", 0), 6
        ),
    }


# ── helpers ────────────────────────────────────────────────────────────


def _median(values: List[float]) -> float:
    """Return the median of a list of floats."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _empty_summary() -> Dict[str, Any]:
    return {
        "count": 0,
        "mean_saliency": 0.0,
        "max_saliency": 0.0,
        "min_saliency": 0.0,
        "median_saliency": 0.0,
        "band_distribution": {},
        "landmark_count": 0,
        "background_ratio": 0.0,
    }
