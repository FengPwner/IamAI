#!/usr/bin/env python3
"""writer_cohesion — measure how well sentences connect to one another.

Cohesion is the glue that holds a text together at the sentence level.
A cohesive text flows: each sentence picks up where the last left off,
transitions signal direction changes, pronouns resolve cleanly, and
lexical threads carry meaning across sentence boundaries.

A text with poor cohesion feels like a list of unrelated statements,
even if each sentence is individually well-written. A text with strong
cohesion reads as a unified argument, narrative, or exposition.

This module is orthogonal to the other writer metrics:

- **coherence** tracks whether the *overall logical flow* makes sense.
  Coherence is macro-structural; cohesion is micro-structural. A text
  can be coherent (the argument progresses logically) while having weak
  cohesion (each step is a jump rather than a slide).

- **readability** tracks whether prose is *easy to parse*. Readability
  is about sentence-level complexity; cohesion is about sentence-to-
  sentence *connection*. Simple sentences can be cohesive (if well-
  linked) or disjointed (if not).

- **signal_clarity** tracks whether strokes are *substantively unique*.
  Signal clarity is about information novelty across strokes; cohesion
  is about connection quality within a stroke.

- **topic_drift** tracks whether the text *stays on subject*. Topic
  drift is about thematic focus; cohesion is about connective tissue.
  A text can stay on topic while being poorly connected (a list of
  facts about one subject).

- **voice_consistency** tracks whether the narrator's identity stays
  stable. Voice is about *who speaks*; cohesion is about *how sentences
  link*.

Cohesion asks: **does each sentence connect to its neighbors, or does
the reader have to leap across gaps?**

Four signals are tracked:

1. **Transition density** — frequency of explicit connective words and
   phrases per hundred words: "however", "therefore", "moreover", "in
   contrast", "as a result", "for example", "similarly", "consequently",
   "furthermore", "nevertheless", "in addition", "on the other hand",
   "that is", "specifically", "in other words", "for instance",
   "likewise", "accordingly", "hence", "thus", "yet", "still",
   "meanwhile", "instead", "otherwise". These words tell the reader
   *how* the next sentence relates to the previous one.

2. **Referential continuity** — fraction of sentences that contain at
   least one backward-reference: pronouns (he, she, it, they, this,
   that, these, those), definite articles on previously-mentioned nouns,
   or demonstrative phrases ("this approach", "that idea"). A sentence
   with referential continuity reaches back to prior context; a sentence
   without it starts fresh.

3. **Lexical chain strength** — average Jaccard similarity of content
   words (nouns, verbs, adjectives, adverbs) between consecutive
   sentence pairs. Higher overlap means lexical threads persist across
   boundaries; lower overlap means each sentence introduces entirely new
   vocabulary.

4. **Structural parallelism** — fraction of consecutive sentence pairs
   that share a syntactic opening pattern (e.g., both start with a
   subject noun phrase, or both start with a prepositional phrase).
   Moderate parallelism aids readability; extreme parallelism suggests
   mechanical repetition.

The **cohesion_index** is computed as a weighted composite:

    index = transition_norm       * 0.25
          + referential_norm      * 0.30
          + lexical_chain_avg     * 0.25
          + (1 - |parallel - 0.5| * 2) * 0.20

The parallelism component is centered at 0.5: too little parallelism
(0.0) or too much (1.0) both reduce the score. The ideal is moderate
structural echo.

Classified as:

- **seamless** (>= 0.75): sentences connect fluidly; transitions are
  present, references resolve, lexical threads persist.

- **connected** (0.60 <= index < 0.75): mostly well-linked with
  occasional gaps where the reader must infer the connection.

- **choppy** (0.45 <= index < 0.60): noticeable gaps between sentences;
  transitions are sparse and references are ambiguous.

- **fragmented** (0.30 <= index < 0.45): sentences feel like isolated
  statements; the text reads as a list rather than a flow.

- **disjointed** (index < 0.30): no discernible connective tissue;
  each sentence could be shuffled without the reader noticing.

Reference: Halliday & Hasan (1976), *Cohesion in English*. The five
types of cohesive ties — reference, substitution, ellipsis,
conjunction, lexical cohesion — are the theoretical basis for this
module's four signals.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Transition words and phrases — explicit connectives
# ---------------------------------------------------------------------------

TRANSITION_PHRASES: list[re.Pattern] = [
    # Single-word connectives
    re.compile(r"\bhowever\b", re.IGNORECASE),
    re.compile(r"\btherefore\b", re.IGNORECASE),
    re.compile(r"\bmoreover\b", re.IGNORECASE),
    re.compile(r"\bfurthermore\b", re.IGNORECASE),
    re.compile(r"\bnevertheless\b", re.IGNORECASE),
    re.compile(r"\bnonetheless\b", re.IGNORECASE),
    re.compile(r"\bconsequently\b", re.IGNORECASE),
    re.compile(r"\baccordingly\b", re.IGNORECASE),
    re.compile(r"\bsimilarly\b", re.IGNORECASE),
    re.compile(r"\blikewise\b", re.IGNORECASE),
    re.compile(r"\bmeanwhile\b", re.IGNORECASE),
    re.compile(r"\binstead\b", re.IGNORECASE),
    re.compile(r"\botherwise\b", re.IGNORECASE),
    re.compile(r"\bhence\b", re.IGNORECASE),
    re.compile(r"\bthus\b", re.IGNORECASE),
    # Multi-word connectives
    re.compile(r"\bin\s+contrast\b", re.IGNORECASE),
    re.compile(r"\bas\s+a\s+result\b", re.IGNORECASE),
    re.compile(r"\bfor\s+example\b", re.IGNORECASE),
    re.compile(r"\bfor\s+instance\b", re.IGNORECASE),
    re.compile(r"\bin\s+addition\b", re.IGNORECASE),
    re.compile(r"\bon\s+the\s+other\s+hand\b", re.IGNORECASE),
    re.compile(r"\bthat\s+is\b", re.IGNORECASE),
    re.compile(r"\bin\s+other\s+words\b", re.IGNORECASE),
    re.compile(r"\bspecifically\b", re.IGNORECASE),
    re.compile(r"\bin\s+particular\b", re.IGNORECASE),
    re.compile(r"\bon\s+the\s+contrary\b", re.IGNORECASE),
    re.compile(r"\bas\s+a\s+consequence\b", re.IGNORECASE),
    re.compile(r"\bby\s+contrast\b", re.IGNORECASE),
    re.compile(r"\bin\s+the\s+same\s+way\b", re.IGNORECASE),
    re.compile(r"\bto\s+that\s+end\b", re.IGNORECASE),
    re.compile(r"\bwhat'?s\s+more\b", re.IGNORECASE),
    # Clause-level connectives
    re.compile(r"\bnot\s+only\b", re.IGNORECASE),
    re.compile(r"\bbut\s+also\b", re.IGNORECASE),
    re.compile(r"\bso\s+that\b", re.IGNORECASE),
    re.compile(r"\beven\s+though\b", re.IGNORECASE),
    re.compile(r"\bnow\s+that\b", re.IGNORECASE),
    re.compile(r"\bjust\s+as\b", re.IGNORECASE),
    # Adversative short forms
    re.compile(r"\byet\b", re.IGNORECASE),
    re.compile(r"\bstill\b", re.IGNORECASE),
    re.compile(r"\binstead\b", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Backward-reference markers — pronouns, demonstratives, definite articles
# ---------------------------------------------------------------------------

BACKREF_PATTERNS: list[re.Pattern] = [
    # Pronouns (personal, possessive, reflexive)
    re.compile(r"\bhe\b", re.IGNORECASE),
    re.compile(r"\bshe\b", re.IGNORECASE),
    re.compile(r"\bit\b", re.IGNORECASE),
    re.compile(r"\bthey\b", re.IGNORECASE),
    re.compile(r"\bthem\b", re.IGNORECASE),
    re.compile(r"\bhis\b", re.IGNORECASE),
    re.compile(r"\bher\b", re.IGNORECASE),
    re.compile(r"\bits\b", re.IGNORECASE),
    re.compile(r"\btheir\b", re.IGNORECASE),
    re.compile(r"\bhim\b", re.IGNORECASE),
    re.compile(r"\bhimself\b", re.IGNORECASE),
    re.compile(r"\bherself\b", re.IGNORECASE),
    re.compile(r"\bitself\b", re.IGNORECASE),
    re.compile(r"\bthemselves\b", re.IGNORECASE),
    # Demonstratives
    re.compile(r"\bthis\b", re.IGNORECASE),
    re.compile(r"\bthat\b", re.IGNORECASE),
    re.compile(r"\bthese\b", re.IGNORECASE),
    re.compile(r"\bthose\b", re.IGNORECASE),
    # Demonstrative + noun phrases
    re.compile(r"\bthis\s+\w+", re.IGNORECASE),
    re.compile(r"\bthat\s+\w+", re.IGNORECASE),
    re.compile(r"\bsuch\s+\w+", re.IGNORECASE),
    re.compile(r"\bthe\s+same\b", re.IGNORECASE),
    re.compile(r"\bthe\s+(?:former|latter)\b", re.IGNORECASE),
    # Anaphoric expressions
    re.compile(r"\bthe\s+above\b", re.IGNORECASE),
    re.compile(r"\bthe\s+aforementioned\b", re.IGNORECASE),
    re.compile(r"\bsaid\s+\w+", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Content word filter — common function words to exclude
# ---------------------------------------------------------------------------

FUNCTION_WORDS: set[str] = {
    "a", "an", "the", "is", "am", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "shall", "should", "may", "might", "must", "can", "could", "to",
    "of", "in", "on", "at", "by", "for", "with", "from", "about",
    "between", "through", "during", "before", "after", "above", "below",
    "up", "down", "out", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "when", "where", "why", "how",
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "just", "because", "but", "and", "or",
    "if", "while", "as", "that", "this", "these", "those", "what",
    "which", "who", "whom", "whose", "i", "me", "my", "we", "us",
    "our", "you", "your", "he", "him", "his", "she", "her", "it",
    "its", "they", "them", "their",
}

# ---------------------------------------------------------------------------
# Sentence splitter
# ---------------------------------------------------------------------------

SENTENCE_SPLITTER = re.compile(
    r'(?<=[.!?])\s+(?=[A-Z\"])',
)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using punctuation + capitalization cues."""
    raw = SENTENCE_SPLITTER.split(text.strip())
    return [s.strip() for s in raw if len(s.strip()) > 5]


def _content_words(sentence: str) -> set[str]:
    """Extract content words (excluding function words and short tokens)."""
    tokens = re.findall(r"[a-z']+", sentence.lower())
    return {t for t in tokens if t not in FUNCTION_WORDS and len(t) > 2}


def _word_count(text: str) -> int:
    """Count words in text."""
    return len(text.split())


# ---------------------------------------------------------------------------
# Signal 1: Transition density
# ---------------------------------------------------------------------------

def count_transitions(text: str) -> int:
    """Count the number of explicit transition words/phrases in text."""
    count = 0
    for pattern in TRANSITION_PHRASES:
        count += len(pattern.findall(text))
    return count


def compute_transition_density(text: str) -> float:
    """Transitions per hundred words, capped at 1.0 for normalization.

    Typical range: 0–8 per hundred words in well-written prose.
    We normalize with a soft cap: density = min(raw / 5.0, 1.0).
    """
    wc = _word_count(text)
    if wc == 0:
        return 0.0
    raw = (count_transitions(text) / wc) * 100
    return min(raw / 5.0, 1.0)


# ---------------------------------------------------------------------------
# Signal 2: Referential continuity
# ---------------------------------------------------------------------------

def _sentence_has_backref(sentence: str) -> bool:
    """Check if a sentence contains at least one backward-reference."""
    for pattern in BACKREF_PATTERNS:
        if pattern.search(sentence):
            return True
    return False


def compute_referential_continuity(text: str) -> float:
    """Fraction of sentences containing a backward-reference.

    Higher = more sentences reach back to prior context.
    """
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 0.0
    # Skip the first sentence (nothing to refer back to)
    rest = sentences[1:]
    count = sum(1 for s in rest if _sentence_has_backref(s))
    return count / len(rest)


# ---------------------------------------------------------------------------
# Signal 3: Lexical chain strength
# ---------------------------------------------------------------------------

def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two sets."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def compute_lexical_chain_strength(text: str) -> float:
    """Average Jaccard similarity of content words between consecutive
    sentence pairs. Higher = stronger lexical threads across boundaries.
    """
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 0.0
    pairs = []
    for i in range(len(sentences) - 1):
        words_a = _content_words(sentences[i])
        words_b = _content_words(sentences[i + 1])
        pairs.append(_jaccard_similarity(words_a, words_b))
    return sum(pairs) / len(pairs) if pairs else 0.0


# ---------------------------------------------------------------------------
# Signal 4: Structural parallelism
# ---------------------------------------------------------------------------

OPENING_PATTERNS = [
    # Order matters: specific patterns first, generic fallback last
    re.compile(r'^\s*(?:However|Therefore|Moreover|Furthermore|Thus|Hence)\b'),  # 0: Connective
    re.compile(r'^\s*(?:In|On|At|By|With|For|From|During|After|Before)\s'),  # 1: Prep phrase
    re.compile(r'^\s*(?:If|When|While|Although|Because|Since|Unless)\b'),  # 2: Subordinate
    re.compile(r'^\s*(?:He|She|It|They|We|I)\b'),  # 3: Pronoun-first
    re.compile(r'^\s*(?:This|That|These|Those)\b'),  # 4: Demonstrative
    re.compile(r'^\s*[A-Z][a-z]+\s+[a-z]+'),       # 5: Subject-first (fallback)
]


def _classify_opening(sentence: str) -> int:
    """Classify sentence opening into a structural category (0-5)."""
    for idx, pattern in enumerate(OPENING_PATTERNS):
        if pattern.match(sentence):
            return idx
    return -1  # uncategorized


def compute_structural_parallelism(text: str) -> float:
    """Fraction of consecutive sentence pairs sharing the same opening
    pattern. Returns raw parallelism (0.0–1.0).

    The cohesion score for parallelism is: 1 - |parallelism - 0.5| * 2
    This penalizes both extremes (no parallelism and total repetition).
    """
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 0.0
    matches = 0
    total = 0
    for i in range(len(sentences) - 1):
        cat_a = _classify_opening(sentences[i])
        cat_b = _classify_opening(sentences[i + 1])
        if cat_a >= 0 and cat_b >= 0:
            total += 1
            if cat_a == cat_b:
                matches += 1
    if total == 0:
        return 0.5  # neutral when openings can't be classified
    return matches / total


def _parallelism_score(parallelism: float) -> float:
    """Convert raw parallelism to a cohesion contribution score.

    Ideal is 0.5 (moderate echo); both 0.0 and 1.0 are penalized.
    """
    return 1.0 - abs(parallelism - 0.5) * 2.0


# ---------------------------------------------------------------------------
# Composite: cohesion index
# ---------------------------------------------------------------------------

def compute_cohesion_metrics(text: str) -> dict[str, Any]:
    """Compute all cohesion signals and the composite index.

    Parameters
    ----------
    text : str
        The text to analyze. Should be at least two sentences.

    Returns
    -------
    dict with keys:
        transition_density : float (0.0–1.0)
        referential_continuity : float (0.0–1.0)
        lexical_chain_strength : float (0.0–1.0)
        structural_parallelism : float (0.0–1.0, raw)
        parallelism_score : float (0.0–1.0, centered)
        cohesion_index : float (0.0–1.0)
        cohesion_class : str
        sentence_count : int
        word_count : int
    """
    if not text or not text.strip():
        return _empty_metrics()

    sentences = _split_sentences(text)
    wc = _word_count(text)

    if len(sentences) < 2:
        return _empty_metrics()

    transition = compute_transition_density(text)
    referential = compute_referential_continuity(text)
    lexical = compute_lexical_chain_strength(text)
    parallelism = compute_structural_parallelism(text)
    par_score = _parallelism_score(parallelism)

    # Weighted composite
    index = (
        transition * 0.25
        + referential * 0.30
        + lexical * 0.25
        + par_score * 0.20
    )

    return {
        "transition_density": round(transition, 4),
        "referential_continuity": round(referential, 4),
        "lexical_chain_strength": round(lexical, 4),
        "structural_parallelism": round(parallelism, 4),
        "parallelism_score": round(par_score, 4),
        "cohesion_index": round(index, 4),
        "cohesion_class": _classify(index),
        "sentence_count": len(sentences),
        "word_count": wc,
    }


def _empty_metrics() -> dict[str, Any]:
    """Return zeroed-out metrics for empty or too-short text."""
    return {
        "transition_density": 0.0,
        "referential_continuity": 0.0,
        "lexical_chain_strength": 0.0,
        "structural_parallelism": 0.0,
        "parallelism_score": 0.0,
        "cohesion_index": 0.0,
        "cohesion_class": "disjointed",
        "sentence_count": 0,
        "word_count": 0,
    }


def _classify(index: float) -> str:
    """Map cohesion index to a classification label."""
    if index >= 0.75:
        return "seamless"
    elif index >= 0.60:
        return "connected"
    elif index >= 0.45:
        return "choppy"
    elif index >= 0.30:
        return "fragmented"
    else:
        return "disjointed"


# ---------------------------------------------------------------------------
# Trend analysis — compare cohesion across text segments
# ---------------------------------------------------------------------------

def compute_cohesion_trend(
    text: str, segments: int = 4
) -> dict[str, Any]:
    """Split text into segments and compute cohesion trend.

    Parameters
    ----------
    text : str
        The full text.
    segments : int
        Number of segments to split into.

    Returns
    -------
    dict with keys:
        trend : str ("improving" | "stable" | "declining" | "insufficient_data")
        segment_scores : list[float]
        first_half_avg : float
        second_half_avg : float
    """
    sentences = _split_sentences(text)
    if len(sentences) < segments * 2:
        return {
            "trend": "insufficient_data",
            "segment_scores": [],
            "first_half_avg": 0.0,
            "second_half_avg": 0.0,
        }

    chunk_size = len(sentences) // segments
    segment_scores = []
    for i in range(segments):
        start = i * chunk_size
        end = start + chunk_size if i < segments - 1 else len(sentences)
        chunk = " ".join(sentences[start:end])
        metrics = compute_cohesion_metrics(chunk)
        segment_scores.append(metrics["cohesion_index"])

    mid = len(segment_scores) // 2
    first_half = sum(segment_scores[:mid]) / mid if mid > 0 else 0.0
    second_half = sum(segment_scores[mid:]) / (len(segment_scores) - mid) if (len(segment_scores) - mid) > 0 else 0.0
    delta = second_half - first_half

    if delta > 0.05:
        trend = "improving"
    elif delta < -0.05:
        trend = "declining"
    else:
        trend = "stable"

    return {
        "trend": trend,
        "segment_scores": [round(s, 4) for s in segment_scores],
        "first_half_avg": round(first_half, 4),
        "second_half_avg": round(second_half, 4),
    }


def classify_trend(first_metrics: dict, second_metrics: dict) -> str:
    """Compare two sets of metrics and classify the trend.

    Parameters
    ----------
    first_metrics : dict
        Metrics from the earlier text segment.
    second_metrics : dict
        Metrics from the later text segment.

    Returns
    -------
    str : "improving" | "stable" | "declining"
    """
    delta = second_metrics.get("cohesion_index", 0) - first_metrics.get("cohesion_index", 0)
    if delta > 0.05:
        return "improving"
    elif delta < -0.05:
        return "declining"
    return "stable"


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_cohesion_report(metrics: dict[str, Any]) -> str:
    """Format metrics into a human-readable report.

    Parameters
    ----------
    metrics : dict
        Output from compute_cohesion_metrics.

    Returns
    -------
    str : formatted report
    """
    lines = [
        f"Cohesion Analysis: {metrics['cohesion_class'].upper()}",
        f"  Index: {metrics['cohesion_index']:.2f}",
        f"  Transition density:    {metrics['transition_density']:.2f}",
        f"  Referential continuity: {metrics['referential_continuity']:.2f}",
        f"  Lexical chain strength: {metrics['lexical_chain_strength']:.2f}",
        f"  Structural parallelism: {metrics['structural_parallelism']:.2f} "
        f"(score: {metrics['parallelism_score']:.2f})",
        f"  Sentences: {metrics['sentence_count']}, "
        f"Words: {metrics['word_count']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSONL integration — read strokes and analyze
# ---------------------------------------------------------------------------

def analyze_strokes(strokes_path: str | Path, last_n: int = 10) -> list[dict]:
    """Analyze the last N strokes from the strokes JSONL file.

    Parameters
    ----------
    strokes_path : path to data/strokes.jsonl
    last_n : number of recent strokes to analyze

    Returns
    -------
    list of dicts, each with stroke metadata + cohesion metrics
    """
    path = Path(strokes_path)
    if not path.exists():
        return []

    lines = path.read_text().strip().split("\n")
    recent = lines[-last_n:] if len(lines) >= last_n else lines

    results = []
    for line in recent:
        try:
            stroke = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = stroke.get("content", "")
        if not content:
            continue
        metrics = compute_cohesion_metrics(content)
        metrics["stroke_type"] = stroke.get("type", "unknown")
        metrics["stroke_id"] = stroke.get("id", "")
        results.append(metrics)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    repo = Path(__file__).resolve().parent.parent

    if len(sys.argv) > 1 and sys.argv[1] == "--analyze":
        strokes_file = repo / "data" / "strokes.jsonl"
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        results = analyze_strokes(strokes_file, last_n=n)
        for r in results:
            print(f"[{r.get('stroke_type', '?')}] {r['cohesion_class']} "
                  f"({r['cohesion_index']:.2f}) — "
                  f"trans={r['transition_density']:.2f} "
                  f"ref={r['referential_continuity']:.2f} "
                  f"lex={r['lexical_chain_strength']:.2f} "
                  f"par={r['parallelism_score']:.2f}")
    else:
        # Demo with sample text
        sample = (
            "The writer sat at the desk and opened the notebook. "
            "However, the page remained blank for several minutes. "
            "Therefore, the writer decided to start with a simple observation. "
            "The room was quiet, except for the hum of the ventilation. "
            "Moreover, the light from the window cast long shadows across the floor. "
            "This observation led to another: the shadows moved as the sun descended. "
            "Consequently, the writer began to write about time and its passage. "
            "The notebook filled with words, each one building on the last. "
            "Furthermore, the act of writing itself became the subject. "
            "In the end, the writer had produced three pages of connected thought."
        )
        metrics = compute_cohesion_metrics(sample)
        print(format_cohesion_report(metrics))

        print("\nTrend analysis:")
        trend = compute_cohesion_trend(sample, segments=3)
        print(f"  Trend: {trend['trend']}")
        print(f"  Scores: {trend['segment_scores']}")
