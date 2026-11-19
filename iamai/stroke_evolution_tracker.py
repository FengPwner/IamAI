"""stroke_evolution_tracker — track how the stroke stream evolves over time.

While ``stroke_concept_propagation`` measures whether ideas *stick* and
``stroke_thematic_coherence`` checks whether a batch *stays on topic*,
neither answers: *is the stream getting deeper over time, or just
wandering?*

A self-writing repo should show **intellectual evolution**: early
strokes introduce surface-level observations, later strokes should
build on them with increasing nuance, cross-references, and synthesis.
If every stroke is at the same depth covering the same ground, the
stream is stagnant. If topics shift constantly without deepening,
the stream is wandering.

This module quantifies four dimensions of stream evolution:

1. **Depth progression** — are strokes getting structurally richer
   over time?  Measured via vocabulary complexity, sentence density,
   and cross-reference markers.
2. **Topic drift velocity** — how fast does the topic shift between
   consecutive stroke windows?  Low drift + high depth growth =
   deepening.  High drift + low depth growth = wandering.
3. **Callback density** — how often does a stroke reuse distinctive
   words from *distant* earlier strokes (not just recent ones)?
   High callback density indicates narrative threading.
4. **Evolution regime** — classify the overall stream as:

==============  =========================================================
regime          description
==============  =========================================================
**deepening**   topics stay relatively stable, depth increases steadily
**spiraling**   topics cycle back with increasing depth each pass
**wandering**   topics shift constantly, depth stays flat
**stagnating**  topics and depth both stay flat — no evolution
==============  =========================================================

Algorithm
---------
We process strokes in sequential windows of size *W* (default 10).

For each window we compute:

    depth(w) = normalised composite of:
        - mean unique-word count per stroke
        - mean sentence count per stroke (split on ``.!?``)
        - fraction of strokes containing cross-reference markers
          (words like *see*, *cf.*, *previously*, *earlier*, *above*,
          *recall*, *builds on*, *extends*)

    topic_similarity(w_i, w_{i+1}) = Jaccard(content_words(w_i),
                                               content_words(w_{i+1}))

    drift_velocity = 1 - mean(topic_similarity over consecutive pairs)

    callback_density(w) = |{strokes in w that reuse a content word
                            first seen ≥ 2W strokes ago}| / |w|

Evolution classification uses linear regression on depth scores
(slope direction) crossed with mean drift velocity:

    deepening  = depth_slope > threshold  AND drift < threshold
    spiraling  = depth_slope > threshold  AND drift ≥ threshold
                 AND callback_density high
    wandering  = depth_slope ≤ threshold  AND drift ≥ threshold
    stagnating = depth_slope ≤ threshold  AND drift < threshold

Edge cases
----------
* Empty input → zeroed report.
* Fewer than 2 windows → cannot compute drift; report partial.
* All strokes identical → drift = 0, depth constant → stagnating.

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 729, 2026-11-19.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# stopwords — same set as sibling modules
# ---------------------------------------------------------------------------
_STOPWORDS = frozenset(
    "a an the and or but not is are was were be been being have has had "
    "do does did will would shall should may might can could this that "
    "these those it its i me my we our you your he she they them their "
    "what which who whom how when where why all each every both few "
    "more most other some such no nor only own same so than too very "
    "just about above after again against as at be because before below "
    "between by during for from further here if in into of off on out "
    "over under until up with through to".split()
)

_CROSS_REF_MARKERS = frozenset(
    "see cf previously earlier above recall extends builds "
    "referenced mentioned introduced discussed established "
    "revisit revisit revisited revisiting complement complements "
    "counterpart prior preceding foregoing aforementioned".split()
)

_MIN_WORD_LEN = 4


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------

@dataclass
class WindowMetrics:
    """Metrics for a single window of strokes."""

    window_index: int
    stroke_range: Tuple[int, int]
    depth_score: float = 0.0
    unique_words: int = 0
    mean_sentences: float = 0.0
    cross_ref_fraction: float = 0.0
    callback_density: float = 0.0


@dataclass
class EvolutionReport:
    """Full evolution analysis report."""

    total_strokes: int = 0
    window_count: int = 0
    window_size: int = 10

    depth_scores: List[float] = field(default_factory=list)
    depth_slope: float = 0.0
    mean_depth: float = 0.0

    drift_velocities: List[float] = field(default_factory=list)
    mean_drift: float = 0.0

    callback_densities: List[float] = field(default_factory=list)
    mean_callback_density: float = 0.0

    regime: str = "stagnating"

    windows: List[WindowMetrics] = field(default_factory=list)

    def summary(self) -> str:
        """One-line human-readable summary."""
        if self.total_strokes == 0:
            return "no strokes to analyse"
        return (
            f"{self.regime} | depth_slope={self.depth_slope:+.4f} "
            f"drift={self.mean_drift:.3f} "
            f"callbacks={self.mean_callback_density:.3f} "
            f"({self.window_count} windows over {self.total_strokes} strokes)"
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def extract_content_words(text: str) -> List[str]:
    """Return lowercase content words ≥ ``_MIN_WORD_LEN`` chars."""
    tokens = re.findall(r"[a-z']+", text.lower())
    return [
        t.strip("'")
        for t in tokens
        if len(t.strip("'")) >= _MIN_WORD_LEN
        and t.strip("'") not in _STOPWORDS
    ]


def count_sentences(text: str) -> int:
    """Count sentences by splitting on terminal punctuation."""
    parts = re.split(r"[.!?]+", text)
    return sum(1 for p in parts if p.strip())


def has_cross_reference(text: str) -> bool:
    """Check whether *text* contains any cross-reference marker."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    return bool(words & _CROSS_REF_MARKERS)


def _linear_slope(values: Sequence[float]) -> float:
    """Compute the slope of a simple linear regression (y on x=0..n-1).

    Returns 0.0 for sequences shorter than 2.
    """
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


# ---------------------------------------------------------------------------
# core analysis
# ---------------------------------------------------------------------------


def compute_window_depth(strokes: Sequence[str]) -> Tuple[float, int, float, float]:
    """Compute composite depth score for a window of stroke texts.

    Returns (depth_score, total_unique_words, mean_sentences, cross_ref_fraction).
    """
    if not strokes:
        return 0.0, 0, 0.0, 0.0

    all_words: set = set()
    total_sentences = 0
    cross_ref_count = 0
    per_stroke_unique: list = []

    for text in strokes:
        words = extract_content_words(text)
        all_words.update(words)
        per_stroke_unique.append(len(set(words)))
        total_sentences += count_sentences(text)
        if has_cross_reference(text):
            cross_ref_count += 1

    n = len(strokes)
    mean_unique = sum(per_stroke_unique) / n
    mean_sentences = total_sentences / n
    cross_ref_frac = cross_ref_count / n

    # normalise components (heuristic scales)
    norm_unique = min(mean_unique / 30.0, 1.0)
    norm_sentences = min(mean_sentences / 5.0, 1.0)
    norm_crossref = min(cross_ref_frac / 0.5, 1.0)

    depth = 0.45 * norm_unique + 0.30 * norm_sentences + 0.25 * norm_crossref

    return depth, len(all_words), mean_sentences, cross_ref_frac


def compute_topic_similarity(
    words_a: Sequence[str], words_b: Sequence[str]
) -> float:
    """Jaccard similarity between two word sets."""
    set_a = set(words_a)
    set_b = set(words_b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def compute_callback_density(
    window_strokes: Sequence[str],
    prior_vocab: set,
) -> float:
    """Fraction of strokes that reuse a word from the distant past."""
    if not window_strokes or not prior_vocab:
        return 0.0
    hits = 0
    for text in window_strokes:
        stroke_words = set(extract_content_words(text))
        if stroke_words & prior_vocab:
            hits += 1
    return hits / len(window_strokes)


def _classify_regime(
    depth_slope: float,
    mean_drift: float,
    mean_callback: float,
    slope_threshold: float = 0.005,
    drift_threshold: float = 0.65,
    callback_threshold: float = 0.30,
) -> str:
    """Classify the evolution regime."""
    deepening_depth = depth_slope > slope_threshold
    high_drift = mean_drift >= drift_threshold
    high_callback = mean_callback >= callback_threshold

    if deepening_depth and not high_drift:
        return "deepening"
    if deepening_depth and high_drift and high_callback:
        return "spiraling"
    if deepening_depth and high_drift:
        # deepening but drifting — closer to spiraling without callbacks
        return "spiraling"
    if not deepening_depth and high_drift:
        return "wandering"
    return "stagnating"


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


def analyse_evolution(
    strokes: Sequence[str],
    window_size: int = 10,
) -> EvolutionReport:
    """Analyse the evolution of a stroke stream.

    Parameters
    ----------
    strokes : sequence of str
        Ordered stroke texts (oldest first).
    window_size : int
        Number of strokes per analysis window.

    Returns
    -------
    EvolutionReport
    """
    report = EvolutionReport(
        total_strokes=len(strokes),
        window_size=window_size,
    )

    if not strokes:
        return report

    # build windows
    windows: List[List[str]] = []
    for i in range(0, len(strokes), window_size):
        chunk = list(strokes[i : i + window_size])
        if chunk:
            windows.append(chunk)

    report.window_count = len(windows)

    # distant vocabulary tracker: words seen ≥ 2 windows ago
    distant_vocab: set = set()
    window_vocabs: List[set] = []

    depth_scores: List[float] = []
    drift_velocities: List[float] = []
    callback_densities: List[float] = []
    window_metrics: List[WindowMetrics] = []

    prev_words: Optional[List[str]] = []

    for idx, win in enumerate(windows):
        start_i = idx * window_size
        end_i = start_i + len(win)

        # current window vocabulary
        cur_words: list = []
        for text in win:
            cur_words.extend(extract_content_words(text))

        # depth
        depth, n_unique, mean_sent, cross_ref = compute_window_depth(win)
        depth_scores.append(depth)

        # drift (similarity to previous window)
        if prev_words is not None and idx > 0:
            sim = compute_topic_similarity(prev_words, cur_words)
            drift_velocities.append(1.0 - sim)
        elif idx == 0:
            # no previous window; drift undefined
            pass

        # callback density
        cb = compute_callback_density(win, distant_vocab)
        callback_densities.append(cb)

        # metrics record
        wm = WindowMetrics(
            window_index=idx,
            stroke_range=(start_i, end_i),
            depth_score=depth,
            unique_words=n_unique,
            mean_sentences=mean_sent,
            cross_ref_fraction=cross_ref,
            callback_density=cb,
        )
        window_metrics.append(wm)

        # update distant vocabulary: add words from 2 windows ago
        if idx >= 1:
            distant_vocab |= window_vocabs[idx - 1]
        window_vocabs.append(set(cur_words))

        prev_words = cur_words

    # aggregate
    report.depth_scores = depth_scores
    report.mean_depth = sum(depth_scores) / len(depth_scores) if depth_scores else 0.0
    report.depth_slope = _linear_slope(depth_scores)

    report.drift_velocities = drift_velocities
    report.mean_drift = (
        sum(drift_velocities) / len(drift_velocities)
        if drift_velocities
        else 0.0
    )

    report.callback_densities = callback_densities
    report.mean_callback_density = (
        sum(callback_densities) / len(callback_densities)
        if callback_densities
        else 0.0
    )

    report.regime = _classify_regime(
        report.depth_slope, report.mean_drift, report.mean_callback_density
    )
    report.windows = window_metrics

    return report


def analyse_evolution_windows(
    strokes: Sequence[str],
    window_size: int = 10,
) -> List[WindowMetrics]:
    """Convenience: return per-window metrics only."""
    return analyse_evolution(strokes, window_size).windows
