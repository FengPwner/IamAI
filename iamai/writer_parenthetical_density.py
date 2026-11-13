#!/usr/bin/env python3
"""writer_parenthetical_density — measure how much prose relies on parenthetical asides.

Parentheticals are the writer's side conversations with the reader.
They are the clauses tucked inside dashes, the asides nestled in
brackets, the supplementary whispers between commas.  Every
parenthetical is a bet that the reader can hold the main thread
in working memory while processing a detour — and come back.

Parenthetical density is not a quality metric.  Academic prose
*needs* parentheticals to qualify, cite, and contextualise without
breaking the argumentative thread.  Technical documentation uses
them to define terms in place.  Fiction uses them for voice — the
narrator's wink, the character's interior mutter.  But a text that
cannot finish a sentence without three asides is asking more of
working memory than most readers can give.

This module measures **how much of a text is spent inside
parenthetical constructions** — bracketed asides, em-dash
interruptions, en-dash insertions, comma-delimited appositives,
and the cumulative weight of all these detours on the reader's
attention.

Orthogonality to other metrics
-------------------------------

- **clarity** tracks structural ambiguity — whether the reader
  can parse grammatical relationships on first reading.  A
  parenthetical can be perfectly clear ("the committee, which
  met on Tuesday, approved the budget") or deeply unclear
  ("the report, which the committee, which the board appointed,
  reviewed, was filed").  Clarity measures parse difficulty;
  parenthetical density measures detour frequency.

- **concision** tracks word economy.  A text can be concise
  while being parenthetical ("the result (n=42) was significant")
  or verbose without any parentheticals ("the result was significant
  and this was determined based on a sample of forty-two subjects").
  Concision measures length; parenthetical density measures
  structural interruption.

- **fragment_density** tracks incomplete sentences.  A parenthetical
  is structurally embedded inside a complete sentence; fragments
  stand alone.  They are complementary signals, not overlapping ones.

- **sentence_variety** tracks variation in sentence length and
  structure.  A text can have uniform sentence length while being
  heavily parenthetical, or wild length variation with no
  parentheticals at all.  Variety measures surface diversity;
  parenthetical density measures embedded clause frequency.

- **cohesion** tracks inter-sentence grammatical links.
  Parentheticals are intra-sentence; they live inside the
  boundaries of a single sentence.  Cohesion measures how
  sentences connect to each other; parenthetical density measures
  how much happens inside each sentence.

Parenthetical density asks: **how often does the writer interrupt
their own sentence to say something else, and how much of the
text lives inside those interruptions?**

Six signals are tracked:

1. **Bracket rate** — frequency of square-bracket and round-bracket
   parentheticals per 100 sentences.  "(like this)" and "[sic]"
   are the most explicit forms of parenthetical, visually marked
   and easy to skip.  High bracket rate signals academic or
   technical prose; low rate signals narrative or conversational
   style.

2. **Em-dash aside rate** — frequency of em-dash delimited
   interruptions per 100 sentences.  "The result — which surprised
   everyone — was significant."  Em-dash asides are more dramatic
   than brackets; they demand attention rather than offering an
   optional detour.  High rate signals a discursive, essayistic
   voice.

3. **Comma appositive rate** — frequency of comma-delimited
   non-restrictive clauses per 100 sentences.  "The committee,
   which met on Tuesday, approved the budget."  These are the
   quietest parentheticals, easy to miss on a fast read, and
   the most common source of garden-path re-reading when they
   grow too long.

4. **Nested depth** — maximum nesting depth of parenthetical
   constructions.  "(and (if (you (must))))" is depth 4.
   Depth greater than 2 is a strong signal of over-embedding
   and correlates with re-reading effort.

5. **Parenthetical word share** — fraction of total words that
   live inside any parenthetical construction.  A text where 20%
   of words are inside parentheticals is spending one-fifth of
   the reader's time on detours.  This is the most direct measure
   of parenthetical *weight*.

6. **Interruption ratio** — fraction of sentences that contain
   at least one parenthetical construction.  A text where 80%
   of sentences have an aside is a text that never lets the
   reader finish a thought without a detour.  This captures
   *pervasiveness* rather than *volume*.

The composite **parenthetical_density_index** (0.0 to 1.0) is a
weighted combination:

- bracket_rate:           0.20
- em_dash_aside_rate:     0.20
- comma_appositive_rate:  0.15
- nested_depth:           0.15
- parenthetical_word_share: 0.15
- interruption_ratio:     0.15

Classification thresholds:

- 0.00 – 0.15:  unadorned         — prose that rarely interrupts itself
- 0.15 – 0.30:  lightly_parenthetical — occasional asides, normal for most prose
- 0.30 – 0.50:  moderately_parenthetical — frequent detours, academic or essayistic
- 0.50 – 0.70:  heavily_parenthetical — most sentences contain asides
- 0.70 – 1.00:  recursively_asided — text that cannot finish a thought without three others

written by Qwen during manual caretaker visit 2026-11-13
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Tuple

# ── Patterns ────────────────────────────────────────────────────────

# Round-bracket parentheticals: (like this)
ROUND_BRACKET_RE = re.compile(r"\([^)]*\)")

# Square-bracket parentheticals: [sic], [ed.], [1]
SQUARE_BRACKET_RE = re.compile(r"\[[^\]]*\]")

# Em-dash asides: — text —  (Unicode em-dash U+2014)
EM_DASH_ASIDE_RE = re.compile(r"—[^—]+—")

# En-dash asides (spaced): – text –  (Unicode en-dash U+2013)
EN_DASH_ASIDE_RE = re.compile(r"(?<=\s)–[^–]+–(?=\s)")

# Double-dash asides: -- text -- (ASCII approximation)
DOUBLE_DASH_ASIDE_RE = re.compile(r"--[^-][^-]*(?:--|—)")

# Comma-delimited non-restrictive clauses (which/who/where preceded by comma)
COMMA_APPOSITIVE_RE = re.compile(
    r",\s*(?:which|who|whom|whose|where|when|that)\s+[^,]+,"
)

# Comma-delimited appositives (noun phrase between commas)
# e.g. "the committee, a group of experts, decided"
COMMA_NOUN_APPOSITIVE_RE = re.compile(
    r",\s+(?:a|an|the)\s+[^,]{3,60},"
)

# ── Nesting detection ───────────────────────────────────────────────

_NEST_OPEN = re.compile(r"[(\[]")
_NEST_CLOSE_MAP = {"(": ")", "[": "]"}


# ── Public data class ───────────────────────────────────────────────


class WriterParentheticalDensity:
    """Compute parenthetical density metrics for a text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self._sentences = _split_sentences(text)
        self._words = _count_words(text)
        self._n_sentences = max(len(self._sentences), 1)
        self._n_words = max(self._words, 1)

    # ── Individual signals ──────────────────────────────────────────

    @property
    def bracket_rate(self) -> float:
        """Round + square bracket parentheticals per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(ROUND_BRACKET_RE.findall(s))
            count += len(SQUARE_BRACKET_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def em_dash_aside_rate(self) -> float:
        """Em-dash delimited asides per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(EM_DASH_ASIDE_RE.findall(s))
            count += len(EN_DASH_ASIDE_RE.findall(s))
            count += len(DOUBLE_DASH_ASIDE_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def comma_appositive_rate(self) -> float:
        """Comma-delimited non-restrictive clauses per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(COMMA_APPOSITIVE_RE.findall(s))
            count += len(COMMA_NOUN_APPOSITIVE_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def nested_depth(self) -> int:
        """Maximum nesting depth of bracket/paren constructions."""
        max_depth = 0
        current = 0
        for ch in self.text:
            if ch in ("(", "["):
                current += 1
                max_depth = max(max_depth, current)
            elif ch in (")", "]"):
                current = max(current - 1, 0)
        return max_depth

    @property
    def parenthetical_word_share(self) -> float:
        """Fraction of words inside any parenthetical construction."""
        paren_words = 0
        for match in ROUND_BRACKET_RE.finditer(self.text):
            paren_words += _count_words(match.group())
        for match in SQUARE_BRACKET_RE.finditer(self.text):
            paren_words += _count_words(match.group())
        for match in EM_DASH_ASIDE_RE.finditer(self.text):
            paren_words += _count_words(match.group())
        for match in EN_DASH_ASIDE_RE.finditer(self.text):
            paren_words += _count_words(match.group())
        return min(paren_words / self._n_words, 1.0)

    @property
    def interruption_ratio(self) -> float:
        """Fraction of sentences containing at least one parenthetical."""
        interrupted = 0
        for s in self._sentences:
            if _sentence_has_parenthetical(s):
                interrupted += 1
        return interrupted / self._n_sentences

    # ── Composite ───────────────────────────────────────────────────

    @property
    def parenthetical_density_index(self) -> float:
        """Composite index 0.0 to 1.0."""
        # Normalise rates to 0-1 range with soft caps
        bracket_norm = min(self.bracket_rate / 50.0, 1.0)
        dash_norm = min(self.em_dash_aside_rate / 30.0, 1.0)
        comma_norm = min(self.comma_appositive_rate / 40.0, 1.0)
        depth_norm = min(self.nested_depth / 4.0, 1.0)
        word_norm = self.parenthetical_word_share  # already 0-1
        interrupt_norm = self.interruption_ratio  # already 0-1

        return (
            0.20 * bracket_norm
            + 0.20 * dash_norm
            + 0.15 * comma_norm
            + 0.15 * depth_norm
            + 0.15 * word_norm
            + 0.15 * interrupt_norm
        )

    @property
    def classification(self) -> str:
        """Human-readable classification."""
        idx = self.parenthetical_density_index
        if idx < 0.15:
            return "unadorned"
        if idx < 0.30:
            return "lightly_parenthetical"
        if idx < 0.50:
            return "moderately_parenthetical"
        if idx < 0.70:
            return "heavily_parenthetical"
        return "recursively_asided"

    # ── Summary ─────────────────────────────────────────────────────

    def as_dict(self) -> Dict[str, Any]:
        """Return all metrics as a dictionary."""
        return {
            "bracket_rate": round(self.bracket_rate, 4),
            "em_dash_aside_rate": round(self.em_dash_aside_rate, 4),
            "comma_appositive_rate": round(self.comma_appositive_rate, 4),
            "nested_depth": self.nested_depth,
            "parenthetical_word_share": round(self.parenthetical_word_share, 4),
            "interruption_ratio": round(self.interruption_ratio, 4),
            "parenthetical_density_index": round(self.parenthetical_density_index, 4),
            "classification": self.classification,
            "n_sentences": len(self._sentences),
            "n_words": self._words,
        }


# ── Helpers ─────────────────────────────────────────────────────────


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on . ! ? followed by space or end."""
    if not text or not text.strip():
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _count_words(text: str) -> int:
    """Count words (whitespace-delimited tokens with at least one letter)."""
    tokens = text.split()
    return sum(1 for t in tokens if re.search(r"[a-zA-Z]", t))


def _sentence_has_parenthetical(s: str) -> bool:
    """Check if a sentence contains any parenthetical construction."""
    if ROUND_BRACKET_RE.search(s):
        return True
    if SQUARE_BRACKET_RE.search(s):
        return True
    if EM_DASH_ASIDE_RE.search(s):
        return True
    if EN_DASH_ASIDE_RE.search(s):
        return True
    if DOUBLE_DASH_ASIDE_RE.search(s):
        return True
    if COMMA_APPOSITIVE_RE.search(s):
        return True
    if COMMA_NOUN_APPOSITIVE_RE.search(s):
        return True
    return False


def _count_matching(sentences: List[str], pattern: re.Pattern) -> int:
    """Count sentences matching a pattern at least once."""
    return sum(1 for s in sentences if pattern.search(s))


# ── Module-level convenience ────────────────────────────────────────


def analyse(text: str) -> Dict[str, Any]:
    """One-call convenience: return all metrics for *text*."""
    return WriterParentheticalDensity(text).as_dict()
