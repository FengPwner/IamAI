#!/usr/bin/env python3
"""writer_qualifier_density — measure how much prose relies on qualifiers.

Qualifiers are the seasoning of language.  They amplify,
reduce, compare, and calibrate the force of a statement.
A text rich in qualifiers is precise but potentially
overwrought; a text poor in them is blunt but potentially
imprecise.

The qualifier sits between the assertion and its intensity.
"Hot" becomes "very hot" or "slightly hot" or "hotter than
expected."  Each qualifier shifts the meaning by a degree,
and the accumulation of these shifts shapes how a reader
receives the text.

High qualifier density signals a writer who calibrates
every claim — careful, nuanced, sometimes hedging.  Low
qualifier density signals a writer who states things as
they are — direct, confident, sometimes overconfident.

This module measures **how much of a text consists of
language that modifies the intensity, degree, or scope
of assertions** — intensifiers, downtoners, degree phrases,
comparative qualifiers, and superlative amplifiers.

Orthogonality to other metrics
-------------------------------

- **hedging_density** tracks language that distances the
  writer from their claims (perhaps, possibly, may).
  Qualifiers modify intensity; hedges modify commitment.
  "Very likely" has a qualifier (very) AND a hedge
  (likely).  "Very good" has a qualifier but no hedge.

- **precision** tracks how specific and exact a text is.
  Qualifiers can enhance precision ("approximately 47%"
  is more precise than "about half") or reduce it
  ("somewhat effective" is less precise than "effective
  at reducing errors by 12%").

- **formality** tracks register and tone.  Qualifiers
  appear in both formal ("to a considerable degree")
  and informal ("super cool") registers.  The form of
  the qualifier correlates with formality; the density
  does not.

- **conviction** tracks how forcefully a text argues.
  Intensifiers can boost conviction ("absolutely
  essential") or hedging qualifiers can reduce it
  ("somewhat important").  The qualifier's direction
  matters; this module measures density regardless
  of direction.

- **concreteness** tracks how tangible and sensory a
  text is.  Qualifiers are abstract modifiers — they
  calibrate meaning without adding sensory detail.
  A concrete text can have high or low qualifier
  density.

- **fragment_density** tracks syntactic incompleteness.
  Qualifiers appear within complete sentences; they
  modify rather than fragment.

Dimensions
----------

==============================  =============================================
metric                          meaning
==============================  =============================================
intensifier_rate                frequency of adverbs and adjectives that
                                amplify or strengthen: very, extremely,
                                incredibly, absolutely, totally, utterly,
                                completely, remarkably, exceptionally,
                                extraordinarily, immensely, profoundly,
                                deeply, thoroughly, enormously, vastly,
                                hugely, tremendously, supremely, eminently
downtoner_rate                  frequency of adverbs and phrases that reduce
                                or soften: slightly, somewhat, rather,
                                fairly, mildly, moderately, marginally,
                                barely, hardly, scarcely, a bit, a little,
                                a touch, a hint of, sort of, kind of
degree_phrase_rate              frequency of multi-word degree expressions:
                                to some extent, to a degree, in some
                                measure, by and large, more or less, to a
                                great extent, in no small part, to no small
                                degree, not in the least, at the very least,
                                at most, at best, at worst, for the most
                                part, in large measure
comparative_qualifier_rate      frequency of implicit and explicit comparison
                                markers: more than, less than, rather than,
                                as...as, not as...as, far from, anything
                                but, everything but, all but, next to,
                                second only to, compared to, relative to
superlative_amplifier_rate      frequency of superlative and peak-intensity
                                constructions: the most, the least, the
                                best, the worst, above all, most
                                importantly, most significantly, first and
                                foremost, more than anything, beyond
                                measure, without equal, unparalleled,
                                unmatched, unrivaled
==============================  =============================================

Composite: **qualifier_density_index** (0.0 to 1.0)
Weights: intensifier 0.30, downtoner 0.20, degree_phrase 0.20,
comparative 0.15, superlative 0.15.

Classification thresholds:
- 0.00 – 0.06: unadorned
- 0.06 – 0.15: minimally_qualified
- 0.15 – 0.30: moderately_qualified
- 0.30 – 0.50: richly_qualified
- 0.50 – 1.00: lavishly_qualified
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

INTENSIFIERS: Set[str] = {
    "very", "extremely", "incredibly", "absolutely",
    "totally", "utterly", "completely", "remarkably",
    "exceptionally", "extraordinarily", "immensely",
    "profoundly", "deeply", "thoroughly", "enormously",
    "vastly", "hugely", "tremendously", "supremely",
    "eminently", "intensely", "highly", "particularly",
    "especially", "notably", "significantly", "decidedly",
    "emphatically", "categorically", "unequivocally",
    "unquestionably", "undeniably", "indisputably",
    "terribly", "awfully", "dreadfully", "frightfully",
    "exceedingly", "passing", "wondrously",
}

DOWNTONERS: Set[str] = {
    "slightly", "somewhat", "rather", "fairly",
    "mildly", "moderately", "marginally", "barely",
    "hardly", "scarcely",
}

DOWNTONER_PHRASES: List[re.Pattern] = [
    re.compile(r"\ba\s+bit\b", re.IGNORECASE),
    re.compile(r"\ba\s+little\b", re.IGNORECASE),
    re.compile(r"\ba\s+touch\b", re.IGNORECASE),
    re.compile(r"\ba\s+hint\s+of\b", re.IGNORECASE),
    re.compile(r"\bsort\s+of\b", re.IGNORECASE),
    re.compile(r"\bkind\s+of\b", re.IGNORECASE),
    re.compile(r"\ba\s+smidgen\b", re.IGNORECASE),
    re.compile(r"\ba\s+smidge\b", re.IGNORECASE),
    re.compile(r"\ba\s+shade\b", re.IGNORECASE),
    re.compile(r"\ba\s+trifle\b", re.IGNORECASE),
    re.compile(r"\bever\s+so\s+slightly\b", re.IGNORECASE),
    re.compile(r"\bjust\s+a\s+touch\b", re.IGNORECASE),
    re.compile(r"\bnot\s+entirely\b", re.IGNORECASE),
    re.compile(r"\bnot\s+quite\b", re.IGNORECASE),
    re.compile(r"\bnot\s+exactly\b", re.IGNORECASE),
    re.compile(r"\bnot\s+really\b", re.IGNORECASE),
]

DEGREE_PHRASES: List[re.Pattern] = [
    re.compile(r"\bto\s+some\s+(?:extent|degree)\b", re.IGNORECASE),
    re.compile(r"\bin\s+some\s+measure\b", re.IGNORECASE),
    re.compile(r"\bby\s+and\s+large\b", re.IGNORECASE),
    re.compile(r"\bmore\s+or\s+less\b", re.IGNORECASE),
    re.compile(r"\bto\s+a\s+great\s+extent\b", re.IGNORECASE),
    re.compile(r"\bto\s+a\s+large\s+extent\b", re.IGNORECASE),
    re.compile(r"\bto\s+a\s+certain\s+(?:extent|degree)\b", re.IGNORECASE),
    re.compile(r"\bin\s+no\s+small\s+(?:part|measure|degree)\b", re.IGNORECASE),
    re.compile(r"\bto\s+no\s+small\s+degree\b", re.IGNORECASE),
    re.compile(r"\bnot\s+in\s+the\s+least\b", re.IGNORECASE),
    re.compile(r"\bat\s+the\s+very\s+least\b", re.IGNORECASE),
    re.compile(r"\bat\s+most\b", re.IGNORECASE),
    re.compile(r"\bat\s+best\b", re.IGNORECASE),
    re.compile(r"\bat\s+worst\b", re.IGNORECASE),
    re.compile(r"\bfor\s+the\s+most\s+part\b", re.IGNORECASE),
    re.compile(r"\bin\s+large\s+measure\b", re.IGNORECASE),
    re.compile(r"\bto\s+such\s+an?\s+extent\b", re.IGNORECASE),
    re.compile(r"\bto\s+that\s+extent\b", re.IGNORECASE),
    re.compile(r"\bto\s+this\s+extent\b", re.IGNORECASE),
    re.compile(r"\bin\s+equal\s+measure\b", re.IGNORECASE),
    re.compile(r"\bto\s+varying\s+degrees\b", re.IGNORECASE),
]

COMPARATIVE_QUALIFIER_PHRASES: List[re.Pattern] = [
    re.compile(r"\bmore\s+than\b", re.IGNORECASE),
    re.compile(r"\bless\s+than\b", re.IGNORECASE),
    re.compile(r"\brather\s+than\b", re.IGNORECASE),
    re.compile(r"\bas\s+\w+\s+as\b", re.IGNORECASE),
    re.compile(r"\bnot\s+as\s+\w+\s+as\b", re.IGNORECASE),
    re.compile(r"\bfar\s+from\b", re.IGNORECASE),
    re.compile(r"\banything\s+but\b", re.IGNORECASE),
    re.compile(r"\beverything\s+but\b", re.IGNORECASE),
    re.compile(r"\ball\s+but\b", re.IGNORECASE),
    re.compile(r"\bnext\s+to\b", re.IGNORECASE),
    re.compile(r"\bsecond\s+only\s+to\b", re.IGNORECASE),
    re.compile(r"\bcompared\s+(?:to|with)\b", re.IGNORECASE),
    re.compile(r"\brelative\s+to\b", re.IGNORECASE),
    re.compile(r"\bin\s+comparison\s+(?:to|with)\b", re.IGNORECASE),
    re.compile(r"\bvis[\-\s]à[\-\s]vis\b", re.IGNORECASE),
    re.compile(r"\bby\s+comparison\b", re.IGNORECASE),
]

SUPERLATIVE_AMPLIFIER_PHRASES: List[re.Pattern] = [
    re.compile(r"\bthe\s+most\b", re.IGNORECASE),
    re.compile(r"\bthe\s+least\b", re.IGNORECASE),
    re.compile(r"\bthe\s+best\b", re.IGNORECASE),
    re.compile(r"\bthe\s+worst\b", re.IGNORECASE),
    re.compile(r"\bthe\s+greatest\b", re.IGNORECASE),
    re.compile(r"\bthe\s+finest\b", re.IGNORECASE),
    re.compile(r"\bthe\s+highest\b", re.IGNORECASE),
    re.compile(r"\bthe\s+lowest\b", re.IGNORECASE),
    re.compile(r"\bthe\s+deepest\b", re.IGNORECASE),
    re.compile(r"\bthe\s+strongest\b", re.IGNORECASE),
    re.compile(r"\bthe\s+weakest\b", re.IGNORECASE),
    re.compile(r"\bthe\s+sharpest\b", re.IGNORECASE),
    re.compile(r"\babove\s+all\b", re.IGNORECASE),
    re.compile(r"\bmost\s+importantly\b", re.IGNORECASE),
    re.compile(r"\bmost\s+significantly\b", re.IGNORECASE),
    re.compile(r"\bmost\s+notably\b", re.IGNORECASE),
    re.compile(r"\bfirst\s+and\s+foremost\b", re.IGNORECASE),
    re.compile(r"\bmore\s+than\s+anything\b", re.IGNORECASE),
    re.compile(r"\bbeyond\s+measure\b", re.IGNORECASE),
    re.compile(r"\bwithout\s+equal\b", re.IGNORECASE),
    re.compile(r"\bwithout\s+parallel\b", re.IGNORECASE),
    re.compile(r"\bunparalleled\b", re.IGNORECASE),
    re.compile(r"\bunmatched\b", re.IGNORECASE),
    re.compile(r"\bunrivaled\b", re.IGNORECASE),
    re.compile(r"\bunsurpassed\b", re.IGNORECASE),
    re.compile(r"\bpeerless\b", re.IGNORECASE),
    re.compile(r"\bincomparable\b", re.IGNORECASE),
    re.compile(r"\bsupreme\b", re.IGNORECASE),
]


# ── Main Class ───────────────────────────────────────────────────────

class WriterQualifierDensity:
    """Measure qualifier density in prose text."""

    # ── Individual Dimensions ────────────────────────────────────

    def intensifier_rate(self, text: str) -> float:
        """Count intensifier adverbs per sentence."""
        tokens = _tokenize_lower(text)
        count = sum(1 for t in tokens if t in INTENSIFIERS)
        return count / _sentence_count(text)

    def downtoner_rate(self, text: str) -> float:
        """Count downtoner words and phrases per sentence."""
        tokens = _tokenize_lower(text)
        word_count = sum(1 for t in tokens if t in DOWNTONERS)
        phrase_count = sum(
            1 for pat in DOWNTONER_PHRASES
            for _ in pat.finditer(text)
        )
        return (word_count + phrase_count) / _sentence_count(text)

    def degree_phrase_rate(self, text: str) -> float:
        """Count multi-word degree expressions per sentence."""
        count = sum(
            1 for pat in DEGREE_PHRASES
            for _ in pat.finditer(text)
        )
        return count / _sentence_count(text)

    def comparative_qualifier_rate(self, text: str) -> float:
        """Count comparison marker phrases per sentence."""
        count = sum(
            1 for pat in COMPARATIVE_QUALIFIER_PHRASES
            for _ in pat.finditer(text)
        )
        return count / _sentence_count(text)

    def superlative_amplifier_rate(self, text: str) -> float:
        """Count superlative and peak-intensity constructions per sentence."""
        count = sum(
            1 for pat in SUPERLATIVE_AMPLIFIER_PHRASES
            for _ in pat.finditer(text)
        )
        return count / _sentence_count(text)

    # ── Composite ────────────────────────────────────────────────

    def compute_qualifier_density_index(
        self,
        intensifier: float,
        downtoner: float,
        degree_phrase: float,
        comparative: float,
        superlative: float,
    ) -> float:
        """Compute weighted composite qualifier density index (0.0–1.0)."""

        # Normalize each dimension to [0, 1]

        # intensifier: typically 0-1 per sentence, cap at 3
        norm_intensifier = min(intensifier / 3.0, 1.0)

        # downtoner: typically 0-1 per sentence, cap at 3
        norm_downtoner = min(downtoner / 3.0, 1.0)

        # degree_phrase: typically 0-0.5 per sentence, cap at 2
        norm_degree_phrase = min(degree_phrase / 2.0, 1.0)

        # comparative: typically 0-0.5 per sentence, cap at 2
        norm_comparative = min(comparative / 2.0, 1.0)

        # superlative: typically 0-0.3 per sentence, cap at 1.5
        norm_superlative = min(superlative / 1.5, 1.0)

        return (
            norm_intensifier * 0.30
            + norm_downtoner * 0.20
            + norm_degree_phrase * 0.20
            + norm_comparative * 0.15
            + norm_superlative * 0.15
        )

    def classify(self, index: float) -> str:
        """Classify qualifier density level."""
        if index >= 0.50:
            return "lavishly_qualified"
        elif index >= 0.30:
            return "richly_qualified"
        elif index >= 0.15:
            return "moderately_qualified"
        elif index >= 0.06:
            return "minimally_qualified"
        else:
            return "unadorned"

    # ── Main Entry Point ─────────────────────────────────────────

    def measure(self, text: str) -> Dict[str, Any]:
        """Measure all qualifier density metrics for given text."""
        if not text or not text.strip():
            return {
                "intensifier_rate": 0.0,
                "downtoner_rate": 0.0,
                "degree_phrase_rate": 0.0,
                "comparative_qualifier_rate": 0.0,
                "superlative_amplifier_rate": 0.0,
                "qualifier_density_index": 0.0,
                "classification": "unadorned",
            }

        intensifier = self.intensifier_rate(text)
        downtoner = self.downtoner_rate(text)
        degree_phrase = self.degree_phrase_rate(text)
        comparative = self.comparative_qualifier_rate(text)
        superlative = self.superlative_amplifier_rate(text)

        index = self.compute_qualifier_density_index(
            intensifier, downtoner, degree_phrase,
            comparative, superlative,
        )
        classification = self.classify(index)

        return {
            "intensifier_rate": round(intensifier, 4),
            "downtoner_rate": round(downtoner, 4),
            "degree_phrase_rate": round(degree_phrase, 4),
            "comparative_qualifier_rate": round(comparative, 4),
            "superlative_amplifier_rate": round(superlative, 4),
            "qualifier_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    qualified_text = """
    The results were extremely significant and remarkably
    consistent.  The effect was particularly strong in the
    treatment group, though somewhat weaker in controls.
    To a great extent, the findings confirm what was
    already suspected.  The most important discovery was
    the extraordinarily high correlation between the two
    variables.  More than anything, the data suggest a
    deeply interconnected system.  Above all, the
    implications are profoundly far-reaching.
    """

    plain_text = """
    The results were significant.  The effect appeared in
    the treatment group.  The findings confirm the
    hypothesis.  The correlation between the two variables
    was high.  The data suggest an interconnected system.
    The implications are far-reaching.
    """

    wqd = WriterQualifierDensity()

    print("=== Qualified Text ===")
    result = wqd.measure(qualified_text)
    for key, value in result.items():
        print(f"{key:35s} {value}")

    print("\n=== Plain Text ===")
    result = wqd.measure(plain_text)
    for key, value in result.items():
        print(f"{key:35s} {value}")
