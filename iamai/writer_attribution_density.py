#!/usr/bin/env python3
"""writer_attribution_density — measure how much prose attributes claims to sources.

Every assertion is a choice: stand behind it alone, or borrow
someone else's authority.  Attribution is the rhetorical act of
answering the question "who says?" before the reader can ask it.
A text that never attributes is a text full of floating claims —
"studies show", "experts agree", "it is widely believed" — each
one a ghost citation that asks for trust without offering receipts.
A text that attributes precisely builds a scaffold of named
sources, quoted voices, and traceable evidence.  A text that
attributes excessively drowns its own argument in other people's
authority — every sentence a ventriloquist act.

Attribution density is not a quality metric.  Journalism lives
on attribution — every fact sourced, every quote named.  Academic
prose requires it — claims without citations are speculation.
But fiction, memoir, and persuasive essays often work best when
the author's voice carries the weight alone.  The right density
depends on genre, audience, and the relationship between writer
and reader.

This module measures **how frequently, how diversely, and through
what mechanisms a text attributes its claims to external sources**
— explicit source attribution, quoted speech, expert appeal,
consensus appeal, weasel attribution, and reported speech
constructions.

Orthogonality to other metrics
-------------------------------

- **citation_density** tracks formal citation apparatus —
  footnotes, parenthetical references, bibliography entries,
  bracket numbers.  Attribution density is about the *rhetorical
  act* of attributing a claim, regardless of citation format.
  "According to Smith (2023)" is both a citation and an
  attribution.  "Experts agree" is attribution without citation.
  "[1]" is citation without rhetorical attribution.  Citation
  density measures formal apparatus; attribution density measures
  rhetorical sourcing.

- **hedging_density** tracks cautious language — "perhaps",
  "might", "tends to".  Hedging distances the writer from
  certainty; attribution distances the writer from the claim
  itself.  "It might be true" hedges; "According to Jones, it
  is true" attributes.  Both reduce the writer's personal
  commitment, but through different mechanisms.

- **conviction** tracks how forcefully a text argues.  Attribution
  can either increase conviction (named expert sources strengthen
  an argument) or decrease it (weasel words like "some say"
  weaken commitment).  Attribution density measures the mechanism;
  conviction measures the effect.

- **grounding_density** tracks how well claims are anchored in
  observable evidence.  Attribution is one *form* of grounding
  (appealing to external sources), but grounding also includes
  data references, examples, and demonstrable facts that don't
  require attribution.  Attribution density measures source-based
  grounding; grounding density measures all forms.

- **deixis_density** tracks context-dependent references.
  "He said so" is deictic (who is "he"?).  "Dr. Smith of MIT
  said so" is attributive (the reference is self-contained).
  Deixis measures context-dependence; attribution measures
  source-anchoring.

Attribution density asks: **how much of the prose is built on
attributed claims, and what does the distribution of attribution
mechanisms reveal about the writer's relationship to authority?**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set


# ── regex patterns ──────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Explicit source attribution — "according to X", "as X notes"
_EXPLICIT_ATTRIBUTION = re.compile(
    r"\b(?:according\s+to|"
    r"as\s+(?:noted|stated|argued|observed|suggested|proposed|"
    r"reported|described|explained|shown|demonstrated|found|"
    r"concluded|pointed\s+out|put\s+it|wrote|claimed|"
    r"maintained|insisted|contended|asserted|remarked)\s+by|"
    r"in\s+the\s+(?:words|view|opinion|assessment|analysis|"
    r"judgment|estimation)\s+of|"
    r"as\s+\w+\s+(?:notes?|states?|argues?|observes?|suggests?|"
    r"reports?|writes?|claims?|explains?|describes?|concludes?|"
    r"points?\s+out|puts?\s+it|maintains?|contends?|asserts?)|"
    r"\w+\s+(?:et\s+al\.?|\(\d{4}\))|"
    r"per\s+\w+|"
    r"as\s+reported\s+by|"
    r"citing\s+\w+|"
    r"quoting\s+\w+|"
    r"referencing\s+\w+|"
    r"based\s+on\s+(?:the\s+(?:work|research|findings|analysis|"
    r"study|report|data|evidence)\s+of)|"
    r"following\s+\w+)"
    r"\b",
    re.IGNORECASE,
)

# Quoted speech — direct and indirect quotation markers
_QUOTED_SPEECH = re.compile(
    r'\b(?:said|stated|told|noted|explained|argued|claimed|'
    r'remarked|observed|wrote|declared|announced|testified|'
    r'asserted|maintained|insisted|contended|replied|responded|'
    r'acknowledged|admitted|conceded|confessed|revealed|'
    r'disclosed|confirmed|denied|alleged|recalled|remembered|'
    r'recounted)\s+(?:that|the|a|an|it|he|she|they|we|his|her|'
    r'their|our|this|these|those|in|on|at|to|for|about|with|'
    r'before|after|during|when|while|if|whether|how|why|what|'
    r'who|which|"\w|\'|")'
    r'|\b(?:"|")(?:[^"]{5,200})(?:"|")'
    r'|\b(?:quote|unquote|end\s+quote)\b',
    re.IGNORECASE,
)

# Expert/authority appeal
_EXPERT_APPEAL = re.compile(
    r"\b(?:experts?\s+(?:say|agree|believe|warn|suggest|argue|"
    r"note|recommend|advise|conclude|find|report|claim|insist|"
    r"maintain|contend|assert|observe|explain|estimate|predict)|"
    r"researchers?\s+(?:say|found|discovered|suggest|report|"
    r"conclude|note|believe|argue|claim|show|demonstrate|"
    r"reveal|indicate|estimate|warn|agree|insist|maintain)|"
    r"scientists?\s+(?:say|believe|discovered?|found|suggest|"
    r"report|warn|agree|conclude|note|claim|argue|show|"
    r"demonstrate|reveal|estimate|predict|insist|maintain)|"
    r"(?:doctor|dr|professor|prof)\.\s+\w+|"
    r"authority\s+on|"
    r"leading\s+(?:expert|researcher|scientist|scholar|"
    r"authority|specialist|analyst)|"
    r"(?:peer[\s-]reviewed|published\s+in|"
    r"(?:the\s+)?(?:journal|study|research|paper|report))\s+|"
    r"university\s+of\s+\w+|"
    r"institute\s+(?:of|for)\s+|"
    r"(?:harvard|mit|stanford|oxford|cambridge|yale|princeton|"
    r"columbia|berkeley|chicago|imperial)\s+(?:university|"
    r"research|study|professor|scholar|scientist|expert))",
    re.IGNORECASE,
)

# Consensus appeal — "everyone knows", "widely accepted"
_CONSENSUS_APPEAL = re.compile(
    r"\b(?:widely\s+(?:accepted|known|recognized|believed|"
    r"regarded|acknowledged|understood|agreed|reported|"
    r"documented|established|cited|referenced)|"
    r"(?:generally|commonly|universally|broadly)\s+"
    r"(?:accepted|known|recognized|believed|regarded|"
    r"acknowledged|understood|agreed|established|cited)|"
    r"(?:it\s+is\s+)?(?:well[\s-]known|common\s+knowledge|"
    r"widely\s+held|conventional\s+wisdom|"
    r"the\s+consensus(?:\s+view)?|"
    r"(?:there\s+is\s+)?(?:a|the)\s+(?:growing|emerging|"
    r"broad|general|scientific|expert|academic|scholarly|"
    r"medical|legal)\s+consensus)|"
    r"most\s+(?:experts?|researchers?|scientists?|scholars?|"
    r"analysts?|observers?|authorities?|studies?|reports?|"
    r"sources?|evidence)|"
    r"(?:the\s+)?majority\s+of\s+(?:experts?|researchers?|"
    r"scientists?|scholars?|studies?|reports?|evidence|"
    r"analysts?|observers?)|"
    r"(?:as\s+)?(?:everyone|everybody|we\s+all)\s+"
    r"(?:knows?|agrees?|understands?|recognizes?|"
    r"acknowledges?)|"
    r"no\s+(?:one|expert|researcher|scientist|scholar)\s+"
    r"(?:would\s+)?(?:dispute|deny|disagree|question|"
    r"challenge|doubt))",
    re.IGNORECASE,
)

# Weasel attribution — vague, untraceable source references
_WEASEL_ATTRIBUTION = re.compile(
    r"\b(?:some\s+(?:people|experts?|researchers?|scientists?|"
    r"scholars?|analysts?|observers?|critics?|commentators?|"
    r"sources?|studies?|reports?)\s+(?:say|believe|argue|"
    r"claim|suggest|note|warn|agree|disagree|contend|"
    r"maintain|insist|assert|observe|report|find|show)|"
    r"it\s+is\s+(?:said|believed|thought|reported|rumored|"
    r"claimed|alleged|suggested|understood|known|widely\s+"
    r"(?:held|known|believed|reported))|"
    r"(?:they|people|sources?)\s+say|"
    r"(?:critics?|supporters?|opponents?|advocates?|"
    r"proponents?|detractors?|skeptics?|observers?|"
    r"commentators?|analysts?)\s+(?:say|argue|claim|believe|"
    r"suggest|note|warn|contend|maintain|insist|assert|"
    r"observe|report|find|show|agree|disagree|point\s+out)|"
    r"(?:studies?|research|evidence|data|reports?|surveys?|"
    r"polls?|findings?|statistics?|numbers?|figures?)\s+"
    r"(?:show|suggest|indicate|reveal|demonstrate|confirm|"
    r"support|prove|find|point\s+to|imply)\b|"
    r"(?:many|several|numerous|various|countless)\s+"
    r"(?:studies?|reports?|experts?|researchers?|sources?|"
    r"analyses?)\b|"
    r"(?:anecdotal|circumstantial|preliminary|early)\s+"
    r"(?:evidence|reports?|data|findings?)\b|"
    r"(?:allegedly|reportedly|supposedly|rumored|"
    r"reputedly|purportedly|ostensibly)\b)",
    re.IGNORECASE,
)

# Reported speech constructions — indirect discourse markers
_REPORTED_SPEECH = re.compile(
    r"\b(?:according\s+to\s+(?:reports?|sources?|officials?|"
    r"witnesses?|experts?|analysts?|data|estimates|"
    r"projections?|forecasts?|statistics?|figures?)|"
    r"(?:reports?|sources?|officials?|witnesses?|data|"
    r"estimates?|projections?|forecasts?|statistics?|"
    r"figures?|records?|documents?|archives?|files?|"
    r"accounts?|records?|memoirs?|biographies?)\s+"
    r"(?:indicate|suggest|show|reveal|confirm|state|"
    r"note|record|document|describe|detail|list|"
    r"mention|reference|cite)|"
    r"(?:was|were|has\s+been|have\s+been|is\s+being|"
    r"are\s+being)\s+(?:reported|said|believed|thought|"
    r"known|understood|documented|recorded|alleged|"
    r"claimed|suggested|rumored|estimated|projected|"
    r"forecast|confirmed|denied|disputed|debated|"
    r"questioned|challenged|verified|corroborated)|"
    r"(?:on|in)\s+(?:record|the\s+record|file|account|"
    r"report|statement|declaration|testimony|affidavit|"
    r"transcript|minutes?|proceedings?))",
    re.IGNORECASE,
)

# Anonymous/source attribution — specific source patterns
_SOURCE_PATTERN = re.compile(
    r"\b(?:a\s+(?:senior|junior|former|current|anonymous|"
    r"unnamed|confidential|well[\s-]placed|government|"
    r"industry|inside|insider|official|reliable|"
    r"knowledgeable|informed|independent)\s+source|"
    r"sources?\s+(?:close\s+to|familiar\s+with|"
    r"(?:with\s+)?(?:knowledge|knowledge\s+of|"
    r"direct\s+knowledge|inside\s+information)|"
    r"who\s+(?:asked|requested|demanded|preferred)\s+"
    r"(?:not\s+to\s+be|to\s+remain)\s+(?:named|"
    r"identified|disclosed|revealed))|"
    r"(?:on|under)\s+(?:the\s+)?(?:condition|understanding|"
    r"agreement)\s+of\s+anonymity|"
    r"speaking\s+on\s+(?:the\s+)?(?:condition|understanding)\s+"
    r"of|"
    r"(?:who|that)\s+spoke\s+on\s+(?:the\s+)?(?:condition|"
    r"understanding)\s+of)",
    re.IGNORECASE,
)


# ── dataclass ───────────────────────────────────────────────────


@dataclass
class AttributionDensityResult:
    """Results of attribution density analysis."""

    # Raw counts
    explicit_attribution_count: int = 0
    quoted_speech_count: int = 0
    expert_appeal_count: int = 0
    consensus_appeal_count: int = 0
    weasel_attribution_count: int = 0
    reported_speech_count: int = 0
    source_pattern_count: int = 0
    unique_attribution_forms: int = 0

    # Rates per 100 sentences
    explicit_attribution_rate: float = 0.0
    quoted_speech_rate: float = 0.0
    expert_appeal_rate: float = 0.0
    consensus_appeal_rate: float = 0.0
    weasel_attribution_rate: float = 0.0
    reported_speech_rate: float = 0.0
    source_pattern_rate: float = 0.0

    # Ratios
    attribution_sentence_ratio: float = 0.0
    source_diversity_index: float = 0.0
    traceability_score: float = 0.0

    # Composite
    attribution_density_index: float = 0.0
    classification: str = "unattributed"

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


def measure_attribution_density(text: str) -> AttributionDensityResult:
    """Analyze attribution language density in text.

    Parameters
    ----------
    text : str
        The text to analyze.

    Returns
    -------
    AttributionDensityResult
        Analysis results with rates, composite index, and classification.
    """
    result = AttributionDensityResult()

    if not text or not text.strip():
        return result

    sentence_count = _count_sentences(text)
    result.total_sentences = sentence_count
    scale = 100.0 / max(sentence_count, 1)

    # ── Count each category ─────────────────────────────────
    explicit = _count_matches(_EXPLICIT_ATTRIBUTION, text)
    quoted = _count_matches(_QUOTED_SPEECH, text)
    expert = _count_matches(_EXPERT_APPEAL, text)
    consensus = _count_matches(_CONSENSUS_APPEAL, text)
    weasel = _count_matches(_WEASEL_ATTRIBUTION, text)
    reported = _count_matches(_REPORTED_SPEECH, text)
    source = _count_matches(_SOURCE_PATTERN, text)

    # Count sentences with at least one attribution marker
    sentences = [s for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]
    attribution_sentences = sum(
        1
        for s in sentences
        if (
            _EXPLICIT_ATTRIBUTION.search(s)
            or _QUOTED_SPEECH.search(s)
            or _EXPERT_APPEAL.search(s)
            or _CONSENSUS_APPEAL.search(s)
            or _WEASEL_ATTRIBUTION.search(s)
            or _REPORTED_SPEECH.search(s)
            or _SOURCE_PATTERN.search(s)
        )
    )

    # Unique attribution forms (distinct mechanism categories used)
    categories_used = sum(
        1
        for c in [explicit, quoted, expert, consensus, weasel, reported, source]
        if c > 0
    )

    # Store counts
    result.explicit_attribution_count = explicit
    result.quoted_speech_count = quoted
    result.expert_appeal_count = expert
    result.consensus_appeal_count = consensus
    result.weasel_attribution_count = weasel
    result.reported_speech_count = reported
    result.source_pattern_count = source
    result.unique_attribution_forms = categories_used

    # Rates per 100 sentences
    result.explicit_attribution_rate = round(explicit * scale, 3)
    result.quoted_speech_rate = round(quoted * scale, 3)
    result.expert_appeal_rate = round(expert * scale, 3)
    result.consensus_appeal_rate = round(consensus * scale, 3)
    result.weasel_attribution_rate = round(weasel * scale, 3)
    result.reported_speech_rate = round(reported * scale, 3)
    result.source_pattern_rate = round(source * scale, 3)

    # Attribution sentence ratio
    result.attribution_sentence_ratio = round(
        attribution_sentences / max(sentence_count, 1), 4
    )

    # Source diversity (categories used / 7 max)
    result.source_diversity_index = round(categories_used / 7.0, 3)

    # Traceability: explicit + quoted + expert + source are traceable;
    # consensus + weasel + reported are less traceable
    traceable = explicit + quoted + expert + source
    untraceable = consensus + weasel + reported
    total_attr = traceable + untraceable
    result.traceability_score = round(
        traceable / max(total_attr, 1), 3
    )

    # ── Composite index (0.0 – 1.0) ────────────────────────
    cap_explicit = min(1.0, result.explicit_attribution_rate / 15.0)
    cap_quoted = min(1.0, result.quoted_speech_rate / 20.0)
    cap_expert = min(1.0, result.expert_appeal_rate / 10.0)
    cap_consensus = min(1.0, result.consensus_appeal_rate / 8.0)
    cap_weasel = min(1.0, result.weasel_attribution_rate / 10.0)
    cap_reported = min(1.0, result.reported_speech_rate / 8.0)
    cap_source = min(1.0, result.source_pattern_rate / 3.0)
    cap_ratio = result.attribution_sentence_ratio
    cap_diversity = result.source_diversity_index

    composite = (
        0.18 * cap_explicit
        + 0.15 * cap_quoted
        + 0.10 * cap_expert
        + 0.08 * cap_consensus
        + 0.08 * cap_weasel
        + 0.08 * cap_reported
        + 0.05 * cap_source
        + 0.15 * cap_ratio
        + 0.13 * cap_diversity
    )
    result.attribution_density_index = round(min(1.0, composite), 4)

    # ── Classification ──────────────────────────────────────
    idx = result.attribution_density_index
    if idx < 0.05:
        result.classification = "unattributed"
    elif idx < 0.15:
        result.classification = "lightly_attributed"
    elif idx < 0.35:
        result.classification = "moderately_attributed"
    elif idx < 0.60:
        result.classification = "heavily_attributed"
    else:
        result.classification = "source_saturated"

    result.details = {
        "explicit_attribution_rate": result.explicit_attribution_rate,
        "quoted_speech_rate": result.quoted_speech_rate,
        "expert_appeal_rate": result.expert_appeal_rate,
        "consensus_appeal_rate": result.consensus_appeal_rate,
        "weasel_attribution_rate": result.weasel_attribution_rate,
        "reported_speech_rate": result.reported_speech_rate,
        "source_pattern_rate": result.source_pattern_rate,
        "attribution_sentence_ratio": result.attribution_sentence_ratio,
        "source_diversity_index": result.source_diversity_index,
        "traceability_score": result.traceability_score,
        "attribution_density_index": result.attribution_density_index,
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

    r = measure_attribution_density(text)
    print(f"attribution_density_index : {r.attribution_density_index:.4f}")
    print(f"classification            : {r.classification}")
    print(f"explicit_attribution_rate : {r.explicit_attribution_rate}")
    print(f"quoted_speech_rate        : {r.quoted_speech_rate}")
    print(f"expert_appeal_rate        : {r.expert_appeal_rate}")
    print(f"consensus_appeal_rate     : {r.consensus_appeal_rate}")
    print(f"weasel_attribution_rate   : {r.weasel_attribution_rate}")
    print(f"reported_speech_rate      : {r.reported_speech_rate}")
    print(f"source_pattern_rate       : {r.source_pattern_rate}")
    print(f"attribution_sentence_ratio: {r.attribution_sentence_ratio}")
    print(f"source_diversity_index    : {r.source_diversity_index}")
    print(f"traceability_score        : {r.traceability_score}")
    print(f"total_sentences           : {r.total_sentences}")
