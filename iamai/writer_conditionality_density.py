#!/usr/bin/env python3
"""writer_conditionality_density — measure how much prose relies on conditional structures.

Conditionality is the grammar of contingency — the linguistic
signal that a claim, action, or outcome depends on some prior
state of affairs.  Every "if", "unless", "provided that",
"in case", "suppose", "what if", "had X happened",
"were it not for" is a conditional construction — a small
architectural scaffold around an assertion that cannot
stand alone.

Conditional structures are among the most important devices
in English prose.  They let a writer reason about
possibilities ("if the temperature drops, the reaction
slows"), explore counterfactuals ("had the treaty been
signed, the war might have ended"), set boundaries
("unless you have a reservation, entry is denied"), and
construct hypothetical worlds ("suppose gravity were
twice as strong").  But like any device, conditionality
has a density at which it stops serving logical precision
and starts serving avoidance — or reveals a writer who
cannot assert anything without first wrapping it in a
hypothetical frame.

Conditionality density is not a quality metric.  Legal
drafting lives in conditional logic — "if the tenant
fails to pay, the landlord may terminate".  Scientific
methodology thrives on conditional framing — "if the
null hypothesis is rejected, the alternative gains
support".  Philosophical thought experiments are built
entirely on conditional scaffolding — "suppose you were
connected to a violinist".  But prose that cannot state
a fact without first conditioning it may be avoiding the
harder work of commitment.

This module measures **how frequently, how diversely,
and in what distribution a text uses conditional
structures** — explicit if/then constructions, subjunctive
and counterfactual forms, hypothetical markers, contingent
consequence markers, and the variety of conditional
constructions.

Orthogonality to other metrics
-------------------------------

- **modality_density** tracks modal verbs — must, should,
  could, might.  Modals frequently appear inside
  conditional clauses ("if you go, you should arrive
  early"), but modality operates independently of
  conditional framing ("you must leave" is deontic
  without any condition).  Modality density measures
  modal verb frequency; conditionality density measures
  conditional structure frequency.

- **hedging_density** tracks all softening devices —
  "perhaps", "sort of", "it seems".  Conditional framing
  can be a hedging strategy ("if I may say so"), but
  many conditionals are not hedges ("if water reaches
  100°C, it boils").  Hedging density measures softening;
  conditionality density measures contingent framing.

- **interrogative_density** tracks questions.  "What if"
  questions overlap with hypothetical conditionals, but
  most questions are not conditional ("what time is it?")
  and most conditionals are not questions.  Interrogative
  density measures questioning; conditionality density
  measures contingent reasoning.

- **causal_density** tracks cause-and-effect language —
  "because", "therefore", "as a result".  Conditionals
  and causals are related but distinct: "if A, then B"
  is conditional; "A, therefore B" is causal.  A text
  can be heavily causal without any conditionals, or
  heavily conditional without explicit causal markers.
  Causal density measures stated causation; conditionality
  density measures contingent framing.

- **concession_density** tracks concessive clauses —
  "although", "even though", "despite".  Concessive
  conditionals ("even if") bridge both categories, but
  pure concessives ("although it rained, we went out")
  are not conditional.  Concession density measures
  acknowledgment of counter-evidence; conditionality
  density measures contingent dependency.

Conditionality density asks: **how much of the prose is
built on conditional scaffolding, and what does the
distribution of real, hypothetical, and counterfactual
conditions reveal about the writer's relationship to
assertion?**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set


# ── regex patterns ──────────────────────────────────────────────

# Explicit conditional markers: if/then, unless, provided that, etc.
_EXPLICIT_CONDITIONAL_PATTERNS = [
    r"\bif\b[^.!?]{1,60}\bthen\b",          # if … then
    r"\bif\b",                                # bare if
    r"\bunless\b",                            # unless
    r"\bprovided\s+(?:that\s+)?",            # provided (that)
    r"\bproviding\s+(?:that\s+)?",           # providing (that)
    r"\bin\s+case\b",                         # in case
    r"\bin\s+the\s+event\s+that\b",          # in the event that
    r"\bon\s+condition\s+that\b",            # on condition that
    r"\bas\s+long\s+as\b",                   # as long as
    r"\bso\s+long\s+as\b",                   # so long as
    r"\bwhether\s+or\s+not\b",               # whether or not
    r"\bif\s+only\b",                         # if only
    r"\bif\s+need\s+be\b",                   # if need be
]

# Subjunctive and counterfactual markers
_SUBJUNCTIVE_PATTERNS = [
    r"\bwere\s+(?:it|I|he|she|they|we|you)\b",    # were it, were I
    r"\b(?:if|as\s+if|as\s+though)\s+[^.!?]{0,30}?\bwere\b",  # if ... were
    r"\bhad\s+(?:it|I|he|she|they|we|you)\s+\w+ed\b",  # had it happened
    r"\bhad\s+it\s+not\s+been\b",               # had it not been
    r"\bwere\s+it\s+not\s+for\b",               # were it not for
    r"\bshould\s+you\s+(?:wish|need|want|desire|choose)\b",  # should you wish
]

# Hypothetical scenario markers
_HYPOTHETICAL_PATTERNS = [
    r"\bsuppose\b",
    r"\bimagine\b",
    r"\b(?:let'?s?\s+)?(?:assume|presume)\b",
    r"\bwhat\s+if\b",
    r"\b(?:let'?s?\s+say)\b",
    r"\bfor\s+the\s+sake\s+of\s+argument\b",
    r"\bin\s+a\s+(?:hypothetical|imaginary)\b",
    r"\bpretend\b",
    r"\benvisage\b",
    r"\benvision\b",
    r"\bconceive\s+of\b",
    r"\bpostulate\b",
]

# Concessive conditional — "even if", "even though … might", etc.
_CONCESSIVE_CONDITIONAL_PATTERNS = [
    r"\beven\s+if\b",
    r"\beven\s+though\b[^.!?]{0,40}?(?:would|could|might|may)\b",
    r"\balthough\b[^.!?]{0,40}?(?:would|could|might|may)\b",
    r"\bno\s+matter\s+(?:what|how|when|where|who|which)\b",
    r"\bwhatever\s+(?:happens|may)\b",
    r"\bcome\s+what\s+may\b",
]

# Contingent consequence markers — words that signal the apodosis
_CONSEQUENCE_PATTERNS = [
    r"\bthen\b",
    r"\botherwise\b",
    r"\bor\s+else\b",
    r"\belse\b",
    r"\bin\s+that\s+case\b",
    r"\bunder\s+those\s+circumstances\b",
    r"\bconsequently\b",
    r"\bas\s+a\s+consequence\b",
    r"\baccordingly\b",
    r"\bthereupon\b",
]

# Counterfactual — past perfect in protasis + would/could/might + perfect
_COUNTERFACTUAL_PATTERN = re.compile(
    r"\b(?:if|had)\b[^.!?]{0,50}?"
    r"\b(?:had\s+\w+ed|had\s+been)\b[^.!?]{0,50}?"
    r"\b(?:would|could|might)\s+have\b",
    re.IGNORECASE,
)

# Also catch inverted counterfactuals: "Had I known, I would have…"
_INVERTED_COUNTERFACTUAL = re.compile(
    r"\bHad\b\s+(?:I|he|she|they|we|you|it)\s+\w+ed?"
    r"[^.!?]{0,60}?"
    r"\b(?:would|could|might)\s+have\b",
    re.IGNORECASE,
)

# Compile pattern lists
_explicit_compiled = [re.compile(p, re.IGNORECASE) for p in _EXPLICIT_CONDITIONAL_PATTERNS]
_subjunctive_compiled = [re.compile(p, re.IGNORECASE) for p in _SUBJUNCTIVE_PATTERNS]
_hypothetical_compiled = [re.compile(p, re.IGNORECASE) for p in _HYPOTHETICAL_PATTERNS]
_concessive_conditional_compiled = [re.compile(p, re.IGNORECASE) for p in _CONCESSIVE_CONDITIONAL_PATTERNS]
_consequence_compiled = [re.compile(p, re.IGNORECASE) for p in _CONSEQUENCE_PATTERNS]

# All conditional construction markers for diversity counting
_ALL_CONDITIONAL_MARKERS = re.compile(
    r"\b(?:if|unless|provided|providing|suppose|imagine|assume"
    r"|what if|otherwise|then|whether|lest"
    r"|in case|as long as|so long as"
    r"|even if|no matter|whatever|come what may"
    r"|envisage|envision|postulate|conceive"
    r"|pretend|presume)\b",
    re.IGNORECASE,
)


# ── dataclass ───────────────────────────────────────────────────

@dataclass
class ConditionalityDensityResult:
    """Full output of the conditionality density analysis."""

    explicit_conditional_rate: float = 0.0
    subjunctive_rate: float = 0.0
    hypothetical_marker_rate: float = 0.0
    concessive_conditional_rate: float = 0.0
    contingent_consequence_rate: float = 0.0
    counterfactual_rate: float = 0.0
    conditional_diversity_index: float = 0.0

    conditionality_density_index: float = 0.0
    classification: str = "unconditional"

    explicit_conditional_count: int = 0
    subjunctive_count: int = 0
    hypothetical_marker_count: int = 0
    concessive_conditional_count: int = 0
    contingent_consequence_count: int = 0
    counterfactual_count: int = 0
    unique_conditional_forms: int = 0
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

def measure_conditionality_density(text: str) -> ConditionalityDensityResult:
    """Analyse a text for conditional structure density and distribution.

    Parameters
    ----------
    text : str
        The text to analyse.

    Returns
    -------
    ConditionalityDensityResult
        Rates per 100 sentences, raw counts, composite index,
        and classification.
    """
    result = ConditionalityDensityResult()

    if not text or not text.strip():
        result.classification = "unconditional"
        return result

    total_sentences = _count_sentences(text)
    result.total_sentences = total_sentences
    scale = 100.0 / max(1, total_sentences)

    # ── Count each conditionality category ──────────────────

    explicit = _count_matches(_explicit_compiled, text)
    subjunctive = _count_matches(_subjunctive_compiled, text)
    hypothetical = _count_matches(_hypothetical_compiled, text)
    concessive_conditional = _count_matches(_concessive_conditional_compiled, text)
    consequence = _count_matches(_consequence_compiled, text)

    # Counterfactual (regex-based, two patterns)
    counterfactual = (
        len(_COUNTERFACTUAL_PATTERN.findall(text))
        + len(_INVERTED_COUNTERFACTUAL.findall(text))
    )

    # Conditional diversity — unique forms
    all_forms = _ALL_CONDITIONAL_MARKERS.findall(text)
    unique_forms: Set[str] = {f.lower() for f in all_forms}

    # Store counts
    result.explicit_conditional_count = explicit
    result.subjunctive_count = subjunctive
    result.hypothetical_marker_count = hypothetical
    result.concessive_conditional_count = concessive_conditional
    result.contingent_consequence_count = consequence
    result.counterfactual_count = counterfactual
    result.unique_conditional_forms = len(unique_forms)

    # Rates per 100 sentences
    result.explicit_conditional_rate = round(explicit * scale, 3)
    result.subjunctive_rate = round(subjunctive * scale, 3)
    result.hypothetical_marker_rate = round(hypothetical * scale, 3)
    result.concessive_conditional_rate = round(concessive_conditional * scale, 3)
    result.contingent_consequence_rate = round(consequence * scale, 3)
    result.counterfactual_rate = round(counterfactual * scale, 3)

    # Diversity: ratio of unique forms to maximum possible (~18)
    max_possible_forms = 18
    result.conditional_diversity_index = round(
        min(1.0, len(unique_forms) / max_possible_forms), 3
    )

    # ── Composite index (0.0 – 1.0) ────────────────────────
    # Normalize each rate to roughly 0–1 via soft caps
    cap_explicit = min(1.0, result.explicit_conditional_rate / 20.0)
    cap_subjunctive = min(1.0, result.subjunctive_rate / 8.0)
    cap_hypothetical = min(1.0, result.hypothetical_marker_rate / 10.0)
    cap_concessive = min(1.0, result.concessive_conditional_rate / 5.0)
    cap_consequence = min(1.0, result.contingent_consequence_rate / 12.0)
    cap_counterfactual = min(1.0, result.counterfactual_rate / 3.0)
    cap_diversity = result.conditional_diversity_index

    composite = (
        0.20 * cap_explicit
        + 0.20 * cap_subjunctive
        + 0.15 * cap_hypothetical
        + 0.10 * cap_concessive
        + 0.10 * cap_consequence
        + 0.15 * cap_counterfactual
        + 0.10 * cap_diversity
    )
    result.conditionality_density_index = round(min(1.0, composite), 4)

    # ── Classification ──────────────────────────────────────
    idx = result.conditionality_density_index
    if idx < 0.05:
        result.classification = "unconditional"
    elif idx < 0.15:
        result.classification = "lightly_conditional"
    elif idx < 0.35:
        result.classification = "moderately_conditional"
    elif idx < 0.60:
        result.classification = "heavily_conditional"
    else:
        result.classification = "condition_saturated"

    result.details = {
        "explicit_conditional_rate": result.explicit_conditional_rate,
        "subjunctive_rate": result.subjunctive_rate,
        "hypothetical_marker_rate": result.hypothetical_marker_rate,
        "concessive_conditional_rate": result.concessive_conditional_rate,
        "contingent_consequence_rate": result.contingent_consequence_rate,
        "counterfactual_rate": result.counterfactual_rate,
        "conditional_diversity_index": result.conditional_diversity_index,
        "conditionality_density_index": result.conditionality_density_index,
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

    r = measure_conditionality_density(text)
    print(f"conditionality_density_index : {r.conditionality_density_index:.4f}")
    print(f"classification               : {r.classification}")
    print(f"explicit_conditional_rate    : {r.explicit_conditional_rate}")
    print(f"subjunctive_rate             : {r.subjunctive_rate}")
    print(f"hypothetical_marker_rate     : {r.hypothetical_marker_rate}")
    print(f"concessive_conditional_rate  : {r.concessive_conditional_rate}")
    print(f"contingent_consequence_rate  : {r.contingent_consequence_rate}")
    print(f"counterfactual_rate          : {r.counterfactual_rate}")
    print(f"conditional_diversity_index  : {r.conditional_diversity_index}")
    print(f"total_sentences              : {r.total_sentences}")
