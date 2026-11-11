#!/usr/bin/env python3
"""writer_novelty_decay — measure how the rate of genuinely new content
changes over a sustained writing session.

In any writing session the easiest ideas arrive first.  As the session
deepens the writer must dig further for novelty.  This module tracks
whether a writer's novelty is declining (exhaustion), holding steady
(sustainable pace), or *increasing* (the writer is warming up, finding
stride, or entering flow).

Novelty decay is orthogonal to signal clarity.  Clarity asks whether a
stroke is different from its *immediate neighbours*; decay asks whether
novelty is trending up or down across the *entire session arc*.  A
writer can have high clarity (each stroke differs from the last) but
steep decay (the overall idea-space is narrowing).  Conversely, a
writer can have low clarity (some repetition) but zero decay (the
non-repetitive strokes keep introducing genuinely new territory).

Three signals are tracked:

1. **Vocabulary novelty** — for each stroke, what fraction of its words
   have *never* appeared in any prior stroke in the session?  Early
   strokes score high (everything is new); later strokes score lower
   as the vocabulary pool saturates.  The *rate* at which this drops
   reveals whether the writer is exhausting their lexicon.

2. **Concept novelty** — same idea but at the bigram level.  A bigram
   (consecutive word pair) captures a micro-concept.  If a stroke uses
   bigrams the session has already produced, it is revisiting old
   conceptual ground.  New bigrams signal genuinely new ideas.

3. **Structural novelty** — has the stroke's structural template
   (numbers, paths, and hashes replaced with placeholders) been seen
   before in this session?  Reusing a template is not inherently bad,
   but a session where *every* stroke reuses a template is one that
   has stopped exploring form.

From these signals a composite **novelty_index** is computed and its
trajectory classified:

==============  ============================================================
class           meaning
==============  ============================================================
blooming        novelty_index trend >= +0.03 — the writer is accelerating;
                later strokes are *more* novel than earlier ones; this is
                the signature of a writer entering flow state
steady          -0.03 < trend < +0.03 — novelty is neither accelerating
                nor decaying; the writer is maintaining a sustainable pace
                with a roughly constant drip of new material
plateauing      -0.08 < trend <= -0.03 — moderate decay; the writer is
                running low on fresh ideas but still producing some new
                content; a normal phase in long sessions
exhausted       trend <= -0.08 — sharp decay; the writer has largely
                exhausted its idea-space for this session; new strokes
                are increasingly likely to revisit old ground; consider
                pausing or switching topics
==============  ============================================================

Dimensions
----------

========================  ================================================
metric                    meaning
========================  ================================================
vocabulary_novelty        mean fraction of per-stroke words not seen in
                          any prior stroke; higher = richer vocabulary
                          over the session
concept_novelty           mean fraction of per-stroke bigrams not seen
                          in any prior stroke; higher = more new
                          micro-concepts over the session
structural_novelty        fraction of strokes whose structural template
                          has not appeared earlier in the session;
                          higher = more varied output form
novelty_index             composite score: weighted combination of the
                          three signals (vocabulary 35%, concept 35%,
                          structural 30%)
novelty_trend             linear-regression slope of per-stroke novelty
                          index over the session; positive = blooming,
                          near-zero = steady, negative = decay
decay_class               blooming | steady | plateauing | exhausted
========================  ================================================
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase word-level tokenization preserving order."""
    return re.findall(r"\w+", text.lower())


def _bigrams(tokens: list[str]) -> list[tuple[str, str]]:
    """Generate consecutive word pairs from a token list."""
    return [(tokens[i], tokens[i + 1]) for i in range(len(tokens) - 1)]


def _extract_template(text: str) -> str:
    """Replace variable elements with placeholders to get structural form."""
    t = text.strip()
    t = re.sub(r"\d{4}-\d{2}-\d{2}T[\d:]+(?:[+-]\d{2}:\d{2})?", "<TS>", t)
    t = re.sub(r"[0-9a-f]{7,}", "<HASH>", t)
    t = re.sub(r"\S+\.\w{1,5}\b", "<PATH>", t)
    t = re.sub(r"\b\d+(?:\.\d+)?\b", "<N>", t)
    return t


def _linear_slope(values: list[float]) -> float:
    """Compute the slope of a simple linear regression over indices.

    Returns 0.0 for fewer than 2 data points.
    """
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


# ---------------------------------------------------------------------------
# Per-stroke novelty
# ---------------------------------------------------------------------------

def _stroke_vocabulary_novelty(
    tokens: list[str],
    prior_vocab: set[str],
) -> float:
    """Fraction of tokens not in the prior vocabulary pool."""
    if not tokens:
        return 0.0
    novel = sum(1 for t in tokens if t not in prior_vocab)
    return novel / len(tokens)


def _stroke_concept_novelty(
    bigram_list: list[tuple[str, str]],
    prior_bigrams: set[tuple[str, str]],
) -> float:
    """Fraction of bigrams not in the prior bigram pool."""
    if not bigram_list:
        return 0.0
    novel = sum(1 for bg in bigram_list if bg not in prior_bigrams)
    return novel / len(bigram_list)


def _stroke_structural_novelty(
    template: str,
    prior_templates: set[str],
) -> float:
    """1.0 if the template is new, 0.0 if seen before."""
    return 0.0 if template in prior_templates else 1.0


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------

def compute_novelty_metrics(
    strokes: list[dict[str, Any]],
    window_size: int = 30,
) -> dict[str, Any]:
    """Compute novelty decay metrics for a session of strokes.

    Parameters
    ----------
    strokes : list[dict]
        Stroke records in chronological order, each with at least a
        ``text`` or ``content`` field.
    window_size : int
        Maximum number of strokes to analyze.  If the session is
        longer, only the most recent *window_size* strokes are used.

    Returns
    -------
    dict with keys: vocabulary_novelty, concept_novelty,
    structural_novelty, novelty_index, novelty_trend, decay_class,
    strokes_analyzed, per_stroke_novelty.
    """
    if not strokes:
        return _empty_metrics()

    n = min(len(strokes), window_size)
    window = strokes[-n:]

    prior_vocab: set[str] = set()
    prior_bigrams: set[tuple[str, str]] = set()
    prior_templates: set[str] = set()

    per_stroke_index: list[float] = []
    vocab_scores: list[float] = []
    concept_scores: list[float] = []
    struct_scores: list[float] = []

    for stroke in window:
        text = stroke.get("text", "") or stroke.get("content", "") or ""
        tokens = _tokenize(text)
        bg = _bigrams(tokens)
        template = _extract_template(text)

        vn = _stroke_vocabulary_novelty(tokens, prior_vocab)
        cn = _stroke_concept_novelty(bg, prior_bigrams)
        sn = _stroke_structural_novelty(template, prior_templates)

        # Composite per-stroke novelty (same weights as final index)
        idx = 0.35 * vn + 0.35 * cn + 0.30 * sn
        per_stroke_index.append(idx)
        vocab_scores.append(vn)
        concept_scores.append(cn)
        struct_scores.append(sn)

        # Update pools AFTER scoring (so stroke is compared to prior only)
        prior_vocab.update(tokens)
        prior_bigrams.update(bg)
        prior_templates.add(template)

    # Aggregate means
    mean_vocab = sum(vocab_scores) / n if n > 0 else 0.0
    mean_concept = sum(concept_scores) / n if n > 0 else 0.0
    mean_struct = sum(struct_scores) / n if n > 0 else 0.0

    # Composite novelty index (session-level)
    novelty_index = 0.35 * mean_vocab + 0.35 * mean_concept + 0.30 * mean_struct

    # Trend: slope of per-stroke novelty over the session
    novelty_trend = _linear_slope(per_stroke_index)

    # Classification
    decay_class = _classify_decay(novelty_trend)

    return {
        "vocabulary_novelty": round(mean_vocab, 4),
        "concept_novelty": round(mean_concept, 4),
        "structural_novelty": round(mean_struct, 4),
        "novelty_index": round(novelty_index, 4),
        "novelty_trend": round(novelty_trend, 6),
        "decay_class": decay_class,
        "strokes_analyzed": n,
        "per_stroke_novelty": [round(v, 4) for v in per_stroke_index],
    }


def _classify_decay(trend: float) -> str:
    """Classify novelty decay from the trend slope."""
    if trend >= 0.03:
        return "blooming"
    elif trend > -0.03:
        return "steady"
    elif trend > -0.08:
        return "plateauing"
    else:
        return "exhausted"


def _empty_metrics() -> dict[str, Any]:
    """Return empty metrics when no strokes are available."""
    return {
        "vocabulary_novelty": 0.0,
        "concept_novelty": 0.0,
        "structural_novelty": 0.0,
        "novelty_index": 0.0,
        "novelty_trend": 0.0,
        "decay_class": "exhausted",
        "strokes_analyzed": 0,
        "per_stroke_novelty": [],
    }


# ---------------------------------------------------------------------------
# Trend analysis (multi-session)
# ---------------------------------------------------------------------------

def compute_novelty_over_sessions(
    all_strokes: list[dict[str, Any]],
    session_size: int = 20,
    step: int = 10,
) -> list[dict[str, Any]]:
    """Compute novelty metrics over sliding windows across sessions.

    Parameters
    ----------
    all_strokes : list[dict]
        Full stroke history across sessions.
    session_size : int
        Number of strokes per analysis window.
    step : int
        Step between consecutive windows.

    Returns
    -------
    list[dict]
        One metrics dict per window.
    """
    if len(all_strokes) < session_size:
        return [compute_novelty_metrics(all_strokes, session_size)]

    snapshots: list[dict[str, Any]] = []
    for start in range(0, len(all_strokes) - session_size + 1, step):
        window = all_strokes[start : start + session_size]
        metrics = compute_novelty_metrics(window, session_size)
        metrics["window_start"] = start
        snapshots.append(metrics)

    return snapshots


def classify_session_trajectory(
    snapshots: list[dict[str, Any]],
) -> str:
    """Classify how novelty decay evolves across sessions.

    Returns
    -------
    str
        One of: recovering, stable, declining, insufficient_data.

        - recovering: later sessions have better (more positive)
          novelty trends than earlier ones.
        - stable: novelty trends are roughly constant.
        - declining: later sessions have worse (more negative)
          novelty trends.
    """
    if len(snapshots) < 2:
        return "insufficient_data"

    trends = [s.get("novelty_trend", 0.0) for s in snapshots]
    half = len(trends) // 2
    first_half = trends[:half]
    second_half = trends[half:]

    avg_first = sum(first_half) / len(first_half) if first_half else 0.0
    avg_second = sum(second_half) / len(second_half) if second_half else 0.0

    delta = avg_second - avg_first

    if delta > 0.02:
        return "recovering"
    elif delta < -0.02:
        return "declining"
    else:
        return "stable"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def format_novelty_report(metrics: dict[str, Any]) -> str:
    """Format novelty decay metrics as a human-readable report."""
    lines = [
        "=== Writer Novelty Decay ===",
        f"Strokes analyzed:     {metrics['strokes_analyzed']}",
        f"Novelty index:        {metrics['novelty_index']:.4f}",
        f"Novelty trend:        {metrics['novelty_trend']:+.6f}",
        f"Decay class:          {metrics['decay_class']}",
        "",
        f"Vocabulary novelty:   {metrics['vocabulary_novelty']:.4f}",
        f"Concept novelty:      {metrics['concept_novelty']:.4f}",
        f"Structural novelty:   {metrics['structural_novelty']:.4f}",
        "",
    ]

    dc = metrics["decay_class"]
    lines.append("Interpretation:")
    if dc == "blooming":
        lines.append("  Novelty is accelerating. The writer is finding more new")
        lines.append("  territory as the session progresses — a flow state.")
    elif dc == "steady":
        lines.append("  Novelty is stable. The writer maintains a sustainable")
        lines.append("  pace with a roughly constant drip of new material.")
    elif dc == "plateauing":
        lines.append("  Moderate novelty decay. The writer is running low on")
        lines.append("  fresh ideas but still producing some new content.")
        lines.append("  Normal in long sessions; consider a topic shift.")
    else:
        lines.append("  Sharp novelty decay. The writer has largely exhausted")
        lines.append("  its idea-space. New strokes revisit old ground.")
        lines.append("  Intervention recommended: pause or switch topics.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone analysis (reads from strokes.jsonl)
# ---------------------------------------------------------------------------

def analyze_novelty_decay(
    strokes_path: str = "data/strokes.jsonl",
    window_size: int = 50,
) -> dict[str, Any]:
    """Analyze novelty decay from the strokes file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Novelty decay metrics.
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

    return compute_novelty_metrics(strokes, window_size)


if __name__ == "__main__":
    metrics = analyze_novelty_decay()
    print(format_novelty_report(metrics))
