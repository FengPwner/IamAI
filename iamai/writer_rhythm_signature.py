#!/usr/bin/env python3
"""writer_rhythm_signature — analyse the rhythmic fingerprint of text.

Every writer has a rhythmic signature: a distinctive pattern of long
and short sentences, dense and sparse passages, fast and slow sections.
Some writers naturally settle into a predictable cadence — alternating
long and short, or maintaining steady medium-length sentences — while
others vary their rhythm more freely.

This module quantifies that signature by measuring sentence-length
variation, syllable density, function-word ratio, paragraph pacing,
and overall rhythmic entropy, then combines them into a single
*rhythm index* and a classification label.

========================  =============================================
metric                    meaning
========================  =============================================
total_sentences           sentences analysed
total_paragraphs          paragraphs analysed
mean_sentence_length      mean words per sentence
sentence_length_cv        coefficient of variation of sentence
                          lengths (std / mean); higher = more varied
syllable_density          mean syllables per word across all text
function_word_ratio       fraction of tokens that are function words
rhythmic_entropy          normalised entropy of the sentence-length
                          distribution (bins: short / medium / long);
                          0 = all one length, 1 = perfectly mixed
paragraph_pace_cv         coefficient of variation of paragraph
                          lengths (in sentences)
punctuation_density       punctuation marks per word
rhythm_index              composite score in [0, 1]; higher means
                          a more distinctive, varied rhythm
rhythm_label              human-readable classification
========================  =============================================

Rhythm labels
-------------

================  =====================================================
label             description
================  =====================================================
strong            high sentence-length variation and rhythmic entropy;
                  the text has a clear, dynamic cadence
moderate          moderate variation; some rhythmic patterns present
                  but not strongly pronounced
steady            low variation; sentences cluster around a similar
                  length, producing an even, measured pace
erratic           very high variation with low entropy — the rhythm
                  is unpredictable and lacks a discernible pattern
accelerating      paragraphs trend shorter over the course of the text
                  (building momentum toward the end)
decelerating      paragraphs trend longer over the course of the text
                  (slowing down, becoming more elaborate)
================  =====================================================

Usage::

    python3 -m iamai.writer_rhythm_signature              # last 200 strokes
    python3 -m iamai.writer_rhythm_signature -n 500       # last 500 strokes
    python3 -m iamai.writer_rhythm_signature --json       # full JSON report
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

# Common English function words (closed-class: articles, prepositions,
# conjunctions, pronouns, auxiliary verbs, determiners, particles)
FUNCTION_WORDS = frozenset({
    # articles
    "a", "an", "the",
    # prepositions
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "up",
    "out", "into", "over", "under", "between", "through", "about",
    "against", "along", "among", "around", "before", "after", "above",
    "below", "behind", "beside", "beyond", "despite", "during",
    "except", "inside", "near", "outside", "past", "since", "toward",
    "towards", "until", "upon", "within", "without", "across",
    # conjunctions
    "and", "but", "or", "nor", "yet", "so", "for", "because",
    "although", "though", "if", "unless", "until", "while", "whereas",
    "whether", "since", "when", "where", "how", "that",
    # pronouns
    "i", "me", "my", "mine", "myself",
    "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself",
    "she", "her", "hers", "herself",
    "it", "its", "itself",
    "we", "us", "our", "ours", "ourselves",
    "they", "them", "their", "theirs", "themselves",
    "this", "that", "these", "those",
    "who", "whom", "whose", "which", "what",
    # auxiliary verbs
    "is", "am", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "having",
    "do", "does", "did", "doing",
    "will", "would", "shall", "should", "may", "might", "must",
    "can", "could",
    # determiners & particles
    "some", "any", "no", "not", "every", "each", "all", "both",
    "few", "many", "much", "several", "enough",
    "just", "only", "even", "also", "too", "very",
})

# Sentence-length bins
_SHORT_THRESHOLD = 8    # ≤ 8 words = short
_LONG_THRESHOLD = 25    # ≥ 25 words = long

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STROKES_FILE = DATA_DIR / "strokes.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase tokenise, stripping punctuation."""
    return re.findall(r"[a-zA-Z']+", text.lower())


def _count_punctuation(text: str) -> int:
    """Count punctuation characters."""
    return sum(1 for c in text if c in ".,;:!?—–-()[]{}\"'…")


def _split_sentences(text: str) -> list[str]:
    """Naive sentence splitting on terminal punctuation."""
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p for p in parts if p]


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines."""
    parts = re.split(r'\n\s*\n', text.strip())
    return [p for p in parts if p.strip()]


def _estimate_syllables(word: str) -> int:
    """Estimate syllable count for an English word.

    Uses a simple vowel-group heuristic: count groups of consecutive
    vowels, subtract one for silent-e, with a minimum of 1.
    """
    word = word.lower().strip("'")
    if not word:
        return 0
    # Count vowel groups
    vowel_groups = len(re.findall(r'[aeiouy]+', word))
    # Silent e
    if word.endswith('e') and not word.endswith('le') and vowel_groups > 1:
        vowel_groups -= 1
    return max(1, vowel_groups)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_rhythm_signature(texts: list[str]) -> dict[str, Any]:
    """Compute rhythmic-signature metrics from a list of text strings.

    Returns a dict with all metrics listed in the module docstring.
    """
    all_sentence_lengths: list[int] = []
    all_syllable_counts: list[int] = []
    all_word_counts: list[int] = []
    function_count = 0
    total_tokens = 0
    total_punctuation = 0
    paragraph_lengths: list[int] = []  # sentences per paragraph

    for text in texts:
        paragraphs = _split_paragraphs(text)
        for para in paragraphs:
            sentences = _split_sentences(para)
            para_sentence_count = 0
            for sent in sentences:
                tokens = _tokenize(sent)
                if not tokens:
                    continue
                para_sentence_count += 1
                word_count = len(tokens)
                all_sentence_lengths.append(word_count)
                all_word_counts.append(word_count)
                total_punctuation += _count_punctuation(sent)

                for tok in tokens:
                    all_syllable_counts.append(_estimate_syllables(tok))
                    total_tokens += 1
                    if tok in FUNCTION_WORDS:
                        function_count += 1

            if para_sentence_count > 0:
                paragraph_lengths.append(para_sentence_count)

    if not all_sentence_lengths:
        return _empty_result()

    n = len(all_sentence_lengths)
    mean_sl = sum(all_sentence_lengths) / n

    # Coefficient of variation for sentence lengths
    variance = sum((x - mean_sl) ** 2 for x in all_sentence_lengths) / n
    std_sl = math.sqrt(variance)
    sl_cv = std_sl / mean_sl if mean_sl > 0 else 0.0

    # Syllable density
    total_syllables = sum(all_syllable_counts)
    total_words = len(all_syllable_counts)
    syl_density = total_syllables / total_words if total_words > 0 else 0.0

    # Function word ratio
    fw_ratio = function_count / total_tokens if total_tokens > 0 else 0.0

    # Rhythmic entropy: bin sentences into short / medium / long
    short_count = sum(1 for l in all_sentence_lengths if l <= _SHORT_THRESHOLD)
    long_count = sum(1 for l in all_sentence_lengths if l >= _LONG_THRESHOLD)
    mid_count = n - short_count - long_count

    ratios = [short_count / n, mid_count / n, long_count / n]
    entropy = -sum(r * math.log2(r) for r in ratios if r > 0)
    max_entropy = math.log2(3)
    rhythmic_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

    # Paragraph pace CV
    para_pace_cv = 0.0
    if len(paragraph_lengths) >= 2:
        mean_pl = sum(paragraph_lengths) / len(paragraph_lengths)
        if mean_pl > 0:
            pl_var = sum((x - mean_pl) ** 2 for x in paragraph_lengths) / len(paragraph_lengths)
            para_pace_cv = math.sqrt(pl_var) / mean_pl

    # Punctuation density
    punct_density = total_punctuation / total_words if total_words > 0 else 0.0

    # Composite rhythm index: weighted combination
    # High CV → more varied → higher index
    # High entropy → more balanced distribution → higher index
    # Moderate paragraph variation adds to distinctiveness
    cv_component = min(sl_cv / 1.5, 1.0)  # normalise, cap at 1
    entropy_component = rhythmic_entropy
    para_component = min(para_pace_cv / 1.0, 1.0)

    rhythm_index = (
        0.45 * cv_component +
        0.35 * entropy_component +
        0.20 * para_component
    )
    rhythm_index = min(max(rhythm_index, 0.0), 1.0)

    label = _classify(
        sl_cv, rhythmic_entropy, paragraph_lengths, rhythm_index,
    )

    return {
        "total_sentences": n,
        "total_paragraphs": len(paragraph_lengths),
        "mean_sentence_length": round(mean_sl, 2),
        "sentence_length_cv": round(sl_cv, 4),
        "syllable_density": round(syl_density, 4),
        "function_word_ratio": round(fw_ratio, 4),
        "rhythmic_entropy": round(rhythmic_entropy, 4),
        "paragraph_pace_cv": round(para_pace_cv, 4),
        "punctuation_density": round(punct_density, 4),
        "rhythm_index": round(rhythm_index, 4),
        "rhythm_label": label,
    }


def _empty_result() -> dict[str, Any]:
    """Return zeroed-out metrics when no text is available."""
    return {
        "total_sentences": 0,
        "total_paragraphs": 0,
        "mean_sentence_length": 0.0,
        "sentence_length_cv": 0.0,
        "syllable_density": 0.0,
        "function_word_ratio": 0.0,
        "rhythmic_entropy": 0.0,
        "paragraph_pace_cv": 0.0,
        "punctuation_density": 0.0,
        "rhythm_index": 0.0,
        "rhythm_label": "steady",
    }


def _classify(
    sl_cv: float,
    rhythmic_entropy: float,
    paragraph_lengths: list[int],
    rhythm_index: float,
) -> str:
    """Classify the rhythm pattern into one of 6 labels."""

    if len(paragraph_lengths) < 3:
        return "steady"

    # Check for trends: are paragraphs getting shorter or longer?
    half = len(paragraph_lengths) // 2
    first_half_mean = sum(paragraph_lengths[:half]) / half if half > 0 else 0
    second_half_mean = sum(paragraph_lengths[half:]) / (len(paragraph_lengths) - half)

    if first_half_mean > 0 and second_half_mean > 0:
        trend_ratio = second_half_mean / first_half_mean
        if trend_ratio < 0.6 and len(paragraph_lengths) >= 6:
            return "accelerating"
        if trend_ratio > 1.6 and len(paragraph_lengths) >= 6:
            return "decelerating"

    # Very high CV but low entropy → erratic (wild swings, not balanced)
    if sl_cv > 1.2 and rhythmic_entropy < 0.6:
        return "erratic"

    # High rhythm index → strong, distinctive cadence
    if rhythm_index >= 0.65:
        return "strong"

    # Very low variation → steady
    if sl_cv < 0.3 and rhythmic_entropy < 0.5:
        return "steady"

    # Moderate → moderate
    if rhythm_index >= 0.35:
        return "moderate"

    return "steady"


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


def rhythm_signature_report(n: int = 200) -> dict[str, Any]:
    """Compute rhythm signature from the on-disk strokes file."""
    texts = _load_strokes(n)
    metrics = compute_rhythm_signature(texts)
    metrics["strokes_analysed"] = len(texts)
    return metrics


def rhythm_signature_summary(metrics: dict[str, Any]) -> str:
    """Human-readable summary of rhythm signature."""
    lines = [
        f"Sentences analysed : {metrics['total_sentences']}",
        f"Paragraphs         : {metrics['total_paragraphs']}",
        f"Mean sentence len  : {metrics['mean_sentence_length']:.1f} words",
        f"Sentence length CV : {metrics['sentence_length_cv']:.3f}",
        f"Syllable density   : {metrics['syllable_density']:.3f} syl/word",
        f"Function word ratio: {metrics['function_word_ratio']:.2%}",
        f"Rhythmic entropy   : {metrics['rhythmic_entropy']:.3f}",
        f"Paragraph pace CV  : {metrics['paragraph_pace_cv']:.3f}",
        f"Punctuation density: {metrics['punctuation_density']:.3f}",
        f"Rhythm index       : {metrics['rhythm_index']:.3f}",
        f"Label              : {metrics['rhythm_label']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Analyse rhythmic signature of recent strokes.",
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

    metrics = rhythm_signature_report(args.strokes)

    if args.json:
        print(json.dumps(metrics, indent=2, ensure_ascii=False))
    else:
        print(rhythm_signature_summary(metrics))

    return 0


if __name__ == "__main__":
    sys.exit(main())
