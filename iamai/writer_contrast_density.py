#!/usr/bin/env python3
"""writer_contrast_density — measure how much prose relies on contrastive structures.

Contrast is the rhetorical engine of disagreement, surprise, and
nuance.  A text rich in contrast constantly juxtaposes opposing
ideas — "not this, but that", "although X, nevertheless Y",
"on one hand… on the other hand".  A text poor in contrast
presents ideas without friction — everything aligns, nothing
pushes back.

Contrast density is not a quality metric.  Argumentative essays
and philosophical discourse *must* be contrast-dense — the point
is to weigh competing ideas.  Poetry can use contrast devastatingly
("I wandered lonely as a cloud" sets solitude against company)
or avoid it entirely (haiku presents without opposition).  Technical
writing uses contrast sparingly but precisely ("unlike X, Y
supports…").  Propaganda eliminates contrast — only one side exists.

This module measures **how much of a text is spent establishing
opposition, contradiction, reversal, concession, or juxtaposition**
— adversative conjunctions, antithetical structures, expectation
reversals, concessive pivots, and direct semantic oppositions.

Orthogonality to other metrics
-------------------------------

- **hedging_density** tracks cautious language.  Contrast is about
  opposition, not uncertainty.  A text can contrast boldly ("X is
  wrong; Y is right") or hedge without contrast ("X may be true").
  Hedging softens claims; contrast opposes them.

- **negation_density** tracks logical inversion.  Negation says
  "not X"; contrast says "not X, but Y".  Negation denies;
  contrast denies *and replaces*.  A text can be negation-heavy
  without contrast ("no, never, nothing" — pure denial) or
  contrast-heavy with minimal negation ("however", "although",
  "on the other hand" — juxtaposition without explicit negation).

- **conviction** tracks certainty.  Contrast can strengthen
  conviction (showing you've considered both sides) or undermine
  it (revealing genuine uncertainty between options).  Conviction
  measures confidence; contrast measures structural opposition.

- **causal_density** tracks cause-and-effect reasoning.  Contrast
  and causation can overlap ("because X failed, Y succeeded" —
  causal AND contrastive) but measure different things: causation
  explains *why*; contrast shows *what differs*.

- **ellipsis_density** tracks what is left unsaid.  Contrast is
  explicitly structural — it names both sides.  Ellipsis omits;
  contrast juxtaposes.

- **parallelism_density** tracks grammatical mirroring.  Antithesis
  (a contrast dimension) often uses parallel structure ("it was the
  best of times, it was the worst of times"), but parallelism
  need not be contrastive ("she ran, she jumped, she swam").
  Parallelism measures form; contrast measures opposition.

Dimensions
----------

=============================  =============================================
metric                         meaning
=============================  =============================================
adversative_conjunction_rate   frequency of adversative conjunctions per
                               sentence: but, yet, however, nevertheless,
                               nonetheless, still, although, though, even
                               though, while, whereas, despite, in spite of,
                               notwithstanding, albeit, albeit that
antithesis_rate                frequency of antithetical structures per
                               sentence: not-X-but-Y, rather-than,
                               instead-of, on-one-hand/on-the-other-hand,
                               neither-nor with contrasting terms,
                               either-or with opposing options
reversal_rate                  frequency of expectation-reversing markers
                               per sentence: actually, in fact,
                               surprisingly, contrary to, far from,
                               on the contrary, then again, as it
                               happens, it turns out, paradoxically,
                               ironically, unexpectedly
concession_rate                frequency of concessive pivots per sentence:
                               acknowledged-then-pivoted constructions —
                               "admittedly X, but Y", "granted X,
                               however Y", "it is true that X, yet Y",
                               "to be sure X, nevertheless Y",
                               "of course X, but Y", "while X, Y"
                               where X is acknowledged before being
                               overridden by Y
opposition_density             density of direct semantic opposition:
                               antonym pairs within the same sentence,
                               comparative contrasts (more/less X than Y,
                               unlike X, Y), binary framing
                               (winners/losers, before/after,
                               old/new, past/future, theory/practice)
contrast_density_index         composite score (0.0 = no contrast,
                               1.0 = maximally contrastive) combining
                               adversative_conjunction_rate (0.25),
                               antithesis_rate (0.20),
                               reversal_rate (0.15),
                               concession_rate (0.15),
                               opposition_density (0.25)
classification                 categorical label:
                               contrast_free (<0.05),
                               minimally_contrastive (<0.15),
                               moderately_contrastive (<0.35),
                               richly_contrastive (<0.55),
                               dialectically_contrastive (>=0.55)
=============================  =============================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


# ── Sentence splitting and tokenization ──────────────────────────────

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)?")

# ── Adversative conjunctions ─────────────────────────────────────────

ADVERSATIVE_CONJUNCTIONS: Tuple[str, ...] = tuple(sorted((
    "in spite of the fact that",
    "despite the fact that",
    "in spite of",
    "notwithstanding",
    "on the other hand",
    "in contrast to",
    "even though",
    "for all that",
    "nevertheless",
    "nonetheless",
    "although",
    "whereas",
    "despite",
    "however",
    "though",
    "albeit",
    "while",
    "but",
    "yet",
), key=len, reverse=True))

# ── Antithesis patterns ──────────────────────────────────────────────

ANTITHESIS_PATTERNS: Tuple[str, ...] = (
    r"\bnot\s+(?:\S+\s+){1,4}but\b",
    r"\brather\s+than\b",
    r"\binstead\s+of\b",
    r"\bon\s+(?:the\s+)?one\s+hand\b",
    r"\bon\s+the\s+other\s+hand\b",
    r"\bthe\s+more\b.*\bthe\s+(?:more|less)\b",
    r"\bnot\s+only\b.*\bbut\s+also\b",
    r"\bfrom\s+\S+\s+to\s+\S+\b",
)

# ── Reversal markers ─────────────────────────────────────────────────

REVERSAL_MARKERS: Tuple[str, ...] = tuple(sorted((
    "contrary to popular belief",
    "contrary to expectations",
    "contrary to what",
    "as it turns out",
    "it turns out",
    "against all odds",
    "far from it",
    "on the contrary",
    "paradoxically",
    "unexpectedly",
    "surprisingly",
    "ironically",
    "in reality",
    "as it happens",
    "then again",
    "far from",
    "in fact",
    "actually",
), key=len, reverse=True))

# ── Concession pivots ───────────────────────────────────────────────

CONCESSION_PATTERNS: Tuple[str, ...] = (
    r"\badmittedly\b",
    r"\bgranted[,\s]",
    r"\bto\s+be\s+sure\b",
    r"\bit\s+is\s+true\s+that\b",
    r"\bof\s+course\b",
    r"\bcertainly\b.*(?:but|yet|however|nevertheless|nonetheless)\b",
    r"\bundoubtedly\b.*(?:but|yet|however|nevertheless|nonetheless)\b",
    r"\bno\s+doubt\b.*(?:but|yet|however|nevertheless|nonetheless)\b",
    r"\bgranted\s+that\b",
    r"\bI\s+concede\b",
    r"\bone\s+might\s+(?:say|argue|think)\b",
    r"\bit\s+must\s+be\s+(?:said|admitted|acknowledged)\b",
)

# ── Opposition word pairs ───────────────────────────────────────────

OPPOSITION_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("good", "bad"),
    ("right", "wrong"),
    ("true", "false"),
    ("light", "dark"),
    ("old", "new"),
    ("young", "old"),
    ("past", "future"),
    ("before", "after"),
    ("up", "down"),
    ("high", "low"),
    ("big", "small"),
    ("large", "small"),
    ("long", "short"),
    ("fast", "slow"),
    ("hard", "soft"),
    ("hot", "cold"),
    ("rich", "poor"),
    ("strong", "weak"),
    ("success", "failure"),
    ("win", "lose"),
    ("winners", "losers"),
    ("hope", "despair"),
    ("love", "hate"),
    ("peace", "war"),
    ("life", "death"),
    ("beginning", "end"),
    ("start", "finish"),
    ("create", "destroy"),
    ("build", "break"),
    ("open", "close"),
    ("theory", "practice"),
    ("ideal", "real"),
    ("problem", "solution"),
    ("cause", "effect"),
    ("question", "answer"),
    ("input", "output"),
    ("cause", "effect"),
    ("abstract", "concrete"),
    ("general", "specific"),
    ("simple", "complex"),
    ("easy", "difficult"),
    ("similar", "different"),
    ("same", "different"),
    ("advantage", "disadvantage"),
    ("pros", "cons"),
    ("benefit", "cost"),
    ("reward", "risk"),
    ("strength", "weakness"),
)

# ── Comparative contrast markers ────────────────────────────────────

COMPARATIVE_CONTRAST: Tuple[str, ...] = tuple(sorted((
    "unlike",
    "in contrast",
    "as opposed to",
    "different from",
    "contrary to",
    "compared to",
    "compared with",
    "by contrast",
    "in comparison",
    "more than",
    "less than",
    "rather than",
    "instead of",
), key=len, reverse=True))


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


# ── Main Class ───────────────────────────────────────────────────────


class WriterContrastDensity:
    """Measure how much prose relies on contrastive structures."""

    def __init__(self):
        self.adversative_conjunctions = ADVERSATIVE_CONJUNCTIONS
        self.antithesis_patterns = ANTITHESIS_PATTERNS
        self.reversal_markers = REVERSAL_MARKERS
        self.concession_patterns = CONCESSION_PATTERNS
        self.opposition_pairs = OPPOSITION_PAIRS
        self.comparative_contrast = COMPARATIVE_CONTRAST

    # ── Dimension 1: Adversative conjunction rate ─────────────────

    def measure_adversative_conjunction_rate(self, text: str) -> float:
        """Count adversative conjunctions per sentence."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_phrase_occurrences(text, self.adversative_conjunctions)
        return min(count / len(sentences), 1.0)

    # ── Dimension 2: Antithesis rate ──────────────────────────────

    def measure_antithesis_rate(self, text: str) -> float:
        """Count antithetical structures per sentence."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_pattern_matches(text, self.antithesis_patterns)
        return min(count / len(sentences), 1.0)

    # ── Dimension 3: Reversal rate ────────────────────────────────

    def measure_reversal_rate(self, text: str) -> float:
        """Count expectation-reversing markers per sentence."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_phrase_occurrences(text, self.reversal_markers)
        return min(count / len(sentences), 1.0)

    # ── Dimension 4: Concession rate ──────────────────────────────

    def measure_concession_rate(self, text: str) -> float:
        """Count concessive pivots per sentence."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_pattern_matches(text, self.concession_patterns)
        return min(count / len(sentences), 1.0)

    # ── Dimension 5: Opposition density ──────────────────────────

    def measure_opposition_density(self, text: str) -> float:
        """Measure direct semantic opposition and comparative contrast."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0

        opposition_score = 0.0
        for sent in sentences:
            tokens = set(_tokenize(sent))
            # Count opposition pairs present in same sentence
            for word_a, word_b in self.opposition_pairs:
                if word_a in tokens and word_b in tokens:
                    opposition_score += 1.0

        # Comparative contrast markers
        comp_count = _count_phrase_occurrences(text, self.comparative_contrast)

        total = opposition_score + comp_count
        return min(total / len(sentences), 1.0)

    # ── Composite index ──────────────────────────────────────────

    def compute_contrast_density_index(
        self,
        adversative: float,
        antithesis: float,
        reversal: float,
        concession: float,
        opposition: float,
    ) -> float:
        """Compute weighted composite (0.0 to 1.0)."""
        index = (
            adversative * 0.25
            + antithesis * 0.20
            + reversal * 0.15
            + concession * 0.15
            + opposition * 0.25
        )
        return min(max(index, 0.0), 1.0)

    # ── Classification ───────────────────────────────────────────

    @staticmethod
    def classify(index: float) -> str:
        """Map composite index to categorical label."""
        if index < 0.05:
            return "contrast_free"
        if index < 0.15:
            return "minimally_contrastive"
        if index < 0.35:
            return "moderately_contrastive"
        if index < 0.55:
            return "richly_contrastive"
        return "dialectically_contrastive"

    # ── Main entry point ─────────────────────────────────────────

    def measure(self, text: str) -> Dict[str, Any]:
        """Measure all contrast density metrics for given text."""
        if not text or not text.strip():
            return {
                "adversative_conjunction_rate": 0.0,
                "antithesis_rate": 0.0,
                "reversal_rate": 0.0,
                "concession_rate": 0.0,
                "opposition_density": 0.0,
                "contrast_density_index": 0.0,
                "classification": "contrast_free",
            }

        adversative = self.measure_adversative_conjunction_rate(text)
        antithesis = self.measure_antithesis_rate(text)
        reversal = self.measure_reversal_rate(text)
        concession = self.measure_concession_rate(text)
        opposition = self.measure_opposition_density(text)

        index = self.compute_contrast_density_index(
            adversative, antithesis, reversal, concession, opposition
        )
        classification = self.classify(index)

        return {
            "adversative_conjunction_rate": round(adversative, 4),
            "antithesis_rate": round(antithesis, 4),
            "reversal_rate": round(reversal, 4),
            "concession_rate": round(concession, 4),
            "opposition_density": round(opposition, 4),
            "contrast_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    contrast_rich = """
    The theory was elegant, but the data told a different story.
    Although the model predicted smooth convergence, the actual
    results were chaotic. On one hand, the parameters seemed
    well-calibrated; on the other hand, the output diverged
    wildly. Surprisingly, the simplest baseline outperformed
    the complex architecture. It turns out that depth was not
    the answer — breadth mattered more. Rather than adding
    layers, the team found success by widening the hidden
    dimensions. Unlike previous approaches, this one favored
    simplicity over sophistication, and the results spoke for
    themselves: success where there had been failure, clarity
    where there had been confusion.
    """

    contrast_free = """
    The old house stood at the edge of the meadow. Wildflowers
    grew along the stone path leading to the front door. The
    windows were dark, the paint peeling in long strips. A cat
    sat on the porch, watching sparrows in the hedge. The wind
    carried the smell of cut grass and distant rain. Somewhere
    a dog barked, then fell silent.
    """

    wcd = WriterContrastDensity()

    print("=== Contrast-Rich Text ===")
    result = wcd.measure(contrast_rich)
    for key, value in result.items():
        print(f"{key:35s} {value}")

    print("\n=== Contrast-Free Text ===")
    result = wcd.measure(contrast_free)
    for key, value in result.items():
        print(f"{key:35s} {value}")
