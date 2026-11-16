#!/usr/bin/env python3
"""writer_pronoun_density — measure pronoun usage patterns in prose.

Pronouns are the most frequent words in any language, yet their
distribution reveals a great deal about a writer's voice.  First-
person prose ("I think", "we found") signals a personal, subjective
stance.  Second-person prose ("you might notice") creates intimacy
or instruction.  Third-person prose ("they argued", "she observed")
maintains distance and objectivity.

Beyond person, the *density* of pronouns relative to content words
indicates how much a text relies on deixis versus explicit nouns.
High pronoun density often correlates with conversational or narrative
prose; low density with technical or formal writing where nouns are
repeated for precision.

This module is orthogonal to existing writer metrics:

- **formality** tracks register along a casual-formal axis.  Pronoun
  choice *correlates* with formality but does not determine it: formal
  writing can use "we" (academic convention), and informal writing can
  avoid pronouns (bullet-point style).

- **hedging** tracks epistemic caution.  First-person pronouns often
  co-occur with hedging ("I think"), but pronoun density is a
  structural measure, not a modal one.

- **specificity** tracks concrete vs. abstract reference.  Pronoun
  density measures *how often* the writer uses pronominal reference
  rather than *what kind* of entities are referenced.

- **voice_consistency** tracks stability of voice across a text.
  Pronoun density measures a *snapshot* property; voice consistency
  measures *variance* of voice properties over segments.

Pronoun density asks: **how heavily does this prose rely on pronominal
reference, and what person/role distribution does it exhibit?**

Dimensions
----------

===========================  ===========================================
metric                       meaning
===========================  ===========================================
total_pronouns               raw count of all pronouns detected
pronoun_rate                 pronouns per 100 words
first_person_ratio           fraction of pronouns that are first person
second_person_ratio          fraction that are second person
third_person_ratio           fraction that are third person
possessive_ratio             fraction that are possessive pronouns
reflexive_ratio              fraction that are reflexive pronouns
person_balance               entropy-based balance across persons
                             (0 = single person, 1 = perfectly balanced)
dominant_person              the person category with highest ratio
===========================  ===========================================

Classification
--------------

Based on pronoun_rate (pronouns per 100 words):

==============  ============================================================
class           meaning
==============  ============================================================
sparse          rate < 3 — minimal pronominal reference (formal / technical)
lean            3 <= rate < 6 — restrained pronoun use (literary / editorial)
balanced        6 <= rate < 10 — moderate pronoun use (general prose)
pronoun_heavy   10 <= rate < 15 — frequent pronoun use (conversational)
deictic         rate >= 15 — very high pronoun density (stream-of-consciousness
                or dialogue-heavy prose)
==============  ============================================================

Written by Qwen during caretaker visit 662, 2026-11-17.
"""

from __future__ import annotations

import re
import math
from typing import Any, Dict, List, Tuple
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIRST_PERSON = {
    "i", "me", "my", "mine", "myself",
    "we", "us", "our", "ours", "ourselves",
}

SECOND_PERSON = {
    "you", "your", "yours", "yourself", "yourselves",
}

THIRD_PERSON = {
    "he", "him", "his", "himself",
    "she", "her", "hers", "herself",
    "it", "its", "itself",
    "they", "them", "their", "theirs", "themselves",
    "one", "oneself",
}

POSSESSIVE = {
    "my", "mine", "your", "yours", "his", "her", "hers",
    "its", "our", "ours", "their", "theirs",
}

REFLEXIVE = {
    "myself", "yourself", "yourselves", "himself", "herself",
    "itself", "ourselves", "themselves", "oneself",
}

ALL_PRONOUNS = FIRST_PERSON | SECOND_PERSON | THIRD_PERSON

# Sorted longest-first to match "themselves" before "them" before "the"
_PRONOUN_PATTERN = re.compile(
    r"\b(?:" + "|".join(sorted(ALL_PRONOUNS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

_WORD_PATTERN = re.compile(r"[a-zA-Z']+")

# Contraction handling: "I'm", "we're", "they've" etc.
_CONTRACTION_OWNER = {
    "i'm": "i", "i've": "i", "i'd": "i", "i'll": "i",
    "we're": "we", "we've": "we", "we'd": "we", "we'll": "we",
    "you're": "you", "you've": "you", "you'd": "you", "you'll": "you",
    "he's": "he", "he'll": "he", "he'd": "he",
    "she's": "she", "she'll": "she", "she'd": "she",
    "it's": "it", "it'll": "it",
    "they're": "they", "they've": "they", "they'd": "they", "they'll": "they",
    "one's": "one",
}


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class PronounDensityResult:
    """Result of pronoun density analysis."""

    total_pronouns: int = 0
    total_words: int = 0
    pronoun_rate: float = 0.0
    first_person_count: int = 0
    second_person_count: int = 0
    third_person_count: int = 0
    possessive_count: int = 0
    reflexive_count: int = 0
    first_person_ratio: float = 0.0
    second_person_ratio: float = 0.0
    third_person_ratio: float = 0.0
    possessive_ratio: float = 0.0
    reflexive_ratio: float = 0.0
    person_balance: float = 0.0
    dominant_person: str = "none"
    category_counts: Dict[str, int] = field(default_factory=dict)
    top_pronouns: List[Tuple[str, int]] = field(default_factory=list)
    classification: str = "unknown"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase words, expanding contractions."""
    raw_tokens = _WORD_PATTERN.findall(text.lower())
    tokens: List[str] = []
    for tok in raw_tokens:
        if tok in _CONTRACTION_OWNER:
            # The contraction contains a pronoun; add the pronoun form
            tokens.append(_CONTRACTION_OWNER[tok])
        else:
            tokens.append(tok)
    return tokens


def _find_pronouns(tokens: List[str]) -> List[str]:
    """Extract pronoun tokens from a token list."""
    return [t for t in tokens if t in ALL_PRONOUNS]


def _categorize(pronouns: List[str]) -> Dict[str, int]:
    """Count pronouns by person category."""
    counts = {"first": 0, "second": 0, "third": 0}
    for p in pronouns:
        if p in FIRST_PERSON:
            counts["first"] += 1
        elif p in SECOND_PERSON:
            counts["second"] += 1
        elif p in THIRD_PERSON:
            counts["third"] += 1
    return counts


def _count_special(pronouns: List[str]) -> Tuple[int, int]:
    """Count possessive and reflexive pronouns."""
    poss = sum(1 for p in pronouns if p in POSSESSIVE)
    refl = sum(1 for p in pronouns if p in REFLEXIVE)
    return poss, refl


def _frequency_list(pronouns: List[str], top_n: int = 5) -> List[Tuple[str, int]]:
    """Return top-N most frequent pronouns."""
    freq: Dict[str, int] = {}
    for p in pronouns:
        freq[p] = freq.get(p, 0) + 1
    ranked = sorted(freq.items(), key=lambda x: (-x[1], x[0]))
    return ranked[:top_n]


def _person_balance_entropy(first: float, second: float, third: float) -> float:
    """Compute normalized entropy across person categories.

    Returns 0.0 when all pronouns are in one category, 1.0 when
    perfectly balanced across all three.
    """
    ratios = [first, second, third]
    total = sum(ratios)
    if total == 0:
        return 0.0
    probs = [r / total for r in ratios if r > 0]
    if len(probs) <= 1:
        return 0.0
    entropy = -sum(p * math.log2(p) for p in probs)
    max_entropy = math.log2(3)  # ~1.585
    return entropy / max_entropy


def _classify(rate: float, total: int) -> str:
    """Classify based on pronoun rate per 100 words."""
    if total == 0:
        return "unknown"
    if rate < 3:
        return "sparse"
    elif rate < 6:
        return "lean"
    elif rate < 10:
        return "balanced"
    elif rate < 15:
        return "pronoun_heavy"
    else:
        return "deictic"


def _dominant_person(first: float, second: float, third: float) -> str:
    """Return the person category with the highest ratio."""
    if first == 0 and second == 0 and third == 0:
        return "none"
    persons = {"first": first, "second": second, "third": third}
    return max(persons, key=persons.get)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def measure_pronoun_density(text: str) -> PronounDensityResult:
    """Analyze pronoun usage patterns in a text.

    Parameters
    ----------
    text : str
        The input text to analyze.

    Returns
    -------
    PronounDensityResult
        A dataclass with all pronoun density metrics.
    """
    if not text or not text.strip():
        return PronounDensityResult(classification="unknown")

    tokens = _tokenize(text)
    total_words = len(tokens)

    if total_words == 0:
        return PronounDensityResult(classification="unknown")

    pronouns = _find_pronouns(tokens)
    total_pronouns = len(pronouns)

    # Rate per 100 words
    pronoun_rate = (total_pronouns / total_words) * 100 if total_words > 0 else 0.0

    # Category counts
    cat_counts = _categorize(pronouns)
    poss_count, refl_count = _count_special(pronouns)

    # Ratios (of total pronouns)
    if total_pronouns > 0:
        first_ratio = cat_counts["first"] / total_pronouns
        second_ratio = cat_counts["second"] / total_pronouns
        third_ratio = cat_counts["third"] / total_pronouns
        poss_ratio = poss_count / total_pronouns
        refl_ratio = refl_count / total_pronouns
    else:
        first_ratio = second_ratio = third_ratio = 0.0
        poss_ratio = refl_ratio = 0.0

    # Person balance
    balance = _person_balance_entropy(first_ratio, second_ratio, third_ratio)

    # Dominant person
    dominant = _dominant_person(
        cat_counts["first"], cat_counts["second"], cat_counts["third"]
    )

    # Frequency list
    top = _frequency_list(pronouns)

    # Classification
    classification = _classify(pronoun_rate, total_pronouns)

    return PronounDensityResult(
        total_pronouns=total_pronouns,
        total_words=total_words,
        pronoun_rate=round(pronoun_rate, 2),
        first_person_count=cat_counts["first"],
        second_person_count=cat_counts["second"],
        third_person_count=cat_counts["third"],
        possessive_count=poss_count,
        reflexive_count=refl_count,
        first_person_ratio=round(first_ratio, 4),
        second_person_ratio=round(second_ratio, 4),
        third_person_ratio=round(third_ratio, 4),
        possessive_ratio=round(poss_ratio, 4),
        reflexive_ratio=round(refl_ratio, 4),
        person_balance=round(balance, 4),
        dominant_person=dominant,
        category_counts=cat_counts,
        top_pronouns=top,
        classification=classification,
    )
