"""stroke_readability_tracker — track how readable the stroke stream is over time.

While ``stroke_evolution_tracker`` measures intellectual depth and
``stroke_vocabulary_growth`` models vocabulary expansion via Heap's Law,
neither answers a practical question: *is the writing getting harder to
read?*

A self-writing repo should produce strokes that remain **accessible**
to a general audience.  If sentence length keeps growing, vocabulary
gets increasingly arcane, and every paragraph is padded with filler,
the stream is drifting toward **impenetrable** prose.  Conversely, if
every stroke is a terse fragment with no substance, the stream is
**shallow** — technically easy to read but offering nothing to chew on.

This module quantifies four dimensions of readability:

1. **Sentence length** — mean sentence length in words.  Shorter
   sentences are easier to parse.  Track mean, median, and max.
2. **Word complexity** — average word length in characters and the
   fraction of "long" words (> 8 characters).  Longer words tend to
   be less common and harder to process.
3. **Filler ratio** — fraction of tokens that are filler/hedge words
   (e.g. "basically", "essentially", "actually", "just", "really").
   High filler density pads text without adding information.
4. **Readability regime** — classify the overall stream as:

================  =========================================================
regime            description
================  =========================================================
**accessible**    short sentences, common words, low filler
**balanced**      moderate complexity with some depth
**dense**         long sentences and complex vocabulary
**impenetrable**  extreme complexity on all dimensions
================  =========================================================

Algorithm
---------
For each stroke *s*:

    sentences(s) = split on sentence-ending punctuation (.!?)
    words(s)     = tokenise each sentence, filter empty tokens

    mean_sent_len(s) = mean(len(sent) for sent in sentences(s))
    mean_word_len(s) = mean(len(w) for w in words(s))
    long_word_frac(s) = |{w : len(w) > 8}| / |words(s)|
    filler_ratio(s)  = |{w : w in FILLERS}| / |words(s)|

Composite readability score (0–100, higher = more readable):

    raw = 100
         - (mean_sent_len - 10) * 2.0     # penalty for long sentences
         - (mean_word_len - 4.0) * 10.0   # penalty for long words
         - long_word_frac * 30.0          # penalty for complex vocabulary
         - filler_ratio * 40.0            # penalty for filler

    score = clamp(raw, 0, 100)

Regime thresholds:

    accessible   = score >= 70
    balanced     = score >= 40
    dense        = score >= 20
    impenetrable = score <  20

Edge cases
----------
* Empty input → zeroed report.
* Single-word strokes → score based on word length alone.
* All filler words → score heavily penalised.

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 731, 2026-11-19.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Filler / hedge words
# ---------------------------------------------------------------------------

_FILLERS = {
    "actually", "basically", "certainly", "clearly", "definitely",
    "essentially", "frankly", "generally", "honestly", "indeed",
    "just", "literally", "maybe", "merely", "naturally", "obviously",
    "perhaps", "practically", "presumably", "quite", "rather", "really",
    "seemingly", "seriously", "simply", "slightly", "somewhat",
    "sort", "totally", "truly", "utterly", "virtually",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StrokeReadability:
    """Readability metrics for a single stroke."""

    text: str
    mean_sentence_length: float  # words per sentence
    mean_word_length: float      # characters per word
    long_word_fraction: float    # fraction of words > 8 chars
    filler_ratio: float          # fraction of filler tokens
    readability_score: float     # 0–100
    regime: str                  # accessible / balanced / dense / impenetrable
    sentence_count: int = 0
    word_count: int = 0


@dataclass
class ReadabilityReport:
    """Aggregate readability report for the entire stroke stream."""

    total_strokes: int
    mean_score: float
    regime: str
    regime_counts: Dict[str, int] = field(default_factory=dict)
    mean_sentence_length: float = 0.0
    mean_word_length: float = 0.0
    mean_long_word_fraction: float = 0.0
    mean_filler_ratio: float = 0.0
    trend: str = "unknown"  # improving / stable / declining


@dataclass
class WindowReadability:
    """Readability metrics for a sliding window."""

    start: int
    end: int
    mean_score: float
    regime: str
    mean_sentence_length: float
    filler_ratio: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def split_sentences(text: str) -> List[str]:
    """Split *text* into sentences on sentence-ending punctuation.

    Handles abbreviations poorly but well enough for stroke content.
    Returns at least one element for non-empty input.
    """
    if not text or not text.strip():
        return []

    # Split on sentence-ending punctuation followed by whitespace or EOF
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def tokenise(sentence: str) -> List[str]:
    """Tokenise a sentence into lowercase alphabetic words."""
    return [w.lower() for w in re.findall(r"[a-z]+", sentence.lower()) if w]


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _classify(score: float) -> str:
    if score >= 70:
        return "accessible"
    if score >= 40:
        return "balanced"
    if score >= 20:
        return "dense"
    return "impenetrable"


def compute_readability_score(
    mean_sent_len: float,
    mean_word_len: float,
    long_word_frac: float,
    filler_ratio: float,
) -> float:
    """Compute composite readability score (0–100, higher = more readable)."""
    raw = 100.0
    # Penalise long sentences (baseline 10 words/sentence)
    raw -= max(0.0, mean_sent_len - 10.0) * 2.0
    # Penalise long words (baseline 4 chars/word)
    raw -= max(0.0, mean_word_len - 4.0) * 10.0
    # Penalise complex vocabulary
    raw -= long_word_frac * 30.0
    # Penalise filler words
    raw -= filler_ratio * 40.0
    return round(_clamp(raw), 2)


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyse_stroke(text: str) -> StrokeReadability:
    """Analyse readability of a single stroke."""
    sentences = split_sentences(text)
    if not sentences:
        return StrokeReadability(
            text=text,
            mean_sentence_length=0.0,
            mean_word_length=0.0,
            long_word_fraction=0.0,
            filler_ratio=0.0,
            readability_score=100.0,
            regime="accessible",
            sentence_count=0,
            word_count=0,
        )

    all_words: List[str] = []
    sent_lengths: List[int] = []

    for sent in sentences:
        words = tokenise(sent)
        sent_lengths.append(len(words))
        all_words.extend(words)

    if not all_words:
        return StrokeReadability(
            text=text,
            mean_sentence_length=0.0,
            mean_word_length=0.0,
            long_word_fraction=0.0,
            filler_ratio=0.0,
            readability_score=100.0,
            regime="accessible",
            sentence_count=len(sentences),
            word_count=0,
        )

    mean_sent = statistics.mean(sent_lengths) if sent_lengths else 0.0
    mean_word = statistics.mean(len(w) for w in all_words)
    long_frac = sum(1 for w in all_words if len(w) > 8) / len(all_words)
    filler_count = sum(1 for w in all_words if w in _FILLERS)
    filler_rat = filler_count / len(all_words)

    score = compute_readability_score(mean_sent, mean_word, long_frac, filler_rat)

    return StrokeReadability(
        text=text,
        mean_sentence_length=round(mean_sent, 2),
        mean_word_length=round(mean_word, 2),
        long_word_fraction=round(long_frac, 4),
        filler_ratio=round(filler_rat, 4),
        readability_score=score,
        regime=_classify(score),
        sentence_count=len(sentences),
        word_count=len(all_words),
    )


# ---------------------------------------------------------------------------
# Stream-level analysis
# ---------------------------------------------------------------------------


def analyse_stream(texts: Sequence[str]) -> ReadabilityReport:
    """Analyse readability across an entire stroke stream.

    Returns aggregate metrics and an overall trend classification.
    """
    if not texts:
        return ReadabilityReport(
            total_strokes=0,
            mean_score=0.0,
            regime="unknown",
            regime_counts={},
            trend="unknown",
        )

    strokes = [analyse_stroke(t) for t in texts]
    scores = [s.readability_score for s in strokes]

    regime_counts: Dict[str, int] = {}
    for s in strokes:
        regime_counts[s.regime] = regime_counts.get(s.regime, 0) + 1

    overall_regime = _classify(statistics.mean(scores))

    # Trend: compare first half vs second half
    trend = "stable"
    if len(scores) >= 4:
        mid = len(scores) // 2
        first_half = statistics.mean(scores[:mid])
        second_half = statistics.mean(scores[mid:])
        diff = second_half - first_half
        if diff > 5.0:
            trend = "improving"
        elif diff < -5.0:
            trend = "declining"

    return ReadabilityReport(
        total_strokes=len(texts),
        mean_score=round(statistics.mean(scores), 2),
        regime=overall_regime,
        regime_counts=regime_counts,
        mean_sentence_length=round(
            statistics.mean(s.mean_sentence_length for s in strokes), 2
        ),
        mean_word_length=round(
            statistics.mean(s.mean_word_length for s in strokes), 2
        ),
        mean_long_word_fraction=round(
            statistics.mean(s.long_word_fraction for s in strokes), 4
        ),
        mean_filler_ratio=round(
            statistics.mean(s.filler_ratio for s in strokes), 4
        ),
        trend=trend,
    )


# ---------------------------------------------------------------------------
# Sliding-window analysis
# ---------------------------------------------------------------------------


def analyse_readability_windows(
    texts: Sequence[str],
    window_size: int = 20,
    step: int = 10,
) -> List[WindowReadability]:
    """Analyse readability in sliding windows over the stroke stream.

    Each window reports its own mean score and regime, showing how
    readability evolves over time.
    """
    if not texts:
        return []

    results: List[WindowReadability] = []

    for start in range(0, len(texts), step):
        end = min(start + window_size, len(texts))
        if start >= len(texts):
            break

        window_texts = texts[start:end]
        window_strokes = [analyse_stroke(t) for t in window_texts]
        window_scores = [s.readability_score for s in window_strokes]
        window_sent_lens = [s.mean_sentence_length for s in window_strokes]
        window_fillers = [s.filler_ratio for s in window_strokes]

        mean_score = statistics.mean(window_scores) if window_scores else 0.0
        mean_sent = statistics.mean(window_sent_lens) if window_sent_lens else 0.0
        mean_filler = statistics.mean(window_fillers) if window_fillers else 0.0

        results.append(WindowReadability(
            start=start,
            end=end,
            mean_score=round(mean_score, 2),
            regime=_classify(mean_score),
            mean_sentence_length=round(mean_sent, 2),
            filler_ratio=round(mean_filler, 4),
        ))

    return results
