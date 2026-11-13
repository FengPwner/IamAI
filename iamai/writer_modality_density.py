#!/usr/bin/env python3
"""writer_modality_density — measure how much prose relies on modal verbs.

Modality is the grammar of possibility, obligation, permission,
ability, and willingness.  Every "must", "should", "could",
"might", "may", "would", "shall", "ought to", "have to",
"need to", "be able to" is a modal expression — a small
grammatical hedge between the writer and the raw assertion.

Modal verbs are among the most powerful tools in English prose.
They let a writer express degrees of certainty ("it might
rain"), social obligation ("you should apologize"), logical
necessity ("the answer must be zero"), ability ("she can
swim"), and willingness ("he would help if asked").  But
like any device, modality has a density at which it stops
serving precision and starts serving evasion — or reveals
a writer who cannot commit to a declarative sentence.

Modality density is not a quality metric.  Legal and
regulatory writing lives in deontic modality — "shall",
"must", "may not".  Philosophical argument thrives on
epistemic modality — "might", "could", "would follow
that".  Polite register relies on modal softening —
"could you", "would you mind".  But prose that cannot
state anything without first wrapping it in a modal
cushion may be avoiding the harder work of precision.

This module measures **how frequently, how diversely,
and in what distribution a text uses modal verbs** —
deontic (obligation/permission), epistemic (possibility/
certainty), dynamic (ability/willingness), their overlap
with negation, their clustering, and the writer's modal
vocabulary breadth.

Orthogonality to other metrics
-------------------------------

- **hedging_density** tracks hedging phrases broadly —
  "perhaps", "sort of", "it seems", "tends to".
  Modality is one hedging mechanism among many.
  Hedging density measures all softening devices;
  modality density measures the modal verb subsystem
  specifically.

- **conviction** tracks how assertively a text states
  its claims — presence of boosters, absence of hedges.
  A high-modality text may have low conviction (hedging
  via modals) or high conviction (deontic insistence —
  "you MUST understand").  Conviction measures rhetorical
  stance; modality density measures grammatical mechanism.

- **imperative_density** tracks commands and directives.
  Deontic modals often appear in directives ("you must
  do this"), but imperatives can be bare ("do this")
  and deontic modals appear outside directives ("she
  must be tired — epistemic").  Imperative density
  measures directive force; modality density measures
  modal verb frequency.

- **negation_density** tracks all negation.  Modals
  interact with negation ("must not", "cannot",
  "should not"), but negation exists independently
  of modality ("no", "never", "not at all").
  Negation density measures denial; modality density
  measures modal qualification.

- **qualifier_density** tracks qualifying phrases that
  limit scope ("in some cases", "for the most part").
  Modals are one form of qualification.  Qualifier
  density measures all scope-limiting devices;
  modality density measures the modal verb channel.

Modality density asks: **how much of the prose is
filtered through modal verbs, and what does the
distribution of deontic, epistemic, and dynamic modality
reveal about the writer's relationship to assertion?**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple, Set


# ── regex patterns ──────────────────────────────────────────────

# Core modal verbs (English).
# We match whole words, case-insensitive, with word boundaries.
# "will" excluded when part of a proper noun is hard to detect
# in plain regex; we accept a small false-positive rate.

# Deontic: obligation and permission
_DEONTIC_PATTERNS = [
    r"\bmust\b",
    r"\bshould\b",
    r"\bshall\b",
    r"\bought\s+to\b",
    r"\bhave\s+to\b",
    r"\bhas\s+to\b",
    r"\bhad\s+to\b",
    r"\bneed\s+to\b",
    r"\bneeds\s+to\b",
    r"\bneeded\s+to\b",
    r"\bsupposed\s+to\b",
    r"\brequired\s+to\b",
    r"\bpermitted\s+to\b",
    r"\ballowed\s+to\b",
    r"\bmay\s+not\b",
    r"\bmust\s+not\b",
    r"\bshould\s+not\b",
    r"\bshall\s+not\b",
]

# Epistemic: possibility and certainty
_EPISTEMIC_PATTERNS = [
    r"\bmight\b",
    r"\bmay\b",
    r"\bcould\b",
    r"\bcan\b",
    r"\bwill\b",
    r"\bwould\b",
    r"\bmust\s+be\b",       # epistemic "must" — deduction
    r"\bcannot\b",
    r"\bcan't\b",
    r"\bwon't\b",
    r"\bwouldn't\b",
    r"\bmight\s+not\b",
    r"\bcould\s+not\b",
]

# Dynamic: ability and willingness
_DYNAMIC_PATTERNS = [
    r"\bcan\b",
    r"\bcould\b",
    r"\bwill\b",
    r"\bwould\b",
    r"\bable\s+to\b",
    r"\bcapable\s+of\b",
    r"\bwilling\s+to\b",
    r"\bmanaged\s+to\b",
    r"\bsucceeded\s+in\b",
    r"\battempted\s+to\b",
]

# Hedging modals — subset used for softening
_HEDGING_MODAL_PATTERNS = [
    r"\bmight\b",
    r"\bcould\b",
    r"\bmay\b",
    r"\bwould\b",
    r"\bcan\b",
]

# Conditional context — modal inside if/unless/when-clauses
# or in the apodosis of a conditional
_CONDITIONAL_MODAL_PATTERN = re.compile(
    r"\b(?:if|unless|when|whenever|provided\s+that|in\s+case)\b"
    r"[^.!?]{0,80}?"
    r"\b(?:would|could|might|may|can|will|shall|should|must)\b",
    re.IGNORECASE,
)

# Negated modal — modal immediately (or closely) followed/preceded by negation
_NEGATED_MODAL_PATTERN = re.compile(
    r"\b(?:must|should|shall|would|could|might|may|can|will)\s+not\b"
    r"|\b(?:cannot|can't|won't|wouldn't|shouldn't|couldn't|mustn't|shan't|mightn't)\b",
    re.IGNORECASE,
)

# Compile all patterns
_deontic_compiled = [re.compile(p, re.IGNORECASE) for p in _DEONTIC_PATTERNS]
_epistemic_compiled = [re.compile(p, re.IGNORECASE) for p in _EPISTEMIC_PATTERNS]
_dynamic_compiled = [re.compile(p, re.IGNORECASE) for p in _DYNAMIC_PATTERNS]
_hedging_modal_compiled = [re.compile(p, re.IGNORECASE) for p in _HEDGING_MODAL_PATTERNS]

# All unique modal verb forms for diversity counting
_ALL_MODAL_VERBS = re.compile(
    r"\b(?:must|should|shall|ought|may|might|can|could|will|would"
    r"|need|have to|has to|had to|able to|capable of|willing to"
    r"|cannot|can't|won't|wouldn't|shouldn't|couldn't|mustn't"
    r"|shan't|mightn't)\b",
    re.IGNORECASE,
)


# ── dataclass ───────────────────────────────────────────────────

@dataclass
class ModalityDensityResult:
    """Full output of the modality density analysis."""

    deontic_modality_rate: float = 0.0
    epistemic_modality_rate: float = 0.0
    dynamic_modality_rate: float = 0.0
    hedging_modal_rate: float = 0.0
    conditional_modal_rate: float = 0.0
    negated_modal_rate: float = 0.0
    modal_diversity_index: float = 0.0

    modality_density_index: float = 0.0
    classification: str = "declarative"

    deontic_count: int = 0
    epistemic_count: int = 0
    dynamic_count: int = 0
    hedging_modal_count: int = 0
    conditional_modal_count: int = 0
    negated_modal_count: int = 0
    unique_modal_forms: int = 0
    total_sentences: int = 0

    details: dict = field(default_factory=dict)


# ── helpers ─────────────────────────────────────────────────────

def _count_sentences(text: str) -> int:
    """Count sentences using simple punctuation heuristic."""
    sents = re.split(r"[.!?]+", text)
    return max(1, len([s for s in sents if s.strip()]))


def _count_matches(patterns: list, text: str) -> int:
    """Count total non-overlapping matches across all patterns."""
    total = 0
    for pat in patterns:
        total += len(pat.findall(text))
    return total


# ── main function ───────────────────────────────────────────────

def measure_modality_density(text: str) -> ModalityDensityResult:
    """Analyse a text for modal verb density and distribution.

    Parameters
    ----------
    text : str
        The text to analyse.

    Returns
    -------
    ModalityDensityResult
        Rates per 100 sentences, raw counts, composite index,
        and classification.
    """
    result = ModalityDensityResult()

    if not text or not text.strip():
        result.classification = "declarative"
        return result

    total_sentences = _count_sentences(text)
    result.total_sentences = total_sentences
    scale = 100.0 / max(1, total_sentences)

    # ── Count each modality category ────────────────────────

    deontic = _count_matches(_deontic_compiled, text)
    epistemic = _count_matches(_epistemic_compiled, text)
    dynamic = _count_matches(_dynamic_compiled, text)
    hedging_modals = _count_matches(_hedging_modal_compiled, text)

    # Conditional modals
    conditional_modals = len(_CONDITIONAL_MODAL_PATTERN.findall(text))

    # Negated modals
    negated_modals = len(_NEGATED_MODAL_PATTERN.findall(text))

    # Modal diversity — unique forms
    all_forms = _ALL_MODAL_VERBS.findall(text)
    unique_forms: Set[str] = {f.lower() for f in all_forms}

    # Store counts
    result.deontic_count = deontic
    result.epistemic_count = epistemic
    result.dynamic_count = dynamic
    result.hedging_modal_count = hedging_modals
    result.conditional_modal_count = conditional_modals
    result.negated_modal_count = negated_modals
    result.unique_modal_forms = len(unique_forms)

    # Rates per 100 sentences
    result.deontic_modality_rate = round(deontic * scale, 3)
    result.epistemic_modality_rate = round(epistemic * scale, 3)
    result.dynamic_modality_rate = round(dynamic * scale, 3)
    result.hedging_modal_rate = round(hedging_modals * scale, 3)
    result.conditional_modal_rate = round(conditional_modals * scale, 3)
    result.negated_modal_rate = round(negated_modals * scale, 3)

    # Diversity: ratio of unique forms to maximum possible (~22)
    max_possible_forms = 22
    result.modal_diversity_index = round(
        min(1.0, len(unique_forms) / max_possible_forms), 3
    )

    # ── Composite index (0.0 – 1.0) ────────────────────────
    # Normalize each rate to roughly 0–1 via soft caps
    cap_deontic = min(1.0, result.deontic_modality_rate / 15.0)
    cap_epistemic = min(1.0, result.epistemic_modality_rate / 20.0)
    cap_dynamic = min(1.0, result.dynamic_modality_rate / 15.0)
    cap_hedging = min(1.0, result.hedging_modal_rate / 12.0)
    cap_conditional = min(1.0, result.conditional_modal_rate / 5.0)
    cap_negated = min(1.0, result.negated_modal_rate / 5.0)
    cap_diversity = result.modal_diversity_index

    composite = (
        0.20 * cap_deontic
        + 0.20 * cap_epistemic
        + 0.15 * cap_dynamic
        + 0.15 * cap_hedging
        + 0.10 * cap_conditional
        + 0.10 * cap_negated
        + 0.10 * cap_diversity
    )
    result.modality_density_index = round(min(1.0, composite), 4)

    # ── Classification ──────────────────────────────────────
    idx = result.modality_density_index
    if idx < 0.05:
        result.classification = "declarative"
    elif idx < 0.15:
        result.classification = "lightly_modal"
    elif idx < 0.35:
        result.classification = "moderately_modal"
    elif idx < 0.60:
        result.classification = "heavily_modal"
    else:
        result.classification = "modal_saturated"

    result.details = {
        "deontic_modality_rate": result.deontic_modality_rate,
        "epistemic_modality_rate": result.epistemic_modality_rate,
        "dynamic_modality_rate": result.dynamic_modality_rate,
        "hedging_modal_rate": result.hedging_modal_rate,
        "conditional_modal_rate": result.conditional_modal_rate,
        "negated_modal_rate": result.negated_modal_rate,
        "modal_diversity_index": result.modal_diversity_index,
        "modality_density_index": result.modality_density_index,
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

    r = measure_modality_density(text)
    print(f"modality_density_index   : {r.modality_density_index:.4f}")
    print(f"classification           : {r.classification}")
    print(f"deontic_modality_rate    : {r.deontic_modality_rate}")
    print(f"epistemic_modality_rate  : {r.epistemic_modality_rate}")
    print(f"dynamic_modality_rate    : {r.dynamic_modality_rate}")
    print(f"hedging_modal_rate       : {r.hedging_modal_rate}")
    print(f"conditional_modal_rate   : {r.conditional_modal_rate}")
    print(f"negated_modal_rate       : {r.negated_modal_rate}")
    print(f"modal_diversity_index    : {r.modal_diversity_index}")
    print(f"total_sentences          : {r.total_sentences}")
