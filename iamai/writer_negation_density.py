#!/usr/bin/env python3
"""writer_negation_density — measure the density and patterns of negation.

Negation is one of the most fundamental operations in human language.
It inverts truth values, denies claims, refuses actions, and marks
absence.  A text saturated with negation ("not", "never", "nothing",
"no one", "neither", "cannot") reads as defensive, pessimistic, or
corrective — it spends more energy saying what *isn't* than what *is*.
A text with almost no negation reads as affirmative, confident, or
naive — it asserts without denial.

The density of negation is not a value judgment.  Legal writing *must*
negate ("the licensee shall not...").  Philosophical inquiry often
proceeds by negation ("the good is not pleasure").  Marketing copy
avoids it ("refreshing!" not "not boring!").  The metric exists so
the writer can *see* how much of their text lives in denial mode —
not to minimize it, but to make the choice conscious.

This module is orthogonal to the other writer metrics:

- **formality** tracks *register conventions*.  Negation appears in
  both formal ("the defendant did not commit the alleged act") and
  informal ("he didn't do it") registers.  Negation density measures
  *how much* negation exists, not what register it uses.

- **clarity** tracks *structural ambiguity*.  Negation can be clear
  ("she did not go") or ambiguous ("I didn't say she stole my money"
  — which word does "not" scope over?).  Clarity measures parse
  certainty; negation density measures negation frequency.

- **concreteness** tracks *sensory grounding*.  Negation can apply to
  concrete things ("the door was not open") or abstractions ("justice
  is not blind").  Concreteness measures *what kind of language*;
  negation density measures *how much denial*.

- **dialog_density** tracks *quoted speech vs narrative*.  Dialog can
  contain negation ("I don't think so") or be purely affirmative
  ("yes, absolutely").  Dialog density measures structural mode;
  negation density measures logical polarity.

- **conviction** tracks *certainty of claims*.  Negation can express
  strong conviction ("this will never work") or weak hedging ("it's
  not exactly clear").  Conviction measures confidence; negation
  density measures inversion frequency.

- **sentiment** (if it existed) would track *emotional valence*.
  Negation inverts sentiment ("not good" = bad) but is not itself
  negative emotion.  "I never get sick" is negation with positive
  implication.  Negation density measures *logical structure*, not
  emotional tone.

Negation density asks: **how much of this text is spent saying
what is *not*, rather than what *is*?**

Dimensions
----------

========================  ==============================================
metric                    meaning
========================  ==============================================
clausal_negation_rate     frequency of clausal negators (not, n't,
                          never, neither, nor) per sentence
constituent_negation_rate frequency of negative quantifiers and
                          pronouns (no, none, nothing, nobody, nowhere,
                          no-one, not-a-single) per sentence
affixal_negation_rate     frequency of morphological negation via
                          prefixes (un-, in-, im-, ir-, il-, dis-,
                          non-, de-, anti-, counter-, mis-) per
                          content word
double_negation_count     number of double negation constructions
                          ("not uncommon", "never nothing", "can't
                          not", "not unlikely") per 1000 words
negation_scope_depth      average nesting depth of negation in
                          sentences — single negation is depth 1,
                          double negation is depth 2, no negation
                          is depth 0
negation_cluster_ratio    fraction of negation tokens that appear
                          within 5 tokens of another negation;
                          high values indicate clustered negation
                          ("it was not merely not helpful but not
                          even relevant")
negation_density_index    composite score (0.0 to 1.0) combining
                          clausal_negation_rate (0.30),
                          constituent_negation_rate (0.15),
                          affixal_negation_rate (0.15),
                          double_negation_count normalized (0.10),
                          negation_scope_depth normalized (0.15),
                          and negation_cluster_ratio (0.15)
classification            categorical label based on index value:
                          negation_saturated (>=0.60),
                          negation_heavy (>=0.40),
                          moderate_negation (>=0.20),
                          affirmative (>=0.10),
                          strongly_affirmative (<0.10)
========================  ==============================================
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple


# ── Clausal negators ─────────────────────────────────────────────────
CLAUSAL_NEGATORS: frozenset = frozenset({
    "not", "never", "neither", "nor", "n't",
    "nope", "nah", "nay",
})

# ── Contractions containing negation ─────────────────────────────────
NEGATION_CONTRACTIONS: frozenset = frozenset({
    "don't", "doesn't", "didn't", "isn't", "aren't", "wasn't",
    "weren't", "won't", "wouldn't", "shouldn't", "couldn't",
    "can't", "cannot", "haven't", "hasn't", "hadn't", "mustn't",
    "needn't", "shan't",
})

# ── Negative quantifiers and pronouns ────────────────────────────────
NEGATIVE_QUANTIFIERS: frozenset = frozenset({
    "no", "none", "nothing", "nobody", "no-one", "no_one",
    "nowhere", "neither",
})

# ── Negative affixes (prefixes) ──────────────────────────────────────
NEGATION_PREFIXES: Tuple[str, ...] = (
    "un", "in", "im", "ir", "il", "dis", "non", "de",
    "anti", "counter", "mis", "a",  # a- as in "atypical", "amoral"
)

# ── Common words that are NOT negation despite looking like it ────────
FALSE_POSITIVES: frozenset = frozenset({
    # "no" as quantifier vs exclamation — context disambiguated below
    "note", "notes", "noted", "notice", "nothing",  # nothing is real
    "nobody", "nowhere",  # these are real negatives
    "none",  # real negative
    "knot", "knots", "know", "knows", "known", "knowledge",
    "noble", "notable", "notably", "notation",
    "noon", "noodle", "nonsense",  # nonsense is borderline; excluded
    "normal", "normally",
    "into", "inner", "income", "indeed", "indoor", "index",
    "indicate", "industry", "individual", "inside",
    "imagine", "image", "improve", "immediate", "important",
    "impact", "implement", "imply", "import",
    "iron", "irony", "irrigate", "irritate", "irregular",
    "illegal", "illustrate",
    "discover", "disease", "discuss", "dismiss", "display",
    "distance", "distinct", "distribute", "district",
    "antique", "anticipate",
    "country", "counter", "count",
    "mistake", "miss", "mission", "mister", "misery",
    "about", "above", "again", "along", "already", "also",
    "amount",
    # common words with in-/im-/un-/dis- that are NOT negation
    "improve", "improves", "improved", "improvement", "improvements",
    "infrastructure", "information", "influence", "inform", "instance",
    "interest", "internet", "introduce", "investigate", "invite",
    "increase", "include", "incredible",
    "under", "understand", "until", "unless", "upon", "upper",
    "universe", "university", "uniform", "unique", "unit", "unite",
    "discuss", "display", "distance", "distribute", "district",
    "different", "difficult", "describe", "design", "desire",
    "approved", "approval", "approve", "approach", "appropriate",
    "unanimous", "unanimously",
    "arrange", "arrive", "attempt", "attend", "attract", "attack",
})

# ── Words with negative prefixes that ARE genuinely negated ──────────
TRUE_NEGATED_WORDS: frozenset = frozenset({
    "unhappy", "unusual", "unlikely", "unable", "unfair", "unclear",
    "uncommon", "uncomfortable", "uncertain", "unconscious",
    "undeniable", "undoubted", "unequal", "unexpected", "unfamiliar",
    "unfortunate", "unfriendly", "unhealthy", "unimportant", "unknown",
    "unnecessary", "unpleasant", "unreasonable", "unsafe", "unstable",
    "unsuccessful", "untrue", "unusual", "unwilling", "unwise",
    "incorrect", "incomplete", "inconsistent", "inconvenient",
    "incredible", "independent", "indirect", "ineffective",
    "inevitable", "inexpensive", "infinite", "invisible",
    "impossible", "impatient", "imperfect", "impolite", "improper",
    "irrelevant", "irresponsible", "irresistible", "irregular",
    "illogical", "illegal", "illiterate", "illegitimate",
    "disagree", "disappear", "disappoint", "disapprove", "disbelief",
    "discomfort", "disconnect", "discourage", "dishonest", "dislike",
    "disorder", "displace", "displease", "disrespect", "dissatisfy",
    "nonexistent", "nonprofit", "nonsense", "nonviolent", "nonverbal",
    "nonstop", "nonpartisan", "nonfiction",
    "deactivate", "decrease", "deflate", "degrade", "demote",
    "depress", "devalue", "decentralize", "decode", "defrost",
    "antibiotic", "antisocial", "antitrust",
    "counterattack", "counterbalance", "counterclaim", "counterfeit",
    "misbehave", "miscalculate", "misconduct", "misinform",
    "mislead", "misplace", "misread", "misspell", "misunderstand",
    "atypical", "amoral", "asymmetric", "asocial",
})

# ── Function words for content-word filtering ────────────────────────
FUNCTION_WORDS: frozenset = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "shall", "should", "may", "might", "must", "can",
    "could", "am", "i", "you", "he", "she", "it", "we", "they",
    "me", "him", "her", "us", "them", "my", "your", "his", "its",
    "our", "their", "this", "that", "these", "those", "and", "but",
    "or", "nor", "for", "yet", "so", "in", "on", "at", "to",
    "from", "by", "with", "of", "about", "into", "through",
    "during", "before", "after", "above", "below", "between",
    "under", "over", "if", "then", "than", "as",
})


class WriterNegationDensity:
    """Analyze negation density and patterns in prose text."""

    def __init__(self) -> None:
        self.clausal_negators = CLAUSAL_NEGATORS
        self.negation_contractions = NEGATION_CONTRACTIONS
        self.negative_quantifiers = NEGATIVE_QUANTIFIERS
        self.negation_prefixes = NEGATION_PREFIXES
        self.false_positives = FALSE_POSITIVES
        self.true_negated_words = TRUE_NEGATED_WORDS
        self.function_words = FUNCTION_WORDS
        # Compile regex patterns once
        self._sentence_re = re.compile(r'(?<=[.!?])\s+')
        self._word_re = re.compile(r"[a-zA-Z']+")
        self._contraction_re = re.compile(
            r"\b(?:don't|doesn't|didn't|isn't|aren't|wasn't|weren't|"
            r"won't|wouldn't|shouldn't|couldn't|can't|cannot|"
            r"haven't|hasn't|hadn't|mustn't|needn't|shan't)\b",
            re.IGNORECASE,
        )
        self._double_neg_re = re.compile(
            r"(?:not\s+(?:\w+\s+){0,3}(?:un|in|im|ir|il|dis|non)\w+|"
            r"never\s+(?:\w+\s+){0,3}(?:un|in|im|ir|il|dis|non)\w+|"
            r"(?:don't|doesn't|didn't|isn't|aren't|wasn't|weren't|"
            r"won't|wouldn't|shouldn't|couldn't|can't|cannot)\s+"
            r"(?:\w+\s+){0,3}(?:un|in|im|ir|il|dis|non)\w+|"
            r"not\s+(?:\w+\s+){0,2}(?:un|in|im|ir|il|dis|non)\w+|"
            r"(?:not|never|don't|doesn't|didn't|isn't|aren't|wasn't|"
            r"weren't|won't|wouldn't|shouldn't|couldn't|can't|cannot)"
            r"\s+(?:\w+\s+){0,3}"
            r"(?:nothing|nobody|nowhere|none|neither))",
            re.IGNORECASE,
        )

    # ── Helpers ──────────────────────────────────────────────────────

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        if not text or not text.strip():
            return []
        parts = self._sentence_re.split(text.strip())
        return [p.strip() for p in parts if p.strip()]

    def _tokenize(self, text: str) -> List[str]:
        """Extract lowercase word tokens."""
        return self._word_re.findall(text.lower())

    def _content_words(self, text: str) -> List[str]:
        """Extract content words (excluding function words)."""
        tokens = self._tokenize(text)
        return [t for t in tokens if t not in self.function_words]

    def _is_genuine_negated_word(self, word: str) -> bool:
        """Check if a word with a negative prefix is genuinely negated.

        Many words start with 'in-' or 'un-' but are not negations
        ('industry', 'under', 'into'). This method checks against
        known true negated forms and applies heuristic prefix stripping.
        """
        word_lower = word.lower()

        # Check known true negated words first
        if word_lower in self.true_negated_words:
            return True

        # Check known false positives
        if word_lower in self.false_positives:
            return False

        # Heuristic: if the word minus the prefix is a common English
        # word, it's likely a genuine negation
        for prefix in sorted(self.negation_prefixes, key=len, reverse=True):
            if word_lower.startswith(prefix) and len(word_lower) > len(prefix) + 2:
                stem = word_lower[len(prefix):]
                # Very short stems are suspicious (e.g., "in-it")
                if len(stem) >= 3:
                    return True

        return False

    # ── Measurement methods ──────────────────────────────────────────

    def measure_clausal_negation_rate(self, text: str) -> float:
        """Count of clausal negators per sentence.

        Includes: not, n't, never, neither, nor, and contractions
        containing negation (don't, can't, etc.)
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        total_negators = 0
        for sentence in sentences:
            tokens = self._tokenize(sentence)
            # Count explicit negators
            for token in tokens:
                if token in self.clausal_negators:
                    total_negators += 1
            # Count negation contractions
            contractions = self._contraction_re.findall(sentence)
            total_negators += len(contractions)
            # "cannot" as one word
            if "cannot" in sentence.lower():
                # Avoid double-counting if already caught by contraction re
                if not self._contraction_re.search("cannot"):
                    total_negators += 1

        return total_negators / len(sentences)

    def measure_constituent_negation_rate(self, text: str) -> float:
        """Count of negative quantifiers/pronouns per sentence.

        Includes: no, none, nothing, nobody, nowhere, no-one
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        total = 0
        for sentence in sentences:
            tokens = self._tokenize(sentence)
            for token in tokens:
                if token in self.negative_quantifiers:
                    # Disambiguate "no" — it's a negative quantifier
                    # when followed by a noun, but we count all instances
                    # since "no" alone is almost always negation
                    total += 1

        return total / len(sentences)

    def measure_affixal_negation_rate(self, text: str) -> float:
        """Fraction of content words with negative prefixes."""
        content = self._content_words(text)
        if not content:
            return 0.0

        negated_count = sum(
            1 for word in content if self._is_genuine_negated_word(word)
        )
        return negated_count / len(content)

    def measure_double_negation_count(self, text: str) -> float:
        """Count of double negation constructions per 1000 words."""
        tokens = self._tokenize(text)
        if not tokens:
            return 0.0

        double_negs = self._double_neg_re.findall(text)
        return (len(double_negs) / len(tokens)) * 1000.0

    def measure_negation_scope_depth(self, text: str) -> float:
        """Average negation depth per sentence.

        Depth 0 = no negation in sentence
        Depth 1 = single negation
        Depth 2 = double negation or two independent negations
        Depth 3+ = nested or clustered negation
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        depths = []
        for sentence in sentences:
            depth = 0
            tokens = self._tokenize(sentence)

            # Count clausal negators
            for token in tokens:
                if token in self.clausal_negators:
                    depth += 1
                if token in self.negative_quantifiers:
                    depth += 1

            # Count contractions
            contractions = self._contraction_re.findall(sentence)
            depth += len(contractions)

            # Count affixal negation (each negated word adds to scope)
            content = [t for t in tokens if t not in self.function_words]
            for word in content:
                if self._is_genuine_negated_word(word):
                    depth += 1

            depths.append(depth)

        if not depths:
            return 0.0
        return sum(depths) / len(depths)

    def measure_negation_cluster_ratio(self, text: str) -> float:
        """Fraction of negation tokens within 5 tokens of another.

        High values indicate clustered negation (multiple negations
        close together), which often signals defensive or corrective
        writing.
        """
        tokens = self._tokenize(text)
        if not tokens:
            return 0.0

        # Find all negation positions
        neg_positions: List[int] = []
        for i, token in enumerate(tokens):
            if (token in self.clausal_negators
                    or token in self.negative_quantifiers
                    or token in self.negation_contractions):
                neg_positions.append(i)
            elif self._is_genuine_negated_word(token):
                neg_positions.append(i)

        if len(neg_positions) <= 1:
            return 0.0

        # Check which negation tokens are clustered
        clustered = 0
        for pos in neg_positions:
            for other_pos in neg_positions:
                if other_pos != pos and abs(other_pos - pos) <= 5:
                    clustered += 1
                    break

        return clustered / len(neg_positions)

    def compute_negation_density_index(
        self,
        clausal_rate: float,
        constituent_rate: float,
        affixal_rate: float,
        double_neg_count: float,
        scope_depth: float,
        cluster_ratio: float,
    ) -> float:
        """Compute weighted composite negation density score."""
        # Normalize clausal_rate: typical range 0-2 per sentence
        norm_clausal = min(clausal_rate / 1.5, 1.0)
        # Normalize constituent_rate: typical range 0-1 per sentence
        norm_constituent = min(constituent_rate / 0.8, 1.0)
        # affixal_rate is already 0-1
        norm_affixal = min(affixal_rate / 0.3, 1.0)
        # Normalize double_neg: typical range 0-10 per 1000 words
        norm_double = min(double_neg_count / 5.0, 1.0)
        # Normalize scope_depth: typical range 0-4
        norm_depth = min(scope_depth / 3.0, 1.0)
        # cluster_ratio is already 0-1

        return (
            norm_clausal * 0.30
            + norm_constituent * 0.15
            + norm_affixal * 0.15
            + norm_double * 0.10
            + norm_depth * 0.15
            + cluster_ratio * 0.15
        )

    def classify(self, index: float) -> str:
        """Classify negation density level."""
        if index >= 0.60:
            return "negation_saturated"
        elif index >= 0.40:
            return "negation_heavy"
        elif index >= 0.20:
            return "moderate_negation"
        elif index >= 0.10:
            return "affirmative"
        else:
            return "strongly_affirmative"

    def measure(self, text: str) -> Dict:
        """Measure all negation density metrics for given text."""
        if not text or not text.strip():
            return {
                "clausal_negation_rate": 0.0,
                "constituent_negation_rate": 0.0,
                "affixal_negation_rate": 0.0,
                "double_negation_count": 0.0,
                "negation_scope_depth": 0.0,
                "negation_cluster_ratio": 0.0,
                "negation_density_index": 0.0,
                "classification": "strongly_affirmative",
            }

        clausal = self.measure_clausal_negation_rate(text)
        constituent = self.measure_constituent_negation_rate(text)
        affixal = self.measure_affixal_negation_rate(text)
        double_neg = self.measure_double_negation_count(text)
        scope_depth = self.measure_negation_scope_depth(text)
        cluster = self.measure_negation_cluster_ratio(text)

        index = self.compute_negation_density_index(
            clausal, constituent, affixal, double_neg, scope_depth, cluster
        )
        classification = self.classify(index)

        return {
            "clausal_negation_rate": round(clausal, 4),
            "constituent_negation_rate": round(constituent, 4),
            "affixal_negation_rate": round(affixal, 4),
            "double_negation_count": round(double_neg, 4),
            "negation_scope_depth": round(scope_depth, 4),
            "negation_cluster_ratio": round(cluster, 4),
            "negation_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    negation_heavy = """
    It was not uncommon for the committee to reject proposals that
    were not clearly aligned with the organization's goals. The
    chairman did not disagree with the need for change, but he
    was unwilling to approve any plan that did not include a
    detailed risk assessment. Nothing was certain. Nobody could
    guarantee success. The board would neither endorse nor reject
    the proposal without further review.
    """

    affirmative = """
    The sun rose over the mountains, painting the valley in gold.
    Birds sang from the treetops. The river flowed steadily toward
    the sea, carrying leaves and small branches. Children played
    in the meadow, chasing butterflies and laughing. The farmer
    tended his crops, satisfied with the season's progress.
    Everything was exactly as it should be.
    """

    wnd = WriterNegationDensity()

    print("=== Negation-Heavy Text ===")
    result = wnd.measure(negation_heavy)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Affirmative Text ===")
    result = wnd.measure(affirmative)
    for key, value in result.items():
        print(f"{key:30s} {value}")
