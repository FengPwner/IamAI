#!/usr/bin/env python3
"""writer_causal_density — measure the density of causal reasoning in prose.

Causal language is how texts explain *why* things happen.  A text rich
in causal connectors ("because", "therefore", "as a result", "due to",
"consequently") builds chains of reasoning — each event or claim is
linked to its cause or effect.  A text poor in causal language may be
descriptive ("the door opened"), narrative ("she walked in"), or
assertive ("this is true") but leaves the reader to infer the *why*.

Causal density is not a quality metric.  Philosophy and science writing
*must* be causally dense — the entire point is explaining why things
are as they are.  Poetry and flash fiction often avoid it — the power
lies in juxtaposition, not explanation.  Legal writing uses causal
language precisely ("whereas the defendant...").  Marketing copy
sometimes implies causation without stating it ("you'll feel the
difference").

This module measures **how much of a text is spent establishing
cause-and-effect relationships** — explicit causal links, conditional
reasoning, concessive contrasts (which imply expected-but-denied
causation), and purpose clauses (which are forward-looking causation).

Orthogonality to other metrics
-------------------------------

- **formality** tracks register conventions.  Causal connectors appear
  in both formal ("consequently, the hypothesis was rejected") and
  informal registers ("so yeah, that's why I left").  Causal density
  measures *how much* causal reasoning; formality measures *how it's
  dressed*.

- **clarity** tracks structural ambiguity.  A causal claim can be clear
  ("she left because she was angry") or ambiguous ("she was angry, she
  left" — is the second caused by the first?).  Clarity measures parse
  certainty; causal density measures causal frequency.

- **linearity** tracks temporal ordering.  Causal chains often imply
  temporal order (cause before effect) but not always ("the verdict
  was overturned because new evidence emerged" — the evidence emerged
  before the verdict, but the sentence presents effect first).
  Linearity measures presentation order; causal density measures
  reasoning links.

- **conviction** tracks certainty.  Causal claims can be certain
  ("this causes cancer") or hedged ("this may contribute to cancer").
  Conviction measures confidence; causal density measures the
  presence of causal structure regardless of certainty.

- **negation_density** tracks logical inversion.  Causal language
  can include negation ("not because he was lazy, but because he was
  sick") or be purely affirmative ("because he was sick").  Negation
  density measures inversion; causal density measures reasoning.

- **transitions** (if it existed) would track paragraph-to-paragraph
  flow.  Causal connectors *are* transitions, but transitions include
  temporal ("meanwhile"), additive ("furthermore"), and contrastive
  ("however") connectors too.  Causal density specifically measures
  cause-and-effect reasoning.

Dimensions
----------

========================  ==============================================
metric                    meaning
========================  ==============================================
cause_connector_rate      frequency of cause-introducing connectors
                          (because, since, due to, owing to, as a
                          result of, on account of, by virtue of,
                          in light of, given that) per sentence
effect_connector_rate     frequency of effect-introducing connectors
                          (therefore, thus, hence, consequently,
                          accordingly, as a result, for this reason,
                          so, then, it follows that) per sentence
conditional_density       frequency of conditional constructions
                          (if, unless, provided that, in case, as
                          long as, on condition that, supposing,
                          in the event that) per sentence
concessive_density        frequency of concessive connectors that
                          imply denied causation (although, despite,
                          in spite of, nevertheless, nonetheless,
                          even though, while, whereas, albeit,
                          notwithstanding, however) per sentence
purpose_clause_density    frequency of purpose/intent clauses which
                          are forward-looking causation (in order to,
                          so that, so as to, for the purpose of,
                          with the aim of, to this end, with a view
                          to, lest) per sentence
causal_chain_length       average number of causal links within
                          each paragraph — paragraphs with multiple
                          causal connectors form reasoning chains
causal_density_index      composite score (0.0 to 1.0) combining
                          cause_connector_rate (0.22),
                          effect_connector_rate (0.20),
                          conditional_density (0.18),
                          concessive_density (0.13),
                          purpose_clause_density (0.12),
                          and causal_chain_length normalized (0.15)
classification            categorical label based on index value:
                          causally_saturated (>=0.60),
                          causally_rich (>=0.40),
                          moderate_causation (>=0.20),
                          causally_sparse (>=0.10),
                          causally_bare (<0.10)
========================  ==============================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


# ── Connector Lexicons ───────────────────────────────────────────────

# Cause-introducing connectors (sorted longest first for greedy match)
CAUSE_CONNECTORS: List[str] = [
    "for the reason that",
    "considering that",
    "as a result of",
    "on account of",
    "by virtue of",
    "in light of",
    "inasmuch as",
    "seeing that",
    "given that",
    "insofar as",
    "thanks to",
    "what with",
    "owing to",
    "now that",
    "in that",
    "because",
    "due to",
    "since",
    "for",
    "as",
]

# Effect-introducing connectors (sorted longest first for greedy match)
EFFECT_CONNECTORS: List[str] = [
    "as a consequence",
    "for this reason",
    "it follows that",
    "in consequence",
    "consequently",
    "accordingly",
    "as a result",
    "henceforth",
    "thereupon",
    "therefore",
    "hence",
    "thus",
    "ergo",
    "then",
    "so",
]

# Conditional constructions (sorted longest first for greedy match)
CONDITIONAL_MARKERS: List[str] = [
    "in the event that",
    "on condition that",
    "supposing that",
    "provided that",
    "assuming that",
    "as long as",
    "so long as",
    "supposing",
    "assuming",
    "in case",
    "whether",
    "if only",
    "unless",
    "if",
]

# Concessive connectors (sorted longest first for greedy match)
CONCESSIVE_MARKERS: List[str] = [
    "despite the fact that",
    "notwithstanding",
    "nevertheless",
    "in spite of",
    "even though",
    "nonetheless",
    "although",
    "even if",
    "despite",
    "whereas",
    "however",
    "whilst",
    "albeit",
    "though",
    "while",
    "still",
    "yet",
]

# Purpose / intent clause markers (sorted longest first for greedy match)
PURPOSE_MARKERS: List[str] = [
    "with the intention of",
    "for the purpose of",
    "with the goal of",
    "with the aim of",
    "in an effort to",
    "with a view to",
    "in order that",
    "for fear that",
    "in order to",
    "to this end",
    "in a bid to",
    "so as to",
    "so that",
    "lest",
]


# ── Stopwords for content-word extraction ────────────────────────────

STOPWORDS = frozenset({
    "a", "an", "the", "is", "am", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "shall", "should", "may", "might", "must", "can", "could", "i", "me",
    "my", "we", "our", "you", "your", "he", "him", "his", "she", "her",
    "it", "its", "they", "them", "their", "this", "that", "these",
    "those", "and", "or", "but", "nor", "not", "no", "so", "yet",
    "both", "either", "neither", "each", "every", "all", "any", "few",
    "more", "most", "other", "some", "such", "than", "too", "very",
    "just", "about", "above", "after", "again", "also", "as", "at",
    "be", "because", "before", "below", "between", "by", "during",
    "for", "from", "if", "in", "into", "of", "off", "on", "once",
    "only", "out", "over", "own", "same", "since", "through", "to",
    "under", "until", "up", "when", "where", "while", "with",
})


def _tokenize(text: str) -> List[str]:
    """Lowercase and split text into word tokens."""
    return re.findall(r"[a-z']+", text.lower())


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on '.', '?', '!' followed by space or EOL."""
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in raw if s.strip()]


def _split_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs on one or more blank lines."""
    raw = re.split(r'\n\s*\n', text.strip())
    return [p.strip() for p in raw if p.strip()]


def _count_phrase_occurrences(text_lower: str, phrases: List[str]) -> int:
    """Count non-overlapping occurrences of phrases in lowercased text.

    Longer phrases are matched first (greedy longest-match) to avoid
    double-counting "as a result of" as both "as a result" and "as".
    """
    count = 0
    # Sort by length descending for greedy longest-match
    sorted_phrases = sorted(phrases, key=len, reverse=True)
    # Use a mutable copy to mask matched regions
    working = text_lower
    for phrase in sorted_phrases:
        # Use word boundary-aware matching
        pattern = r'\b' + re.escape(phrase) + r'\b'
        matches = list(re.finditer(pattern, working))
        count += len(matches)
        # Mask matched regions to prevent double-counting
        for m in reversed(matches):
            working = working[:m.start()] + ' ' * (m.end() - m.start()) + working[m.end():]
    return count


class WriterCausalDensity:
    """Measure the density of causal reasoning in prose."""

    def __init__(self):
        self.cause_connectors = CAUSE_CONNECTORS
        self.effect_connectors = EFFECT_CONNECTORS
        self.conditional_markers = CONDITIONAL_MARKERS
        self.concessive_markers = CONCESSIVE_MARKERS
        self.purpose_markers = PURPOSE_MARKERS
        self.stopwords = STOPWORDS

    # ── Helpers ──────────────────────────────────────────────────

    def _split_sentences(self, text: str) -> List[str]:
        return _split_sentences(text)

    def _split_paragraphs(self, text: str) -> List[str]:
        return _split_paragraphs(text)

    def _tokenize(self, text: str) -> List[str]:
        return _tokenize(text)

    # ── Dimension 1: Cause Connector Rate ────────────────────────

    def measure_cause_connector_rate(self, text: str) -> float:
        """Count cause-introducing connectors per sentence.

        Examples: "because", "since", "due to", "owing to",
        "as a result of", "on account of", "given that".
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        total = 0
        for sent in sentences:
            total += _count_phrase_occurrences(sent.lower(), self.cause_connectors)

        return total / len(sentences)

    # ── Dimension 2: Effect Connector Rate ───────────────────────

    def measure_effect_connector_rate(self, text: str) -> float:
        """Count effect-introducing connectors per sentence.

        Examples: "therefore", "thus", "hence", "consequently",
        "as a result", "accordingly", "so".
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        total = 0
        for sent in sentences:
            total += _count_phrase_occurrences(sent.lower(), self.effect_connectors)

        return total / len(sentences)

    # ── Dimension 3: Conditional Density ─────────────────────────

    def measure_conditional_density(self, text: str) -> float:
        """Count conditional constructions per sentence.

        Examples: "if", "unless", "provided that", "in case",
        "as long as", "supposing".
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        total = 0
        for sent in sentences:
            total += _count_phrase_occurrences(sent.lower(), self.conditional_markers)

        return total / len(sentences)

    # ── Dimension 4: Concessive Density ──────────────────────────

    def measure_concessive_density(self, text: str) -> float:
        """Count concessive connectors per sentence.

        Concessive markers imply expected-but-denied causation:
        "although", "despite", "nevertheless", "however", "yet".
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        total = 0
        for sent in sentences:
            total += _count_phrase_occurrences(sent.lower(), self.concessive_markers)

        return total / len(sentences)

    # ── Dimension 5: Purpose Clause Density ──────────────────────

    def measure_purpose_clause_density(self, text: str) -> float:
        """Count purpose/intent clauses per sentence.

        Purpose clauses are forward-looking causation: "in order to",
        "so that", "for the purpose of", "with the aim of".
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        total = 0
        for sent in sentences:
            total += _count_phrase_occurrences(sent.lower(), self.purpose_markers)

        return total / len(sentences)

    # ── Dimension 6: Causal Chain Length ─────────────────────────

    def measure_causal_chain_length(self, text: str) -> float:
        """Average number of causal links per paragraph.

        A causal chain is formed when a paragraph contains multiple
        causal connectors (any type), forming a reasoning sequence.
        Paragraphs with zero or one connector have chain length equal
        to that count.
        """
        paragraphs = self._split_paragraphs(text)
        if not paragraphs:
            return 0.0

        all_connectors = (
            self.cause_connectors
            + self.effect_connectors
            + self.conditional_markers
            + self.concessive_markers
            + self.purpose_markers
        )

        chain_lengths = []
        for para in paragraphs:
            count = _count_phrase_occurrences(para.lower(), all_connectors)
            chain_lengths.append(count)

        return sum(chain_lengths) / len(chain_lengths)

    # ── Composite Score ──────────────────────────────────────────

    def compute_causal_density_index(
        self,
        cause_rate: float,
        effect_rate: float,
        conditional: float,
        concessive: float,
        purpose: float,
        chain_length: float,
    ) -> float:
        """Compute weighted composite causal density score (0.0 to 1.0)."""
        # Normalize cause_rate: typical range 0-2 per sentence
        norm_cause = min(cause_rate / 1.5, 1.0)
        # Normalize effect_rate: typical range 0-1.5 per sentence
        norm_effect = min(effect_rate / 1.2, 1.0)
        # Normalize conditional: typical range 0-1.5 per sentence
        norm_conditional = min(conditional / 1.2, 1.0)
        # Normalize concessive: typical range 0-1 per sentence
        norm_concessive = min(concessive / 1.0, 1.0)
        # Normalize purpose: typical range 0-0.8 per sentence
        norm_purpose = min(purpose / 0.8, 1.0)
        # Normalize chain_length: typical range 0-5 per paragraph
        norm_chain = min(chain_length / 4.0, 1.0)

        return (
            norm_cause * 0.22
            + norm_effect * 0.20
            + norm_conditional * 0.18
            + norm_concessive * 0.13
            + norm_purpose * 0.12
            + norm_chain * 0.15
        )

    def classify(self, index: float) -> str:
        """Classify causal density level."""
        if index >= 0.60:
            return "causally_saturated"
        elif index >= 0.40:
            return "causally_rich"
        elif index >= 0.20:
            return "moderate_causation"
        elif index >= 0.10:
            return "causally_sparse"
        else:
            return "causally_bare"

    # ── Main Entry Point ─────────────────────────────────────────

    def measure(self, text: str) -> Dict[str, Any]:
        """Measure all causal density metrics for given text."""
        if not text or not text.strip():
            return {
                "cause_connector_rate": 0.0,
                "effect_connector_rate": 0.0,
                "conditional_density": 0.0,
                "concessive_density": 0.0,
                "purpose_clause_density": 0.0,
                "causal_chain_length": 0.0,
                "causal_density_index": 0.0,
                "classification": "causally_bare",
            }

        cause = self.measure_cause_connector_rate(text)
        effect = self.measure_effect_connector_rate(text)
        conditional = self.measure_conditional_density(text)
        concessive = self.measure_concessive_density(text)
        purpose = self.measure_purpose_clause_density(text)
        chain = self.measure_causal_chain_length(text)

        index = self.compute_causal_density_index(
            cause, effect, conditional, concessive, purpose, chain
        )
        classification = self.classify(index)

        return {
            "cause_connector_rate": round(cause, 4),
            "effect_connector_rate": round(effect, 4),
            "conditional_density": round(conditional, 4),
            "concessive_density": round(concessive, 4),
            "purpose_clause_density": round(purpose, 4),
            "causal_chain_length": round(chain, 4),
            "causal_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    causally_rich = """
    The experiment failed because the temperature exceeded the
    threshold specified in the protocol. Consequently, the enzyme
    denatured before the reaction could reach equilibrium. Since
    the substrate was already partially degraded, the yield was
    lower than expected. Therefore, the team decided to repeat
    the trial under controlled conditions, in order to isolate
    the temperature variable. Although the initial results were
    disappointing, they provided valuable data for the next round.

    If the new trial succeeds, the hypothesis will be confirmed.
    Unless the contamination issue is resolved, however, the
    results may remain inconclusive. Given that the deadline
    approaches, the team must work efficiently so that the
    report can be submitted on time.
    """

    causally_sparse = """
    The old house stood at the edge of the meadow. Wildflowers
    grew along the stone path leading to the front door. The
    windows were dark, the paint peeling in long strips. A cat
    sat on the porch, watching sparrows in the hedge. The wind
    carried the smell of cut grass and distant rain. Somewhere
    a dog barked, then fell silent.
    """

    wcd = WriterCausalDensity()

    print("=== Causally Rich Text ===")
    result = wcd.measure(causally_rich)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Causally Sparse Text ===")
    result = wcd.measure(causally_sparse)
    for key, value in result.items():
        print(f"{key:30s} {value}")
