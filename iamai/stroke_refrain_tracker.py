"""Stroke refrain tracker — find phrases the writer keeps returning to.

``stroke_echo_detector`` catches *accidental* near-duplicate strokes
(similarity ≥ 0.85).  ``stroke_repetition_detector`` flags exact
duplicates.  Neither answers a subtler question: *what ideas does the
writer deliberately revisit?*

A **refrain** is a content phrase (≥ 3 significant words) that appears
in multiple distinct strokes across the log.  Refrains are intellectual
touchstones — concepts, metaphors, or observations the writer finds
worth restating in different words.  Tracking them reveals:

* What the writer cares about most (top refrains)
* Whether the stream has a coherent intellectual spine or drifts
* How thematic density evolves over time (more refrains = deeper
  exploration; fewer = surface-level wandering)

Data model
----------

A **Refrain** records one recurring phrase:

================  =====================================================
field             meaning
================  =====================================================
``phrase``        the canonical (first-seen) form of the phrase
``count``         number of distinct strokes containing it
``stroke_indices`` indices of strokes where it appears
``first_seen``    index of the earliest stroke containing it
``last_seen``     index of the latest stroke containing it
================  =====================================================

Algorithm
---------
1. Tokenise each stroke into words, lowercased, stripping punctuation.
2. Extract all **content n-grams** (n = 3, 4, 5) after removing stop
   words.  Only n-grams with ≥ 2 content words survive.
3. Across all strokes, find n-grams that appear in ≥ 2 *distinct*
   strokes.  These are candidate refrains.
4. Merge overlapping candidates: if a 5-gram and a 4-gram share ≥ 3
   words and appear in the same set of strokes, keep the longer one.
5. Rank by ``count`` descending; break ties by ``phrase`` length
   descending (longer = more specific).

Refrain density
~~~~~~~~~~~~~~~

``refrain_density`` = total refrain-hits / total strokes.

================  =====================================================
density           verdict
================  =====================================================
≥ 0.5             ``thematic`` — strong intellectual spine
0.2 – 0.5         ``exploratory`` — some recurring threads
0.05 – 0.2        ``scattered`` — few callbacks
< 0.05            ``drifting`` — almost no revisitation
================  =====================================================

Sliding-window analysis
~~~~~~~~~~~~~~~~~~~~~~~

Split the stroke stream into non-overlapping windows of ``window_size``
strokes (default 50).  Compute refrain density per window to track how
thematic focus evolves:

* **tightening** — density increasing over time
* **stable** — density roughly constant
* **loosening** — density decreasing

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 732, 2026-11-19.
"""

from __future__ import annotations

import re
import string
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Stop words — removed before n-gram extraction
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by",
    "can", "could", "did", "do", "does", "done", "for", "from", "had",
    "has", "have", "he", "her", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "just", "let", "like", "ll", "may", "me",
    "might", "more", "most", "must", "my", "no", "nor", "not", "now",
    "of", "on", "or", "our", "out", "own", "re", "s", "she", "should",
    "so", "some", "still", "such", "t", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "those", "to",
    "too", "up", "us", "ve", "very", "was", "we", "were", "what",
    "when", "where", "which", "while", "who", "whom", "why", "will",
    "with", "would", "you", "your",
})

# Minimum content words in an n-gram for it to count
_MIN_CONTENT_WORDS = 2

# N-gram sizes to extract
_NGRAM_SIZES = (3, 4, 5)

# Minimum distinct strokes for an n-gram to be a refrain
_MIN_STROKE_COUNT = 2

# Default window size for sliding analysis
_DEFAULT_WINDOW_SIZE = 50


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Refrain:
    """A phrase that recurs across multiple strokes."""

    phrase: str
    count: int
    stroke_indices: Tuple[int, ...]
    first_seen: int
    last_seen: int

    @property
    def span(self) -> int:
        """Distance between first and last occurrence."""
        return self.last_seen - self.first_seen


@dataclass
class RefrainReport:
    """Summary of refrain analysis over a stroke stream."""

    refrains: List[Refrain]
    total_strokes: int
    total_refrain_hits: int
    density: float
    verdict: str  # "thematic" | "exploratory" | "scattered" | "drifting"

    @property
    def top_refrain(self) -> Optional[Refrain]:
        """The most frequently recurring phrase, or None."""
        return self.refrains[0] if self.refrains else None

    @property
    def unique_refrain_count(self) -> int:
        """Number of distinct refrains found."""
        return len(self.refrains)


@dataclass
class WindowRefrainInfo:
    """Refrain density for a single window of strokes."""

    window_index: int
    start_index: int
    end_index: int
    stroke_count: int
    refrain_hits: int
    density: float


@dataclass
class RefrainTrend:
    """How refrain density evolves across windows."""

    windows: List[WindowRefrainInfo]
    direction: str  # "tightening" | "stable" | "loosening"
    first_density: float
    last_density: float


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------


def _tokenise(text: str) -> List[str]:
    """Lowercase tokenise, strip punctuation, drop empties."""
    text = text.lower()
    # Replace punctuation with spaces
    table = str.maketrans(string.punctuation, " " * len(string.punctuation))
    text = text.translate(table)
    return [tok for tok in text.split() if tok]


def _content_words(tokens: List[str]) -> List[str]:
    """Filter out stop words, keep only content words."""
    return [tok for tok in tokens if tok not in _STOP_WORDS and len(tok) > 1]


# ---------------------------------------------------------------------------
# N-gram extraction
# ---------------------------------------------------------------------------


def extract_ngrams(tokens: List[str], n: int) -> List[Tuple[str, ...]]:
    """Extract all n-grams of size *n* from a token list.

    Each n-gram must contain at least ``_MIN_CONTENT_WORDS`` content words.
    Returns list of tuples (each tuple is one n-gram).
    """
    if len(tokens) < n:
        return []
    result = []
    for i in range(len(tokens) - n + 1):
        gram = tuple(tokens[i : i + n])
        content = [w for w in gram if w not in _STOP_WORDS and len(w) > 1]
        if len(content) >= _MIN_CONTENT_WORDS:
            result.append(gram)
    return result


def extract_all_ngrams(tokens: List[str]) -> List[Tuple[str, ...]]:
    """Extract content n-grams for all configured sizes."""
    result = []
    for size in _NGRAM_SIZES:
        result.extend(extract_ngrams(tokens, size))
    return result


# ---------------------------------------------------------------------------
# Refrain detection
# ---------------------------------------------------------------------------


def _build_ngram_index(stroke_texts: Sequence[str]) -> Dict[Tuple[str, ...], List[int]]:
    """Map each n-gram to the list of stroke indices containing it."""
    index: Dict[Tuple[str, ...], List[int]] = defaultdict(list)
    for idx, text in enumerate(stroke_texts):
        tokens = _content_words(_tokenise(text))
        seen_in_this_stroke: set = set()
        for gram in extract_all_ngrams(tokens):
            if gram not in seen_in_this_stroke:
                index[gram].append(idx)
                seen_in_this_stroke.add(gram)
    return dict(index)


def _merge_overlapping(
    candidates: Dict[Tuple[str, ...], List[int]],
) -> Dict[Tuple[str, ...], List[int]]:
    """Merge n-grams that share ≥ 3 words and the same stroke set.

    When merging, keep the longer n-gram as the canonical form.
    """
    items = sorted(candidates.items(), key=lambda kv: -len(kv[0]))
    merged: Dict[Tuple[str, ...], List[int]] = {}
    absorbed: set = set()

    for gram, indices in items:
        gram_set = set(gram)
        was_absorbed = False
        for existing_gram, existing_indices in list(merged.items()):
            overlap = len(gram_set & set(existing_gram))
            if overlap >= 3 and set(indices) == set(existing_indices):
                # Absorb: keep the longer gram
                was_absorbed = True
                break
        if not was_absorbed:
            merged[gram] = indices

    return merged


def detect_refrains(
    stroke_texts: Sequence[str],
    min_count: int = _MIN_STROKE_COUNT,
) -> List[Refrain]:
    """Find recurring phrases across the stroke stream.

    Parameters
    ----------
    stroke_texts : sequence of str
        Ordered stroke texts.
    min_count : int
        Minimum number of distinct strokes a phrase must appear in
        to qualify as a refrain (default 2).

    Returns
    -------
    list of Refrain, sorted by count descending, then phrase length
    descending.
    """
    if not stroke_texts:
        return []

    index = _build_ngram_index(stroke_texts)

    # Filter to n-grams appearing in >= min_count distinct strokes
    candidates = {
        gram: indices
        for gram, indices in index.items()
        if len(indices) >= min_count
    }

    if not candidates:
        return []

    # Merge overlapping n-grams
    merged = _merge_overlapping(candidates)

    # Build Refrain objects
    refrains = []
    for gram, indices in merged.items():
        sorted_indices = sorted(indices)
        phrase = " ".join(gram)
        refrains.append(
            Refrain(
                phrase=phrase,
                count=len(sorted_indices),
                stroke_indices=tuple(sorted_indices),
                first_seen=sorted_indices[0],
                last_seen=sorted_indices[-1],
            )
        )

    # Sort: count descending, then phrase length descending
    refrains.sort(key=lambda r: (-r.count, -len(r.phrase)))
    return refrains


# ---------------------------------------------------------------------------
# Refrain report
# ---------------------------------------------------------------------------


def _classify_density(density: float) -> str:
    """Classify refrain density into a verdict string."""
    if density >= 0.5:
        return "thematic"
    elif density >= 0.2:
        return "exploratory"
    elif density >= 0.05:
        return "scattered"
    else:
        return "drifting"


def refrain_report(
    stroke_texts: Sequence[str],
    min_count: int = _MIN_STROKE_COUNT,
) -> RefrainReport:
    """Compute a full refrain analysis report.

    Parameters
    ----------
    stroke_texts : sequence of str
        Ordered stroke texts.
    min_count : int
        Minimum stroke occurrences for a phrase to be a refrain.

    Returns
    -------
    RefrainReport with all refrains and summary statistics.
    """
    refrains = detect_refrains(stroke_texts, min_count=min_count)
    total_strokes = len(stroke_texts)

    # Total refrain hits = sum of (count - 1) for each refrain
    # (first occurrence isn't a "re-visitation")
    total_hits = sum(max(r.count - 1, 0) for r in refrains)

    density = total_hits / total_strokes if total_strokes > 0 else 0.0
    verdict = _classify_density(density)

    return RefrainReport(
        refrains=refrains,
        total_strokes=total_strokes,
        total_refrain_hits=total_hits,
        density=density,
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# Sliding-window analysis
# ---------------------------------------------------------------------------


def window_refrain_density(
    stroke_texts: Sequence[str],
    window_size: int = _DEFAULT_WINDOW_SIZE,
    min_count: int = _MIN_STROKE_COUNT,
) -> List[WindowRefrainInfo]:
    """Compute refrain density per non-overlapping window.

    Parameters
    ----------
    stroke_texts : sequence of str
        Ordered stroke texts.
    window_size : int
        Number of strokes per window.
    min_count : int
        Minimum stroke count for a phrase to qualify within a window.

    Returns
    -------
    list of WindowRefrainInfo, one per window.
    """
    if not stroke_texts or window_size < 1:
        return []

    windows: List[WindowRefrainInfo] = []
    for w_idx, start in enumerate(range(0, len(stroke_texts), window_size)):
        end = min(start + window_size, len(stroke_texts))
        chunk = stroke_texts[start:end]
        count = len(chunk)

        if count < min_count:
            windows.append(
                WindowRefrainInfo(
                    window_index=w_idx,
                    start_index=start,
                    end_index=end,
                    stroke_count=count,
                    refrain_hits=0,
                    density=0.0,
                )
            )
            continue

        refrains = detect_refrains(chunk, min_count=min_count)
        hits = sum(max(r.count - 1, 0) for r in refrains)
        dens = hits / count if count > 0 else 0.0

        windows.append(
            WindowRefrainInfo(
                window_index=w_idx,
                start_index=start,
                end_index=end,
                stroke_count=count,
                refrain_hits=hits,
                density=dens,
            )
        )

    return windows


def refrain_trend(
    stroke_texts: Sequence[str],
    window_size: int = _DEFAULT_WINDOW_SIZE,
    min_count: int = _MIN_STROKE_COUNT,
) -> RefrainTrend:
    """Analyse how refrain density evolves over time.

    Returns
    -------
    RefrainTrend with direction ("tightening", "stable", "loosening").
    """
    windows = window_refrain_density(stroke_texts, window_size, min_count)

    if len(windows) < 2:
        first_d = windows[0].density if windows else 0.0
        return RefrainTrend(
            windows=windows,
            direction="stable",
            first_density=first_d,
            last_density=first_d,
        )

    first_d = windows[0].density
    last_d = windows[-1].density
    delta = last_d - first_d

    if delta > 0.05:
        direction = "tightening"
    elif delta < -0.05:
        direction = "loosening"
    else:
        direction = "stable"

    return RefrainTrend(
        windows=windows,
        direction=direction,
        first_density=first_d,
        last_density=last_d,
    )
