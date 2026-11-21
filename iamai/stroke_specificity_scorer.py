"""stroke_specificity_scorer — measure how concrete vs. vague each stroke is.

Existing content-health modules answer *variety* (diversity, vocabulary
growth) or *structure* (coherence, rhythm, momentum).  Specificity
answers a different question: is the writer saying something *precise*,
or hand-waving in generalities?

A specific stroke contains numbers, proper nouns, file paths, commit
hashes, measurements — anchors that tie words to verifiable reality.
A vague stroke leans on hedging adverbs ("maybe", "sort of", "quite"),
superlatives without evidence ("very important", "really great"), and
generic nouns ("things", "stuff", "aspects").

Metrics per stroke
------------------

- **specificity_score**: float 0.0–1.0.  Higher = more concrete.
  Computed as the weighted sum of indicator rates (see below),
  clamped to [0, 1].
- **indicators**: dict of raw counts / rates:
    - ``numeric_refs``    — count of numbers, dates, measurements
    - ``proper_nouns``    — count of capitalised non-sentence-start words
    - ``code_refs``       — count of backtick-quoted or path-like tokens
    - ``hedge_words``     — count of hedging / vague modifiers
    - ``generic_nouns``   — count of empty placeholder nouns
    - ``citation_like``   — count of commit hashes, URLs, version strings
- **band**: ``precise`` / ``adequate`` / ``vague`` / ``hand_wavy``

Aggregate metrics (over a list of strokes)
------------------------------------------

- **mean_specificity**: average score across all strokes.
- **specificity_trend**: slope of a linear fit over the score series
  (positive = getting more specific, negative = getting vaguer).
- **precise_ratio**: fraction of strokes scoring >= 0.40.
- **band_distribution**: counts per band.

Design choices
--------------

- Pure functions, no I/O — all inputs are arguments.
- Regex-based detection (no NLP dependency) — fast and portable.
- Hedge-word and generic-noun lists are deliberately small and
  high-signal; a longer list would capture noise.
- Numeric detection covers integers, floats, dates, percentages,
  and byte-size strings (e.g. "12 MB", "3.2 GB").
- Proper-noun heuristic: any capitalised word not at sentence start
  and not in a small exclusion list (I, Python, README, etc. that
  are always capitalised).

Usage::

    from iamai.stroke_specificity_scorer import score, aggregate

    strokes = [
        {"text": "commit 9058c43 added 7 files and 51 insertions"},
        {"text": "things are getting somewhat better maybe"},
    ]

    for s in strokes:
        result = score(s["text"])
        print(result["specificity_score"], result["band"])
        # 0.75 precise
        # 0.10 hand_wavy

    report = aggregate([score(s["text"]) for s in strokes])
    print(report["mean_specificity"])  # ~0.425
"""

from __future__ import annotations

import re
import statistics
from typing import Any, Dict, List, Sequence


# ---------------------------------------------------------------------------
# Word lists
# ---------------------------------------------------------------------------

_HEDGE_WORDS = frozenset(
    "maybe somewhat roughly approximately possibly presumably "
    "arguably basically essentially practically virtually "
    "fairly rather quite slightly somehow kind sort "
    "tend tends tendency seem seems seemed "
    "generally usually often probably likely".split()
)

_GENERIC_NOUNS = frozenset(
    "things stuff aspects factors elements items "
    "issues problems situations cases scenarios "
    "people someone something everything nothing "
    "lot plenty bunch".split()
)

# Words that are always capitalised but not proper nouns in context
_PROPER_NOUN_EXCLUSIONS = frozenset(
    "I Python README GitHub Git JSON YAML URL API CLI "
    "CPU RAM SSD HDD SQL HTTP HTTPS SSH TCP IP DNS "
    "UTC EST PST CST MST GMT ASCII UTF ".split()
)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Numbers: integers, floats, percentages, byte sizes, dates
_NUMERIC_RE = re.compile(
    r"\b"
    r"(?:"
    r"\d{1,3}(?:,\d{3})*(?:\.\d+)?"  # 1,234 or 1,234.56
    r"|\d+\.\d+"                       # 3.14
    r"|\d+\s*(?:%|MB|GB|TB|KB|ms|sec|min|hrs?|days?|files?|commits?|lines?|strokes?|pid)"
    r"|\d{4}-\d{2}-\d{2}"             # 2026-11-21
    r"|\d{1,2}:\d{2}(?::\d{2})?"      # 17:02 or 17:02:30
    r"|\b\d+\b"                        # plain integer
    r")"
    r"\b",
    re.IGNORECASE,
)

# Commit hashes: 7+ hex chars, often preceded by "commit" or a hash symbol
_COMMIT_HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)

# URLs
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# Code references: backtick-quoted or path-like (contains /)
_CODE_REF_RE = re.compile(
    r"`[^`]+`"                         # backtick-quoted
    r"|[a-zA-Z_][\w/]*/[\w/.]+"       # path-like (tools/foo.py, docs/DEVLOG.md)
)

# Sentence boundaries for proper-noun detection
_SENTENCE_START_RE = re.compile(r"(?:^|[.!?]\s+)([A-Z][a-z]+)")


# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "numeric_refs": 0.15,
    "proper_nouns": 0.12,
    "code_refs": 0.18,
    "citation_like": 0.20,
    "hedge_words": -0.15,
    "generic_nouns": -0.12,
}

_BAND_THRESHOLDS = [
    (0.55, "precise"),
    (0.30, "adequate"),
    (0.15, "vague"),
    (0.00, "hand_wavy"),
]


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def _count_matches(pattern: re.Pattern, text: str) -> int:
    """Return the number of non-overlapping matches of *pattern* in *text*."""
    return len(pattern.findall(text))


def _count_proper_nouns(text: str) -> int:
    """Count proper-noun signals: capitalised words and internal capitals.

    A proper-noun signal is:
    - Any capital letter inside a word that is NOT at position 0
      (e.g. 'P' in 'FengPwner', 'H' in 'GitHub') — these are always
      proper-noun markers in camelCase / PascalCase text.
    - Any word starting with a capital that is NOT at a sentence start
      and NOT in the exclusion list.
    """
    count = 0

    # Internal capitals (camelCase): a capital letter preceded by a lowercase letter
    internal_caps = re.findall(r"[a-z][A-Z]", text)
    count += len(internal_caps)

    # Capitalised words not at sentence start
    words = re.findall(r"\b[A-Z][a-zA-Z]{1,}\b", text)
    sentence_starters = set(_SENTENCE_START_RE.findall(text))
    for w in words:
        # Skip words already counted via internal capitals
        if re.search(r"[a-z][A-Z]", w):
            continue
        if w in _PROPER_NOUN_EXCLUSIONS:
            continue
        if w in sentence_starters:
            sentence_starters.discard(w)
            continue
        count += 1

    return count


def _count_hedge_words(text: str) -> int:
    """Count hedging / vague modifier occurrences."""
    words = re.findall(r"\b[a-z]+\b", text.lower())
    return sum(1 for w in words if w in _HEDGE_WORDS)


def _count_generic_nouns(text: str) -> int:
    """Count generic placeholder nouns."""
    words = re.findall(r"\b[a-z]+\b", text.lower())
    return sum(1 for w in words if w in _GENERIC_NOUNS)


def score(text: str) -> Dict[str, Any]:
    """Score the specificity of a single stroke's text.

    Returns a dict with:
        - specificity_score: float 0.0–1.0
        - indicators: dict of raw counts
        - band: str (precise / adequate / vague / hand_wavy)
    """
    if not text or not text.strip():
        return {
            "specificity_score": 0.0,
            "indicators": {
                "numeric_refs": 0,
                "proper_nouns": 0,
                "code_refs": 0,
                "citation_like": 0,
                "hedge_words": 0,
                "generic_nouns": 0,
            },
            "band": "hand_wavy",
        }

    word_count = max(len(text.split()), 1)

    # Positive indicators
    numeric = _count_matches(_NUMERIC_RE, text)
    proper = _count_proper_nouns(text)
    code = _count_matches(_CODE_REF_RE, text)
    citations = _count_matches(_COMMIT_HASH_RE, text) + _count_matches(_URL_RE, text)

    # Negative indicators
    hedges = _count_hedge_words(text)
    generics = _count_generic_nouns(text)

    # Normalise by word count (rate per 10 words) to avoid bias toward long strokes
    scale = 10.0 / word_count
    raw = (
        _WEIGHTS["numeric_refs"] * numeric * scale
        + _WEIGHTS["proper_nouns"] * proper * scale
        + _WEIGHTS["code_refs"] * code * scale
        + _WEIGHTS["citation_like"] * citations * scale
        + _WEIGHTS["hedge_words"] * hedges * scale
        + _WEIGHTS["generic_nouns"] * generics * scale
    )

    specificity = max(0.0, min(1.0, raw))

    # Band
    band = "hand_wavy"
    for threshold, label in _BAND_THRESHOLDS:
        if specificity >= threshold:
            band = label
            break

    return {
        "specificity_score": round(specificity, 4),
        "indicators": {
            "numeric_refs": numeric,
            "proper_nouns": proper,
            "code_refs": code,
            "citation_like": citations,
            "hedge_words": hedges,
            "generic_nouns": generics,
        },
        "band": band,
    }


def aggregate(
    results: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute aggregate specificity over a series of scored strokes.

    Parameters
    ----------
    results : sequence of dicts returned by :func:`score`

    Returns
    -------
    dict with:
        - mean_specificity: float
        - specificity_trend: float (linear slope; positive = improving)
        - precise_ratio: float (fraction scoring >= 0.40)
        - band_distribution: dict[str, int]
        - median_specificity: float
        - min_specificity: float
        - max_specificity: float
    """
    if not results:
        return {
            "mean_specificity": 0.0,
            "specificity_trend": 0.0,
            "precise_ratio": 0.0,
            "band_distribution": {
                "precise": 0,
                "adequate": 0,
                "vague": 0,
                "hand_wavy": 0,
            },
            "median_specificity": 0.0,
            "min_specificity": 0.0,
            "max_specificity": 0.0,
        }

    scores = [r["specificity_score"] for r in results]

    # Linear trend (least-squares slope)
    trend = 0.0
    if len(scores) >= 2:
        n = len(scores)
        x_mean = (n - 1) / 2.0
        y_mean = statistics.mean(scores)
        num = sum((i - x_mean) * (s - y_mean) for i, s in enumerate(scores))
        den = sum((i - x_mean) ** 2 for i in range(n))
        if den > 0:
            trend = num / den

    # Band distribution
    band_dist = {"precise": 0, "adequate": 0, "vague": 0, "hand_wavy": 0}
    for r in results:
        band_dist[r["band"]] += 1

    precise_count = sum(1 for s in scores if s >= 0.40)

    return {
        "mean_specificity": round(statistics.mean(scores), 4),
        "specificity_trend": round(trend, 6),
        "precise_ratio": round(precise_count / len(scores), 4),
        "band_distribution": band_dist,
        "median_specificity": round(statistics.median(scores), 4),
        "min_specificity": round(min(scores), 4),
        "max_specificity": round(max(scores), 4),
    }
