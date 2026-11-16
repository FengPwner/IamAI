#!/usr/bin/env python3
"""writer_concession_density — measure how much prose concedes before it asserts.

Concession is the rhetorical act of acknowledging an opposing view,
a limitation, or an uncomfortable fact *before* pressing on with
one's own argument.  It is the writer's way of saying "I see
your point — and yet."  A well-placed concession builds trust:
the reader feels heard, and the subsequent argument lands harder
because it has already survived the writer's own counterfactual.

Concession manifests through five measurable channels.

**Concessive conjunctions** subordinate the acknowledged point:
*although, though, even though, while, whilst, whereas, albeit,
notwithstanding, despite, in spite of*.  They signal that the
main clause will override the subordinate one — "Although the
sample was small, the results were significant."

**Concessive adverbs** open a sentence with a frank admission:
*admittedly, granted, certainly, surely, indeed, of course,
undeniably, unquestionably, granted that, to be sure*.  They
front-load the concession so the reader knows it is deliberate —
"Admittedly, the method has limitations."

**Concessive phrases** are multi-word constructions that mark
the acknowledgment explicitly: *it is true that, it must be
acknowledged, one might argue, fair enough, that said, having
said that, be that as it may, for all that, in spite of this,
despite the fact that, regardless of, irrespective of*.  They
are the most formal concession signals, common in academic and
legal prose.

**Performative concessions** use first-person verbs to enact
the concession in real time: *I concede, I grant, I acknowledge,
I admit, I accept, to be fair, to give credit, to do justice*.
They are the most personal concession form — the writer steps
forward and performs the act of yielding.

**Concessive clause structures** embed the concession in a
subordinate clause that the main clause then overrides: *while
it is true that, though one may argue, even if we accept,
regardless of whether, no matter how much, however much*.  They
are syntactically complex and signal high rhetorical control.

A text with high concession density reads as balanced, fair,
and intellectually honest — it shows its work, considers
objections, and argues through them.  A text with low concession
density reads as one-sided, either confident to the point of
dogma or simply unaware of counterarguments.  Neither is
inherently better: a concession-rich editorial persuades by
showing it has considered the other side; a concession-poor
manifesto energizes by refusing to entertain doubt.

This module measures concession density as a composite index
(0.0 – 1.0) across five independent channels, orthogonal to
hedging (which measures uncertainty rather than acknowledgment),
contrast (which juxtaposes differences without necessarily
yielding), certainty (which measures commitment to claims),
and formality (which measures register).

written by Qwen during manual caretaker visit 652, 2026-11-16
"""

import re
from dataclasses import dataclass
from typing import List


# ── regex patterns ──────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"[a-zA-Z'-]+")


# ── channel 1: concessive conjunctions ───────────────────────────
# Single words and short phrases that introduce a concessive
# subordinate clause.

_CONJUNCTION_SINGLE = set(
    w.lower()
    for w in [
        "although", "though", "albeit", "notwithstanding",
        "whereas", "despite",
    ]
)

_CONJUNCTION_PHRASES = {
    "even though",
    "even if",
    "even when",
    "even where",
    "in spite of",
    "in spite of the fact that",
    "despite the fact that",
    "despite the reality that",
    "in the face of",
    "regardless of",
    "irrespective of",
    "no matter how",
    "no matter what",
    "no matter who",
    "no matter why",
    "no matter when",
    "no matter where",
}

# "while" and "whilst" are concessive when they introduce a
# contrastive subordinate clause.  We detect them as single
# words but note they can also be temporal; this is an
# acceptable approximation for density measurement.
_CONJUNCTION_AMBIGUOUS = set(
    w.lower()
    for w in ["while", "whilst"]
)


# ── channel 2: concessive adverbs ───────────────────────────────
# Sentence-initial or mid-sentence adverbs that signal frank
# acknowledgment.

_ADVERB_SINGLE = set(
    w.lower()
    for w in [
        "admittedly", "granted", "certainly", "surely",
        "indeed", "undeniably", "unquestionably", "arguably",
    ]
)

_ADVERB_PHRASES = {
    "to be sure",
    "of course",
    "no doubt",
    "without doubt",
    "beyond doubt",
    "in fairness",
    "to be fair",
    "to be honest",
    "to be candid",
    "to be frank",
    "to be just",
    "to give credit",
    "to do justice",
    "to grant the point",
    "fair enough",
    "point taken",
    "well taken",
    "that said",
    "having said that",
    "this being said",
    "all the same",
    "just the same",
    "even so",
    "all the same",
    "for all that",
    "with all due respect",
}


# ── channel 3: concessive phrases ───────────────────────────────
# Multi-word constructions that explicitly mark acknowledgment.

_CONCESSION_PHRASES = {
    "it is true that",
    "it must be acknowledged",
    "it must be admitted",
    "it must be conceded",
    "it should be noted",
    "it should be acknowledged",
    "it is fair to say",
    "it is only fair",
    "one might argue",
    "one could argue",
    "one may argue",
    "some might say",
    "some may say",
    "critics might say",
    "critics may say",
    "it could be argued",
    "it might be argued",
    "it may be objected",
    "it could be objected",
    "be that as it may",
    "come what may",
    "whatsoever it may be",
    "as the case may be",
    "at the same time",
    "on the other hand",
    "then again",
    "and yet",
    "but then",
}


# ── channel 4: performative concessions ─────────────────────────
# First-person verbs that enact the concession.

_PERFORMATIVE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bI\s+concede\b",
        r"\bI\s+grant\b",
        r"\bI\s+acknowledge\b",
        r"\bI\s+admit\b",
        r"\bI\s+accept\b",
        r"\bI\s+yield\b",
        r"\bwe\s+concede\b",
        r"\bwe\s+grant\b",
        r"\bwe\s+acknowledge\b",
        r"\bwe\s+admit\b",
        r"\bwe\s+accept\b",
        r"\bwe\s+yield\b",
        r"\bI\s+must\s+admit\b",
        r"\bI\s+have\s+to\s+admit\b",
        r"\bI\s+will\s+grant\b",
        r"\bI\s+would\s+concede\b",
        r"\bone\s+must\s+admit\b",
        r"\bone\s+has\s+to\s+admit\b",
        r"\bone\s+must\s+grant\b",
        r"\bone\s+cannot\s+deny\b",
        r"\bthe\s+reader\s+may\s+object\b",
        r"\ba\s+critic\s+might\s+(say|argue|object|note)\b",
    ]
]


# ── channel 5: concessive clause structures ─────────────────────
# Syntactically complex concession markers that embed a
# subordinate clause.

_CLAUSE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bwhile\s+it\s+(is|may\s+be|might\s+be|could\s+be)\s+true\b",
        r"\bthough\s+one\s+(may|might|could)\b",
        r"\beven\s+if\s+we\s+(accept|grant|assume|allow)\b",
        r"\beven\s+assuming\b",
        r"\bregardless\s+of\s+whether\b",
        r"\birrespective\s+of\s+whether\b",
        r"\bhowever\s+much\b",
        r"\bno\s+matter\s+how\s+much\b",
        r"\bnotwithstanding\s+that\b",
        r"\bgranted\s+that\b",
        r"\badmitting\s+that\b",
        r"\bconceding\s+that\b",
        r"\ballowing\s+that\b",
        r"\bsupposing\s+(that\s+)?even\b",
    ]
]


# ── helpers ─────────────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    parts = _SENTENCE_SPLIT.split(text.strip())
    return len([p for p in parts if p.strip()])


def _count_words(text: str) -> int:
    return len(_WORD_SPLIT.findall(text))


def _extract_words(text: str) -> List[str]:
    return [w.lower() for w in _WORD_SPLIT.findall(text)]


def _count_phrase_hits(text: str, phrases: set) -> int:
    hits = 0
    for phrase in phrases:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        hits += len(pattern.findall(text))
    return hits


def _count_regex_hits(text: str, patterns: list) -> int:
    return sum(len(p.findall(text)) for p in patterns)


# ── dataclass ───────────────────────────────────────────────────


@dataclass
class ConcessionDensityResult:
    """Result of concession density measurement."""

    concession_index: float = 0.0
    classification: str = "unilateral"

    # Channel counts
    conjunction_count: int = 0
    adverb_count: int = 0
    phrase_count: int = 0
    performative_count: int = 0
    clause_count: int = 0

    # Composite channel scores (0.0–1.0)
    conjunction_score: float = 0.0
    adverb_score: float = 0.0
    phrase_score: float = 0.0
    performative_score: float = 0.0
    clause_score: float = 0.0

    # Metadata
    total_concession_markers: int = 0
    total_sentences: int = 0
    total_words: int = 0


# ── main measurement function ──────────────────────────────────


def measure_concession_density(text: str) -> ConcessionDensityResult:
    """Measure concession density of a text.

    Returns a ConcessionDensityResult with concession_index
    (0.0–1.0) and classification.
    """
    result = ConcessionDensityResult()

    stripped = text.strip()
    if not stripped:
        result.classification = "unilateral"
        return result

    sentences = _count_sentences(text)
    words = _count_words(text)
    result.total_sentences = sentences
    result.total_words = words

    denom = max(sentences, 1)

    # ── count each channel ───────────────────────────────────

    # 1. Concessive conjunctions (cap: 2 per sentence)
    all_words = _extract_words(text)
    conj_hits = sum(1 for w in all_words if w in _CONJUNCTION_SINGLE)
    conj_hits += sum(1 for w in all_words if w in _CONJUNCTION_AMBIGUOUS)
    conj_hits += _count_phrase_hits(text, _CONJUNCTION_PHRASES)
    result.conjunction_count = conj_hits
    result.conjunction_score = min(1.0, (conj_hits / denom) / 2.0)

    # 2. Concessive adverbs (cap: 2 per sentence)
    adverb_hits = sum(1 for w in all_words if w in _ADVERB_SINGLE)
    adverb_hits += _count_phrase_hits(text, _ADVERB_PHRASES)
    result.adverb_count = adverb_hits
    result.adverb_score = min(1.0, (adverb_hits / denom) / 2.0)

    # 3. Concessive phrases (cap: 1.5 per sentence)
    phrase_hits = _count_phrase_hits(text, _CONCESSION_PHRASES)
    result.phrase_count = phrase_hits
    result.phrase_score = min(1.0, (phrase_hits / denom) / 1.5)

    # 4. Performative concessions (cap: 1 per sentence)
    performative_hits = _count_regex_hits(text, _PERFORMATIVE_PATTERNS)
    result.performative_count = performative_hits
    result.performative_score = min(1.0, (performative_hits / denom) / 1.0)

    # 5. Concessive clause structures (cap: 1 per sentence)
    clause_hits = _count_regex_hits(text, _CLAUSE_PATTERNS)
    result.clause_count = clause_hits
    result.clause_score = min(1.0, (clause_hits / denom) / 1.0)

    # ── composite index ──────────────────────────────────────
    # Weights: conjunction 0.30, adverb 0.20, phrase 0.20,
    # performative 0.15, clause 0.15
    result.concession_index = round(
        0.30 * result.conjunction_score
        + 0.20 * result.adverb_score
        + 0.20 * result.phrase_score
        + 0.15 * result.performative_score
        + 0.15 * result.clause_score,
        4,
    )

    result.concession_index = min(1.0, max(0.0, result.concession_index))

    result.total_concession_markers = (
        conj_hits
        + adverb_hits
        + phrase_hits
        + performative_hits
        + clause_hits
    )

    # ── classification ───────────────────────────────────────
    idx = result.concession_index
    if idx < 0.05:
        result.classification = "unilateral"
    elif idx < 0.15:
        result.classification = "occasional"
    elif idx < 0.30:
        result.classification = "balanced"
    elif idx < 0.50:
        result.classification = "deliberative"
    else:
        result.classification = "dialectical"

    return result
