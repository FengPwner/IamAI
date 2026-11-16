#!/usr/bin/env python3
"""writer_perspective_shift — measure grammatical-person stability in prose.

Perspective shift is the frequency at which a text changes its
dominant grammatical person — first person (I, we, my, our),
second person (you, your, yourself), or third person (he, she,
they, it, the author, one).  A text that stays in one person
reads as focused and intentional; a text that jumps between
persons reads as disorienting or conversational.  Neither is
inherently good or bad — a tutorial *should* mix second and
third person ("You call the function.  It returns a value.");
a legal brief *should* stay in third person throughout.
But uncontrolled person-shifts are a common drafting defect:
the essay that opens with "We all face challenges" and then
drifts into "One must consider the implications" before
switching to "You see this in practice."

Person manifests through pronoun usage.

**First-person markers** are pronouns and possessives that
place the speaker inside the text: *I, me, my, mine, myself,
we, us, our, ours, ourselves*.  They signal that the writer
is speaking from personal experience or taking ownership of
a claim.  High first-person density makes prose feel intimate,
confessional, or authoritative depending on context.

**Second-person markers** address the reader directly: *you,
your, yours, yourself, yourselves*.  They create immediacy
and pull the reader into the text.  Instructional writing,
advice columns, and interactive fiction rely heavily on
second person; academic papers and formal reports avoid it.

**Third-person markers** refer to entities outside the
speaker–reader dyad: *he, him, his, himself, she, her, hers,
herself, it, its, itself, they, them, their, theirs,
themselves, one, one's*.  They create distance and objectivity.
Journalism, scientific writing, and narrative fiction
predominantly operate in third person.

A **person shift** occurs when the dominant person of one
sentence differs from the dominant person of the next sentence.
The shift rate is the fraction of adjacent-sentence pairs that
exhibit a person change.  A text with zero shifts is perfectly
stable; a text where every sentence uses a different person
has a shift rate approaching 1.0.

This module measures perspective stability as a composite
index (0.0 – 1.0) where:

- 0.0 = perfectly stable (no person shifts)
- 1.0 = maximally unstable (every sentence boundary is a shift)

The index is orthogonal to verbosity (word count), formality
(register), hedging (uncertainty expression), and prose
granularity (detail level).  A short text can be highly
unstable ("I think. You know. They say."); a long text can
be perfectly stable.

written by Qwen during manual caretaker visit 657, 2026-11-16
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional


# ── regex primitives ────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"[a-zA-Z']+")


# ── pronoun dictionaries ───────────────────────────────────────

_FIRST_PERSON = {
    "i", "me", "my", "mine", "myself",
    "we", "us", "our", "ours", "ourselves",
}

_SECOND_PERSON = {
    "you", "your", "yours", "yourself", "yourselves",
}

_THIRD_PERSON = {
    "he", "him", "his", "himself",
    "she", "her", "hers", "herself",
    "it", "its", "itself",
    "they", "them", "their", "theirs", "themselves",
    "one", "one's",
}


# ── helper: extract words ──────────────────────────────────────


def _extract_words(text: str) -> List[str]:
    """Return lowercased word tokens."""
    return [m.lower() for m in _WORD_SPLIT.findall(text)]


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences, filtering empties."""
    parts = _SENTENCE_SPLIT.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


# ── per-sentence person detection ──────────────────────────────


@dataclass
class SentencePerson:
    """Person counts for a single sentence."""
    first: int = 0
    second: int = 0
    third: int = 0

    @property
    def dominant(self) -> Optional[str]:
        """Return the dominant person, or None if no pronouns."""
        counts = {"first": self.first, "second": self.second, "third": self.third}
        total = sum(counts.values())
        if total == 0:
            return None
        return max(counts, key=counts.get)

    @property
    def total(self) -> int:
        return self.first + self.second + self.third


def _classify_sentence(sentence: str) -> SentencePerson:
    """Count person markers in a single sentence."""
    words = _extract_words(sentence)
    sp = SentencePerson()
    for w in words:
        if w in _FIRST_PERSON:
            sp.first += 1
        elif w in _SECOND_PERSON:
            sp.second += 1
        elif w in _THIRD_PERSON:
            sp.third += 1
    return sp


# ── result dataclass ────────────────────────────────────────────


@dataclass
class PerspectiveShiftResult:
    """Result of perspective-shift analysis."""

    # Composite index (0.0 = stable, 1.0 = maximally unstable)
    shift_index: float = 0.0

    # Classification
    classification: str = "stable"
    # stable | mostly_stable | mixed | restless | unstable

    # Per-person totals across the whole text
    first_person_count: int = 0
    second_person_count: int = 0
    third_person_count: int = 0

    # Per-person scores (fraction of all pronoun tokens)
    first_person_score: float = 0.0
    second_person_score: float = 0.0
    third_person_score: float = 0.0

    # Shift counts
    total_shifts: int = 0
    shift_pairs: int = 0  # total adjacent pairs with person data

    # Dominant person
    dominant_person: Optional[str] = None

    # Per-sentence breakdown (optional, for debugging)
    sentence_persons: List[SentencePerson] = field(default_factory=list)

    # Metadata
    total_sentences: int = 0
    total_words: int = 0
    total_pronouns: int = 0


# ── main measurement function ──────────────────────────────────


def measure_perspective_shift(text: str) -> PerspectiveShiftResult:
    """Measure grammatical-person stability in a text.

    Returns a PerspectiveShiftResult with shift_index (0.0–1.0)
    and classification.
    """
    result = PerspectiveShiftResult()

    stripped = text.strip()
    if not stripped:
        result.classification = "stable"
        return result

    sentences = _split_sentences(text)
    words = _extract_words(text)
    result.total_sentences = len(sentences)
    result.total_words = len(words)

    if len(sentences) < 2:
        # Single sentence: no shifts possible
        sp = _classify_sentence(sentences[0]) if sentences else SentencePerson()
        result.first_person_count = sp.first
        result.second_person_count = sp.second
        result.third_person_count = sp.third
        result.total_pronouns = sp.total
        result.sentence_persons = [sp]
        result.dominant_person = sp.dominant
        result.classification = "stable"
        result.shift_index = 0.0
        _compute_scores(result)
        return result

    # Classify each sentence
    sentence_persons = [_classify_sentence(s) for s in sentences]
    result.sentence_persons = sentence_persons

    # Aggregate totals
    result.first_person_count = sum(sp.first for sp in sentence_persons)
    result.second_person_count = sum(sp.second for sp in sentence_persons)
    result.third_person_count = sum(sp.third for sp in sentence_persons)
    result.total_pronouns = (
        result.first_person_count
        + result.second_person_count
        + result.third_person_count
    )

    # Count person shifts between adjacent sentences
    shifts = 0
    pairs = 0
    for i in range(len(sentence_persons) - 1):
        dom_a = sentence_persons[i].dominant
        dom_b = sentence_persons[i + 1].dominant
        # Only count pairs where both sentences have person data
        if dom_a is not None and dom_b is not None:
            pairs += 1
            if dom_a != dom_b:
                shifts += 1

    result.total_shifts = shifts
    result.shift_pairs = pairs

    # Compute shift index
    if pairs > 0:
        result.shift_index = round(shifts / pairs, 4)
    else:
        result.shift_index = 0.0

    # Determine dominant person
    counts = {
        "first": result.first_person_count,
        "second": result.second_person_count,
        "third": result.third_person_count,
    }
    if result.total_pronouns > 0:
        result.dominant_person = max(counts, key=counts.get)
    else:
        result.dominant_person = None

    # Compute per-person scores
    _compute_scores(result)

    # Classification
    idx = result.shift_index
    if idx < 0.10:
        result.classification = "stable"
    elif idx < 0.25:
        result.classification = "mostly_stable"
    elif idx < 0.45:
        result.classification = "mixed"
    elif idx < 0.65:
        result.classification = "restless"
    else:
        result.classification = "unstable"

    return result


def _compute_scores(result: PerspectiveShiftResult) -> None:
    """Compute per-person fraction scores."""
    total = result.total_pronouns
    if total > 0:
        result.first_person_score = round(result.first_person_count / total, 4)
        result.second_person_score = round(result.second_person_count / total, 4)
        result.third_person_score = round(result.third_person_count / total, 4)
    else:
        result.first_person_score = 0.0
        result.second_person_score = 0.0
        result.third_person_score = 0.0
