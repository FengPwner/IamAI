#!/usr/bin/env python3
"""writer_specificity — measure whether writing uses concrete, precise language.

Specificity is about *concreteness*.  Specific prose names the thing, gives
the number, points to the place.  Vague prose gestures: "some people",
"various reasons", "a lot of", "things like that".

This module is orthogonal to the other writer metrics:

- **readability** tracks whether prose is *easy to parse*.  A text can be
  readable (short sentences, simple words) while being vague ("many things
  happen").  Readability is about effort; specificity is about precision.

- **concision** tracks whether prose uses *more words than needed*.  A text
  can be concise while being vague ("problems occurred" — two words, zero
  information).  Concision is about economy; specificity is about whether
  the words chosen carry concrete meaning.

- **signal_clarity** tracks whether strokes are *substantively unique*.
  A writer can produce unique but vague strokes (each one gestures at
  something different without naming it).  Clarity is about uniqueness;
  specificity is about concreteness.

- **vocabulary_richness** tracks *diversity* of word choice.  A text can
  use rich vocabulary while being vague (ornate hedging) or use simple
  vocabulary while being specific (plain numbers, plain names).

- **grounding_density** tracks whether claims are *anchored in evidence*.
  Grounding asks "is there a source?"  Specificity asks "is there a
  *what*?" — a number, a name, a date, a place.  Grounded but vague text
  cites a study without saying what it found.

- **prose_rhythm** tracks *variation* in sentence length.  Rhythm is
  structural; specificity is semantic.

Specificity asks: **does the reader finish the sentence knowing more than
before, or just feeling like they do?**

Five signals are tracked:

1. **Vagueness marker density** — frequency of recognized vague words and
   phrases per hundred words.  Includes: hedging quantifiers ("some",
   "various", "certain", "several", "many", "numerous", "a number of"),
   placeholder nouns ("things", "stuff", "aspects", "factors", "issues",
   "matters", "elements"), trailing hedges ("etc.", "and so on", "and
   the like", "or something", "or whatever"), and degree vagueness
   ("quite", "fairly", "rather", "somewhat", "a bit", "kind of",
   "sort of", "pretty much").

2. **Numerical precision** — whether quantities are expressed as numbers
   or approximated with words.  "47 tests failed" is specific; "many
   tests failed" is vague.  Measured as the ratio of digit-expressed
   quantities to total quantity-expressing contexts.

3. **Named entity density** — frequency of proper nouns and specific
   referents per hundred words.  "Python 3.12" is specific; "a programming
   language" is vague.  Detected via capitalization patterns (words
   starting with uppercase mid-sentence, excluding sentence starters).

4. **Concrete word ratio** — fraction of nouns and adjectives that refer
   to perceptible, tangible things.  "Keyboard", "server", "log file"
   are concrete; "concept", "approach", "methodology" are abstract.
   Uses a curated list of abstract nouns as the inverse signal.

5. **Temporal specificity** — whether time references are precise ("at
   14:32 on October 3rd") or vague ("recently", "a while ago", "at some
   point", "in the future").

The **specificity_index** is computed as a weighted composite:

    index = (1 - vagueness_density_norm) * 0.30
          + numerical_precision       * 0.25
          + named_entity_density_norm * 0.20
          + concrete_word_ratio       * 0.15
          + temporal_specificity      * 0.10

Classified as:

- **precise** (≥ 0.80): writing names things, gives numbers, points to
  specific times and places.
- **grounded** (≥ 0.60): mostly concrete with occasional vague patches.
- **serviceable** (≥ 0.40): mixed — some specifics, some hand-waving.
- **vague** (≥ 0.20): mostly abstract, hedged, or gestured-at.
- **foggy** (< 0.20): almost no concrete referents; the reader finishes
  knowing roughly what the writer felt, not what they meant.
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

VAGUENESS_MARKERS: list[str] = [
    # Hedging quantifiers
    "some", "various", "certain", "several", "many", "numerous",
    "a number of", "a lot of", "lots of", "a great deal of",
    "a fair amount of", "quite a few", "a handful of",
    # Placeholder nouns
    "things", "stuff", "aspects", "factors", "issues", "matters",
    "elements", "components", "considerations", "circumstances",
    "situations", "conditions", "phenomena", "entities",
    # Trailing hedges
    "etc", "etc.", "and so on", "and the like", "or something",
    "or whatever", "or similar", "and such", "and whatnot",
    # Degree vagueness
    "quite", "fairly", "rather", "somewhat", "a bit", "kind of",
    "sort of", "pretty much", "more or less", "to some extent",
    "in some way", "in some sense", "to a degree",
]

ABSTRACT_NOUNS: list[str] = [
    "concept", "approach", "methodology", "framework", "paradigm",
    "perspective", "dimension", "aspect", "facet", "notion",
    "idea", "theory", "principle", "phenomenon", "process",
    "strategy", "mechanism", "mechanism", "dynamic", "tendency",
    "implication", "ramification", "consideration", "observation",
    "realization", "understanding", "awareness", "insight",
    "capability", "functionality", "potentiality", "possibility",
    "effectiveness", "efficiency", "reliability", "availability",
    "complexity", "simplicity", "difficulty", "opportunity",
    "responsibility", "accountability", "sustainability",
    "transparency", "significance", "relevance", "importance",
]

VAGUE_TIME_REFS: list[str] = [
    "recently", "lately", "a while ago", "at some point",
    "in the future", "in the past", "eventually", "someday",
    "from time to time", "now and then", "occasionally",
    "sometimes", "often", "frequently", "regularly",
    "at one point", "back in the day", "these days",
    "in recent times", "going forward", "moving forward",
]

PRECISE_TIME_PATTERN = re.compile(
    r"\b\d{1,2}:\d{2}\b"            # HH:MM
    r"|\b\d{4}-\d{2}-\d{2}\b"       # YYYY-MM-DD
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b" # M/D/Y or D/M/Y
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r"\s+\d{1,2}(?:st|nd|rd|th)?\b" # Month Day
    r"|\b\d{1,2}(?:st|nd|rd|th)\s+"
    r"(?:of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b"
    r"|\bq[1-4]\s*\d{4}\b"          # Q1 2026
    r"|\b\d{4}\b",                    # standalone year
    re.IGNORECASE,
)

NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?(?:%|k|m|b|ms|s|mb|gb|tb)?\b")

QUANTITY_WORD_PATTERN = re.compile(
    r"\b(?:many|few|several|numerous|countless|a lot of|lots of|"
    r"a number of|a great deal of|a fair amount of|quite a few|"
    r"most|some|all|no)\b",
    re.IGNORECASE,
)

# Note: proper noun detection uses sentence-splitting logic in
# compute_named_entity_density() rather than a single regex, because
# Python's re module requires fixed-width lookbehinds.


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


def _count_sentences(text: str) -> int:
    """Approximate sentence count."""
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    return max(len(sentences), 1)


# ---------------------------------------------------------------------------
# Signal 1: Vagueness marker density
# ---------------------------------------------------------------------------


def compute_vagueness_density(text: str) -> float:
    """Vague markers per hundred words.  Lower is more specific.

    Returns a value ≥ 0.  Typical range: 0–15.
    """
    words = _split_words(text)
    if not words:
        return 0.0

    text_lower = text.lower()
    hits = 0
    for marker in VAGUENESS_MARKERS:
        # Count occurrences of the marker as a whole word/phrase.
        pattern = r"\b" + re.escape(marker) + r"\b"
        hits += len(re.findall(pattern, text_lower))

    return (hits / len(words)) * 100


def _score_vagueness(density: float) -> float:
    """Convert density to 0–1 score (1 = no vagueness).

    Uses exponential decay: score = exp(-density / 5).
    At density 0 → 1.0, density 5 → ~0.37, density 10 → ~0.13.
    """
    return math.exp(-density / 5.0)


# ---------------------------------------------------------------------------
# Signal 2: Numerical precision
# ---------------------------------------------------------------------------


def compute_numerical_precision(text: str) -> float:
    """Ratio of digit-expressed quantities to total quantity contexts.

    Returns 0–1.  Higher means quantities are expressed as numbers,
    not vague words.
    """
    number_hits = len(NUMBER_PATTERN.findall(text))
    quantity_words = len(QUANTITY_WORD_PATTERN.findall(text))
    total = number_hits + quantity_words
    if total == 0:
        return 0.5  # neutral when no quantities at all
    return number_hits / total


# ---------------------------------------------------------------------------
# Signal 3: Named entity density
# ---------------------------------------------------------------------------


def compute_named_entity_density(text: str) -> float:
    """Approximate proper noun density as a proxy for named references.

    Detects capitalized words mid-sentence (not at sentence start).
    Returns entities per hundred words.  Higher is more specific.
    """
    words = _split_words(text)
    if not words:
        return 0.0

    # Split into sentences and look for mid-sentence capitals.
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    proper_nouns = 0
    for sent in sentences:
        # Skip the first word (expected to be capitalized).
        tokens = sent.split()
        if len(tokens) < 2:
            continue
        for token in tokens[1:]:
            # Must start uppercase, rest lowercase, at least 2 chars total.
            if (
                len(token) >= 2
                and token[0].isupper()
                and token[1:].isalpha()
                and token[1:].islower()
            ):
                proper_nouns += 1

    return (proper_nouns / len(words)) * 100


def _score_entity_density(density: float) -> float:
    """Convert entity density to 0–1 score (1 = many named references).

    Uses saturation curve: score = 1 - exp(-density / 3).
    At density 0 → 0, density 3 → ~0.63, density 6 → ~0.86.
    """
    return 1.0 - math.exp(-density / 3.0)


# ---------------------------------------------------------------------------
# Signal 4: Concrete word ratio
# ---------------------------------------------------------------------------


def compute_concrete_word_ratio(text: str) -> float:
    """Fraction of nouns that are concrete (not abstract).

    Uses a curated list of abstract nouns.  Returns 0–1; higher means
    more concrete language.
    """
    words = _split_words(text)
    if not words:
        return 0.5

    abstract_set = set(ABSTRACT_NOUNS)
    # Count abstract nouns found in text.
    abstract_hits = sum(1 for w in words if w in abstract_set)
    total_nouns_approx = max(len(words) // 4, 1)  # rough noun estimate

    # Concrete ratio = 1 - (abstract / estimated_nouns).
    abstract_ratio = min(abstract_hits / total_nouns_approx, 1.0)
    return 1.0 - abstract_ratio


# ---------------------------------------------------------------------------
# Signal 5: Temporal specificity
# ---------------------------------------------------------------------------


def compute_temporal_specificity(text: str) -> float:
    """Ratio of precise time references to total time references.

    Returns 0–1.  Higher means time is expressed with specific dates/times
    rather than vague references.
    """
    precise_hits = len(PRECISE_TIME_PATTERN.findall(text))

    text_lower = text.lower()
    vague_hits = 0
    for ref in VAGUE_TIME_REFS:
        vague_hits += len(re.findall(r"\b" + re.escape(ref) + r"\b", text_lower))

    total = precise_hits + vague_hits
    if total == 0:
        return 0.5  # neutral when no time references
    return precise_hits / total


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


def compute_specificity_index(
    vagueness_density: float,
    numerical_precision: float,
    named_entity_density: float,
    concrete_word_ratio: float,
    temporal_specificity: float,
) -> float:
    """Weighted composite specificity index, 0–1.

    Weights:
    - vagueness (inverted): 30%
    - numerical precision:  25%
    - named entity density: 20%
    - concrete word ratio:  15%
    - temporal specificity: 10%
    """
    vag_score = _score_vagueness(vagueness_density)
    entity_score = _score_entity_density(named_entity_density)

    index = (
        vag_score * 0.30
        + numerical_precision * 0.25
        + entity_score * 0.20
        + concrete_word_ratio * 0.15
        + temporal_specificity * 0.10
    )
    return round(index, 4)


def classify_specificity(index: float) -> str:
    """Classify specificity index into a human-readable label."""
    if index >= 0.80:
        return "precise"
    if index >= 0.60:
        return "grounded"
    if index >= 0.40:
        return "serviceable"
    if index >= 0.20:
        return "vague"
    return "foggy"


def compute_specificity_metrics(
    strokes: list[dict[str, Any]], window_size: int = 50
) -> dict[str, Any]:
    """Compute specificity metrics over a window of recent strokes.

    Parameters
    ----------
    strokes : list of stroke dicts
        Stroke records from strokes.jsonl.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict with keys:
        vagueness_density, numerical_precision, named_entity_density,
        concrete_word_ratio, temporal_specificity, specificity_index,
        classification, strokes_analyzed.
    """
    recent = strokes[-window_size:] if strokes else []
    texts = [_get_stroke_text(s) for s in recent if _get_stroke_text(s)]

    if not texts:
        return _empty_metrics()

    combined = " ".join(texts)

    vag = compute_vagueness_density(combined)
    num = compute_numerical_precision(combined)
    ent = compute_named_entity_density(combined)
    con = compute_concrete_word_ratio(combined)
    tem = compute_temporal_specificity(combined)
    idx = compute_specificity_index(vag, num, ent, con, tem)

    return {
        "vagueness_density": round(vag, 4),
        "numerical_precision": round(num, 4),
        "named_entity_density": round(ent, 4),
        "concrete_word_ratio": round(con, 4),
        "temporal_specificity": round(tem, 4),
        "specificity_index": idx,
        "classification": classify_specificity(idx),
        "strokes_analyzed": len(texts),
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "vagueness_density": 0.0,
        "numerical_precision": 0.5,
        "named_entity_density": 0.0,
        "concrete_word_ratio": 0.5,
        "temporal_specificity": 0.5,
        "specificity_index": 0.5,
        "classification": "serviceable",
        "strokes_analyzed": 0,
    }


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


def compute_specificity_trend(
    strokes: list[dict[str, Any]], window_size: int = 50
) -> list[dict[str, Any]]:
    """Compute specificity index over sliding windows.

    Returns a list of dicts with 'window_start', 'window_end',
    'specificity_index', 'classification'.
    """
    if len(strokes) < window_size:
        metrics = compute_specificity_metrics(strokes, window_size)
        return [
            {
                "window_start": 0,
                "window_end": len(strokes),
                "specificity_index": metrics["specificity_index"],
                "classification": metrics["classification"],
            }
        ]

    trends = []
    step = max(window_size // 2, 1)
    for start in range(0, len(strokes) - window_size + 1, step):
        window = strokes[start : start + window_size]
        metrics = compute_specificity_metrics(window, window_size)
        trends.append(
            {
                "window_start": start,
                "window_end": start + window_size,
                "specificity_index": metrics["specificity_index"],
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

    avg_first = sum(t["specificity_index"] for t in first_half) / len(first_half)
    avg_second = sum(t["specificity_index"] for t in second_half) / len(second_half)

    delta = avg_second - avg_first
    if delta > 0.05:
        return "improving"
    if delta < -0.05:
        return "declining"
    return "stable"


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyze_stroke_specificity(stroke: dict[str, Any]) -> dict[str, Any]:
    """Analyze specificity for a single stroke."""
    text = _get_stroke_text(stroke)
    if not text:
        return _empty_metrics()

    vag = compute_vagueness_density(text)
    num = compute_numerical_precision(text)
    ent = compute_named_entity_density(text)
    con = compute_concrete_word_ratio(text)
    tem = compute_temporal_specificity(text)
    idx = compute_specificity_index(vag, num, ent, con, tem)

    return {
        "vagueness_density": round(vag, 4),
        "numerical_precision": round(num, 4),
        "named_entity_density": round(ent, 4),
        "concrete_word_ratio": round(con, 4),
        "temporal_specificity": round(tem, 4),
        "specificity_index": idx,
        "classification": classify_specificity(idx),
        "strokes_analyzed": 1,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_specificity_report(metrics: dict[str, Any]) -> str:
    """Format specificity metrics as a human-readable report."""
    if metrics["strokes_analyzed"] == 0:
        return "No strokes analyzed."

    lines = [
        f"Specificity Report ({metrics['strokes_analyzed']} strokes)",
        "=" * 50,
        f"  Specificity Index:    {metrics['specificity_index']:.4f}"
        f"  [{metrics['classification']}]",
        f"  Vagueness Density:    {metrics['vagueness_density']:.4f}"
        " (per 100 words, lower is better)",
        f"  Numerical Precision:  {metrics['numerical_precision']:.4f}"
        " (0–1, higher is better)",
        f"  Named Entity Density: {metrics['named_entity_density']:.4f}"
        " (per 100 words, higher is better)",
        f"  Concrete Word Ratio:  {metrics['concrete_word_ratio']:.4f}"
        " (0–1, higher is better)",
        f"  Temporal Specificity: {metrics['temporal_specificity']:.4f}"
        " (0–1, higher is better)",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def analyze_specificity(
    strokes_path: str | Path = "data/strokes.jsonl",
    window_size: int = 50,
) -> dict[str, Any]:
    """Analyze specificity from a strokes JSONL file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Specificity metrics.
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

    return compute_specificity_metrics(strokes, window_size)


if __name__ == "__main__":
    metrics = analyze_specificity()
    print(format_specificity_report(metrics))
