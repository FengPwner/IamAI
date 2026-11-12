#!/usr/bin/env python3
"""writer_density — measure how much information each word carries.

Information density is the ratio of *meaning* to *words*.  Dense prose
makes every word earn its place: content words outnumber function words,
ideas are not repeated in different clothing, and qualifiers are used
sparingly.  Thin prose pads its word count with filler, redundancy, and
stacked modifiers that say what one word could have said.

This module is orthogonal to the other writer metrics:

- **concision** tracks *word count economy*.  A concise text is short.
  A dense text may be long but every sentence carries weight.  Concision
  is about *how many* words; density is about *what each word does*.
  A 500-word paragraph with 400 content words is denser than a 100-word
  paragraph with 50 content words, even though the shorter one is more
  concise.

- **specificity** tracks *detail granularity*.  Specific text has many
  concrete details.  Dense text may or may not be specific — it could
  carry abstract ideas efficiently.  Density measures *payload per word*,
  not *detail per sentence*.

- **elegance** tracks *craft quality*.  Elegant prose can be dense or
  sparse — elegance is about the artfulness of the expression.  Density
  is a raw measure of information content, independent of beauty.

- **readability** tracks *comprehension ease*.  Very dense text can be
  hard to read (academic jargon, legal briefs).  Readability and density
  can be in tension: the densest text is not always the most useful.

- **restraint** tracks *what is omitted*.  Restraint is the discipline
  of leaving things out.  Density is about the payload of what remains.
  A restrained writer may produce very dense text (every word counts)
  or very thin text (so little is said that each word barely carries
  anything).

Density asks: **does each word carry meaning, or is the prose padded?**

Four signals are tracked:

1. **Semantic payload** — the ratio of content words to total words.
   Content words are nouns, verbs (excluding auxiliaries), adjectives,
   and adverbs that carry semantic meaning.  Function words are articles,
   prepositions, conjunctions, auxiliary verbs, pronouns, and determiners.
   English typically runs 45-55% content words in well-edited prose.
   Below 40% suggests padding; above 60% suggests telegraphic density
   that may sacrifice readability.

2. **Redundancy rate** — how often adjacent or near-adjacent sentences
   repeat the same idea in different words.  Measured by Jaccard
   similarity of content-word sets between consecutive sentence pairs.
   High overlap (>0.3) between consecutive sentences suggests the writer
   is saying the same thing twice.  Occasional repetition for emphasis
   is normal; systematic redundancy is padding.

3. **Qualifier stacking** — the frequency of multiple modifiers piled
   before a noun or verb.  "The very extremely important critical
   decision" uses five words where "the crucial decision" would suffice.
   Stacking is detected by counting consecutive content-word modifiers
   before a noun-like word.  Two or more stacked qualifiers is a density
   leak.

4. **Filler phrases** — multi-word expressions that add zero information:
   "it is important to note that", "at the end of the day", "in terms of",
   "when it comes to", "the fact that", "for all intents and purposes",
   "it goes without saying", "needless to say", "as a matter of fact",
   "in the final analysis".  These are the dead weight of English prose.

From these signals a session-level **density_index** is computed and
classified:

==============  ============================================================
class           meaning
==============  ============================================================
concentrated    index >= 0.75 — every word pulls weight; high content ratio,
                minimal redundancy, no filler; the prose is lean and loaded
dense           0.55 <= index < 0.75 — good payload; occasional filler or
                redundancy but overall each sentence carries real content
moderate        0.35 <= index < 0.55 — average density; mix of content and
                padding; could be tightened without losing meaning
thin            0.20 <= index < 0.35 — more padding than payload; filler
                phrases and redundant restatements dominate the word count
dilute          index < 0.20 — almost no density; the text is mostly
                scaffolding with very little actual information inside
==============  ============================================================
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Word lists
# ---------------------------------------------------------------------------

# Common English function words (closed-class, low semantic payload)
FUNCTION_WORDS: frozenset[str] = frozenset({
    # articles / determiners
    "a", "an", "the", "this", "that", "these", "those", "my", "your",
    "his", "her", "its", "our", "their", "some", "any", "no", "every",
    "each", "all", "both", "neither", "either",
    # pronouns
    "i", "me", "we", "us", "you", "he", "him", "she", "it", "they",
    "them", "who", "whom", "which", "what", "myself", "yourself",
    "himself", "herself", "itself", "ourselves", "themselves",
    # prepositions
    "in", "on", "at", "to", "for", "with", "by", "from", "of", "about",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "under", "over", "up", "down", "out", "off", "around",
    "across", "along", "against", "behind", "beyond", "toward",
    "without", "within", "among", "upon", "near", "towards",
    # conjunctions
    "and", "or", "but", "nor", "yet", "so", "because", "although",
    "while", "if", "unless", "until", "since", "though", "whereas",
    "whether", "however", "therefore", "moreover", "furthermore",
    "nevertheless", "nonetheless", "meanwhile", "otherwise",
    # auxiliary / modal verbs
    "is", "am", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "having",
    "do", "does", "did", "doing",
    "will", "would", "shall", "should", "may", "might", "must",
    "can", "could",
    # common particles / fillers
    "not", "n't", "there", "here", "than", "then", "as", "also",
    "too", "very", "just", "only", "even", "still", "already",
    "rather", "quite", "somewhat",
})

# Multi-word filler phrases that carry zero information
FILLER_PHRASES: list[str] = [
    "it is important to note that",
    "it should be noted that",
    "it is worth noting that",
    "it goes without saying",
    "for all intents and purposes",
    "at the end of the day",
    "in the final analysis",
    "when it comes to",
    "in terms of",
    "the fact that",
    "as a matter of fact",
    "by and large",
    "in a manner of speaking",
    "in the grand scheme of things",
    "at this point in time",
    "needless to say",
    "it stands to reason",
    "in light of the fact that",
    "due to the fact that",
    "in spite of the fact that",
    "on the grounds that",
    "in the event that",
    "for the purpose of",
    "with regard to",
    "with respect to",
    "in relation to",
    "in connection with",
    "on the part of",
    "in the process of",
    "in the midst of",
]

# Qualifier words that often appear in stacks before nouns
QUALIFIER_WORDS: frozenset[str] = frozenset({
    "very", "extremely", "incredibly", "remarkably", "particularly",
    "especially", "highly", "really", "absolutely", "completely",
    "totally", "utterly", "perfectly", "quite", "rather", "fairly",
    "somewhat", "slightly", "moderately", "enormously", "immensely",
    "profoundly", "deeply", "truly", "genuinely", "seriously",
    "significantly", "substantially", "considerably", "markedly",
    "notably", "strikingly", "exceedingly", "tremendously",
})

# Density classification thresholds
DENSITY_CLASSES: list[tuple[float, str]] = [
    (0.75, "concentrated"),
    (0.55, "dense"),
    (0.35, "moderate"),
    (0.20, "thin"),
    (0.00, "dilute"),
]

# Weight configuration for the composite index
SIGNAL_WEIGHTS: dict[str, float] = {
    "semantic_payload": 0.35,
    "non_redundancy": 0.30,
    "no_stacking": 0.15,
    "no_filler": 0.20,
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


def _content_words(words: list[str]) -> list[str]:
    """Return only content words (not function words, length > 1)."""
    return [w for w in words if w not in FUNCTION_WORDS and len(w) > 1]


# ---------------------------------------------------------------------------
# Signal 1: Semantic payload
# ---------------------------------------------------------------------------


def compute_semantic_payload(text: str) -> float:
    """Compute the ratio of content words to total words.

    Returns a value between 0.0 and 1.0.  Higher means more content
    per word.
    """
    words = _split_words(text)
    if not words:
        return 0.0

    total = len(words)
    content = len(_content_words(words))

    return content / total


# ---------------------------------------------------------------------------
# Signal 2: Redundancy rate
# ---------------------------------------------------------------------------


def _sentence_content_set(sentence: str) -> set[str]:
    """Get the set of content words in a sentence."""
    return set(_content_words(_split_words(sentence)))


def compute_redundancy_rate(text: str) -> float:
    """Compute the average Jaccard similarity between consecutive sentences.

    Returns a value between 0.0 and 1.0.  Higher means more redundancy.
    """
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 0.0

    total_similarity = 0.0
    pairs = 0

    for i in range(len(sentences) - 1):
        set_a = _sentence_content_set(sentences[i])
        set_b = _sentence_content_set(sentences[i + 1])

        if not set_a and not set_b:
            continue

        union = set_a | set_b
        if not union:
            continue

        jaccard = len(set_a & set_b) / len(union)
        total_similarity += jaccard
        pairs += 1

    if pairs == 0:
        return 0.0

    return total_similarity / pairs


# ---------------------------------------------------------------------------
# Signal 3: Qualifier stacking
# ---------------------------------------------------------------------------


def compute_qualifier_stacking(text: str) -> float:
    """Count qualifier stacks (2+ consecutive qualifiers before a word).

    Returns the number of stacks per 100 words.  Lower is better.
    """
    words = _split_words(text)
    if len(words) < 3:
        return 0.0

    stacks = 0
    consecutive = 0

    for word in words:
        if word in QUALIFIER_WORDS:
            consecutive += 1
        else:
            if consecutive >= 2:
                stacks += 1
            consecutive = 0

    # Check trailing stack
    if consecutive >= 2:
        stacks += 1

    return (stacks / len(words)) * 100


# ---------------------------------------------------------------------------
# Signal 4: Filler phrases
# ---------------------------------------------------------------------------


def compute_filler_density(text: str) -> float:
    """Count filler phrases per 100 words.

    Returns the number of filler phrases found, normalized by word count.
    """
    lower = text.lower()
    words = _split_words(text)
    if not words:
        return 0.0

    count = 0
    for phrase in FILLER_PHRASES:
        # Count non-overlapping occurrences
        start = 0
        while True:
            idx = lower.find(phrase, start)
            if idx == -1:
                break
            count += 1
            start = idx + len(phrase)

    return (count / len(words)) * 100


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyze_stroke_density(stroke: Any) -> dict[str, Any]:
    """Analyze density for a single stroke.

    Returns
    -------
    dict
        Keys: semantic_payload, redundancy_rate, qualifier_stacking,
        filler_density, density_index, density_class.
    """
    text = _get_stroke_text(stroke)
    if not text.strip():
        return _empty_stroke_metrics()

    payload = compute_semantic_payload(text)
    redundancy = compute_redundancy_rate(text)
    stacking = compute_qualifier_stacking(text)
    filler = compute_filler_density(text)

    # Normalize each signal to 0-1 (higher = denser)
    # payload is already 0-1
    # redundancy: invert (low redundancy = high density)
    non_redundancy = max(0.0, 1.0 - redundancy * 3)  # 0.33+ redundancy → 0
    # stacking: invert (low stacking = high density), typical 0-5 per 100w
    no_stacking = max(0.0, 1.0 - stacking / 5.0)
    # filler: invert (low filler = high density), typical 0-3 per 100w
    no_filler = max(0.0, 1.0 - filler / 3.0)

    index = (
        SIGNAL_WEIGHTS["semantic_payload"] * payload
        + SIGNAL_WEIGHTS["non_redundancy"] * non_redundancy
        + SIGNAL_WEIGHTS["no_stacking"] * no_stacking
        + SIGNAL_WEIGHTS["no_filler"] * no_filler
    )

    density_class = _classify_density(index)

    return {
        "semantic_payload": round(payload, 4),
        "redundancy_rate": round(redundancy, 4),
        "qualifier_stacking": round(stacking, 4),
        "filler_density": round(filler, 4),
        "density_index": round(index, 4),
        "density_class": density_class,
    }


def _empty_stroke_metrics() -> dict[str, Any]:
    """Return empty metrics for a blank stroke."""
    return {
        "semantic_payload": 0.0,
        "redundancy_rate": 0.0,
        "qualifier_stacking": 0.0,
        "filler_density": 0.0,
        "density_index": 0.0,
        "density_class": "dilute",
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify_density(index: float) -> str:
    """Map a density_index to its class label."""
    for threshold, label in DENSITY_CLASSES:
        if index >= threshold:
            return label
    return "dilute"


# ---------------------------------------------------------------------------
# Session-level aggregation
# ---------------------------------------------------------------------------


def _empty_metrics() -> dict[str, Any]:
    """Return zeroed-out session metrics when no data is available."""
    return {
        "strokes_analyzed": 0,
        "total_words": 0,
        "density_index": 0.0,
        "density_class": "dilute",
        "semantic_payload": 0.0,
        "redundancy_rate": 0.0,
        "qualifier_stacking": 0.0,
        "filler_density": 0.0,
        "class_distribution": {},
        "stroke_indices": [],
    }


def compute_density_metrics(
    strokes: list[Any],
    window_size: int = 50,
) -> dict[str, Any]:
    """Compute aggregated density metrics over a window of strokes.

    Parameters
    ----------
    strokes : list
        List of strokes (strings or dicts with 'text' key).
    window_size : int
        Maximum number of recent strokes to analyze.

    Returns
    -------
    dict
        Aggregated density metrics.
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
        analysis = analyze_stroke_density(stroke)
        analyses.append(analysis)
        total_words += len(_split_words(text))

    if not analyses:
        return _empty_metrics()

    n = len(analyses)
    avg_payload = sum(a["semantic_payload"] for a in analyses) / n
    avg_redundancy = sum(a["redundancy_rate"] for a in analyses) / n
    avg_stacking = sum(a["qualifier_stacking"] for a in analyses) / n
    avg_filler = sum(a["filler_density"] for a in analyses) / n
    avg_index = sum(a["density_index"] for a in analyses) / n

    class_dist: dict[str, int] = {}
    for a in analyses:
        cls = a["density_class"]
        class_dist[cls] = class_dist.get(cls, 0) + 1

    return {
        "strokes_analyzed": n,
        "total_words": total_words,
        "density_index": round(avg_index, 4),
        "density_class": _classify_density(avg_index),
        "semantic_payload": round(avg_payload, 4),
        "redundancy_rate": round(avg_redundancy, 4),
        "qualifier_stacking": round(avg_stacking, 4),
        "filler_density": round(avg_filler, 4),
        "class_distribution": class_dist,
        "stroke_indices": [a["density_index"] for a in analyses],
    }


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


def compute_density_trend(
    strokes: list[Any],
    window_size: int = 20,
    step: int = 10,
) -> list[dict[str, Any]]:
    """Compute density snapshots over time for trend analysis.

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
        List of snapshot dicts with density metrics.
    """
    if not strokes:
        return []

    snapshots: list[dict[str, Any]] = []
    for start in range(0, max(1, len(strokes) - window_size + 1), step):
        window = strokes[start : start + window_size]
        metrics = compute_density_metrics(window, window_size)
        metrics["window_start"] = start
        snapshots.append(metrics)
    return snapshots


def classify_trend(snapshots: list[dict[str, Any]]) -> str:
    """Classify the density trend from snapshots.

    Returns one of: concentrating, stable, thinning, insufficient_data.
    """
    if len(snapshots) < 2:
        return "insufficient_data"

    scores = [s.get("density_index", 0.0) for s in snapshots]
    first_half = scores[: len(scores) // 2]
    second_half = scores[len(scores) // 2 :]

    avg_first = sum(first_half) / len(first_half) if first_half else 0.0
    avg_second = sum(second_half) / len(second_half) if second_half else 0.0

    delta = avg_second - avg_first

    if delta > 0.05:
        return "concentrating"
    elif delta < -0.05:
        return "thinning"
    else:
        return "stable"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_density_report(metrics: dict[str, Any]) -> str:
    """Format density metrics as a human-readable report."""
    lines = [
        "=== Writer Density ===",
        f"Strokes analyzed:          {metrics['strokes_analyzed']}",
        f"Total words:               {metrics['total_words']}",
        f"Density index:             {metrics['density_index']:.4f} ({metrics['density_class']})",
        "",
        f"Semantic payload:          {metrics['semantic_payload']:.4f}",
        f"Redundancy rate:           {metrics['redundancy_rate']:.4f}",
        f"Qualifier stacking:        {metrics['qualifier_stacking']:.4f}/100w",
        f"Filler density:            {metrics['filler_density']:.4f}/100w",
        "",
    ]

    dist = metrics.get("class_distribution", {})
    if dist:
        lines.append("Class distribution:")
        for cls in ("concentrated", "dense", "moderate", "thin", "dilute"):
            count = dist.get(cls, 0)
            if count:
                lines.append(f"  {cls:14s} {count}")
        lines.append("")

    dc = metrics["density_class"]
    lines.append("Interpretation:")
    if dc == "concentrated":
        lines.append("  Every word pulls weight. High content ratio, minimal")
        lines.append("  redundancy, no filler. The prose is lean and loaded.")
    elif dc == "dense":
        lines.append("  Good payload. Occasional filler or redundancy but")
        lines.append("  overall each sentence carries real content.")
    elif dc == "moderate":
        lines.append("  Average density. Mix of content and padding; could")
        lines.append("  be tightened without losing meaning.")
    elif dc == "thin":
        lines.append("  More padding than payload. Filler phrases and redundant")
        lines.append("  restatements dominate the word count.")
    else:
        lines.append("  Almost no density. The text is mostly scaffolding with")
        lines.append("  very little actual information inside.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone analysis (reads from strokes.jsonl)
# ---------------------------------------------------------------------------


def analyze_density(
    strokes_path: str = "data/strokes.jsonl",
    window_size: int = 50,
) -> dict[str, Any]:
    """Analyze density from the strokes file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Density metrics.
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

    return compute_density_metrics(strokes, window_size)


if __name__ == "__main__":
    metrics = analyze_density()
    print(format_density_report(metrics))
