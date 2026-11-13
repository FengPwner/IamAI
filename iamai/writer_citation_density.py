#!/usr/bin/env python3
"""writer_citation_density — measure how much prose is spent quoting or attributing external sources.

Citation is the rhetorical act of borrowing authority.  A text
rich in citation leans on voices other than its own — "as X
argues", "according to Y", "in the words of Z", direct quotes
in quotation marks, statistical references ("a 2024 study found
that…"), bibliographic pointers ([1], (Smith, 2023)).

A text poor in citation speaks entirely in its own voice.
Every claim is the author's; every fact is presented as
self-evident or common knowledge.  Memoirs, manifestos, and
children's stories tend toward zero citation.  Academic papers,
journalism, and legal briefs are citation-dense by design.

Citation density is not a quality metric.  A research paper
that cites appropriately earns trust; one that over-cites
reads as derivative or insecure.  An op-ed that cites no one
may be confidently original or recklessly unsupported.  The
right density depends on genre, audience, and epistemic
responsibility.

This module measures **how much of a text is spent invoking,
quoting, paraphrasing, or referencing external sources** —
direct quotations, attribution verbs, named-source references,
statistical citations, and bibliographic markers.

Orthogonality to other metrics
-------------------------------

- **hedging_density** tracks cautious language.  Attribution
  ("according to X") is one hedging *mechanism*, but citation
  is broader: it includes direct quotation, statistical reference,
  and bibliographic pointers that assert rather than hedge.
  A text can cite boldly ("Smith (2023) proved X") or hedge
  without citation ("some believe that X").  Hedging softens
  claims; citation anchors them to sources.

- **conviction** tracks how forcefully a text argues.  Citation
  can strengthen conviction (appealing to authority) or undermine
  it (revealing that the author cannot stand behind their own
  claims).  Conviction measures confidence; citation measures
  source-dependence.

- **formality** tracks register conventions.  Academic citation
  formats are formal, but blog posts cite casually ("as Y
  tweeted…").  Citation appears across the formality spectrum.

- **contrast_density** tracks opposition.  Citation can support
  contrast ("X says A; Y says B") but measures something
  different: who speaks, not whether they disagree.

- **causal_density** tracks cause-and-effect reasoning.
  Citation and causation overlap when sources provide causal
  claims ("a study found that X causes Y"), but citation
  itself is about attribution, not explanation.

- **ellipsis_density** tracks what is left unsaid.  Citation
  is explicitly additive — it brings external voices into the
  text.  Ellipsis omits; citation imports.

Dimensions
----------

=============================  =============================================
metric                         meaning
=============================  =============================================
direct_quotation_rate          frequency of quoted passages per sentence:
                               text enclosed in double or single quotation
                               marks, block-quote markers (leading >),
                               and em-dash-attributed quotes
attribution_verb_rate          frequency of attribution verbs per sentence:
                               says, said, writes, wrote, argues, argued,
                               claims, claimed, notes, noted, observes,
                               observed, suggests, contends, asserts,
                               reports, explains, states, declares,
                               insists, maintains, proposes, concludes,
                               points out, according to
named_source_rate              frequency of named-source references per
                               sentence: capitalized proper nouns followed
                               by year in parentheses, or preceded by
                               "according to", "as", per capitalizedName
                               (Year) pattern, or "X et al."
statistical_citation_rate      frequency of statistical references per
                               sentence: percentage values, study/survey/
                               research/poll references, data-point
                               markers ("the data shows", "results
                               indicate", "figures reveal"), confidence
                               intervals, p-values
bibliographic_marker_rate      frequency of bibliographic pointers per
                               sentence: bracketed numbers [1], [2-4];
                               parenthetical author-year (Smith, 2023);
                               footnote markers; "ibid.", "op. cit.",
                               "loc. cit.", DOI/ISBN references,
                               URL citations
citation_density_index         composite score (0.0 = no citation,
                               1.0 = maximally citation-dense) combining
                               direct_quotation (0.25),
                               attribution_verb (0.25),
                               named_source (0.20),
                               statistical_citation (0.15),
                               bibliographic_marker (0.15)
classification                 categorical label:
                               uncited (<0.05),
                               minimally_cited (<0.15),
                               moderately_cited (<0.35),
                               heavily_cited (<0.55),
                               saturated_with_citation (>=0.55)
=============================  =============================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


# ── Sentence splitting and tokenization ──────────────────────────────

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)?")

# ── Direct quotation patterns ────────────────────────────────────────

_LQ = "\u201c"   # left double quotation mark
_RQ = "\u201d"   # right double quotation mark
_LS = "\u2018"   # left single quotation mark
_RS = "\u2019"   # right single quotation mark

QUOTATION_PATTERNS: Tuple[str, ...] = (
    r'"[^"]*"',                                  # double-quoted passages
    r"'[^']{4,}'",                               # single-quoted (min 4 chars)
    _LQ + r"[^" + _RQ + r"]*" + _RQ,            # smart double quotes
    _LS + r"[^" + _RS + r"]*" + _RS,            # smart single quotes
    r"^>\s+.+",                                  # block-quote markers
    r"\u2014\u2014\s*[A-Z]",                     # double em-dash attribution
    r"\u2014\s*[A-Z]",                           # em-dash attribution
)

# ── Attribution verbs and phrases ────────────────────────────────────

ATTRIBUTION_PHRASES: Tuple[str, ...] = tuple(sorted((
    "according to",
    "in the words of",
    "as stated by",
    "as noted by",
    "as argued by",
    "as observed by",
    "as reported by",
    "as described by",
    "as explained by",
    "as suggested by",
    "in the view of",
    "on the authority of",
    "points out",
    "pointed out",
    "point out",
), key=len, reverse=True))

ATTRIBUTION_VERBS: Tuple[str, ...] = (
    "says", "said",
    "writes", "wrote", "writing",
    "argues", "argued", "arguing",
    "claims", "claimed", "claiming",
    "notes", "noted", "noting",
    "observes", "observed", "observing",
    "suggests", "suggested", "suggesting",
    "contends", "contended", "contending",
    "asserts", "asserted", "asserting",
    "reports", "reported", "reporting",
    "explains", "explained", "explaining",
    "states", "stated", "stating",
    "declares", "declared", "declaring",
    "insists", "insisted", "insisting",
    "maintains", "maintained", "maintaining",
    "proposes", "proposed", "proposing",
    "concludes", "concluded", "concluding",
    "emphasizes", "emphasized", "emphasizing",
    "highlights", "highlighted", "highlighting",
    "demonstrates", "demonstrated", "demonstrating",
    "reveals", "revealed", "revealing",
    "acknowledges", "acknowledged", "acknowledging",
    "admits", "admitted", "admitting",
    "alleges", "alleged", "alleging",
    "testifies", "testified", "testifying",
    "warns", "warned", "warning",
    "confirms", "confirmed", "confirming",
    "estimates", "estimated", "estimating",
    "predicts", "predicted", "predicting",
    "believes", "believed", "believing",
    "thinks", "thought",
    "responds", "responded", "responding",
    "counters", "countered", "countering",
)

# ── Named-source patterns ────────────────────────────────────────────

NAMED_SOURCE_PATTERNS: Tuple[str, ...] = (
    r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+\(\d{4}\)",   # Smith (2023), Van Der Berg (2021)
    r"[A-Z][a-z]+\s+et\s+al\.",                        # Smith et al.
    r"[A-Z][a-z]+\s+&\s+[A-Z][a-z]+",                  # Smith & Jones
    r"[Aa]ccording\s+to\s+[A-Z][a-z]+",                 # according to Smith / According to Smith
    r"[Aa]s\s+[A-Z][a-z]+\s+(?:says|argues|notes|writes|observes|claims|contends|suggests)",  # as Smith argues
)

# ── Statistical citation markers ─────────────────────────────────────

STATISTICAL_MARKERS: Tuple[str, ...] = tuple(sorted((
    "a study found",
    "studies show",
    "studies suggest",
    "research shows",
    "research suggests",
    "research indicates",
    "research finds",
    "a survey found",
    "surveys show",
    "the data shows",
    "the data show",
    "data suggests",
    "data indicates",
    "results indicate",
    "results show",
    "results suggest",
    "figures reveal",
    "figures show",
    "the evidence suggests",
    "the evidence shows",
    "evidence indicates",
    "analysis reveals",
    "analysis shows",
    "a report found",
    "reports indicate",
    "the poll found",
    "polls suggest",
    "the investigation found",
    "experiments show",
    "the trial demonstrated",
    "clinical trials",
    "peer-reviewed",
    "meta-analysis",
    "systematic review",
    "longitudinal study",
    "randomized controlled trial",
    "cohort study",
    "case study",
    "cross-sectional",
), key=len, reverse=True))

STATISTICAL_NUMBER_PATTERNS: Tuple[str, ...] = (
    r"\d+(?:\.\d+)?%",                              # percentages: 42%, 3.7%
    r"p\s*[<>=]\s*0?\.\d+",                         # p-values: p<0.05, p=.001
    r"(?:95%|99%|90%)\s*(?:CI|confidence)",          # confidence intervals
    r"(?:CI|confidence\s+interval)[:\s]*\[",          # CI: [0.3, 0.7]
    r"r\s*=\s*-?\d+\.\d+",                           # correlation coefficients
    r"(?:OR|HR|RR|CI)\s*[=:]\s*\d+",                 # odds/hazard ratios
    r"\d+\s*(?:participants?|subjects?|respondents?|samples?)",  # sample sizes
)

# ── Bibliographic markers ────────────────────────────────────────────

BIBLIOGRAPHIC_PATTERNS: Tuple[str, ...] = (
    r"\[\d+\]",                    # numbered references: [1], [23]
    r"\[\d+[-–]\d+\]",             # range references: [1-4], [2–5]
    r"\([A-Z][a-z]+,?\s+\d{4}\)",  # parenthetical: (Smith, 2023) or (Smith 2023)
    r"\([A-Z][a-z]+\s+et\s+al\.?,?\s+\d{4}\)",  # (Smith et al., 2023)
    r"\bdoi:\s*10\.\d+/\S+",       # DOI references
    r"\bISBN\s+[\d-]+",            # ISBN references
    r"\bISSN\s+[\d-]+",            # ISSN references
    r"\bibid\.?",                   # ibid
    r"\bop\.\s*cit\.?",            # op. cit.
    r"\bloc\.\s*cit\.?",           # loc. cit.
    r"\bcf\.?\s+[A-Z]",            # cf. Smith
    r"\b[Ss]ee\s+[A-Z][a-z]+",     # see Smith / See Smith
    r"\bq\.v\.?",                  # q.v.
    r"\bsupra\s+note",             # supra note
    r"\binfra\s+note",             # infra note
)


# ── Helper functions ─────────────────────────────────────────────────

def _split_sentences(text: str) -> List[str]:
    """Split text into sentences."""
    sents = _SENT_SPLIT.split(text.strip())
    return [s.strip() for s in sents if s.strip()]


def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase words."""
    return _WORD_RE.findall(text.lower())


def _count_phrase_occurrences(text: str, phrases: Tuple[str, ...]) -> int:
    """Count non-overlapping occurrences of phrases in text."""
    text_lower = text.lower()
    total = 0
    for phrase in phrases:
        total += text_lower.count(phrase)
    return total


def _count_pattern_matches(text: str, patterns: Tuple[str, ...]) -> int:
    """Count regex pattern matches in text."""
    text_lower = text.lower()
    total = 0
    for pat in patterns:
        total += len(re.findall(pat, text_lower))
    return total


def _count_pattern_matches_case(text: str, patterns: Tuple[str, ...]) -> int:
    """Count regex pattern matches preserving case."""
    total = 0
    for pat in patterns:
        total += len(re.findall(pat, text))
    return total


# ── Main Class ───────────────────────────────────────────────────────


class WriterCitationDensity:
    """Measure how much prose is spent quoting or attributing external sources."""

    def __init__(self):
        self.quotation_patterns = QUOTATION_PATTERNS
        self.attribution_phrases = ATTRIBUTION_PHRASES
        self.attribution_verbs = ATTRIBUTION_VERBS
        self.named_source_patterns = NAMED_SOURCE_PATTERNS
        self.statistical_markers = STATISTICAL_MARKERS
        self.statistical_number_patterns = STATISTICAL_NUMBER_PATTERNS
        self.bibliographic_patterns = BIBLIOGRAPHIC_PATTERNS

    # ── Dimension 1: Direct quotation rate ────────────────────────

    def measure_direct_quotation_rate(self, text: str) -> float:
        """Count quoted passages per sentence."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_pattern_matches_case(text, self.quotation_patterns)
        return min(count / len(sentences), 1.0)

    # ── Dimension 2: Attribution verb rate ────────────────────────

    def measure_attribution_verb_rate(self, text: str) -> float:
        """Count attribution verbs and phrases per sentence."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        phrase_count = _count_phrase_occurrences(text, self.attribution_phrases)
        verb_count = 0
        text_lower = text.lower()
        words = set(_tokenize(text))
        for verb in self.attribution_verbs:
            if verb in words:
                # Count actual occurrences as whole words
                verb_count += len(re.findall(r"\b" + re.escape(verb) + r"\b", text_lower))
        total = phrase_count + verb_count
        return min(total / len(sentences), 1.0)

    # ── Dimension 3: Named-source rate ────────────────────────────

    def measure_named_source_rate(self, text: str) -> float:
        """Count named-source references per sentence."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        # Case-sensitive: named sources require capitalization
        count = _count_pattern_matches_case(text, self.named_source_patterns)
        return min(count / len(sentences), 1.0)

    # ── Dimension 4: Statistical citation rate ────────────────────

    def measure_statistical_citation_rate(self, text: str) -> float:
        """Count statistical references per sentence."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        marker_count = _count_phrase_occurrences(text, self.statistical_markers)
        number_count = _count_pattern_matches(text, self.statistical_number_patterns)
        total = marker_count + number_count
        return min(total / len(sentences), 1.0)

    # ── Dimension 5: Bibliographic marker rate ────────────────────

    def measure_bibliographic_marker_rate(self, text: str) -> float:
        """Count bibliographic pointers per sentence."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_pattern_matches_case(text, self.bibliographic_patterns)
        return min(count / len(sentences), 1.0)

    # ── Composite index ──────────────────────────────────────────

    def compute_citation_density_index(
        self,
        direct_quotation: float,
        attribution_verb: float,
        named_source: float,
        statistical_citation: float,
        bibliographic_marker: float,
    ) -> float:
        """Compute weighted composite (0.0 to 1.0)."""
        index = (
            direct_quotation * 0.25
            + attribution_verb * 0.25
            + named_source * 0.20
            + statistical_citation * 0.15
            + bibliographic_marker * 0.15
        )
        return min(max(index, 0.0), 1.0)

    # ── Classification ───────────────────────────────────────────

    @staticmethod
    def classify(index: float) -> str:
        """Map composite index to categorical label."""
        if index < 0.05:
            return "uncited"
        if index < 0.15:
            return "minimally_cited"
        if index < 0.35:
            return "moderately_cited"
        if index < 0.55:
            return "heavily_cited"
        return "saturated_with_citation"

    # ── Main entry point ─────────────────────────────────────────

    def measure(self, text: str) -> Dict[str, Any]:
        """Measure all citation density metrics for given text."""
        if not text or not text.strip():
            return {
                "direct_quotation_rate": 0.0,
                "attribution_verb_rate": 0.0,
                "named_source_rate": 0.0,
                "statistical_citation_rate": 0.0,
                "bibliographic_marker_rate": 0.0,
                "citation_density_index": 0.0,
                "classification": "uncited",
            }

        direct_quotation = self.measure_direct_quotation_rate(text)
        attribution_verb = self.measure_attribution_verb_rate(text)
        named_source = self.measure_named_source_rate(text)
        statistical_citation = self.measure_statistical_citation_rate(text)
        bibliographic_marker = self.measure_bibliographic_marker_rate(text)

        index = self.compute_citation_density_index(
            direct_quotation, attribution_verb, named_source,
            statistical_citation, bibliographic_marker
        )
        classification = self.classify(index)

        return {
            "direct_quotation_rate": round(direct_quotation, 4),
            "attribution_verb_rate": round(attribution_verb, 4),
            "named_source_rate": round(named_source, 4),
            "statistical_citation_rate": round(statistical_citation, 4),
            "bibliographic_marker_rate": round(bibliographic_marker, 4),
            "citation_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    citation_rich = """
    According to Smith (2023), the results indicate a significant
    correlation between sleep quality and cognitive performance
    (r = 0.72, p < 0.001). As Johnson argues, "the relationship
    between rest and productivity is not linear but logarithmic"
    [1]. A meta-analysis of 47 studies found that 83% of
    participants showed improvement after intervention. Brown et al.
    reported similar findings, noting that "the effect persists
    across demographics" (Brown, 2022). The data shows a 95% CI
    of [0.65, 0.89]. Williams & Chen observed that the effect
    was strongest in the 25-34 age group. "We were surprised by
    the consistency," the authors wrote. See also the systematic
    review by Davis (2021), doi: 10.1234/example.
    """

    uncited = """
    The old house stood at the edge of the meadow. Wildflowers
    grew along the stone path leading to the front door. The
    windows were dark, the paint peeling in long strips. A cat
    sat on the porch, watching sparrows in the hedge. The wind
    carried the smell of cut grass and distant rain. Somewhere
    a dog barked, then fell silent.
    """

    wcd = WriterCitationDensity()

    print("=== Citation-Rich Text ===")
    result = wcd.measure(citation_rich)
    for key, value in result.items():
        print(f"{key:35s} {value}")

    print("\n=== Uncited Text ===")
    result = wcd.measure(uncited)
    for key, value in result.items():
        print(f"{key:35s} {value}")
