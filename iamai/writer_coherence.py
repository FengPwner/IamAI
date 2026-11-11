#!/usr/bin/env python3
"""writer_coherence — measure whether consecutive ideas logically connect
and build on each other within a writing session.

Coherence is about *thread continuity*.  A coherent session reads like a
single sustained argument: each stroke picks up concepts from its
predecessors, extends them, and passes them forward.  An incoherent
session reads like a shuffled deck of unrelated notes: each stroke may
be well-formed in isolation, but the sequence lacks connective tissue.

This module is orthogonal to the other writer metrics:

- **novelty_decay** tracks whether the *rate of new content* trends up
  or down across the session arc.  A session can have zero decay
  (steady novelty) while being incoherent (each novel stroke is about
  a different topic).

- **exploration_exploitation** tracks whether the writer *ventures into
  new territory* or *deepens known territory*.  A session can be 100%
  exploitation (no exploration) while being incoherent (exploiting ten
  unrelated threads in alternation).

- **signal_clarity** tracks whether strokes are *substantively different*
  from their neighbours.  A session can have perfect clarity (no
  repetition) while being incoherent (every stroke is unique but
  unrelated to the previous).

Coherence asks specifically: **does stroke N connect to stroke N-1?**

Three signals are tracked per adjacent pair:

1. **Lexical chaining** — Jaccard similarity of word sets between
   adjacent strokes.  Two strokes that share significant vocabulary
   are lexically chained; two strokes with zero word overlap are
   lexically disconnected.

2. **Concept threading** — do any bigrams from stroke N appear in
   strokes N-1 through N-W (a lookback window)?  A concept that
   recurs across multiple strokes forms a *thread*.  A session with
   many active threads is coherent; one where each stroke introduces
   only disposable bigrams is fragmented.

3. **Topic stability** — the rolling-window similarity of vocabulary
   distributions.  If the word-frequency profile of the last W strokes
   is similar to the profile of the previous W strokes, the topic is
   stable.  Sharp shifts indicate topic jumps.

From these per-pair signals a session-level **coherence_index** is
computed and classified:

==============  ============================================================
class           meaning
==============  ============================================================
narrative       coherence_index >= 0.60 — ideas flow from one stroke to the
                next with strong connective tissue; the session reads like
                a single sustained exploration of related concepts
meandering      0.40 <= coherence_index < 0.60 — moderate connectivity;
                the writer follows tangents but eventually circles back
                to related themes; normal for exploratory sessions
fragmented      0.20 <= coherence_index < 0.40 — weak connectivity; the
                writer jumps between topics with minimal bridging; output
                is a collection of loosely related fragments
disjointed      coherence_index < 0.20 — almost no connectivity; strokes
                appear to be about independent topics; the session lacks
                a through-line
==============  ============================================================

The module also computes a **thread_count**: the number of distinct
bigram-based concept threads that persist across at least three
strokes.  A thread is "alive" when its bigrams appear in the current
lookback window and "dead" when they haven't appeared for W strokes.

Session arc analysis
--------------------
The session is divided into quartiles and the coherence index is
computed for each.  A healthy sustained session shows a characteristic
"settle-in" curve: moderate coherence in Q1 (the writer is still
finding the thread), rising coherence in Q2-Q3 (the thread is
developing), and slightly declining coherence in Q4 (the writer has
exhausted the easy connections and must reach further for new ones).
Deviations from this pattern are flagged:

- **Steady**: coherence roughly constant across quartiles → the writer
  maintains a consistent level of connectivity throughout.
- **Rising**: coherence increases over the session → the writer started
  scattered and gradually found the thread.
- **Falling**: coherence decreases over the session → the writer started
  strong but lost the thread, possibly due to fatigue.
- **Oscillating**: coherence alternates between high and low → the
  writer works in bursts of focused exploration separated by pivots.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase word-level tokenization preserving order."""
    return re.findall(r"\w+", text.lower())


def _bigrams(tokens: list[str]) -> list[tuple[str, str]]:
    """Extract consecutive word pairs from a token list."""
    return list(zip(tokens, tokens[1:])) if len(tokens) >= 2 else []


def _get_stroke_text(stroke: dict[str, Any]) -> str:
    """Extract text from a stroke dict, handling None and missing."""
    text = stroke.get("text") or stroke.get("content") or ""
    return str(text) if text is not None else ""


def _word_set(tokens: list[str]) -> set[str]:
    """Convert a token list to a set for Jaccard computation."""
    return set(tokens)


def _jaccard(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Per-pair analysis
# ---------------------------------------------------------------------------

def analyze_lexical_chaining(
    current_tokens: list[str],
    previous_tokens: list[str],
) -> float:
    """Compute lexical chain strength between two adjacent strokes.

    Returns Jaccard similarity of their word sets (0.0–1.0).
    """
    return _jaccard(_word_set(current_tokens), _word_set(previous_tokens))


def analyze_concept_threading(
    current_bigrams: list[tuple[str, str]],
    lookback_bigrams: list[list[tuple[str, str]]],
) -> float:
    """Measure how many of the current stroke's bigrams recur in lookback.

    Parameters
    ----------
    current_bigrams : list of bigram tuples from the current stroke
    lookback_bigrams : list of lists of bigrams from the prior W strokes

    Returns
    -------
    Fraction of current bigrams that appear in at least one lookback
    stroke (0.0–1.0).  Returns 0.0 if there are no current bigrams.
    """
    if not current_bigrams:
        return 0.0

    lookback_set: set[tuple[str, str]] = set()
    for stroke_bigrams in lookback_bigrams:
        lookback_set.update(stroke_bigrams)

    if not lookback_set:
        return 0.0

    threaded = sum(1 for b in current_bigrams if b in lookback_set)
    return threaded / len(current_bigrams)


def analyze_topic_stability(
    window_tokens: list[list[str]],
    prev_window_tokens: list[list[str]],
) -> float:
    """Measure stability of vocabulary distribution across adjacent windows.

    Computes Jaccard similarity of the union of word sets in each window.
    Returns 0.0–1.0.
    """
    current_union: set[str] = set()
    for tokens in window_tokens:
        current_union.update(tokens)

    prev_union: set[str] = set()
    for tokens in prev_window_tokens:
        prev_union.update(tokens)

    return _jaccard(current_union, prev_union)


# ---------------------------------------------------------------------------
# Thread tracking
# ---------------------------------------------------------------------------

def count_active_threads(
    strokes: list[dict[str, Any]],
    lookback: int = 5,
    min_persistence: int = 3,
) -> int:
    """Count distinct concept threads that persist across multiple strokes.

    A thread is a bigram that appears in at least ``min_persistence``
    strokes within any window of ``lookback`` consecutive strokes.

    Parameters
    ----------
    strokes : ordered list of stroke records
    lookback : window size for thread detection
    min_persistence : minimum number of strokes a bigram must appear in
        within a window to count as a thread

    Returns
    -------
    Number of distinct threads found across the entire session.
    """
    if len(strokes) < min_persistence:
        return 0

    # Collect all bigrams per stroke
    per_stroke_bigrams: list[set[tuple[str, str]]] = []
    for stroke in strokes:
        text = _get_stroke_text(stroke)
        tokens = _tokenize(text)
        per_stroke_bigrams.append(set(_bigrams(tokens)))

    # Track which bigrams appear in at least min_persistence strokes
    # within any sliding window of size lookback
    thread_bigrams: set[tuple[str, str]] = set()

    n = len(per_stroke_bigrams)
    for window_start in range(max(1, n - lookback + 1)):
        window_end = min(window_start + lookback, n)
        bigram_counts: dict[tuple[str, str], int] = {}
        for i in range(window_start, window_end):
            for b in per_stroke_bigrams[i]:
                bigram_counts[b] = bigram_counts.get(b, 0) + 1
        for bigram, count in bigram_counts.items():
            if count >= min_persistence:
                thread_bigrams.add(bigram)

    return len(thread_bigrams)


# ---------------------------------------------------------------------------
# Session-level analysis
# ---------------------------------------------------------------------------

def compute_coherence_metrics(
    strokes: list[dict[str, Any]],
    lookback: int = 3,
) -> dict[str, Any]:
    """Compute session-level coherence metrics.

    Parameters
    ----------
    strokes : list[dict]
        Ordered list of stroke records, each with ``text`` or ``content``.
    lookback : int
        Number of prior strokes to use for concept threading and topic
        stability calculations.

    Returns
    -------
    dict with keys:
        ``strokes_analyzed`` — number of strokes processed
        ``lexical_chaining`` — mean Jaccard similarity between adjacent strokes
        ``concept_threading`` — mean bigram recurrence across lookback
        ``topic_stability`` — mean vocabulary stability across windows
        ``coherence_index`` — composite (mean of the three signals)
        ``coherence_class`` — narrative | meandering | fragmented | disjointed
        ``thread_count`` — number of persistent concept threads
        ``phase_scores`` — list of 4 floats (quartile coherence scores)
        ``phase_arc`` — steady | rising | falling | oscillating
    """
    if not strokes:
        return {
            "strokes_analyzed": 0,
            "lexical_chaining": 0.0,
            "concept_threading": 0.0,
            "topic_stability": 0.0,
            "coherence_index": 0.0,
            "coherence_class": "disjointed",
            "thread_count": 0,
            "phase_scores": [0.0, 0.0, 0.0, 0.0],
            "phase_arc": "steady",
        }

    if len(strokes) == 1:
        return {
            "strokes_analyzed": 1,
            "lexical_chaining": 0.0,
            "concept_threading": 0.0,
            "topic_stability": 0.0,
            "coherence_index": 0.0,
            "coherence_class": "disjointed",
            "thread_count": 0,
            "phase_scores": [0.0, 0.0, 0.0, 0.0],
            "phase_arc": "steady",
        }

    # Pre-compute tokens and bigrams for all strokes
    all_tokens: list[list[str]] = []
    all_bigrams: list[list[tuple[str, str]]] = []
    for stroke in strokes:
        text = _get_stroke_text(stroke)
        tokens = _tokenize(text)
        all_tokens.append(tokens)
        all_bigrams.append(_bigrams(tokens))

    # Per-pair metrics
    lexical_scores: list[float] = []
    concept_scores: list[float] = []
    stability_scores: list[float] = []

    for i in range(1, len(strokes)):
        # Lexical chaining (adjacent pair)
        lex = analyze_lexical_chaining(all_tokens[i], all_tokens[i - 1])
        lexical_scores.append(lex)

        # Concept threading (lookback)
        lb_start = max(0, i - lookback)
        lb_bigrams = all_bigrams[lb_start:i]
        con = analyze_concept_threading(all_bigrams[i], lb_bigrams)
        concept_scores.append(con)

        # Topic stability (window comparison)
        win_end = i + 1
        win_start = max(0, win_end - lookback)
        prev_end = win_start
        prev_start = max(0, prev_end - lookback)
        if prev_start < prev_end and win_start < win_end:
            stab = analyze_topic_stability(
                all_tokens[win_start:win_end],
                all_tokens[prev_start:prev_end],
            )
        else:
            stab = 0.0
        stability_scores.append(stab)

    n_pairs = len(lexical_scores)
    mean_lex = sum(lexical_scores) / n_pairs if n_pairs > 0 else 0.0
    mean_con = sum(concept_scores) / n_pairs if n_pairs > 0 else 0.0
    mean_stab = sum(stability_scores) / n_pairs if n_pairs > 0 else 0.0
    coherence_index = (mean_lex + mean_con + mean_stab) / 3.0

    # Classification
    coherence_class = _classify_coherence(coherence_index)

    # Thread count
    thread_count = count_active_threads(strokes, lookback=lookback)

    # Phase analysis
    phase_scores = _compute_phase_scores(
        lexical_scores, concept_scores, stability_scores,
    )
    phase_arc = _classify_phase_arc(phase_scores)

    return {
        "strokes_analyzed": len(strokes),
        "lexical_chaining": round(mean_lex, 4),
        "concept_threading": round(mean_con, 4),
        "topic_stability": round(mean_stab, 4),
        "coherence_index": round(coherence_index, 4),
        "coherence_class": coherence_class,
        "thread_count": thread_count,
        "phase_scores": [round(s, 4) for s in phase_scores],
        "phase_arc": phase_arc,
    }


def _classify_coherence(coherence_index: float) -> str:
    """Map coherence_index to a class label."""
    if coherence_index >= 0.60:
        return "narrative"
    elif coherence_index >= 0.40:
        return "meandering"
    elif coherence_index >= 0.20:
        return "fragmented"
    else:
        return "disjointed"


def _compute_phase_scores(
    lexical: list[float],
    concept: list[float],
    stability: list[float],
) -> list[float]:
    """Divide per-pair scores into quartiles and compute mean per quartile."""
    n = len(lexical)
    if n == 0:
        return [0.0, 0.0, 0.0, 0.0]

    # Compute per-pair composite scores
    composites = [
        (lexical[i] + concept[i] + stability[i]) / 3.0
        for i in range(n)
    ]

    if n < 4:
        scores = [0.0, 0.0, 0.0, 0.0]
        for i, s in enumerate(composites):
            q = min(i, 3)
            scores[q] = s
        return scores

    q_size = n / 4.0
    quartiles: list[list[float]] = [[], [], [], []]
    for i, s in enumerate(composites):
        q = min(int(i / q_size), 3)
        quartiles[q].append(s)

    return [
        sum(q) / len(q) if q else 0.0
        for q in quartiles
    ]


def _classify_phase_arc(phase_scores: list[float]) -> str:
    """Classify the session's coherence trajectory across quartiles."""
    q1, q2, q3, q4 = phase_scores

    # Oscillating: adjacent quartiles alternate direction by > 0.05
    diffs = [q2 - q1, q3 - q2, q4 - q3]
    sign_changes = sum(
        1 for i in range(len(diffs) - 1)
        if diffs[i] * diffs[i + 1] < -0.001
    )
    if sign_changes >= 2:
        return "oscillating"

    # Rising: Q4 > Q1 by at least 0.05
    if q4 > q1 + 0.05:
        return "rising"

    # Falling: Q1 > Q4 by at least 0.05
    if q1 > q4 + 0.05:
        return "falling"

    return "steady"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_coherence_report(metrics: dict[str, Any]) -> str:
    """Format coherence metrics as a readable report."""
    lines = [
        "## writer coherence",
        "",
        f"strokes analyzed: {metrics['strokes_analyzed']}",
        f"coherence index: {metrics['coherence_index']}",
        f"coherence class: {metrics['coherence_class']}",
        f"active threads: {metrics['thread_count']}",
        "",
        "### signals",
        f"  lexical chaining: {metrics['lexical_chaining']}",
        f"  concept threading: {metrics['concept_threading']}",
        f"  topic stability: {metrics['topic_stability']}",
        "",
        "### phase analysis",
    ]
    labels = ["Q1 (early)", "Q2", "Q3", "Q4 (late)"]
    for label, score in zip(labels, metrics["phase_scores"]):
        lines.append(f"  {label}: {score}")
    lines.append(f"  arc: {metrics['phase_arc']}")
    lines.append("")

    interp = _interpret(metrics)
    lines.append("### interpretation")
    lines.append(interp)
    lines.append("")

    return "\n".join(lines)


def _interpret(metrics: dict[str, Any]) -> str:
    """Generate a plain-language interpretation of the metrics."""
    cc = metrics["coherence_class"]
    tc = metrics["thread_count"]
    pa = metrics["phase_arc"]

    parts = []

    if cc == "narrative":
        parts.append(
            "ideas flow smoothly from stroke to stroke with strong "
            "connective tissue — the session reads as a sustained argument"
        )
    elif cc == "meandering":
        parts.append(
            "moderate connectivity with occasional tangents — the writer "
            "follows side threads but circles back to related themes"
        )
    elif cc == "fragmented":
        parts.append(
            "weak connectivity between strokes — the writer jumps between "
            "topics with minimal bridging; output resembles a collection "
            "of loosely related notes"
        )
    else:
        parts.append(
            "almost no connective tissue between strokes — the session "
            "lacks a through-line and reads as independent fragments"
        )

    if tc >= 10:
        parts.append(
            f"{tc} active concept threads — the writer is juggling many "
            "interrelated ideas simultaneously"
        )
    elif tc >= 3:
        parts.append(
            f"{tc} active concept threads — a manageable number of "
            "recurring themes being developed in parallel"
        )
    elif tc >= 1:
        parts.append(
            f"only {tc} concept thread — the session is narrowly focused "
            "on a single recurring idea"
        )
    else:
        parts.append(
            "no persistent concept threads detected — ideas are introduced "
            "and abandoned without development"
        )

    if pa == "rising":
        parts.append("arc: the writer started scattered and gradually found the thread")
    elif pa == "falling":
        parts.append("arc: the writer started strong but lost coherence over time")
    elif pa == "oscillating":
        parts.append("arc: alternating between focused and scattered phases")
    else:
        parts.append("arc: consistent coherence level throughout the session")

    return "; ".join(parts)
