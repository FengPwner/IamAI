#!/usr/bin/env python3
"""writer_coherence — measure how well ideas connect and flow within writing.

Coherence is about *logical connectedness*.  Coherent prose links ideas
explicitly, maintains clear referents, and builds from one thought to
the next.  Incoherent prose jumps between topics, drops referents, and
leaves the reader to guess how sentence B relates to sentence A.

This module is orthogonal to the other writer metrics:

- **readability** tracks whether prose is *easy to parse*.  A text can be
  readable (short sentences, simple words) while being incoherent (each
  sentence is clear in isolation but the paragraph jumps randomly between
  topics).  Readability is about effort per sentence; coherence is about
  whether sentences *connect*.

- **concision** tracks whether prose uses *more words than needed*.  A
  text can be concise while being incoherent ("Deploy failed. Market
  opened. Tests pass." — three words each, zero connection).  Concision
  is about economy; coherence is about linkage.

- **signal_clarity** tracks whether strokes are *substantively unique*.
  A writer can produce unique, coherent strokes that don't connect to
  each other.  Clarity is about within-stroke uniqueness; coherence is
  about between-sentence connectedness.

- **specificity** tracks whether prose names *concrete things*.  A text
  can be specific ("Python 3.12", "port 8080", "2026-11-03") while
  being incoherent (jumping between unrelated specifics with no
  transitions).  Specificity is about precision of reference; coherence
  is about logical flow between references.

- **vocabulary_richness** tracks *diversity* of word choice.  A text
  can use rich vocabulary while being incoherent (ornate topic-jumping)
  or simple vocabulary while being coherent (plain but connected).

- **prose_rhythm** tracks *variation* in sentence length.  Rhythm is
  structural; coherence is semantic and logical.

- **grounding_density** tracks whether claims are *anchored in evidence*.
  Grounded but incoherent text cites sources without connecting the
  claims they support.

Coherence asks: **can the reader follow the argument, or do they have to
guess how each sentence relates to the last?**

Five signals are tracked:

1. **Transition density** — frequency of explicit transition words and
   phrases per hundred words.  Includes: additive ("moreover",
   "furthermore", "additionally", "also", "besides"), contrastive
   ("however", "although", "nevertheless", "in contrast", "on the other
   hand", "conversely", "yet"), causal ("therefore", "consequently",
   "because", "since", "as a result", "thus", "hence", "accordingly"),
   and temporal ("meanwhile", "subsequently", "afterward", "then",
   "next", "finally", "previously", "initially").

2. **Pronoun reference clarity** — whether pronouns have plausible
   antecedents in the preceding sentence.  Measured as the ratio of
   pronouns with a matching content-word antecedent in the prior sentence
   to total pronouns.  "The server crashed. It had been running for 48
   hours." — 'it' refers to 'server', clear.  "The server crashed. They
   said it would." — 'they' has no antecedent, unclear.

3. **Logical connector coverage** — fraction of consecutive sentence
   pairs that contain at least one logical connector (transition word,
   conjunction, or discourse marker).  A text where every sentence pair
   has a connector scores 1.0; a text where sentences are simply
   juxtaposed scores 0.0.

4. **Lexical cohesion** — overlap of content words between consecutive
   sentences.  Measured as the Jaccard similarity of content-word sets
   (nouns, verbs, adjectives, adverbs) between adjacent sentences,
   averaged across all pairs.  Higher overlap means the text stays on
   topic; zero overlap means each sentence introduces entirely new
   vocabulary.

5. **Discourse marker diversity** — variety of discourse markers used
   relative to total discourse marker instances.  A text that uses
   "however" seven times scores lower than one that uses "however",
   "moreover", "consequently", "in contrast", "meanwhile", "thus",
   "additionally" once each.  Measured as unique markers / total markers.

The **coherence_index** is computed as a weighted composite:

    index = transition_density_norm    * 0.25
          + pronoun_reference_clarity  * 0.20
          + logical_connector_coverage * 0.25
          + lexical_cohesion           * 0.15
          + discourse_marker_diversity * 0.15

Classified as:

- **tight** (>= 0.80): ideas flow naturally, every sentence connects
  to the last, referents are always clear.
- **connected** (>= 0.60): mostly coherent with occasional jumps.
- **adequate** (>= 0.40): mixed — some paragraphs flow, others feel
  like bullet points pretending to be prose.
- **loose** (>= 0.20): frequent topic jumps, unclear referents,
  reader must work to find connections.
- **fragmented** (< 0.20): sentences are islands; the text reads like
  a shuffled deck of independent thoughts.
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

TRANSITION_ADDITIVE: list[str] = [
    "moreover", "furthermore", "additionally", "also", "besides",
    "in addition", "what is more", "not only", "along with",
    "as well as", "equally important", "similarly", "likewise",
    "by the same token", "in the same way", "correspondingly",
]

TRANSITION_CONTRASTIVE: list[str] = [
    "however", "although", "nevertheless", "nonetheless",
    "in contrast", "on the other hand", "conversely", "yet",
    "still", "but", "whereas", "while", "despite",
    "in spite of", "on the contrary", "rather", "instead",
    "then again",
]

TRANSITION_CAUSAL: list[str] = [
    "therefore", "consequently", "because", "since", "as a result",
    "thus", "hence", "accordingly", "so", "for this reason",
    "due to", "owing to", "as a consequence", "in consequence",
    "for that reason", "which means", "that is why",
    "it follows that", "this suggests",
]

TRANSITION_TEMPORAL: list[str] = [
    "meanwhile", "subsequently", "afterward", "afterwards", "then",
    "next", "finally", "previously", "initially", "first",
    "second", "third", "later", "earlier", "before",
    "after", "during", "simultaneously", "at the same time",
    "in the meantime", "soon", "eventually", "ultimately",
]

ALL_TRANSITIONS: list[str] = (
    TRANSITION_ADDITIVE
    + TRANSITION_CONTRASTIVE
    + TRANSITION_CAUSAL
    + TRANSITION_TEMPORAL
)

TRANSITION_CATEGORIES: dict[str, list[str]] = {
    "additive": TRANSITION_ADDITIVE,
    "contrastive": TRANSITION_CONTRASTIVE,
    "causal": TRANSITION_CAUSAL,
    "temporal": TRANSITION_TEMPORAL,
}

PRONOUNS: list[str] = [
    "it", "its", "they", "them", "their", "theirs",
    "he", "him", "his", "she", "her", "hers",
    "this", "that", "these", "those",
    "which", "who", "whom",
]

# Common stop words to exclude from content-word analysis.
STOP_WORDS: set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can",
    "need", "dare", "ought", "used", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between",
    "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all",
    "both", "each", "few", "more", "most", "other", "some", "such",
    "no", "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "just", "because", "but", "and", "or", "if", "while",
    "about", "up", "that", "this", "these", "those", "it", "its",
    "they", "them", "their", "he", "him", "his", "she", "her",
    "we", "us", "our", "you", "your", "i", "me", "my", "what",
    "which", "who", "whom", "whose",
}


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


def _content_words(words: list[str]) -> list[str]:
    """Filter to content words (not stop words, length >= 3)."""
    return [w for w in words if w not in STOP_WORDS and len(w) >= 3]


# ---------------------------------------------------------------------------
# Signal 1: Transition density
# ---------------------------------------------------------------------------


def compute_transition_density(text: str) -> float:
    """Transition markers per hundred words.  Higher is more coherent.

    Returns a value >= 0.  Typical range: 0-10.
    """
    words = _split_words(text)
    if not words:
        return 0.0

    text_lower = text.lower()
    hits = 0
    for marker in ALL_TRANSITIONS:
        pattern = r"\b" + re.escape(marker) + r"\b"
        hits += len(re.findall(pattern, text_lower))

    return (hits / len(words)) * 100


def _score_transition_density(density: float) -> float:
    """Convert density to 0-1 score (1 = well-connected).

    Uses saturation curve: score = 1 - exp(-density / 3).
    At density 0 -> 0, density 3 -> ~0.63, density 6 -> ~0.86.
    """
    return 1.0 - math.exp(-density / 3.0)


# ---------------------------------------------------------------------------
# Signal 2: Pronoun reference clarity
# ---------------------------------------------------------------------------


def compute_pronoun_reference_clarity(text: str) -> float:
    """Fraction of pronouns with a plausible antecedent in the prior sentence.

    Returns 0-1.  Higher means pronouns consistently refer back to
    something named in the preceding sentence.
    """
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 0.5  # neutral when only one sentence

    total_pronouns = 0
    clear_pronouns = 0

    for i in range(1, len(sentences)):
        prev_words = set(_content_words(_split_words(sentences[i - 1])))
        curr_words = _split_words(sentences[i])

        for word in curr_words:
            if word in PRONOUNS:
                total_pronouns += 1
                if _has_antecedent(word, prev_words):
                    clear_pronouns += 1

    if total_pronouns == 0:
        return 0.7  # slightly above neutral when no pronouns used
    return clear_pronouns / total_pronouns


def _has_antecedent(pronoun: str, prev_content_words: set[str]) -> bool:
    """Check whether a pronoun has a plausible antecedent.

    Uses simple heuristic: any content word in the prior sentence that
    is not itself a pronoun counts as a potential antecedent for 'it',
    'they', 'this', 'that'.  For 'he'/'she', looks for person-nouns.
    """
    if not prev_content_words:
        return False

    person_indicators = {
        "man", "woman", "person", "user", "developer", "engineer",
        "author", "writer", "reader", "admin", "manager", "leader",
        "team", "group", "member", "client", "customer", "player",
        "he", "she", "him", "her", "who", "someone", "anyone",
    }

    if pronoun in ("he", "him", "his", "she", "her", "hers"):
        return bool(prev_content_words & person_indicators)

    # For 'it', 'they', 'this', 'that', 'these', 'those', 'which':
    # Any content word is a potential antecedent.
    return len(prev_content_words) > 0


# ---------------------------------------------------------------------------
# Signal 3: Logical connector coverage
# ---------------------------------------------------------------------------


def compute_logical_connector_coverage(text: str) -> float:
    """Fraction of consecutive sentence pairs linked by a connector.

    Returns 0-1.  Higher means more sentence pairs are explicitly linked.
    """
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 0.5  # neutral when only one sentence

    pairs = len(sentences) - 1
    linked = 0

    for i in range(1, len(sentences)):
        combined = (sentences[i - 1] + " " + sentences[i]).lower()
        for connector in ALL_TRANSITIONS:
            if re.search(r"\b" + re.escape(connector) + r"\b", combined):
                linked += 1
                break

    return linked / pairs


# ---------------------------------------------------------------------------
# Signal 4: Lexical cohesion
# ---------------------------------------------------------------------------


def compute_lexical_cohesion(text: str) -> float:
    """Average Jaccard similarity of content words between adjacent sentences.

    Returns 0-1.  Higher means consecutive sentences share more vocabulary,
    indicating the text stays on topic.
    """
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 0.5  # neutral when only one sentence

    similarities = []
    for i in range(1, len(sentences)):
        words_prev = set(_content_words(_split_words(sentences[i - 1])))
        words_curr = set(_content_words(_split_words(sentences[i])))

        if not words_prev and not words_curr:
            similarities.append(0.0)
            continue

        union = words_prev | words_curr
        if not union:
            similarities.append(0.0)
            continue

        intersection = words_prev & words_curr
        similarities.append(len(intersection) / len(union))

    if not similarities:
        return 0.5
    return sum(similarities) / len(similarities)


# ---------------------------------------------------------------------------
# Signal 5: Discourse marker diversity
# ---------------------------------------------------------------------------


def compute_discourse_marker_diversity(text: str) -> float:
    """Ratio of unique discourse markers to total marker instances.

    Returns 0-1.  Higher means the writer uses a variety of connectors
    rather than repeating the same one.
    """
    text_lower = text.lower()
    total = 0
    unique: set[str] = set()

    for marker in ALL_TRANSITIONS:
        pattern = r"\b" + re.escape(marker) + r"\b"
        count = len(re.findall(pattern, text_lower))
        if count > 0:
            total += count
            unique.add(marker)

    if total == 0:
        return 0.5  # neutral when no markers used
    return len(unique) / total


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


def compute_coherence_index(
    transition_density: float,
    pronoun_reference_clarity: float,
    logical_connector_coverage: float,
    lexical_cohesion: float,
    discourse_marker_diversity: float,
) -> float:
    """Weighted composite coherence index, 0-1.

    Weights:
    - transition density:          25%
    - pronoun reference clarity:   20%
    - logical connector coverage:  25%
    - lexical cohesion:            15%
    - discourse marker diversity:  15%
    """
    td_score = _score_transition_density(transition_density)

    index = (
        td_score * 0.25
        + pronoun_reference_clarity * 0.20
        + logical_connector_coverage * 0.25
        + lexical_cohesion * 0.15
        + discourse_marker_diversity * 0.15
    )
    return round(index, 4)


def classify_coherence(index: float) -> str:
    """Classify coherence index into a human-readable label."""
    if index >= 0.80:
        return "tight"
    if index >= 0.60:
        return "connected"
    if index >= 0.40:
        return "adequate"
    if index >= 0.20:
        return "loose"
    return "fragmented"


def compute_coherence_metrics(
    strokes: list[dict[str, Any]], window_size: int = 50
) -> dict[str, Any]:
    """Compute coherence metrics over a window of recent strokes.

    Parameters
    ----------
    strokes : list of stroke dicts
        Stroke records from strokes.jsonl.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict with keys:
        transition_density, pronoun_reference_clarity,
        logical_connector_coverage, lexical_cohesion,
        discourse_marker_diversity, coherence_index,
        classification, strokes_analyzed.
    """
    recent = strokes[-window_size:] if strokes else []
    texts = [_get_stroke_text(s) for s in recent if _get_stroke_text(s)]

    if not texts:
        return _empty_metrics()

    combined = " ".join(texts)

    td = compute_transition_density(combined)
    pr = compute_pronoun_reference_clarity(combined)
    lc = compute_logical_connector_coverage(combined)
    lx = compute_lexical_cohesion(combined)
    dm = compute_discourse_marker_diversity(combined)
    idx = compute_coherence_index(td, pr, lc, lx, dm)

    return {
        "transition_density": round(td, 4),
        "pronoun_reference_clarity": round(pr, 4),
        "logical_connector_coverage": round(lc, 4),
        "lexical_cohesion": round(lx, 4),
        "discourse_marker_diversity": round(dm, 4),
        "coherence_index": idx,
        "classification": classify_coherence(idx),
        "strokes_analyzed": len(texts),
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "transition_density": 0.0,
        "pronoun_reference_clarity": 0.5,
        "logical_connector_coverage": 0.5,
        "lexical_cohesion": 0.5,
        "discourse_marker_diversity": 0.5,
        "coherence_index": 0.5,
        "classification": "adequate",
        "strokes_analyzed": 0,
    }


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


def compute_coherence_trend(
    strokes: list[dict[str, Any]], window_size: int = 50
) -> list[dict[str, Any]]:
    """Compute coherence index over sliding windows.

    Returns a list of dicts with 'window_start', 'window_end',
    'coherence_index', 'classification'.
    """
    if len(strokes) < window_size:
        metrics = compute_coherence_metrics(strokes, window_size)
        return [
            {
                "window_start": 0,
                "window_end": len(strokes),
                "coherence_index": metrics["coherence_index"],
                "classification": metrics["classification"],
            }
        ]

    trends = []
    step = max(window_size // 2, 1)
    for start in range(0, len(strokes) - window_size + 1, step):
        window = strokes[start : start + window_size]
        metrics = compute_coherence_metrics(window, window_size)
        trends.append(
            {
                "window_start": start,
                "window_end": start + window_size,
                "coherence_index": metrics["coherence_index"],
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

    avg_first = sum(t["coherence_index"] for t in first_half) / len(first_half)
    avg_second = sum(t["coherence_index"] for t in second_half) / len(second_half)

    delta = avg_second - avg_first
    if delta > 0.05:
        return "improving"
    if delta < -0.05:
        return "declining"
    return "stable"


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyze_stroke_coherence(stroke: dict[str, Any]) -> dict[str, Any]:
    """Analyze coherence for a single stroke."""
    text = _get_stroke_text(stroke)
    if not text:
        return _empty_metrics()

    td = compute_transition_density(text)
    pr = compute_pronoun_reference_clarity(text)
    lc = compute_logical_connector_coverage(text)
    lx = compute_lexical_cohesion(text)
    dm = compute_discourse_marker_diversity(text)
    idx = compute_coherence_index(td, pr, lc, lx, dm)

    return {
        "transition_density": round(td, 4),
        "pronoun_reference_clarity": round(pr, 4),
        "logical_connector_coverage": round(lc, 4),
        "lexical_cohesion": round(lx, 4),
        "discourse_marker_diversity": round(dm, 4),
        "coherence_index": idx,
        "classification": classify_coherence(idx),
        "strokes_analyzed": 1,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_coherence_report(metrics: dict[str, Any]) -> str:
    """Format coherence metrics as a human-readable report."""
    if metrics["strokes_analyzed"] == 0:
        return "No strokes analyzed."

    lines = [
        f"Coherence Report ({metrics['strokes_analyzed']} strokes)",
        "=" * 50,
        f"  Coherence Index:             {metrics['coherence_index']:.4f}"
        f"  [{metrics['classification']}]",
        f"  Transition Density:          {metrics['transition_density']:.4f}"
        " (per 100 words, higher is better)",
        f"  Pronoun Reference Clarity:   {metrics['pronoun_reference_clarity']:.4f}"
        " (0-1, higher is better)",
        f"  Logical Connector Coverage:  {metrics['logical_connector_coverage']:.4f}"
        " (0-1, higher is better)",
        f"  Lexical Cohesion:            {metrics['lexical_cohesion']:.4f}"
        " (0-1, higher is better)",
        f"  Discourse Marker Diversity:  {metrics['discourse_marker_diversity']:.4f}"
        " (0-1, higher is better)",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def analyze_coherence(
    strokes_path: str | Path = "data/strokes.jsonl",
    window_size: int = 50,
) -> dict[str, Any]:
    """Analyze coherence from a strokes JSONL file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Coherence metrics.
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

    return compute_coherence_metrics(strokes, window_size)


if __name__ == "__main__":
    metrics = analyze_coherence()
    print(format_coherence_report(metrics))
