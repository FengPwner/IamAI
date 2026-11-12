#!/usr/bin/env python3
"""writer_pacing — measure whether text varies its density with intention.

Pacing is about *rhythm at the paragraph level*.  Well-paced writing
alternates between dense, complex passages and lighter, more accessible
ones.  The variation is deliberate: a complex argument is followed by a
concrete example; a data-heavy paragraph yields to a short anecdote; a
series of short punchy sentences gives way to a longer exploratory one.

Poorly-paced writing is either:

- **Monotonous**: every paragraph has the same density, the same
  complexity, the same tone.  The reader's attention drifts because
  there is no change to latch onto.

- **Erratic**: density swings wildly with no pattern.  A dense
  technical paragraph is followed by a one-sentence quip, then a
  three-hundred-word digression, then a bullet list.  The reader
  cannot build momentum because the ground keeps shifting.

This module is orthogonal to the other writer metrics:

- **prose_rhythm** tracks *sentence-length variation*.  Prose rhythm is
  about the micro-level alternation of long and short sentences within
  a paragraph.  Pacing is about the macro-level alternation of dense
  and light *segments* across the whole text.

- **readability** tracks *parse difficulty*.  A text can be readable
  (simple sentences, common words) while being monotonously paced
  (every paragraph is equally simple).  Readability is about access;
  pacing is about variation.

- **cohesion** tracks *sentence-to-sentence connection*.  A text can be
  cohesive (each sentence links to the last) while being poorly paced
  (the linked sentences are all at the same density).  Cohesion is
  about connection; pacing is about alternation.

- **concision** tracks *economy of words*.  A text can be concise
  (no wasted words) while being monotonous (every paragraph is
  equally compressed).  Concision is about efficiency; pacing is
  about rhythm.

- **signal_clarity** tracks *novelty across strokes*.  A text can have
  high signal clarity (every stroke is unique) while being erratically
  paced (the unique strokes swing between dense and thin).  Clarity is
  about uniqueness; pacing is about density distribution.

- **topic_drift** tracks *thematic focus*.  A text can stay on topic
  while being poorly paced (all facts at the same level of detail).
  Topic drift is about subject; pacing is about presentation rhythm.

Pacing asks: **does the text breathe, or does it drone?**

Four signals are tracked:

1. **Density variation coefficient** — the coefficient of variation
   (standard deviation / mean) of content-word density across text
   segments.  Content words are nouns, verbs (excluding auxiliaries),
   adjectives, and adverbs.  Segments are fixed-size windows of
   approximately 50 words.  A CV near 0 means every segment has the
   same density (monotonous).  A very high CV (>0.5) means density
   swings wildly (erratic).  The ideal is moderate variation (0.15–0.35).

2. **Complexity variation coefficient** — the coefficient of variation
   of average sentence length across segments.  Same windowing as
   density.  Measures whether some segments use short sentences while
   others use long ones, or whether every segment has the same average.

3. **Transition smoothness** — the average absolute difference in
   density between consecutive segments, normalized by the overall
   density standard deviation.  Low values mean density changes
   gradually (smooth transitions).  High values mean density jumps
   abruptly (jarring shifts).  The ideal is moderate smoothness:
   enough variation to be interesting, not so much as to be jarring.

4. **Engagement distribution** — the fraction of segments that contain
   at least one engagement marker: questions (sentences ending in '?'),
   examples ("for example", "for instance", "e.g.", "such as"),
   direct address ("you", "your"), lists (lines starting with '-' or
   '*' or numbered items), or dialogue markers (quoted speech).  A
   well-paced text distributes engagement markers across segments
   rather than clustering them.

The **pacing_index** is computed as a weighted composite:

    density_score    = 1 - abs(cv_density - 0.25) / 0.25     # centered at 0.25
    complexity_score = 1 - abs(cv_complexity - 0.30) / 0.30   # centered at 0.30
    smoothness_score = 1 - min(1.0, abs_transition_norm)       # lower jumps = better
    engagement_score = engagement_fraction                      # 0..1

    index = density_score    * 0.30
          + complexity_score * 0.25
          + smoothness_score * 0.25
          + engagement_score * 0.20

Each component is clamped to [0, 1] before weighting.

From the pacing_index, the text is classified:

==============  ============================================================
class           meaning
==============  ============================================================
riveting        index >= 0.75 — well-paced; deliberate rhythm of dense and
                light passages keeps the reader engaged; engagement markers
                are distributed throughout
engaging        0.60 <= index < 0.75 — mostly good pacing; some flat spots
                but the text generally breathes; the reader's attention is
                held for most of the text
uneven          0.45 <= index < 0.60 — noticeable pacing problems; some
                sections drone while others rush; the reader must effortfully
                adjust to inconsistent density
monotonous      0.30 <= index < 0.45 — very little variation; every
                paragraph feels the same; the reader's attention drifts
                because there is no change to latch onto
erratic         index < 0.30 — chaotic pacing; density swings wildly with
                no discernible pattern; the reader cannot build momentum
==============  ============================================================

Reference: advice on "pacing" in nonfiction writing (e.g., William Zinsser,
*On Writing Well*, ch. 10: "The lead and the ending"; Gary Provost,
*100 Ways to Improve Your Writing*, on sentence-length variation as a
proxy for reader engagement).  Applied to autonomous writing: a writer
that cannot vary its density produces output that is technically correct
but rhythmically dead — a wall of equally-dense text that the reader's
eye slides off.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Engagement markers: patterns that signal reader-engaging content.
ENGAGEMENT_PATTERNS: list[str] = [
    r"\?",                          # questions
    r"\bfor\s+example\b",           # examples
    r"\bfor\s+instance\b",
    r"\be\.g\.",
    r"\bsuch\s+as\b",
    r"\blike\s+this\b",
    r"\bconsider\b",                # direct engagement
    r"\bimagine\b",
    r"\bthink\s+about\b",
    r"\bnote\s+that\b",
    r"\bremember\b",
    r"\bhere'?s\b",                 # presentational
    r"\blook\b",
    r"\blisten\b",
    r"\bthe\s+key\s+is\b",
    r"\bthe\s+point\s+is\b",
    r"\bin\s+other\s+words\b",      # reframing
    r"\bput\s+simply\b",
    r"\bto\s+be\s+clear\b",
]

# Compile once.
_ENGAGEMENT_RE = re.compile(
    "|".join(ENGAGEMENT_PATTERNS), re.IGNORECASE
)

# List markers (lines that start a list item).
_LIST_RE = re.compile(r"^\s*[-*+]\s+|^\s*\d+[.)]\s+", re.MULTILINE)

# Direct address markers.
_DIRECT_ADDRESS_RE = re.compile(r"\byou\b|\byour\b|\byourself\b", re.IGNORECASE)

# Quote markers (dialogue or cited speech).
_QUOTE_RE = re.compile(r'["\u201c].{5,}?["\u201d]')

# Words considered "content" words (basic heuristic: alphabetic, > 2 chars,
# not in a stopword list).
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing", "will",
    "would", "could", "should", "may", "might", "must", "shall", "can",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "under", "over", "and", "but", "or", "nor", "not", "so",
    "yet", "both", "either", "neither", "each", "every", "all", "any",
    "few", "more", "most", "other", "some", "such", "no", "only", "own",
    "same", "than", "too", "very", "just", "because", "if", "when",
    "where", "how", "what", "which", "who", "whom", "this", "that",
    "these", "those", "am", "it", "its", "he", "she", "they", "them",
    "her", "his", "their", "my", "your", "we", "us", "our", "i", "me",
    "about", "up", "out", "then", "there", "here", "now", "also",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_words(text: str) -> list[str]:
    """Split text into lowercase words, stripping punctuation."""
    results: list[str] = []
    for w in text.split():
        cleaned = w.strip(".,;:!?\"()-").lower()
        # Allow internal apostrophes (e.g. "it's", "don't").
        cleaned = cleaned.strip("'")
        if cleaned and cleaned.replace("'", "").isalpha():
            results.append(cleaned)
    return results


def _is_content_word(word: str) -> bool:
    """Return True if word is a content word (not a stopword, len > 2)."""
    return len(word) > 2 and word not in _STOPWORDS


def _get_stroke_text(stroke: dict[str, Any] | str) -> str:
    """Extract text from a stroke (string or dict)."""
    if isinstance(stroke, str):
        return stroke
    if isinstance(stroke, dict):
        return stroke.get("text", "") or stroke.get("content", "") or ""
    return ""


def _segment_words(words: list[str], segment_size: int = 50) -> list[list[str]]:
    """Split word list into fixed-size segments (last may be shorter)."""
    if not words:
        return []
    return [
        words[i : i + segment_size]
        for i in range(0, len(words), segment_size)
    ]


def _segment_density(words: list[str]) -> float:
    """Compute content-word density for a word list (0..1)."""
    if not words:
        return 0.0
    content = sum(1 for w in words if _is_content_word(w))
    return content / len(words)


def _segment_avg_sentence_length(words: list[str], original_text: str) -> float:
    """Estimate average sentence length in words for a segment.

    Uses the original text for sentence splitting but falls back to
    word count / estimated sentences if needed.
    """
    # Count sentences by splitting on sentence-ending punctuation.
    sentences = re.split(r"[.!?]+", original_text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return float(len(words))
    total_words_in_sentences = sum(len(s.split()) for s in sentences)
    return total_words_in_sentences / len(sentences)


def _coefficient_of_variation(values: list[float]) -> float:
    """Compute coefficient of variation (std / mean).  Returns 0 if mean is 0."""
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(variance)
    return std / mean


def _has_engagement_marker(text: str) -> bool:
    """Return True if text contains at least one engagement marker."""
    if _ENGAGEMENT_RE.search(text):
        return True
    if _LIST_RE.search(text):
        return True
    if _DIRECT_ADDRESS_RE.search(text):
        return True
    if _QUOTE_RE.search(text):
        return True
    return False


# ---------------------------------------------------------------------------
# Per-segment analysis
# ---------------------------------------------------------------------------


def _analyze_segment(
    words: list[str],
    segment_text: str,
) -> dict[str, Any]:
    """Analyze a single text segment for pacing signals."""
    density = _segment_density(words)
    avg_sent_len = _segment_avg_sentence_length(words, segment_text)
    has_engagement = _has_engagement_marker(segment_text)

    return {
        "word_count": len(words),
        "density": density,
        "avg_sentence_length": avg_sent_len,
        "has_engagement": has_engagement,
    }


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def analyze_stroke_pacing(
    stroke: dict[str, Any] | str,
    segment_size: int = 50,
) -> dict[str, Any]:
    """Analyze pacing for a single stroke.

    Returns per-segment breakdown and aggregate signals.
    """
    text = _get_stroke_text(stroke)
    if not text or len(text.strip()) < 20:
        return {
            "segments": [],
            "density_cv": 0.0,
            "complexity_cv": 0.0,
            "transition_smoothness": 1.0,
            "engagement_fraction": 0.0,
            "pacing_index": 0.0,
            "pacing_class": "monotonous",
        }

    words = _split_words(text)
    if len(words) < segment_size:
        # Too short for multi-segment analysis — treat as single segment.
        seg = _analyze_segment(words, text)
        return {
            "segments": [seg],
            "density_cv": 0.0,
            "complexity_cv": 0.0,
            "transition_smoothness": 1.0,
            "engagement_fraction": 1.0 if seg["has_engagement"] else 0.0,
            "pacing_index": 0.5,  # neutral for single-segment
            "pacing_class": "uneven",
        }

    segments_words = _segment_words(words, segment_size)

    # Reconstruct approximate segment texts from original.
    # This is a heuristic: we split the original text by word boundaries.
    segment_texts: list[str] = []
    word_idx = 0
    for seg_words in segments_words:
        seg_len = len(seg_words)
        # Find approximate position in original text.
        remaining = text[word_idx:]
        # Advance word_idx by seg_len words.
        for _ in range(seg_len):
            m = re.search(r"\S+", text[word_idx:])
            if m:
                word_idx = word_idx + m.end()
        segment_texts.append(text[max(0, word_idx - 200) : word_idx + 200])

    # If segment reconstruction is imprecise, fall back to proportional slicing.
    if len(segment_texts) != len(segments_words):
        char_per_seg = len(text) // max(1, len(segments_words))
        segment_texts = [
            text[i * char_per_seg : (i + 1) * char_per_seg]
            for i in range(len(segments_words))
        ]

    segment_analyses: list[dict[str, Any]] = []
    for i, seg_words in enumerate(segments_words):
        seg_text = segment_texts[i] if i < len(segment_texts) else ""
        analysis = _analyze_segment(seg_words, seg_text)
        segment_analyses.append(analysis)

    # Compute aggregate signals.
    densities = [s["density"] for s in segment_analyses]
    complexities = [s["avg_sentence_length"] for s in segment_analyses]

    density_cv = _coefficient_of_variation(densities)
    complexity_cv = _coefficient_of_variation(complexities)

    # Transition smoothness: average absolute density delta between
    # consecutive segments, normalized by overall density std.
    if len(densities) >= 2:
        deltas = [
            abs(densities[i + 1] - densities[i])
            for i in range(len(densities) - 1)
        ]
        avg_delta = sum(deltas) / len(deltas)
        density_std = math.sqrt(
            sum((d - sum(densities) / len(densities)) ** 2 for d in densities)
            / len(densities)
        ) if len(densities) > 1 else 1.0
        if density_std > 0:
            transition_norm = avg_delta / density_std
        else:
            transition_norm = 0.0
    else:
        transition_norm = 0.0

    engagement_count = sum(1 for s in segment_analyses if s["has_engagement"])
    engagement_fraction = engagement_count / len(segment_analyses) if segment_analyses else 0.0

    # Compute pacing index.
    density_score = max(0.0, min(1.0, 1.0 - abs(density_cv - 0.25) / 0.25))
    complexity_score = max(0.0, min(1.0, 1.0 - abs(complexity_cv - 0.30) / 0.30))
    smoothness_score = max(0.0, min(1.0, 1.0 - transition_norm))
    engagement_score = max(0.0, min(1.0, engagement_fraction))

    pacing_index = (
        density_score * 0.30
        + complexity_score * 0.25
        + smoothness_score * 0.25
        + engagement_score * 0.20
    )

    pacing_class = _classify_pacing(pacing_index, density_cv, complexity_cv)

    return {
        "segments": segment_analyses,
        "density_cv": round(density_cv, 4),
        "complexity_cv": round(complexity_cv, 4),
        "transition_smoothness": round(1.0 - transition_norm, 4) if transition_norm <= 1.0 else 0.0,
        "engagement_fraction": round(engagement_fraction, 4),
        "pacing_index": round(pacing_index, 4),
        "pacing_class": pacing_class,
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify_pacing(
    index: float,
    density_cv: float = 0.0,
    complexity_cv: float = 0.0,
) -> str:
    """Classify pacing from the pacing_index and variation signals.

    When density_cv and complexity_cv are both very low (< 0.05), the
    text is classified as 'monotonous' regardless of index, because
    there is essentially no variation at all.
    """
    if density_cv < 0.05 and complexity_cv < 0.05:
        return "monotonous"
    if index >= 0.75:
        return "riveting"
    elif index >= 0.60:
        return "engaging"
    elif index >= 0.45:
        return "uneven"
    elif index >= 0.30:
        return "monotonous"
    else:
        return "erratic"


# ---------------------------------------------------------------------------
# Session-level metrics
# ---------------------------------------------------------------------------


def compute_pacing_metrics(
    strokes: list[dict[str, Any] | str],
    window_size: int = 50,
    segment_size: int = 50,
) -> dict[str, Any]:
    """Compute pacing metrics over a set of strokes.

    Parameters
    ----------
    strokes : list
        List of strokes (strings or dicts with 'text'/'content' key).
    window_size : int
        Number of recent strokes to analyze.
    segment_size : int
        Words per segment for within-stroke analysis.

    Returns
    -------
    dict
        Pacing metrics.
    """
    if not strokes:
        return _empty_metrics()

    # Use the most recent window_size strokes.
    recent = strokes[-window_size:]

    stroke_analyses: list[dict[str, Any]] = []
    for stroke in recent:
        analysis = analyze_stroke_pacing(stroke, segment_size)
        stroke_analyses.append(analysis)

    # Aggregate across strokes.
    density_cvs = [a["density_cv"] for a in stroke_analyses if a["segments"]]
    complexity_cvs = [a["complexity_cv"] for a in stroke_analyses if a["segments"]]
    smoothness_vals = [a["transition_smoothness"] for a in stroke_analyses if a["segments"]]
    engagement_vals = [a["engagement_fraction"] for a in stroke_analyses if a["segments"]]
    pacing_indices = [a["pacing_index"] for a in stroke_analyses if a["segments"]]

    avg_density_cv = sum(density_cvs) / len(density_cvs) if density_cvs else 0.0
    avg_complexity_cv = sum(complexity_cvs) / len(complexity_cvs) if complexity_cvs else 0.0
    avg_smoothness = sum(smoothness_vals) / len(smoothness_vals) if smoothness_vals else 0.0
    avg_engagement = sum(engagement_vals) / len(engagement_vals) if engagement_vals else 0.0

    # Session-level pacing index: average of per-stroke indices.
    if pacing_indices:
        pacing_index = sum(pacing_indices) / len(pacing_indices)
    else:
        pacing_index = 0.0

    pacing_class = _classify_pacing(pacing_index, avg_density_cv, avg_complexity_cv)

    # Class distribution.
    class_dist: dict[str, int] = {}
    for a in stroke_analyses:
        if a["segments"]:
            cc = a["pacing_class"]
            class_dist[cc] = class_dist.get(cc, 0) + 1

    return {
        "strokes_analyzed": len(stroke_analyses),
        "strokes_with_segments": len(density_cvs),
        "pacing_index": round(pacing_index, 4),
        "pacing_class": pacing_class,
        "avg_density_cv": round(avg_density_cv, 4),
        "avg_complexity_cv": round(avg_complexity_cv, 4),
        "avg_transition_smoothness": round(avg_smoothness, 4),
        "avg_engagement_fraction": round(avg_engagement, 4),
        "class_distribution": class_dist,
    }


def _empty_metrics() -> dict[str, Any]:
    """Return empty metrics structure."""
    return {
        "strokes_analyzed": 0,
        "strokes_with_segments": 0,
        "pacing_index": 0.0,
        "pacing_class": "monotonous",
        "avg_density_cv": 0.0,
        "avg_complexity_cv": 0.0,
        "avg_transition_smoothness": 0.0,
        "avg_engagement_fraction": 0.0,
        "class_distribution": {},
    }


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


def compute_pacing_trend(
    strokes: list[dict[str, Any] | str],
    window_size: int = 20,
    step: int = 10,
    segment_size: int = 50,
) -> list[dict[str, Any]]:
    """Compute pacing snapshots over time for trend analysis.

    Parameters
    ----------
    strokes : list
        Full stroke list.
    window_size : int
        Strokes per snapshot window.
    step : int
        Stride between windows.
    segment_size : int
        Words per segment for within-stroke analysis.

    Returns
    -------
    list[dict]
        List of snapshot dicts with pacing metrics.
    """
    if not strokes:
        return []

    snapshots: list[dict[str, Any]] = []
    for start in range(0, max(1, len(strokes) - window_size + 1), step):
        window = strokes[start : start + window_size]
        metrics = compute_pacing_metrics(window, window_size, segment_size)
        metrics["window_start"] = start
        snapshots.append(metrics)
    return snapshots


def classify_trend(snapshots: list[dict[str, Any]]) -> str:
    """Classify the pacing trend from snapshots.

    Returns one of: improving, stable, degrading, insufficient_data.
    """
    if len(snapshots) < 2:
        return "insufficient_data"

    scores = [s.get("pacing_index", 0.0) for s in snapshots]
    first_half = scores[: len(scores) // 2]
    second_half = scores[len(scores) // 2 :]

    avg_first = sum(first_half) / len(first_half) if first_half else 0.0
    avg_second = sum(second_half) / len(second_half) if second_half else 0.0

    delta = avg_second - avg_first

    if delta > 0.05:
        return "improving"
    elif delta < -0.05:
        return "degrading"
    else:
        return "stable"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_pacing_report(metrics: dict[str, Any]) -> str:
    """Format pacing metrics as a human-readable report."""
    lines = [
        "=== Writer Pacing ===",
        f"Strokes analyzed:        {metrics['strokes_analyzed']}",
        f"Strokes with segments:   {metrics['strokes_with_segments']}",
        f"Pacing index:            {metrics['pacing_index']:.4f} ({metrics['pacing_class']})",
        "",
        f"Avg density CV:          {metrics['avg_density_cv']:.4f}",
        f"Avg complexity CV:       {metrics['avg_complexity_cv']:.4f}",
        f"Avg transition smooth:   {metrics['avg_transition_smoothness']:.4f}",
        f"Avg engagement fraction: {metrics['avg_engagement_fraction']:.4f}",
        "",
    ]

    dist = metrics.get("class_distribution", {})
    if dist:
        lines.append("Class distribution:")
        for cls in ("riveting", "engaging", "uneven", "monotonous", "erratic"):
            count = dist.get(cls, 0)
            if count:
                lines.append(f"  {cls:14s} {count}")
        lines.append("")

    cc = metrics["pacing_class"]
    lines.append("Interpretation:")
    if cc == "riveting":
        lines.append("  Well-paced writing. Deliberate rhythm of dense and light")
        lines.append("  passages keeps the reader engaged throughout.")
    elif cc == "engaging":
        lines.append("  Mostly good pacing. Some flat spots, but the text")
        lines.append("  generally breathes and holds attention.")
    elif cc == "uneven":
        lines.append("  Noticeable pacing inconsistency. Some sections drone")
        lines.append("  while others rush; the reader adjusts effortfully.")
    elif cc == "monotonous":
        lines.append("  Very little density variation. Every paragraph feels")
        lines.append("  the same; the reader's attention drifts.")
    else:
        lines.append("  Chaotic pacing. Density swings wildly with no")
        lines.append("  discernible pattern; the reader cannot build momentum.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone analysis (reads from strokes.jsonl)
# ---------------------------------------------------------------------------


def analyze_pacing(
    strokes_path: str = "data/strokes.jsonl",
    window_size: int = 50,
    segment_size: int = 50,
) -> dict[str, Any]:
    """Analyze pacing from the strokes file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.
    segment_size : int
        Words per segment for within-stroke analysis.

    Returns
    -------
    dict
        Pacing metrics.
    """
    path = Path(strokes_path)
    if not path.exists():
        return _empty_metrics()

    strokes: list[dict[str, Any]] = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    strokes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return compute_pacing_metrics(strokes, window_size, segment_size)


if __name__ == "__main__":
    metrics = analyze_pacing()
    print(format_pacing_report(metrics))
