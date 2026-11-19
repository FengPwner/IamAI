"""stroke_cross_pollination — measure how ideas flow between stroke categories.

While ``stroke_concept_propagation`` tracks whether individual ideas persist
and ``stroke_thematic_coherence`` checks whether a batch stays on topic,
neither answers: *do ideas originating in one category (e.g. thought)
influence content in other categories (e.g. devlog, garden)?*

A healthy self-writing repo should show **cross-pollination**: an insight
first expressed as a *thought* should later appear in a *devlog* entry or
inform a *garden* note.  A metric concept coined in *metrics* might inspire
a *snippet*.  If categories are hermetically sealed — each using its own
vocabulary with no overlap — the stream is **siloed**.

This module quantifies four aspects of cross-category idea flow:

1. **Bridge words** — content words that first appear in one category
   and later appear in a *different* category.  The count and fraction
   of bridge words indicate how porous category boundaries are.

2. **Cross-category echo rate** — for each stroke, what fraction of its
   content words were previously used *only* in a different category?
   Averaged over all strokes, this gives the stream-level echo rate.

3. **Category influence matrix** — for each ordered pair of categories
   (A, B), count the number of bridge words that originated in A and
   spread to B.  Normalise to get an influence score.

4. **Pollination regime** — classify the overall stream as:

=============  =========================================================
regime         description
=============  =========================================================
**crossroads** high bridge-word fraction, many category pairs active
**source**     one category dominates as origin, others absorb
**siloed**     low bridge-word fraction, categories use distinct vocab
**convergent** many categories share the same pool from the start
=============  =========================================================

Algorithm
---------
For each stroke *s* with category *c*:

    new_words(s) = content_words(s) - union(content_words of all prior strokes)
    bridge_words(s) = { w in content_words(s) :
                        w first appeared in category X ≠ c,
                        and has NOT appeared in category c before }

    cross_echo(s) = |{ w in content_words(s) :
                       w appeared before ONLY in categories ≠ c }| /
                     |content_words(s)|

Influence matrix M[A][B] = total bridge words that originated in A
and first-crossed into B.

Regime classification uses bridge fraction and category entropy:

    crossroads = bridge_frac ≥ threshold AND entropy ≥ threshold
    source     = bridge_frac ≥ threshold AND entropy < threshold
                 (one origin dominates ≥ 60% of bridge words)
    siloed     = bridge_frac < threshold AND entropy < threshold
    convergent = bridge_frac < threshold AND entropy ≥ threshold
                 (shared pool from early on)

Edge cases
----------
* Empty input → zeroed report.
* Single category present → regime is "siloed" by definition.
* All strokes share the same vocabulary from stroke 1 → convergent.

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 730, 2026-11-19.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple


# ---------------------------------------------------------------------------
# Stopwords (same set used across stroke modules)
# ---------------------------------------------------------------------------

_STOPWORDS: Set[str] = {
    "about", "above", "after", "again", "against", "all", "almost",
    "also", "although", "always", "among", "another", "any", "anything",
    "around", "away", "back", "because", "been", "before", "being",
    "below", "between", "both", "but", "cannot", "come", "could",
    "different", "does", "doing", "done", "down", "during", "each",
    "enough", "even", "ever", "every", "everything", "first", "for",
    "from", "further", "give", "given", "going", "good", "great",
    "here", "high", "however", "important", "into", "just", "keep",
    "kind", "know", "large", "last", "later", "like", "line", "long",
    "look", "made", "make", "many", "more", "most", "much", "must",
    "need", "never", "next", "nothing", "number", "off", "often",
    "once", "only", "other", "over", "part", "place", "point", "right",
    "same", "second", "seem", "seems", "shall", "show", "side", "since",
    "small", "some", "such", "take", "than", "that", "their", "them",
    "then", "there", "these", "they", "thing", "think", "this", "those",
    "through", "time", "together", "under", "upon", "very", "want",
    "well", "were", "what", "when", "where", "which", "while", "will",
    "with", "without", "word", "work", "world", "would", "year", "your",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BridgeEvent:
    """A single word crossing from one category to another."""

    word: str
    origin_category: str
    target_category: str
    origin_stroke: int  # stroke index where word first appeared
    crossing_stroke: int  # stroke index where word first crossed


@dataclass
class CategoryPairInfluence:
    """Influence score between an ordered pair of categories."""

    origin: str
    target: str
    bridge_count: int
    influence_score: float  # bridge_count / total bridge words


@dataclass
class PollinationReport:
    """Overall cross-pollination health of the stroke stream."""

    total_strokes: int
    total_categories: int
    categories_seen: List[str]
    total_content_words: int
    total_bridge_words: int
    bridge_fraction: float  # bridge_words / total_content_words
    avg_cross_echo: float  # mean per-stroke cross-category echo
    influence_matrix: Dict[str, Dict[str, int]]  # M[origin][target]
    top_pairs: List[CategoryPairInfluence]
    bridge_events: List[BridgeEvent]
    regime: str  # crossroads / source / siloed / convergent
    dominant_source: Optional[str]  # category that originates most bridges


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------


def extract_content_words(text: str, min_len: int = 4) -> List[str]:
    """Extract lowercase content words, excluding stopwords."""
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    return [t for t in tokens if len(t) >= min_len and t not in _STOPWORDS]


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def find_bridge_events(
    texts: Sequence[str],
    categories: Sequence[str],
    min_len: int = 4,
) -> List[BridgeEvent]:
    """Identify every word that crosses from one category to another.

    A bridge event occurs when a content word that first appeared in
    category A later appears for the first time in category B (B ≠ A).

    Returns bridge events in chronological order (by crossing_stroke).
    """
    if len(texts) != len(categories):
        raise ValueError("texts and categories must have the same length")

    # Track: word -> { category -> first_stroke_index }
    word_cat_first: Dict[str, Dict[str, int]] = defaultdict(dict)
    # Track: word -> origin category (very first appearance)
    word_origin: Dict[str, Tuple[str, int]] = {}  # word -> (cat, stroke_idx)

    events: List[BridgeEvent] = []

    for idx, (text, cat) in enumerate(zip(texts, categories)):
        words = set(extract_content_words(text, min_len=min_len))
        for w in words:
            if w not in word_origin:
                # First appearance ever
                word_origin[w] = (cat, idx)
                word_cat_first[w][cat] = idx
            else:
                origin_cat, origin_idx = word_origin[w]
                # Check if this is the first time in a NEW category
                if cat not in word_cat_first[w]:
                    word_cat_first[w][cat] = idx
                    if cat != origin_cat:
                        events.append(BridgeEvent(
                            word=w,
                            origin_category=origin_cat,
                            target_category=cat,
                            origin_stroke=origin_idx,
                            crossing_stroke=idx,
                        ))

    events.sort(key=lambda e: e.crossing_stroke)
    return events


def compute_cross_echo_per_stroke(
    texts: Sequence[str],
    categories: Sequence[str],
    min_len: int = 4,
) -> List[float]:
    """For each stroke, fraction of content words previously seen ONLY
    in different categories.

    Returns a list of floats, one per stroke.  Strokes with no content
    words get 0.0.
    """
    if len(texts) != len(categories):
        raise ValueError("texts and categories must have the same length")

    # word -> set of categories seen so far (before current stroke)
    word_cats: Dict[str, Set[str]] = defaultdict(set)
    echoes: List[float] = []

    for idx, (text, cat) in enumerate(zip(texts, categories)):
        words = extract_content_words(text, min_len=min_len)
        if not words:
            echoes.append(0.0)
            continue

        cross_count = 0
        for w in words:
            if w in word_cats and word_cats[w] and cat not in word_cats[w]:
                cross_count += 1

        echoes.append(cross_count / len(words))

        # Update tracker
        for w in words:
            word_cats[w].add(cat)

    return echoes


def build_influence_matrix(
    events: Sequence[BridgeEvent],
) -> Dict[str, Dict[str, int]]:
    """Build M[origin][target] = count of bridge words."""
    matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for ev in events:
        matrix[ev.origin_category][ev.target_category] += 1
    # Convert to regular dicts
    return {k: dict(v) for k, v in matrix.items()}


def _entropy(values: Sequence[float]) -> float:
    """Shannon entropy of a probability distribution (base 2)."""
    total = sum(values)
    if total == 0:
        return 0.0
    probs = [v / total for v in values if v > 0]
    if not probs:
        return 0.0
    return -sum(p * math.log2(p) for p in probs)


def _classify_regime(
    bridge_fraction: float,
    category_entropy: float,
    max_entropy: float,
    dominant_fraction: float,
    bridge_threshold: float = 0.05,
    entropy_ratio_threshold: float = 0.6,
) -> str:
    """Classify the pollination regime.

    Parameters
    ----------
    bridge_fraction : fraction of content words that are bridge words.
    category_entropy : entropy of bridge-word origins across categories.
    max_entropy : maximum possible entropy (log2 of category count).
    dominant_fraction : fraction of bridge words from the top origin.
    bridge_threshold : minimum bridge_fraction to consider "active".
    entropy_ratio_threshold : entropy/max_entropy ratio for "diverse".
    """
    active = bridge_fraction >= bridge_threshold
    diverse = (
        max_entropy > 0
        and (category_entropy / max_entropy) >= entropy_ratio_threshold
    )

    if active and diverse:
        return "crossroads"
    elif active and not diverse:
        # Check if one source dominates
        if dominant_fraction >= 0.6:
            return "source"
        return "source"  # active but not diverse = source-like
    elif not active and diverse:
        return "convergent"
    else:
        return "siloed"


def analyse_pollination(
    texts: Sequence[str],
    categories: Sequence[str],
    min_len: int = 4,
    bridge_threshold: float = 0.05,
    entropy_ratio_threshold: float = 0.6,
) -> PollinationReport:
    """Analyse cross-category pollination of the stroke stream.

    Parameters
    ----------
    texts : sequence of stroke text contents.
    categories : sequence of stroke category labels (same length as texts).
    min_len : minimum word length for content words.
    bridge_threshold : minimum bridge fraction for "active" classification.
    entropy_ratio_threshold : entropy ratio for "diverse" classification.

    Returns
    -------
    PollinationReport with all cross-pollination metrics.
    """
    if not texts:
        return PollinationReport(
            total_strokes=0,
            total_categories=0,
            categories_seen=[],
            total_content_words=0,
            total_bridge_words=0,
            bridge_fraction=0.0,
            avg_cross_echo=0.0,
            influence_matrix={},
            top_pairs=[],
            bridge_events=[],
            regime="siloed",
            dominant_source=None,
        )

    # Find bridge events
    events = find_bridge_events(texts, categories, min_len=min_len)

    # Cross echo per stroke
    echoes = compute_cross_echo_per_stroke(texts, categories, min_len=min_len)
    avg_echo = sum(echoes) / len(echoes) if echoes else 0.0

    # Influence matrix
    matrix = build_influence_matrix(events)

    # Category stats
    cats_seen = sorted(set(categories))
    n_cats = len(cats_seen)

    # Count total content words
    all_content_words: Set[str] = set()
    for text in texts:
        all_content_words.update(extract_content_words(text, min_len=min_len))
    total_content = len(all_content_words)

    # Unique bridge words
    bridge_words = set(ev.word for ev in events)
    total_bridge = len(bridge_words)
    bridge_frac = total_bridge / total_content if total_content > 0 else 0.0

    # Origin counts for entropy and dominance
    origin_counts: Dict[str, int] = defaultdict(int)
    for ev in events:
        origin_counts[ev.origin_category] += 1

    origin_values = list(origin_counts.values()) if origin_counts else [0]
    cat_entropy = _entropy([float(v) for v in origin_values])
    max_entropy = math.log2(n_cats) if n_cats > 1 else 0.0

    dominant_cat = None
    dominant_frac = 0.0
    if origin_counts:
        dominant_cat = max(origin_counts, key=origin_counts.get)
        dominant_frac = origin_counts[dominant_cat] / total_bridge if total_bridge > 0 else 0.0

    regime = _classify_regime(
        bridge_frac, cat_entropy, max_entropy, dominant_frac,
        bridge_threshold=bridge_threshold,
        entropy_ratio_threshold=entropy_ratio_threshold,
    )

    # Top pairs
    pairs: List[CategoryPairInfluence] = []
    for origin, targets in matrix.items():
        for target, count in targets.items():
            score = count / total_bridge if total_bridge > 0 else 0.0
            pairs.append(CategoryPairInfluence(
                origin=origin,
                target=target,
                bridge_count=count,
                influence_score=score,
            ))
    pairs.sort(key=lambda p: p.bridge_count, reverse=True)

    return PollinationReport(
        total_strokes=len(texts),
        total_categories=n_cats,
        categories_seen=cats_seen,
        total_content_words=total_content,
        total_bridge_words=total_bridge,
        bridge_fraction=bridge_frac,
        avg_cross_echo=avg_echo,
        influence_matrix=matrix,
        top_pairs=pairs[:10],
        bridge_events=events,
        regime=regime,
        dominant_source=dominant_cat,
    )


# ---------------------------------------------------------------------------
# Sliding-window analysis
# ---------------------------------------------------------------------------


@dataclass
class WindowPollination:
    """Cross-pollination metrics for a sliding window."""

    start: int
    end: int
    bridge_count: int
    cross_echo_avg: float
    regime: str


def analyse_pollination_windows(
    texts: Sequence[str],
    categories: Sequence[str],
    window_size: int = 20,
    step: int = 10,
    min_len: int = 4,
) -> List[WindowPollination]:
    """Analyse cross-pollination in sliding windows over the stroke stream.

    Each window reports its own bridge count and cross-echo average,
    computed relative to the *entire prior stream* (not just the window).
    This shows how cross-pollination evolves over time.
    """
    if not texts:
        return []

    results: List[WindowPollination] = []

    # Build cumulative word->categories tracker up to each stroke
    word_cats_cumulative: List[Dict[str, Set[str]]] = []
    word_cats: Dict[str, Set[str]] = defaultdict(set)

    for idx, (text, cat) in enumerate(zip(texts, categories)):
        snapshot = {w: set(cs) for w, cs in word_cats.items()}
        word_cats_cumulative.append(snapshot)
        words = set(extract_content_words(text, min_len=min_len))
        for w in words:
            word_cats[w].add(cat)

    for start in range(0, len(texts), step):
        end = min(start + window_size, len(texts))
        if start >= len(texts):
            break

        window_bridge = 0
        window_echo_sum = 0.0
        window_echo_count = 0

        for idx in range(start, end):
            text = texts[idx]
            cat = categories[idx]
            words = extract_content_words(text, min_len=min_len)
            if not words:
                continue

            # Words known before this stroke
            prior_cats = word_cats_cumulative[idx]

            bridge_in_stroke = 0
            cross_in_stroke = 0

            for w in set(words):
                if w in prior_cats:
                    if cat not in prior_cats[w]:
                        bridge_in_stroke += 1
                    if prior_cats[w] and cat not in prior_cats[w]:
                        cross_in_stroke += 1

            window_bridge += bridge_in_stroke
            window_echo_sum += cross_in_stroke / len(words) if words else 0.0
            window_echo_count += 1

        avg_echo = window_echo_sum / window_echo_count if window_echo_count > 0 else 0.0

        # Simple regime for window
        total_words_window = sum(
            len(set(extract_content_words(texts[i], min_len=min_len)))
            for i in range(start, end)
        )
        bridge_frac_w = window_bridge / total_words_window if total_words_window > 0 else 0.0
        window_regime = "active" if bridge_frac_w >= 0.05 else "quiet"

        results.append(WindowPollination(
            start=start,
            end=end,
            bridge_count=window_bridge,
            cross_echo_avg=round(avg_echo, 4),
            regime=window_regime,
        ))

    return results
