#!/usr/bin/env python3
"""writer_tension — measure how well text builds and sustains anticipation.

Tension is about *forward pull*.  A tensioned text makes the reader want
to keep reading: questions are posed before answers are given, information
is revealed gradually, stakes are established early, and resolution is
delayed just enough to create engagement without frustration.

A text with no tension reads like a grocery list — each item is self-
contained, nothing depends on what came before, and there is no reason
to continue beyond the current line.  A text with strong tension reads
like a detective story — every paragraph opens a new question or deepens
an existing one, and the reader feels compelled to resolve the gap.

This module is orthogonal to the other writer metrics:

- **pacing** tracks *density variation*.  A text can have excellent
  pacing (alternating dense and light passages) while having no tension
  (each passage is self-contained, nothing hangs unresolved).  Pacing is
  about rhythm; tension is about anticipation.

- **coherence** tracks *logical flow*.  A text can be perfectly coherent
  (every step follows logically) while having no tension (every question
  is answered immediately, nothing is left open).  Coherence is about
  sense; tension is about curiosity.

- **cohesion** tracks *sentence-to-sentence connection*.  A text can be
  cohesive (each sentence links smoothly to the next) while having no
  tension (the linked sentences form a flat, predictable sequence).
  Cohesion is about connection; tension is about forward pull.

- **signal_clarity** tracks *novelty across strokes*.  A text can have
  high clarity (every stroke is unique) while having no tension (the
  unique strokes don't build on each other).  Clarity is about freshness;
  tension is about accumulation.

- **readability** tracks *parse ease*.  A text can be very readable
  (simple sentences, common words) while having no tension (the simple
  sentences don't create any unresolved expectations).  Readability is
  about access; tension is about engagement.

- **concision** tracks *economy*.  A text can be concise (no wasted
  words) while having no tension (every word contributes to a flat,
  resolved narrative).  Concision is about efficiency; tension is about
  the reader's desire to continue.

Tension asks: **does the text make the reader want to turn the page?**

Four signals are tracked:

1. **Open loop density** — the frequency of unresolved questions,
   conditional statements, forward references, and anticipatory phrases
   per hundred words.  Open loops include: direct questions ("why does
   this happen?"), conditional openings ("if we assume...", "given
   that..."), forward references ("as we will see", "this becomes
   important later"), anticipatory phrases ("the surprising result",
   "what follows is", "the key insight"), and cliffhanger endings
   (sentences ending with "...", trailing clauses).  Higher density
   means more threads are being opened for the reader to track.

2. **Resolution delay** — the average distance (in sentences) between
   an open loop and its nearest resolution marker.  Resolution markers
   include: answer words ("the answer is", "this means", "therefore",
   "thus", "so"), conclusion phrases ("in conclusion", "as a result",
   "this shows that"), and definitive statements ("the fact is",
   "clearly", "evidently").  Longer delay means the reader must hold
   more uncertainty for longer.  Short delay means every question is
   answered immediately (low tension).  Very long delay means the
   reader may forget the question or lose patience (excessive tension).
   The ideal is moderate delay: 3–7 sentences.

3. **Stakes escalation** — whether consequence and importance markers
   increase over the course of the text.  Stakes markers include:
   consequence words ("therefore", "consequently", "as a result"),
   importance markers ("crucially", "importantly", "significantly",
   "the key", "the critical"), urgency signals ("urgently", "must",
   "essential", "vital", "imperative"), and risk language ("danger",
   "risk", "threat", "failure", "collapse", "catastrophic").  The
   metric measures the correlation between sentence position and stakes
   marker density: positive correlation means stakes escalate; zero
   correlation means stakes are flat; negative correlation means stakes
   deflate (the text starts dramatic and becomes mundane).

4. **Information reveal rate** — how gradually new information is
   introduced.  Measured as the coefficient of variation of new-word
   introduction rate across text segments.  A text that dumps all new
   concepts in the first paragraph and then elaborates has low reveal
   variation (front-loaded).  A text that introduces new concepts at a
   steady or accelerating rate has high reveal variation (gradual or
   building).  The ideal is moderate variation: new information arrives
   throughout, not just at the beginning or end.

From these signals a session-level **tension_index** is computed and
classified:

==============  ============================================================
class           meaning
==============  ============================================================
gripping        index >= 0.80 — the text builds anticipation masterfully;
                questions are posed and resolved with perfect timing; stakes
                escalate; the reader is pulled forward relentlessly
compelling      0.65 <= index < 0.80 — strong forward pull; most sections
                build anticipation effectively; occasional flat spots but
                the overall arc keeps the reader engaged
steady          0.50 <= index < 0.65 — moderate tension; some sections build
                anticipation well while others are flat; the reader has
                reasons to continue but no strong compulsion
flat            0.35 <= index < 0.50 — weak forward pull; most statements
                are self-contained; few open loops or escalating stakes;
                the reader can stop at any point without feeling loss
stale           index < 0.35 — no tension whatsoever; the text reads like
                a flat enumeration; no questions, no stakes, no revelation;
                the reader has no reason to continue
==============  ============================================================

Reference: Jerry Cleaver, *Immediate Fiction* (2002): "Story is about
conflict and what it does to people.  Conflict is the trigger that starts
everything."  Applied to autonomous writing: a writer that cannot build
tension produces output that is correct but inert — technically sound,
rhetorically lifeless.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Open loop patterns — phrases that create unresolved expectations
# ---------------------------------------------------------------------------

OPEN_LOOP_PATTERNS: list[re.Pattern] = [
    # Direct questions
    re.compile(r"\?", re.IGNORECASE),
    # Conditional openings
    re.compile(r"\bif\s+we\s+(?:assume|consider|accept|suppose|imagine)\b", re.IGNORECASE),
    re.compile(r"\bgiven\s+that\b", re.IGNORECASE),
    re.compile(r"\bsuppose\s+(?:that\s+)?(?:we|you|the|it)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+if\b", re.IGNORECASE),
    re.compile(r"\bimagine\s+(?:that\s+)?(?:we|you|the|it)\b", re.IGNORECASE),
    # Forward references
    re.compile(r"\bas\s+we\s+will\s+see\b", re.IGNORECASE),
    re.compile(r"\bthis\s+becomes?\s+(?:important|relevant|clear|apparent|evident)\s+later\b", re.IGNORECASE),
    re.compile(r"\bwe\s+will\s+(?:see|discover|find|explore|examine|return\s+to)\b", re.IGNORECASE),
    re.compile(r"\bthis\s+will\s+(?:become|prove|turn\s+out\s+to\s+be)\b", re.IGNORECASE),
    re.compile(r"\bmore\s+on\s+this\s+later\b", re.IGNORECASE),
    re.compile(r"\bas\s+(?:noted|mentioned|discussed)\s+(?:earlier|above|below|later)\b", re.IGNORECASE),
    # Anticipatory phrases
    re.compile(r"\bthe\s+(?:surprising|unexpected|remarkable|startling|striking)\s+(?:result|finding|truth|answer|conclusion|twist)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+follows\s+is\b", re.IGNORECASE),
    re.compile(r"\bthe\s+key\s+(?:insight|idea|point|takeaway|observation)\b", re.IGNORECASE),
    re.compile(r"\bhere'?s?\s+the\s+(?:thing|catch|twist|trick|secret|puzzle)\b", re.IGNORECASE),
    re.compile(r"\bbut\s+(?:there'?s|here'?s)\s+(?:a|the)\b", re.IGNORECASE),
    re.compile(r"\bthe\s+question\s+(?:is|remains|becomes)\b", re.IGNORECASE),
    re.compile(r"\bthis\s+raises?\s+the\s+question\b", re.IGNORECASE),
    re.compile(r"\bone\s+might\s+(?:wonder|ask|think)\b", re.IGNORECASE),
    # Cliffhanger / trailing patterns
    re.compile(r"\.\.\.\s*$"),
    re.compile(r"\bbut\s+(?:that'?s\s+)?(?:not|another)\s+(?:story|matter|question)\s+(?:for|entirely)\b", re.IGNORECASE),
    re.compile(r"\bor\s+does\s+it\s*\?", re.IGNORECASE),
    re.compile(r"\bbut\s+at\s+what\s+cost\s*\?", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Resolution markers — phrases that close open loops
# ---------------------------------------------------------------------------

RESOLUTION_MARKERS: list[re.Pattern] = [
    re.compile(r"\bthe\s+answer\s+is\b", re.IGNORECASE),
    re.compile(r"\bthis\s+means\s+that\b", re.IGNORECASE),
    re.compile(r"\btherefore\b", re.IGNORECASE),
    re.compile(r"\bthus\b", re.IGNORECASE),
    re.compile(r"\bso\s+(?:the|we|it|this|that)\b", re.IGNORECASE),
    re.compile(r"\bin\s+conclusion\b", re.IGNORECASE),
    re.compile(r"\bas\s+a\s+result\b", re.IGNORECASE),
    re.compile(r"\bthis\s+shows?\s+that\b", re.IGNORECASE),
    re.compile(r"\bthis\s+(?:proves|demonstrates|reveals|confirms|indicates)\b", re.IGNORECASE),
    re.compile(r"\bthe\s+(?:fact|truth|reality)\s+is\b", re.IGNORECASE),
    re.compile(r"\bclearly\b", re.IGNORECASE),
    re.compile(r"\bevidently\b", re.IGNORECASE),
    re.compile(r"\bit\s+(?:turns?\s+out|becomes?\s+clear|is\s+now\s+clear)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+this\s+means\b", re.IGNORECASE),
    re.compile(r"\bthe\s+(?:reason|explanation|cause)\s+(?:is|was)\b", re.IGNORECASE),
    re.compile(r"\bthis\s+(?:resolves|answers|explains|clarifies)\b", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Stakes markers — words that signal consequence and importance
# ---------------------------------------------------------------------------

STAKES_MARKERS: set[str] = {
    # Consequence
    "therefore", "consequently", "accordingly", "hence",
    # Importance
    "crucially", "importantly", "significantly", "critically",
    "essential", "vital", "fundamental", "pivotal", "key",
    "central", "paramount", "decisive", "determinative",
    # Urgency
    "urgently", "must", "imperative", "pressing", "urgent",
    "compelling", "necessary", "required", "indispensable",
    # Risk
    "danger", "risk", "threat", "failure", "collapse",
    "catastrophic", "devastating", "irreversible", "fatal",
    "precarious", "fragile", "vulnerable", "perilous",
    # Impact
    "profound", "far-reaching", "transformative", "revolutionary",
    "consequential", "monumental", "earth-shattering", "seismic",
}

_STAKES_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in sorted(STAKES_MARKERS)) + r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_words(text: str) -> list[str]:
    """Split text into lowercase words."""
    return re.findall(r"[a-zA-Z']+", text.lower())


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    parts = re.split(r'[.!?]+', text)
    return [p.strip() for p in parts if p.strip()]


def _get_stroke_text(stroke: dict[str, Any] | str) -> str:
    """Extract text from a stroke dict or raw string."""
    if isinstance(stroke, str):
        return stroke
    return stroke.get("text", stroke.get("content", ""))


def _segment_words(words: list[str], segment_size: int = 50) -> list[list[str]]:
    """Split word list into fixed-size segments."""
    return [words[i:i + segment_size] for i in range(0, len(words), segment_size)]


# ---------------------------------------------------------------------------
# Signal 1: Open loop density
# ---------------------------------------------------------------------------


def count_open_loops(text: str) -> int:
    """Count the number of open loop patterns found in text."""
    count = 0
    for pattern in OPEN_LOOP_PATTERNS:
        count += len(pattern.findall(text))
    return count


def compute_open_loop_density(text: str) -> float:
    """Compute open loops per hundred words.

    Returns the number of open loop pattern hits normalized per 100
    words.  Higher = more unresolved expectations created.
    """
    words = _split_words(text)
    if not words:
        return 0.0
    loop_count = count_open_loops(text)
    return (loop_count / len(words)) * 100


# ---------------------------------------------------------------------------
# Signal 2: Resolution delay
# ---------------------------------------------------------------------------


def _sentence_has_open_loop(sentence: str) -> bool:
    """Check whether a sentence contains an open loop pattern."""
    return any(p.search(sentence) for p in OPEN_LOOP_PATTERNS)


def _sentence_has_resolution(sentence: str) -> bool:
    """Check whether a sentence contains a resolution marker."""
    return any(p.search(sentence) for p in RESOLUTION_MARKERS)


def compute_resolution_delay(text: str, max_lookback: int = 20) -> float:
    """Compute average distance between open loops and their resolutions.

    For each sentence containing an open loop, look ahead (up to
    max_lookback sentences) for the nearest resolution marker.  Return
    the average gap in sentences.

    Returns
    -------
    float
        Average sentences between loop opening and resolution.
        Returns 0.0 if no open loops are found.
        Returns max_lookback as a floor if loops exist but no
        resolutions are found (unresolved tension).
    """
    sentences = _split_sentences(text)
    if not sentences:
        return 0.0

    delays: list[int] = []
    for i, sent in enumerate(sentences):
        if _sentence_has_open_loop(sent):
            # Look ahead for resolution
            resolved = False
            for j in range(i + 1, min(i + max_lookback + 1, len(sentences))):
                if _sentence_has_resolution(sentences[j]):
                    delays.append(j - i)
                    resolved = True
                    break
            if not resolved:
                delays.append(max_lookback)

    if not delays:
        return 0.0

    return sum(delays) / len(delays)


def _resolution_delay_score(delay: float) -> float:
    """Score resolution delay on a 0-1 scale.

    Ideal is 3-7 sentences (score ~1.0).
    Too short (0-2) or too long (8+) both reduce score.
    """
    if delay == 0.0:
        return 0.0
    # Bell curve centered at 5 with sigma ~2
    import math
    score = math.exp(-0.5 * ((delay - 5.0) / 2.5) ** 2)
    return round(score, 4)


# ---------------------------------------------------------------------------
# Signal 3: Stakes escalation
# ---------------------------------------------------------------------------


def compute_stakes_escalation(text: str) -> float:
    """Compute whether stakes markers increase over the text.

    Divides the text into ten equal segments and measures stakes marker
    density in each.  Returns the Pearson correlation between segment
    index and stakes density.  Positive = escalating; negative =
    deflating; zero = flat.

    Returns a value in [-1, 1].  Returns 0.0 if insufficient data.
    """
    words = _split_words(text)
    if len(words) < 20:
        return 0.0

    n_segments = 10
    seg_size = max(1, len(words) // n_segments)
    densities: list[float] = []

    for i in range(n_segments):
        start = i * seg_size
        end = min(start + seg_size, len(words))
        segment_text = " ".join(words[start:end])
        stake_count = len(_STAKES_RE.findall(segment_text))
        seg_len = end - start
        densities.append(stake_count / seg_len if seg_len > 0 else 0.0)

    # Pearson correlation between segment index and density
    n = len(densities)
    if n < 3:
        return 0.0

    mean_x = (n - 1) / 2.0
    mean_y = sum(densities) / n

    numerator = sum((i - mean_x) * (d - mean_y) for i, d in enumerate(densities))
    denom_x = sum((i - mean_x) ** 2 for i in range(n))
    denom_y = sum((d - mean_y) ** 2 for d in densities)

    if denom_x == 0 or denom_y == 0:
        return 0.0

    correlation = numerator / (denom_x ** 0.5 * denom_y ** 0.5)
    return round(max(-1.0, min(1.0, correlation)), 4)


def _stakes_score(escalation: float) -> float:
    """Convert stakes escalation correlation to 0-1 score.

    Maps [-1, 1] to [0, 1] linearly: -1 → 0, 0 → 0.5, 1 → 1.
    """
    return round((escalation + 1.0) / 2.0, 4)


# ---------------------------------------------------------------------------
# Signal 4: Information reveal rate
# ---------------------------------------------------------------------------


def compute_information_reveal_rate(text: str, segment_size: int = 50) -> float:
    """Compute how gradually new information is introduced.

    Measures the coefficient of variation of new-word rate across text
    segments.  New words in a segment are those not seen in any prior
    segment.

    Returns the CV (std / mean) of new-word counts across segments.
    Higher CV = more uneven reveal (front-loaded or back-loaded).
    Lower CV = steady reveal.  The ideal is moderate variation (0.2-0.5).

    Returns
    -------
    float
        CV of new-word introduction rate.  0.0 if insufficient data.
    """
    words = _split_words(text)
    if len(words) < segment_size * 2:
        return 0.0

    segments = _segment_words(words, segment_size)
    seen: set[str] = set()
    new_counts: list[int] = []

    for seg in segments:
        new_words = [w for w in seg if w not in seen]
        new_counts.append(len(new_words))
        seen.update(seg)

    if not new_counts:
        return 0.0

    mean_val = sum(new_counts) / len(new_counts)
    if mean_val == 0:
        return 0.0

    variance = sum((c - mean_val) ** 2 for c in new_counts) / len(new_counts)
    return round(variance ** 0.5 / mean_val, 4)


def _reveal_score(cv: float) -> float:
    """Score information reveal rate on a 0-1 scale.

    Ideal CV is 0.2-0.5 (moderate variation).  Bell curve centered
    at 0.35 with sigma ~0.2.
    """
    if cv == 0.0:
        return 0.3  # No data → low-mid score
    import math
    score = math.exp(-0.5 * ((cv - 0.35) / 0.25) ** 2)
    return round(score, 4)


# ---------------------------------------------------------------------------
# Composite index
# ---------------------------------------------------------------------------


def compute_tension_index(
    open_loop_density: float,
    resolution_delay: float,
    stakes_escalation: float,
    information_reveal_rate: float,
) -> float:
    """Compute composite tension index from the four signals.

    The index is a weighted combination:
    - Open loop density: 30% weight (how many threads are opened)
    - Resolution delay: 25% weight (how long threads stay open)
    - Stakes escalation: 25% weight (whether stakes build)
    - Information reveal: 20% weight (how gradually info is revealed)

    Returns a value in [0, 1] where higher = more tensioned.
    """
    # Open loop density: ideal 1-3 per 100 words; map to score
    if open_loop_density == 0.0:
        loop_score = 0.0
    elif open_loop_density < 0.5:
        loop_score = open_loop_density * 1.0  # 0-0.5 → 0-0.5
    else:
        # Bell curve centered at 2.0
        import math
        loop_score = math.exp(-0.5 * ((open_loop_density - 2.0) / 1.5) ** 2)

    delay_score = _resolution_delay_score(resolution_delay)
    stakes_score = _stakes_score(stakes_escalation)
    reveal_score = _reveal_score(information_reveal_rate)

    index = (
        0.30 * loop_score
        + 0.25 * delay_score
        + 0.25 * stakes_score
        + 0.20 * reveal_score
    )

    return round(max(0.0, min(1.0, index)), 4)


def _classify_tension(index: float) -> str:
    """Classify tension index into a descriptive class.

    Returns one of: gripping, compelling, steady, flat, stale.
    """
    if index >= 0.80:
        return "gripping"
    elif index >= 0.65:
        return "compelling"
    elif index >= 0.50:
        return "steady"
    elif index >= 0.35:
        return "flat"
    else:
        return "stale"


# ---------------------------------------------------------------------------
# Stroke-level analysis
# ---------------------------------------------------------------------------


def analyze_stroke_tension(
    stroke: dict[str, Any] | str,
) -> dict[str, Any]:
    """Analyze tension for a single stroke.

    Parameters
    ----------
    stroke : dict or str
        A stroke dict (with 'text' or 'content' key) or raw text string.

    Returns
    -------
    dict
        Tension metrics for the stroke.
    """
    text = _get_stroke_text(stroke)
    words = _split_words(text)
    word_count = len(words)

    if word_count == 0:
        return {
            "word_count": 0,
            "open_loop_density": 0.0,
            "open_loop_count": 0,
            "resolution_delay": 0.0,
            "stakes_escalation": 0.0,
            "information_reveal_rate": 0.0,
            "tension_index": 0.0,
            "tension_class": "stale",
        }

    ol_density = compute_open_loop_density(text)
    ol_count = count_open_loops(text)
    res_delay = compute_resolution_delay(text)
    stakes_esc = compute_stakes_escalation(text)
    reveal_rate = compute_information_reveal_rate(text)
    tension_idx = compute_tension_index(ol_density, res_delay, stakes_esc, reveal_rate)

    return {
        "word_count": word_count,
        "open_loop_density": round(ol_density, 4),
        "open_loop_count": ol_count,
        "resolution_delay": round(res_delay, 4),
        "stakes_escalation": round(stakes_esc, 4),
        "information_reveal_rate": round(reveal_rate, 4),
        "tension_index": tension_idx,
        "tension_class": _classify_tension(tension_idx),
    }


# ---------------------------------------------------------------------------
# Session-level analysis
# ---------------------------------------------------------------------------


def compute_tension_metrics(
    strokes: list[dict[str, Any] | str],
    window_size: int = 50,
) -> dict[str, Any]:
    """Compute session-level tension metrics from a list of strokes.

    Parameters
    ----------
    strokes : list
        List of stroke dicts or raw text strings.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Session-level tension metrics.
    """
    if not strokes:
        return _empty_metrics()

    recent = strokes[-window_size:]
    stroke_analyses = [analyze_stroke_tension(s) for s in recent]

    total_words = sum(a["word_count"] for a in stroke_analyses)

    avg_ol_density = (
        sum(a["open_loop_density"] for a in stroke_analyses)
        / len(stroke_analyses)
    )
    total_ol_count = sum(a["open_loop_count"] for a in stroke_analyses)
    avg_res_delay = (
        sum(a["resolution_delay"] for a in stroke_analyses)
        / len(stroke_analyses)
    )
    avg_stakes = (
        sum(a["stakes_escalation"] for a in stroke_analyses)
        / len(stroke_analyses)
    )
    avg_reveal = (
        sum(a["information_reveal_rate"] for a in stroke_analyses)
        / len(stroke_analyses)
    )

    tension_index = compute_tension_index(
        avg_ol_density, avg_res_delay, avg_stakes, avg_reveal
    )
    tension_class = _classify_tension(tension_index)

    # Distribution of tension classes across strokes
    class_dist: dict[str, int] = {}
    for a in stroke_analyses:
        tc = a["tension_class"]
        class_dist[tc] = class_dist.get(tc, 0) + 1

    return {
        "strokes_analyzed": len(stroke_analyses),
        "total_words": total_words,
        "tension_index": tension_index,
        "tension_class": tension_class,
        "avg_open_loop_density": round(avg_ol_density, 4),
        "total_open_loops": total_ol_count,
        "avg_resolution_delay": round(avg_res_delay, 4),
        "avg_stakes_escalation": round(avg_stakes, 4),
        "avg_information_reveal_rate": round(avg_reveal, 4),
        "class_distribution": class_dist,
    }


def _empty_metrics() -> dict[str, Any]:
    """Return empty metrics structure."""
    return {
        "strokes_analyzed": 0,
        "total_words": 0,
        "tension_index": 0.0,
        "tension_class": "stale",
        "avg_open_loop_density": 0.0,
        "total_open_loops": 0,
        "avg_resolution_delay": 0.0,
        "avg_stakes_escalation": 0.0,
        "avg_information_reveal_rate": 0.0,
        "class_distribution": {},
    }


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


def compute_tension_trend(
    strokes: list[dict[str, Any] | str],
    window_size: int = 20,
    step: int = 10,
) -> list[dict[str, Any]]:
    """Compute tension snapshots over time for trend analysis.

    Parameters
    ----------
    strokes : list
        Full stroke list.
    window_size : int
        Strokes per snapshot window.
    step : int
        Stride between windows.

    Returns
    -------
    list[dict]
        List of snapshot dicts with tension metrics.
    """
    if not strokes:
        return []

    snapshots: list[dict[str, Any]] = []
    for start in range(0, max(1, len(strokes) - window_size + 1), step):
        window = strokes[start : start + window_size]
        metrics = compute_tension_metrics(window, window_size)
        metrics["window_start"] = start
        snapshots.append(metrics)
    return snapshots


def classify_trend(snapshots: list[dict[str, Any]]) -> str:
    """Classify the tension trend from snapshots.

    Returns one of: building, stable, fading, insufficient_data.
    """
    if len(snapshots) < 2:
        return "insufficient_data"

    scores = [s.get("tension_index", 0.0) for s in snapshots]
    first_half = scores[: len(scores) // 2]
    second_half = scores[len(scores) // 2 :]

    avg_first = sum(first_half) / len(first_half) if first_half else 0.0
    avg_second = sum(second_half) / len(second_half) if second_half else 0.0

    delta = avg_second - avg_first

    if delta > 0.05:
        return "building"
    elif delta < -0.05:
        return "fading"
    else:
        return "stable"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_tension_report(metrics: dict[str, Any]) -> str:
    """Format tension metrics as a human-readable report."""
    lines = [
        "=== Writer Tension ===",
        f"Strokes analyzed: {metrics['strokes_analyzed']}",
        f"Total words:      {metrics['total_words']}",
        f"Tension index:    {metrics['tension_index']:.4f} ({metrics['tension_class']})",
        "",
        f"Avg open loop density:      {metrics['avg_open_loop_density']:.4f} per 100 words",
        f"Total open loops:           {metrics['total_open_loops']}",
        f"Avg resolution delay:       {metrics['avg_resolution_delay']:.4f} sentences",
        f"Avg stakes escalation:      {metrics['avg_stakes_escalation']:.4f}",
        f"Avg info reveal rate (CV):  {metrics['avg_information_reveal_rate']:.4f}",
        "",
    ]

    dist = metrics.get("class_distribution", {})
    if dist:
        lines.append("Class distribution:")
        for cls in ("gripping", "compelling", "steady", "flat", "stale"):
            count = dist.get(cls, 0)
            if count:
                lines.append(f"  {cls:14s} {count}")
        lines.append("")

    tc = metrics["tension_class"]
    lines.append("Interpretation:")
    if tc == "gripping":
        lines.append("  The text builds anticipation masterfully. Questions are")
        lines.append("  posed and resolved with perfect timing; stakes escalate;")
        lines.append("  the reader is pulled forward relentlessly.")
    elif tc == "compelling":
        lines.append("  Strong forward pull. Most sections build anticipation")
        lines.append("  effectively. The overall arc keeps the reader engaged.")
    elif tc == "steady":
        lines.append("  Moderate tension. Some sections build anticipation while")
        lines.append("  others are flat. The reader has reasons to continue but")
        lines.append("  no strong compulsion.")
    elif tc == "flat":
        lines.append("  Weak forward pull. Most statements are self-contained.")
        lines.append("  The reader can stop at any point without feeling loss.")
    else:
        lines.append("  No tension. The text reads like a flat enumeration.")
        lines.append("  The reader has no reason to continue.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Session-level analysis (aliases used by writer_loop / metrics pipeline)
# ---------------------------------------------------------------------------


def analyze_strokes(
    strokes: list[dict[str, Any] | str],
    window_size: int = 50,
) -> dict[str, Any]:
    """Alias for compute_tension_metrics (pipeline compatibility)."""
    return compute_tension_metrics(strokes, window_size)


def format_report(metrics: dict[str, Any]) -> str:
    """Alias for format_tension_report (pipeline compatibility)."""
    return format_tension_report(metrics)


# ---------------------------------------------------------------------------
# Standalone analysis (reads from strokes.jsonl)
# ---------------------------------------------------------------------------


def analyze_tension(
    strokes_path: str = "data/strokes.jsonl",
    window_size: int = 50,
) -> dict[str, Any]:
    """Analyze tension from the strokes file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Tension metrics.
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

    return compute_tension_metrics(strokes, window_size)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze writer tension")
    parser.add_argument(
        "--strokes", default="data/strokes.jsonl", help="Path to strokes file"
    )
    parser.add_argument(
        "--window", type=int, default=50, help="Number of strokes to analyze"
    )
    args = parser.parse_args()

    metrics = analyze_tension(args.strokes, args.window)
    print(format_tension_report(metrics))
