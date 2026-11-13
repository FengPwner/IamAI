#!/usr/bin/env python3
"""writer_ellipsis_density — measure how much prose communicates through omission.

Ellipsis is the art of what's left unsaid.  A text rich in ellipsis
relies on the reader to fill gaps — dropped subjects, trailing
thoughts, suggestive dashes, pronouns without antecedents, questions
left hanging.  A text poor in ellipsis spells everything out — every
subject stated, every reference resolved, every thought completed.

Ellipsis density is not a quality metric.  Literary fiction and
poetry *must* be elliptical — the power lives in the negative space.
Technical documentation should avoid it — every parameter must be
named, every step explicit.  Dialog thrives on ellipsis ("you know
what I mean").  Legal writing forbids it ("the party of the first
part, hereinafter referred to as…").

This module measures **how much of a text is communicated through
implication, omission, and deliberate incompleteness** — syntactic
gaps, punctuational suspensions, vague references, and trailing
thoughts that require the reader to participate in constructing
meaning.

Orthogonality to other metrics
-------------------------------

- **formality** tracks register conventions.  Ellipsis appears in
  both formal literary prose ("and so it was —") and informal speech
  ("went there, saw it, done").  Ellipsis density measures *how much
  is omitted*; formality measures *how it's dressed*.

- **clarity** tracks structural ambiguity.  A text can be elliptical
  yet clear from context (Hemingway's iceberg technique) or explicit
  yet ambiguous (legalese).  Clarity measures parse certainty;
  ellipsis density measures intentional omission.

- **concision** tracks economy of expression.  Concision is about
  using no more words than needed; ellipsis is about leaving things
  unsaid entirely.  A concise text states everything but briefly;
  an elliptical text leaves some things unstated.

- **conviction** tracks certainty.  Ellipsis can express uncertainty
  ("maybe it was…") or supreme confidence (the Hemingway pause).
  Conviction measures confidence; ellipsis measures omission.

- **negation_density** tracks logical inversion.  Ellipsis can
  include negation ("not that it mattered…") or avoid it entirely.
  Negation measures inversion; ellipsis measures gaps.

- **subtext** tracks implied meaning beneath the surface.  Subtext
  and ellipsis overlap but differ: subtext is about *hidden meaning*;
  ellipsis is about *structural incompleteness*.  A fully grammatical
  sentence can carry subtext; a sentence fragment is elliptical
  regardless of whether it has hidden meaning.

Dimensions
----------

=============================  =============================================
metric                         meaning
=============================  =============================================
syntactic_ellipsis_rate        fraction of sentences with dropped subjects
                               or sentence fragments (verb phrases without
                               explicit subjects, noun phrases standing
                               alone)
punctuation_gap_rate           frequency of ellipsis marks (…), em-dashes
                               (—), and trailing punctuation per sentence
                               — the typographic signals of deliberate
                               incompleteness
vague_reference_rate           frequency of demonstratives and indefinite
                               pronouns without nearby antecedents (this,
                               that, these, those, something, someone,
                               somewhere, anything, everything, nothing,
                               one, some, they [generic]) per sentence
trailing_off_rate              fraction of sentences that end with
                               suspension markers (…, —, open questions
                               without resolution, or em-dash followed
                               by nothing) per sentence
inference_load                 density of constructions that require
                               reader inference: rhetorical questions,
                               conditional fragments, parenthetical
                               asides that hint without explaining,
                               "you know" / "of course" / "needless to
                               say" markers that signal shared knowledge
ellipsis_density_index         composite score (0.0 = fully explicit,
                               1.0 = maximally elliptical) combining
                               syntactic_ellipsis_rate (0.25),
                               punctuation_gap_rate (0.20),
                               vague_reference_rate (0.15),
                               trailing_off_rate (0.20),
                               inference_load (0.20)
classification                 categorical label:
                               fully_explicit (<0.10),
                               minimally_elliptical (<0.25),
                               moderately_elliptical (<0.45),
                               richly_elliptical (<0.65),
                               radically_elliptical (>=0.65)
=============================  =============================================
"""

from __future__ import annotations

import re
from typing import Dict, List


# ── Sentence splitting and tokenization ──────────────────────────────
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)?")

# Stop words for filtering
STOP_WORDS: frozenset = frozenset({
    "a", "an", "the", "and", "or", "but", "nor", "for", "yet", "so",
    "in", "on", "at", "to", "of", "by", "up", "as", "is", "am", "be",
    "do", "if", "it", "he", "we", "my", "me", "us", "no", "oh",
    "was", "has", "had", "did", "its", "his", "her", "our",
    "i", "you", "she", "they", "them", "this", "that", "these",
    "those", "with", "from", "into", "out", "over", "under", "about",
    "above", "below", "between", "through", "during", "before", "after",
    "which", "who", "whom", "whose", "what", "where", "when", "how",
    "than", "then", "there", "here", "were", "been", "being", "are",
    "not", "nor", "too", "very", "just", "also", "still",
    "will", "would", "could", "should", "may", "might", "shall",
    "can", "must", "have", "does",
})

# ── Pattern sets for ellipsis detection ──────────────────────────────

# Ellipsis characters (three dots or Unicode ellipsis)
_ELLIPSIS_RE = re.compile(r"…|\.{2,}")

# Em-dash (Unicode or double-hyphen)
_EM_DASH_RE = re.compile(r"—|——|--")

# Trailing punctuation at end of sentence: ellipsis or dash
_TRAILING_RE = re.compile(r"(?:…|\.{2,}|—|--)\s*$")

# Vague / indefinite references
_VAGUE_REFERENCES = [
    "something", "someone", "somebody", "somewhere", "somehow",
    "anything", "anyone", "anybody", "anywhere", "anyhow",
    "everything", "everyone", "everybody", "everything",
    "nothing", "no one", "nobody", "nowhere",
    "one", "ones", "some", "certain", "particular",
    "thing", "things", "stuff", "matter", "whatever",
    "whoever", "whichever", "whatsoever",
]

# Inference markers — phrases that signal shared knowledge or
# invite the reader to fill in the gap themselves
_INFERENCE_MARKERS = [
    "you know", "of course", "needless to say", "as we know",
    "as everyone knows", "as you might expect", "as expected",
    "goes without saying", "it goes without saying",
    "as it were", "so to speak", "in a manner of speaking",
    "if you will", "as they say", "you might say",
    "as one might expect", "naturally", "obviously",
    "clearly", "evidently", "patently",
    "as always", "as usual", "as ever",
    "you see", "you see what", "see what",
]

# Subject pronouns — if a sentence starts with one of these,
# it has an explicit subject (not a fragment)
_SUBJECT_PRONOUNS = frozenset({
    "i", "you", "he", "she", "it", "we", "they",
    "who", "what", "which", "whoever", "whatever",
    "everyone", "someone", "anyone", "nobody", "somebody",
    "everybody", "anybody", "nothing", "something",
    "anything", "everything",
})

# Sentence-initial verbs (suggest dropped subject)
# Common auxiliary/modal/verb forms that start a sentence when
# the subject is omitted
_INITIAL_VERB_RE = re.compile(
    r"^(?:went|came|ran|walked|sat|stood|turned|looked|thought|"
    r"said|asked|knew|knew|found|took|made|did|got|gave|felt|"
    r"saw|heard|told|left|began|started|stopped|kept|tried|"
    r"wanted|needed|loved|hated|hoped|wished|waited|remembered|"
    r"forgot|believed|seemed|appeared|became|remained|stayed|"
    r"opened|closed|moved|spoke|whispered|shouted|muttered|"
    r"walking|running|sitting|standing|looking|thinking|"
    r"having|being|doing|going|coming|taking|making|"
    r"perhaps|maybe|probably|certainly|surely|apparently|"
    r"if only|wish|imagine|suppose|consider|remember|forget)",
    re.IGNORECASE,
)


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on . ! ? … followed by whitespace."""
    if not text or not text.strip():
        return []
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text.strip())
    # Split on standard sentence-ending punctuation followed by space
    raw = re.split(r"(?<=[.!?])\s+|(?<=…)\s+|(?<=\.{2})\s+", text)
    return [s.strip() for s in raw if s.strip()]


def _tokenize(sentence: str) -> List[str]:
    """Lowercase alphabetic tokens, preserving contractions."""
    return _WORD_RE.findall(sentence.lower())


def _content_words(tokens: List[str]) -> List[str]:
    """Filter out stop words and very short tokens."""
    return [w for w in tokens if w not in STOP_WORDS and len(w) > 1]


class WriterEllipsisDensity:
    """Measure how much prose communicates through omission."""

    def __init__(self):
        self.stop_words = STOP_WORDS
        self.vague_references = _VAGUE_REFERENCES
        self.inference_markers = _INFERENCE_MARKERS

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

    def syntactic_ellipsis_rate(self, text: str) -> float:
        """Fraction of sentences with dropped subjects or fragments.

        Detects sentences that begin with a verb form (suggesting a
        dropped subject) or that consist of a noun phrase standing
        alone (sentence fragments used for stylistic effect).

        Returns 0.0 when every sentence has an explicit subject,
        higher values as more sentences use ellipsis.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        elliptical_count = 0
        for sent in sentences:
            tokens = self._tokenize(sent)
            if not tokens:
                continue

            stripped = sent.strip()
            # Remove leading punctuation for check
            stripped_clean = re.sub(r"^[\"'(\[]+", "", stripped).strip()
            if not stripped_clean:
                continue

            # Check if sentence starts with a verb form (dropped subject)
            first_token = tokens[0] if tokens else ""
            if _INITIAL_VERB_RE.match(stripped_clean):
                elliptical_count += 1
                continue

            # Check for very short fragments (1-4 words without a verb)
            # that look like standalone noun phrases.
            # Exclude sentences starting with subject pronouns —
            # those have an explicit subject.
            content = self._content_words(tokens)
            first_token = tokens[0] if tokens else ""
            starts_with_subject = first_token in _SUBJECT_PRONOUNS

            if (len(tokens) <= 4 and len(content) >= 1
                    and not starts_with_subject):
                # Simple heuristic: if no common verb forms present,
                # likely a fragment
                verb_indicators = {
                    "is", "was", "are", "were", "be", "been", "being",
                    "has", "have", "had", "do", "does", "did",
                    "will", "would", "could", "should", "may", "might",
                    "shall", "can", "must",
                }
                if not any(t in verb_indicators for t in tokens):
                    elliptical_count += 1

        return elliptical_count / len(sentences)

    def punctuation_gap_rate(self, text: str) -> float:
        """Frequency of ellipsis marks and em-dashes per sentence.

        Counts typographic signals of deliberate incompleteness:
        - Ellipsis characters (…) or sequences of dots (..)
        - Em-dashes (—, --, ——)

        Returns 0.0 when no gap punctuation is present, higher
        values for more frequent use.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        total_gaps = 0
        for sent in sentences:
            ellipsis_count = len(_ELLIPSIS_RE.findall(sent))
            dash_count = len(_EM_DASH_RE.findall(sent))
            total_gaps += ellipsis_count + dash_count

        return total_gaps / len(sentences)

    def vague_reference_rate(self, text: str) -> float:
        """Frequency of vague or indefinite references per sentence.

        Counts demonstratives and indefinite pronouns that require
        the reader to infer the referent:
        - something, someone, somewhere, somehow
        - anything, anyone, anywhere
        - everything, everyone, everywhere
        - nothing, nobody, nowhere
        - thing, things, stuff, matter
        - whatever, whoever, whichever

        Returns 0.0 when no vague references are found, higher
        values for more frequent use.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        total_vague = 0
        text_lower = text.lower()
        for ref in self.vague_references:
            # Count occurrences, using word boundaries for short terms
            if len(ref.split()) == 1:
                pattern = r"\b" + re.escape(ref) + r"\b"
                total_vague += len(re.findall(pattern, text_lower))
            else:
                total_vague += text_lower.count(ref)

        return total_vague / len(sentences)

    def trailing_off_rate(self, text: str) -> float:
        """Fraction of sentences ending with suspension markers.

        Detects sentences that trail off rather than concluding:
        - Ending with ellipsis (…) or multiple dots
        - Ending with em-dash (—, --)
        - Ending with a question mark followed by ellipsis

        Returns 0.0 when every sentence ends with definitive
        punctuation, higher values for more trailing sentences.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        trailing_count = 0
        for sent in sentences:
            stripped = sent.rstrip()
            if _TRAILING_RE.search(stripped):
                trailing_count += 1
            elif stripped.endswith("…") or stripped.endswith(".."):
                trailing_count += 1
            elif stripped.endswith("—") or stripped.endswith("--"):
                trailing_count += 1

        return trailing_count / len(sentences)

    def inference_load(self, text: str) -> float:
        """Density of constructions requiring reader inference.

        Counts:
        - Inference markers ("you know", "of course", "needless
          to say", "naturally", "obviously", etc.)
        - Rhetorical questions (questions that don't expect answers
          — detected as questions without following answers)
        - Parenthetical hints (content in parentheses or dashes
          that suggests without explaining)

        Returns 0.0 when no inference triggers are found, higher
        values for more inference-requiring text.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0

        text_lower = text.lower()
        total_inference = 0

        # Count inference markers
        for marker in self.inference_markers:
            total_inference += text_lower.count(marker)

        # Count rhetorical questions (questions in text)
        question_count = sum(
            1 for s in sentences
            if s.rstrip().endswith("?")
        )
        total_inference += question_count

        # Count parenthetical asides
        paren_count = len(re.findall(r"\([^)]+\)", text))
        total_inference += paren_count

        return total_inference / len(sentences)

    # ── Composite ────────────────────────────────────────────────

    def compute_ellipsis_density_index(
        self,
        syntactic: float,
        punctuation: float,
        vague: float,
        trailing: float,
        inference: float,
    ) -> float:
        """Compute composite ellipsis density index (0.0 to 1.0).

        Weights:
        - syntactic_ellipsis_rate: 0.25 (structural omission is
          the strongest signal)
        - punctuation_gap_rate: 0.20 (typographic signals)
        - vague_reference_rate: 0.15 (indefinite reference)
        - trailing_off_rate: 0.20 (deliberate incompleteness)
        - inference_load: 0.20 (reader participation required)
        """
        # Normalize each dimension to [0, 1]
        # syntactic: already 0-1 (fraction of sentences)
        norm_syntactic = min(syntactic, 1.0)

        # punctuation: typically 0-2 per sentence, cap at 3
        norm_punctuation = min(punctuation / 3.0, 1.0)

        # vague: typically 0-1.5 per sentence, cap at 2
        norm_vague = min(vague / 2.0, 1.0)

        # trailing: already 0-1 (fraction of sentences)
        norm_trailing = min(trailing, 1.0)

        # inference: typically 0-2 per sentence, cap at 3
        norm_inference = min(inference / 3.0, 1.0)

        return (
            norm_syntactic * 0.25
            + norm_punctuation * 0.20
            + norm_vague * 0.15
            + norm_trailing * 0.20
            + norm_inference * 0.20
        )

    def classify(self, index: float) -> str:
        """Classify ellipsis density level."""
        if index >= 0.65:
            return "radically_elliptical"
        elif index >= 0.45:
            return "richly_elliptical"
        elif index >= 0.25:
            return "moderately_elliptical"
        elif index >= 0.10:
            return "minimally_elliptical"
        else:
            return "fully_explicit"

    # ── Main Entry Point ─────────────────────────────────────────

    def measure(self, text: str) -> Dict[str, any]:
        """Measure all ellipsis density metrics for given text."""
        if not text or not text.strip():
            return {
                "syntactic_ellipsis_rate": 0.0,
                "punctuation_gap_rate": 0.0,
                "vague_reference_rate": 0.0,
                "trailing_off_rate": 0.0,
                "inference_load": 0.0,
                "ellipsis_density_index": 0.0,
                "classification": "fully_explicit",
            }

        syntactic = self.syntactic_ellipsis_rate(text)
        punctuation = self.punctuation_gap_rate(text)
        vague = self.vague_reference_rate(text)
        trailing = self.trailing_off_rate(text)
        inference = self.inference_load(text)

        index = self.compute_ellipsis_density_index(
            syntactic, punctuation, vague, trailing, inference
        )
        classification = self.classify(index)

        return {
            "syntactic_ellipsis_rate": round(syntactic, 4),
            "punctuation_gap_rate": round(punctuation, 4),
            "vague_reference_rate": round(vague, 4),
            "trailing_off_rate": round(trailing, 4),
            "inference_load": round(inference, 4),
            "ellipsis_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    elliptical_text = """
    Went to the window again. The same view — grey sky, wet
    street, the cat on the wall. Something had changed though.
    Couldn't say what. Maybe the light. Maybe nothing at all…

    Of course, it was never about the view. You know how it
    goes — you look out and you're really looking in. Somewhere
    in the distance, a bell. Then silence.

    If only things were simpler. Imagine a world where…
    """

    explicit_text = """
    The researcher opened the laboratory notebook and reviewed
    the experimental results from Tuesday. The temperature had
    reached forty-two degrees Celsius before the reaction stopped.
    Three samples were contaminated during the transfer process.
    The team scheduled a meeting for Thursday to discuss the
    contamination issue. Each member would prepare a summary of
    their observations.
    """

    wed = WriterEllipsisDensity()

    print("=== Elliptical Text ===")
    result = wed.measure(elliptical_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Explicit Text ===")
    result = wed.measure(explicit_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")
