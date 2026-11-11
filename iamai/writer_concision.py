#!/usr/bin/env python3
"""writer_concision — measure whether writing uses more words than needed.

Concision is about *economy*.  Concise prose delivers its meaning in the
fewest words that preserve accuracy and tone.  Verbose prose pads,
hedges, restates, and decorates — adding words without adding meaning.

This module is orthogonal to the other writer metrics:

- **readability** tracks whether prose is *easy to parse*.  A text can
  be readable (short sentences, simple words) while being verbose
  (repeating the same point three times in slightly different ways).
  Readability is about access; concision is about efficiency.

- **prose_rhythm** tracks *variation* in sentence length.  A text can
  have excellent rhythm (alternating long and short sentences) while
  every long sentence is padded with deadwood.  Rhythm is about pacing;
  concision is about whether each word earns its place.

- **signal_clarity** tracks whether strokes are *substantively unique*.
  A writer can have high clarity (no near-duplicates) while each stroke
  takes twice as many words as necessary.  Clarity is about uniqueness;
  concision is about density.

- **vocabulary_richness** tracks *diversity* of word choice.  A text can
  use rich vocabulary while being concise (each word is precise and
  irreplaceable).  Conversely, a text can use narrow vocabulary while
  being concise (simple words, no waste).

- **grounding_density** tracks whether claims are *anchored in evidence*.
  A text can be well-grounded while being verbose (citing evidence at
  unnecessary length).  Grounding is about support; concision is about
  whether the support is delivered efficiently.

Concision asks specifically: **could this sentence be shorter without
losing meaning?**

Four signals are tracked:

1. **Redundancy ratio** — the fraction of recognized verbose patterns
   found in the text.  Patterns like "in order to" (vs. "to"), "due to
   the fact that" (vs. "because"), "at this point in time" (vs. "now"),
   "it is important to note that" (vs. nothing — just say it).  Each
   pattern has a concise equivalent; the ratio measures how often the
   verbose form is chosen over the concise one.

2. **Deadwood ratio** — the density of words that add no meaning:
   intensifiers without force ("very", "really", "quite", "rather"),
   hedges without nuance ("basically", "actually", "essentially",
   "literally"), and filler adverbs ("just", "simply", "merely",
   "obviously", "clearly").  These words can almost always be removed
   without changing the sentence's meaning.

3. **Filler clause density** — the frequency of empty introductory or
   transitional clauses per hundred words: "it should be noted that",
   "it is worth mentioning", "as a matter of fact", "in today's world",
   "at the end of the day", "when all is said and done".  These phrases
   announce that content is coming instead of delivering it.

4. **Information density** — the ratio of content words (nouns, verbs
   excluding auxiliaries, adjectives, adverbs) to total words.  High
   density means most words carry meaning.  Low density means the text
   is padded with function words, articles, prepositions, and
   auxiliaries beyond what grammar requires.

From these signals a session-level **concision_index** is computed
and classified:

==============  ============================================================
class           meaning
==============  ============================================================
precise         index >= 0.80 — every word earns its place; the writing is
                tight and direct; meaning is delivered efficiently
clean           0.65 <= index < 0.80 — mostly direct; occasional verbose
                patterns but the prose doesn't waste the reader's time
wordy           0.50 <= index < 0.65 — noticeable padding; sentences could
                be tightened without losing meaning; the reader notices
bloated         0.35 <= index < 0.50 — significant verbosity; every
                paragraph has filler phrases and deadwood; the reader
                must wade through words to find meaning
suffocating     index < 0.35 — the prose is buried under qualifiers,
                hedges, and restatements; meaning is obscured by the
                sheer volume of words around it
==============  ============================================================

Reference: Strunk & White, *The Elements of Style* (Rule 17: "Omit
needless words").  Applied to autonomous writing: a writer that cannot
compress its thoughts into efficient prose produces output that is
correct but exhausting — technically accurate, rhetorically wasteful.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Redundancy patterns — verbose phrase → concise equivalent
# ---------------------------------------------------------------------------

REDUNDANCY_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "in order to" → "to"
    (re.compile(r"\bin\s+order\s+to\b", re.IGNORECASE), "to"),
    # "due to the fact that" → "because"
    (re.compile(r"\bdue\s+to\s+the\s+fact\s+that\b", re.IGNORECASE), "because"),
    # "at this point in time" → "now"
    (re.compile(r"\bat\s+this\s+point\s+in\s+time\b", re.IGNORECASE), "now"),
    # "in the event that" → "if"
    (re.compile(r"\bin\s+the\s+event\s+that\b", re.IGNORECASE), "if"),
    # "for the purpose of" → "to" / "for"
    (re.compile(r"\bfor\s+the\s+purpose\s+of\b", re.IGNORECASE), "to"),
    # "it is important to note that" → (just say it)
    (re.compile(r"\bit\s+is\s+important\s+to\s+note\s+that\b", re.IGNORECASE), ""),
    # "it should be noted that" → (just say it)
    (re.compile(r"\bit\s+should\s+be\s+noted\s+that\b", re.IGNORECASE), ""),
    # "it is worth mentioning that" → (just say it)
    (re.compile(r"\bit\s+is\s+worth\s+mentioning\s+that\b", re.IGNORECASE), ""),
    # "as a matter of fact" → (just say it)
    (re.compile(r"\bas\s+a\s+matter\s+of\s+fact\b", re.IGNORECASE), ""),
    # "in spite of the fact that" → "although" / "despite"
    (re.compile(r"\bin\s+spite\s+of\s+the\s+fact\s+that\b", re.IGNORECASE), "although"),
    # "on the grounds that" → "because"
    (re.compile(r"\bon\s+the\s+grounds\s+that\b", re.IGNORECASE), "because"),
    # "in the process of" → (use verb directly)
    (re.compile(r"\bin\s+the\s+process\s+of\b", re.IGNORECASE), ""),
    # "has the ability to" → "can"
    (re.compile(r"\bhas\s+the\s+ability\s+to\b", re.IGNORECASE), "can"),
    # "is able to" → "can"
    (re.compile(r"\bis\s+able\s+to\b", re.IGNORECASE), "can"),
    # "make use of" → "use"
    (re.compile(r"\bmake\s+use\s+of\b", re.IGNORECASE), "use"),
    # "take into consideration" → "consider"
    (re.compile(r"\btake\s+into\s+consideration\b", re.IGNORECASE), "consider"),
    # "come to the conclusion" → "conclude"
    (re.compile(r"\bcome\s+to\s+the\s+conclusion\b", re.IGNORECASE), "conclude"),
    # "give an indication" → "indicate"
    (re.compile(r"\bgive\s+an\s+indication\b", re.IGNORECASE), "indicate"),
    # "there is a possibility" → "possibly" / "might"
    (re.compile(r"\bthere\s+is\s+a\s+possibility\b", re.IGNORECASE), "might"),
    # "in the vicinity of" → "near" / "around"
    (re.compile(r"\bin\s+the\s+vicinity\s+of\b", re.IGNORECASE), "near"),
]


# ---------------------------------------------------------------------------
# Deadwood words — words that add no meaning
# ---------------------------------------------------------------------------

DEADWOOD_WORDS: set[str] = {
    # Intensifiers without force
    "very", "really", "quite", "rather", "extremely", "incredibly",
    "absolutely", "totally", "completely", "utterly", "thoroughly",
    # Hedges without nuance
    "basically", "actually", "essentially", "literally", "practically",
    "virtually", "technically", "arguably",
    # Filler adverbs
    "just", "simply", "merely", "obviously", "clearly", "certainly",
    "definitely", "undoubtedly", "admittedly", "hopefully",
    # Empty qualifiers
    "somewhat", "fairly", "pretty", "kind", "sort",
}

# Compile a pattern that matches any deadwood word at a word boundary
_DEADWOOD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in sorted(DEADWOOD_WORDS)) + r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Filler clause patterns
# ---------------------------------------------------------------------------

FILLER_CLAUSES: list[re.Pattern] = [
    re.compile(r"\bat\s+the\s+end\s+of\s+the\s+day\b", re.IGNORECASE),
    re.compile(r"\bwhen\s+all\s+is\s+said\s+and\s+done\b", re.IGNORECASE),
    re.compile(r"\bin\s+today'?s\s+world\b", re.IGNORECASE),
    re.compile(r"\bit\s+goes\s+without\s+saying\b", re.IGNORECASE),
    re.compile(r"\bneedless\s+to\s+say\b", re.IGNORECASE),
    re.compile(r"\bfor\s+all\s+intents\s+and\s+purposes\b", re.IGNORECASE),
    re.compile(r"\blong\s+story\s+short\b", re.IGNORECASE),
    re.compile(r"\bto\s+make\s+a\s+long\s+story\s+short\b", re.IGNORECASE),
    re.compile(r"\bthe\s+fact\s+of\s+the\s+matter\s+is\b", re.IGNORECASE),
    re.compile(r"\bthe\s+bottom\s+line\s+is\b", re.IGNORECASE),
    re.compile(r"\bat\s+the\s+end\s+of\s+the\s+day\b", re.IGNORECASE),
    re.compile(r"\bwith\s+that\s+being\s+said\b", re.IGNORECASE),
    re.compile(r"\bthat\s+being\s+said\b", re.IGNORECASE),
    re.compile(r"\bhaving\s+said\s+that\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Content word identification (simplified POS via suffix heuristics)
# ---------------------------------------------------------------------------

# Common function words (closed class)
_FUNCTION_WORDS: set[str] = {
    # Articles
    "a", "an", "the",
    # Prepositions
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "up",
    "about", "into", "through", "during", "before", "after", "above",
    "below", "between", "under", "over", "out", "off", "down", "near",
    "across", "along", "around", "beside", "beyond", "despite", "except",
    "inside", "outside", "since", "toward", "towards", "until", "upon",
    "within", "without", "among", "against",
    # Pronouns
    "i", "me", "my", "we", "us", "our", "you", "your", "he", "him",
    "his", "she", "her", "it", "its", "they", "them", "their", "this",
    "that", "these", "those", "who", "whom", "which", "what",
    # Conjunctions
    "and", "but", "or", "nor", "yet", "so", "if", "then", "than",
    "because", "although", "while", "when", "where", "how", "whether",
    "unless", "until", "since",
    # Auxiliary verbs
    "is", "are", "was", "were", "be", "been", "being", "am",
    "has", "have", "had", "having",
    "do", "does", "did", "doing",
    "will", "would", "shall", "should", "may", "might", "must", "can",
    "could",
    # Other function words
    "not", "no", "nor", "too", "also", "very",
    # Existential
    "there", "here",
}


# ---------------------------------------------------------------------------
# Low-level signal functions
# ---------------------------------------------------------------------------


def _split_words(text: str) -> list[str]:
    """Split text into lowercase words."""
    return re.findall(r"[a-zA-Z']+", text.lower())


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    parts = re.split(r'[.!?]+', text)
    return [p.strip() for p in parts if p.strip()]


def _get_stroke_text(stroke: dict[str, Any] | str) -> str:
    """Extract text content from a stroke dict or raw string."""
    if isinstance(stroke, str):
        return stroke
    return stroke.get("text", stroke.get("content", ""))


def count_redundancy_hits(text: str) -> list[tuple[str, str]]:
    """Find all verbose redundancy patterns in text.

    Returns
    -------
    list[tuple[str, str]]
        List of (verbose_phrase_found, concise_replacement).
    """
    hits: list[tuple[str, str]] = []
    for pattern, replacement in REDUNDANCY_PATTERNS:
        matches = pattern.findall(text)
        for match in matches:
            hits.append((match.lower(), replacement))
    return hits


def compute_redundancy_ratio(text: str) -> float:
    """Compute ratio of words consumed by redundancy patterns.

    Returns the fraction of total words that belong to detected
    redundancy patterns.  Higher = more verbose.
    """
    words = _split_words(text)
    if not words:
        return 0.0

    hits = count_redundancy_hits(text)
    if not hits:
        return 0.0

    # Count words consumed by verbose patterns
    redundant_words = sum(len(h[0].split()) for h in hits)
    return min(redundant_words / len(words), 1.0)


def compute_deadwood_ratio(text: str) -> float:
    """Compute fraction of words that are deadwood.

    Returns the fraction of total words that match the deadwood list.
    Higher = more padding.
    """
    words = _split_words(text)
    if not words:
        return 0.0

    deadwood_count = len(_DEADWOOD_RE.findall(text))
    return deadwood_count / len(words)


def compute_filler_clause_density(text: str) -> float:
    """Compute filler clauses per hundred words.

    Returns the number of filler clause hits normalized per 100 words.
    """
    words = _split_words(text)
    if not words:
        return 0.0

    filler_count = 0
    for pattern in FILLER_CLAUSES:
        filler_count += len(pattern.findall(text))

    return (filler_count / len(words)) * 100


def compute_information_density(text: str) -> float:
    """Compute ratio of content words to total words.

    Content words are those not in the function word list.  Higher
    density means more meaning per word.
    """
    words = _split_words(text)
    if not words:
        return 0.0

    content_words = [w for w in words if w not in _FUNCTION_WORDS]
    return len(content_words) / len(words)


# ---------------------------------------------------------------------------
# Composite index
# ---------------------------------------------------------------------------


def compute_concision_index(
    redundancy_ratio: float,
    deadwood_ratio: float,
    filler_clause_density: float,
    information_density: float,
) -> float:
    """Compute composite concision index from the four signals.

    The index is a weighted combination:
    - Redundancy penalty: 30% weight (direct waste)
    - Deadwood penalty: 25% weight (meaningless words)
    - Filler clause penalty: 20% weight (empty phrases)
    - Information density reward: 25% weight (substance per word)

    Returns a value in [0, 1] where higher = more concise.
    """
    # Redundancy: 0 redundancy → 1.0, 0.10+ redundancy → ~0.0
    redundancy_score = max(0.0, 1.0 - (redundancy_ratio * 10.0))

    # Deadwood: 0 deadwood → 1.0, 0.15+ deadwood → ~0.0
    deadwood_score = max(0.0, 1.0 - (deadwood_ratio * 6.67))

    # Filler clauses: 0 per 100 words → 1.0, 5+ per 100 → ~0.0
    filler_score = max(0.0, 1.0 - (filler_clause_density / 5.0))

    # Information density: typical range 0.45–0.65; map to 0–1
    # Higher density = better; 0.55+ → 1.0, below 0.35 → 0.0
    info_score = max(0.0, min(1.0, (information_density - 0.35) / 0.20))

    index = (
        0.30 * redundancy_score
        + 0.25 * deadwood_score
        + 0.20 * filler_score
        + 0.25 * info_score
    )

    return round(max(0.0, min(1.0, index)), 4)


def _classify_concision(index: float) -> str:
    """Classify concision index into a descriptive class.

    Returns one of: precise, clean, wordy, bloated, suffocating.
    """
    if index >= 0.80:
        return "precise"
    elif index >= 0.65:
        return "clean"
    elif index >= 0.50:
        return "wordy"
    elif index >= 0.35:
        return "bloated"
    else:
        return "suffocating"


# ---------------------------------------------------------------------------
# Stroke-level analysis
# ---------------------------------------------------------------------------


def analyze_stroke_concision(
    stroke: dict[str, Any] | str,
) -> dict[str, Any]:
    """Analyze concision for a single stroke.

    Parameters
    ----------
    stroke : dict or str
        A stroke dict (with 'text' or 'content' key) or raw text string.

    Returns
    -------
    dict
        Concision metrics for the stroke.
    """
    text = _get_stroke_text(stroke)
    words = _split_words(text)
    word_count = len(words)

    if word_count == 0:
        return {
            "word_count": 0,
            "redundancy_ratio": 0.0,
            "deadwood_ratio": 0.0,
            "filler_clause_density": 0.0,
            "information_density": 0.0,
            "redundancy_hits": [],
            "deadwood_count": 0,
            "filler_count": 0,
            "concision_index": 0.0,
            "concision_class": "suffocating",
        }

    redundancy_ratio = compute_redundancy_ratio(text)
    deadwood_ratio = compute_deadwood_ratio(text)
    filler_density = compute_filler_clause_density(text)
    info_density = compute_information_density(text)
    concision_index = compute_concision_index(
        redundancy_ratio, deadwood_ratio, filler_density, info_density
    )

    return {
        "word_count": word_count,
        "redundancy_ratio": round(redundancy_ratio, 4),
        "deadwood_ratio": round(deadwood_ratio, 4),
        "filler_clause_density": round(filler_density, 4),
        "information_density": round(info_density, 4),
        "redundancy_hits": count_redundancy_hits(text),
        "deadwood_count": len(_DEADWOOD_RE.findall(text)),
        "filler_count": sum(
            len(p.findall(text)) for p in FILLER_CLAUSES
        ),
        "concision_index": concision_index,
        "concision_class": _classify_concision(concision_index),
    }


# ---------------------------------------------------------------------------
# Session-level analysis
# ---------------------------------------------------------------------------


def compute_concision_metrics(
    strokes: list[dict[str, Any] | str],
    window_size: int = 50,
) -> dict[str, Any]:
    """Compute session-level concision metrics from a list of strokes.

    Parameters
    ----------
    strokes : list
        List of stroke dicts or raw text strings.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Session-level concision metrics.
    """
    if not strokes:
        return _empty_metrics()

    recent = strokes[-window_size:]
    stroke_analyses = [analyze_stroke_concision(s) for s in recent]

    total_words = sum(a["word_count"] for a in stroke_analyses)
    total_redundancy_hits = sum(
        len(a["redundancy_hits"]) for a in stroke_analyses
    )
    total_deadwood = sum(a["deadwood_count"] for a in stroke_analyses)
    total_filler = sum(a["filler_count"] for a in stroke_analyses)

    # Aggregate ratios
    avg_redundancy = (
        sum(a["redundancy_ratio"] for a in stroke_analyses)
        / len(stroke_analyses)
        if stroke_analyses
        else 0.0
    )
    avg_deadwood = (
        sum(a["deadwood_ratio"] for a in stroke_analyses)
        / len(stroke_analyses)
        if stroke_analyses
        else 0.0
    )
    avg_filler = (
        sum(a["filler_clause_density"] for a in stroke_analyses)
        / len(stroke_analyses)
        if stroke_analyses
        else 0.0
    )
    avg_info_density = (
        sum(a["information_density"] for a in stroke_analyses)
        / len(stroke_analyses)
        if stroke_analyses
        else 0.0
    )

    concision_index = compute_concision_index(
        avg_redundancy, avg_deadwood, avg_filler, avg_info_density
    )
    concision_class = _classify_concision(concision_index)

    # Distribution of concision classes across strokes
    class_dist: dict[str, int] = {}
    for a in stroke_analyses:
        cc = a["concision_class"]
        class_dist[cc] = class_dist.get(cc, 0) + 1

    return {
        "strokes_analyzed": len(stroke_analyses),
        "total_words": total_words,
        "concision_index": concision_index,
        "concision_class": concision_class,
        "avg_redundancy_ratio": round(avg_redundancy, 4),
        "avg_deadwood_ratio": round(avg_deadwood, 4),
        "avg_filler_clause_density": round(avg_filler, 4),
        "avg_information_density": round(avg_info_density, 4),
        "total_redundancy_hits": total_redundancy_hits,
        "total_deadwood_words": total_deadwood,
        "total_filler_clauses": total_filler,
        "class_distribution": class_dist,
    }


def _empty_metrics() -> dict[str, Any]:
    """Return empty metrics structure."""
    return {
        "strokes_analyzed": 0,
        "total_words": 0,
        "concision_index": 0.0,
        "concision_class": "suffocating",
        "avg_redundancy_ratio": 0.0,
        "avg_deadwood_ratio": 0.0,
        "avg_filler_clause_density": 0.0,
        "avg_information_density": 0.0,
        "total_redundancy_hits": 0,
        "total_deadwood_words": 0,
        "total_filler_clauses": 0,
        "class_distribution": {},
    }


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


def compute_concision_trend(
    strokes: list[dict[str, Any] | str],
    window_size: int = 20,
    step: int = 10,
) -> list[dict[str, Any]]:
    """Compute concision snapshots over time for trend analysis.

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
        List of snapshot dicts with concision metrics.
    """
    if not strokes:
        return []

    snapshots: list[dict[str, Any]] = []
    for start in range(0, max(1, len(strokes) - window_size + 1), step):
        window = strokes[start : start + window_size]
        metrics = compute_concision_metrics(window, window_size)
        metrics["window_start"] = start
        snapshots.append(metrics)
    return snapshots


def classify_trend(snapshots: list[dict[str, Any]]) -> str:
    """Classify the concision trend from snapshots.

    Returns one of: improving, stable, degrading, insufficient_data.
    """
    if len(snapshots) < 2:
        return "insufficient_data"

    scores = [s.get("concision_index", 0.0) for s in snapshots]
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


def format_concision_report(metrics: dict[str, Any]) -> str:
    """Format concision metrics as a human-readable report."""
    lines = [
        "=== Writer Concision ===",
        f"Strokes analyzed: {metrics['strokes_analyzed']}",
        f"Total words:      {metrics['total_words']}",
        f"Concision index:  {metrics['concision_index']:.4f} ({metrics['concision_class']})",
        "",
        f"Avg redundancy ratio:     {metrics['avg_redundancy_ratio']:.4f}",
        f"Avg deadwood ratio:       {metrics['avg_deadwood_ratio']:.4f}",
        f"Avg filler clause density: {metrics['avg_filler_clause_density']:.4f}",
        f"Avg information density:  {metrics['avg_information_density']:.4f}",
        "",
        f"Total redundancy hits:    {metrics['total_redundancy_hits']}",
        f"Total deadwood words:     {metrics['total_deadwood_words']}",
        f"Total filler clauses:     {metrics['total_filler_clauses']}",
        "",
    ]

    dist = metrics.get("class_distribution", {})
    if dist:
        lines.append("Class distribution:")
        for cls in ("precise", "clean", "wordy", "bloated", "suffocating"):
            count = dist.get(cls, 0)
            if count:
                lines.append(f"  {cls:14s} {count}")
        lines.append("")

    cc = metrics["concision_class"]
    lines.append("Interpretation:")
    if cc == "precise":
        lines.append("  Every word earns its place. The writing is tight")
        lines.append("  and direct, delivering meaning efficiently.")
    elif cc == "clean":
        lines.append("  Mostly direct prose with occasional verbose patterns.")
        lines.append("  The reader's time is generally respected.")
    elif cc == "wordy":
        lines.append("  Noticeable padding detected. Sentences could be")
        lines.append("  tightened without losing meaning.")
    elif cc == "bloated":
        lines.append("  Significant verbosity. Filler phrases and deadwood")
        lines.append("  words are consuming the reader's attention.")
    else:
        lines.append("  Prose is buried under qualifiers and restatements.")
        lines.append("  Meaning is obscured by excessive word count.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone analysis (reads from strokes.jsonl)
# ---------------------------------------------------------------------------


def analyze_concision(
    strokes_path: str = "data/strokes.jsonl",
    window_size: int = 50,
) -> dict[str, Any]:
    """Analyze concision from the strokes file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Concision metrics.
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

    return compute_concision_metrics(strokes, window_size)


if __name__ == "__main__":
    metrics = analyze_concision()
    print(format_concision_report(metrics))
