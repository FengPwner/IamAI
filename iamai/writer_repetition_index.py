#!/usr/bin/env python3
"""writer_repetition_index — measure lexical and structural repetition.

Repetition is the skeleton of both poetry and tedium.  A sentence that
repeats the same words, the same structures, the same rhythms becomes
hypnotic — sometimes by design (anaphora in rhetoric, refrain in verse),
sometimes by accident (a writer who keeps starting sentences with "he
walked… he walked… he walked…").

The repetition index measures **how much a text echoes itself**.  It
looks at several independent dimensions:

- Do the same *words* recur more often than chance would predict?
  (type-token ratio, content-word reuse rate)
- Do the same *bigrams and trigrams* repeat?  (phrase-level echo)
- Do consecutive sentences share the same *opening structure*?
  (syntactic parallelism)
- Do consecutive sentences have similar *length*?  (rhythmic monotony)
- Does the text reuse the same *sentence templates* when abstracted
  to POS-like patterns?  (structural repetition)

These dimensions are independent of the existing metrics:

- **formality** tracks register conventions.  Repetition appears in
  both formal ("the committee shall… the committee shall…") and
  informal ("I said… I said…") registers.

- **clarity** tracks parse ambiguity.  Repetition can be clear
  (rhetorical anaphora) or muddy (accidental word echoes).

- **concreteness** tracks sensory grounding.  Repetition can apply
  to concrete things ("the stone, the stone, always the stone") or
  abstractions ("freedom, freedom, freedom").

- **dialog_density** tracks quoted speech.  Dialog can contain
  repetition ("yes, yes, yes") or avoid it entirely.

- **negation_density** tracks logical inversion.  Repetition can
  amplify negation ("never, never, never") or affirm anything.

- **sensory_density** tracks perceptual language.  Repetition can
  layer sensory detail or flatten it.

Repetition index asks: **does this text echo itself, and if so,
is the echo rhythmic (intentional) or monotonous (accidental)?**

Dimensions
----------

========================  ==============================================
metric                    meaning
========================  ==============================================
type_token_ratio          ratio of unique content words to total
                          content words; higher = less repetition
                          at the word level
content_word_reuse_rate   fraction of content words that appear
                          more than once; higher = more word-level
                          echo
bigram_repeat_rate        fraction of word bigrams that appear
                          more than once (excluding stopword-only
                          bigrams like "in the")
trigram_repeat_rate       fraction of word trigrams that appear
                          more than once
sentence_opening_diversity
                          ratio of unique sentence-opening words
                          (first content word) to total sentences;
                          lower = more parallel openings
sentence_length_cv        coefficient of variation (std/mean) of
                          sentence lengths in words; lower = more
                          rhythmic uniformity
structural_template_diversity
                          ratio of unique sentence templates
                          (length-bucketed word-count categories)
                          to total sentences; lower = more
                          structural repetition
anaphora_rate             fraction of consecutive sentence pairs
                          that share the same opening word or
                          bigram — a deliberate rhetorical device
repetition_index          composite score (0.0 = no repetition,
                          1.0 = extreme repetition) combining
                          1 - type_token_ratio (0.20),
                          content_word_reuse_rate (0.15),
                          bigram_repeat_rate (0.15),
                          trigram_repeat_rate (0.10),
                          1 - sentence_opening_diversity (0.15),
                          1 - normalized sentence_length_cv (0.10),
                          1 - structural_template_diversity (0.15)
classification            categorical label:
                          highly_repetitive (>=0.65),
                          moderately_repetitive (>=0.45),
                          balanced (>=0.30),
                          varied (>=0.15),
                          highly_varied (<0.15)
========================  ==============================================
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Tuple


# ── Stop words (for filtering) ───────────────────────────────────────
STOP_WORDS: frozenset = frozenset({
    "a", "an", "the", "and", "or", "but", "nor", "for", "yet", "so",
    "in", "on", "at", "to", "of", "by", "up", "as", "is", "am", "be",
    "do", "if", "it", "he", "we", "my", "me", "us", "no", "oh", "oh",
    "was", "has", "had", "did", "its", "his", "her", "our", "his",
    "i", "you", "she", "they", "them", "this", "that", "these",
    "those", "with", "from", "into", "out", "over", "under", "about",
    "above", "below", "between", "through", "during", "before", "after",
    "which", "who", "whom", "whose", "what", "where", "when", "how",
    "than", "then", "there", "here", "were", "been", "being", "are",
    "not", "no", "nor", "too", "very", "just", "also", "still",
    "will", "would", "could", "should", "may", "might", "shall",
    "can", "must", "have", "had", "has", "does", "did",
})

# Sentence-splitting pattern
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Word tokenization (alphabetic + apostrophe for contractions)
_WORD_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)?")


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on . ! ? followed by whitespace."""
    if not text or not text.strip():
        return []
    return [s.strip() for s in _SENT_SPLIT.split(text.strip()) if s.strip()]


def _tokenize(sentence: str) -> List[str]:
    """Lowercase tokenization, keeping contractions."""
    return [w.lower() for w in _WORD_RE.findall(sentence)]


def _content_words(tokens: List[str]) -> List[str]:
    """Filter out stop words and very short tokens."""
    return [w for w in tokens if w not in STOP_WORDS and len(w) > 1]


class WriterRepetitionIndex:
    """Measure lexical and structural repetition in prose."""

    def __init__(self):
        self.stop_words = STOP_WORDS

    # ── Sentence helpers ─────────────────────────────────────────

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        return _split_sentences(text)

    @staticmethod
    def _tokenize(sentence: str) -> List[str]:
        return _tokenize(sentence)

    @staticmethod
    def _content_words(tokens: List[str]) -> List[str]:
        return _content_words(tokens)

    # ── Core metrics ─────────────────────────────────────────────

    def type_token_ratio(self, text: str) -> float:
        """Ratio of unique content words to total content words.

        Returns 1.0 for text where every content word is unique
        (maximum diversity), approaches 0.0 for highly repetitive text.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 1.0

        all_content: List[str] = []
        for s in sentences:
            all_content.extend(self._content_words(self._tokenize(s)))

        if len(all_content) <= 1:
            return 1.0

        unique = len(set(all_content))
        return unique / len(all_content)

    def content_word_reuse_rate(self, text: str) -> float:
        """Fraction of content words that appear more than once.

        Returns 0.0 when no content word is reused, approaches 1.0
        when almost every content word appears multiple times.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        all_content: List[str] = []
        for s in sentences:
            all_content.extend(self._content_words(self._tokenize(s)))

        if not all_content:
            return 0.0

        counts = Counter(all_content)
        reused = sum(1 for w in counts if counts[w] > 1)
        return reused / len(counts)

    def bigram_repeat_rate(self, text: str) -> float:
        """Fraction of word bigrams that appear more than once.

        Excludes bigrams composed entirely of stop words (e.g.
        "in the", "of a").  Returns 0.0 when no bigram repeats.
        """
        sentences = self._split_sentences(text)
        all_tokens: List[str] = []
        for s in sentences:
            all_tokens.extend(self._tokenize(s))

        if len(all_tokens) < 2:
            return 0.0

        bigrams: List[Tuple[str, str]] = []
        for i in range(len(all_tokens) - 1):
            a, b = all_tokens[i], all_tokens[i + 1]
            # skip stopword-only bigrams
            if a in self.stop_words and b in self.stop_words:
                continue
            bigrams.append((a, b))

        if not bigrams:
            return 0.0

        counts = Counter(bigrams)
        unique = len(counts)
        reused = sum(1 for bg in counts if counts[bg] > 1)
        return reused / unique

    def trigram_repeat_rate(self, text: str) -> float:
        """Fraction of word trigrams that appear more than once.

        Excludes trigrams composed entirely of stop words.
        Returns 0.0 when no trigram repeats.
        """
        sentences = self._split_sentences(text)
        all_tokens: List[str] = []
        for s in sentences:
            all_tokens.extend(self._tokenize(s))

        if len(all_tokens) < 3:
            return 0.0

        trigrams: List[Tuple[str, str, str]] = []
        for i in range(len(all_tokens) - 2):
            a, b, c = all_tokens[i], all_tokens[i + 1], all_tokens[i + 2]
            if a in self.stop_words and b in self.stop_words and c in self.stop_words:
                continue
            trigrams.append((a, b, c))

        if not trigrams:
            return 0.0

        counts = Counter(trigrams)
        unique = len(counts)
        reused = sum(1 for tg in counts if counts[tg] > 1)
        return reused / unique

    def sentence_opening_diversity(self, text: str) -> float:
        """Ratio of unique sentence-opening words to total sentences.

        The "opening word" is the first token of each sentence
        (lowercased).  This captures structural parallelism —
        sentences that start with the same word ("She walked.
        She talked.  She listened.") have low diversity even if
        "she" is a function word.

        Returns 1.0 when every sentence opens with a different
        word, lower values for parallel openings.
        """
        sentences = self._split_sentences(text)
        if len(sentences) <= 1:
            return 1.0

        openings: List[str] = []
        for s in sentences:
            tokens = self._tokenize(s)
            if tokens:
                openings.append(tokens[0])

        if not openings:
            return 1.0

        return len(set(openings)) / len(openings)

    def sentence_length_cv(self, text: str) -> float:
        """Coefficient of variation of sentence lengths (in words).

        CV = std / mean.  Returns 0.0 for uniform-length sentences,
        higher values for varied sentence lengths.  Capped at 2.0
        for normalization purposes.
        """
        sentences = self._split_sentences(text)
        if len(sentences) <= 1:
            return 0.0

        lengths = [len(self._tokenize(s)) for s in sentences]
        lengths = [l for l in lengths if l > 0]

        if len(lengths) <= 1:
            return 0.0

        mean = sum(lengths) / len(lengths)
        if mean == 0:
            return 0.0

        variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
        std = math.sqrt(variance)
        cv = std / mean
        return min(cv, 2.0)

    def structural_template_diversity(self, text: str) -> float:
        """Ratio of unique sentence templates to total sentences.

        A "template" is the sentence's word count bucketed into
        categories: micro (1-3), short (4-8), medium (9-15),
        long (16-25), sprawling (26+).  Returns 1.0 when all
        bucket types are used proportionally; lower values when
        the writer sticks to one or two length categories.
        """
        sentences = self._split_sentences(text)
        if len(sentences) <= 1:
            return 1.0

        def bucket(n: int) -> str:
            if n <= 3:
                return "micro"
            elif n <= 8:
                return "short"
            elif n <= 15:
                return "medium"
            elif n <= 25:
                return "long"
            else:
                return "sprawling"

        templates = [bucket(len(self._tokenize(s))) for s in sentences]
        unique = len(set(templates))
        total_buckets = 5  # maximum possible diversity
        # normalize: diversity = unique / total_buckets,
        # but also factor in how evenly distributed they are
        if not templates:
            return 1.0

        counts = Counter(templates)
        # Shannon evenness normalized to [0, 1]
        n = len(counts)
        if n <= 1:
            # all in one bucket — minimum diversity
            return 1.0 / total_buckets

        entropy = -sum(
            (c / len(templates)) * math.log2(c / len(templates))
            for c in counts.values()
        )
        max_entropy = math.log2(n)
        evenness = entropy / max_entropy if max_entropy > 0 else 0

        # combine coverage (how many buckets used) with evenness
        coverage = n / total_buckets
        return coverage * 0.5 + evenness * 0.5

    def anaphora_rate(self, text: str) -> float:
        """Fraction of consecutive sentence pairs sharing an opening.

        An "opening" is the first word or first two-word sequence
        of each sentence (including function words and pronouns).
        This captures deliberate rhetorical repetition (anaphora —
        "She walked.  She talked.  She listened.") as well as
        accidental monotony.  Returns 0.0 when no consecutive
        pair shares an opening.
        """
        sentences = self._split_sentences(text)
        if len(sentences) < 2:
            return 0.0

        openings: List[Tuple[str, str]] = []
        for s in sentences:
            tokens = self._tokenize(s)
            if not tokens:
                openings.append(("", ""))
                continue
            first_word = tokens[0]
            first_bigram = tokens[0] if len(tokens) < 2 else f"{tokens[0]} {tokens[1]}"
            openings.append((first_word, first_bigram))

        matches = 0
        pairs = len(openings) - 1
        for i in range(pairs):
            a_word, a_bg = openings[i]
            b_word, b_bg = openings[i + 1]
            if a_word == b_word or a_bg == b_bg:
                matches += 1

        return matches / pairs

    # ── Composite ────────────────────────────────────────────────

    def analyze(self, text: str) -> Dict:
        """Compute all repetition metrics and a composite index.

        Returns a dict with all individual metrics, the composite
        repetition_index (0.0–1.0), and a classification label.
        """
        ttr = self.type_token_ratio(text)
        reuse = self.content_word_reuse_rate(text)
        bigram = self.bigram_repeat_rate(text)
        trigram = self.trigram_repeat_rate(text)
        opening = self.sentence_opening_diversity(text)
        length_cv = self.sentence_length_cv(text)
        template = self.structural_template_diversity(text)
        anaphora = self.anaphora_rate(text)

        # Normalize length_cv to [0, 1] where 1 = highly varied
        # Typical CV range is 0.0 to ~1.5; normalize with sigmoid-like
        normalized_cv = min(length_cv / 1.5, 1.0)

        # Composite: higher = more repetitive
        # TTR is inverted: high TTR = diverse, so 1-TTR = repetitive
        # Reuse, bigram, trigram, anaphora: already "more = more repetitive"
        # Opening diversity inverted: low diversity = more repetitive
        # Template diversity inverted: low diversity = more repetitive
        # CV inverted: low CV = more rhythmic/repetitive
        repetition_index = (
            0.20 * (1.0 - ttr) +
            0.15 * reuse +
            0.15 * bigram +
            0.10 * trigram +
            0.15 * (1.0 - opening) +
            0.10 * (1.0 - normalized_cv) +
            0.15 * (1.0 - template)
        )

        # Classification
        if repetition_index >= 0.65:
            classification = "highly_repetitive"
        elif repetition_index >= 0.45:
            classification = "moderately_repetitive"
        elif repetition_index >= 0.30:
            classification = "balanced"
        elif repetition_index >= 0.15:
            classification = "varied"
        else:
            classification = "highly_varied"

        return {
            "type_token_ratio": round(ttr, 4),
            "content_word_reuse_rate": round(reuse, 4),
            "bigram_repeat_rate": round(bigram, 4),
            "trigram_repeat_rate": round(trigram, 4),
            "sentence_opening_diversity": round(opening, 4),
            "sentence_length_cv": round(length_cv, 4),
            "structural_template_diversity": round(template, 4),
            "anaphora_rate": round(anaphora, 4),
            "repetition_index": round(repetition_index, 4),
            "classification": classification,
        }
