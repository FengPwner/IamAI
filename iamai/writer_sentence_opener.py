#!/usr/bin/env python3
"""writer_sentence_opener — measure how sentences begin and the diversity of those openings.

Sentence openers are the first word or phrase of each sentence.
They set the rhetorical posture of what follows: a subject-first
opener ("The server crashed") gets straight to the point; an
adverbial opener ("Suddenly, the server crashed") frames the action
in time or manner; a prepositional opener ("In the datacenter, the
server crashed") grounds it in space or context; a conjunction
opener ("And the server crashed") links it to what came before.

A text where every sentence starts with a subject pronoun
("I did this. I saw that. I went there.") reads as monotonous
and childlike.  A text that varies its openers creates rhythm,
emphasis, and structural clarity.  But too much variation —
especially too many conjunction or adverbial openers — can make
prose feel cluttered or over-signposted.

This module classifies each sentence opener into one of seven
categories:

- **subject_pronoun**: starts with I, you, he, she, it, we, they
- **determiner**: starts with the, a, an, this, that, these, those, my, your, his, her, its, our, their
- **adverb**: starts with an -ly adverb or common sentence adverb (however, meanwhile, suddenly, etc.)
- **preposition**: starts with in, on, at, by, for, with, from, to, of, about, between, through, during, before, after, under, above, across, against, into, without
- **conjunction**: starts with and, but, or, so, yet, nor, for (as coordinating conjunction)
- **subordinator**: starts with if, when, while, because, although, since, unless, until, after, before (as subordinating conjunction)
- **other**: everything else — typically a noun, adjective, verb, or number

A well-balanced text distributes openers across several categories.
A text dominated by a single category has a monotonous sentence
rhythm.  The opener diversity index (Shannon entropy, normalized)
captures this: 0.0 means every sentence uses the same category;
1.0 means maximum even distribution across all categories.

The module also measures **conjunction_start_rate** (what fraction
of sentences begin with a coordinating conjunction) and
**subordinator_start_rate** (what fraction begin with a subordinating
conjunction).  High conjunction-start rates indicate a conversational
or stream-of-consciousness style; high subordinator-start rates
indicate heavily dependent, conditional prose.

This metric is orthogonal to verbosity (word count), formality
(register), and perspective (grammatical person).  A formal paper
can have diverse openers; an informal blog post can have uniform ones.

written by Qwen during manual caretaker visit 658, 2026-11-16
"""

import re
import math
from dataclasses import dataclass, field
from typing import List, Optional, Dict


# ── regex primitives ────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"[a-zA-Z']+")


# ── word sets for classification ────────────────────────────────

_SUBJECT_PRONOUNS = {
    "i", "you", "he", "she", "it", "we", "they",
    "me", "him", "her", "us", "them",
    "myself", "yourself", "himself", "herself", "itself",
    "ourselves", "yourselves", "themselves",
}

_DETERMINERS = {
    "the", "a", "an",
    "this", "that", "these", "those",
    "my", "your", "his", "her", "its", "our", "their",
    "some", "any", "no", "every", "each", "all", "both",
    "few", "many", "much", "several",
}

_COORDINATING_CONJUNCTIONS = {
    "and", "but", "or", "so", "yet", "nor", "for",
}

_COMMON_ADVERBS = {
    "however", "meanwhile", "therefore", "furthermore",
    "moreover", "nevertheless", "nonetheless", "consequently",
    "accordingly", "hence", "thus", "then", "also",
    "instead", "otherwise", "suddenly", "gradually",
    "eventually", "finally", "initially", "previously",
    "subsequently", "currently", "recently", "already",
    "still", "just", "only", "even", "also", "often",
    "always", "never", "sometimes", "usually", "rarely",
    "certainly", "surely", "clearly", "obviously",
    "apparently", "perhaps", "maybe", "indeed",
    "here", "there", "now", "today", "yesterday", "tomorrow",
    "not", "no", "yes",
}

_PREPOSITIONS = {
    "in", "on", "at", "by", "for", "with", "from",
    "to", "of", "about", "between", "through", "during",
    "before", "after", "under", "above", "across",
    "against", "into", "without", "within", "beyond",
    "behind", "beside", "below", "beneath", "besides",
    "among", "around", "down", "except", "inside",
    "near", "off", "onto", "out", "over", "past",
    "since", "than", "toward", "towards", "underneath",
    "until", "up", "upon", "via",
}

_SUBORDINATORS = {
    "if", "when", "while", "because", "although", "though",
    "since", "unless", "until", "whereas", "wherever",
    "whenever", "whether", "after", "before",
    "as", "once", "provided", "assuming",
}


# ── data structures ─────────────────────────────────────────────

@dataclass
class SentenceOpener:
    """Classification of a single sentence's opener."""
    text: str = ""
    first_word: str = ""
    category: str = "other"


@dataclass
class SentenceOpenerResult:
    """Aggregate results for sentence opener analysis."""
    # Per-sentence classifications
    openers: List[SentenceOpener] = field(default_factory=list)

    # Category counts
    subject_pronoun_count: int = 0
    determiner_count: int = 0
    adverb_count: int = 0
    preposition_count: int = 0
    conjunction_count: int = 0
    subordinator_count: int = 0
    other_count: int = 0

    # Category fractions (0.0 to 1.0)
    subject_pronoun_frac: float = 0.0
    determiner_frac: float = 0.0
    adverb_frac: float = 0.0
    preposition_frac: float = 0.0
    conjunction_frac: float = 0.0
    subordinator_frac: float = 0.0
    other_frac: float = 0.0

    # Composite metrics
    diversity_index: float = 0.0  # normalized Shannon entropy (0.0 = uniform, 1.0 = max diverse)
    dominant_category: Optional[str] = None
    conjunction_start_rate: float = 0.0
    subordinator_start_rate: float = 0.0

    # Classification
    classification: str = "unknown"  # uniform | concentrated | balanced | diverse | varied

    # Total sentences analyzed
    total_sentences: int = 0


# ── classification ──────────────────────────────────────────────

def _classify_opener(sentence: str) -> SentenceOpener:
    """Classify the opener of a single sentence."""
    so = SentenceOpener()
    so.text = sentence.strip()

    words = _WORD_SPLIT.findall(sentence.strip())
    if not words:
        so.first_word = ""
        so.category = "other"
        return so

    first = words[0].lower()
    so.first_word = words[0]

    if first in _SUBJECT_PRONOUNS:
        so.category = "subject_pronoun"
    elif first in _COORDINATING_CONJUNCTIONS:
        so.category = "conjunction"
    elif first in _SUBORDINATORS:
        so.category = "subordinator"
    elif first in _DETERMINERS:
        so.category = "determiner"
    elif first in _PREPOSITIONS:
        so.category = "preposition"
    elif first.endswith("ly") or first in _COMMON_ADVERBS:
        so.category = "adverb"
    else:
        so.category = "other"

    return so


# ── main function ───────────────────────────────────────────────

def measure_sentence_openers(text: str) -> SentenceOpenerResult:
    """Analyze sentence openers in a text.

    Returns a SentenceOpenerResult with per-category counts,
    fractions, diversity index, and classification.
    """
    result = SentenceOpenerResult()

    if not text or not text.strip():
        result.classification = "unknown"
        return result

    # Split into sentences
    sentences = _SENTENCE_SPLIT.split(text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        result.classification = "unknown"
        return result

    result.total_sentences = len(sentences)

    # Classify each sentence opener
    openers = [_classify_opener(s) for s in sentences]
    result.openers = openers

    # Count by category
    category_counts: Dict[str, int] = {}
    for o in openers:
        category_counts[o.category] = category_counts.get(o.category, 0) + 1

    result.subject_pronoun_count = category_counts.get("subject_pronoun", 0)
    result.determiner_count = category_counts.get("determiner", 0)
    result.adverb_count = category_counts.get("adverb", 0)
    result.preposition_count = category_counts.get("preposition", 0)
    result.conjunction_count = category_counts.get("conjunction", 0)
    result.subordinator_count = category_counts.get("subordinator", 0)
    result.other_count = category_counts.get("other", 0)

    # Compute fractions
    n = len(openers)
    result.subject_pronoun_frac = round(result.subject_pronoun_count / n, 4)
    result.determiner_frac = round(result.determiner_count / n, 4)
    result.adverb_frac = round(result.adverb_count / n, 4)
    result.preposition_frac = round(result.preposition_count / n, 4)
    result.conjunction_frac = round(result.conjunction_count / n, 4)
    result.subordinator_frac = round(result.subordinator_count / n, 4)
    result.other_frac = round(result.other_count / n, 4)

    # Conjunction and subordinator start rates
    result.conjunction_start_rate = round(result.conjunction_count / n, 4)
    result.subordinator_start_rate = round(result.subordinator_count / n, 4)

    # Compute Shannon entropy (normalized)
    # H = -sum(p * log(p)) / log(k) where k = number of categories with p > 0
    fracs = [
        result.subject_pronoun_frac,
        result.determiner_frac,
        result.adverb_frac,
        result.preposition_frac,
        result.conjunction_frac,
        result.subordinator_frac,
        result.other_frac,
    ]
    non_zero = [f for f in fracs if f > 0]
    k = len(non_zero)

    if k <= 1:
        result.diversity_index = 0.0
    else:
        h = -sum(f * math.log(f) for f in non_zero)
        h_max = math.log(k)
        result.diversity_index = round(h / h_max, 4) if h_max > 0 else 0.0

    # Find dominant category
    counts = {
        "subject_pronoun": result.subject_pronoun_count,
        "determiner": result.determiner_count,
        "adverb": result.adverb_count,
        "preposition": result.preposition_count,
        "conjunction": result.conjunction_count,
        "subordinator": result.subordinator_count,
        "other": result.other_count,
    }
    result.dominant_category = max(counts, key=counts.get)

    # Classification based on diversity index
    idx = result.diversity_index
    if idx < 0.20:
        result.classification = "uniform"
    elif idx < 0.40:
        result.classification = "concentrated"
    elif idx < 0.60:
        result.classification = "balanced"
    elif idx < 0.80:
        result.classification = "diverse"
    else:
        result.classification = "varied"

    return result
