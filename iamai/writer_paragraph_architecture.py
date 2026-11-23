#!/usr/bin/env python3
"""writer_paragraph_architecture — analyse paragraph-level structure.

Paragraphs are the building blocks of prose.  Each one is a unit of
thought: a topic introduced, developed, and concluded.  How a writer
shapes these units — their length, internal coherence, variation
across the text — reveals structural habits that sentence-level
metrics cannot capture.

This module measures the architectural skeleton of text: paragraph
length distribution, internal cohesion (how tightly sentences within
a paragraph relate), structural progression (whether paragraphs
follow a topic → development → conclusion pattern), and overall
architectural soundness.

========================  =============================================
metric                    meaning
========================  =============================================
total_paragraphs          number of paragraphs analysed
mean_paragraph_length     mean words per paragraph
median_paragraph_length   median words per paragraph
paragraph_length_cv       coefficient of variation of paragraph
                          lengths (std / mean); higher = more varied
length_progression        correlation between paragraph position
                          and length (−1 = shortening, 0 = flat,
                          +1 = lengthening)
internal_cohesion         mean cosine similarity of consecutive
                          sentence word-sets within each paragraph;
                          averaged across all paragraphs
transition_strength       mean lexical overlap between the last
                          sentence of one paragraph and the first
                          sentence of the next
topic_sentence_rate       fraction of paragraphs whose first
                          sentence contains at least one content
                          word that recurs later in the paragraph
architecture_index       composite score in [0, 1]; higher means
                          better-structured paragraphs
architecture_label        human-readable classification
========================  =============================================

Architecture labels
-------------------

================  =====================================================
label             description
================  =====================================================
well-structured   paragraphs vary in length, have strong internal
                  cohesion and clear topic sentences; the text reads
                  as carefully composed
developing        moderate structure; some paragraphs are well
                  formed while others lack clear shape
loose             low cohesion or weak topic sentences; paragraphs
                  feel like sentence collections rather than units
monolithic        very long paragraphs with low length variation;
                  the text lacks visual and structural breathing
                  room
fragmented        very short paragraphs with weak transitions; the
                  text feels choppy or list-like
uniform           paragraphs cluster around a similar length with
                  low variation; the text has a steady but
                  undifferentiated structure
================  =====================================================

Usage::

    python3 -m iamai.writer_paragraph_architecture              # last 200 strokes
    python3 -m iamai.writer_paragraph_architecture -n 500       # last 500 strokes
    python3 -m iamai.writer_paragraph_architecture --json       # full JSON report
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STOP_WORDS = frozenset({
    "a", "an", "the", "and", "but", "or", "nor", "for", "yet", "so",
    "in", "on", "at", "to", "from", "by", "of", "with", "as", "into",
    "through", "during", "before", "after", "above", "below", "between",
    "under", "over", "out", "off", "up", "down", "is", "am", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "shall", "can", "need", "dare", "ought", "used", "it", "its",
    "this", "that", "these", "those", "i", "me", "my", "we", "our",
    "you", "your", "he", "him", "his", "she", "her", "they", "them",
    "their", "what", "which", "who", "whom", "when", "where", "why",
    "how", "not", "no", "nor", "if", "then", "than", "too", "very",
    "just", "about", "also", "more", "most", "some", "any", "all",
    "each", "every", "both", "few", "many", "much", "other", "another",
    "such", "only", "own", "same", "so", "here", "there", "now",
    "once", "again", "further", "because", "until", "while", "since",
    "although", "though", "however", "therefore", "moreover",
    "furthermore", "nevertheless", "nonetheless", "accordingly",
    "consequently", "meanwhile", "otherwise", "instead", "indeed",
    "thus", "hence", "still", "already", "even", "also", "well",
    "back", "like", "make", "made", "get", "got", "go", "went",
    "gone", "come", "came", "take", "took", "give", "gave", "know",
    "knew", "think", "thought", "say", "said", "let", "see", "saw",
    "want", "look", "put", "keep", "begin", "seem", "help", "show",
    "hear", "play", "run", "move", "live", "believe", "bring",
    "happen", "write", "provide", "sit", "stand", "lose", "pay",
    "meet", "include", "continue", "set", "learn", "change", "lead",
    "understand", "watch", "follow", "stop", "create", "speak",
    "read", "allow", "add", "spend", "grow", "open", "walk", "win",
    "offer", "remember", "love", "consider", "appear", "buy", "wait",
    "serve", "die", "send", "expect", "build", "stay", "fall", "cut",
    "reach", "kill", "remain", "suggest", "raise", "pass", "sell",
    "require", "report", "decide", "pull", "develop",
})

_MIN_WORD_LEN = 3

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STROKES_FILE = DATA_DIR / "strokes.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase tokenise, stripping punctuation and short words."""
    tokens = re.findall(r"[a-zA-Z']+", text.lower())
    return [t for t in tokens if len(t) >= _MIN_WORD_LEN]


def _content_words(tokens: list[str]) -> list[str]:
    """Filter tokens to content words only (not stop words)."""
    return [t for t in tokens if t not in STOP_WORDS]


def _split_paragraphs(text: str) -> list[str]:
    """Split text on blank lines."""
    paras = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in paras if p.strip()]


def _split_sentences(text: str) -> list[str]:
    """Naive sentence splitting on terminal punctuation."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def _word_set(text: str) -> set[str]:
    """Return set of content words in text."""
    return set(_content_words(_tokenize(text)))


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _pearson_correlation(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient.  Returns 0.0 for degenerate inputs."""
    n = len(x)
    if n < 2:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    den_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_paragraph_architecture(
    texts: list[str],
) -> dict[str, Any]:
    """Compute paragraph architecture metrics for a list of stroke texts.

    Parameters
    ----------
    texts:
        List of text strings (one per stroke).

    Returns
    -------
    dict with all paragraph architecture metrics.
    """
    if not texts:
        return _empty_result()

    combined = "\n\n".join(texts)
    paragraphs = _split_paragraphs(combined)

    if not paragraphs:
        return _empty_result()

    total_paragraphs = len(paragraphs)

    # Paragraph lengths (in words)
    para_lengths = [len(_tokenize(p)) for p in paragraphs]
    mean_length = sum(para_lengths) / total_paragraphs
    sorted_lengths = sorted(para_lengths)
    if total_paragraphs % 2 == 0:
        mid = total_paragraphs // 2
        median_length = (sorted_lengths[mid - 1] + sorted_lengths[mid]) / 2
    else:
        median_length = sorted_lengths[total_paragraphs // 2]

    # Length CV
    if total_paragraphs >= 2 and mean_length > 0:
        var_length = sum((l - mean_length) ** 2 for l in para_lengths) / total_paragraphs
        std_length = math.sqrt(var_length)
        length_cv = std_length / mean_length
    else:
        length_cv = 0.0

    # Length progression: correlation between position and length
    if total_paragraphs >= 3:
        positions = list(range(total_paragraphs))
        length_progression = _pearson_correlation(
            [float(p) for p in positions],
            [float(l) for l in para_lengths],
        )
    else:
        length_progression = 0.0

    # Internal cohesion: mean consecutive-sentence Jaccard similarity
    # within each paragraph, averaged across paragraphs.
    cohesion_scores: list[float] = []
    topic_sentence_hits = 0

    for para in paragraphs:
        sentences = _split_sentences(para)
        if len(sentences) >= 2:
            for i in range(len(sentences) - 1):
                s1_words = _word_set(sentences[i])
                s2_words = _word_set(sentences[i + 1])
                cohesion_scores.append(_jaccard_similarity(s1_words, s2_words))

        # Topic sentence: first sentence contains a content word that
        # recurs in the rest of the paragraph.
        if sentences:
            first_words = _word_set(sentences[0])
            rest_words = set()
            for s in sentences[1:]:
                rest_words |= _word_set(s)
            if first_words & rest_words:
                topic_sentence_hits += 1

    internal_cohesion = (
        sum(cohesion_scores) / len(cohesion_scores) if cohesion_scores else 0.0
    )

    topic_sentence_rate = (
        topic_sentence_hits / total_paragraphs if total_paragraphs else 0.0
    )

    # Transition strength: overlap between last sentence of para N and
    # first sentence of para N+1.
    transition_scores: list[float] = []
    for i in range(len(paragraphs) - 1):
        last_sentences = _split_sentences(paragraphs[i])
        next_sentences = _split_sentences(paragraphs[i + 1])
        if last_sentences and next_sentences:
            last_words = _word_set(last_sentences[-1])
            next_words = _word_set(next_sentences[0])
            transition_scores.append(_jaccard_similarity(last_words, next_words))

    transition_strength = (
        sum(transition_scores) / len(transition_scores)
        if transition_scores else 0.0
    )

    # Architecture index: weighted composite
    # Components:
    #   cohesion (0.25) — higher is better, cap at 0.3
    #   topic_sentence_rate (0.25) — higher is better
    #   length_variation (0.20) — moderate CV (0.3–0.7) is ideal
    #   transition_strength (0.15) — higher is better, cap at 0.2
    #   length_quality (0.15) — penalise very short or very long means

    cohesion_score = min(internal_cohesion / 0.30, 1.0)
    topic_score = min(topic_sentence_rate, 1.0)
    transition_score = min(transition_strength / 0.20, 1.0)

    # Ideal length CV: 0.3–0.7 is best; below = uniform, above = erratic
    if 0.30 <= length_cv <= 0.70:
        length_var_score = 1.0
    elif length_cv < 0.30:
        length_var_score = length_cv / 0.30
    else:
        length_var_score = max(0.0, 1.0 - (length_cv - 0.70) / 0.70)

    # Ideal mean length: 30–100 words per paragraph
    if 30 <= mean_length <= 100:
        length_quality = 1.0
    elif mean_length < 30:
        length_quality = mean_length / 30
    else:
        length_quality = max(0.0, 1.0 - (mean_length - 100) / 200)

    architecture_index = (
        0.25 * cohesion_score
        + 0.25 * topic_score
        + 0.20 * length_var_score
        + 0.15 * transition_score
        + 0.15 * length_quality
    )
    architecture_index = round(max(0.0, min(1.0, architecture_index)), 4)

    architecture_label = _classify(
        architecture_index, length_cv, internal_cohesion,
        topic_sentence_rate, mean_length, total_paragraphs,
    )

    return {
        "total_paragraphs": total_paragraphs,
        "mean_paragraph_length": round(mean_length, 1),
        "median_paragraph_length": round(median_length, 1),
        "paragraph_length_cv": round(length_cv, 4),
        "length_progression": round(length_progression, 4),
        "internal_cohesion": round(internal_cohesion, 4),
        "transition_strength": round(transition_strength, 4),
        "topic_sentence_rate": round(topic_sentence_rate, 4),
        "architecture_index": architecture_index,
        "architecture_label": architecture_label,
    }


def _empty_result() -> dict[str, Any]:
    """Return a zeroed-out result when there is no text to analyse."""
    return {
        "total_paragraphs": 0,
        "mean_paragraph_length": 0.0,
        "median_paragraph_length": 0.0,
        "paragraph_length_cv": 0.0,
        "length_progression": 0.0,
        "internal_cohesion": 0.0,
        "transition_strength": 0.0,
        "topic_sentence_rate": 0.0,
        "architecture_index": 0.0,
        "architecture_label": "loose",
    }


def _classify(
    arch_index: float,
    length_cv: float,
    cohesion: float,
    topic_rate: float,
    mean_length: float,
    n_paragraphs: int,
) -> str:
    """Classify the text's paragraph architecture."""
    if n_paragraphs == 0:
        return "loose"

    # Monolithic: long paragraphs, low variation
    if mean_length > 120 and length_cv < 0.30:
        return "monolithic"

    # Fragmented: very short paragraphs
    if mean_length < 20 and length_cv < 0.50:
        return "fragmented"

    # Well-structured: strong metrics across the board
    if arch_index >= 0.65 and cohesion >= 0.10 and topic_rate >= 0.50:
        return "well-structured"

    # Uniform: low CV, moderate length
    if length_cv < 0.25 and 25 <= mean_length <= 120:
        return "uniform"

    # Loose: weak cohesion or topic sentences
    if cohesion < 0.05 or topic_rate < 0.30:
        return "loose"

    # Developing: moderate
    if arch_index >= 0.40:
        return "developing"

    return "loose"


# ---------------------------------------------------------------------------
# On-disk integration
# ---------------------------------------------------------------------------

def _load_strokes(n: int = 200) -> list[str]:
    """Load the last *n* stroke texts from the JSONL file."""
    if not STROKES_FILE.exists():
        return []
    lines = STROKES_FILE.read_text(encoding="utf-8").strip().splitlines()
    texts: list[str] = []
    for line in lines[-n:]:
        try:
            obj = json.loads(line)
            t = obj.get("text", "")
            if t:
                texts.append(t)
        except json.JSONDecodeError:
            continue
    return texts


def architecture_report(n: int = 200) -> dict[str, Any]:
    """Compute paragraph architecture from the on-disk strokes file."""
    texts = _load_strokes(n)
    metrics = compute_paragraph_architecture(texts)
    metrics["strokes_analysed"] = len(texts)
    return metrics


def architecture_summary(metrics: dict[str, Any]) -> str:
    """Human-readable summary of paragraph architecture metrics."""
    lines = [
        f"Paragraphs       : {metrics['total_paragraphs']}",
        f"Mean length      : {metrics['mean_paragraph_length']:.1f} words",
        f"Median length    : {metrics['median_paragraph_length']:.1f} words",
        f"Length CV        : {metrics['paragraph_length_cv']:.3f}",
        f"Length progression: {metrics['length_progression']:.3f}",
        f"Internal cohesion: {metrics['internal_cohesion']:.3f}",
        f"Transition str.  : {metrics['transition_strength']:.3f}",
        f"Topic sent. rate : {metrics['topic_sentence_rate']:.2%}",
        f"Architecture idx : {metrics['architecture_index']:.3f}",
        f"Label            : {metrics['architecture_label']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Analyse paragraph architecture in recent strokes.",
    )
    ap.add_argument(
        "-n", "--strokes", type=int, default=200,
        help="number of recent strokes to analyse (default: 200)",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="output full JSON report",
    )
    args = ap.parse_args(argv)

    metrics = architecture_report(args.strokes)

    if args.json:
        print(json.dumps(metrics, indent=2, ensure_ascii=False))
    else:
        print(architecture_summary(metrics))

    return 0


if __name__ == "__main__":
    sys.exit(main())
