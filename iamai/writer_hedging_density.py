#!/usr/bin/env python3
"""writer_hedging_density — measure how much prose uses hedging and cautious language.

Hedging is the linguistic art of saying less than you mean, or
meaning more than you say.  It is the gap between assertion and
commitment — the space where a writer protects themselves from
being wrong while still communicating something useful.

A text with high hedging density bristles with qualifiers:
"perhaps", "it seems", "tends to", "may", "somewhat",
"reportedly", "to some extent".  Every claim comes wrapped
in cotton wool.  Academic papers and legal documents often
score high — precision demands caution.

A text with low hedging density commits fully to every
statement: "The sky is blue.  Water boils at 100°C.  She
won the race."  Journalism, fiction, and persuasive writing
tend toward low hedging — they want the reader to believe.

Hedging density is not a quality metric.  A scientific paper
that hedges appropriately earns trust; one that over-hedges
reads as evasive.  A novel that never hedges feels confident;
one that hedges constantly loses its narrative authority.
The right amount depends on genre, audience, and purpose.

This module measures **how much of a text uses language that
softens, qualifies, or distances the writer from their own
assertions** — epistemic hedges, modal hedges, attribution
shields, approximants, frequency softeners, and degree
dampeners.

Orthogonality to other metrics
-------------------------------

- **conviction** tracks how forcefully a text argues its
  points.  Hedging is one *mechanism* that reduces conviction,
  but conviction also involves evidence quality, logical
  structure, and emotional appeal.  A text can have low
  hedging but also low conviction (bland assertions without
  support), or high hedging with high conviction (carefully
  qualified but well-reasoned arguments).

- **formality** tracks register and tone.  Hedging correlates
  with formality in academic prose but not universally —
  casual speech hedges constantly ("kind of", "sort of",
  "I mean") while formal legal language can be absolute
  ("shall", "must", "will").

- **clarity** tracks how easy a text is to understand.
  Hedging can reduce clarity by adding layers of
  qualification, but clear text can still hedge precisely
  ("approximately 47%" is clearer than "about half").

- **negation_density** tracks denial and rejection.  Hedging
  is not negation — "may not" hedges AND negates, but "might"
  hedges without negating.  Negation says no; hedging says
  maybe.

- **ellipsis_density** tracks what is left unsaid.  Hedging
  is the opposite impulse — adding words to qualify what IS
  said.  Ellipsis omits; hedging qualifies.

- **causal_density** tracks cause-and-effect language.
  Hedging can appear within causal claims ("X may cause Y")
  but measures the caution, not the causation.

Dimensions
----------

=============================  =============================================
metric                         meaning
=============================  =============================================
epistemic_hedge_rate           frequency of epistemic adverbs and adjectives
                               that signal uncertainty: perhaps, possibly,
                               probably, likely, apparently, seemingly,
                               presumably, arguably, allegedly, supposedly,
                               conceivably, plausibly
modal_hedge_rate               frequency of epistemic modal verbs expressing
                               possibility or probability rather than
                               certainty: may, might, could, would, can
                               (when used for possibility not ability),
                               ought to, should (when probabilistic)
attribution_hedge_rate         frequency of attribution shields that
                               distance the writer from a claim: reportedly,
                               allegedly, according to, it is said, some
                               believe, critics argue, sources indicate,
                               it seems, it appears, one might say
approximant_rate               frequency of approximation language that
                               signals imprecision: approximately, roughly,
                               about, around, nearly, almost, sort of,
                               kind of, more or less, in the region of,
                               give or take, or so, -ish
frequency_hedge_rate           frequency of frequency softeners that avoid
                               absolute quantification: often, sometimes,
                               frequently, occasionally, rarely, seldom,
                               tends to, tends toward, generally, typically,
                               usually, for the most part, by and large
degree_hedge_rate              frequency of degree dampeners that reduce
                               the intensity of claims: somewhat, slightly,
                               fairly, rather, quite (as dampener not
                               intensifier), mildly, moderately, to some
                               extent, to a degree, in part, partially
=============================  =============================================

Composite: **hedging_density_index** (0.0 to 1.0)
Weights: epistemic 0.25, modal 0.20, attribution 0.15,
approximant 0.12, frequency 0.13, degree 0.15.

Classification thresholds:
- 0.00 – 0.08: fully_committal
- 0.08 – 0.20: mildly_hedged
- 0.20 – 0.40: moderately_hedged
- 0.40 – 0.60: heavily_hedged
- 0.60 – 1.00: evasively_hedged
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set


# ── Helpers ──────────────────────────────────────────────────────────

def _split_sentences(text: str) -> List[str]:
    """Split text into sentences, stripping whitespace."""
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in raw if s.strip()]


def _tokenize_lower(text: str) -> List[str]:
    """Lowercase word tokenizer."""
    return re.findall(r"[a-zA-Z']+", text.lower())


def _sentence_count(text: str) -> int:
    """Count sentences, minimum 1 to avoid division by zero."""
    sentences = _split_sentences(text)
    return max(len(sentences), 1)


# ── Lexicons ─────────────────────────────────────────────────────────

EPISTEMIC_HEDGES: Set[str] = {
    "perhaps", "possibly", "probably", "likely", "unlikely",
    "apparently", "seemingly", "presumably", "arguably",
    "allegedly", "supposedly", "conceivably", "plausibly",
    "ostensibly", "evidently", "reportedly", "purportedly",
}

# Multi-word epistemic phrases
EPISTEMIC_PHRASES: List[re.Pattern] = [
    re.compile(r"\bit\s+(?:seems|appears|looks)\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+(?:possible|probable|likely|unlikely|conceivable|plausible)\b", re.IGNORECASE),
    re.compile(r"\bit\s+(?:may|might|could|would)\s+be\b", re.IGNORECASE),
    re.compile(r"\bthere\s+(?:may|might|could|would)\s+be\b", re.IGNORECASE),
    re.compile(r"\bto\s+some\s+(?:extent|degree)\b", re.IGNORECASE),
    re.compile(r"\bin\s+all\s+likelihood\b", re.IGNORECASE),
    re.compile(r"\bmore\s+likely\s+than\s+not\b", re.IGNORECASE),
]

MODAL_HEDGES: Set[str] = {
    "may", "might", "could", "would",
}

# "can" is tricky — it hedges when expressing possibility
# ("can be dangerous") but not ability ("can swim").
# We handle it with context in the modal_hedge_rate method.

MODAL_HEDGE_PHRASES: List[re.Pattern] = [
    re.compile(r"\bought\s+to\b", re.IGNORECASE),
    re.compile(r"\bhad\s+better\b", re.IGNORECASE),
    re.compile(r"\bmay\s+well\b", re.IGNORECASE),
    re.compile(r"\bmight\s+well\b", re.IGNORECASE),
    re.compile(r"\bcould\s+well\b", re.IGNORECASE),
    re.compile(r"\bwould\s+(?:tend|appear|seem)\b", re.IGNORECASE),
]

ATTRIBUTION_SHIELDS: List[re.Pattern] = [
    re.compile(r"\baccording\s+to\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+said\b", re.IGNORECASE),
    re.compile(r"\bit\s+has\s+been\s+said\b", re.IGNORECASE),
    re.compile(r"\bsome\s+(?:believe|argue|claim|say|suggest|think|contend|maintain)\b", re.IGNORECASE),
    re.compile(r"\bcritics\s+(?:argue|claim|say|suggest|contend|maintain|point\s+out)\b", re.IGNORECASE),
    re.compile(r"\bsources\s+(?:indicate|suggest|say|claim|report|note)\b", re.IGNORECASE),
    re.compile(r"\bresearchers\s+(?:believe|suggest|argue|claim|find|note|observe)\b", re.IGNORECASE),
    re.compile(r"\bstudies\s+(?:show|suggest|indicate|find|reveal|demonstrate)\b", re.IGNORECASE),
    re.compile(r"\bone\s+might\s+(?:say|argue|suggest|think|conclude)\b", re.IGNORECASE),
    re.compile(r"\bit\s+could\s+be\s+argued\b", re.IGNORECASE),
    re.compile(r"\bthere\s+is\s+(?:reason|grounds)\s+to\s+believe\b", re.IGNORECASE),
    re.compile(r"\bmany\s+(?:believe|argue|claim|say|suggest|think|contend)\b", re.IGNORECASE),
    re.compile(r"\bscholars\s+(?:believe|argue|suggest|note|observe|contend)\b", re.IGNORECASE),
]

APPROXIMANTS: Set[str] = {
    "approximately", "roughly", "about", "around", "nearly",
    "almost", "virtually", "practically", "essentially",
}

APPROXIMANT_PHRASES: List[re.Pattern] = [
    re.compile(r"\bsort\s+of\b", re.IGNORECASE),
    re.compile(r"\bkind\s+of\b", re.IGNORECASE),
    re.compile(r"\bmore\s+or\s+less\b", re.IGNORECASE),
    re.compile(r"\bin\s+the\s+region\s+of\b", re.IGNORECASE),
    re.compile(r"\bgive\s+or\s+take\b", re.IGNORECASE),
    re.compile(r"\bor\s+so\b", re.IGNORECASE),
    re.compile(r"\bor\s+thereabouts\b", re.IGNORECASE),
    re.compile(r"\bsomething\s+like\b", re.IGNORECASE),
    re.compile(r"\bclose\s+to\b", re.IGNORECASE),
    re.compile(r"\bin\s+the\s+neighborhood\s+of\b", re.IGNORECASE),
    re.compile(r"\bin\s+the\s+ballpark\b", re.IGNORECASE),
]

# Suffix "-ish" as approximant
APPROXIMANT_SUFFIX = re.compile(r"\b\w{3,}ish\b", re.IGNORECASE)

FREQUENCY_HEDGES: Set[str] = {
    "often", "sometimes", "frequently", "occasionally",
    "rarely", "seldom", "generally", "typically", "usually",
    "normally", "ordinarily", "commonly", "mostly",
    "predominantly", "largely", "mainly",
}

FREQUENCY_HEDGE_PHRASES: List[re.Pattern] = [
    re.compile(r"\btends?\s+to\b", re.IGNORECASE),
    re.compile(r"\btends?\s+toward\b", re.IGNORECASE),
    re.compile(r"\bfor\s+the\s+most\s+part\b", re.IGNORECASE),
    re.compile(r"\bby\s+and\s+large\b", re.IGNORECASE),
    re.compile(r"\bas\s+a\s+(?:general\s+)?rule\b", re.IGNORECASE),
    re.compile(r"\bin\s+general\b", re.IGNORECASE),
    re.compile(r"\bmore\s+often\s+than\s+not\b", re.IGNORECASE),
    re.compile(r"\bfrom\s+time\s+to\s+time\b", re.IGNORECASE),
    re.compile(r"\bnow\s+and\s+then\b", re.IGNORECASE),
    re.compile(r"\bon\s+the\s+whole\b", re.IGNORECASE),
]

DEGREE_HEDGES: Set[str] = {
    "somewhat", "slightly", "fairly", "rather", "mildly",
    "moderately", "marginally", "partially", "partly",
}

DEGREE_HEDGE_PHRASES: List[re.Pattern] = [
    re.compile(r"\bto\s+some\s+(?:extent|degree)\b", re.IGNORECASE),
    re.compile(r"\bto\s+a\s+(?:certain|limited|some)\s+(?:extent|degree)\b", re.IGNORECASE),
    re.compile(r"\bin\s+part\b", re.IGNORECASE),
    re.compile(r"\bat\s+least\s+(?:somewhat|partially|in\s+part)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+entirely\b", re.IGNORECASE),
    re.compile(r"\bnot\s+wholly\b", re.IGNORECASE),
    re.compile(r"\bnot\s+altogether\b", re.IGNORECASE),
    re.compile(r"\bnot\s+fully\b", re.IGNORECASE),
    re.compile(r"\bnot\s+completely\b", re.IGNORECASE),
]

# "quite" is a dampener before gradable adjectives ("quite good")
# but an intensifier before absolute ones ("quite perfect").
# We count it as dampener before common gradable adjectives.
QUITE_DAMPENER = re.compile(
    r"\bquite\s+(?:good|bad|nice|interesting|important|useful|"
    r"different|similar|large|small|big|long|short|high|low|"
    r"hot|cold|fast|slow|hard|soft|easy|difficult|simple|"
    r"complex|clear|obvious|significant|substantial|considerable|"
    r"effective|successful|suitable|appropriate|relevant)\b",
    re.IGNORECASE,
)


# ── Main Class ───────────────────────────────────────────────────────


class WriterHedgingDensity:
    """Measure how much prose uses hedging and cautious language."""

    def __init__(self) -> None:
        self.epistemic_hedges = EPISTEMIC_HEDGES
        self.epistemic_phrases = EPISTEMIC_PHRASES
        self.modal_hedges = MODAL_HEDGES
        self.modal_phrases = MODAL_HEDGE_PHRASES
        self.attribution_shields = ATTRIBUTION_SHIELDS
        self.approximants = APPROXIMANTS
        self.approximant_phrases = APPROXIMANT_PHRASES
        self.approximant_suffix = APPROXIMANT_SUFFIX
        self.frequency_hedges = FREQUENCY_HEDGES
        self.frequency_phrases = FREQUENCY_HEDGE_PHRASES
        self.degree_hedges = DEGREE_HEDGES
        self.degree_phrases = DEGREE_HEDGE_PHRASES
        self.quite_dampener = QUITE_DAMPENER

    # ── Dimension 1: Epistemic Hedges ────────────────────────────

    def epistemic_hedge_rate(self, text: str) -> float:
        """Frequency of epistemic uncertainty markers per sentence.

        Counts words like 'perhaps', 'possibly', 'probably',
        'likely', 'apparently', 'seemingly', 'presumably',
        'arguably', and phrases like 'it seems', 'it appears',
        'it is possible'.

        Returns 0.0 when no epistemic hedges are found,
        higher values for more epistemically hedged text.
        """
        n_sentences = _sentence_count(text)
        tokens = _tokenize_lower(text)

        count = sum(1 for t in tokens if t in self.epistemic_hedges)

        # Multi-word phrases
        for pattern in self.epistemic_phrases:
            count += len(pattern.findall(text))

        return count / n_sentences

    # ── Dimension 2: Modal Hedges ────────────────────────────────

    def modal_hedge_rate(self, text: str) -> float:
        """Frequency of epistemic modal verbs per sentence.

        Counts 'may', 'might', 'could', 'would' when used to
        express possibility rather than ability or past tense.
        Also counts phrases like 'ought to', 'may well',
        'might well', 'would tend'.

        The word 'can' is counted only when followed by 'be',
        'have', or a past participle — contexts where it
        expresses possibility rather than ability.

        Returns 0.0 when no modal hedges are found,
        higher values for more modally hedged text.
        """
        n_sentences = _sentence_count(text)
        tokens = _tokenize_lower(text)

        count = 0
        for i, token in enumerate(tokens):
            if token in self.modal_hedges:
                count += 1
            elif token == "can":
                # "can be", "can have", "can cause" → possibility
                # "can swim", "can run" → ability
                if i + 1 < len(tokens):
                    next_word = tokens[i + 1]
                    if next_word in (
                        "be", "have", "has", "had", "cause",
                        "lead", "result", "produce", "occur",
                        "happen", "trigger", "create", "make",
                        "affect", "influence", "change",
                    ):
                        count += 1

        # Multi-word modal phrases
        for pattern in self.modal_phrases:
            count += len(pattern.findall(text))

        return count / n_sentences

    # ── Dimension 3: Attribution Shields ─────────────────────────

    def attribution_hedge_rate(self, text: str) -> float:
        """Frequency of attribution shields per sentence.

        Counts phrases that distance the writer from a claim:
        'according to', 'reportedly', 'allegedly', 'it is said',
        'some believe', 'critics argue', 'sources indicate',
        'one might say', 'studies show/suggest'.

        Returns 0.0 when no attribution shields are found,
        higher values for more attribution-hedged text.
        """
        n_sentences = _sentence_count(text)

        count = 0
        for pattern in self.attribution_shields:
            count += len(pattern.findall(text))

        # Single-word attribution adverbs (when not already counted
        # in epistemic_hedges)
        attribution_adverbs = {"reportedly", "allegedly", "purportedly"}
        tokens = _tokenize_lower(text)
        count += sum(1 for t in tokens if t in attribution_adverbs)

        return count / n_sentences

    # ── Dimension 4: Approximants ────────────────────────────────

    def approximant_rate(self, text: str) -> float:
        """Frequency of approximation language per sentence.

        Counts words and phrases that signal imprecision:
        'approximately', 'roughly', 'about', 'around',
        'nearly', 'almost', 'sort of', 'kind of',
        'more or less', 'give or take', '-ish' suffix.

        Returns 0.0 when no approximants are found,
        higher values for more approximate text.
        """
        n_sentences = _sentence_count(text)
        tokens = _tokenize_lower(text)

        count = sum(1 for t in tokens if t in self.approximants)

        # Multi-word approximant phrases
        for pattern in self.approximant_phrases:
            count += len(pattern.findall(text))

        # -ish suffix
        count += len(self.approximant_suffix.findall(text))

        return count / n_sentences

    # ── Dimension 5: Frequency Hedges ────────────────────────────

    def frequency_hedge_rate(self, text: str) -> float:
        """Frequency of frequency softeners per sentence.

        Counts words and phrases that avoid absolute
        quantification: 'often', 'sometimes', 'frequently',
        'occasionally', 'rarely', 'tends to', 'generally',
        'for the most part', 'by and large'.

        Returns 0.0 when no frequency hedges are found,
        higher values for more frequency-hedged text.
        """
        n_sentences = _sentence_count(text)
        tokens = _tokenize_lower(text)

        count = sum(1 for t in tokens if t in self.frequency_hedges)

        # Multi-word frequency phrases
        for pattern in self.frequency_phrases:
            count += len(pattern.findall(text))

        return count / n_sentences

    # ── Dimension 6: Degree Hedges ───────────────────────────────

    def degree_hedge_rate(self, text: str) -> float:
        """Frequency of degree dampeners per sentence.

        Counts words and phrases that reduce the intensity
        of claims: 'somewhat', 'slightly', 'fairly', 'rather',
        'mildly', 'moderately', 'to some extent', 'in part',
        'not entirely', 'not completely'.

        Also counts 'quite' as a dampener when followed by
        gradable adjectives ('quite good' = somewhat good,
        not 'quite perfect' = completely perfect).

        Returns 0.0 when no degree hedges are found,
        higher values for more degree-hedged text.
        """
        n_sentences = _sentence_count(text)
        tokens = _tokenize_lower(text)

        count = sum(1 for t in tokens if t in self.degree_hedges)

        # Multi-word degree phrases
        for pattern in self.degree_phrases:
            count += len(pattern.findall(text))

        # "quite" as dampener
        count += len(self.quite_dampener.findall(text))

        return count / n_sentences

    # ── Composite ────────────────────────────────────────────────

    def compute_hedging_density_index(
        self,
        epistemic: float,
        modal: float,
        attribution: float,
        approximant: float,
        frequency: float,
        degree: float,
    ) -> float:
        """Compute composite hedging density index (0.0 to 1.0).

        Weights:
        - epistemic_hedge_rate: 0.25 (direct uncertainty markers
          are the strongest hedging signal)
        - modal_hedge_rate: 0.20 (epistemic modals are the
          grammatical backbone of hedging)
        - attribution_hedge_rate: 0.15 (attribution shields
          distance the writer from claims)
        - approximant_rate: 0.12 (approximation language
          signals imprecision)
        - frequency_hedge_rate: 0.13 (frequency softeners
          avoid absolute claims)
        - degree_hedge_rate: 0.15 (degree dampeners reduce
          the intensity of assertions)
        """
        # Normalize each dimension to [0, 1]

        # epistemic: typically 0-1 per sentence, cap at 3
        norm_epistemic = min(epistemic / 3.0, 1.0)

        # modal: typically 0-2 per sentence, cap at 4
        norm_modal = min(modal / 4.0, 1.0)

        # attribution: typically 0-0.5 per sentence, cap at 2
        norm_attribution = min(attribution / 2.0, 1.0)

        # approximant: typically 0-1 per sentence, cap at 3
        norm_approximant = min(approximant / 3.0, 1.0)

        # frequency: typically 0-1 per sentence, cap at 3
        norm_frequency = min(frequency / 3.0, 1.0)

        # degree: typically 0-1 per sentence, cap at 3
        norm_degree = min(degree / 3.0, 1.0)

        return (
            norm_epistemic * 0.25
            + norm_modal * 0.20
            + norm_attribution * 0.15
            + norm_approximant * 0.12
            + norm_frequency * 0.13
            + norm_degree * 0.15
        )

    def classify(self, index: float) -> str:
        """Classify hedging density level."""
        if index >= 0.60:
            return "evasively_hedged"
        elif index >= 0.40:
            return "heavily_hedged"
        elif index >= 0.20:
            return "moderately_hedged"
        elif index >= 0.08:
            return "mildly_hedged"
        else:
            return "fully_committal"

    # ── Main Entry Point ─────────────────────────────────────────

    def measure(self, text: str) -> Dict[str, Any]:
        """Measure all hedging density metrics for given text."""
        if not text or not text.strip():
            return {
                "epistemic_hedge_rate": 0.0,
                "modal_hedge_rate": 0.0,
                "attribution_hedge_rate": 0.0,
                "approximant_rate": 0.0,
                "frequency_hedge_rate": 0.0,
                "degree_hedge_rate": 0.0,
                "hedging_density_index": 0.0,
                "classification": "fully_committal",
            }

        epistemic = self.epistemic_hedge_rate(text)
        modal = self.modal_hedge_rate(text)
        attribution = self.attribution_hedge_rate(text)
        approximant = self.approximant_rate(text)
        frequency = self.frequency_hedge_rate(text)
        degree = self.degree_hedge_rate(text)

        index = self.compute_hedging_density_index(
            epistemic, modal, attribution, approximant,
            frequency, degree,
        )
        classification = self.classify(index)

        return {
            "epistemic_hedge_rate": round(epistemic, 4),
            "modal_hedge_rate": round(modal, 4),
            "attribution_hedge_rate": round(attribution, 4),
            "approximant_rate": round(approximant, 4),
            "frequency_hedge_rate": round(frequency, 4),
            "degree_hedge_rate": round(degree, 4),
            "hedging_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    hedged_text = """
    It seems that the results may possibly suggest a
    correlation between the two variables.  The effect
    could perhaps be attributed to environmental factors,
    according to some researchers.  Studies suggest that
    the relationship is somewhat complex and may tend to
    vary depending on context.  It is possible that
    approximately half of the observed variation might
    be explained by factors not yet identified.  Critics
    argue that the methodology is not entirely sound,
    and one might say the conclusions are rather
    preliminary.  The findings are generally consistent
    with previous work, though not completely aligned.
    """

    direct_text = """
    The results demonstrate a clear correlation between
    the two variables.  Environmental factors cause the
    observed effect.  The relationship is complex and
    varies by context.  Half of the variation remains
    unexplained.  The methodology is flawed.  The
    conclusions are preliminary.  The findings contradict
    previous work.
    """

    whd = WriterHedgingDensity()

    print("=== Hedged Text ===")
    result = whd.measure(hedged_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Direct Text ===")
    result = whd.measure(direct_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")
