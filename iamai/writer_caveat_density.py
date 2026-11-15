#!/usr/bin/env python3
"""writer_caveat_density — measure how much prose builds defensive scaffolding.

Every claim carries an implicit boundary.  "This approach works" is a
bold assertion; "this approach works, *provided* the dataset is
balanced" draws a fence around it.  Caveats are the writer's way of
saying: here is where my claim stops being true, here is where you
should stop trusting me, here is the escape hatch I built in case
reality turns out differently.

Caveat language is the prose of intellectual self-defense.  Where
emphasis directs attention ("look here!"), caveats manage
expectations ("but don't expect too much").  Where hedging signals
uncertainty about whether a claim is true ("it might be the case"),
caveats specify the conditions under which a claim is *not* true
("except when the input is empty").  The hedge says "I'm not sure";
the caveat says "I'm sure, but only within these bounds."

Caveats operate through several distinct channels.  **Adversative
conjunctions** introduce contrasting information that limits the
preceding claim: "however", "although", "nevertheless", "yet",
"on the other hand".  **Scope limiters** explicitly restrict the
domain of applicability: "in some cases", "under certain conditions",
"for the most part", "to a certain extent".  **Preemptive
concessions** acknowledge counterarguments before they can be
raised: "admittedly", "granted", "to be fair", "of course", "while
it is true that".  **Exception markers** carve out specific cases
where a claim does not apply: "except for", "with the exception of",
"apart from", "unless".  **Provisional language** marks claims as
dependent on unstated assumptions: "in principle", "theoretically",
"on paper", "ideally", "all else being equal".  **Qualification
adverbs** soften the universality of assertions: "generally",
"typically", "largely", "predominantly", "for the most part".

A text's caveat density reveals the writer's relationship to their
own claims.  Academic prose is dense with caveats — every finding
comes with limitations, every generalization with exceptions.  Legal
writing drowns in caveats — the fine print is entirely built from
"provided that", "subject to", "notwithstanding".  Technical
documentation sprinkles caveats at decision points — "unless the
connection times out", "assuming default configuration".  Marketing
copy avoids caveats entirely — everything works, always, no
conditions.  Journalism places caveats in attribution — "according
to sources", "reportedly", "allegedly".  Casual writing rarely
caveats — opinions are stated without qualification.

This module measures **how frequently, how diversely, and through
what channels a text builds defensive scaffolding** — adversative
qualification, scope limitation, preemptive concession, exception
carving, provisional framing, and assertion softening.

Orthogonality to other metrics
-------------------------------

- **hedging_density** tracks uncertainty and caution in claims —
  "perhaps", "might", "could", "it seems".  Hedging modulates
  commitment to truth; caveat modulates the *scope* of truth.
  "This might work" hedges; "this works, except on Tuesdays"
  caveats.  Hedging says "I'm not sure it's true"; caveat says
  "it's true, but only here".  Hedging is epistemic caution;
  caveat is territorial limitation.

- **conviction** tracks assertiveness — "this is correct" vs
  "this might be correct".  Conviction measures the strength of
  the claim; caveat measures the boundary of the claim.  A
  convicted statement can carry a caveat ("I am certain this
  works, provided the input is valid").  A low-conviction
  statement may have no caveat ("I think this might work").
  Conviction is volume; caveat is fence.

- **emphasis_density** tracks attention-direction — spotlighting
  certain elements as worthy of extra focus.  Emphasis says
  "look here"; caveat says "but not too closely".  Emphasis
  foregrounds; caveat backgrounds.  A sentence can be both
  emphasized and caveated ("the **critical** caveat is that..."),
  but the two serve opposite functions: emphasis amplifies,
  caveat constrains.

- **self_correction** tracks mid-stream revision — "or rather",
  "I mean", "more precisely".  Self-correction revises a claim
  after making it; caveat limits a claim while (or before) making
  it.  Self-correction is retrospective; caveat is prospective.
  Self-correction says "I said it wrong"; caveat says "I said it,
  but with conditions".

- **gradation_density** tracks degree calibration — comparatives,
  superlatives, intensifiers.  "More important than" calibrates
  degree; "important, at least for now" calibrates scope.
  Gradation answers "how much"; caveat answers "where" and "when".

- **pleonasm_density** tracks redundancy — saying the same thing
  twice in different words.  Caveats can be redundant ("however,
  on the other hand"), but redundancy measures repetition while
  caveat measures defensive qualification.  Pleonasm pads;
  caveat fences.

- **formality** tracks register — formal vs informal language.
  Caveat language tends formal ("notwithstanding", "provided that")
  but formality measures register while caveat measures defensive
  posture.  A formal text may be caveat-free; casual writing can
  be heavily caveated ("well, sort of, I guess, unless not").

Caveat density asks: **how much of the prose is built on defensive
scaffolding, and what does the distribution of adversative,
scope-limiting, concessive, exceptional, provisional, and
qualifying language reveal about the writer's relationship to
their own claims?**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Set


# ── regex patterns ──────────────────────────────────────────────

# Sentence splitter (approximate)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# ── adversative conjunctions ────────────────────────────────────
# Words that introduce contrasting or limiting information
_ADVERSATIVE = re.compile(
    r"\b(?:"
    r"however|"
    r"although|"
    r"though\b(?!\s+that)|"
    r"nevertheless|"
    r"nonetheless|"
    r"notwithstanding|"
    r"conversely|"
    r"on\s+the\s+other\s+hand|"
    r"then\s+again|"
    r"that\s+said|"
    r"having\s+said\s+that|"
    r"be\s+that\s+as\s+it\s+may|"
    r"at\s+the\s+same\s+time|"
    r"by\s+contrast|"
    r"in\s+contrast|"
    r"yet\b|"
    r"still\b(?=[\s,])|"
    r"whereas|"
    r"while\b(?=\s+\w+\s+\w+)|"
    r"albeit"
    r")\b",
    re.IGNORECASE,
)

# ── scope limiters ──────────────────────────────────────────────
# Phrases that explicitly restrict the domain of a claim
_SCOPE_LIMITER = re.compile(
    r"\b(?:"
    r"in\s+some\s+(?:cases|instances|situations|contexts|scenarios)|"
    r"under\s+certain\s+(?:conditions|circumstances)|"
    r"in\s+certain\s+(?:cases|instances|situations|contexts)|"
    r"to\s+(?:a\s+)?(?:certain|some|limited|significant|large|small)\s+"
    r"(?:extent|degree)|"
    r"for\s+the\s+most\s+part|"
    r"in\s+most\s+(?:cases|instances|situations|contexts)|"
    r"as\s+a\s+(?:general\s+)?rule|"
    r"more\s+often\s+than\s+not|"
    r"in\s+practice|"
    r"in\s+reality|"
    r"at\s+least\s+(?:in|for|when|if|some)|"
    r"at\s+most|"
    r"within\s+(?:certain|some|reasonable|narrow|broad)\s+"
    r"(?:limits|bounds|boundaries|parameters|constraints)|"
    r"up\s+to\s+a\s+point|"
    r"in\s+the\s+majority\s+of\s+cases|"
    r"for\s+(?:the\s+)?most\s+part|"
    r"on\s+the\s+whole|"
    r"by\s+and\s+large|"
    r"in\s+broad\s+(?:terms|strokes|outline)|"
    r"generally\s+speaking|"
    r"strictly\s+speaking|"
    r"technically\s+speaking|"
    r"as\s+far\s+as\s+(?:\w+\s+){0,3}(?:goes|is\s+concerned)|"
    r"insofar\s+as"
    r")\b",
    re.IGNORECASE,
)

# ── preemptive concessions ──────────────────────────────────────
# Acknowledging counterarguments before they can be raised
_PREEMPTIVE_CONCESSION = re.compile(
    r"\b(?:"
    r"admittedly|"
    r"granted(?=[,\s])|"
    r"to\s+be\s+fair|"
    r"to\s+be\s+sure|"
    r"of\s+course|"
    r"(?:it\s+is\s+)?(?:true|fair)\s+(?:enough\s+)?that|"
    r"while\s+(?:it\s+is\s+)?(?:true|clear|evident|obvious|undeniable)\s+that|"
    r"(?:one\s+)?could\s+argue\s+that|"
    r"(?:one\s+)?might\s+(?:say|argue|object|counter)\s+that|"
    r"(?:some|others|critics?\s+)?(?:might|could|would)\s+(?:say|argue|object|counter|point\s+out)|"
    r"it\s+(?:is|was)\s+(?:worth|fair)\s+(?:noting|mentioning|pointing\s+out)\s+that|"
    r"(?:this|that)\s+is\s+(?:not|no)\s+(?:to\s+say|to\s+suggest|without\s+its\s+(?:own\s+)?(?:problems?|issues?|limitations?|drawbacks?))|"
    r"(?:to\s+be\s+clear|for\s+clarity|"
    r"to\s+avoid\s+(?:any\s+)?(?:confusion|misunderstanding|ambiguity))"
    r")\b",
    re.IGNORECASE,
)

# ── exception markers ───────────────────────────────────────────
# Carving out cases where a claim does not apply
_EXCEPTION_MARKER = re.compile(
    r"\b(?:"
    r"except\s+(?:for|when|where|in\s+cases?\s+(?:where|of)|that)|"
    r"with\s+the\s+(?:sole\s+)?exception\s+of|"
    r"apart\s+from|"
    r"aside\s+from|"
    r"barring|"
    r"unless\b|"
    r"save\s+for|"
    r"excluding|"
    r"not\s+counting|"
    r"but\s+for|"
    r"if\s+not\s+for|"
    r"outside\s+of|"
    r"(?:other|other\s+than)\s+than\b|"
    r"in\s+the\s+absence\s+of|"
    r"failing\s+that|"
    r"in\s+the\s+event\s+(?:of|that)"
    r")\b",
    re.IGNORECASE,
)

# ── provisional language ────────────────────────────────────────
# Marking claims as dependent on assumptions
_PROVISIONAL = re.compile(
    r"\b(?:"
    r"in\s+principle|"
    r"(?:in\s+)?theory|"
    r"theoretically|"
    r"on\s+paper|"
    r"ideally|"
    r"(?:all|other)\s+(?:things|else)\s+(?:being|remaining)\s+(?:equal|the\s+same)|"
    r"(?:ceteris\s+paribus)|"
    r"(?:assuming|given|presuming|supposing)\s+(?:that\s+)?|"
    r"conditional\s+on|"
    r"contingent\s+(?:on|upon)|"
    r"subject\s+to|"
    r"provided\s+that|"
    r"(?:only|just)\s+if|"
    r"(?:as|so)\s+long\s+as|"
    r"in\s+an\s+ideal\s+world|"
    r"(?:everything|all\s+things)\s+(?:being|remaining)\s+equal|"
    r"for\s+(?:all\s+)?intents\s+and\s+purposes"
    r")\b",
    re.IGNORECASE,
)

# ── qualification adverbs ───────────────────────────────────────
# Softening the universality of assertions
_QUALIFICATION_ADVERB = re.compile(
    r"\b(?:"
    r"generally|"
    r"typically|"
    r"usually|"
    r"normally|"
    r"ordinarily|"
    r"commonly|"
    r"predominantly|"
    r"largely|"
    r"mostly|"
    r"primarily|"
    r"principally|"
    r"chiefly|"
    r"mainly|"
    r"broadly|"
    r"roughly|"
    r"tends?\s+to|"
    r"arguably|"
    r"presumably|"
    r"ostensibly|"
    r"seemingly|"
    r"apparently|"
    r"conceivably"
    r")\b",
    re.IGNORECASE,
)

# ── unique caveat forms for diversity ───────────────────────────
_ALL_CAVEAT_LEXICAL = re.compile(
    r"\b(?:"
    r"however|although|though|nevertheless|nonetheless|"
    r"notwithstanding|conversely|whereas|albeit|"
    r"admittedly|granted|arguably|presumably|ostensibly|"
    r"seemingly|apparently|conceivably|"
    r"generally|typically|usually|normally|ordinarily|"
    r"commonly|predominantly|largely|mostly|primarily|"
    r"principally|chiefly|mainly|broadly|roughly|"
    r"theoretically|ideally|barring|unless|excluding|"
    r"provisional|conditional|contingent"
    r")\b",
    re.IGNORECASE,
)


# ── dataclass ───────────────────────────────────────────────────


@dataclass
class CaveatDensityResult:
    """Results of caveat density analysis."""

    # Raw counts
    adversative_count: int = 0
    scope_limiter_count: int = 0
    preemptive_concession_count: int = 0
    exception_marker_count: int = 0
    provisional_count: int = 0
    qualification_adverb_count: int = 0
    unique_caveat_forms: int = 0

    # Rates per 100 sentences
    adversative_rate: float = 0.0
    scope_limiter_rate: float = 0.0
    preemptive_concession_rate: float = 0.0
    exception_marker_rate: float = 0.0
    provisional_rate: float = 0.0
    qualification_adverb_rate: float = 0.0

    # Composite
    caveat_diversity_index: float = 0.0
    caveat_density_index: float = 0.0
    classification: str = "uncaveated"

    # Metadata
    total_sentences: int = 0
    details: dict = field(default_factory=dict)


# ── helpers ─────────────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    """Count sentences (approximate)."""
    stripped = text.strip()
    if not stripped:
        return 0
    sentences = [s for s in _SENTENCE_SPLIT.split(stripped) if s.strip()]
    return max(len(sentences), 1)


def _count_matches(pattern: re.Pattern, text: str) -> int:
    """Count non-overlapping regex matches."""
    return len(pattern.findall(text))


# ── main function ───────────────────────────────────────────────


def measure_caveat_density(text: str) -> CaveatDensityResult:
    """Analyze caveat and defensive-qualification density in text.

    Parameters
    ----------
    text : str
        The text to analyze.

    Returns
    -------
    CaveatDensityResult
        Analysis results with rates, composite index, and classification.
    """
    result = CaveatDensityResult()

    if not text or not text.strip():
        return result

    sentence_count = _count_sentences(text)
    result.total_sentences = sentence_count
    scale = 100.0 / max(sentence_count, 1)

    # ── Count each category ─────────────────────────────────
    adversative = _count_matches(_ADVERSATIVE, text)
    scope_limiter = _count_matches(_SCOPE_LIMITER, text)
    preemptive = _count_matches(_PREEMPTIVE_CONCESSION, text)
    exception = _count_matches(_EXCEPTION_MARKER, text)
    provisional = _count_matches(_PROVISIONAL, text)
    qualification = _count_matches(_QUALIFICATION_ADVERB, text)

    # Unique caveat forms for diversity
    all_forms = _ALL_CAVEAT_LEXICAL.findall(text)
    unique_forms: Set[str] = {f.lower().strip() for f in all_forms}

    # Store counts
    result.adversative_count = adversative
    result.scope_limiter_count = scope_limiter
    result.preemptive_concession_count = preemptive
    result.exception_marker_count = exception
    result.provisional_count = provisional
    result.qualification_adverb_count = qualification
    result.unique_caveat_forms = len(unique_forms)

    # Rates per 100 sentences
    result.adversative_rate = round(adversative * scale, 3)
    result.scope_limiter_rate = round(scope_limiter * scale, 3)
    result.preemptive_concession_rate = round(preemptive * scale, 3)
    result.exception_marker_rate = round(exception * scale, 3)
    result.provisional_rate = round(provisional * scale, 3)
    result.qualification_adverb_rate = round(qualification * scale, 3)

    # Diversity: ratio of unique forms to maximum possible (~30)
    max_possible_forms = 30
    result.caveat_diversity_index = round(
        min(1.0, len(unique_forms) / max_possible_forms), 3
    )

    # ── Composite index (0.0 – 1.0) ────────────────────────
    # Normalize each rate to roughly 0–1 via soft caps
    cap_adversative = min(1.0, result.adversative_rate / 15.0)
    cap_scope = min(1.0, result.scope_limiter_rate / 10.0)
    cap_preemptive = min(1.0, result.preemptive_concession_rate / 8.0)
    cap_exception = min(1.0, result.exception_marker_rate / 10.0)
    cap_provisional = min(1.0, result.provisional_rate / 8.0)
    cap_qualification = min(1.0, result.qualification_adverb_rate / 12.0)
    cap_diversity = result.caveat_diversity_index

    composite = (
        0.20 * cap_adversative
        + 0.12 * cap_scope
        + 0.12 * cap_preemptive
        + 0.12 * cap_exception
        + 0.12 * cap_provisional
        + 0.12 * cap_qualification
        + 0.20 * cap_diversity
    )
    result.caveat_density_index = round(min(1.0, composite), 4)

    # ── Classification ──────────────────────────────────────
    idx = result.caveat_density_index
    if idx < 0.05:
        result.classification = "uncaveated"
    elif idx < 0.15:
        result.classification = "lightly_caveated"
    elif idx < 0.35:
        result.classification = "moderately_caveated"
    elif idx < 0.60:
        result.classification = "heavily_caveated"
    else:
        result.classification = "caveat_saturated"

    result.details = {
        "adversative_rate": result.adversative_rate,
        "scope_limiter_rate": result.scope_limiter_rate,
        "preemptive_concession_rate": result.preemptive_concession_rate,
        "exception_marker_rate": result.exception_marker_rate,
        "provisional_rate": result.provisional_rate,
        "qualification_adverb_rate": result.qualification_adverb_rate,
        "caveat_diversity_index": result.caveat_diversity_index,
        "caveat_density_index": result.caveat_density_index,
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

    r = measure_caveat_density(text)
    print(f"caveat_density_index          : {r.caveat_density_index:.4f}")
    print(f"classification                : {r.classification}")
    print(f"adversative_rate              : {r.adversative_rate}")
    print(f"scope_limiter_rate            : {r.scope_limiter_rate}")
    print(f"preemptive_concession_rate    : {r.preemptive_concession_rate}")
    print(f"exception_marker_rate         : {r.exception_marker_rate}")
    print(f"provisional_rate              : {r.provisional_rate}")
    print(f"qualification_adverb_rate     : {r.qualification_adverb_rate}")
    print(f"caveat_diversity_index        : {r.caveat_diversity_index}")
    print(f"total_sentences               : {r.total_sentences}")
