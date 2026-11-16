#!/usr/bin/env python3
"""writer_causal_density — measure how much prose articulates cause and effect.

Causal density is the degree to which a text explicitly links events,
conditions, and outcomes through cause-and-effect reasoning.  It is one
of the fundamental dimensions of analytical and explanatory writing:
a text that merely *describes* what happened sits at one end of the
spectrum, while a text that traces *why* things happened, *what* they
lead to, and *under what conditions* they would differ sits at the other.

High causal density is the hallmark of scientific explanation, legal
argument, and good engineering documentation.  Low causal density is
not a flaw — narrative prose, poetry, and instruction manuals often
deliberately avoid explicit causation — but when a text *aims* to
explain or persuade, thin causal reasoning is a red flag.

Causation manifests through five measurable channels.

**Explicit causal connectives** are the most direct signals:
*because, since, therefore, thus, hence, consequently, as a result,
due to, caused by, owing to, on account of, for this reason,
accordingly, so*.  They leave no ambiguity about the direction of
the causal link — "The server crashed because the disk was full."

**Conditional causation** expresses cause-effect relationships that
depend on a precondition: *if, when, whenever, unless, provided that,
in case, on condition that, as long as, so long as*.  They describe
what *would* happen *given* some condition — "If the load exceeds
capacity, the circuit breaker trips."

**Teleological markers** explain actions by their intended purpose
or goal: *in order to, so that, to ensure, to prevent, to avoid,
for the purpose of, with the aim of, with a view to, designed to,
intended to, aimed at*.  They are forward-looking causation — the
effect is the *reason* for the cause — "The cache was introduced
to reduce database load."

**Consequence chains** describe outcomes that flow from a prior
event: *leading to, resulting in, which means, which causes,
triggers, produces, generates, gives rise to, brings about,
precipitates, sets off, sparks*.  They trace the downstream effects
of an upstream cause — "The policy change resulted in a 40%
increase in enrollment."

**Counterfactual causation** reasons about causes by imagining their
absence: *would have, could have, might have, had...would,
without...would, but for, were it not for, in the absence of,
if not for*.  They identify causes by asking "what if this had not
happened?" — "Had the backup been current, the data loss would
have been minimal."

A text with high causal density reads as explanatory, rigorous,
and mechanistic — it traces chains of reasoning and makes its
logic explicit.  A text with low causal density reads as descriptive,
narrative, or assertoric — it states facts without linking them.
Neither is inherently better: a causal-rich research paper explains
phenomena; a causal-poor poem evokes them.

This module measures causal density as a composite index
(0.0 – 1.0) across five independent channels, orthogonal to
concession (acknowledging opposing views), hedging (expressing
uncertainty), urgency (signaling time pressure), and formality
(register and decorum).

written by Qwen during manual caretaker visit 654, 2026-11-16
"""

import re
from dataclasses import dataclass
from typing import List


# ── regex patterns ──────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"[a-zA-Z'-]+")


# ── channel 1: explicit causal connectives ──────────────────────
# Single-word connectives that unambiguously signal cause or effect.

_CAUSAL_SINGLE = set(
    w.lower()
    for w in [
        # Cause-direction (X because Y)
        "because",
        "since",
        "for",
        # Effect-direction (X therefore Y)
        "therefore",
        "thus",
        "hence",
        "consequently",
        "accordingly",
        "so",
    ]
)

# Multi-word causal phrases
_CAUSAL_PHRASES = [
    "as a result",
    "due to",
    "caused by",
    "owing to",
    "on account of",
    "for this reason",
    "as a consequence",
    "in consequence",
    "by virtue of",
    "in light of",
    "in view of",
    "thanks to",
    "on grounds of",
    "by reason of",
    "stemming from",
    "arising from",
    "resulting from",
]

# Ambiguous words that are causal only in certain contexts.
# "as" can be causal ("as the load increased") or temporal ("as I walked").
# "given" can be causal ("given the constraints") or conditional.
_CAUSAL_AMBIGUOUS = set(
    w.lower()
    for w in [
        "given",
    ]
)


# ── channel 2: conditional causation ────────────────────────────
# Words and phrases expressing condition-dependent cause-effect.

_CONDITIONAL_SINGLE = set(
    w.lower()
    for w in [
        "if",
        "when",
        "whenever",
        "unless",
    ]
)

_CONDITIONAL_PHRASES = [
    "provided that",
    "providing that",
    "in case",
    "on condition that",
    "as long as",
    "so long as",
    "only if",
    "even if",
    "in the event that",
    "suppose that",
    "assuming that",
]


# ── channel 3: teleological markers (purpose/goal) ─────────────
# Phrases that explain an action by its intended effect.

_TELEOLOGICAL_PHRASES = [
    "in order to",
    "so that",
    "so as to",
    "to ensure",
    "to prevent",
    "to avoid",
    "to reduce",
    "to improve",
    "to increase",
    "to minimize",
    "to maximize",
    "to protect",
    "to maintain",
    "to achieve",
    "to enable",
    "for the purpose of",
    "with the aim of",
    "with a view to",
    "with the goal of",
    "with the intent of",
    "for the sake of",
    "in an effort to",
    "in a bid to",
    "in an attempt to",
]

_TELEOLOGICAL_PATTERNS = [
    re.compile(r"\bdesigned\s+to\b", re.IGNORECASE),
    re.compile(r"\bintended\s+to\b", re.IGNORECASE),
    re.compile(r"\baimed\s+at\b", re.IGNORECASE),
    re.compile(r"\bmeant\s+to\b", re.IGNORECASE),
    re.compile(r"\bcreated\s+to\b", re.IGNORECASE),
    re.compile(r"\bbuilt\s+to\b", re.IGNORECASE),
    re.compile(r"\bintroduced\s+to\b", re.IGNORECASE),
    re.compile(r"\bimplemented\s+to\b", re.IGNORECASE),
]


# ── channel 4: consequence chains ──────────────────────────────
# Phrases that trace downstream effects from an upstream cause.

_CONSEQUENCE_PHRASES = [
    "leading to",
    "resulting in",
    "which means",
    "which causes",
    "which led to",
    "which results in",
    "which leads to",
    "which triggered",
    "which produced",
    "giving rise to",
    "bringing about",
    "setting off",
]

_CONSEQUENCE_PATTERNS = [
    re.compile(r"\btriggers?\b", re.IGNORECASE),
    re.compile(r"\bproduces?\b", re.IGNORECASE),
    re.compile(r"\bgenerates?\b", re.IGNORECASE),
    re.compile(r"\bprecipitates?\b", re.IGNORECASE),
    re.compile(r"\bsparks?\b", re.IGNORECASE),
    re.compile(r"\bcauses?\b", re.IGNORECASE),
    re.compile(r"\bdrives?\b", re.IGNORECASE),
    re.compile(r"\byields?\b", re.IGNORECASE),
    re.compile(r"\bengenders?\b", re.IGNORECASE),
    re.compile(r"\bfosters?\b", re.IGNORECASE),
    re.compile(r"\bpromotes?\b", re.IGNORECASE),
    re.compile(r"\bfacilitates?\b", re.IGNORECASE),
]


# ── channel 5: counterfactual causation ────────────────────────
# Reasoning about causes by imagining their absence.

_COUNTERFACTUAL_PATTERNS = [
    re.compile(r"\bwould\s+have\b", re.IGNORECASE),
    re.compile(r"\bcould\s+have\b", re.IGNORECASE),
    re.compile(r"\bmight\s+have\b", re.IGNORECASE),
    re.compile(r"\bhad\s+\w+\s+\w+ed\b", re.IGNORECASE),  # "had X happened"
    re.compile(r"\bwere\s+it\s+not\s+for\b", re.IGNORECASE),
    re.compile(r"\bbut\s+for\b", re.IGNORECASE),
    re.compile(r"\bif\s+not\s+for\b", re.IGNORECASE),
    re.compile(r"\bin\s+the\s+absence\s+of\b", re.IGNORECASE),
    re.compile(r"\bwithout\s+.+?\s+would\b", re.IGNORECASE),
    re.compile(r"\bhad\s+it\s+not\s+been\b", re.IGNORECASE),
    re.compile(r"\bwould\s+not\s+have\b", re.IGNORECASE),
    re.compile(r"\bcould\s+not\s+have\b", re.IGNORECASE),
]


# ── helper functions ────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    """Count sentences by splitting on sentence-ending punctuation."""
    parts = _SENTENCE_SPLIT.split(text.strip())
    return len([p for p in parts if p.strip()])


def _count_words(text: str) -> int:
    """Count words in the text."""
    return len(_WORD_SPLIT.findall(text))


def _extract_words(text: str) -> List[str]:
    """Extract all words as lowercase strings."""
    return [w.lower() for w in _WORD_SPLIT.findall(text)]


def _count_phrase_hits(text: str, phrases: List[str]) -> int:
    """Count how many times phrases appear in text (case-insensitive)."""
    lower = text.lower()
    total = 0
    for phrase in phrases:
        total += lower.count(phrase.lower())
    return total


def _count_regex_hits(text: str, patterns: List[re.Pattern]) -> int:
    """Count total regex pattern hits across all patterns."""
    total = 0
    for pat in patterns:
        total += len(pat.findall(text))
    return total


# ── result dataclass ────────────────────────────────────────────


@dataclass
class CausalDensityResult:
    """Result of causal density measurement."""

    # Composite
    causal_index: float = 0.0
    classification: str = "descriptive"

    # Per-channel raw counts
    causal_connective_count: int = 0
    conditional_count: int = 0
    teleological_count: int = 0
    consequence_count: int = 0
    counterfactual_count: int = 0

    # Per-channel scores (0.0–1.0)
    causal_connective_score: float = 0.0
    conditional_score: float = 0.0
    teleological_score: float = 0.0
    consequence_score: float = 0.0
    counterfactual_score: float = 0.0

    # Metadata
    total_causal_markers: int = 0
    total_sentences: int = 0
    total_words: int = 0


# ── main measurement function ──────────────────────────────────


def measure_causal_density(text: str) -> CausalDensityResult:
    """Measure causal density of a text.

    Returns a CausalDensityResult with causal_index
    (0.0–1.0) and classification.
    """
    result = CausalDensityResult()

    stripped = text.strip()
    if not stripped:
        result.classification = "descriptive"
        return result

    sentences = _count_sentences(text)
    words = _count_words(text)
    result.total_sentences = sentences
    result.total_words = words

    denom = max(sentences, 1)

    # ── count each channel ───────────────────────────────────

    # 1. Explicit causal connectives (cap: 2 per sentence)
    all_words = _extract_words(text)
    causal_hits = sum(1 for w in all_words if w in _CAUSAL_SINGLE)
    causal_hits += sum(1 for w in all_words if w in _CAUSAL_AMBIGUOUS)
    causal_hits += _count_phrase_hits(text, _CAUSAL_PHRASES)
    result.causal_connective_count = causal_hits
    result.causal_connective_score = min(1.0, (causal_hits / denom) / 2.0)

    # 2. Conditional causation (cap: 2 per sentence)
    conditional_hits = sum(1 for w in all_words if w in _CONDITIONAL_SINGLE)
    conditional_hits += _count_phrase_hits(text, _CONDITIONAL_PHRASES)
    result.conditional_count = conditional_hits
    result.conditional_score = min(1.0, (conditional_hits / denom) / 2.0)

    # 3. Teleological markers (cap: 1.5 per sentence)
    teleological_hits = _count_phrase_hits(text, _TELEOLOGICAL_PHRASES)
    teleological_hits += _count_regex_hits(text, _TELEOLOGICAL_PATTERNS)
    result.teleological_count = teleological_hits
    result.teleological_score = min(1.0, (teleological_hits / denom) / 1.5)

    # 4. Consequence chains (cap: 1.5 per sentence)
    consequence_hits = _count_phrase_hits(text, _CONSEQUENCE_PHRASES)
    consequence_hits += _count_regex_hits(text, _CONSEQUENCE_PATTERNS)
    result.consequence_count = consequence_hits
    result.consequence_score = min(1.0, (consequence_hits / denom) / 1.5)

    # 5. Counterfactual causation (cap: 1 per sentence)
    counterfactual_hits = _count_regex_hits(text, _COUNTERFACTUAL_PATTERNS)
    result.counterfactual_count = counterfactual_hits
    result.counterfactual_score = min(1.0, (counterfactual_hits / denom) / 1.0)

    # ── composite index ──────────────────────────────────────
    # Weights: causal_connective 0.25, conditional 0.20,
    # consequence 0.25, teleological 0.20, counterfactual 0.10
    result.causal_index = round(
        0.25 * result.causal_connective_score
        + 0.20 * result.conditional_score
        + 0.25 * result.consequence_score
        + 0.20 * result.teleological_score
        + 0.10 * result.counterfactual_score,
        4,
    )

    result.causal_index = min(1.0, max(0.0, result.causal_index))

    result.total_causal_markers = (
        causal_hits
        + conditional_hits
        + teleological_hits
        + consequence_hits
        + counterfactual_hits
    )

    # ── classification ───────────────────────────────────────
    idx = result.causal_index
    if idx < 0.05:
        result.classification = "descriptive"
    elif idx < 0.15:
        result.classification = "associative"
    elif idx < 0.30:
        result.classification = "explanatory"
    elif idx < 0.50:
        result.classification = "analytical"
    else:
        result.classification = "mechanistic"

    return result
