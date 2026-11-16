#!/usr/bin/env python3
"""writer_nominalization_density — measure the density of nominalizations in prose.

Nominalizations are nouns derived from verbs or adjectives via
productive suffixes: *implementation*, *observation*, *development*,
*happiness*, *clarity*, *resistance*, *modernism*.  Linguist Helen
Sword calls them "zombie nouns" because they drain the life from
sentences — replacing concrete actors and actions with abstract
entities that float free of agency.

Compare:

    "The committee **decided** to **implement** the plan."
    → Two verbs, clear actors.

    "The committee's **decision** led to the **implementation** of the plan."
    → Two nominalizations, agency obscured.

Nominalizations are not inherently bad — they enable abstraction and
are essential in technical and academic writing.  But excessive
nominalization makes prose heavy, bureaucratic, and hard to follow.

This module detects nominalizations via suffix patterns and computes:

- **nominalization_count**: total words identified as nominalizations
- **nominalization_rate**: nominalizations per 100 words
- **nominalization_noun_ratio**: fraction of all nouns that are nominalizations
- **suffix_breakdown**: counts per suffix category (-tion, -sion,
  -ment, -ness, -ity, -ence, -ance, -ism, -ist)
- **dominant_suffix**: the suffix category with the most hits
- **density_index**: composite score 0.0 (no nominalizations) to 1.0
  (extremely nominalized prose)
- **classification**: one of concrete | lean | moderate | dense | bureaucratic

Detection uses suffix matching with a curated exception list of
common words that end in nominalization suffixes but are not
nominalizations (e.g., *nation*, *action* as a standalone concept,
*moment*, *cement*, *pavement*).  The exception list is intentionally
conservative: false negatives are preferred over false positives.

This metric is orthogonal to verbosity (word count), formality
(register), and sentence complexity.  A short sentence can be
nominalization-heavy; a long sentence can be verb-driven.

written by Qwen during manual caretaker visit 659, 2026-11-16
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict


# ── regex primitives ────────────────────────────────────────────

_WORD_RE = re.compile(r"[a-zA-Z']+")
_SUFFIX_RE = re.compile(
    r"(?:tion|sion|ment|ness|ity|ence|ance|ism|ist)$",
    re.IGNORECASE,
)


# ── suffix categories ──────────────────────────────────────────

_SUFFIX_CATEGORIES = {
    "tion": re.compile(r"tion$", re.IGNORECASE),
    "sion": re.compile(r"sion$", re.IGNORECASE),
    "ment": re.compile(r"ment$", re.IGNORECASE),
    "ness": re.compile(r"ness$", re.IGNORECASE),
    "ity": re.compile(r"ity$", re.IGNORECASE),
    "ence": re.compile(r"ence$", re.IGNORECASE),
    "ance": re.compile(r"ance$", re.IGNORECASE),
    "ism": re.compile(r"ism$", re.IGNORECASE),
    "ist": re.compile(r"ist$", re.IGNORECASE),
}


# ── exception list ──────────────────────────────────────────────
# Common words that end in nominalization suffixes but are NOT
# nominalizations (they are base nouns, proper nouns, or words
# whose meaning is not derived from a verb/adjective).

_EXCEPTIONS = {
    # -tion words that are base nouns
    "nation", "action", "station", "portion", "option", "auction",
    "caution", "function", "mention", "potion", "motion", "notion",
    "question", "position", "condition", "addition", "edition",
    "tradition", "ambition", "munition", "partition", "petition",
    "nutrition", "definition", "ignition", "apparition", "expedition",
    "transition", "competition", "recognition", "ammunition",
    "acquisition", "inquisition", "jurisdiction", "superstition",
    # -sion words that are base nouns
    "mission", "session", "passion", "mansion", "pension",
    "tension", "version", "cushion", "fusion", "vision",
    "decision", "precision", "occasion", "persuasion", "invasion",
    "collision", "provision", "television", "supervision",
    # -ment words that are base nouns or concrete objects
    "moment", "cement", "pavement", "basement", "casement",
    "raiment", "vestment", "vestment", "ferment", "torment",
    "garment", "ornament", "sediment", "ligament", "testament",
    "document", "monument", "instrument", "experiment",
    "department", "apartment", "compartment", "encampment",
    # -ness words that are base nouns
    "witness", "darkness", "wilderness", "fortress", "mistress",
    "princess", "goddess", "hostess", "lioness", "temptress",
    "business", "lioness",
    # -ity words that are base nouns or common concrete words
    "city", "pity", "ditty", "beauty", "duty", "deputy",
    "penalty", "loyalty", "royalty", "reality", "vitality",
    "hospitality", "personality", "locality", "morality",
    "mortality", "immunity", "community", "opportunity",
    "university", "curiosity", "generosity", "necessity",
    # -ence / -ance words that are base nouns
    "hence", "thence", "whence", "fence", "pence", "science",
    "conscience", "audience", "silence", "violence", "patience",
    "sentence", "presence", "absence", "essence", "licence",
    "dance", "chance", "glance", "lance", "trance", "stance",
    "balance", "ambulance", "substance", "entrance", "fragrance",
    "ignorance", "importance", "acceptance", "attendance",
    # -ism words that are not nominalizations from verbs
    "baptism", "organism", "mechanism", "criticism", "tourism",
    "terrorism", "journalism", "capitalism", "socialism",
    "communism", "feminism", "racism", "sexism", "ageism",
    # -ist words that denote people (agent nouns, not abstractions)
    "artist", "chemist", "dentist", "novelist", "pianist",
    "tourist", "journalist", "terrorist", "capitalist", "socialist",
    "scientist", "cyclist", "motorist", "florist", "typist",
    "optimist", "pessimist", "realist", "idealist", "analyst",
}


# ── noun detection (heuristic) ──────────────────────────────────
# Simple heuristic: words that are not in a stop-word list and
# match common noun patterns.  This is intentionally broad; the
# denominator in nominalization_noun_ratio is an approximation.

_COMMON_NON_NOUNS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can",
    "need", "dare", "ought", "used",
    "i", "you", "he", "she", "it", "we", "they", "me", "him",
    "her", "us", "them", "my", "your", "his", "its", "our", "their",
    "this", "that", "these", "those",
    "and", "but", "or", "nor", "for", "yet", "so",
    "if", "when", "while", "because", "although", "since", "unless",
    "until", "after", "before", "as", "than",
    "in", "on", "at", "by", "from", "to", "of", "about", "with",
    "through", "during", "between", "under", "above", "across",
    "into", "without", "upon", "within", "over", "against",
    "not", "no", "never", "nor", "neither",
    "very", "quite", "rather", "somewhat", "too", "also",
    "just", "only", "even", "still", "already", "yet",
    "here", "there", "now", "then", "today", "tomorrow", "yesterday",
    "how", "why", "what", "who", "whom", "which", "where",
    "all", "each", "every", "both", "few", "many", "much", "some",
    "any", "most", "more", "less", "least", "other", "another",
    "such", "same", "different",
}


# ── data classes ────────────────────────────────────────────────

@dataclass
class NominalizationHit:
    """A single nominalization detected in the text."""
    word: str
    suffix: str
    position: int  # word index in the text


@dataclass
class NominalizationDensityResult:
    """Result of nominalization density analysis."""
    nominalization_count: int = 0
    total_words: int = 0
    nominalization_rate: float = 0.0  # per 100 words
    nominalization_noun_ratio: float = 0.0  # fraction of nouns
    suffix_breakdown: Dict[str, int] = field(default_factory=dict)
    dominant_suffix: str = "none"
    density_index: float = 0.0
    classification: str = "unknown"
    hits: List[NominalizationHit] = field(default_factory=list)


# ── core functions ──────────────────────────────────────────────

def _classify_suffix(word: str) -> str:
    """Return the suffix category of a word, or 'none'."""
    for suffix, pattern in _SUFFIX_CATEGORIES.items():
        if pattern.search(word):
            return suffix
    return "none"


def _is_nominalization(word: str) -> bool:
    """Check whether a word is a nominalization."""
    lower = word.lower().strip("'")

    # Too short to be a meaningful nominalization
    if len(lower) < 5:
        return False

    # Exception list
    if lower in _EXCEPTIONS:
        return False

    # Check suffix match
    if not _SUFFIX_RE.search(lower):
        return False

    # Additional heuristic: word must be at least 6 chars for -tion/-sion
    # to avoid false positives on short words
    if lower.endswith(("tion", "sion")) and len(lower) < 6:
        return False

    return True


def _is_likely_noun(word: str) -> bool:
    """Heuristic: is this word likely a noun?"""
    lower = word.lower()

    # Skip stop words
    if lower in _COMMON_NON_NOUNS:
        return False

    # Skip very short words
    if len(lower) < 3:
        return False

    # Skip words ending in common verb/adjective suffixes
    if lower.endswith(("ing", "ed", "ly", "ive", "ous", "ful",
                        "able", "ible", "al", "ial")):
        return False

    return True


def measure_nominalization_density(text: str) -> NominalizationDensityResult:
    """Analyze nominalization density in a text.

    Returns a NominalizationDensityResult with counts, rates,
    suffix breakdown, density index, and classification.
    """
    result = NominalizationDensityResult()

    if not text or not text.strip():
        result.classification = "unknown"
        return result

    words = _WORD_RE.findall(text)
    if not words:
        result.classification = "unknown"
        return result

    result.total_words = len(words)

    # Find nominalizations
    hits: List[NominalizationHit] = []
    suffix_counts: Dict[str, int] = {}

    for i, word in enumerate(words):
        if _is_nominalization(word):
            suffix = _classify_suffix(word)
            hit = NominalizationHit(
                word=word.lower(),
                suffix=suffix,
                position=i,
            )
            hits.append(hit)
            suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1

    result.hits = hits
    result.nominalization_count = len(hits)
    result.suffix_breakdown = suffix_counts

    # Compute rates
    n = result.total_words
    result.nominalization_rate = round(
        (result.nominalization_count / n) * 100, 2
    ) if n > 0 else 0.0

    # Count likely nouns for noun ratio
    noun_count = sum(1 for w in words if _is_likely_noun(w))
    result.nominalization_noun_ratio = round(
        result.nominalization_count / noun_count, 4
    ) if noun_count > 0 else 0.0

    # Dominant suffix
    if suffix_counts:
        result.dominant_suffix = max(suffix_counts, key=suffix_counts.get)
    else:
        result.dominant_suffix = "none"

    # Compute density index
    # Composite: weighted combination of rate and noun ratio
    # rate_component: normalize rate to 0-1 (5% = very high)
    rate_component = min(result.nominalization_rate / 5.0, 1.0)
    # noun_ratio_component: normalize to 0-1 (0.3 = very high)
    ratio_component = min(result.nominalization_noun_ratio / 0.3, 1.0)
    result.density_index = round(
        0.6 * rate_component + 0.4 * ratio_component, 4
    )

    # Classification
    idx = result.density_index
    if idx < 0.10:
        result.classification = "concrete"
    elif idx < 0.25:
        result.classification = "lean"
    elif idx < 0.45:
        result.classification = "moderate"
    elif idx < 0.65:
        result.classification = "dense"
    else:
        result.classification = "bureaucratic"

    return result
