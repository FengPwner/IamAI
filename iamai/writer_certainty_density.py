#!/usr/bin/env python3
"""writer_certainty_density — measure how much prose commits to its assertions.

Certainty is the linguistic signal that a writer stands behind what
they say.  It is not bravado and it is not volume — it is the
difference between "The experiment demonstrates that X causes Y"
and "The experiment may suggest that X could be related to Y."
Both sentences convey the same finding; only one of them commits.

Certainty manifests through six measurable channels.

**Epistemic commitment verbs** signal that the writer takes
ownership of a claim: *know, prove, demonstrate, establish,
confirm, show, determine, conclude, verify, guarantee, ensure*.
These verbs do not merely report — they assert.

**Absolute quantifiers** leave no room for exception:
*all, every, always, never, none, no one, everyone, nothing,
entirely, completely, wholly, fully, absolutely, totally*.
They close the escape hatches that hedging leaves open.

**Definitive determiners** point at specific, unambiguous
referents: *the, this, that, these, those, the specific,
the particular, the exact*.  They say "I know which one I
mean" rather than "some unspecified instance."

**Certainty adverbs** modify assertions with unambiguous
confidence: *certainly, definitely, undoubtedly, unquestionably,
clearly, obviously, plainly, manifestly, patently, necessarily,
inevitably, categorically, unequivocally, indisputably*.

**Rejection-of-doubt phrases** explicitly dismiss alternative
interpretations: *there is no doubt, it is certain, beyond question,
without exception, incontestably, irrefutably, as a matter of fact,
it is well established, the evidence is conclusive*.

**Performative assertions** use speech-act verbs that create
commitment by the act of uttering: *I assert, I maintain, I contend,
I insist, I affirm, I declare, I state categorically*.

A text with high certainty density reads like a verdict or a
manifesto — every sentence plants its flag.  A text with low
certainty density reads like a hypothesis or a question — every
sentence leaves room for revision.  Neither is inherently better:
scientific writing earns its certainty through evidence; polemic
writing borrows certainty from conviction.  Knowing where a text
sits on this spectrum helps calibrate it for its audience.

This module measures certainty density as a composite index
(0.0 – 1.0) across six independent channels, orthogonal to
hedging (which measures commitment *avoidance* — a text can
score low on both if it simply asserts plainly without either
amplifying or dampening commitment), conviction (which measures
argumentative force including evidence quality), formality
(which measures register), abstraction (which measures conceptual
distance), and verbosity (which measures padding).

written by Qwen during manual caretaker visit 650, 2026-11-16
"""

import re
from dataclasses import dataclass, field
from typing import List


# ── regex patterns ──────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"[a-zA-Z'-]+")


# ── epistemic commitment verbs ──────────────────────────────────
# Verbs that signal the writer takes ownership of a claim.

_COMMITMENT_VERBS = set(
    w.lower()
    for w in [
        # Core assertion verbs
        "know", "knew", "known", "prove", "proved", "proven", "proves",
        "demonstrate", "demonstrated", "demonstrates", "demonstrating",
        "establish", "established", "establishes", "establishing",
        "confirm", "confirmed", "confirms", "confirming",
        "show", "showed", "shown", "shows", "showing",
        "determine", "determined", "determines", "determining",
        "conclude", "concluded", "concludes", "concluding",
        "verify", "verified", "verifies", "verifying",
        "guarantee", "guaranteed", "guarantees", "guaranteeing",
        "ensure", "ensured", "ensures", "ensuring",
        # Stronger assertion verbs
        "assert", "asserted", "asserts", "asserting",
        "maintain", "maintained", "maintains", "maintaining",
        "contend", "contended", "contends", "contending",
        "insist", "insisted", "insists", "insisting",
        "affirm", "affirmed", "affirms", "affirming",
        "declare", "declared", "declares", "declaring",
        "state", "stated", "states", "stating",
        "warrant", "warranted", "warrants", "warranting",
        "certify", "certified", "certifies", "certifying",
        "attest", "attested", "attests", "attesting",
        "avow", "avowed", "avows", "avowing",
        "swear", "swore", "sworn", "swears", "swearing",
        "vouch", "vouched", "vouches", "vouching",
        "pledge", "pledged", "pledges", "pledging",
        "promise", "promised", "promises", "promising",
    ]
)


# ── absolute quantifiers ────────────────────────────────────────
# Words that leave no room for exception.

_ABSOLUTE_QUANTIFIERS = set(
    w.lower()
    for w in [
        "all", "every", "always", "never", "none",
        "no one", "everyone", "everything", "nothing",
        "nobody", "everybody", "entirely", "completely",
        "wholly", "fully", "absolutely", "totally",
        "utterly", "thoroughly", "exhaustively",
        "without exception", "in every case",
        "each and every", "any and all",
    ]
)

# Single-word absolute quantifiers for word-level matching.
_ABSOLUTE_SINGLE = set(
    w.lower()
    for w in [
        "all", "every", "always", "never", "none",
        "everyone", "everything", "nothing",
        "nobody", "everybody", "entirely", "completely",
        "wholly", "fully", "absolutely", "totally",
        "utterly", "thoroughly", "exhaustively",
    ]
)


# ── definitive determiners ──────────────────────────────────────
# Determiners that signal specific, unambiguous reference.

_DEFINITIVE_DETERMINERS = set(
    w.lower()
    for w in [
        "this", "that", "these", "those",
    ]
)

_DEFINITIVE_PHRASES = [
    re.compile(r"\bthe\s+specific\b", re.IGNORECASE),
    re.compile(r"\bthe\s+particular\b", re.IGNORECASE),
    re.compile(r"\bthe\s+exact\b", re.IGNORECASE),
    re.compile(r"\bthe\s+precise\b", re.IGNORECASE),
    re.compile(r"\bthe\s+definite\b", re.IGNORECASE),
    re.compile(r"\bthe\s+actual\b", re.IGNORECASE),
]


# ── certainty adverbs ───────────────────────────────────────────
# Adverbs that modify assertions with unambiguous confidence.

_CERTAINTY_ADVERBS = set(
    w.lower()
    for w in [
        "certainly", "definitely", "undoubtedly", "unquestionably",
        "clearly", "obviously", "plainly", "manifestly", "patently",
        "necessarily", "inevitably", "categorically", "unequivocally",
        "indisputably", "incontrovertibly", "conclusively",
        "decisively", "unambiguously", "explicitly", "emphatically",
        "unfailingly", "invariably", "irrevocably", "irrefutably",
        "incontestably", "undeniably", "unmistakably", "evidently",
        "palpably", "visibly", "demonstrably", "provably",
        "surely", "assuredly", "confidently", "resolutely",
        "unequivocally", "unconditionally", "unreservedly",
    ]
)


# ── rejection-of-doubt phrases ──────────────────────────────────
# Multi-word constructions that explicitly dismiss uncertainty.

_REJECTION_PHRASES = [
    re.compile(r"\bthere\s+is\s+no\s+doubt\b", re.IGNORECASE),
    re.compile(r"\bthere\s+can\s+be\s+no\s+doubt\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+certain\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+clear\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+obvious\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+undeniable\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+evident\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+incontrovertible\b", re.IGNORECASE),
    re.compile(r"\bbeyond\s+question\b", re.IGNORECASE),
    re.compile(r"\bbeyond\s+(?:a\s+|any\s+)?doubt\b", re.IGNORECASE),
    re.compile(r"\bwithout\s+exception\b", re.IGNORECASE),
    re.compile(r"\bwithout\s+(?:a\s+)?doubt\b", re.IGNORECASE),
    re.compile(r"\bas\s+a\s+matter\s+of\s+fact\b", re.IGNORECASE),
    re.compile(r"\bthe\s+evidence\s+is\s+conclusive\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+well\s+established\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+widely\s+accepted\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+universally\s+acknowledged\b", re.IGNORECASE),
    re.compile(r"\bthe\s+fact\s+(?:is|was|remains)\b", re.IGNORECASE),
    re.compile(r"\bmake\s+no\s+mistake\b", re.IGNORECASE),
    re.compile(r"\brest\s+assured\b", re.IGNORECASE),
    re.compile(r"\bmark\s+my\s+words\b", re.IGNORECASE),
    re.compile(r"\btake\s+it\s+from\s+me\b", re.IGNORECASE),
]


# ── performative assertions ─────────────────────────────────────
# Speech-act constructions that create commitment by utterance.

_PERFORMATIVE_PATTERNS = [
    re.compile(r"\bI\s+assert\b", re.IGNORECASE),
    re.compile(r"\bI\s+maintain\b", re.IGNORECASE),
    re.compile(r"\bI\s+contend\b", re.IGNORECASE),
    re.compile(r"\bI\s+insist\b", re.IGNORECASE),
    re.compile(r"\bI\s+affirm\b", re.IGNORECASE),
    re.compile(r"\bI\s+declare\b", re.IGNORECASE),
    re.compile(r"\bI\s+state\s+categorically\b", re.IGNORECASE),
    re.compile(r"\bI\s+am\s+certain\b", re.IGNORECASE),
    re.compile(r"\bI\s+am\s+sure\b", re.IGNORECASE),
    re.compile(r"\bI\s+am\s+confident\b", re.IGNORECASE),
    re.compile(r"\bI\s+have\s+no\s+doubt\b", re.IGNORECASE),
    re.compile(r"\bwe\s+assert\b", re.IGNORECASE),
    re.compile(r"\bwe\s+maintain\b", re.IGNORECASE),
    re.compile(r"\bwe\s+contend\b", re.IGNORECASE),
    re.compile(r"\bwe\s+insist\b", re.IGNORECASE),
    re.compile(r"\bwe\s+affirm\b", re.IGNORECASE),
    re.compile(r"\bwe\s+declare\b", re.IGNORECASE),
    re.compile(r"\bwe\s+are\s+certain\b", re.IGNORECASE),
    re.compile(r"\bwe\s+are\s+confident\b", re.IGNORECASE),
]


# ── helpers ─────────────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    """Count sentences in text."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]
    return max(len(sentences), 1)


def _count_words(text: str) -> int:
    """Count words in text."""
    return len(_WORD_SPLIT.findall(text))


def _extract_words(text: str) -> List[str]:
    """Extract all words from text, lowercased."""
    return [w.lower() for w in _WORD_SPLIT.findall(text)]


# ── result dataclass ────────────────────────────────────────────


@dataclass
class CertaintyDensityResult:
    """Result of certainty density measurement."""

    certainty_index: float = 0.0
    classification: str = "tentative"

    # Channel counts
    commitment_verb_count: int = 0
    absolute_quantifier_count: int = 0
    definitive_determiner_count: int = 0
    certainty_adverb_count: int = 0
    rejection_phrase_count: int = 0
    performative_count: int = 0

    # Composite channel scores (0.0–1.0)
    commitment_score: float = 0.0
    absolute_score: float = 0.0
    definitive_score: float = 0.0
    adverb_score: float = 0.0
    rejection_score: float = 0.0
    performative_score: float = 0.0

    # Metadata
    total_certainty_markers: int = 0
    total_sentences: int = 0
    total_words: int = 0


# ── main measurement function ──────────────────────────────────


def measure_certainty_density(text: str) -> CertaintyDensityResult:
    """Measure certainty density of a text.

    Returns a CertaintyDensityResult with certainty_index (0.0–1.0)
    and classification.
    """
    result = CertaintyDensityResult()

    stripped = text.strip()
    if not stripped:
        result.classification = "tentative"
        return result

    sentences = _count_sentences(text)
    words = _count_words(text)
    result.total_sentences = sentences
    result.total_words = words

    # Per-sentence rates, normalized against typical maxima
    denom = max(sentences, 1)
    all_words = _extract_words(text)

    # ── count each channel ───────────────────────────────────

    # 1. Commitment verbs (cap: 2 per sentence)
    commitment_hits = sum(1 for w in all_words if w in _COMMITMENT_VERBS)
    result.commitment_verb_count = commitment_hits
    result.commitment_score = min(1.0, (commitment_hits / denom) / 2.0)

    # 2. Absolute quantifiers (cap: 1.5 per sentence)
    absolute_hits = sum(1 for w in all_words if w in _ABSOLUTE_SINGLE)
    for phrase in _ABSOLUTE_QUANTIFIERS - _ABSOLUTE_SINGLE:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        absolute_hits += len(pattern.findall(text))
    result.absolute_quantifier_count = absolute_hits
    result.absolute_score = min(1.0, (absolute_hits / denom) / 1.5)

    # 3. Definitive determiners (cap: 4 per sentence — very common)
    definitive_hits = sum(1 for w in all_words if w in _DEFINITIVE_DETERMINERS)
    for pattern in _DEFINITIVE_PHRASES:
        definitive_hits += len(pattern.findall(text))
    result.definitive_determiner_count = definitive_hits
    result.definitive_score = min(1.0, (definitive_hits / denom) / 4.0)

    # 4. Certainty adverbs (cap: 1.5 per sentence)
    adverb_hits = sum(1 for w in all_words if w in _CERTAINTY_ADVERBS)
    result.certainty_adverb_count = adverb_hits
    result.adverb_score = min(1.0, (adverb_hits / denom) / 1.5)

    # 5. Rejection-of-doubt phrases (cap: 0.5 per sentence — rare)
    rejection_hits = 0
    for pattern in _REJECTION_PHRASES:
        rejection_hits += len(pattern.findall(text))
    result.rejection_phrase_count = rejection_hits
    result.rejection_score = min(1.0, (rejection_hits / denom) / 0.5)

    # 6. Performative assertions (cap: 0.5 per sentence — rare)
    performative_hits = 0
    for pattern in _PERFORMATIVE_PATTERNS:
        performative_hits += len(pattern.findall(text))
    result.performative_count = performative_hits
    result.performative_score = min(1.0, (performative_hits / denom) / 0.5)

    # ── composite index ──────────────────────────────────────
    # Weights: commitment 0.25, absolute 0.20, adverb 0.20,
    # definitive 0.15, rejection 0.10, performative 0.10
    result.certainty_index = round(
        0.25 * result.commitment_score
        + 0.20 * result.absolute_score
        + 0.20 * result.adverb_score
        + 0.15 * result.definitive_score
        + 0.10 * result.rejection_score
        + 0.10 * result.performative_score,
        4,
    )

    result.certainty_index = min(1.0, max(0.0, result.certainty_index))

    result.total_certainty_markers = (
        commitment_hits
        + absolute_hits
        + definitive_hits
        + adverb_hits
        + rejection_hits
        + performative_hits
    )

    # ── classification ───────────────────────────────────────
    idx = result.certainty_index
    if idx < 0.10:
        result.classification = "tentative"
    elif idx < 0.25:
        result.classification = "measured"
    elif idx < 0.45:
        result.classification = "assertive"
    elif idx < 0.65:
        result.classification = "confident"
    else:
        result.classification = "dogmatic"

    return result
