#!/usr/bin/env python3
"""writer_prose_rhythm — measure sentence-level pacing and variation
in a writing session.

Prose rhythm is the *texture* of writing: the alternation of long and
short sentences, the acceleration or deceleration within a paragraph,
and the overall variation in sentence length.  Good rhythm keeps readers
engaged; poor rhythm makes even correct prose feel flat or exhausting.

This module is orthogonal to the other writer metrics:

- **coherence** tracks whether consecutive ideas *connect logically*.
  A text can be perfectly coherent (one sustained argument) while having
  poor rhythm (every sentence is the same length).

- **grounding_density** tracks whether abstract claims are *anchored with
  concrete evidence*.  A text can be well-grounded while being rhythmically
  monotone.

- **vocabulary_richness** tracks *word-level diversity*.  A text can use
  rich vocabulary while maintaining identical sentence lengths.

- **signal_clarity** tracks whether strokes are *substantively different*
  from their neighbours.  Clarity is about content uniqueness; rhythm is
  about structural variation.

Prose rhythm asks specifically: **does the writing vary its sentence
lengths in a way that creates engagement rather than monotony?**

Three signals are tracked:

1. **Sentence length variation** — the coefficient of variation (CV)
   of sentence lengths across a stroke or session.  High CV means the
   writer mixes long and short sentences; low CV means sentences are
   uniform.  Natural prose typically has CV between 0.4 and 0.8.

2. **Alternation index** — the degree to which consecutive sentences
   alternate between longer and shorter.  Measured as the fraction of
   adjacent pairs where one sentence is above median length and the
   next is below (or vice versa).  Good alternation prevents the
   "drone" effect of uniformly-sized sentences.

3. **Paragraph momentum** — the trend of sentence lengths within each
   paragraph.  An accelerating paragraph (sentences getting shorter)
   creates urgency; a decelerating one (sentences getting longer)
   creates contemplation; a steady one is neutral.  Momentum is
   classified per paragraph and then aggregated.

From these signals a session-level **rhythm_index** is computed and
classified:

==============  ============================================================
class           meaning
==============  ============================================================
varied          rhythm_index >= 0.65 — strong variation in sentence length
                with good alternation; the prose has a natural, engaging
                cadence that keeps readers attentive
measured        0.45 <= rhythm_index < 0.65 — moderate variation; the
                writer has a recognizable style but occasionally falls
                into uniform patterns; typical of technical writing
monotone        0.25 <= rhythm_index < 0.45 — weak variation; sentences
                tend toward uniform length with little alternation; the
                prose reads as flat or mechanical
erratic         rhythm_index < 0.25 — no discernible rhythm pattern;
                sentence lengths appear random rather than purposefully
                varied; may indicate fragmented or rushed writing
==============  ============================================================

The module also computes a **tempo** metric: the median sentence length
in words.  Tempo classifies the writing style:

- **staccato**: tempo < 8 words/sentence — short, punchy, fragmented
- **conversational**: 8 <= tempo < 18 — natural, readable
- **measured**: 18 <= tempo < 30 — deliberate, academic
- **labyrinthine**: tempo >= 30 — complex, potentially unwieldy

Session arc analysis
--------------------
The session is divided into quartiles and the rhythm index is computed
for each.  A healthy session shows a characteristic "warm-up" curve:
slightly erratic rhythm in Q1 (the writer is finding their voice),
improving rhythm in Q2-Q3 (the prose settles into a natural flow), and
slightly degraded rhythm in Q4 (fatigue or rushing toward completion).

API
---
>>> from iamai.writer_prose_rhythm import compute_rhythm_metrics
>>> result = compute_rhythm_metrics(strokes)
>>> result["rhythm_index"]
0.58
>>> result["rhythm_class"]
'measured'
>>> result["tempo"]
14.5
>>> result["tempo_class"]
'conversational'
"""

from __future__ import annotations

import math
import re
from statistics import mean, median, stdev
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Tokenization helpers
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(
    r'(?<=[.!?])\s+(?=[A-Z"\'])|(?<=\n)\s*',
)

_WORD_RE = re.compile(r"\b[\w'-]+\b")


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using punctuation boundaries."""
    if not text or not text.strip():
        return []
    # Split on sentence-ending punctuation followed by space and uppercase
    raw = _SENTENCE_RE.split(text.strip())
    sentences = [s.strip() for s in raw if s.strip()]
    # If no split occurred, treat the whole text as one sentence if non-empty
    if not sentences and text.strip():
        sentences = [text.strip()]
    return sentences


def _word_count(text: str) -> int:
    """Count words in a text fragment."""
    return len(_WORD_RE.findall(text))


def _sentence_lengths(text: str) -> List[int]:
    """Return list of word counts per sentence."""
    sentences = _split_sentences(text)
    return [_word_count(s) for s in sentences if _word_count(s) > 0]


def _get_stroke_text(stroke: Any) -> str:
    """Extract text content from a stroke (dict or object)."""
    if isinstance(stroke, dict):
        return stroke.get("text", "") or stroke.get("content", "")
    return getattr(stroke, "text", "") or getattr(stroke, "content", "")


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------


def compute_sentence_length_cv(lengths: Sequence[int]) -> float:
    """Compute coefficient of variation of sentence lengths.

    Returns a float in [0, inf). Natural prose typically has CV 0.4–0.8.
    Returns 0.0 if fewer than 2 sentences or all identical length.
    """
    if len(lengths) < 2:
        return 0.0
    m = mean(lengths)
    if m == 0:
        return 0.0
    s = stdev(lengths)
    return s / m


def compute_alternation_index(lengths: Sequence[int]) -> float:
    """Compute the fraction of adjacent pairs that cross the median.

    An alternating pair is one where one sentence is above median and
    the next is below (or equal to) median, or vice versa.

    Returns a float in [0, 1]. Returns 0.5 for random text.
    """
    if len(lengths) < 2:
        return 0.0
    med = median(lengths)
    crossings = 0
    for i in range(len(lengths) - 1):
        above_a = lengths[i] > med
        above_b = lengths[i + 1] > med
        if above_a != above_b:
            crossings += 1
    return crossings / (len(lengths) - 1)


def classify_paragraph_momentum(lengths: Sequence[int]) -> str:
    """Classify the trend of sentence lengths in a paragraph.

    Returns one of: 'accelerating', 'decelerating', 'steady', 'irregular'.
    """
    if len(lengths) < 3:
        return "steady"
    # Simple linear regression on sentence lengths
    n = len(lengths)
    x_mean = (n - 1) / 2.0
    y_mean = mean(lengths)
    numerator = sum((i - x_mean) * (lengths[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return "steady"
    slope = numerator / denominator
    # Normalize slope by mean to get relative trend
    if y_mean == 0:
        return "steady"
    relative_slope = slope / y_mean

    # If the slope is negligible, the paragraph is steady regardless of R²
    if abs(relative_slope) <= 0.1:
        return "steady"

    # Also check linearity (R² approximation) for non-trivial slopes
    predicted = [y_mean + slope * (i - x_mean) for i in range(n)]
    ss_res = sum((lengths[i] - predicted[i]) ** 2 for i in range(n))
    ss_tot = sum((lengths[i] - y_mean) ** 2 for i in range(n))
    if ss_tot == 0:
        r_squared = 1.0
    else:
        r_squared = 1.0 - (ss_res / ss_tot)

    if r_squared < 0.3:
        return "irregular"
    if relative_slope > 0.1:
        return "accelerating"
    if relative_slope < -0.1:
        return "decelerating"
    return "steady"


def compute_rhythm_index(
    cv: float,
    alternation: float,
    momentum_distribution: Optional[Dict[str, float]] = None,
) -> float:
    """Compute the composite rhythm index from sub-signals.

    Components:
    - cv_score: mapped from CV (0.4-0.8 is ideal → score 1.0)
    - alternation_score: alternation index directly (higher is better)
    - momentum_score: fraction of non-steady paragraphs (variety is good)

    Returns a float in [0, 1].
    """
    # CV scoring: bell curve centered at 0.6
    if cv <= 0:
        cv_score = 0.0
    elif cv <= 0.6:
        cv_score = cv / 0.6
    elif cv <= 1.2:
        cv_score = max(0, 1.0 - (cv - 0.6) / 0.6)
    else:
        cv_score = 0.0

    # Alternation scoring: direct use, capped at 1.0
    alt_score = min(1.0, alternation / 0.6)

    # Momentum scoring: variety in paragraph trends is good
    if momentum_distribution:
        total = sum(momentum_distribution.values())
        if total > 0:
            # Fraction of paragraphs with non-steady momentum
            steady_frac = momentum_distribution.get("steady", 0) / total
            momentum_score = 1.0 - steady_frac
        else:
            momentum_score = 0.5
    else:
        momentum_score = 0.5

    # Weighted composite
    index = 0.40 * cv_score + 0.35 * alt_score + 0.25 * momentum_score
    return round(index, 4)


def _classify_rhythm(index: float) -> str:
    """Classify rhythm index into a category."""
    if index >= 0.65:
        return "varied"
    if index >= 0.45:
        return "measured"
    if index >= 0.25:
        return "monotone"
    return "erratic"


def _classify_tempo(median_words: float) -> str:
    """Classify median sentence length into a tempo category."""
    if median_words < 8:
        return "staccato"
    if median_words < 18:
        return "conversational"
    if median_words < 30:
        return "measured"
    return "labyrinthine"


# ---------------------------------------------------------------------------
# Session-level analysis
# ---------------------------------------------------------------------------


def compute_quartile_rhythm(
    all_lengths: List[List[int]],
) -> Dict[str, float]:
    """Compute rhythm index for each session quartile.

    Args:
        all_lengths: list of per-stroke sentence length lists.

    Returns:
        Dict with keys 'q1', 'q2', 'q3', 'q4' mapping to rhythm index.
    """
    n = len(all_lengths)
    if n == 0:
        return {"q1": 0.0, "q2": 0.0, "q3": 0.0, "q4": 0.0}

    q_size = max(1, n // 4)
    quartiles = {}
    for qi, label in enumerate(["q1", "q2", "q3", "q4"]):
        start = qi * q_size
        end = start + q_size if qi < 3 else n
        chunk = all_lengths[start:end]
        flat = [w for lengths in chunk for w in lengths]
        if len(flat) < 2:
            quartiles[label] = 0.0
            continue
        cv = compute_sentence_length_cv(flat)
        alt = compute_alternation_index(flat)
        quartiles[label] = compute_rhythm_index(cv, alt)
    return quartiles


def classify_rhythm_trend(quartiles: Dict[str, float]) -> str:
    """Classify how rhythm evolves across the session.

    Returns one of: 'improving', 'degrading', 'stable', 'arc', 'inverted_arc'.
    """
    values = [quartiles["q1"], quartiles["q2"], quartiles["q3"], quartiles["q4"]]
    if len(set(round(v, 2) for v in values)) <= 1:
        return "stable"

    # Check for arc pattern (rise then fall)
    if values[1] > values[0] and values[2] > values[1] and values[3] < values[2]:
        return "arc"
    # Check for inverted arc (fall then rise)
    if values[1] < values[0] and values[2] < values[1] and values[3] > values[2]:
        return "inverted_arc"

    # Simple trend
    if values[-1] > values[0] + 0.05:
        return "improving"
    if values[-1] < values[0] - 0.05:
        return "degrading"
    return "stable"


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyze_stroke_rhythm(stroke: Any) -> Dict[str, Any]:
    """Analyze rhythm for a single stroke.

    Returns dict with:
    - sentence_count: number of sentences
    - median_length: median sentence length in words
    - cv: coefficient of variation
    - alternation: alternation index
    - momentum: paragraph momentum classification
    """
    text = _get_stroke_text(stroke)
    lengths = _sentence_lengths(text)
    if not lengths:
        return {
            "sentence_count": 0,
            "median_length": 0,
            "cv": 0.0,
            "alternation": 0.0,
            "momentum": "steady",
        }
    return {
        "sentence_count": len(lengths),
        "median_length": median(lengths),
        "cv": round(compute_sentence_length_cv(lengths), 4),
        "alternation": round(compute_alternation_index(lengths), 4),
        "momentum": classify_paragraph_momentum(lengths),
    }


# ---------------------------------------------------------------------------
# Session-level aggregation
# ---------------------------------------------------------------------------


def compute_rhythm_metrics(strokes: Sequence[Any]) -> Dict[str, Any]:
    """Compute comprehensive rhythm metrics for a writing session.

    Args:
        strokes: sequence of stroke objects (dicts with 'text' key).

    Returns:
        Dict with:
        - rhythm_index: composite rhythm score [0, 1]
        - rhythm_class: 'varied' | 'measured' | 'monotone' | 'erratic'
        - tempo: median sentence length in words
        - tempo_class: 'staccato' | 'conversational' | 'measured' | 'labyrinthine'
        - sentence_length_cv: coefficient of variation
        - alternation_index: alternation score
        - stroke_count: number of strokes analyzed
        - total_sentences: total sentence count
        - quartile_rhythm: per-quartile rhythm indices
        - rhythm_trend: how rhythm evolves
        - momentum_distribution: distribution of paragraph momenta
    """
    if not strokes:
        return {
            "rhythm_index": 0.0,
            "rhythm_class": "erratic",
            "tempo": 0.0,
            "tempo_class": "staccato",
            "sentence_length_cv": 0.0,
            "alternation_index": 0.0,
            "stroke_count": 0,
            "total_sentences": 0,
            "quartile_rhythm": {"q1": 0.0, "q2": 0.0, "q3": 0.0, "q4": 0.0},
            "rhythm_trend": "stable",
            "momentum_distribution": {},
        }

    all_lengths: List[List[int]] = []
    momentum_counts: Dict[str, int] = {}
    total_sentences = 0

    for stroke in strokes:
        text = _get_stroke_text(stroke)
        lengths = _sentence_lengths(text)
        if lengths:
            all_lengths.append(lengths)
            total_sentences += len(lengths)
            mom = classify_paragraph_momentum(lengths)
            momentum_counts[mom] = momentum_counts.get(mom, 0) + 1

    # Flatten all lengths for session-level metrics
    flat_lengths = [w for lengths in all_lengths for w in lengths]

    if not flat_lengths:
        return {
            "rhythm_index": 0.0,
            "rhythm_class": "erratic",
            "tempo": 0.0,
            "tempo_class": "staccato",
            "sentence_length_cv": 0.0,
            "alternation_index": 0.0,
            "stroke_count": len(strokes),
            "total_sentences": 0,
            "quartile_rhythm": {"q1": 0.0, "q2": 0.0, "q3": 0.0, "q4": 0.0},
            "rhythm_trend": "stable",
            "momentum_distribution": {},
        }

    cv = compute_sentence_length_cv(flat_lengths)
    alt = compute_alternation_index(flat_lengths)

    # Momentum distribution as fractions
    total_strokes_with_text = sum(momentum_counts.values())
    momentum_dist = {}
    if total_strokes_with_text > 0:
        for k, v in momentum_counts.items():
            momentum_dist[k] = round(v / total_strokes_with_text, 4)

    rhythm_idx = compute_rhythm_index(cv, alt, momentum_dist)
    tempo_val = float(median(flat_lengths))

    quartiles = compute_quartile_rhythm(all_lengths)
    trend = classify_rhythm_trend(quartiles)

    return {
        "rhythm_index": rhythm_idx,
        "rhythm_class": _classify_rhythm(rhythm_idx),
        "tempo": round(tempo_val, 1),
        "tempo_class": _classify_tempo(tempo_val),
        "sentence_length_cv": round(cv, 4),
        "alternation_index": round(alt, 4),
        "stroke_count": len(strokes),
        "total_sentences": total_sentences,
        "quartile_rhythm": {k: round(v, 4) for k, v in quartiles.items()},
        "rhythm_trend": trend,
        "momentum_distribution": momentum_dist,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_rhythm_report(metrics: Dict[str, Any]) -> str:
    """Format rhythm metrics into a human-readable report."""
    lines = [
        f"Prose Rhythm Report",
        f"  rhythm_index:    {metrics['rhythm_index']:.4f}  ({metrics['rhythm_class']})",
        f"  tempo:           {metrics['tempo']:.1f} words/sentence  ({metrics['tempo_class']})",
        f"  sentence_cv:     {metrics['sentence_length_cv']:.4f}",
        f"  alternation:     {metrics['alternation_index']:.4f}",
        f"  strokes:         {metrics['stroke_count']}",
        f"  sentences:       {metrics['total_sentences']}",
        f"  trend:           {metrics['rhythm_trend']}",
        f"  quartiles:       Q1={metrics['quartile_rhythm']['q1']:.3f}  "
        f"Q2={metrics['quartile_rhythm']['q2']:.3f}  "
        f"Q3={metrics['quartile_rhythm']['q3']:.3f}  "
        f"Q4={metrics['quartile_rhythm']['q4']:.3f}",
    ]
    if metrics.get("momentum_distribution"):
        lines.append("  momentum:")
        for k, v in sorted(metrics["momentum_distribution"].items()):
            lines.append(f"    {k:15s} {v:.2%}")
    return "\n".join(lines)
