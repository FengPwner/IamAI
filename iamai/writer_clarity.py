#!/usr/bin/env python3
"""writer_clarity — measure how easily a reader can parse structural meaning.

Clarity is the property of *unambiguous structure*.  Clear prose arranges
words so that the grammatical relationships between them are immediately
obvious.  Unclear prose forces the reader to re-read, re-parse, or guess
which noun a modifier attaches to, what a pronoun refers to, or where a
clause boundary falls.

This module is orthogonal to the other writer metrics:

- **precision** tracks *exactness of claims*.  Precise text names specific
  quantities and avoids hedge words.  Clear text has unambiguous structure.
  A sentence can be precise ("approximately 42% of users experienced some
  improvement") but structurally unclear (which users? what kind of
  improvement?).  Precision measures *what* is said; clarity measures
  *how parseable* the structure is.

- **readability** tracks *overall ease of reading*, typically via sentence
  length and word difficulty.  A text can be readable (short sentences,
  simple words) while being structurally ambiguous ("I saw the man with
  the telescope" — who has the telescope?).  Readability measures surface
  difficulty; clarity measures structural ambiguity.

- **concision** tracks *word economy*.  Concise text uses the fewest
  words needed.  A text can be concise ("flying planes can be dangerous")
  while being maximally ambiguous (are the planes flying, or is flying
  them dangerous?).  Concision measures length efficiency; clarity
  measures parse certainty.

- **coherence** tracks *logical flow between sentences*.  Coherent text
  has ideas that connect logically.  Clear text has unambiguous structure
  within each sentence.  A text can be coherent (ideas flow) while
  individual sentences are structurally ambiguous.

- **cohesion** tracks *grammatical links between sentences* (reference
  chains, conjunctions).  Cohesion measures how sentences connect; clarity
  measures how parseable each sentence is in isolation.

Clarity asks: **can the reader parse the structural meaning on first
reading, or must they re-read and guess?**

Four signals are tracked:

1. **Attachment ambiguity rate** — frequency of prepositional phrases and
   modifiers that could attach to multiple heads.  "I saw the man with the
   telescope" (does "with the telescope" modify "saw" or "the man"?).
   "The report of the committee on the budget" (does "on the budget"
   modify "report" or "committee"?).  Measured per 100 words.  Detected
   via patterns: consecutive prepositional phrases, dangling participles,
   ambiguous relative clauses.

2. **Garden path rate** — frequency of sentences that force the reader to
   re-parse after encountering a disambiguating word.  "The old man the
   boat" (initial parse: old man is a noun phrase; correction: "man" is
   a verb).  "The horse raced past the barn fell" (reduced relative
   clause forces re-read).  Measured per 100 sentences.  Detected via
   known garden-path patterns: noun-verb ambiguity at sentence start,
   reduced relative clauses, late disambiguation.

3. **Pronoun-antecedent distance** — average word distance between
   pronouns and their nearest candidate antecedent.  "The system
   processed the request and then it crashed" ("it" is 5 words from
   "system").  "After the manager reviewed the proposal that the team
   had submitted, she approved it" ("she" is 12 words from "manager").
   Measured as mean word distance.  Closer pronouns are easier to resolve;
   distant pronouns force the reader to search back through the text.

4. **Nested clause depth** — maximum depth of clause embedding within
   sentences.  "The cat sat" (depth 1).  "The cat that the dog chased
   sat" (depth 2).  "The cat that the dog that the rat bit chased sat"
   (depth 3).  Measured as mean and max depth per sentence.  Deeper
   nesting requires the reader to hold more context in working memory;
   depth > 2 significantly increases parsing difficulty.

The clarity_index is computed as a weighted composite:
- attachment ambiguity: 0.30 (most common structural ambiguity)
- garden path rate: 0.20 (less frequent but high impact)
- pronoun distance: 0.25 (affects comprehension on every sentence)
- nested depth: 0.25 (working memory load)

Classification:
- crystalline (0.8–1.0): structure is immediately parseable
- lucid (0.6–0.8): minor ambiguities, easily resolved
- serviceable (0.4–0.6): some re-reading needed
- murky (0.2–0.4): frequent structural confusion
- opaque (0.0–0.2): reader must constantly re-parse
"""

from __future__ import annotations

import re
import math
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Prepositions that commonly introduce attachment-ambiguous phrases
PREPOSITIONS = {
    "with", "of", "on", "in", "at", "to", "for", "from", "by",
    "about", "into", "through", "after", "before", "between",
    "under", "over", "above", "below", "near", "beside", "behind",
    "around", "across", "along", "against", "among", "upon",
    "within", "without", "beyond", "beneath",
}

# Pronouns that require antecedent resolution
ANAPHORIC_PRONOUNS = {
    "it", "its", "they", "them", "their", "theirs",
    "he", "him", "his", "she", "her", "hers",
    "this", "that", "these", "those",
    "which", "who", "whom",
}

# Relative pronouns that introduce embedded clauses
RELATIVE_PRONOUNS = {"that", "which", "who", "whom", "whose", "where", "when"}

# Subordinating conjunctions that introduce embedded clauses
SUBORDINATORS = {
    "because", "although", "though", "while", "whereas", "since",
    "if", "unless", "until", "before", "after", "when", "whenever",
    "where", "wherever", "whether", "even", "provided", "assuming",
    "given", "considering",
}

# Garden path trigger patterns (simplified detection)
GARDEN_PATH_PATTERNS = [
    # "The old man the boats" — adjective-noun that could be noun-verb
    # Matches: the [adj-like] [verb-like] the — where the second word
    # could be parsed as a noun (initial misparse) or verb (correct parse)
    re.compile(r'\bthe\s+\w+ed?\s+\w+\s+the\b', re.IGNORECASE),
    # Broader garden path: "The [adj] [noun/verb] the [noun]" — any
    # structure where the first noun-slot could be a verb
    re.compile(r'\bthe\s+(?:old|young|rich|poor|fat|thin)\s+(?:man|men|woman|women)\s+the\b', re.IGNORECASE),
    # Reduced relative: "The horse raced past the barn fell"
    re.compile(r'\bthe\s+\w+\s+\w+ed\s+past\b', re.IGNORECASE),
    # "The cotton clothing is made of" — late prepositional stranding
    re.compile(r'\bthe\s+\w+\s+\w+\s+is\s+made\s+of\b', re.IGNORECASE),
]

# Ambiguous PP attachment patterns
PP_ATTACHMENT_PATTERNS = [
    # "N1 of N2 Prep N3" — does Prep attach to N1 or N2?
    re.compile(
        r'\b\w+\s+of\s+\w+\s+(?:with|on|in|at|for|from|by|about|into|through)\s+\w+',
        re.IGNORECASE,
    ),
    # "V N1 Prep N2" where Prep could modify V or N1
    re.compile(
        r'\b\w+ed?\s+\w+\s+(?:with|on|in|at|near|behind|beside)\s+(?:the|a|an)\s+\w+',
        re.IGNORECASE,
    ),
    # Consecutive PPs: "the report of the committee on the budget"
    re.compile(
        r'\b\w+\s+(?:of|from|by)\s+(?:the|a|an)\s+\w+\s+(?:on|in|with|at|for|about)\s+(?:the|a|an)\s+\w+',
        re.IGNORECASE,
    ),
]

# Signal weights for composite index
SIGNAL_WEIGHTS = {
    "attachment": 0.30,
    "garden_path": 0.20,
    "pronoun_distance": 0.25,
    "nested_depth": 0.25,
}

# Classification boundaries
CLARITY_CLASSES = [
    (0.8, "crystalline"),
    (0.6, "lucid"),
    (0.4, "serviceable"),
    (0.2, "murky"),
    (0.0, "opaque"),
]


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _split_words(text: str) -> list[str]:
    """Split text into lowercase words, stripping punctuation."""
    return re.findall(r"[a-z']+", text.lower())


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences on . ! ? boundaries."""
    parts = re.split(r'[.!?]+', text)
    return [s.strip() for s in parts if s.strip()]


def _get_stroke_text(stroke: Any) -> str:
    """Extract text content from a stroke (dict, str, or object)."""
    if isinstance(stroke, str):
        return stroke
    if isinstance(stroke, dict):
        return stroke.get("text", stroke.get("content", ""))
    return str(stroke) if stroke else ""


# ---------------------------------------------------------------------------
# Signal 1: Attachment ambiguity rate
# ---------------------------------------------------------------------------

def count_attachment_ambiguities(text: str) -> int:
    """Count potential PP-attachment ambiguities in text.

    Detects patterns where a prepositional phrase could modify either
    the preceding noun or the verb (or another noun in a chain).
    """
    count = 0
    for pattern in PP_ATTACHMENT_PATTERNS:
        count += len(pattern.findall(text))
    return count


def compute_attachment_ambiguity_rate(text: str) -> float:
    """Attachment ambiguities per 100 words.

    Returns a score from 0.0 (no ambiguities) to 1.0 (frequent).
    Raw rate is ambiguities per 100 words, normalized: 0 → 1.0,
    2+ per 100 words → 0.0.
    """
    words = _split_words(text)
    if len(words) < 5:
        return 1.0
    raw = count_attachment_ambiguities(text)
    rate_per_100 = raw / (len(words) / 100)
    # Normalize: 0 per 100 words → 1.0 score; 2+ per 100 → 0.0
    score = max(0.0, 1.0 - rate_per_100 / 2.0)
    return round(score, 4)


# ---------------------------------------------------------------------------
# Signal 2: Garden path rate
# ---------------------------------------------------------------------------

def count_garden_paths(text: str) -> int:
    """Count potential garden-path sentences in text.

    Uses pattern matching to detect known garden-path structures.
    This is a simplified heuristic — full detection would require
    a parser.
    """
    count = 0
    for pattern in GARDEN_PATH_PATTERNS:
        count += len(pattern.findall(text))
    return count


def compute_garden_path_rate(text: str) -> float:
    """Garden-path sentences per total sentences.

    Returns a score from 0.0 (many garden paths) to 1.0 (none).
    Normalized: 0% garden paths → 1.0; 10%+ → 0.0.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return 1.0
    raw = count_garden_paths(text)
    rate = raw / len(sentences)
    score = max(0.0, 1.0 - rate / 0.10)
    return round(score, 4)


# ---------------------------------------------------------------------------
# Signal 3: Pronoun-antecedent distance
# ---------------------------------------------------------------------------

def _find_pronoun_distances(text: str) -> list[int]:
    """Compute word distances between pronouns and nearest candidate
    antecedent nouns.

    For each anaphoric pronoun, search backward for the nearest
    content word (noun-like) and record the word distance.
    """
    words = _split_words(text)
    distances = []
    for i, w in enumerate(words):
        if w in ANAPHORIC_PRONOUNS:
            # Search backward for nearest content word (not a pronoun,
            # not a function word)
            for j in range(i - 1, -1, -1):
                if (
                    words[j] not in ANAPHORIC_PRONOUNS
                    and len(words[j]) > 2
                    and words[j] not in PREPOSITIONS
                    and words[j] not in {"the", "a", "an", "is", "are",
                                          "was", "were", "be", "been",
                                          "has", "have", "had", "do",
                                          "does", "did", "will", "would",
                                          "could", "should", "may", "might",
                                          "can", "shall", "and", "but",
                                          "or", "not", "no"}
                ):
                    distances.append(i - j)
                    break
    return distances


def compute_pronoun_distance(text: str) -> float:
    """Mean pronoun-antecedent distance, normalized.

    Returns a score from 0.0 (very distant pronouns) to 1.0 (close).
    Mean distance 1–2 words → 1.0; 15+ words → 0.0.
    """
    distances = _find_pronoun_distances(text)
    if not distances:
        return 1.0  # No pronouns to resolve
    mean_dist = sum(distances) / len(distances)
    # Normalize: mean ≤ 2 → 1.0; mean ≥ 15 → 0.0
    score = max(0.0, min(1.0, 1.0 - (mean_dist - 2) / 13))
    return round(score, 4)


# ---------------------------------------------------------------------------
# Signal 4: Nested clause depth
# ---------------------------------------------------------------------------

def _measure_clause_depth(sentence: str) -> int:
    """Estimate the maximum clause embedding depth of a sentence.

    Heuristic: count the nesting of relative clauses (that/which/who)
    and subordinating conjunctions.  Each relative pronoun or
    subordinator increments depth by 1.
    """
    words = _split_words(sentence)
    depth = 1  # The main clause
    max_depth = 1
    for w in words:
        if w in RELATIVE_PRONOUNS or w in SUBORDINATORS:
            depth += 1
            max_depth = max(max_depth, depth)
        # Commas can close a clause (simplified heuristic)
        # We approximate by checking for comma-separated segments
    # Also count parenthetical and comma-delimited clauses
    comma_count = sentence.count(",")
    if comma_count >= 4:
        max_depth = max(max_depth, max_depth + 1)
    return max_depth


def compute_nested_depth(text: str) -> float:
    """Mean clause nesting depth, normalized.

    Returns a score from 0.0 (very deep nesting) to 1.0 (flat).
    Mean depth 1.0 → 1.0; mean depth 3.0+ → 0.0.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return 1.0
    depths = [_measure_clause_depth(s) for s in sentences]
    mean_depth = sum(depths) / len(depths)
    # Normalize: 1.0 → 1.0; 3.0+ → 0.0
    score = max(0.0, min(1.0, 1.0 - (mean_depth - 1.0) / 2.0))
    return round(score, 4)


def compute_max_nested_depth(text: str) -> int:
    """Maximum clause nesting depth across all sentences."""
    sentences = _split_sentences(text)
    if not sentences:
        return 0
    return max(_measure_clause_depth(s) for s in sentences)


# ---------------------------------------------------------------------------
# Composite metric
# ---------------------------------------------------------------------------

def _classify_clarity(index: float) -> str:
    """Classify a clarity index into a human-readable label."""
    for threshold, label in CLARITY_CLASSES:
        if index >= threshold:
            return label
    return "opaque"


def _empty_metrics() -> dict[str, Any]:
    """Return a metrics dict with all signals at neutral/default."""
    return {
        "attachment_rate": 1.0,
        "garden_path_rate": 1.0,
        "pronoun_distance": 1.0,
        "nested_depth": 1.0,
        "max_depth": 0,
        "clarity_index": 1.0,
        "clarity_class": "crystalline",
        "word_count": 0,
        "sentence_count": 0,
    }


def _empty_stroke_metrics() -> dict[str, Any]:
    """Return an empty per-stroke metrics dict."""
    return {
        "attachment_rate": 1.0,
        "garden_path_rate": 1.0,
        "pronoun_distance": 1.0,
        "nested_depth": 1.0,
        "clarity_index": 1.0,
        "clarity_class": "crystalline",
    }


def compute_clarity_metrics(
    text: str,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compute all clarity signals and composite index for a text.

    Parameters
    ----------
    text : str
        The text to analyze.
    weights : dict, optional
        Override default signal weights.  Keys: attachment, garden_path,
        pronoun_distance, nested_depth.  Values must sum to 1.0.

    Returns
    -------
    dict with all signal scores, composite index, classification,
    and text statistics.
    """
    w = weights or SIGNAL_WEIGHTS
    words = _split_words(text)
    sentences = _split_sentences(text)

    if not words:
        return _empty_metrics()

    att = compute_attachment_ambiguity_rate(text)
    gp = compute_garden_path_rate(text)
    pd = compute_pronoun_distance(text)
    nd = compute_nested_depth(text)
    max_nd = compute_max_nested_depth(text)

    index = (
        att * w.get("attachment", 0.30)
        + gp * w.get("garden_path", 0.20)
        + pd * w.get("pronoun_distance", 0.25)
        + nd * w.get("nested_depth", 0.25)
    )

    return {
        "attachment_rate": att,
        "garden_path_rate": gp,
        "pronoun_distance": pd,
        "nested_depth": nd,
        "max_depth": max_nd,
        "clarity_index": round(index, 4),
        "clarity_class": _classify_clarity(index),
        "word_count": len(words),
        "sentence_count": len(sentences),
    }


def analyze_stroke_clarity(stroke: Any) -> dict[str, Any]:
    """Analyze clarity of a single stroke."""
    text = _get_stroke_text(stroke)
    if not text.strip():
        return _empty_stroke_metrics()

    metrics = compute_clarity_metrics(text)
    return {
        "attachment_rate": metrics["attachment_rate"],
        "garden_path_rate": metrics["garden_path_rate"],
        "pronoun_distance": metrics["pronoun_distance"],
        "nested_depth": metrics["nested_depth"],
        "clarity_index": metrics["clarity_index"],
        "clarity_class": metrics["clarity_class"],
    }


def compute_clarity_trend(
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze clarity trend across multiple snapshots.

    Parameters
    ----------
    snapshots : list of dicts
        Each dict must contain a "clarity_index" key.

    Returns
    -------
    dict with trend direction, delta, and interpretation.
    """
    if not snapshots:
        return {"trend": "no_data", "delta": 0.0, "interpretation": ""}
    if len(snapshots) == 1:
        return {
            "trend": "single_snapshot",
            "delta": 0.0,
            "interpretation": f"clarity index: {snapshots[0].get('clarity_index', 0):.3f}",
        }

    indices = [s.get("clarity_index", 0) for s in snapshots]
    first = indices[0]
    last = indices[-1]
    delta = last - first

    if abs(delta) < 0.05:
        trend = "stable"
    elif delta > 0:
        trend = "improving"
    else:
        trend = "declining"

    return {
        "trend": trend,
        "delta": round(delta, 4),
        "first": round(first, 4),
        "last": round(last, 4),
        "count": len(snapshots),
        "interpretation": _trend_interpretation(trend, delta),
    }


def _trend_interpretation(trend: str, delta: float) -> str:
    """Generate a human-readable interpretation of a clarity trend."""
    if trend == "improving":
        return f"clarity improved by {delta:+.3f} — prose is becoming easier to parse"
    if trend == "declining":
        return f"clarity declined by {delta:+.3f} — prose is becoming harder to parse"
    if trend == "stable":
        return "clarity is stable — structural ambiguity has not changed significantly"
    return ""


def classify_trend(delta: float) -> str:
    """Classify a clarity delta into a trend label."""
    if abs(delta) < 0.05:
        return "stable"
    if delta > 0:
        return "improving"
    return "declining"


def format_clarity_report(metrics: dict[str, Any]) -> str:
    """Format clarity metrics as a human-readable report string."""
    lines = [
        f"clarity: {metrics.get('clarity_class', 'unknown')}",
        f"  index: {metrics.get('clarity_index', 0):.3f}",
        f"  attachment ambiguity rate: {metrics.get('attachment_rate', 0):.3f}",
        f"  garden path rate: {metrics.get('garden_path_rate', 0):.3f}",
        f"  pronoun distance: {metrics.get('pronoun_distance', 0):.3f}",
        f"  nested depth: {metrics.get('nested_depth', 0):.3f} (max {metrics.get('max_depth', 0)})",
        f"  words: {metrics.get('word_count', 0)}, sentences: {metrics.get('sentence_count', 0)}",
    ]
    return "\n".join(lines)


def analyze_clarity(
    text: str,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Full clarity analysis pipeline.

    Convenience wrapper around compute_clarity_metrics that also
    includes the formatted report.
    """
    metrics = compute_clarity_metrics(text, weights=weights)
    metrics["report"] = format_clarity_report(metrics)
    return metrics
