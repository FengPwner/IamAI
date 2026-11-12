#!/usr/bin/env python3
"""writer_precision — measure how exact and unambiguous the language is.

Precision is the discipline of saying exactly what you mean.  Precise
prose names specific quantities, avoids hedge words that blur claims,
uses pronouns with clear antecedents, and replaces vague quantifiers
with concrete numbers.  Imprecise prose hedges every statement, speaks
of "many" and "various" without specifying how many or which, and
leaves the reader guessing what "it" or "this" refers to.

This module is orthogonal to the other writer metrics:

- **density** tracks *information per word*.  Dense text may still be
  imprecise — "significantly many important things happened" is dense
  (three content words) but imprecise (how many? which things? how
  significant?).  Density measures *payload*; precision measures
  *exactness*.

- **specificity** tracks *detail granularity*.  Specific text names
  concrete details.  Precision overlaps with specificity but focuses
  on *linguistic exactness* — the absence of hedges, vague quantifiers,
  and ambiguous references — rather than *detail richness*.  A text
  can be specific (lots of details) but imprecise (hedged with "maybe"
  and "somewhat"), or precise (every claim exact) but not specific
  (making exact claims about abstract concepts).

- **conviction** tracks *commitment to claims*.  Conviction measures
  whether the writer stands behind their statements.  Precision
  measures whether the statements are exact enough to stand behind.
  A convicted writer says "X is wrong"; a precise writer says "X fails
  in 73% of edge cases"; a writer with both says "X fails in 73% of
  edge cases and must be replaced."

- **clarity** (if it exists) tracks *comprehension ease*.  Clear text
  is easy to understand.  Precise text is exact in its claims.  Legal
  documents are precise but often unclear; casual explanations can be
  clear but imprecise.

- **restraint** tracks *what is omitted*.  Restraint is the discipline
  of leaving things out.  Precision is about the exactness of what
  remains.  A restrained writer says less; a precise writer says
  exactly.

Precision asks: **does the writer say exactly what they mean, or do
they blur every claim with hedges and vague references?**

Four signals are tracked:

1. **Hedge density** — the frequency of hedge words and phrases that
   soften or blur claims.  Hedges include: perhaps, maybe, possibly,
   probably, somewhat, rather, quite, fairly, basically, essentially,
   effectively, relatively, generally, typically, usually, often,
   sometimes, might, could, would, seems, appears, tends, allegedly,
   arguably, presumably, supposedly, kind of, sort of, in a way,
   to some extent, in some sense, more or less, by and large.
   Measured per 100 words.  Zero hedges is surgical precision; ten
   or more per 100 words is constant blurring.

2. **Vague quantifier rate** — how often the writer uses vague quantity
   words instead of specific numbers.  Vague quantifiers include:
   many, much, few, several, some, various, numerous, a lot, plenty,
   a number of, quite a bit, a great deal, a few, a couple of,
   a handful of, dozens, scores, hundreds of (without exact count).
   Measured per 100 words.  Occasional vague quantifiers are natural
   in informal prose; frequent use signals a writer who avoids
   commitment to specifics.

3. **Ambiguous pronoun rate** — frequency of pronouns that lack clear
   antecedents.  "It is important" (what is "it"?).  "They say that"
   (who are "they"?).  "This shows that" (what does "this" refer to?).
   Detected by counting sentence-initial pronouns (it, they, this,
   that, these, those, he, she, we) where the preceding sentence does
   not contain an obvious antecedent noun.  Measured per 100 words.
   Some ambiguous pronouns are natural in conversational prose;
   excessive use signals sloppy reference tracking.

4. **Numerical precision** — the ratio of specific numbers, dates,
   and measurements to vague approximations.  Specific: "42 users",
   "3.7 seconds", "January 15", "95% confidence".  Vague: "about",
   "approximately", "roughly", "around", "nearly", "almost",
   "close to", "in the ballpark of", "on the order of".  The ratio
   is computed as specific / (specific + vague).  A ratio of 1.0
   means every quantity is exact; 0.0 means every quantity is hedged.

From these signals a session-level **precision_index** is computed and
classified:

==============  ============================================================
class           meaning
==============  ============================================================
surgical        index >= 0.75 — every claim is exact; numbers are specific,
                hedges are rare, pronouns have clear antecedents; the prose
                reads like a technical specification or legal document
exact           0.55 <= index < 0.75 — mostly precise; occasional hedges or
                vague quantifiers but claims are generally well-defined and
                unambiguous
measured        0.35 <= index < 0.55 — moderate precision; mix of exact
                claims and hedged statements; the prose is competent but
                the writer sometimes avoids commitment
fuzzy           0.20 <= index < 0.35 — more blurring than precision; hedges
                and vague references dominate; the reader must guess at
                quantities and referents
nebulous        index < 0.20 — almost no precision; every claim is softened,
                every quantity is vague, every pronoun is ambiguous; the
                prose is a cloud of approximations
==============  ============================================================
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Word lists
# ---------------------------------------------------------------------------

# Hedge words and phrases that blur or soften claims
HEDGE_WORDS: frozenset[str] = frozenset({
    # modal hedges
    "perhaps", "maybe", "possibly", "probably", "likely", "unlikely",
    "conceivably", "plausibly",
    # degree softeners
    "somewhat", "rather", "quite", "fairly", "slightly", "mildly",
    "marginally", "moderately",
    # essentialist hedges (imply "not exactly but close enough")
    "basically", "essentially", "effectively", "virtually", "practically",
    "technically", "theoretically", "supposedly", "allegedly",
    # relativizers
    "relatively", "comparatively", "generally", "typically", "usually",
    "often", "sometimes", "frequently", "occasionally", "tends",
    # appearance hedges (suggest rather than state)
    "seems", "seemed", "appears", "appeared", "looks", "looked",
    "suggests", "suggested", "implies", "implied",
    # epistemic hedges
    "arguably", "presumably", "reportedly", "evidently", "apparently",
    "ostensibly", "seemingly",
})

# Multi-word hedge phrases
HEDGE_PHRASES: list[str] = [
    "kind of",
    "sort of",
    "in a way",
    "to some extent",
    "in some sense",
    "more or less",
    "by and large",
    "for the most part",
    "as it were",
    "so to speak",
    "if you will",
    "in a sense",
    "to a degree",
    "up to a point",
    "in some respects",
    "to some degree",
    "at least in part",
]

# Vague quantifiers — imprecise quantity words
VAGUE_QUANTIFIERS: frozenset[str] = frozenset({
    "many", "much", "few", "several", "some", "various", "numerous",
    "plenty", "countless", "myriad", "abundant", "scarce",
})

# Multi-word vague quantifier phrases
VAGUE_QUANTIFIER_PHRASES: list[str] = [
    "a lot of",
    "lots of",
    "a number of",
    "quite a bit",
    "a great deal",
    "a couple of",
    "a handful of",
    "a wide range of",
    "a variety of",
    "a whole bunch of",
    "a whole lot of",
    "any number of",
    "dozens of",
    "scores of",
    "hundreds of",
    "thousands of",
    "a significant amount of",
    "a substantial amount of",
    "a considerable amount of",
]

# Vague approximation words (used before/instead of exact numbers)
APPROXIMATION_WORDS: frozenset[str] = frozenset({
    "about", "approximately", "roughly", "around", "nearly", "almost",
    "close to", "near", "circa", "some",
})

# Multi-word approximation phrases
APPROXIMATION_PHRASES: list[str] = [
    "in the ballpark of",
    "on the order of",
    "more or less",
    "give or take",
    "or so",
    "or thereabouts",
    "in the neighborhood of",
    "in the vicinity of",
    "something like",
    "in the region of",
    "up to about",
    "as much as",
    "as many as",
    "as few as",
    "as low as",
    "as high as",
]

# Sentence-initial ambiguous pronouns
AMBIGUOUS_PRONOUNS: frozenset[str] = frozenset({
    "it", "they", "this", "that", "these", "those",
    "he", "she", "we", "them",
})

# Precision classification thresholds
PRECISION_CLASSES: list[tuple[float, str]] = [
    (0.75, "surgical"),
    (0.55, "exact"),
    (0.35, "measured"),
    (0.20, "fuzzy"),
    (0.00, "nebulous"),
]

# Weight configuration for the composite index
SIGNAL_WEIGHTS: dict[str, float] = {
    "no_hedges": 0.30,
    "no_vague_quantifiers": 0.25,
    "no_ambiguous_pronouns": 0.20,
    "numerical_precision": 0.25,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_words(text: str) -> list[str]:
    """Split text into lowercase word tokens."""
    return re.findall(r"[a-z']+", text.lower())


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using punctuation boundaries."""
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def _get_stroke_text(stroke: Any) -> str:
    """Extract text from a stroke (string or dict with 'text' key)."""
    if isinstance(stroke, str):
        return stroke
    if isinstance(stroke, dict):
        return stroke.get("text", "")
    return str(stroke)


def _first_word(sentence: str) -> str:
    """Return the first word of a sentence, lowercased."""
    words = _split_words(sentence)
    return words[0] if words else ""


# ---------------------------------------------------------------------------
# Signal 1: Hedge density
# ---------------------------------------------------------------------------


def compute_hedge_density(text: str) -> float:
    """Count hedge words and phrases per 100 words.

    Returns the number of hedges per 100 words.  Lower is more precise.
    """
    words = _split_words(text)
    if not words:
        return 0.0

    lower = text.lower()
    count = 0

    # Count single-word hedges
    for word in words:
        if word in HEDGE_WORDS:
            count += 1

    # Count multi-word hedge phrases (avoid double-counting with singles)
    for phrase in HEDGE_PHRASES:
        start = 0
        while True:
            idx = lower.find(phrase, start)
            if idx == -1:
                break
            count += 1
            start = idx + len(phrase)

    return (count / len(words)) * 100


# ---------------------------------------------------------------------------
# Signal 2: Vague quantifier rate
# ---------------------------------------------------------------------------


def compute_vague_quantifier_rate(text: str) -> float:
    """Count vague quantifiers per 100 words.

    Returns the number of vague quantifier usages per 100 words.
    Lower is more precise.
    """
    words = _split_words(text)
    if not words:
        return 0.0

    lower = text.lower()
    count = 0

    # Count single-word vague quantifiers
    for word in words:
        if word in VAGUE_QUANTIFIERS:
            count += 1

    # Count multi-word vague quantifier phrases
    for phrase in VAGUE_QUANTIFIER_PHRASES:
        start = 0
        while True:
            idx = lower.find(phrase, start)
            if idx == -1:
                break
            count += 1
            start = idx + len(phrase)

    return (count / len(words)) * 100


# ---------------------------------------------------------------------------
# Signal 3: Ambiguous pronoun rate
# ---------------------------------------------------------------------------


def _extract_nouns(sentence: str) -> set[str]:
    """Extract candidate noun words from a sentence (simple heuristic).

    Returns a set of lowercase words that are likely nouns or noun phrases.
    We use a simple heuristic: words longer than 3 characters that are
    not common function words.
    """
    # Common function words that are not nouns
    non_nouns = {
        "that", "this", "with", "from", "have", "been", "were", "will",
        "would", "could", "should", "their", "there", "what", "when",
        "where", "which", "about", "into", "through", "during", "before",
        "after", "above", "below", "between", "under", "over", "also",
        "just", "only", "even", "still", "very", "much", "more", "most",
        "than", "then", "because", "although", "while", "unless", "until",
        "since", "however", "therefore", "moreover", "furthermore",
        "perhaps", "maybe", "probably", "possibly",
    }
    words = _split_words(sentence)
    return {w for w in words if len(w) > 3 and w not in non_nouns}


def compute_ambiguous_pronoun_rate(text: str) -> float:
    """Count sentence-initial ambiguous pronouns per 100 words.

    A pronoun is considered ambiguous if the preceding sentence does not
    contain an obvious antecedent noun.  This is a heuristic — it catches
    the worst offenders (sentences starting with "It" or "This" with no
    prior context) rather than performing full coreference resolution.

    Returns the number of ambiguous pronouns per 100 words.
    """
    sentences = _split_sentences(text)
    words = _split_words(text)
    if not words or not sentences:
        return 0.0

    ambiguous_count = 0

    for i, sentence in enumerate(sentences):
        first = _first_word(sentence)
        if first not in AMBIGUOUS_PRONOUNS:
            continue

        # Check if preceding sentence has a potential antecedent
        if i == 0:
            # First sentence with a pronoun opener — always ambiguous
            ambiguous_count += 1
            continue

        prev_nouns = _extract_nouns(sentences[i - 1])
        if not prev_nouns:
            # No nouns in preceding sentence to serve as antecedent
            ambiguous_count += 1
        # If there are nouns in the previous sentence, we assume the
        # pronoun has a valid antecedent (heuristic — not perfect but
        # good enough for a precision signal)

    return (ambiguous_count / len(words)) * 100


# ---------------------------------------------------------------------------
# Signal 4: Numerical precision
# ---------------------------------------------------------------------------

# Pattern for specific numbers (digits, decimals, percentages, dates)
_SPECIFIC_NUMBER_RE = re.compile(
    r'\b\d+(?:\.\d+)?(?:%|st|nd|rd|th)?\b'  # 42, 3.7, 95%, 1st
    r'|\b\d{4}\b'                             # years: 2024
    r'|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b'  # dates: 1/15, 01-15-2024
)


def _count_specific_numbers(text: str) -> int:
    """Count specific numerical references in text."""
    return len(_SPECIFIC_NUMBER_RE.findall(text))


def _count_approximations(text: str) -> int:
    """Count vague approximation words and phrases in text."""
    lower = text.lower()
    words = _split_words(text)
    count = 0

    # Single-word approximations
    for word in words:
        if word in APPROXIMATION_WORDS:
            count += 1

    # Multi-word approximation phrases
    for phrase in APPROXIMATION_PHRASES:
        start = 0
        while True:
            idx = lower.find(phrase, start)
            if idx == -1:
                break
            count += 1
            start = idx + len(phrase)

    return count


def compute_numerical_precision(text: str) -> float:
    """Compute the ratio of specific numbers to total numerical references.

    Returns a value between 0.0 and 1.0.  1.0 means every number is
    exact; 0.0 means every number is approximated.  If there are no
    numerical references at all, returns 0.5 (neutral — the text simply
    doesn't deal in numbers).
    """
    specific = _count_specific_numbers(text)
    vague = _count_approximations(text)

    total = specific + vague
    if total == 0:
        # No numerical content — neutral score
        return 0.5

    return specific / total


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyze_stroke_precision(stroke: Any) -> dict[str, Any]:
    """Analyze precision for a single stroke.

    Returns
    -------
    dict
        Keys: hedge_density, vague_quantifier_rate, ambiguous_pronoun_rate,
        numerical_precision, precision_index, precision_class.
    """
    text = _get_stroke_text(stroke)
    if not text.strip():
        return _empty_stroke_metrics()

    hedges = compute_hedge_density(text)
    vague = compute_vague_quantifier_rate(text)
    pronouns = compute_ambiguous_pronoun_rate(text)
    num_precision = compute_numerical_precision(text)

    # Normalize each signal to 0-1 (higher = more precise)
    # hedges: invert (low hedges = high precision), typical 0-10 per 100w
    no_hedges = max(0.0, 1.0 - hedges / 10.0)
    # vague quantifiers: invert, typical 0-5 per 100w
    no_vague = max(0.0, 1.0 - vague / 5.0)
    # ambiguous pronouns: invert, typical 0-3 per 100w
    no_pronouns = max(0.0, 1.0 - pronouns / 3.0)
    # numerical precision is already 0-1
    precision_score = num_precision

    index = (
        SIGNAL_WEIGHTS["no_hedges"] * no_hedges
        + SIGNAL_WEIGHTS["no_vague_quantifiers"] * no_vague
        + SIGNAL_WEIGHTS["no_ambiguous_pronouns"] * no_pronouns
        + SIGNAL_WEIGHTS["numerical_precision"] * precision_score
    )

    precision_class = _classify_precision(index)

    return {
        "hedge_density": round(hedges, 4),
        "vague_quantifier_rate": round(vague, 4),
        "ambiguous_pronoun_rate": round(pronouns, 4),
        "numerical_precision": round(num_precision, 4),
        "precision_index": round(index, 4),
        "precision_class": precision_class,
    }


def _empty_stroke_metrics() -> dict[str, Any]:
    """Return empty metrics for a blank stroke."""
    return {
        "hedge_density": 0.0,
        "vague_quantifier_rate": 0.0,
        "ambiguous_pronoun_rate": 0.0,
        "numerical_precision": 0.0,
        "precision_index": 0.0,
        "precision_class": "nebulous",
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify_precision(index: float) -> str:
    """Map a precision_index to its class label."""
    for threshold, label in PRECISION_CLASSES:
        if index >= threshold:
            return label
    return "nebulous"


# ---------------------------------------------------------------------------
# Session-level aggregation
# ---------------------------------------------------------------------------


def _empty_metrics() -> dict[str, Any]:
    """Return zeroed-out session metrics when no data is available."""
    return {
        "strokes_analyzed": 0,
        "total_words": 0,
        "precision_index": 0.0,
        "precision_class": "nebulous",
        "hedge_density": 0.0,
        "vague_quantifier_rate": 0.0,
        "ambiguous_pronoun_rate": 0.0,
        "numerical_precision": 0.0,
        "class_distribution": {},
        "stroke_indices": [],
    }


def compute_precision_metrics(
    strokes: list[Any],
    window_size: int = 50,
) -> dict[str, Any]:
    """Compute aggregated precision metrics over a window of strokes.

    Parameters
    ----------
    strokes : list
        List of strokes (strings or dicts with 'text' key).
    window_size : int
        Maximum number of recent strokes to analyze.

    Returns
    -------
    dict
        Aggregated precision metrics.
    """
    if not strokes:
        return _empty_metrics()

    recent = strokes[-window_size:]
    analyses: list[dict[str, Any]] = []
    total_words = 0

    for stroke in recent:
        text = _get_stroke_text(stroke)
        if not text.strip():
            continue
        analysis = analyze_stroke_precision(stroke)
        analyses.append(analysis)
        total_words += len(_split_words(text))

    if not analyses:
        return _empty_metrics()

    n = len(analyses)
    avg_hedges = sum(a["hedge_density"] for a in analyses) / n
    avg_vague = sum(a["vague_quantifier_rate"] for a in analyses) / n
    avg_pronouns = sum(a["ambiguous_pronoun_rate"] for a in analyses) / n
    avg_num_precision = sum(a["numerical_precision"] for a in analyses) / n
    avg_index = sum(a["precision_index"] for a in analyses) / n

    class_dist: dict[str, int] = {}
    for a in analyses:
        cls = a["precision_class"]
        class_dist[cls] = class_dist.get(cls, 0) + 1

    return {
        "strokes_analyzed": n,
        "total_words": total_words,
        "precision_index": round(avg_index, 4),
        "precision_class": _classify_precision(avg_index),
        "hedge_density": round(avg_hedges, 4),
        "vague_quantifier_rate": round(avg_vague, 4),
        "ambiguous_pronoun_rate": round(avg_pronouns, 4),
        "numerical_precision": round(avg_num_precision, 4),
        "class_distribution": class_dist,
        "stroke_indices": [a["precision_index"] for a in analyses],
    }


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


def compute_precision_trend(
    strokes: list[Any],
    window_size: int = 20,
) -> dict[str, Any]:
    """Compute the trend of precision over recent strokes.

    Compares the average precision_index of the first half of the window
    against the second half.

    Returns
    -------
    dict
        Keys: early_index, late_index, delta, trend.
    """
    if len(strokes) < 4:
        return {"early_index": 0.0, "late_index": 0.0, "delta": 0.0, "trend": "stable"}

    recent = strokes[-window_size:]
    mid = len(recent) // 2

    early_strokes = recent[:mid]
    late_strokes = recent[mid:]

    early_analyses = [
        analyze_stroke_precision(s) for s in early_strokes
        if _get_stroke_text(s).strip()
    ]
    late_analyses = [
        analyze_stroke_precision(s) for s in late_strokes
        if _get_stroke_text(s).strip()
    ]

    if not early_analyses or not late_analyses:
        return {"early_index": 0.0, "late_index": 0.0, "delta": 0.0, "trend": "stable"}

    early_avg = sum(a["precision_index"] for a in early_analyses) / len(early_analyses)
    late_avg = sum(a["precision_index"] for a in late_analyses) / len(late_analyses)
    delta = late_avg - early_avg

    return {
        "early_index": round(early_avg, 4),
        "late_index": round(late_avg, 4),
        "delta": round(delta, 4),
        "trend": classify_trend(delta),
    }


def classify_trend(delta: float) -> str:
    """Classify a precision trend based on the delta."""
    if delta > 0.05:
        return "sharpening"
    elif delta < -0.05:
        return "blurring"
    else:
        return "stable"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_precision_report(metrics: dict[str, Any]) -> str:
    """Format precision metrics as a human-readable report."""
    lines = [
        "=== Writer Precision ===",
        f"Strokes analyzed:          {metrics['strokes_analyzed']}",
        f"Total words:               {metrics['total_words']}",
        f"Precision index:           {metrics['precision_index']:.4f} ({metrics['precision_class']})",
        "",
        f"Hedge density:             {metrics['hedge_density']:.4f}/100w",
        f"Vague quantifier rate:     {metrics['vague_quantifier_rate']:.4f}/100w",
        f"Ambiguous pronoun rate:    {metrics['ambiguous_pronoun_rate']:.4f}/100w",
        f"Numerical precision:       {metrics['numerical_precision']:.4f}",
        "",
    ]

    dist = metrics.get("class_distribution", {})
    if dist:
        lines.append("Class distribution:")
        for cls in ("surgical", "exact", "measured", "fuzzy", "nebulous"):
            count = dist.get(cls, 0)
            if count:
                lines.append(f"  {cls:14s} {count}")
        lines.append("")

    pc = metrics["precision_class"]
    lines.append("Interpretation:")
    if pc == "surgical":
        lines.append("  Every claim is exact. Numbers are specific, hedges are")
        lines.append("  rare, pronouns have clear antecedents.")
    elif pc == "exact":
        lines.append("  Mostly precise. Occasional hedges or vague quantifiers")
        lines.append("  but claims are generally well-defined.")
    elif pc == "measured":
        lines.append("  Moderate precision. Mix of exact claims and hedged")
        lines.append("  statements; the writer sometimes avoids commitment.")
    elif pc == "fuzzy":
        lines.append("  More blurring than precision. Hedges and vague references")
        lines.append("  dominate; the reader must guess at quantities.")
    else:
        lines.append("  Almost no precision. Every claim is softened, every")
        lines.append("  quantity is vague, every pronoun is ambiguous.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone analysis (reads from strokes.jsonl)
# ---------------------------------------------------------------------------


def analyze_precision(
    strokes_path: str = "data/strokes.jsonl",
    window_size: int = 50,
) -> dict[str, Any]:
    """Analyze precision from the strokes file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Precision metrics.
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

    return compute_precision_metrics(strokes, window_size)


if __name__ == "__main__":
    metrics = analyze_precision()
    print(format_precision_report(metrics))
