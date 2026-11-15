#!/usr/bin/env python3
"""writer_self_correction — measure how much prose corrects itself mid-stream.

Every writer, at some point, stops and says: no, that's not right.
"Or rather."  "I mean."  "More precisely."  "To put it another way."
These moments of self-interruption — where the text turns back on
itself to revise, retract, refine, or reformulate — are what this
module measures.

Self-correction is one of the most revealing linguistic behaviors.
It exposes the gap between what a writer almost said and what they
decided to say instead.  A speaker who corrects themselves constantly
is either deeply precise (refusing to let an approximation stand)
or deeply uncertain (unable to commit to a first formulation).
The same ambiguity applies to prose: a legal document that says
"the party, or more precisely the counterparty, shall..." is being
careful; a novel that says "she loved him — or rather, she loved
the idea of him" is being literary.  Both correct; the motivations
could not be more different.

Self-correction is not a quality metric.  Academic philosophy often
scores high — every term defined, every claim hedged and then
sharpened.  Casual conversation scores high — "I saw it on
Tuesday — no, Wednesday."  Technical documentation scores moderate
— "connect to port 443 (or port 8443 if using the alternate
configuration)."  Fiction that never corrects itself feels either
confident or careless; fiction that corrects constantly feels
either precise or neurotic.

This module measures **how frequently, how diversely, and through
what mechanisms a text corrects, revises, retracts, or
reformulates its own statements** — explicit correction markers,
reformulation phrases, retraction expressions, precision
escalators, scope narrowing devices, and metalinguistic
commentary.

Orthogonality to other metrics
-------------------------------

- **hedging_density** tracks softening and cautious language —
  "perhaps", "it seems", "may", "tends to".  Hedging avoids
  commitment before a claim is made; self-correction revises
  a claim after it has been made.  A hedged sentence never
  quite asserts; a self-corrected sentence asserts, then
  amends.  Hedging is preemptive caution; self-correction is
  reactive precision.

- **revision_depth** tracks how deeply files are revised across
  strokes — inter-session editing behavior.  Self-correction
  is intra-textual: the correction happens within a single
  utterance, not across editing sessions.  Revision depth
  measures behavior over time; self-correction measures
  behavior within a single pass.

- **precision** tracks how specific and exact the language is
  overall.  A precise text may never need to correct itself
  because it gets things right the first time.  A precise text
  may also correct itself constantly because the writer demands
  ever-greater exactness.  Precision measures the destination;
  self-correction measures the journey.

- **conviction** tracks commitment to stated positions.  Self-
  correction can undermine conviction (constant backtracking
  suggests uncertainty) or demonstrate it (relentless
  refinement suggests the writer cares deeply about getting
  it exactly right).  Conviction measures stance; self-
  correction measures process.

- **reflexivity** tracks writing that comments on itself as
  writing — "this essay argues", "the present discussion".
  Self-correction is one form of reflexivity, but reflexivity
  also includes self-reference without correction.  Reflexivity
  measures self-awareness; self-correction measures self-
  amendment.

Self-correction dimensions
--------------------------

============================  ================================================
metric                        meaning
============================  ================================================
explicit_correction_rate      or rather, I mean, that is, more precisely,
                              more accurately, to be exact, I should say,
                              let me rephrase (per 100 sentences)
reformulation_rate            in other words, to put it differently,
                              put another way, stated differently,
                              to rephrase, to put it another way,
                              what I mean is (per 100 sentences)
retraction_rate               scratch that, forget that, disregard,
                              ignore that, never mind, on second thought,
                              on reflection, actually no, cancel that,
                              take that back (per 100 sentences)
precision_escalation_rate     or more specifically, or to be exact,
                              strictly speaking, technically, more
                              narrowly, more broadly, in the strict
                              sense, in the precise sense (per 100 sentences)
scope_narrowing_rate          or at least, or at any rate, at minimum,
                              at the very least, if nothing else,
                              at a minimum, to say the least (per 100 sentences)
metalinguistic_rate           I misspoke, wrong word, poor choice,
                              let me put that better, badly phrased,
                              poor phrasing, to put it more carefully,
                              I should have said (per 100 sentences)
self_correction_diversity     vocabulary breadth across all correction
                              forms (0.0 – 1.0)
============================  ================================================

Classifications
---------------

====================  ============================================================
class                 meaning
====================  ============================================================
uncorrected           index < 0.03 — almost no self-correction; text commits
                      to its first formulations; either confident or careless
lightly_corrected     0.03 ≤ index < 0.10 — occasional corrections; normal
                      for edited prose where minor clarifications appear
moderately_corrected  0.10 ≤ index < 0.25 — regular self-amendment; typical
                      of careful academic or philosophical writing
heavily_corrected     0.25 ≤ index < 0.50 — frequent corrections; suggests
                      either extreme precision demands or deep uncertainty
correction_saturated  index ≥ 0.50 — text cannot settle on its own
                      formulations; every claim is revised before the
                      sentence ends
====================  ============================================================

written by Qwen during manual caretaker visit 637, 2026-11-15
"""

import re
from dataclasses import dataclass, field
from typing import Dict, Set


# ── Pattern dictionaries ────────────────────────────────────────

_EXPLICIT_CORRECTION = [
    "or rather",
    "i mean",
    "that is",
    "more precisely",
    "more accurately",
    "to be exact",
    "i should say",
    "let me rephrase",
    "let me correct",
    "to be more precise",
    "to be more accurate",
    "or better",
    "or more correctly",
    "i would say rather",
    "or perhaps more accurately",
]

_REFORMULATION = [
    "in other words",
    "to put it differently",
    "put another way",
    "stated differently",
    "to rephrase",
    "to put it another way",
    "what i mean is",
    "what i'm trying to say",
    "to say it differently",
    "expressed differently",
    "to frame it differently",
    "to put it more simply",
    "to put it bluntly",
    "to put it plainly",
    "simply put",
]

_RETRACTION = [
    "scratch that",
    "forget that",
    "disregard",
    "ignore that",
    "never mind",
    "on second thought",
    "on reflection",
    "actually no",
    "cancel that",
    "take that back",
    "i take that back",
    "i take it back",
    "strike that",
    "forget i said",
    "on second thoughts",
    "correction",
    "wait no",
    "actually not",
    "i was wrong",
    "i stand corrected",
]

_PRECISION_ESCALATION = [
    "or more specifically",
    "or to be exact",
    "strictly speaking",
    "technically",
    "more narrowly",
    "more broadly",
    "in the strict sense",
    "in the precise sense",
    "more exactly",
    "to be technically accurate",
    "in the strictest sense",
    "more rigorously",
    "in precise terms",
    "in technical terms",
    "speaking precisely",
]

_SCOPE_NARROWING = [
    "or at least",
    "or at any rate",
    "at minimum",
    "at the very least",
    "if nothing else",
    "at a minimum",
    "to say the least",
    "at the least",
    "at bare minimum",
    "if anything",
    "at the very minimum",
    "or so it seems at least",
]

_METALINGUISTIC = [
    "i misspoke",
    "wrong word",
    "poor choice",
    "let me put that better",
    "badly phrased",
    "poor phrasing",
    "to put it more carefully",
    "i should have said",
    "i should have written",
    "that was poorly put",
    "awkward phrasing",
    "poorly worded",
    "i misspoke earlier",
    "choose a better word",
    "to put it less awkwardly",
]

_ALL_CORRECTION_TERMS: list = (
    _EXPLICIT_CORRECTION
    + _REFORMULATION
    + _RETRACTION
    + _PRECISION_ESCALATION
    + _SCOPE_NARROWING
    + _METALINGUISTIC
)

# Build a single compiled regex for all terms
def _build_pattern(terms: list) -> "re.Pattern":
    """Build a word-boundary-aware pattern from a list of phrases."""
    # Use \b word boundaries so "correction" doesn't match "corrections"
    parts = [r"\b" + re.escape(t) + r"\b" for t in terms]
    return re.compile("|".join(parts), re.IGNORECASE)


_ALL_CORRECTION_PATTERN = _build_pattern(_ALL_CORRECTION_TERMS)

# Individual compiled patterns for each category
_PATTERNS = {
    "explicit_correction": _build_pattern(_EXPLICIT_CORRECTION),
    "reformulation": _build_pattern(_REFORMULATION),
    "retraction": _build_pattern(_RETRACTION),
    "precision_escalation": _build_pattern(_PRECISION_ESCALATION),
    "scope_narrowing": _build_pattern(_SCOPE_NARROWING),
    "metalinguistic": _build_pattern(_METALINGUISTIC),
}


# ── Result dataclass ────────────────────────────────────────────


@dataclass
class SelfCorrectionResult:
    """Results from measuring self-correction density in a text."""

    # Counts
    explicit_correction_count: int = 0
    reformulation_count: int = 0
    retraction_count: int = 0
    precision_escalation_count: int = 0
    scope_narrowing_count: int = 0
    metalinguistic_count: int = 0
    unique_correction_forms: int = 0

    # Rates per 100 sentences
    explicit_correction_rate: float = 0.0
    reformulation_rate: float = 0.0
    retraction_rate: float = 0.0
    precision_escalation_rate: float = 0.0
    scope_narrowing_rate: float = 0.0
    metalinguistic_rate: float = 0.0

    # Diversity
    self_correction_diversity: float = 0.0

    # Composite
    self_correction_index: float = 0.0

    # Classification
    classification: str = "uncorrected"

    # Metadata
    total_sentences: int = 0
    details: Dict = field(default_factory=dict)


# ── Helpers ─────────────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    """Estimate the number of sentences in text."""
    if not text or not text.strip():
        return 0
    # Split on sentence-ending punctuation followed by space or end
    sentences = re.split(r"[.!?]+(?:\s|$)", text.strip())
    # Filter empty strings
    return len([s for s in sentences if s.strip()])


def _count_matches(pattern: "re.Pattern", text: str) -> int:
    """Count non-overlapping matches of pattern in text."""
    return len(pattern.findall(text))


def _find_unique_matches(pattern: "re.Pattern", text: str) -> Set[str]:
    """Return unique matched forms (lowercased, stripped)."""
    return {m.lower().strip() for m in pattern.findall(text)}


# ── Main measurement function ──────────────────────────────────


def measure_self_correction(text: str) -> SelfCorrectionResult:
    """Measure the density and diversity of self-correction language in text.

    Parameters
    ----------
    text : str
        The text to analyze.

    Returns
    -------
    SelfCorrectionResult
        Dataclass with counts, rates, composite index, and classification.
    """
    result = SelfCorrectionResult()

    if not text or not text.strip():
        result.classification = "uncorrected"
        result.details = {
            "explicit_correction_rate": 0.0,
            "reformulation_rate": 0.0,
            "retraction_rate": 0.0,
            "precision_escalation_rate": 0.0,
            "scope_narrowing_rate": 0.0,
            "metalinguistic_rate": 0.0,
            "self_correction_diversity": 0.0,
            "self_correction_index": 0.0,
            "classification": "uncorrected",
        }
        return result

    sentence_count = _count_sentences(text)
    result.total_sentences = sentence_count
    scale = 100.0 / max(sentence_count, 1)

    # ── Count each category ─────────────────────────────────
    explicit = _count_matches(_PATTERNS["explicit_correction"], text)
    reform = _count_matches(_PATTERNS["reformulation"], text)
    retract = _count_matches(_PATTERNS["retraction"], text)
    precision = _count_matches(_PATTERNS["precision_escalation"], text)
    scope = _count_matches(_PATTERNS["scope_narrowing"], text)
    meta = _count_matches(_PATTERNS["metalinguistic"], text)

    # Unique correction forms across all categories
    unique_forms = _find_unique_matches(_ALL_CORRECTION_PATTERN, text)

    # Store counts
    result.explicit_correction_count = explicit
    result.reformulation_count = reform
    result.retraction_count = retract
    result.precision_escalation_count = precision
    result.scope_narrowing_count = scope
    result.metalinguistic_count = meta
    result.unique_correction_forms = len(unique_forms)

    # Rates per 100 sentences
    result.explicit_correction_rate = round(explicit * scale, 3)
    result.reformulation_rate = round(reform * scale, 3)
    result.retraction_rate = round(retract * scale, 3)
    result.precision_escalation_rate = round(precision * scale, 3)
    result.scope_narrowing_rate = round(scope * scale, 3)
    result.metalinguistic_rate = round(meta * scale, 3)

    # Diversity: ratio of unique forms to maximum possible (~80)
    max_possible_forms = 80
    result.self_correction_diversity = round(
        min(1.0, len(unique_forms) / max_possible_forms), 3
    )

    # ── Composite index (0.0 – 1.0) ────────────────────────
    # Normalize each rate to roughly 0–1 via soft caps
    cap_explicit = min(1.0, result.explicit_correction_rate / 15.0)
    cap_reform = min(1.0, result.reformulation_rate / 10.0)
    cap_retract = min(1.0, result.retraction_rate / 8.0)
    cap_precision = min(1.0, result.precision_escalation_rate / 10.0)
    cap_scope = min(1.0, result.scope_narrowing_rate / 8.0)
    cap_meta = min(1.0, result.metalinguistic_rate / 5.0)
    cap_diversity = result.self_correction_diversity

    composite = (
        0.22 * cap_explicit
        + 0.15 * cap_reform
        + 0.12 * cap_retract
        + 0.15 * cap_precision
        + 0.10 * cap_scope
        + 0.10 * cap_meta
        + 0.16 * cap_diversity
    )
    result.self_correction_index = round(min(1.0, composite), 4)

    # ── Classification ──────────────────────────────────────
    idx = result.self_correction_index
    if idx < 0.03:
        result.classification = "uncorrected"
    elif idx < 0.10:
        result.classification = "lightly_corrected"
    elif idx < 0.25:
        result.classification = "moderately_corrected"
    elif idx < 0.50:
        result.classification = "heavily_corrected"
    else:
        result.classification = "correction_saturated"

    result.details = {
        "explicit_correction_rate": result.explicit_correction_rate,
        "reformulation_rate": result.reformulation_rate,
        "retraction_rate": result.retraction_rate,
        "precision_escalation_rate": result.precision_escalation_rate,
        "scope_narrowing_rate": result.scope_narrowing_rate,
        "metalinguistic_rate": result.metalinguistic_rate,
        "self_correction_diversity": result.self_correction_diversity,
        "self_correction_index": result.self_correction_index,
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

    r = measure_self_correction(text)
    print(f"self_correction_index      : {r.self_correction_index:.4f}")
    print(f"classification             : {r.classification}")
    print(f"explicit_correction_rate   : {r.explicit_correction_rate}")
    print(f"reformulation_rate         : {r.reformulation_rate}")
    print(f"retraction_rate            : {r.retraction_rate}")
    print(f"precision_escalation_rate  : {r.precision_escalation_rate}")
    print(f"scope_narrowing_rate       : {r.scope_narrowing_rate}")
    print(f"metalinguistic_rate        : {r.metalinguistic_rate}")
    print(f"self_correction_diversity  : {r.self_correction_diversity}")
    print(f"total_sentences            : {r.total_sentences}")
