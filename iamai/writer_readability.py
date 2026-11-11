#!/usr/bin/env python3
"""writer_readability — is the text easy to read and understand?

Readability is about *access*.  Clear prose lets the reader focus on
ideas rather than decoding sentences.  Dense prose forces the reader to
work harder — re-reading, parsing nested clauses, and translating
abstractions back into concrete meaning.

This module is orthogonal to the other writer metrics:

- **prose_rhythm** tracks *variation* in sentence length.  A text can
  have excellent rhythm (alternating long and short sentences) while
  being hard to read (every sentence uses rare words and abstract
  nouns).  Rhythm is about pacing; readability is about accessibility.

- **vocabulary_richness** tracks *diversity* of word choice.  A text
  can use rich vocabulary while remaining readable (precise words are
  often simpler than vague ones).  Conversely, a text can use a narrow
  vocabulary while being impenetrable (jargon repeated endlessly).

- **coherence** tracks whether consecutive ideas *connect logically*.
  A text can be coherent (one sustained argument) while being dense
  (every sentence requires effort).  Coherence is about connection;
  readability is about effort.

- **grounding_density** tracks whether abstract claims are *anchored
  with concrete evidence*.  A text can be well-grounded while being
  hard to read (lots of numbers in long, complex sentences).

- **signal_clarity** tracks whether strokes are *substantively
  different* from their neighbours.  Clarity is about uniqueness;
  readability is about ease of comprehension.

Readability asks specifically: **how much effort does the reader need
to invest to understand each sentence?**

Four signals are tracked:

1. **Sentence length appropriateness** — sentences between 8 and 22
   words are easiest to read.  Shorter sentences feel choppy; longer
   ones require working memory to hold the beginning while reaching
   the end.  Score is 1.0 for ideal lengths and degrades as sentences
   deviate.

2. **Complex word ratio** — the fraction of words with three or more
   syllables.  Complex words are not wrong, but a high density of them
   signals that the writer is choosing Latinate abstractions over
   Anglo-Saxon concreteness.  "Implementation" where "doing" would
   suffice.

3. **Hedge word ratio** — the fraction of words that weaken
   assertions: "perhaps", "maybe", "possibly", "somewhat", "rather",
   "quite", "fairly", "arguably", "seemingly".  Some hedging shows
   nuance; excessive hedging makes prose timid and hard to pin down.
   The penalty is U-shaped: zero hedges and many hedges both score
   lower than a moderate amount.

4. **Nominalization ratio** — the fraction of words that are abstract
   nouns (ending in -tion, -ment, -ness, -ity, -ence, -ance).
   Nominalizations turn actions into things: "the implementation of
   the solution" instead of "we solved it".  Each nominalization adds
   cognitive load.

From these signals a session-level **readability_index** is computed
and classified:

==============  ============================================================
class           meaning
==============  ============================================================
clear           index >= 0.80 — prose is easy and pleasant to read; the
                reader grasps meaning on first pass without re-reading
transparent     0.65 <= index < 0.80 — mostly clear; occasional complex
                sentences or jargon but the reader stays oriented
serviceable     0.50 <= index < 0.65 — readable with effort; the reader
                must slow down for some passages but can follow along
dense           0.35 <= index < 0.50 — heavy prose; frequent re-reading
                needed; long sentences packed with abstract vocabulary
impenetrable    index < 0.35 — the reader must decode every sentence;
                the prose is a barrier rather than a bridge
==============  ============================================================

Public API
----------
- ``analyze_stroke_readability(stroke)`` — analyze one stroke
- ``compute_readability_metrics(texts)`` — analyze a list of text samples
- ``format_readability_report(metrics)`` — format metrics as report

Constants
---------
- ``HEDGE_WORDS`` — set of recognized hedge words
- ``NOMINALIZATION_SUFFIXES`` — suffixes that identify abstract nouns
- ``IDEAL_SENTENCE_RANGE`` — (min, max) ideal word count per sentence
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEDGE_WORDS: frozenset = frozenset({
    "perhaps", "maybe", "possibly", "somewhat", "rather",
    "quite", "fairly", "arguably", "seemingly", "apparently",
    "presumably", "roughly", "mostly", "generally", "largely",
    "slightly", "mildly", "marginally", "ostensibly", "supposedly",
    "might", "could", "would",
})

NOMINALIZATION_SUFFIXES: Tuple[str, ...] = (
    "tion", "sion", "ment", "ness", "ity",
    "ence", "ance", "ism", "ist",
)

IDEAL_SENTENCE_RANGE: Tuple[int, int] = (8, 22)

# Minimum word length for nominalization detection (avoid short words
# like "men" matching "-ment")
_MIN_NOMINALIZATION_LEN = 5


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on '.', '!', '?', or newlines."""
    if not text or not text.strip():
        return []
    parts = re.split(r'[.!?\n]+', text)
    return [s.strip() for s in parts if s.strip()]


def _split_words(text: str) -> List[str]:
    """Split text into lowercase words, stripping punctuation."""
    if not text:
        return []
    tokens = re.findall(r"[a-zA-Z'-]+", text.lower())
    return [t.strip("'") for t in tokens if t.strip("'")]


def _count_syllables(word: str) -> int:
    """Estimate syllable count for an English word.

    Uses the standard heuristic: count vowel groups, subtract silent 'e',
    add back if the word ends in 'le' preceded by a consonant.
    Minimum return is 1 for non-empty words.
    """
    if not word:
        return 0
    word = word.lower().strip()
    if len(word) <= 2:
        return 1

    # Count vowel groups
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for char in word:
        is_vowel = char in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel

    # Adjust for silent 'e'.  The 'e' is its own syllable when two or
    # more consonants separate it from the previous vowel (e.g. "cre-a-te"
    # → 't' + 'a' between them).  With only one intervening consonant
    # (e.g. "make" → 'k' between 'a' and 'e'), the 'e' is silent.
    if word.endswith("e") and not word.endswith("le"):
        # Count consecutive consonants before the final 'e'
        cons_run = 0
        for i in range(len(word) - 2, -1, -1):
            if word[i] not in vowels:
                cons_run += 1
            else:
                break
        if cons_run >= 2:
            pass  # 'e' is its own syllable
        else:
            count -= 1

    # Adjust for '-le' ending preceded by consonant.  The final 'e'
    # was already counted as a vowel group but is actually silent; the
    # '-le' still forms a syllable (/əl/).  Net effect: no change to
    # the vowel-group count (the 'e' group shifts from 'e' to 'l+e').
    # Only adjust if the silent-e block did not already subtract.
    if word.endswith("le") and len(word) > 2 and word[-3] not in vowels:
        # The 'e' was counted as a vowel group.  Since the silent-e
        # block does not run for 'le' words, no adjustment is needed —
        # the count is already correct as the vowel-group count.
        pass

    return max(1, count)


def _count_complex_words(words: List[str]) -> int:
    """Count words with 3 or more syllables."""
    return sum(1 for w in words if _count_syllables(w) >= 3)


def _count_hedge_words(words: List[str]) -> int:
    """Count hedge / weakening words."""
    return sum(1 for w in words if w in HEDGE_WORDS)


def _count_nominalizations(words: List[str]) -> int:
    """Count abstract nouns by suffix, requiring minimum word length."""
    count = 0
    for w in words:
        if len(w) < _MIN_NOMINALIZATION_LEN:
            continue
        for suffix in NOMINALIZATION_SUFFIXES:
            if w.endswith(suffix):
                count += 1
                break
    return count


def _get_stroke_text(stroke: Dict[str, Any]) -> str:
    """Extract text content from a stroke dict."""
    for key in ("text", "content", "body"):
        val = stroke.get(key)
        if val and isinstance(val, str):
            return val
    return ""


# ---------------------------------------------------------------------------
# Signal computations
# ---------------------------------------------------------------------------


def compute_sentence_length_score(sentences: List[str]) -> float:
    """Score sentence lengths against the ideal range.

    Returns a float 0.0–1.0.  Sentences within the ideal range (8–22
    words) score 1.0; deviations are penalized proportionally.
    """
    if not sentences:
        return 0.0

    lo, hi = IDEAL_SENTENCE_RANGE
    scores = []
    for sent in sentences:
        words = _split_words(sent)
        n = len(words)
        if n == 0:
            continue
        if lo <= n <= hi:
            scores.append(1.0)
        elif n < lo:
            # Too short — mild penalty (short is better than too long)
            scores.append(n / lo)
        else:
            # Too long — stronger penalty
            overshoot = n - hi
            penalty = overshoot / hi
            scores.append(max(0.0, 1.0 - penalty))

    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def compute_complex_word_ratio(words: List[str]) -> float:
    """Fraction of words with 3+ syllables."""
    if not words:
        return 0.0
    return _count_complex_words(words) / len(words)


def compute_hedge_ratio(words: List[str]) -> float:
    """Fraction of words that are hedge / weakening words."""
    if not words:
        return 0.0
    return _count_hedge_words(words) / len(words)


def compute_nominalization_ratio(words: List[str]) -> float:
    """Fraction of words that are abstract nouns."""
    if not words:
        return 0.0
    return _count_nominalizations(words) / len(words)


# ---------------------------------------------------------------------------
# Composite index
# ---------------------------------------------------------------------------


def compute_readability_index(
    sentence_length_score: float,
    complex_word_ratio: float,
    hedge_ratio: float,
    nominalization_ratio: float,
) -> float:
    """Compute composite readability index from four signals.

    Weights:
    - sentence_length_score: 35%  (structure)
    - complex_word_ratio: 30%      (vocabulary complexity, inverted)
    - hedge_ratio: 15%           (hedging, U-shaped penalty)
    - nominalization_ratio: 20%  (abstraction density, inverted)

    Returns a float 0.0–1.0.
    """
    # Sentence length contributes positively
    s_score = sentence_length_score * 0.35

    # Complex words penalize readability
    c_score = (1.0 - min(complex_word_ratio / 0.4, 1.0)) * 0.30

    # Hedge words: U-shaped — ideal around 0.02-0.05
    # Too few hedges = dogmatic; too many = timid
    if hedge_ratio <= 0.05:
        h_score = 1.0 - abs(hedge_ratio - 0.03) / 0.05
    else:
        h_score = max(0.0, 1.0 - (hedge_ratio - 0.05) / 0.15)
    h_score = max(0.0, min(1.0, h_score)) * 0.15

    # Nominalizations penalize readability
    n_score = (1.0 - min(nominalization_ratio / 0.25, 1.0)) * 0.20

    index = s_score + c_score + h_score + n_score
    return max(0.0, min(1.0, index))


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify_readability(index: float) -> str:
    """Classify readability index into a human-readable label."""
    if index >= 0.80:
        return "clear"
    elif index >= 0.65:
        return "transparent"
    elif index >= 0.50:
        return "serviceable"
    elif index >= 0.35:
        return "dense"
    else:
        return "impenetrable"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def compute_readability_metrics(texts: List[str]) -> Dict[str, Any]:
    """Compute readability metrics across a list of text samples.

    Args:
        texts: list of text strings (strokes, paragraphs, etc.)

    Returns:
        dict with all readability metrics and classification.
    """
    all_sentences: List[str] = []
    all_words: List[str] = []

    for text in texts:
        if not text or not text.strip():
            continue
        sentences = _split_sentences(text)
        all_sentences.extend(sentences)
        all_words.extend(_split_words(text))

    if not all_sentences or not all_words:
        return {
            "readability_index": 0.0,
            "readability_class": "impenetrable",
            "sentence_length_score": 0.0,
            "complex_word_ratio": 0.0,
            "hedge_ratio": 0.0,
            "nominalization_ratio": 0.0,
            "text_count": len(texts),
            "total_sentences": 0,
            "total_words": 0,
        }

    sl_score = compute_sentence_length_score(all_sentences)
    cw_ratio = compute_complex_word_ratio(all_words)
    h_ratio = compute_hedge_ratio(all_words)
    nom_ratio = compute_nominalization_ratio(all_words)

    index = compute_readability_index(sl_score, cw_ratio, h_ratio, nom_ratio)

    return {
        "readability_index": round(index, 4),
        "readability_class": _classify_readability(index),
        "sentence_length_score": round(sl_score, 4),
        "complex_word_ratio": round(cw_ratio, 4),
        "hedge_ratio": round(h_ratio, 4),
        "nominalization_ratio": round(nom_ratio, 4),
        "text_count": len(texts),
        "total_sentences": len(all_sentences),
        "total_words": len(all_words),
    }


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyze_stroke_readability(stroke: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze readability of a single stroke.

    Args:
        stroke: dict with 'text', 'content', or 'body' field.

    Returns:
        dict with readability_index and readability_class.
    """
    text = _get_stroke_text(stroke)
    if not text:
        return {
            "readability_index": 0.0,
            "readability_class": "impenetrable",
        }
    metrics = compute_readability_metrics([text])
    return {
        "readability_index": metrics["readability_index"],
        "readability_class": metrics["readability_class"],
        "sentence_length_score": metrics["sentence_length_score"],
        "complex_word_ratio": metrics["complex_word_ratio"],
        "hedge_ratio": metrics["hedge_ratio"],
        "nominalization_ratio": metrics["nominalization_ratio"],
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_readability_report(metrics: Dict[str, Any]) -> str:
    """Format readability metrics into a human-readable report."""
    lines = [
        "Readability Report",
        f"  readability_index:  {metrics['readability_index']:.4f}  "
        f"({metrics['readability_class']})",
        f"  sentence_length:    {metrics['sentence_length_score']:.4f}",
        f"  complex_words:      {metrics['complex_word_ratio']:.4f}",
        f"  hedge_words:        {metrics['hedge_ratio']:.4f}",
        f"  nominalizations:    {metrics['nominalization_ratio']:.4f}",
        f"  texts:              {metrics['text_count']}",
        f"  sentences:          {metrics['total_sentences']}",
        f"  words:              {metrics['total_words']}",
    ]
    return "\n".join(lines)
