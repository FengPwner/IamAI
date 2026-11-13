#!/usr/bin/env python3
"""writer_parallelism_density — measure how much prose uses parallel grammatical structures.

Parallelism is the rhetorical device of using repeated grammatical
forms to create emphasis, rhythm, and clarity.  From Cicero's
balanced clauses to Martin Luther King Jr.'s anaphora ("I have a
dream…"), parallel structures are among the oldest and most
powerful tools in the writer's toolkit.

A text with high parallelism density relies heavily on repeated
grammatical patterns — lists with uniform structure, balanced
clauses of similar length, correlative conjunctions (both/and,
either/or, neither/nor), and deliberate repetition at the
beginning or end of successive phrases.

A text with low parallelism density uses varied, asymmetric
structures — each sentence a different shape, each clause its
own length, no repeated patterns.

Parallelism density is not a quality metric.  Speeches and
persuasive essays often benefit from high parallelism — it
creates rhythm and makes ideas memorable.  Narrative fiction
usually needs lower parallelism — too much parallel structure
sounds oratorical, breaking the illusion of lived experience.
Technical documentation uses parallelism selectively (in lists
and comparison tables) but avoids it in running prose.

This module measures **how much of a text relies on parallel
grammatical structures** — repeated patterns, balanced clauses,
correlative conjunctions, and deliberate word-level repetition
at phrase boundaries.

Orthogonality to other metrics
-------------------------------

- **sentence_variety** tracks how diverse sentence structures
  are.  Parallelism is the *opposite impulse* — using similar
  structures deliberately.  A text can have high sentence
  variety AND high parallelism if it alternates between
  parallel passages and varied ones.  Sentence variety
  measures overall diversity; parallelism measures local
  repetition.

- **repetition_index** tracks repeated words and phrases
  globally.  Parallelism is a *specific kind* of repetition —
  structural repetition at clause or sentence boundaries.
  Repetition index catches all repeated content; parallelism
  density catches repeated *form*.

- **prose_rhythm** tracks syllable-level stress patterns and
  cadence.  Parallelism creates rhythm through structure
  rather than syllables.  A text can have strong rhythm
  without parallelism (iambic prose) or strong parallelism
  without clear syllable rhythm.

- **elegance** tracks overall polish and grace.  Parallelism
  can contribute to elegance but is neither necessary nor
  sufficient.  Elegant prose may avoid obvious parallelism;
  clumsy prose may overuse it.

- **musicality** tracks sound-level patterns (alliteration,
  assonance, consonance).  Parallelism operates at the
  grammatical and structural level.  Musical repetition is
  phonetic; parallel repetition is syntactic.

Dimensions
----------

=============================  =============================================
metric                         meaning
=============================  =============================================
anaphora_rate                  frequency of repeated opening words or
                               phrases across consecutive sentences or
                               clauses — "We shall fight on the beaches,
                               we shall fight on the landing grounds…"
epistrophe_rate                frequency of repeated closing words or
                               phrases across consecutive sentences —
                               "…of the people, by the people, for the
                               people"
balanced_clause_rate           fraction of consecutive clause pairs that
                               have similar length (within 30% word count)
                               and matching grammatical shape
correlative_density            frequency of correlative conjunction pairs:
                               both/and, either/or, neither/nor, not
                               only/but also, whether/or, the…the…
structural_repetition_rate     fraction of consecutive sentences that
                               share the same opening grammatical pattern
                               (same part of speech, same clause type,
                               same verb tense)
list_parallelism_rate          fraction of list-like structures (comma-
                               separated items, bullet points, numbered
                               items) that maintain uniform grammatical
                               form across items
=============================  =============================================

Composite: **parallelism_density_index** (0.0 to 1.0)
Weights: anaphora 0.22, epistrophe 0.15, balanced 0.20,
correlative 0.13, structural 0.18, list 0.12.

Classification thresholds:
- 0.00 – 0.10: structurally_asymmetric
- 0.10 – 0.25: mildly_parallel
- 0.25 – 0.45: moderately_parallel
- 0.45 – 0.65: richly_parallel
- 0.65 – 1.00: oratorically_parallel
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


# ── Helpers ──────────────────────────────────────────────────────────

def _split_sentences(text: str) -> List[str]:
    """Split text into sentences, stripping whitespace."""
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in raw if s.strip()]


def _split_clauses(text: str) -> List[str]:
    """Split text into clauses on commas, semicolons, colons, dashes."""
    raw = re.split(r"[,;:—–-]", text)
    return [c.strip() for c in raw if c.strip() and len(c.strip().split()) >= 2]


def _tokenize(text: str) -> List[str]:
    """Simple whitespace + punctuation tokenizer."""
    return re.findall(r"[a-zA-Z']+|[^\s\w]", text)


def _word_count(text: str) -> int:
    """Count words in a text fragment."""
    return len(text.split())


def _opening_words(sentence: str, n: int = 3) -> List[str]:
    """Get the first n lowercase words of a sentence."""
    words = re.findall(r"[a-zA-Z']+", sentence.lower())
    return words[:n]


def _closing_words(sentence: str, n: int = 3) -> List[str]:
    """Get the last n lowercase words of a sentence."""
    words = re.findall(r"[a-zA-Z']+", sentence.lower())
    return words[-n:] if len(words) >= n else words


def _opening_pos_tag(sentence: str) -> str:
    """Rough part-of-speech tag for the opening word.

    Uses heuristic rules rather than a full POS tagger.
    Returns one of: DET, PRON, PROPN, ADJ, ADV, VERB,
    PREP, CONJ, AUX, OTHER.
    """
    words = re.findall(r"[a-zA-Z']+", sentence)
    if not words:
        return "OTHER"
    raw_first = words[0]
    first = raw_first.lower()

    determiners = {
        "the", "a", "an", "this", "that", "these", "those",
        "my", "your", "his", "her", "its", "our", "their",
        "some", "any", "no", "every", "each", "all", "both",
    }
    pronouns = {
        "i", "me", "we", "us", "you", "he", "him", "she",
        "her", "it", "they", "them", "who", "whom", "what",
        "which", "someone", "anyone", "everyone", "nobody",
    }
    prepositions = {
        "in", "on", "at", "to", "for", "with", "from", "by",
        "of", "about", "into", "through", "after", "before",
        "during", "without", "between", "among", "behind",
        "beyond", "across", "along", "around", "beside",
        "beneath", "below", "above", "over", "under", "near",
        "upon", "toward", "towards", "until", "unto",
    }
    conjunctions = {
        "and", "but", "or", "nor", "yet", "so", "because",
        "although", "while", "if", "unless", "since", "when",
        "where", "whether", "though", "as", "than",
    }
    auxiliaries = {
        "is", "am", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "shall", "should", "can", "could",
        "may", "might", "must",
    }
    adverbs = {
        "very", "quite", "rather", "somewhat", "extremely",
        "barely", "hardly", "scarcely", "almost", "already",
        "always", "never", "often", "sometimes", "usually",
        "here", "there", "now", "then", "today", "yesterday",
        "tomorrow", "suddenly", "slowly", "quickly", "gently",
        "however", "moreover", "furthermore", "nevertheless",
        "meanwhile", "therefore", "thus", "hence", "accordingly",
        "consequently", "still", "yet", "just", "only",
    }

    if first in determiners:
        return "DET"
    if first in pronouns:
        return "PRON"
    if first in prepositions:
        return "PREP"
    if first in conjunctions:
        return "CONJ"
    if first in auxiliaries:
        return "AUX"
    if first in adverbs:
        return "ADV"
    if first.endswith("ly") and len(first) > 3:
        return "ADV"
    if first.endswith("ing"):
        return "VERB"
    if first.endswith("ed"):
        return "VERB"
    # Check if capitalized word is actually a known verb form
    if raw_first[0:1].isupper():
        if first in auxiliaries:
            return "AUX"
        # If followed by a determiner or pronoun, likely a verb
        # (imperative: "Run the tests", "Fix the bugs")
        if len(words) > 1:
            second = words[1].lower()
            if second in determiners or second in pronouns:
                return "VERB"
        # Sentence-initial capitalization: check if next word suggests
        # this is a proper noun (another capital or title case) or
        # just a capitalized common word
        if len(words) > 1 and words[1][0:1].isupper():
            return "PROPN"
        # Default: capitalized word at sentence start is PROPN
        # unless we have evidence otherwise
        return "PROPN"
    return "OTHER"


# ── Correlative pairs ────────────────────────────────────────────────

CORRELATIVE_PAIRS: List[Tuple[str, str]] = [
    ("both", "and"),
    ("either", "or"),
    ("neither", "nor"),
    ("not only", "but also"),
    ("not only", "but"),
    ("whether", "or"),
    ("the more", "the more"),
    ("the less", "the less"),
    ("the more", "the less"),
    ("the less", "the more"),
    ("the better", "the better"),
    ("the worse", "the worse"),
    ("the bigger", "the bigger"),
    ("the smaller", "the smaller"),
    ("the faster", "the faster"),
    ("the slower", "the slower"),
    ("the higher", "the higher"),
    ("the lower", "the lower"),
    ("the sooner", "the better"),
    ("as much", "as"),
    ("as well", "as"),
    ("as long", "as"),
    ("as far", "as"),
]

# Patterns for correlative detection
_CORRELATIVE_PATTERNS = [
    re.compile(r"\bboth\b.{1,80}\band\b", re.IGNORECASE),
    re.compile(r"\beither\b.{1,80}\bor\b", re.IGNORECASE),
    re.compile(r"\bneither\b.{1,80}\bnor\b", re.IGNORECASE),
    re.compile(r"\bnot\s+only\b.{1,80}\bbut\s+(?:also|even)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+only\b.{1,80}\bbut\b", re.IGNORECASE),
    re.compile(r"\bwhether\b.{1,80}\bor\b", re.IGNORECASE),
    re.compile(r"\bthe\s+(?:more|less|bigger|smaller|faster|slower|higher|lower|better|worse)\b.{1,60}\bthe\s+(?:more|less|bigger|smaller|faster|slower|higher|lower|better|worse)\b", re.IGNORECASE),
    re.compile(r"\bas\s+(?:much|well|long|far)\b.{1,60}\bas\b", re.IGNORECASE),
]


# ── Main Class ───────────────────────────────────────────────────────


class WriterParallelismDensity:
    """Measure how much prose relies on parallel grammatical structures."""

    def __init__(self) -> None:
        self.correlative_patterns = _CORRELATIVE_PATTERNS

    def _split_sentences(self, text: str) -> List[str]:
        return _split_sentences(text)

    def _split_clauses(self, text: str) -> List[str]:
        return _split_clauses(text)

    # ── Dimension 1: Anaphora ────────────────────────────────────

    def anaphora_rate(self, text: str) -> float:
        """Frequency of repeated opening words across consecutive sentences.

        Detects when consecutive sentences begin with the same word
        or short phrase (2-3 words).  This is the classic rhetorical
        device of anaphora — "We shall fight on the beaches, we shall
        fight on the landing grounds, we shall fight in France…"

        Returns 0.0 when no consecutive sentences share openings,
        higher values for more anaphoric text.
        """
        sentences = self._split_sentences(text)
        if len(sentences) < 2:
            return 0.0

        anaphora_count = 0
        for i in range(1, len(sentences)):
            prev_opening = _opening_words(sentences[i - 1], 2)
            curr_opening = _opening_words(sentences[i], 2)
            if (
                len(prev_opening) >= 1
                and len(curr_opening) >= 1
                and prev_opening[0] == curr_opening[0]
            ):
                anaphora_count += 1
                # Bonus for 2-word match
                if (
                    len(prev_opening) >= 2
                    and len(curr_opening) >= 2
                    and prev_opening[1] == curr_opening[1]
                ):
                    anaphora_count += 0.5

        return anaphora_count / (len(sentences) - 1)

    # ── Dimension 2: Epistrophe ──────────────────────────────────

    def epistrophe_rate(self, text: str) -> float:
        """Frequency of repeated closing words across consecutive sentences.

        Detects when consecutive sentences end with the same word or
        phrase.  This is epistrophe — "…government of the people,
        by the people, for the people, shall not perish from the earth."

        Returns 0.0 when no consecutive sentences share endings,
        higher values for more epistrophic text.
        """
        sentences = self._split_sentences(text)
        if len(sentences) < 2:
            return 0.0

        epistrophe_count = 0
        for i in range(1, len(sentences)):
            prev_closing = _closing_words(sentences[i - 1], 2)
            curr_closing = _closing_words(sentences[i], 2)
            if (
                len(prev_closing) >= 1
                and len(curr_closing) >= 1
                and prev_closing[-1] == curr_closing[-1]
            ):
                epistrophe_count += 1

        return epistrophe_count / (len(sentences) - 1)

    # ── Dimension 3: Balanced Clauses ────────────────────────────

    def balanced_clause_rate(self, text: str) -> float:
        """Fraction of consecutive clause pairs with similar length.

        Detects when adjacent clauses (separated by commas,
        semicolons, or conjunctions) have similar word counts
        (within 30% of each other).  Balanced clauses are a
        hallmark of parallel prose — "Easy come, easy go."

        Returns 0.0 when no clauses are balanced, higher values
        for more balanced text.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        total_pairs = 0
        balanced_count = 0

        for sent in sentences:
            clauses = self._split_clauses(sent)
            if len(clauses) < 2:
                continue

            for i in range(1, len(clauses)):
                wc_prev = _word_count(clauses[i - 1])
                wc_curr = _word_count(clauses[i])
                total_pairs += 1

                if wc_prev == 0 and wc_curr == 0:
                    balanced_count += 1
                elif wc_prev > 0 and wc_curr > 0:
                    ratio = min(wc_prev, wc_curr) / max(wc_prev, wc_curr)
                    if ratio >= 0.70:
                        balanced_count += 1

        if total_pairs == 0:
            return 0.0

        return balanced_count / total_pairs

    # ── Dimension 4: Correlative Conjunctions ────────────────────

    def correlative_density(self, text: str) -> float:
        """Frequency of correlative conjunction pairs per sentence.

        Counts pairs like both/and, either/or, neither/nor,
        not only/but also, whether/or, and comparative
        correlatives (the more/the more).

        Returns 0.0 when no correlatives are found, higher
        values for more correlative-heavy text.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        total_correlatives = 0
        for pattern in self.correlative_patterns:
            total_correlatives += len(pattern.findall(text))

        return total_correlatives / len(sentences)

    # ── Dimension 5: Structural Repetition ───────────────────────

    def structural_repetition_rate(self, text: str) -> float:
        """Fraction of consecutive sentences sharing opening grammatical pattern.

        Uses heuristic part-of-speech tagging to determine the
        grammatical category of each sentence's opening word.
        Consecutive sentences that start with the same category
        (both starting with determiners, both starting with
        pronouns, both starting with prepositions, etc.) count
        as structural repetition.

        Returns 0.0 when no consecutive sentences share opening
        patterns, higher values for more structurally repetitive text.
        """
        sentences = self._split_sentences(text)
        if len(sentences) < 2:
            return 0.0

        repetition_count = 0
        for i in range(1, len(sentences)):
            prev_pos = _opening_pos_tag(sentences[i - 1])
            curr_pos = _opening_pos_tag(sentences[i])
            if prev_pos == curr_pos and prev_pos != "OTHER":
                repetition_count += 1

        return repetition_count / (len(sentences) - 1)

    # ── Dimension 6: List Parallelism ────────────────────────────

    def list_parallelism_rate(self, text: str) -> float:
        """Fraction of list-like structures with uniform grammatical form.

        Detects comma-separated sequences of 3+ items and checks
        whether all items share the same grammatical form (all
        nouns, all verb phrases, all adjectives, etc.).

        Also detects bullet-point and numbered-list structures
        (lines starting with -, *, or digits).

        Returns 0.0 when no lists are found or lists are
        non-parallel, higher values for more parallel lists.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        total_lists = 0
        parallel_lists = 0

        # Check for inline lists (3+ comma-separated items)
        for sent in sentences:
            # Look for sequences like "X, Y, and Z" or "X, Y, Z"
            list_match = re.findall(
                r"(\w+(?:\s+\w+)?)(?:,\s*(\w+(?:\s+\w+)?))+",
                sent,
            )
            # Simpler approach: split on commas and check
            parts = re.split(r",\s*", sent)
            if len(parts) >= 3:
                # Check if items (excluding conjunctions) have similar form
                items = []
                for p in parts:
                    # Remove leading conjunctions
                    clean = re.sub(r"^\s*(?:and|or|but)\s+", "", p.strip())
                    if clean and len(clean.split()) >= 1:
                        items.append(clean)

                if len(items) >= 3:
                    total_lists += 1
                    # Check if all items start with same POS
                    pos_tags = [_opening_pos_tag(item) for item in items]
                    non_other = [p for p in pos_tags if p != "OTHER"]
                    if non_other and len(set(non_other)) == 1:
                        parallel_lists += 1

        # Check for bullet/numbered lists
        lines = text.strip().split("\n")
        bullet_items = []
        for line in lines:
            stripped = line.strip()
            if re.match(r"^[-*•]\s+", stripped):
                bullet_items.append(re.sub(r"^[-*•]\s+", "", stripped))
            elif re.match(r"^\d+[.)]\s+", stripped):
                bullet_items.append(re.sub(r"^\d+[.)]\s+", "", stripped))

        if len(bullet_items) >= 2:
            total_lists += 1
            pos_tags = [_opening_pos_tag(item) for item in bullet_items]
            non_other = [p for p in pos_tags if p != "OTHER"]
            if non_other and len(set(non_other)) == 1:
                parallel_lists += 1

        if total_lists == 0:
            return 0.0

        return parallel_lists / total_lists

    # ── Composite ────────────────────────────────────────────────

    def compute_parallelism_density_index(
        self,
        anaphora: float,
        epistrophe: float,
        balanced: float,
        correlative: float,
        structural: float,
        list_parallel: float,
    ) -> float:
        """Compute composite parallelism density index (0.0 to 1.0).

        Weights:
        - anaphora_rate: 0.22 (repeated openings are the most
          recognizable parallel device)
        - epistrophe_rate: 0.15 (repeated closings are rarer
          but powerful)
        - balanced_clause_rate: 0.20 (structural balance is
          a core parallelism signal)
        - correlative_density: 0.13 (correlative conjunctions
          are explicit parallel markers but less frequent)
        - structural_repetition_rate: 0.18 (opening POS
          repetition captures structural parallelism)
        - list_parallelism_rate: 0.12 (list parallelism is
          context-dependent)
        """
        # Normalize each dimension to [0, 1]

        # anaphora: typically 0-2, cap at 3
        norm_anaphora = min(anaphora / 3.0, 1.0)

        # epistrophe: typically 0-1, cap at 2
        norm_epistrophe = min(epistrophe / 2.0, 1.0)

        # balanced: already 0-1 (fraction of pairs)
        norm_balanced = min(balanced, 1.0)

        # correlative: typically 0-1 per sentence, cap at 2
        norm_correlative = min(correlative / 2.0, 1.0)

        # structural: already 0-1 (fraction of pairs)
        norm_structural = min(structural, 1.0)

        # list: already 0-1 (fraction of lists)
        norm_list = min(list_parallel, 1.0)

        return (
            norm_anaphora * 0.22
            + norm_epistrophe * 0.15
            + norm_balanced * 0.20
            + norm_correlative * 0.13
            + norm_structural * 0.18
            + norm_list * 0.12
        )

    def classify(self, index: float) -> str:
        """Classify parallelism density level."""
        if index >= 0.65:
            return "oratorically_parallel"
        elif index >= 0.45:
            return "richly_parallel"
        elif index >= 0.25:
            return "moderately_parallel"
        elif index >= 0.10:
            return "mildly_parallel"
        else:
            return "structurally_asymmetric"

    # ── Main Entry Point ─────────────────────────────────────────

    def measure(self, text: str) -> Dict[str, Any]:
        """Measure all parallelism density metrics for given text."""
        if not text or not text.strip():
            return {
                "anaphora_rate": 0.0,
                "epistrophe_rate": 0.0,
                "balanced_clause_rate": 0.0,
                "correlative_density": 0.0,
                "structural_repetition_rate": 0.0,
                "list_parallelism_rate": 0.0,
                "parallelism_density_index": 0.0,
                "classification": "structurally_asymmetric",
            }

        anaphora = self.anaphora_rate(text)
        epistrophe = self.epistrophe_rate(text)
        balanced = self.balanced_clause_rate(text)
        correlative = self.correlative_density(text)
        structural = self.structural_repetition_rate(text)
        list_parallel = self.list_parallelism_rate(text)

        index = self.compute_parallelism_density_index(
            anaphora, epistrophe, balanced, correlative,
            structural, list_parallel,
        )
        classification = self.classify(index)

        return {
            "anaphora_rate": round(anaphora, 4),
            "epistrophe_rate": round(epistrophe, 4),
            "balanced_clause_rate": round(balanced, 4),
            "correlative_density": round(correlative, 4),
            "structural_repetition_rate": round(structural, 4),
            "list_parallelism_rate": round(list_parallel, 4),
            "parallelism_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    parallel_text = """
    We shall fight on the beaches. We shall fight on the
    landing grounds. We shall fight in the fields and in the
    streets. We shall fight in the hills. We shall never
    surrender.

    It was the best of times, it was the worst of times.
    It was the age of wisdom, it was the age of foolishness.
    It was the epoch of belief, it was the epoch of
    incredulity.

    Government of the people, by the people, for the people.
    Both the cause and the effect were clear. Either we
    act now or we lose everything. Not only did they win,
    but they also changed the rules.
    """

    asymmetric_text = """
    The researcher opened the laboratory notebook and reviewed
    the experimental results from Tuesday. Temperature readings
    had been recorded at fifteen-minute intervals throughout
    the afternoon. Three of the seven samples showed signs of
    contamination during the transfer process. A meeting was
    scheduled for Thursday morning. Each team member would
    prepare a brief summary of their observations before
    attending.
    """

    wpd = WriterParallelismDensity()

    print("=== Parallel Text ===")
    result = wpd.measure(parallel_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Asymmetric Text ===")
    result = wpd.measure(asymmetric_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")
