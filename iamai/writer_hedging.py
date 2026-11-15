#!/usr/bin/env python3
"""writer_hedging — measure how much a writer avoids direct assertion.

Hedging is the linguistic art of not quite committing.  It softens
claims, creates plausible deniability, and signals epistemic humility
— or epistemic cowardice, depending on the dose.

A hedged sentence isn't wrong; it's cautious.  "The results suggest
a correlation" is more defensible than "the results prove a
correlation", but also less useful.  In scientific writing, hedging
is precision.  In opinion pieces, it's evasion.  In code
documentation, it's noise.

Hedging manifests through five measurable channels.  **Epistemic
hedges** soften the truth-commitment of a claim: "might", "could",
"seem", "appear", "tend to", "likely".  **Evidential hedges**
distance the writer from the source: "apparently", "reportedly",
"allegedly", "supposedly", "ostensibly".  **Frequency hedges**
blur how often something happens: "sometimes", "occasionally",
"often", "rarely", "seldom".  **Degree hedges** soften intensity:
"somewhat", "slightly", "rather", "fairly", "quite", "more or less".
**Proportion hedges** blur how much or how many: "mostly", "largely",
"partly", "generally", "typically", "usually".

An assertive writer says "X is Y".  A hedged writer says "X might
perhaps tend to be somewhat Y, generally speaking".  Both may be
correct, but the second has paid a readability tax for its caution.

This module measures hedging as a composite index (0.0 – 1.0) across
five independent channels, orthogonal to verbosity (which measures
padding-to-payload ratio), specificity (which measures precision of
reference), formality (which measures register), and exemplification
density (which measures use of examples).

written by Qwen during manual caretaker visit 646, 2026-11-16
"""

import re
from dataclasses import dataclass, field
from typing import List


# ── regex patterns ──────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"[a-zA-Z'-]+")


# ── epistemic hedges ────────────────────────────────────────────
# Words and phrases that soften truth-commitment.

_EPISTEMIC_HEDGES: List[re.Pattern] = [
    re.compile(r"\bmay\b", re.IGNORECASE),
    re.compile(r"\bmight\b", re.IGNORECASE),
    re.compile(r"\bcould\b", re.IGNORECASE),
    re.compile(r"\bperhaps\b", re.IGNORECASE),
    re.compile(r"\bmaybe\b", re.IGNORECASE),
    re.compile(r"\bpossibly\b", re.IGNORECASE),
    re.compile(r"\bprobably\b", re.IGNORECASE),
    re.compile(r"\blikely\b", re.IGNORECASE),
    re.compile(r"\bunlikely\b", re.IGNORECASE),
    re.compile(r"\bseem(?:s|ed)?\b", re.IGNORECASE),
    re.compile(r"\bappear(?:s|ed)?\b", re.IGNORECASE),
    re.compile(r"\btend(?:s|ed)?\s+to\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+(?:not\s+)?(?:un)?clear\b", re.IGNORECASE),
    re.compile(r"\bit\s+(?:is|was)\s+(?:not\s+)?(?:un)?certain\b", re.IGNORECASE),
    re.compile(r"\barguably\b", re.IGNORECASE),
    re.compile(r"\bconceivably\b", re.IGNORECASE),
    re.compile(r"\bplausibly\b", re.IGNORECASE),
    re.compile(r"\bto\s+some\s+(?:degree|extent)\b", re.IGNORECASE),
    re.compile(r"\bin\s+some\s+(?:way|sense|cases?)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+necessarily\b", re.IGNORECASE),
    re.compile(r"\bit\s+would\s+seem\b", re.IGNORECASE),
    re.compile(r"\bone\s+could\s+argue\b", re.IGNORECASE),
    re.compile(r"\bthere\s+is\s+(?:some\s+)?(?:evidence|reason)\s+to\s+(?:believe|suggest)\b", re.IGNORECASE),
]


# ── evidential hedges ───────────────────────────────────────────
# Words that distance the writer from the claim's source.

_EVIDENTIAL_HEDGES: List[re.Pattern] = [
    re.compile(r"\bapparently\b", re.IGNORECASE),
    re.compile(r"\breportedly\b", re.IGNORECASE),
    re.compile(r"\ballegedly\b", re.IGNORECASE),
    re.compile(r"\bsupposedly\b", re.IGNORECASE),
    re.compile(r"\bostensibly\b", re.IGNORECASE),
    re.compile(r"\bseemingly\b", re.IGNORECASE),
    re.compile(r"\baccording\s+to\s+(?:some|many|various)\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+said\s+that\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+believed\s+that\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+thought\s+that\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+rumored\b", re.IGNORECASE),
    re.compile(r"\bword\s+has\s+it\b", re.IGNORECASE),
    re.compile(r"\breputedly\b", re.IGNORECASE),
    re.compile(r"\bpurportedly\b", re.IGNORECASE),
]


# ── frequency hedges ────────────────────────────────────────────
# Words that blur how often something happens.

_FREQUENCY_HEDGES: List[re.Pattern] = [
    re.compile(r"\bsometimes\b", re.IGNORECASE),
    re.compile(r"\boccasionally\b", re.IGNORECASE),
    re.compile(r"\boften\b", re.IGNORECASE),
    re.compile(r"\bfrequently\b", re.IGNORECASE),
    re.compile(r"\brarely\b", re.IGNORECASE),
    re.compile(r"\bseldom\b", re.IGNORECASE),
    re.compile(r"\bat\s+times\b", re.IGNORECASE),
    re.compile(r"\bfrom\s+time\s+to\s+time\b", re.IGNORECASE),
    re.compile(r"\bnow\s+and\s+(?:then|again)\b", re.IGNORECASE),
    re.compile(r"\bhere\s+and\s+there\b", re.IGNORECASE),
    re.compile(r"\bintermittently\b", re.IGNORECASE),
    re.compile(r"\bsporadically\b", re.IGNORECASE),
]


# ── degree hedges ───────────────────────────────────────────────
# Words that soften intensity.

_DEGREE_HEDGES: List[re.Pattern] = [
    re.compile(r"\bsomewhat\b", re.IGNORECASE),
    re.compile(r"\bslightly\b", re.IGNORECASE),
    re.compile(r"\brather\b", re.IGNORECASE),
    re.compile(r"\bfairly\b", re.IGNORECASE),
    re.compile(r"\bquite\b", re.IGNORECASE),
    re.compile(r"\bmore\s+or\s+less\b", re.IGNORECASE),
    re.compile(r"\bkind\s+of\b", re.IGNORECASE),
    re.compile(r"\bsort\s+of\b", re.IGNORECASE),
    re.compile(r"\ba\s+bit\b", re.IGNORECASE),
    re.compile(r"\ba\s+little\b", re.IGNORECASE),
    re.compile(r"\bmildly\b", re.IGNORECASE),
    re.compile(r"\bmoderately\b", re.IGNORECASE),
    re.compile(r"\breasonably\b", re.IGNORECASE),
    re.compile(r"\bnot\s+(?:entirely|wholly|completely)\b", re.IGNORECASE),
]


# ── proportion hedges ───────────────────────────────────────────
# Words that blur how much or how many.

_PROPORTION_HEDGES: List[re.Pattern] = [
    re.compile(r"\bmostly\b", re.IGNORECASE),
    re.compile(r"\blargely\b", re.IGNORECASE),
    re.compile(r"\bpartly\b", re.IGNORECASE),
    re.compile(r"\bpartially\b", re.IGNORECASE),
    re.compile(r"\bgenerally\b", re.IGNORECASE),
    re.compile(r"\btypically\b", re.IGNORECASE),
    re.compile(r"\busually\b", re.IGNORECASE),
    re.compile(r"\bfor\s+the\s+most\s+part\b", re.IGNORECASE),
    re.compile(r"\bin\s+general\b", re.IGNORECASE),
    re.compile(r"\bas\s+a\s+rule\b", re.IGNORECASE),
    re.compile(r"\bmore\s+often\s+than\s+not\b", re.IGNORECASE),
    re.compile(r"\bbroadly\s+speaking\b", re.IGNORECASE),
    re.compile(r"\bin\s+most\s+cases\b", re.IGNORECASE),
]


# ── result dataclass ────────────────────────────────────────────


@dataclass
class HedgingResult:
    """Results of hedging analysis."""

    # Raw counts
    epistemic_count: int = 0
    evidential_count: int = 0
    frequency_count: int = 0
    degree_count: int = 0
    proportion_count: int = 0

    # Rates per 100 sentences
    epistemic_rate: float = 0.0
    evidential_rate: float = 0.0
    frequency_rate: float = 0.0
    degree_rate: float = 0.0
    proportion_rate: float = 0.0

    # Composite
    hedging_index: float = 0.0
    classification: str = "assertive"

    # Metadata
    total_sentences: int = 0
    total_words: int = 0
    total_hedges: int = 0
    details: dict = field(default_factory=dict)


# ── helpers ─────────────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    """Count sentences (approximate)."""
    stripped = text.strip()
    if not stripped:
        return 0
    sentences = [s for s in _SENTENCE_SPLIT.split(stripped) if s.strip()]
    return max(len(sentences), 1)


def _count_words(text: str) -> int:
    """Count words."""
    return len(_WORD_SPLIT.findall(text))


def _count_pattern_matches(text: str, patterns: List[re.Pattern]) -> int:
    """Count total matches across a list of patterns."""
    return sum(len(p.findall(text)) for p in patterns)


# ── main measurement function ───────────────────────────────────


def measure_hedging(text: str) -> HedgingResult:
    """Measure hedging density of a text.

    Returns a HedgingResult with hedging_index (0.0–1.0)
    and classification.
    """
    result = HedgingResult()

    stripped = text.strip()
    if not stripped:
        result.classification = "assertive"
        return result

    sentences = _count_sentences(text)
    words = _count_words(text)
    result.total_sentences = sentences
    result.total_words = words

    scale = 100.0 / max(sentences, 1)

    # ── count each channel ───────────────────────────────────
    result.epistemic_count = _count_pattern_matches(text, _EPISTEMIC_HEDGES)
    result.evidential_count = _count_pattern_matches(text, _EVIDENTIAL_HEDGES)
    result.frequency_count = _count_pattern_matches(text, _FREQUENCY_HEDGES)
    result.degree_count = _count_pattern_matches(text, _DEGREE_HEDGES)
    result.proportion_count = _count_pattern_matches(text, _PROPORTION_HEDGES)

    result.total_hedges = (
        result.epistemic_count
        + result.evidential_count
        + result.frequency_count
        + result.degree_count
        + result.proportion_count
    )

    # ── rates per 100 sentences ──────────────────────────────
    result.epistemic_rate = round(result.epistemic_count * scale, 3)
    result.evidential_rate = round(result.evidential_count * scale, 3)
    result.frequency_rate = round(result.frequency_count * scale, 3)
    result.degree_rate = round(result.degree_count * scale, 3)
    result.proportion_rate = round(result.proportion_count * scale, 3)

    # ── composite hedging index (0.0 – 1.0) ──────────────────
    # Normalize each channel to ~0–1 via typical maxima
    cap_epi = min(1.0, result.epistemic_rate / 25.0)
    cap_evi = min(1.0, result.evidential_rate / 10.0)
    cap_freq = min(1.0, result.frequency_rate / 15.0)
    cap_deg = min(1.0, result.degree_rate / 20.0)
    cap_prop = min(1.0, result.proportion_rate / 15.0)

    composite = (
        0.30 * cap_epi
        + 0.15 * cap_evi
        + 0.15 * cap_freq
        + 0.25 * cap_deg
        + 0.15 * cap_prop
    )
    result.hedging_index = round(min(1.0, composite), 4)

    # ── classification ───────────────────────────────────────
    idx = result.hedging_index
    if idx < 0.10:
        result.classification = "assertive"
    elif idx < 0.25:
        result.classification = "measured"
    elif idx < 0.45:
        result.classification = "cautious"
    elif idx < 0.65:
        result.classification = "tentative"
    else:
        result.classification = "noncommittal"

    result.details = {
        "epistemic_rate": result.epistemic_rate,
        "evidential_rate": result.evidential_rate,
        "frequency_rate": result.frequency_rate,
        "degree_rate": result.degree_rate,
        "proportion_rate": result.proportion_rate,
        "hedging_index": result.hedging_index,
        "classification": result.classification,
    }

    return result


# ── CLI convenience ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else None
    if path:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    r = measure_hedging(text)
    print(f"hedging_index             : {r.hedging_index:.4f}")
    print(f"classification            : {r.classification}")
    print(f"epistemic_rate            : {r.epistemic_rate}")
    print(f"evidential_rate           : {r.evidential_rate}")
    print(f"frequency_rate            : {r.frequency_rate}")
    print(f"degree_rate               : {r.degree_rate}")
    print(f"proportion_rate           : {r.proportion_rate}")
    print(f"total_hedges              : {r.total_hedges}")
    print(f"total_sentences           : {r.total_sentences}")
    print(f"total_words               : {r.total_words}")
