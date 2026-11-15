#!/usr/bin/env python3
"""writer_gradation_density — measure how much prose relies on degree language.

Every writer, consciously or not, constantly adjusts intensity.
"Very good."  "Somewhat unlikely."  "The most important factor."
"Less convincing than the original."  These gradations — the
comparative scaffolding that positions every quality on a scale —
are so embedded in English that we barely notice them.  But they
shape meaning profoundly: "good" and "very good" and "barely
adequate" describe the same territory with radically different
implications.

Gradation language serves distinct rhetorical functions.
Comparatives ("better", "more nuanced", "less frequent") position
one thing relative to another.  Superlatives ("best", "most
critical", "least expected") claim an extreme.  Intensifiers
("extremely", "remarkably", "deeply") amplify.  Diminishers
("slightly", "somewhat", "a bit") soften.  Equatives ("as
important as", "equally valid") establish parity.  Degree adverbs
("almost", "nearly", "practically") approach without reaching.
Together, they form a gradient apparatus that lets writers
calibrate every claim along a continuum rather than committing
to absolutes.

Gradation density is not a quality metric.  Academic writing
thrives on careful gradation — "this result is somewhat
consistent with prior findings, though considerably less robust
than initially hypothesized."  Advertising saturates in it —
"the most advanced, incredibly powerful, exceptionally refined
machine ever built."  Casual speech peppers it throughout —
"it's pretty good, maybe a little too expensive, but honestly
not the worst thing."  Legal prose avoids it deliberately —
"the party shall comply" admits no degree.  Fiction modulates
it for voice — Hemingway strips it bare; Woolf layers it thick.

This module measures **how frequently, how diversely, and through
what mechanisms a text uses gradation and degree language** —
comparative constructions, superlative constructions, intensifiers,
diminishers, equative constructions, approximative degree adverbs,
and sufficiency/excess markers.

Orthogonality to other metrics
-------------------------------

- **hedging_density** tracks cautious softening — "perhaps",
  "it seems", "may", "tends to".  Hedging avoids commitment
  to a claim; gradation modulates the intensity of a claim
  already made.  "Perhaps the best approach" is both hedged
  and gradated; "definitely the best approach" is gradated
  but not hedged.  Hedging is about certainty; gradation is
  about degree.

- **precision** tracks how specific and exact language is.
  Gradation can be precise ("3.7 times more frequent") or
  vague ("a lot more frequent").  Precision measures exactness;
  gradation measures degree-positioning regardless of exactness.

- **conviction** tracks the overall confidence and assertiveness
  of prose.  A convicted statement may use gradation ("this is
  absolutely the correct approach") or avoid it ("this is the
  correct approach").  Gradation can amplify or undermine
  conviction depending on direction.  Conviction measures
  commitment; gradation measures calibration.

- **qualifier_density** tracks restricting and limiting
  expressions — "only", "merely", "simply", "just".
  Qualifiers narrow scope; gradation adjusts intensity.
  "Only slightly better" is both qualified and gradated,
  but "far better" is gradated without being qualified.
  Qualifiers restrict; gradation scales.

- **contrast_density** tracks opposition and juxtaposition.
  Comparatives often appear in contrasts ("X is larger than Y"),
  but gradation also operates without contrast ("this is
  extremely important" makes no comparison).  Contrast measures
  opposition; gradation measures degree regardless of whether
  anything is being compared.

- **self_correction** tracks mid-stream revisions.
  "It was good — or rather, exceptional" corrects upward
  through gradation, but self-correction is the act of
  revision itself, not the degree language used within it.
  Self-correction measures the turn; gradation measures
  the scale.

Gradation density asks: **how much of the prose is built on
degree scaffolding, and what does the distribution of
comparative, superlative, intensifying, diminishing, and
approximative language reveal about the writer's relationship
to calibration and scale?**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set


# ── regex patterns ──────────────────────────────────────────────

# Sentence splitter (approximate)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# ── comparative constructions ───────────────────────────────────
# Includes both morphological (-er) and periphrastic (more/less) comparatives
_COMPARATIVE_CONSTRUCTIONS = re.compile(
    r"\b(?:"
    # periphrastic comparatives
    r"more\s+\w+|less\s+\w+|fewer\s+\w+|"
    r"more\s+than|less\s+than|fewer\s+than|"
    r"more\s+\w+\s+than|less\s+\w+\s+than|"
    # common irregular comparatives
    r"better(?:\s+than)?|worse(?:\s+than)?|"
    r"greater(?:\s+than)?|lesser(?:\s+than)?|"
    r"larger(?:\s+than)?|smaller(?:\s+than)?|"
    r"higher(?:\s+than)?|lower(?:\s+than)?|"
    r"longer(?:\s+than)?|shorter(?:\s+than)?|"
    r"wider(?:\s+than)?|narrower(?:\s+than)?|"
    r"deeper(?:\s+than)?|shallower(?:\s+than)?|"
    r"broader(?:\s+than)?|thinner(?:\s+than)?|"
    r"thicker(?:\s+than)?|heavier(?:\s+than)?|"
    r"lighter(?:\s+than)?|faster(?:\s+than)?|"
    r"slower(?:\s+than)?|harder(?:\s+than)?|"
    r"easier(?:\s+than)?|stronger(?:\s+than)?|"
    r"weaker(?:\s+than)?|richer(?:\s+than)?|"
    r"poorer(?:\s+than)?|older(?:\s+than)?|"
    r"younger(?:\s+than)?|newer(?:\s+than)?|"
    r"warmer(?:\s+than)?|cooler(?:\s+than)?|"
    r"hotter(?:\s+than)?|colder(?:\s+than)?|"
    r"brighter(?:\s+than)?|darker(?:\s+than)?|"
    r"louder(?:\s+than)?|quieter(?:\s+than)?|"
    r"clearer(?:\s+than)?|simpler(?:\s+than)?|"
    r"rather\s+than|"
    r"the\s+more\s+the\s+\w+|"
    r"the\s+\w+er\s+the\s+\w+er"
    r")\b",
    re.IGNORECASE,
)

# ── superlative constructions ───────────────────────────────────
_SUPERLATIVE_CONSTRUCTIONS = re.compile(
    r"\b(?:"
    # periphrastic superlatives
    r"the\s+most\s+\w+|"
    r"the\s+least\s+\w+|"
    r"the\s+fewest\s+\w+|"
    # common irregular superlatives
    r"the\s+best|the\s+worst|"
    r"the\s+greatest|the\s+least|"
    r"the\s+largest|the\s+smallest|"
    r"the\s+highest|the\s+lowest|"
    r"the\s+longest|the\s+shortest|"
    r"the\s+widest|the\s+narrowest|"
    r"the\s+deepest|the\s+shallowest|"
    r"the\s+broadest|the\s+thinnest|"
    r"the\s+thickest|the\s+heaviest|"
    r"the\s+lightest|the\s+fastest|"
    r"the\s+slowest|the\s+hardest|"
    r"the\s+easiest|the\s+strongest|"
    r"the\s+weakest|the\s+richest|"
    r"the\s+poorest|the\s+oldest|"
    r"the\s+youngest|the\s+newest|"
    r"the\s+warmest|the\s+coolest|"
    r"the\s+hottest|the\s+coldest|"
    r"the\s+brightest|the\s+darkest|"
    r"the\s+loudest|the\s+quietest|"
    r"the\s+clearest|the\s+simplest|"
    # intensifier superlatives
    r"absolutely\s+the\s+most|"
    r"by\s+far\s+the\s+most|"
    r"very\s+nearly\s+the|"
    r"among\s+the\s+most|"
    r"one\s+of\s+the\s+most"
    r")\b",
    re.IGNORECASE,
)

# ── intensifiers ────────────────────────────────────────────────
_INTENSIFIERS = re.compile(
    r"\b(?:"
    # strong intensifiers
    r"very|extremely|exceedingly|exceptionally|"
    r"extraordinarily|tremendously|immensely|"
    r"enormously|intensely|profoundly|deeply|"
    r"thoroughly|utterly|completely|totally|"
    r"absolutely|entirely|fully|wholly|"
    r"perfectly|quite\s+(?:remarkable|extraordinary|impossible|different)|"
    r"remarkably|incredibly|unbelievably|"
    r"strikingly|stunningly|breathtakingly|"
    r"overwhelmingly|devastatingly|"
    # moderate intensifiers
    r"really|highly|particularly|especially|"
    r"significantly|substantially|considerably|"
    r"noticeably|markedly|distinctly|"
    r"seriously|genuinely|truly|"
    r"decidedly|emphatically|categorically|"
    # colloquial intensifiers
    r"so\s+\w+(?:\s+that)|way\s+too|"
    r"dead\s+\w+|drop\s+\w+|"
    r"bone\s+dry|ice\s+cold|"
    r"crystal\s+clear|pitch\s+dark|"
    r"stone\s+cold|wide\s+open|"
    r"fast\s+asleep|wide\s+awake"
    r")\b",
    re.IGNORECASE,
)

# ── diminishers ─────────────────────────────────────────────────
_DIMINISHERS = re.compile(
    r"\b(?:"
    # softeners
    r"somewhat|slightly|a\s+bit|a\s+little|"
    r"fairly|rather|mildly|moderately|"
    r"reasonably|adequately|passably|"
    r"marginally|minimally|negligibly|"
    r"barely|hardly|scarcely|"
    # hedges of degree
    r"kind\s+of|sort\s+of|a\s+sort\s+of|"
    r"to\s+some\s+(?:degree|extent)|"
    r"in\s+some\s+(?:measure|way|respect)|"
    r"to\s+a\s+(?:certain|some|limited)\s+(?:degree|extent)|"
    r"at\s+least\s+(?:somewhat|slightly)|"
    r"more\s+or\s+less|by\s+and\s+large|"
    # understatement markers
    r"not\s+entirely|not\s+exactly|"
    r"not\s+quite|not\s+really|"
    r"not\s+particularly|not\s+especially|"
    r"not\s+terribly|not\s+awfully|"
    r"not\s+all\s+that|not\s+so\s+much|"
    # diminishers
    r"only\s+(?:slightly|somewhat|a\s+little|marginally)|"
    r"just\s+(?:barely|hardly|scarcely|a\s+little)|"
    r"ever\s+so\s+slightly"
    r")\b",
    re.IGNORECASE,
)

# ── equative constructions ──────────────────────────────────────
_EQUATIVE_CONSTRUCTIONS = re.compile(
    r"\b(?:"
    r"as\s+\w+\s+as|"
    r"equally\s+\w+|"
    r"just\s+as\s+\w+|"
    r"every\s+bit\s+as|"
    r"no\s+less\s+than|"
    r"no\s+more\s+than|"
    r"the\s+same\s+(?:degree|extent|level|amount)|"
    r"to\s+the\s+same\s+(?:degree|extent)|"
    r"on\s+a\s+par\s+with|"
    r"on\s+an\s+equal\s+footing|"
    r"in\s+equal\s+measure|"
    r"as\s+much\s+as|"
    r"as\s+little\s+as|"
    r"as\s+many\s+as|"
    r"as\s+few\s+as|"
    r"as\s+well\s+as|"
    r"as\s+bad\s+as|"
    r"as\s+good\s+as|"
    r"as\s+big\s+as|"
    r"as\s+small\s+as"
    r")\b",
    re.IGNORECASE,
)

# ── approximative degree adverbs ────────────────────────────────
_APPROXIMATIVE_ADVERBS = re.compile(
    r"\b(?:"
    r"almost|nearly|practically|virtually|"
    r"essentially|effectively|roughly|"
    r"approximately|about|around|"
    r"close\s+to|bordering\s+on|"
    r"verging\s+on|tantamount\s+to|"
    r"all\s+but|anything\s+but|"
    r"next\s+to\s+(?:impossible|useless|pointless)|"
    r"well\s+nigh|"
    r"more\s+or\s+less|"
    r"in\s+the\s+(?:neighborhood|vicinity|ballpark)\s+of|"
    r"somewhere\s+(?:around|between|near)|"
    r"getting\s+on\s+for|"
    r"not\s+far\s+from|"
    r"within\s+(?:reach|sight|a\s+whisker)\s+of|"
    r"touching\s+on"
    r")\b",
    re.IGNORECASE,
)

# ── sufficiency and excess markers ──────────────────────────────
_SUFFICIENCY_EXCESS = re.compile(
    r"\b(?:"
    # excess
    r"too\s+\w+(?:\s+to|\s+for)|"
    r"overly\s+\w+|"
    r"excessively\s+\w+|"
    r"unduly\s+\w+|"
    r"inordinately\s+\w+|"
    r"disproportionately\s+\w+|"
    r"unreasonably\s+\w+|"
    r"painfully\s+\w+|"
    r"impossibly\s+\w+|"
    # sufficiency
    r"\w+\s+enough(?:\s+to|\s+for)|"
    r"sufficiently\s+\w+|"
    r"adequately\s+\w+|"
    r"well\s+enough|"
    r"good\s+enough|"
    r"close\s+enough|"
    r"near\s+enough|"
    # insufficiency
    r"not\s+\w+\s+enough|"
    r"far\s+from\s+enough|"
    r"nowhere\s+near\s+enough|"
    r"not\s+nearly\s+enough"
    r")\b",
    re.IGNORECASE,
)

# ── combined pattern for unique form counting ───────────────────
_ALL_GRADATION = re.compile(
    r"\b(?:"
    # comparatives
    r"more|less|fewer|better|worse|greater|lesser|"
    r"larger|smaller|higher|lower|longer|shorter|"
    r"wider|narrower|deeper|shallower|broader|thinner|"
    r"thicker|heavier|lighter|faster|slower|harder|easier|"
    r"stronger|weaker|richer|poorer|older|younger|newer|"
    r"warmer|cooler|hotter|colder|brighter|darker|louder|"
    r"quieter|clearer|simpler|"
    # superlatives
    r"most|least|fewest|best|worst|greatest|largest|"
    r"smallest|highest|lowest|longest|shortest|widest|"
    r"narrowest|deepest|shallowest|broadest|thinnest|"
    r"thickest|heaviest|lightest|fastest|slowest|hardest|"
    r"easiest|strongest|weakest|richest|poorest|oldest|"
    r"youngest|newest|warmest|coolest|hottest|coldest|"
    r"brightest|darkest|loudest|quietest|clearest|simplest|"
    # intensifiers
    r"very|extremely|exceedingly|exceptionally|extraordinarily|"
    r"tremendously|immensely|enormously|intensely|profoundly|"
    r"deeply|thoroughly|utterly|completely|totally|absolutely|"
    r"entirely|fully|wholly|perfectly|remarkably|incredibly|"
    r"unbelievably|strikingly|stunningly|breathtakingly|"
    r"overwhelmingly|devastatingly|really|highly|particularly|"
    r"especially|significantly|substantially|considerably|"
    r"noticeably|markedly|distinctly|seriously|genuinely|truly|"
    r"decidedly|emphatically|categorically|"
    # diminishers
    r"somewhat|slightly|fairly|rather|mildly|moderately|"
    r"reasonably|adequately|passably|marginally|minimally|"
    r"negligibly|barely|hardly|scarcely|"
    # approximatives
    r"almost|nearly|practically|virtually|essentially|"
    r"effectively|roughly|approximately"
    r")\b",
    re.IGNORECASE,
)


# ── dataclass ───────────────────────────────────────────────────


@dataclass
class GradationDensityResult:
    """Results of gradation density analysis."""

    # Raw counts
    comparative_count: int = 0
    superlative_count: int = 0
    intensifier_count: int = 0
    diminisher_count: int = 0
    equative_count: int = 0
    approximative_count: int = 0
    sufficiency_excess_count: int = 0
    unique_gradation_forms: int = 0

    # Rates per 100 sentences
    comparative_rate: float = 0.0
    superlative_rate: float = 0.0
    intensifier_rate: float = 0.0
    diminisher_rate: float = 0.0
    equative_rate: float = 0.0
    approximative_rate: float = 0.0
    sufficiency_excess_rate: float = 0.0

    # Composite
    gradation_diversity_index: float = 0.0
    gradation_density_index: float = 0.0
    classification: str = "flat"

    # Metadata
    total_sentences: int = 0
    details: dict = field(default_factory=dict)


# ── main function ───────────────────────────────────────────────


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


def measure_gradation_density(text: str) -> GradationDensityResult:
    """Analyze gradation and degree language density in text.

    Parameters
    ----------
    text : str
        The text to analyze.

    Returns
    -------
    GradationDensityResult
        Analysis results with rates, composite index, and classification.
    """
    result = GradationDensityResult()

    if not text or not text.strip():
        return result

    sentence_count = _count_sentences(text)
    result.total_sentences = sentence_count
    scale = 100.0 / max(sentence_count, 1)

    # ── Count each category ─────────────────────────────────
    comparative = _count_matches(_COMPARATIVE_CONSTRUCTIONS, text)
    superlative = _count_matches(_SUPERLATIVE_CONSTRUCTIONS, text)
    intensifier = _count_matches(_INTENSIFIERS, text)
    diminisher = _count_matches(_DIMINISHERS, text)
    equative = _count_matches(_EQUATIVE_CONSTRUCTIONS, text)
    approximative = _count_matches(_APPROXIMATIVE_ADVERBS, text)
    suff_excess = _count_matches(_SUFFICIENCY_EXCESS, text)

    # Unique gradation forms
    all_forms = _ALL_GRADATION.findall(text)
    unique_forms: Set[str] = {f.lower().strip() for f in all_forms}

    # Store counts
    result.comparative_count = comparative
    result.superlative_count = superlative
    result.intensifier_count = intensifier
    result.diminisher_count = diminisher
    result.equative_count = equative
    result.approximative_count = approximative
    result.sufficiency_excess_count = suff_excess
    result.unique_gradation_forms = len(unique_forms)

    # Rates per 100 sentences
    result.comparative_rate = round(comparative * scale, 3)
    result.superlative_rate = round(superlative * scale, 3)
    result.intensifier_rate = round(intensifier * scale, 3)
    result.diminisher_rate = round(diminisher * scale, 3)
    result.equative_rate = round(equative * scale, 3)
    result.approximative_rate = round(approximative * scale, 3)
    result.sufficiency_excess_rate = round(suff_excess * scale, 3)

    # Diversity: ratio of unique forms to maximum possible (~40)
    max_possible_forms = 40
    result.gradation_diversity_index = round(
        min(1.0, len(unique_forms) / max_possible_forms), 3
    )

    # ── Composite index (0.0 – 1.0) ────────────────────────
    # Normalize each rate to roughly 0–1 via soft caps
    cap_comparative = min(1.0, result.comparative_rate / 30.0)
    cap_superlative = min(1.0, result.superlative_rate / 10.0)
    cap_intensifier = min(1.0, result.intensifier_rate / 25.0)
    cap_diminisher = min(1.0, result.diminisher_rate / 12.0)
    cap_equative = min(1.0, result.equative_rate / 8.0)
    cap_approximative = min(1.0, result.approximative_rate / 10.0)
    cap_suff_excess = min(1.0, result.sufficiency_excess_rate / 8.0)
    cap_diversity = result.gradation_diversity_index

    composite = (
        0.20 * cap_comparative
        + 0.12 * cap_superlative
        + 0.22 * cap_intensifier
        + 0.12 * cap_diminisher
        + 0.06 * cap_equative
        + 0.08 * cap_approximative
        + 0.06 * cap_suff_excess
        + 0.14 * cap_diversity
    )
    result.gradation_density_index = round(min(1.0, composite), 4)

    # ── Classification ──────────────────────────────────────
    idx = result.gradation_density_index
    if idx < 0.05:
        result.classification = "flat"
    elif idx < 0.15:
        result.classification = "lightly_gradated"
    elif idx < 0.35:
        result.classification = "moderately_gradated"
    elif idx < 0.60:
        result.classification = "heavily_gradated"
    else:
        result.classification = "gradation_saturated"

    result.details = {
        "comparative_rate": result.comparative_rate,
        "superlative_rate": result.superlative_rate,
        "intensifier_rate": result.intensifier_rate,
        "diminisher_rate": result.diminisher_rate,
        "equative_rate": result.equative_rate,
        "approximative_rate": result.approximative_rate,
        "sufficiency_excess_rate": result.sufficiency_excess_rate,
        "gradation_diversity_index": result.gradation_diversity_index,
        "gradation_density_index": result.gradation_density_index,
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

    r = measure_gradation_density(text)
    print(f"gradation_density_index    : {r.gradation_density_index:.4f}")
    print(f"classification             : {r.classification}")
    print(f"comparative_rate           : {r.comparative_rate}")
    print(f"superlative_rate           : {r.superlative_rate}")
    print(f"intensifier_rate           : {r.intensifier_rate}")
    print(f"diminisher_rate            : {r.diminisher_rate}")
    print(f"equative_rate              : {r.equative_rate}")
    print(f"approximative_rate         : {r.approximative_rate}")
    print(f"sufficiency_excess_rate    : {r.sufficiency_excess_rate}")
    print(f"gradation_diversity_index  : {r.gradation_diversity_index}")
    print(f"total_sentences            : {r.total_sentences}")
