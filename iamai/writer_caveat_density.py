#!/usr/bin/env python3
"""writer_caveat_density — measure how much prose relies on caveats and disclaimers.

Caveats are the prose of self-protection.  They are the writer's
insurance policy, the linguistic equivalent of a legal shield woven
into the fabric of ordinary text.  Every "results may vary" is a
small retreat from the claim that preceded it.  Every "not a
substitute for professional advice" is a wall erected between the
writer and liability.

Caveat density is not a quality metric.  A medical pamphlet
*should* be dense with caveats — lives depend on the reader
understanding the limits of general information.  A terms-of-service
page is saturated with them by design.  A novel should have none.
A blog post might have a few.  The right density depends on the
writer's legal exposure, ethical obligations, and relationship
with the reader's trust.

This module measures **how much of a text is spent limiting
liability, restricting scope, warning of risks, or disclaiming
responsibility** — liability disclaimers, result qualifiers,
professional advice disclaimers, warranty limitations, temporal
restrictions, and scope boundaries.

Orthogonality to other metrics
-------------------------------

- **hedging_density** tracks epistemic caution — language that
  distances the writer from certainty about their claims (perhaps,
  possibly, may, might, seems).  Caveats are not about uncertainty;
  they are about *protection*.  "The results suggest a correlation"
  is hedging.  "Results may vary" is a caveat.  Hedging qualifies
  belief; caveats qualify liability.

- **precision** tracks how specific and exact a text is.  Caveats
  can enhance precision ("valid for 30 days from purchase") or
  reduce it ("subject to change without notice").  But precision
  is about informational specificity; caveats are about obligation
  boundaries.  A precise caveat ("valid until 2026-12-31 23:59 UTC")
  serves both metrics differently.

- **formality** tracks register and tone.  Caveats tend toward
  formal language ("the foregoing shall not constitute a warranty")
  but can appear in casual registers too ("just my opinion though").
  Formality measures social distance; caveats measure legal and
  ethical distance.

- **conviction** tracks how forcefully a text argues.  Caveats
  reduce apparent conviction by limiting the scope of claims, but
  they can coexist with strong conviction in the core argument.
  "This approach works — though results depend on your dataset"
  has both conviction and a caveat.  Conviction measures force;
  caveats measure the perimeter of that force.

- **qualifier_density** tracks intensity modification (very,
  somewhat, extremely).  Qualifiers calibrate degree; caveats
  calibrate responsibility.  "Very effective" has a qualifier
  but no caveat.  "Effective, results may vary" has a caveat
  but no qualifier.

- **fragment_density** tracks syntactic incompleteness.  Caveats
  are typically complete sentences or clauses ("Please note that
  past performance does not guarantee future results").  Fragments
  measure form; caveats measure function.

Caveats ask: **is the text protecting itself, and how much of
its language is spent on that effort?**

Dimensions
----------

==============================  =============================================
metric                          meaning
==============================  =============================================
liability_disclaimer_rate       frequency of sentences containing liability
                                disclaimers per sentence: language that
                                limits legal responsibility — "not liable
                                for", "no warranty", "at your own risk",
                                "as is", "without guarantee", "no
                                obligation", "no responsibility for"
result_qualifier_rate           frequency of sentences containing result
                                disclaimers per sentence: language that
                                limits the generalizability of claims —
                                "results may vary", "your mileage may
                                vary", "individual results", "not
                                guaranteed", "past performance", "no
                                assurance", "may not work for everyone"
professional_advice_rate        frequency of sentences disclaiming
                                professional authority per sentence:
                                language that redirects to qualified
                                professionals — "consult a doctor",
                                "not medical advice", "not legal advice",
                                "not financial advice", "seek professional",
                                "not a substitute for", "talk to your"
warranty_limitation_rate        frequency of sentences limiting warranties
                                or guarantees per sentence: "no warranty
                                expressed or implied", "subject to change",
                                "without notice", "no guarantee", "may be
                                discontinued", "not obligated to maintain"
temporal_restriction_rate       frequency of sentences imposing time
                                boundaries on claims per sentence: "as of",
                                "at the time of writing", "subject to
                                change", "valid until", "current as of",
                                "may expire", "limited time"
scope_limitation_rate           frequency of sentences limiting the scope
                                of claims per sentence: "for informational
                                purposes only", "for educational use",
                                "not exhaustive", "not comprehensive",
                                "does not cover", "limited to", "applies
                                only to", "in certain jurisdictions"
==============================  =============================================

From these six dimensions a composite **caveat_density_index**
is computed as a weighted average and classified:

===========================  =================================================
class                        meaning
===========================  =================================================
unencumbered                 index < 0.03 — prose makes claims without
                             protective language
lightly_caveated             0.03 <= index < 0.10 — occasional disclaimers,
                             typical of responsible non-legal prose
moderately_caveated          0.10 <= index < 0.25 — regular protective
                             language, typical of health/finance content
heavily_caveated             0.25 <= index < 0.45 — text is significantly
                             shaped by liability concerns (legal docs,
                             medical disclaimers, financial products)
legally_saturated            index >= 0.45 — text is dominated by protective
                             language (terms of service, EULAs, regulatory
                             filings)
===========================  =================================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Pattern libraries
# ---------------------------------------------------------------------------

LIABILITY_DISCLAIMER_PATTERNS: List[re.Pattern] = [
    # "Not liable for" / "Not responsible for"
    re.compile(r"\bnot\s+(?:liable|responsible|accountable)\s+(?:for|to)\b", re.IGNORECASE),
    # "At your own risk"
    re.compile(r"\bat\s+(?:your|the\s+user'?s?)\s+own\s+risk\b", re.IGNORECASE),
    # "As is" / "As-is" warranty disclaimer
    re.compile(r"\bas[\s-]+is\b", re.IGNORECASE),
    # "No warranty" / "Without warranty"
    re.compile(r"\b(?:no|without)\s+(?:warranty|guarantee)\b", re.IGNORECASE),
    # "Disclaims all liability" / "Disclaim any responsibility"
    re.compile(r"\bdisclaim[sed]*\s+(?:all|any|every)?\s*(?:liability|responsibility|obligation)\b", re.IGNORECASE),
    # "Hold harmless" / "Indemnify"
    re.compile(r"\b(?:hold\s+harmless|indemnif\w*)\b", re.IGNORECASE),
    # "No obligation"
    re.compile(r"\bno\s+obligation\b", re.IGNORECASE),
    # "Use at your own discretion"
    re.compile(r"\b(?:use|try|apply)\s+(?:it\s+)?at\s+your\s+own\s+(?:risk|discretion|peril)\b", re.IGNORECASE),
    # "Shall not be liable"
    re.compile(r"\bshall\s+not\s+be\s+(?:liable|held\s+liable|responsible|accountable)\b", re.IGNORECASE),
    # "Under no circumstances"
    re.compile(r"\bunder\s+no\s+(?:circumstances|conditions|situations)\b", re.IGNORECASE),
]

RESULT_QUALIFIER_PATTERNS: List[re.Pattern] = [
    # "Results may vary" / "Your results may vary"
    re.compile(r"\b(?:your\s+)?(?:results?|outcomes?|effects?)\s+may\s+vary\b", re.IGNORECASE),
    # "Your mileage may vary" / "YMMV"
    re.compile(r"\b(?:your\s+mileage\s+may\s+vary|YMMV)\b", re.IGNORECASE),
    # "Individual results" / "Individual experiences"
    re.compile(r"\bindividual\s+(?:results?|experiences?|outcomes?|responses?)\b", re.IGNORECASE),
    # "Not guaranteed" / "No guarantee"
    re.compile(r"\bnot\s+guaranteed\b", re.IGNORECASE),
    re.compile(r"\bno\s+guarantee\b", re.IGNORECASE),
    # "Past performance" disclaimer
    re.compile(r"\bpast\s+performance\b", re.IGNORECASE),
    # "May not work for everyone" / "Not for everyone"
    re.compile(r"\bmay\s+not\s+work\s+for\s+(?:everyone|everybody|all\s+users?|you)\b", re.IGNORECASE),
    # "No assurance"
    re.compile(r"\bno\s+assurance\b", re.IGNORECASE),
    # "Does not ensure" / "Cannot ensure"
    re.compile(r"\b(?:does\s+not|cannot|may\s+not)\s+ensure\b", re.IGNORECASE),
    # "Actual results may differ"
    re.compile(r"\bactual\s+results?\s+may\s+(?:differ|vary)\b", re.IGNORECASE),
]

PROFESSIONAL_ADVICE_PATTERNS: List[re.Pattern] = [
    # "Not medical/legal/financial advice"
    re.compile(r"\bnot\s+(?:medical|legal|financial|tax|investment|health|professional)\s+advice\b", re.IGNORECASE),
    # "Consult a doctor/lawyer/professional"
    re.compile(r"\bconsult\s+(?:a|an|your)\s+(?:doctor|physician|lawyer|attorney|accountant|financial\s+advisor|professional|specialist|expert|therapist|counselor|pharmacist|dentist)\b", re.IGNORECASE),
    # "Seek professional" advice/help
    re.compile(r"\bseek\s+(?:professional|medical|legal|financial|expert|qualified)\s+(?:advice|help|guidance|counsel|assistance|consultation)\b", re.IGNORECASE),
    # "Not a substitute for"
    re.compile(r"\bnot\s+a\s+substitute\s+for\b", re.IGNORECASE),
    # "Talk to your doctor/lawyer"
    re.compile(r"\btalk\s+to\s+your\s+(?:doctor|physician|lawyer|attorney|financial\s+advisor|healthcare\s+provider|pharmacist|therapist)\b", re.IGNORECASE),
    # "Always consult"
    re.compile(r"\balways\s+consult\s+(?:a|an|your)\b", re.IGNORECASE),
    # "Before starting any" program/treatment/regimen
    re.compile(r"\bbefore\s+starting\s+(?:any|a|the)\s+(?:program|treatment|regimen|diet|exercise|medication|supplement|therapy|plan)\b", re.IGNORECASE),
    # "Does not constitute" advice
    re.compile(r"\bdoes\s+not\s+constitute\s+(?:medical|legal|financial|professional|investment|tax)\s+advice\b", re.IGNORECASE),
]

WARRANTY_LIMITATION_PATTERNS: List[re.Pattern] = [
    # "Subject to change"
    re.compile(r"\bsubject\s+to\s+change\b", re.IGNORECASE),
    # "Without notice" / "Without prior notice"
    re.compile(r"\bwithout\s+(?:prior\s+)?notice\b", re.IGNORECASE),
    # "No warranty expressed or implied"
    re.compile(r"\bno\s+warranty\s+(?:expressed|implied|or\s+implied|express\s+or\s+implied)\b", re.IGNORECASE),
    # "May be discontinued"
    re.compile(r"\bmay\s+be\s+(?:discontinued|withdrawn|removed|terminated|suspended)\b", re.IGNORECASE),
    # "Not obligated to maintain"
    re.compile(r"\bnot\s+obligated\s+to\s+(?:maintain|support|update|continue|provide)\b", re.IGNORECASE),
    # "Provided as-is"
    re.compile(r"\bprovided\s+(?:as[\s-]+is|without\s+(?:any\s+)?warrant\w+)\b", re.IGNORECASE),
    # "Expressly disclaims"
    re.compile(r"\bexpressly\s+disclaims?\b", re.IGNORECASE),
    # "All warranties are hereby disclaimed"
    re.compile(r"\bwarrant\w*\s+(?:are|is)\s+hereby\s+disclaimed\b", re.IGNORECASE),
]

TEMPORAL_RESTRICTION_PATTERNS: List[re.Pattern] = [
    # "As of" date reference
    re.compile(r"\bas\s+of\s+(?:\d|January|February|March|April|May|June|July|August|September|October|November|December|the\s+date)\b", re.IGNORECASE),
    # "At the time of writing" / "At the time of publication"
    re.compile(r"\bat\s+the\s+time\s+of\s+(?:writing|publication|printing|posting|this\s+writing)\b", re.IGNORECASE),
    # "Current as of"
    re.compile(r"\bcurrent\s+as\s+of\b", re.IGNORECASE),
    # "Valid until" / "Valid through"
    re.compile(r"\bvalid\s+(?:until|through|for)\b", re.IGNORECASE),
    # "May expire"
    re.compile(r"\bmay\s+expire\b", re.IGNORECASE),
    # "Limited time"
    re.compile(r"\blimited[\s-]+time\b", re.IGNORECASE),
    # "Prices and availability subject to change"
    re.compile(r"\b(?:prices?|availability|offers?|terms?)\s+(?:and\s+)?(?:are|is)?\s*(?:subject\s+to\s+change|may\s+change)\b", re.IGNORECASE),
    # "Effective date"
    re.compile(r"\beffective\s+(?:date|from|as\s+of)\b", re.IGNORECASE),
]

SCOPE_LIMITATION_PATTERNS: List[re.Pattern] = [
    # "For informational purposes only"
    re.compile(r"\bfor\s+(?:informational|educational|entertainment|illustrative|reference|demonstration)\s+purposes?(?:\s+only)?\b", re.IGNORECASE),
    # "Not exhaustive" / "Not comprehensive"
    re.compile(r"\bnot\s+(?:exhaustive|comprehensive|complete|all[\s-]+inclusive)\b", re.IGNORECASE),
    # "Does not cover" / "Does not address"
    re.compile(r"\bdoes\s+not\s+(?:cover|address|include|account\s+for|encompass)\b", re.IGNORECASE),
    # "Limited to" scope
    re.compile(r"\blimited\s+to\b", re.IGNORECASE),
    # "Applies only to" / "Applies solely to"
    re.compile(r"\bapplies?\s+(?:only|solely|exclusively)\s+to\b", re.IGNORECASE),
    # "In certain jurisdictions" / "May not be available in all areas"
    re.compile(r"\b(?:in\s+certain\s+jurisdictions|may\s+not\s+be\s+available\s+in\s+(?:all|your|some)\s+(?:areas?|regions?|countries?|jurisdictions?))\b", re.IGNORECASE),
    # "This is not a complete list"
    re.compile(r"\bnot\s+a\s+complete\s+list\b", re.IGNORECASE),
    # "Among other things" / "Including but not limited to"
    re.compile(r"\bincluding\s+but\s+not\s+limited\s+to\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences, preserving terminal punctuation."""
    parts = re.split(r'(?<=[.!?…—–])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def _count_matching(sentences: List[str], patterns: List[re.Pattern]) -> int:
    """Count sentences matching at least one pattern in the list."""
    count = 0
    for sent in sentences:
        if any(p.search(sent) for p in patterns):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class WriterCaveatDensity:
    """Measure how much prose relies on caveats and disclaimers.

    Caveats are the language of self-protection: disclaimers,
    warnings, scope limitations, and liability shields that
    protect the writer from the consequences of their claims.
    """

    def __init__(self):
        self.liability_disclaimer = LIABILITY_DISCLAIMER_PATTERNS
        self.result_qualifier = RESULT_QUALIFIER_PATTERNS
        self.professional_advice = PROFESSIONAL_ADVICE_PATTERNS
        self.warranty_limitation = WARRANTY_LIMITATION_PATTERNS
        self.temporal_restriction = TEMPORAL_RESTRICTION_PATTERNS
        self.scope_limitation = SCOPE_LIMITATION_PATTERNS

    def measure_liability_disclaimer_rate(self, text: str) -> float:
        """Rate of sentences containing liability disclaimers."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.liability_disclaimer)
        return count / len(sentences)

    def measure_result_qualifier_rate(self, text: str) -> float:
        """Rate of sentences containing result disclaimers."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.result_qualifier)
        return count / len(sentences)

    def measure_professional_advice_rate(self, text: str) -> float:
        """Rate of sentences disclaiming professional authority."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.professional_advice)
        return count / len(sentences)

    def measure_warranty_limitation_rate(self, text: str) -> float:
        """Rate of sentences limiting warranties or guarantees."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.warranty_limitation)
        return count / len(sentences)

    def measure_temporal_restriction_rate(self, text: str) -> float:
        """Rate of sentences imposing time boundaries on claims."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.temporal_restriction)
        return count / len(sentences)

    def measure_scope_limitation_rate(self, text: str) -> float:
        """Rate of sentences limiting the scope of claims."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.scope_limitation)
        return count / len(sentences)

    def compute_caveat_density_index(
        self,
        liability: float,
        result_qual: float,
        professional: float,
        warranty: float,
        temporal: float,
        scope: float,
    ) -> float:
        """Compute composite caveat density index (0.0 to 1.0).

        Weights: liability 0.25, result_qualifier 0.20,
        professional_advice 0.15, warranty_limitation 0.15,
        temporal_restriction 0.10, scope_limitation 0.15.
        """
        index = (
            0.25 * liability
            + 0.20 * result_qual
            + 0.15 * professional
            + 0.15 * warranty
            + 0.10 * temporal
            + 0.15 * scope
        )
        return min(index, 1.0)

    def classify(self, index: float) -> str:
        """Classify caveat density into descriptive categories."""
        if index >= 0.45:
            return "legally_saturated"
        elif index >= 0.25:
            return "heavily_caveated"
        elif index >= 0.10:
            return "moderately_caveated"
        elif index >= 0.03:
            return "lightly_caveated"
        else:
            return "unencumbered"

    def measure(self, text: str) -> Dict[str, Any]:
        """Full measurement of caveat density in text."""
        liability = self.measure_liability_disclaimer_rate(text)
        result_qual = self.measure_result_qualifier_rate(text)
        professional = self.measure_professional_advice_rate(text)
        warranty = self.measure_warranty_limitation_rate(text)
        temporal = self.measure_temporal_restriction_rate(text)
        scope = self.measure_scope_limitation_rate(text)
        index = self.compute_caveat_density_index(
            liability, result_qual, professional, warranty, temporal, scope
        )
        classification = self.classify(index)

        return {
            "liability_disclaimer_rate": round(liability, 4),
            "result_qualifier_rate": round(result_qual, 4),
            "professional_advice_rate": round(professional, 4),
            "warranty_limitation_rate": round(warranty, 4),
            "temporal_restriction_rate": round(temporal, 4),
            "scope_limitation_rate": round(scope, 4),
            "caveat_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    legal_text = """This product is provided as-is without warranty
    of any kind. The company shall not be liable for any damages
    arising from the use of this software. Results may vary depending
    on your configuration. This document is for informational purposes
    only and does not constitute legal advice. Consult a lawyer before
    making any decisions. Features are subject to change without notice.
    Information is current as of January 2026. This list is not
    exhaustive and does not cover all edge cases. Use at your own risk."""

    narrative_text = """The morning sun cast long shadows across the
    garden. She knelt beside the rose bushes, examining the new growth.
    A cardinal landed on the fence, tilted its head, and flew away.
    The soil was dark and rich after last night's rain. She worked
    slowly, methodically, pulling weeds by the root. By noon the
    garden looked transformed."""

    wcd = WriterCaveatDensity()

    print("=== Legal/Disclaimer Text ===")
    result = wcd.measure(legal_text)
    for key, value in result.items():
        print(f"{key:35s} {value}")

    print("\n=== Narrative Text ===")
    result = wcd.measure(narrative_text)
    for key, value in result.items():
        print(f"{key:35s} {value}")
