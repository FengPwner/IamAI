#!/usr/bin/env python3
"""writer_voice_consistency — measure whether writing maintains a stable voice.

Voice consistency is about *identity stability*.  A consistent voice
maintains a stable point of view (first, second, or third person),
a steady register (formal, neutral, or informal), and a coherent tone
(confident, tentative, neutral) throughout the text.  An inconsistent
voice shifts between "I think", "you should", and "the system must"
within the same paragraph, or oscillates between academic formality
and slang, or hedges every claim then asserts the next with absolute
certainty.

This module is orthogonal to the other writer metrics:

- **readability** tracks whether prose is *easy to parse*.  A text can
  be readable (short sentences, simple words) while having a fractured
  voice (shifting between formal report and casual chat).  Readability
  is about access; voice consistency is about identity.

- **coherence** tracks whether ideas *connect logically*.  A text can
  be coherent (every sentence follows from the last) while having an
  unstable voice (the argument flows, but the narrator keeps changing
  persona).  Coherence is about logical flow; voice is about who is
  speaking and how.

- **concision** tracks whether prose uses *only the words needed*.
  A text can be concise while having voice shifts (brief but
  alternating between first and third person).  Concision is economy;
  voice consistency is stability.

- **specificity** tracks whether prose names *concrete things*.
  A text can be specific ("Python 3.12", "port 8080") while having
  an inconsistent register (mixing technical precision with slang).
  Specificity is precision of reference; voice is consistency of
  presentation.

- **temporal_awareness** tracks whether writing knows *when*.  A text
  can be temporally grounded while shifting between "I deployed" and
  "the team deployed" and "you should deploy".  Temporal awareness is
  chronological grounding; voice consistency is narrator grounding.

- **signal_clarity** tracks whether strokes are *substantively unique*.
  A writer can produce unique, voice-consistent strokes.  Clarity is
  about uniqueness; voice is about persona stability.

Voice consistency asks: **does the reader know who is speaking, or does
the narrator keep changing identity?**

Five signals are tracked:

1. **POV consistency** — stability of grammatical person across
   sentences.  Measured by detecting first-person markers ("I", "me",
   "my", "we", "us", "our"), second-person markers ("you", "your",
   "yours"), and third-person markers ("he", "she", "it", "they",
   "the system", "the author").  The dominant POV is identified; the
   score is the fraction of sentences that match the dominant POV.
   Legitimate shifts (e.g., "I think you should..." in an
   advisory context) are detected via co-occurrence patterns and not
   penalized.

2. **Register consistency** — stability of formality level.  Formal
   markers include: passive constructions ("was observed", "were
   analyzed"), academic vocabulary ("furthermore", "consequently",
   "notwithstanding"), nominalizations ("implementation", "analysis",
   "utilization").  Informal markers include: contractions ("don't",
   "it's", "won't"), colloquialisms ("stuff", "things", "kinda",
   "sorta", "gonna"), interjections ("wow", "oops", "yikes", "meh"),
   slang ("cool", "awesome", "terrible", "insane").  The dominant
   register is identified; the score reflects how consistently it is
   maintained.

3. **Hedging consistency** — stability of epistemic stance.  Hedges
   include: "perhaps", "maybe", "possibly", "might", "could",
   "seems", "appears", "somewhat", "arguably", "to some extent".
   Boosters include: "clearly", "obviously", "undoubtedly",
   "certainly", "definitely", "must", "will", "always", "never",
   "without question".  The score measures whether the writer
   maintains a consistent level of certainty, or oscillates between
  diffidence and dogmatism.

4. **Imperative consistency** — stability of directive density.
   Imperatives ("do this", "consider that", "note that", "remember")
   create a teaching/advisory voice.  Pure declaratives create an
   expository voice.  The score measures whether the ratio of
   imperatives to declaratives stays stable across the text, or
   shifts between commanding and describing.

5. **Self-reference stability** — consistency of how the writer refers
   to themselves and the reader.  Patterns tracked: "I" vs "we" vs
   "the author" vs "this paper" for self-reference; "you" vs "the
   reader" vs "one" for reader-reference.  Stability means picking
   one pattern and sticking with it.

The **voice_consistency_index** is computed as a weighted composite:

    index = pov_consistency         * 0.25
          + register_consistency    * 0.25
          + hedging_consistency     * 0.20
          + imperative_consistency  * 0.15
          + self_reference_stability * 0.15

Classified as:

- **unified** (>= 0.80): one clear voice throughout, the reader
  always knows who is speaking and in what register.
- **consistent** (>= 0.60): mostly stable with minor shifts that
  feel natural rather than jarring.
- **mixed** (>= 0.40): noticeable shifts in person or register
  that occasionally disorient the reader.
- **wavering** (>= 0.20): frequent identity shifts, the reader
  cannot predict the narrator's stance from one sentence to the next.
- **fractured** (< 0.20): no stable voice; the text reads like a
  collage of different authors.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants — person markers
# ---------------------------------------------------------------------------

FIRST_PERSON_SINGULAR: list[str] = [
    "i", "me", "my", "mine", "myself",
]

FIRST_PERSON_PLURAL: list[str] = [
    "we", "us", "our", "ours", "ourselves",
]

FIRST_PERSON: list[str] = FIRST_PERSON_SINGULAR + FIRST_PERSON_PLURAL

SECOND_PERSON: list[str] = [
    "you", "your", "yours", "yourself", "yourselves",
]

THIRD_PERSON_SINGULAR: list[str] = [
    "he", "him", "his", "himself",
    "she", "her", "hers", "herself",
    "it", "its", "itself",
]

THIRD_PERSON_PLURAL: list[str] = [
    "they", "them", "their", "theirs", "themselves",
]

THIRD_PERSON: list[str] = THIRD_PERSON_SINGULAR + THIRD_PERSON_PLURAL

# ---------------------------------------------------------------------------
# Constants — register markers
# ---------------------------------------------------------------------------

FORMAL_MARKERS: list[str] = [
    "furthermore", "moreover", "consequently", "nevertheless",
    "notwithstanding", "henceforth", "whereas", "therein",
    "thereby", "thereof", "pursuant", "aforementioned",
    "hereinafter", "inasmuch", "whereby",
]

FORMAL_NOMINALIZATIONS: list[str] = [
    "implementation", "utilization", "analysis", "assessment",
    "evaluation", "investigation", "determination", "consideration",
    "examination", "observation", "demonstration", "application",
    "configuration", "optimization", "characterization",
]

INFORMAL_CONTRACTIONS: list[str] = [
    "don't", "doesn't", "didn't", "won't", "wouldn't", "couldn't",
    "shouldn't", "can't", "isn't", "aren't", "wasn't", "weren't",
    "hasn't", "haven't", "hadn't", "it's", "that's", "what's",
    "there's", "here's", "who's", "how's", "let's", "i'm",
    "you're", "we're", "they're", "i've", "you've", "we've",
    "they've", "i'd", "you'd", "he'd", "she'd", "we'd", "they'd",
    "i'll", "you'll", "he'll", "she'll", "we'll", "they'll",
]

INFORMAL_COLLOQUIAL: list[str] = [
    "stuff", "things", "kinda", "sorta", "gonna", "wanna",
    "gotta", "y'know", "anyway", "basically", "honestly",
    "literally", "actually", "pretty", "super", "totally",
    "awesome", "cool", "great", "terrible", "horrible",
    "crazy", "insane", "wild", "weird",
]

INFORMAL_INTERJECTIONS: list[str] = [
    "wow", "oops", "yikes", "meh", "ugh", "hmm", "huh",
    "oh", "ah", "well", "okay", "ok", "alright",
    "anyway", "anyhow",
]

# ---------------------------------------------------------------------------
# Constants — hedging and boosting
# ---------------------------------------------------------------------------

HEDGES: list[str] = [
    "perhaps", "maybe", "possibly", "might", "could",
    "seems", "seemed", "appears", "appeared",
    "somewhat", "arguably", "presumably", "allegedly",
    "reportedly", "apparently", "ostensibly",
    "to some extent", "in some cases", "it seems",
    "it appears", "one might", "it is possible",
    "not necessarily", "not always", "tend to",
    "tends to", "may",
]

BOOSTERS: list[str] = [
    "clearly", "obviously", "undoubtedly", "certainly",
    "definitely", "absolutely", "must", "will", "always",
    "never", "without question", "unquestionably",
    "indisputably", "incontrovertibly", "decidedly",
    "unequivocally", "categorically", "emphatically",
    "incontestably", "irrefutably",
]

# ---------------------------------------------------------------------------
# Constants — imperative patterns
# ---------------------------------------------------------------------------

IMPERATIVE_STARTERS: list[str] = [
    "consider", "note", "remember", "observe", "notice",
    "compare", "imagine", "assume", "suppose", "let",
    "take", "think", "look", "try", "use", "check",
    "verify", "ensure", "make", "keep", "avoid",
    "don't", "do not", "never",
]

# ---------------------------------------------------------------------------
# Constants — self-reference patterns
# ---------------------------------------------------------------------------

SELF_REF_PATTERNS: list[str] = [
    "i", "we", "the author", "this paper", "this article",
    "this study", "this work", "the present work",
    "the researcher", "the writer",
]

READER_REF_PATTERNS: list[str] = [
    "you", "the reader", "one", "readers",
    "the audience", "the user",
]

# All transitions for reference (reused from coherence).
ALL_TRANSITIONS: list[str] = [
    "moreover", "furthermore", "additionally", "also", "besides",
    "however", "although", "nevertheless", "nonetheless",
    "in contrast", "on the other hand", "conversely", "yet",
    "therefore", "consequently", "because", "since", "as a result",
    "thus", "hence", "accordingly", "so",
    "meanwhile", "subsequently", "afterward", "then", "next",
    "finally", "previously", "initially",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_words(text: str) -> list[str]:
    """Split text into lowercase word tokens."""
    return [w.lower() for w in re.findall(r"[a-zA-Z']+", text)]


def _get_stroke_text(stroke: dict[str, Any]) -> str:
    """Extract text content from a stroke record."""
    for key in ("text", "content", "body"):
        val = stroke.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return ""


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, stripping empty fragments."""
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in raw if s.strip() and len(s.split()) >= 2]


def _count_pattern(text_lower: str, patterns: list[str]) -> int:
    """Count occurrences of word-bounded patterns in lowercase text."""
    total = 0
    for p in patterns:
        total += len(re.findall(r"\b" + re.escape(p) + r"\b", text_lower))
    return total


# ---------------------------------------------------------------------------
# Signal 1: POV consistency
# ---------------------------------------------------------------------------


def _detect_pov(sentence_lower: str) -> str | None:
    """Detect the dominant POV of a single sentence.

    Returns 'first', 'second', 'third', or None if indeterminate.
    Co-occurrence of first+second (advisory "I think you should")
    counts as first person (the narrator is present).
    """
    has_first = any(
        re.search(r"\b" + re.escape(w) + r"\b", sentence_lower)
        for w in FIRST_PERSON
    )
    has_second = any(
        re.search(r"\b" + re.escape(w) + r"\b", sentence_lower)
        for w in SECOND_PERSON
    )
    has_third = any(
        re.search(r"\b" + re.escape(w) + r"\b", sentence_lower)
        for w in THIRD_PERSON
    )

    if has_first:
        return "first"
    if has_second:
        return "second"
    if has_third:
        return "third"
    return None


def compute_pov_consistency(text: str) -> float:
    """Fraction of sentences matching the dominant POV.

    Returns 0-1.  Higher means a stable point of view.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return 0.5

    pov_counts: dict[str, int] = {"first": 0, "second": 0, "third": 0}
    for s in sentences:
        pov = _detect_pov(s.lower())
        if pov:
            pov_counts[pov] += 1

    total_tagged = sum(pov_counts.values())
    if total_tagged == 0:
        return 0.5  # neutral when no POV detected

    dominant = max(pov_counts, key=pov_counts.get)  # type: ignore[arg-type]
    return pov_counts[dominant] / total_tagged


# ---------------------------------------------------------------------------
# Signal 2: Register consistency
# ---------------------------------------------------------------------------


def _count_formal(text_lower: str) -> int:
    """Count formal register markers."""
    return (
        _count_pattern(text_lower, FORMAL_MARKERS)
        + _count_pattern(text_lower, FORMAL_NOMINALIZATIONS)
    )


def _count_informal(text_lower: str) -> int:
    """Count informal register markers."""
    return (
        _count_pattern(text_lower, INFORMAL_CONTRACTIONS)
        + _count_pattern(text_lower, INFORMAL_COLLOQUIAL)
        + _count_pattern(text_lower, INFORMAL_INTERJECTIONS)
    )


def compute_register_consistency(text: str) -> float:
    """Measure how consistently one register is maintained.

    Returns 0-1.  1.0 = purely formal or purely informal throughout.
    0.0 = equal mix of formal and informal markers.
    """
    text_lower = text.lower()
    formal = _count_formal(text_lower)
    informal = _count_informal(text_lower)
    total = formal + informal

    if total == 0:
        return 0.7  # neutral when no register markers present

    dominant = max(formal, informal)
    return dominant / total


# ---------------------------------------------------------------------------
# Signal 3: Hedging consistency
# ---------------------------------------------------------------------------


def compute_hedging_consistency(text: str) -> float:
    """Measure stability of epistemic stance.

    High score = consistently hedged or consistently boosted.
    Low score = wild oscillation between hedging and boosting.

    Returns 0-1.
    """
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 0.5

    stance_per_sentence: list[float] = []
    for s in sentences:
        s_lower = s.lower()
        hedges = _count_pattern(s_lower, HEDGES)
        boosts = _count_pattern(s_lower, BOOSTERS)
        total = hedges + boosts
        if total > 0:
            # +1 for hedge-dominant, -1 for boost-dominant, 0 for mixed
            stance_per_sentence.append((hedges - boosts) / total)
        else:
            stance_per_sentence.append(0.0)  # neutral

    # Consistency = 1 - normalized_std of stance values.
    if not stance_per_sentence:
        return 0.5

    mean = sum(stance_per_sentence) / len(stance_per_sentence)
    variance = sum((v - mean) ** 2 for v in stance_per_sentence) / len(
        stance_per_sentence
    )
    std = math.sqrt(variance)

    # Max possible std is 1.0 (all +1 and -1 alternating).
    # Normalize: consistency = 1 - std.
    return max(0.0, 1.0 - std)


# ---------------------------------------------------------------------------
# Signal 4: Imperative consistency
# ---------------------------------------------------------------------------


def _is_imperative(sentence: str) -> bool:
    """Heuristic: sentence starts with an imperative verb."""
    words = sentence.strip().split()
    if not words:
        return False
    first_word = words[0].lower().rstrip("',")
    return first_word in IMPERATIVE_STARTERS


def compute_imperative_consistency(text: str) -> float:
    """Measure stability of directive density across text segments.

    Splits text into halves and compares imperative ratio.
    Returns 0-1.  High = stable ratio; low = shifting between
    commanding and describing.
    """
    sentences = _split_sentences(text)
    if len(sentences) < 4:
        return 0.5  # neutral for very short texts

    mid = len(sentences) // 2
    first_half = sentences[:mid]
    second_half = sentences[mid:]

    def _imp_ratio(sents: list[str]) -> float:
        if not sents:
            return 0.0
        imps = sum(1 for s in sents if _is_imperative(s))
        return imps / len(sents)

    r1 = _imp_ratio(first_half)
    r2 = _imp_ratio(second_half)

    # Consistency = 1 - |difference|.
    return max(0.0, 1.0 - abs(r1 - r2))


# ---------------------------------------------------------------------------
# Signal 5: Self-reference stability
# ---------------------------------------------------------------------------


def compute_self_reference_stability(text: str) -> float:
    """Measure consistency of self-reference and reader-reference patterns.

    Returns 0-1.  High = one self-reference pattern throughout.
    Low = alternating between "I", "we", "the author", etc.
    """
    text_lower = text.lower()

    self_counts: dict[str, int] = {}
    for pattern in SELF_REF_PATTERNS:
        count = len(
            re.findall(r"\b" + re.escape(pattern) + r"\b", text_lower)
        )
        if count > 0:
            self_counts[pattern] = count

    if not self_counts:
        return 0.7  # neutral when no self-reference

    total = sum(self_counts.values())
    dominant = max(self_counts.values())
    return dominant / total


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


def compute_voice_consistency_index(
    pov_consistency: float,
    register_consistency: float,
    hedging_consistency: float,
    imperative_consistency: float,
    self_reference_stability: float,
) -> float:
    """Weighted composite voice consistency index, 0-1.

    Weights:
    - POV consistency:            25%
    - register consistency:       25%
    - hedging consistency:        20%
    - imperative consistency:     15%
    - self-reference stability:   15%
    """
    index = (
        pov_consistency * 0.25
        + register_consistency * 0.25
        + hedging_consistency * 0.20
        + imperative_consistency * 0.15
        + self_reference_stability * 0.15
    )
    return round(index, 4)


def classify_voice_consistency(index: float) -> str:
    """Classify voice consistency index into a human-readable label."""
    if index >= 0.80:
        return "unified"
    if index >= 0.60:
        return "consistent"
    if index >= 0.40:
        return "mixed"
    if index >= 0.20:
        return "wavering"
    return "fractured"


# ---------------------------------------------------------------------------
# Aggregate analysis
# ---------------------------------------------------------------------------


def compute_voice_consistency_metrics(
    strokes: list[dict[str, Any]], window_size: int = 50
) -> dict[str, Any]:
    """Compute voice consistency metrics over a window of recent strokes.

    Parameters
    ----------
    strokes : list of stroke dicts
        Stroke records from strokes.jsonl.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict with keys:
        pov_consistency, register_consistency, hedging_consistency,
        imperative_consistency, self_reference_stability,
        voice_consistency_index, classification, strokes_analyzed.
    """
    recent = strokes[-window_size:] if strokes else []
    texts = [_get_stroke_text(s) for s in recent if _get_stroke_text(s)]

    if not texts:
        return _empty_metrics()

    combined = " ".join(texts)

    pov = compute_pov_consistency(combined)
    reg = compute_register_consistency(combined)
    hed = compute_hedging_consistency(combined)
    imp = compute_imperative_consistency(combined)
    srs = compute_self_reference_stability(combined)
    idx = compute_voice_consistency_index(pov, reg, hed, imp, srs)

    return {
        "pov_consistency": round(pov, 4),
        "register_consistency": round(reg, 4),
        "hedging_consistency": round(hed, 4),
        "imperative_consistency": round(imp, 4),
        "self_reference_stability": round(srs, 4),
        "voice_consistency_index": idx,
        "classification": classify_voice_consistency(idx),
        "strokes_analyzed": len(texts),
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "pov_consistency": 0.5,
        "register_consistency": 0.7,
        "hedging_consistency": 0.5,
        "imperative_consistency": 0.5,
        "self_reference_stability": 0.7,
        "voice_consistency_index": 0.5,
        "classification": "mixed",
        "strokes_analyzed": 0,
    }


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


def compute_voice_consistency_trend(
    strokes: list[dict[str, Any]], window_size: int = 50
) -> list[dict[str, Any]]:
    """Compute voice consistency index over sliding windows.

    Returns a list of dicts with 'window_start', 'window_end',
    'voice_consistency_index', 'classification'.
    """
    if len(strokes) < window_size:
        metrics = compute_voice_consistency_metrics(strokes, window_size)
        return [
            {
                "window_start": 0,
                "window_end": len(strokes),
                "voice_consistency_index": metrics["voice_consistency_index"],
                "classification": metrics["classification"],
            }
        ]

    trends = []
    step = max(window_size // 2, 1)
    for start in range(0, len(strokes) - window_size + 1, step):
        window = strokes[start : start + window_size]
        metrics = compute_voice_consistency_metrics(window, window_size)
        trends.append(
            {
                "window_start": start,
                "window_end": start + window_size,
                "voice_consistency_index": metrics["voice_consistency_index"],
                "classification": metrics["classification"],
            }
        )
    return trends


def classify_trend(trend: list[dict[str, Any]]) -> str:
    """Classify the overall trend direction.

    Returns 'improving', 'stable', or 'declining'.
    """
    if len(trend) < 2:
        return "stable"

    first_half = trend[: len(trend) // 2]
    second_half = trend[len(trend) // 2 :]

    avg_first = (
        sum(t["voice_consistency_index"] for t in first_half) / len(first_half)
    )
    avg_second = (
        sum(t["voice_consistency_index"] for t in second_half) / len(second_half)
    )

    delta = avg_second - avg_first
    if delta > 0.05:
        return "improving"
    if delta < -0.05:
        return "declining"
    return "stable"


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyze_stroke_voice_consistency(stroke: dict[str, Any]) -> dict[str, Any]:
    """Analyze voice consistency for a single stroke."""
    text = _get_stroke_text(stroke)
    if not text:
        return _empty_metrics()

    pov = compute_pov_consistency(text)
    reg = compute_register_consistency(text)
    hed = compute_hedging_consistency(text)
    imp = compute_imperative_consistency(text)
    srs = compute_self_reference_stability(text)
    idx = compute_voice_consistency_index(pov, reg, hed, imp, srs)

    return {
        "pov_consistency": round(pov, 4),
        "register_consistency": round(reg, 4),
        "hedging_consistency": round(hed, 4),
        "imperative_consistency": round(imp, 4),
        "self_reference_stability": round(srs, 4),
        "voice_consistency_index": idx,
        "classification": classify_voice_consistency(idx),
        "strokes_analyzed": 1,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_voice_consistency_report(metrics: dict[str, Any]) -> str:
    """Format voice consistency metrics as a human-readable report."""
    if metrics["strokes_analyzed"] == 0:
        return "No strokes analyzed."

    lines = [
        f"Voice Consistency Report ({metrics['strokes_analyzed']} strokes)",
        "=" * 50,
        f"  Voice Consistency Index:     {metrics['voice_consistency_index']:.4f}"
        f"  [{metrics['classification']}]",
        f"  POV Consistency:             {metrics['pov_consistency']:.4f}"
        " (0-1, higher is more stable)",
        f"  Register Consistency:        {metrics['register_consistency']:.4f}"
        " (0-1, higher is more stable)",
        f"  Hedging Consistency:         {metrics['hedging_consistency']:.4f}"
        " (0-1, higher is more stable)",
        f"  Imperative Consistency:      {metrics['imperative_consistency']:.4f}"
        " (0-1, higher is more stable)",
        f"  Self-Reference Stability:    {metrics['self_reference_stability']:.4f}"
        " (0-1, higher is more stable)",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def analyze_voice_consistency(
    strokes_path: str | Path = "data/strokes.jsonl",
    window_size: int = 50,
) -> dict[str, Any]:
    """Analyze voice consistency from a strokes JSONL file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Voice consistency metrics.
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

    return compute_voice_consistency_metrics(strokes, window_size)


if __name__ == "__main__":
    metrics = analyze_voice_consistency()
    print(format_voice_consistency_report(metrics))
