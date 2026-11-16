#!/usr/bin/env python3
"""writer_information_density — measure how much new information each
sentence carries relative to its length.

Information density is about *payload*.  Dense prose packs meaning into
every clause: content words outnumber function words, each sentence
advances the argument or narrative, and repetition is structural
(parallelism, refrain) rather than accidental.  Thin prose pads with
filler phrases, restates the same idea in adjacent sentences, or buries
one idea under many words.

This module is orthogonal to existing writer metrics:

- **concision** tracks whether *more words than needed* are used.
  Concision is about waste; information density is about *payload per
  unit*.  A text can be concise (few words) while low-density (those
  words carry little information — e.g., "It is what it is.").

- **verbosity** tracks *unnecessary elaboration*.  Verbosity is a
  failure mode; information density is a continuous measure.  Verbose
  text is typically low-density, but short text can also be low-density
  if it says nothing.

- **vocabulary_richness** tracks *diversity* of word choice.  A text can
  use rich vocabulary while being low-density (many beautiful words that
  circle the same point).  Conversely, simple vocabulary can be
  high-density (each word advances meaning — technical prose).

- **readability** tracks *ease of parsing*.  Dense text can be readable
  (well-structured technical writing) or unreadable (jargon soup).
  Readable text can be dense or thin.  Orthogonal dimensions.

- **signal_clarity** tracks *uniqueness of strokes*.  Signal clarity
  operates across units (are two strokes near-duplicates?); information
  density operates *within* each unit.

Information density asks: **how much meaning does each word carry,
and how consistently does the text deliver new information?**

Dimensions
----------

===========================  ===========================================
metric                       meaning
===========================  ===========================================
content_word_ratio           content words / total words (overall)
unique_content_ratio         unique content words / total content words
novel_sentence_ratio         fraction of sentences with >50% new words
redundancy_rate              repeated bigrams / total bigrams
filler_phrase_rate           filler phrases per 100 words
mean_info_per_sentence       mean content words per sentence
info_density_variance        variance of info across sentences
density_score                composite 0-100 score
classification               five-level label
===========================  ===========================================

Classification
--------------

===========  =========  ===============================================
label        score      description
===========  =========  ===============================================
thin         0-20       mostly filler, restatement, padding
light        21-40      some content but uneven, notable redundancy
balanced     41-60      reasonable density with natural variation
dense        61-80      consistently informative, low redundancy
compressed   81-100     extremely dense, every word earns its place
===========  =========  ===============================================

Written by Qwen during caretaker visit 663, 2026-11-17.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import List, Tuple

# ── stop words (function words, not content) ───────────────────

_STOP_WORDS = frozenset(
    "a an the and or but nor for yet so is am are was were be been "
    "being have has had do does did will would shall should may might "
    "must can could of in to for on with at by from as into through "
    "during before after above below between under over again further "
    "then once here there when where why how all each every both few "
    "more most other some such no not only own same so than too very "
    "just because if while about up out off down that this these those "
    "it its i me my we our you your he him his she her they them their "
    "what which who whom whose what whatever whoever whichever "
    "been being become became becoming seem seems seemed "
    "also even still already always never often sometimes "
    "really quite rather fairly somewhat pretty much many "
    "get gets got gotten getting go goes went gone "
    "make makes made making take takes took taken "
    "come comes came know knows knew known "
    "think thinks thought say says said "
    "see sees saw seen look looks looked "
    "want wants wanted need needs needed "
    "use uses used using find finds found "
    "give gives gave given tell tells told "
    "work works worked call calls called "
    "try tries tried ask asks asked "
    "men women children people thing things "
    "way ways day days man woman child "
    "well back also even still just "
    "like as if than because although "
    "though while whilst whereas whether "
    "since until unless despite besides "
    "however therefore moreover furthermore "
    "nevertheless nonetheless meanwhile otherwise "
    "instead indeed certainly surely "
    "basically actually essentially literally "
    "apparently obviously clearly simply "
    "generally usually normally typically".split()
)

# ── filler phrases ─────────────────────────────────────────────

_FILLER_PHRASES = [
    "at the end of the day",
    "in terms of",
    "it goes without saying",
    "needless to say",
    "for all intents and purposes",
    "at this point in time",
    "in the grand scheme of things",
    "it is important to note that",
    "it should be noted that",
    "it is worth mentioning",
    "in other words",
    "as a matter of fact",
    "by and large",
    "when all is said and done",
    "the fact of the matter",
    "in light of the fact that",
    "due to the fact that",
    "in the event that",
    "on the grounds that",
    "for the purpose of",
    "in order to",
    "in the process of",
    "with regard to",
    "with respect to",
    "as far as",
    "is concerned",
    "it seems that",
    "it appears that",
    "there is no doubt that",
    "it is clear that",
    "in my opinion",
    "from my perspective",
    "from my point of view",
    "i would argue that",
    "it could be argued that",
    "one could say that",
    "to put it simply",
    "to put it another way",
    "as it were",
    "so to speak",
    "in a manner of speaking",
]


@dataclass
class InformationDensityResult:
    """Result of information density analysis."""

    total_sentences: int = 0
    total_words: int = 0
    total_content_words: int = 0
    unique_content_words: int = 0
    content_word_ratio: float = 0.0
    unique_content_ratio: float = 0.0
    novel_sentence_ratio: float = 0.0
    redundancy_rate: float = 0.0
    filler_phrase_rate: float = 0.0
    mean_info_per_sentence: float = 0.0
    info_density_variance: float = 0.0
    density_score: float = 0.0
    classification: str = "unknown"
    sentence_densities: List[float] = field(default_factory=list)
    filler_count: int = 0
    redundant_bigram_count: int = 0
    total_bigram_count: int = 0


# ── internal helpers ───────────────────────────────────────────


def _tokenize(text: str) -> List[str]:
    """Lowercase word tokens, stripping punctuation."""
    return [w.strip(".,;:!?\"'()-[]{}*/") for w in text.lower().split() if w.strip(".,;:!?\"'()-[]{}*/")]


def _split_sentences(text: str) -> List[str]:
    """Split text on sentence-ending punctuation."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _content_words(tokens: List[str]) -> List[str]:
    """Filter out stop words and very short tokens."""
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


def _bigrams(tokens: List[str]) -> List[Tuple[str, str]]:
    """Extract consecutive word pairs."""
    return list(zip(tokens[:-1], tokens[1:]))


def _count_filler_phrases(text: str) -> int:
    """Count filler phrases (case-insensitive)."""
    lower = text.lower()
    count = 0
    for phrase in _FILLER_PHRASES:
        count += lower.count(phrase)
    return count


def _compute_sentence_density(
    tokens: List[str], seen_words: set
) -> Tuple[float, float, set]:
    """Compute info density for a single sentence.

    Returns (content_ratio, novelty_ratio, updated_seen_words).
    """
    content = _content_words(tokens)
    if not tokens:
        return 0.0, 0.0, seen_words

    content_ratio = len(content) / len(tokens) if tokens else 0.0

    if content:
        novel = sum(1 for w in content if w not in seen_words)
        novelty_ratio = novel / len(content)
    else:
        novelty_ratio = 0.0

    new_seen = seen_words | set(content)
    return content_ratio, novelty_ratio, new_seen


def _compute_redundancy(tokens: List[str]) -> Tuple[int, int]:
    """Count total bigrams and redundant (repeated) bigrams."""
    bgs = _bigrams(tokens)
    if not bgs:
        return 0, 0

    total = len(bgs)
    seen = {}
    redundant = 0
    for bg in bgs:
        if bg in seen:
            redundant += 1
        else:
            seen[bg] = True

    return redundant, total


def _score(
    content_word_ratio: float,
    unique_content_ratio: float,
    novel_sentence_ratio: float,
    redundancy_rate: float,
    filler_phrase_rate: float,
) -> float:
    """Composite score 0-100."""
    # content word ratio component (0-30)
    cwr_score = min(content_word_ratio / 0.65, 1.0) * 30

    # unique content ratio component (0-25)
    ucr_score = min(unique_content_ratio / 0.80, 1.0) * 25

    # novel sentence ratio component (0-25)
    nsr_score = min(novel_sentence_ratio / 0.70, 1.0) * 25

    # redundancy penalty (0-10, inverted)
    red_penalty = max(0, 10 - (redundancy_rate * 50))

    # filler penalty (0-10, inverted)
    filler_penalty = max(0, 10 - (filler_phrase_rate * 20))

    return max(0, min(100, cwr_score + ucr_score + nsr_score + red_penalty + filler_penalty))


def _classify(score: float) -> str:
    """Five-level classification."""
    if score <= 0:
        return "unknown"
    if score <= 20:
        return "thin"
    if score <= 40:
        return "light"
    if score <= 60:
        return "balanced"
    if score <= 80:
        return "dense"
    return "compressed"


# ── public API ─────────────────────────────────────────────────


def measure_information_density(text: str) -> InformationDensityResult:
    """Analyze information density of a text.

    Parameters
    ----------
    text : str
        The prose to analyze.

    Returns
    -------
    InformationDensityResult
        Density metrics and classification.
    """
    result = InformationDensityResult()

    if not text or not text.strip():
        return result

    sentences = _split_sentences(text)
    all_tokens = _tokenize(text)

    if not all_tokens or not sentences:
        return result

    result.total_sentences = len(sentences)
    result.total_words = len(all_tokens)

    # content words
    all_content = _content_words(all_tokens)
    result.total_content_words = len(all_content)
    result.unique_content_words = len(set(all_content))

    # ratios
    result.content_word_ratio = (
        len(all_content) / len(all_tokens) if all_tokens else 0.0
    )
    result.unique_content_ratio = (
        len(set(all_content)) / len(all_content) if all_content else 0.0
    )

    # per-sentence analysis
    seen_words: set = set()
    sentence_densities = []
    novel_count = 0

    for sent in sentences:
        tokens = _tokenize(sent)
        content_ratio, novelty_ratio, seen_words = _compute_sentence_density(
            tokens, seen_words
        )
        sentence_densities.append(content_ratio)
        if novelty_ratio > 0.5:
            novel_count += 1

    result.sentence_densities = sentence_densities
    result.novel_sentence_ratio = novel_count / len(sentences) if sentences else 0.0

    # info per sentence
    content_per_sentence = [
        len(_content_words(_tokenize(s))) for s in sentences
    ]
    if content_per_sentence:
        result.mean_info_per_sentence = sum(content_per_sentence) / len(
            content_per_sentence
        )
        if len(content_per_sentence) > 1:
            mean = result.mean_info_per_sentence
            result.info_density_variance = sum(
                (x - mean) ** 2 for x in content_per_sentence
            ) / (len(content_per_sentence) - 1)

    # redundancy
    redundant, total = _compute_redundancy(all_tokens)
    result.redundant_bigram_count = redundant
    result.total_bigram_count = total
    result.redundancy_rate = redundant / total if total else 0.0

    # filler phrases
    result.filler_count = _count_filler_phrases(text)
    result.filler_phrase_rate = (
        (result.filler_count / result.total_words) * 100
        if result.total_words
        else 0.0
    )

    # score and classify
    result.density_score = round(
        _score(
            result.content_word_ratio,
            result.unique_content_ratio,
            result.novel_sentence_ratio,
            result.redundancy_rate,
            result.filler_phrase_rate,
        ),
        2,
    )
    result.classification = _classify(result.density_score)

    return result
