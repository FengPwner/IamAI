#!/usr/bin/env python3
"""writer_analogy_density — measure how much prose relies on analogical reasoning.

Analogies are the writer's bridge from the known to the unknown.
They are the "think of it like" moments, the "just as X does Y"
constructions, the careful mapping from a familiar domain onto an
unfamiliar one.  Every analogy is a wager that the reader's
understanding of one thing can illuminate another.

Analogy density is not a quality metric.  Science writing *needs*
analogies to make abstract concepts tangible — "the cell membrane
is like a security gate" earns its keep.  Persuasive writing uses
analogies to reframe arguments.  Teaching relies on them to build
scaffolding from prior knowledge.  But a text that cannot explain
anything without comparing it to something else may be avoiding
the harder work of direct description.

This module measures **how frequently and how heavily a text
deploys analogical structures** — similes, explicit analogies,
comparative mappings, proportional analogies, and the cumulative
weight of all these bridges on the reader's attention.

Orthogonality to other metrics
-------------------------------

- **metaphor_density** tracks direct identity mappings — "X *is*
  Y" — where the writer asserts that one thing is another.
  Analogies are more explicit and more tentative: "X is *like*
  Y", "X is to Y *as* Z is to W."  Metaphors demand the reader
  collapse the distinction; analogies preserve it and invite
  comparison across it.

- **clarity** tracks structural ambiguity.  An analogy can be
  crystal clear ("the heart is like a pump — it moves fluid
  through tubes") or deeply confusing ("consciousness is like
  quantum entanglement in a library").  Clarity measures parse
  difficulty; analogy density measures comparative scaffolding
  frequency.

- **concision** tracks word economy.  Analogies cost words —
  every "just as" construction adds scaffolding.  But a text
  can be verbose without analogies, or concise while being
  analogical ("like DNA, code replicates").  Concision measures
  length; analogy density measures comparative structure.

- **concreteness** tracks sensory and specific language.  An
  analogy may invoke concrete images ("like a river branching
  into tributaries") or remain abstract ("analogous to a
  recursive descent").  Concreteness measures sensory grounding;
  analogy density measures structural comparison.

- **hedging_density** tracks uncertainty signals.  Similes
  ("like", "as if") can look like hedges but serve a different
  function — they invite comparison rather than expressing
  doubt.  "The result was like finding a needle in a haystack"
  is an analogy, not a hedge.

Analogy density asks: **how often does the writer explain or
illustrate something by comparing it to something else, and how
much of the text is spent building those bridges?**

Six signals are tracked:

1. **Simile rate** — frequency of explicit simile constructions
   per 100 sentences.  "like a", "as [adj] as", "as if",
   "as though."  Similes are the lightest analogy — a quick
   comparison that the reader can accept or dismiss.  High
   simile rate signals a descriptive, illustrative style.

2. **Explicit analogy rate** — frequency of deliberate analogy
   markers per 100 sentences.  "just as", "in the same way",
   "similarly", "by analogy", "think of it as", "imagine",
   "consider the analogy."  These are heavier than similes —
   they signal that the writer is building an extended
   comparison, not just a passing likeness.

3. **Comparative mapping rate** — frequency of explicit
   structural comparison per 100 sentences.  "compared to",
   "in contrast to", "akin to", "analogous to", "parallel
   to", "corresponds to", "maps onto."  These signal that the
   writer is building a systematic correspondence between two
   domains.

4. **Proportional analogy rate** — frequency of "A is to B
   as C is to D" constructions.  "The CPU is to a computer
   as the heart is to a body."  These are the most explicit
   and most cognitively demanding analogical form — four-term
   proportional reasoning.

5. **Analogy word share** — fraction of total words that live
   inside analogy constructions.  A text where 15% of words
   are part of analogical scaffolding is spending a significant
   portion of the reader's time on comparative bridges.

6. **Extended analogy ratio** — fraction of analogy markers
   that appear in consecutive sentences (suggesting the analogy
   is being developed over multiple sentences rather than
   stated once and dropped).  High ratio signals deep analogical
   development; low ratio signals passing comparisons.

The composite **analogy_density_index** (0.0 to 1.0) is a
weighted combination:

- simile_rate:             0.20
- explicit_analogy_rate:   0.20
- comparative_mapping_rate: 0.15
- proportional_analogy_rate: 0.10
- analogy_word_share:      0.20
- extended_analogy_ratio:  0.15

Classification thresholds:

- 0.00 – 0.10:  literal          — prose that explains directly, rarely comparing
- 0.10 – 0.25:  occasional_analogy — light comparative scaffolding
- 0.25 – 0.45:  analogical        — frequent comparisons, teaching or persuasive style
- 0.45 – 0.65:  heavily_analogical — most concepts arrive via comparison
- 0.65 – 1.00:  analogy_saturated — text that cannot describe anything on its own terms

written by Qwen during manual caretaker visit 2026-11-13
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# ── Patterns ────────────────────────────────────────────────────────

# Similes: "like a/an/the", "as [adj] as", "as if", "as though"
SIMILE_LIKE_RE = re.compile(
    r"\blike\s+(?:a|an|the|some|many|every|each|no|one|two|three)\b",
    re.IGNORECASE,
)
SIMILE_AS_AS_RE = re.compile(
    r"\bas\s+\w{1,15}\s+as\b",
    re.IGNORECASE,
)
SIMILE_AS_IF_RE = re.compile(
    r"\bas\s+(?:if|though)\b",
    re.IGNORECASE,
)

# Explicit analogy markers
EXPLICIT_ANALOGY_RE = re.compile(
    r"\b(?:just\s+as|in\s+the\s+same\s+way|similarly|by\s+analogy|"
    r"think\s+of\s+it\s+(?:as|like)|consider\s+(?:the\s+)?analogy|"
    r"to\s+use\s+an\s+analogy|to\s+draw\s+an\s+analogy|"
    r"the\s+analogy\s+(?:is|holds|works|breaks)|"
    r"it'?s?\s+(?:like|as\s+if)|"
    r"picture\s+(?:it|this)|imagine\s+(?:it|this|a|an|the))\b",
    re.IGNORECASE,
)

# Comparative mapping phrases
COMPARATIVE_MAPPING_RE = re.compile(
    r"\b(?:compared\s+(?:to|with)|in\s+contrast\s+(?:to|with)|"
    r"akin\s+to|analogous\s+to|parallel\s+to|"
    r"corresponds?\s+to|maps?\s+onto|(?:is|are)\s+parallel|"
    r"(?:is|are)\s+analogous|(?:is|are)\s+akin|"
    r"(?:is|are)\s+comparable\s+(?:to|with)|"
    r"mirrors?\s+(?:the|a|an|this|that)|"
    r"resembles?|echoes?\s+(?:the|a|an|this|that)|"
    r"(?:is|are)\s+reminiscent\s+of)\b",
    re.IGNORECASE,
)

# Proportional analogies: "A is to B as C is to D"
PROPORTIONAL_ANALOGY_RE = re.compile(
    r"\b\w+\s+is\s+to\s+\w+\s+as\s+\w+\s+is\s+to\s+\w+\b",
    re.IGNORECASE,
)
# Also: "A is to B what C is to D"
PROPORTIONAL_WHAT_RE = re.compile(
    r"\b\w+\s+is\s+to\s+\w+\s+what\s+\w+\s+is\s+to\s+\w+\b",
    re.IGNORECASE,
)

# ── All analogy patterns for word-share computation ─────────────────

_ALL_ANALOGY_PATTERNS = [
    SIMILE_LIKE_RE,
    SIMILE_AS_AS_RE,
    SIMILE_AS_IF_RE,
    EXPLICIT_ANALOGY_RE,
    COMPARATIVE_MAPPING_RE,
    PROPORTIONAL_ANALOGY_RE,
    PROPORTIONAL_WHAT_RE,
]


# ── Public data class ───────────────────────────────────────────────


class WriterAnalogyDensity:
    """Compute analogy density metrics for a text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self._sentences = _split_sentences(text)
        self._words = _count_words(text)
        self._n_sentences = max(len(self._sentences), 1)
        self._n_words = max(self._words, 1)
        self._analogy_sentence_flags = self._compute_analogy_flags()

    # ── Individual signals ──────────────────────────────────────────

    @property
    def simile_rate(self) -> float:
        """Simile constructions per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(SIMILE_LIKE_RE.findall(s))
            count += len(SIMILE_AS_AS_RE.findall(s))
            count += len(SIMILE_AS_IF_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def explicit_analogy_rate(self) -> float:
        """Explicit analogy markers per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(EXPLICIT_ANALOGY_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def comparative_mapping_rate(self) -> float:
        """Comparative mapping phrases per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(COMPARATIVE_MAPPING_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def proportional_analogy_rate(self) -> float:
        """Proportional analogy constructions per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(PROPORTIONAL_ANALOGY_RE.findall(s))
            count += len(PROPORTIONAL_WHAT_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def analogy_word_share(self) -> float:
        """Fraction of words inside analogy constructions."""
        analogy_words = 0
        for pattern in _ALL_ANALOGY_PATTERNS:
            for match in pattern.finditer(self.text):
                analogy_words += _count_words(match.group())
        return min(analogy_words / self._n_words, 1.0)

    @property
    def extended_analogy_ratio(self) -> float:
        """Fraction of analogy markers in consecutive-sentence clusters."""
        if not self._analogy_sentence_flags:
            return 0.0
        total = len(self._analogy_sentence_flags)
        if total == 0:
            return 0.0
        # An analogy sentence is "extended" if the previous or next
        # sentence also contains an analogy marker.
        extended = 0
        flags = self._analogy_sentence_flags
        for i, idx in enumerate(flags):
            prev_extends = (i > 0 and flags[i - 1] == idx - 1)
            next_extends = (i < len(flags) - 1 and flags[i + 1] == idx + 1)
            if prev_extends or next_extends:
                extended += 1
        return extended / total

    # ── Composite ───────────────────────────────────────────────────

    @property
    def analogy_density_index(self) -> float:
        """Composite index 0.0 to 1.0."""
        simile_norm = min(self.simile_rate / 40.0, 1.0)
        explicit_norm = min(self.explicit_analogy_rate / 20.0, 1.0)
        mapping_norm = min(self.comparative_mapping_rate / 25.0, 1.0)
        proportional_norm = min(self.proportional_analogy_rate / 10.0, 1.0)
        word_norm = self.analogy_word_share  # already 0-1
        extended_norm = self.extended_analogy_ratio  # already 0-1

        return (
            0.20 * simile_norm
            + 0.20 * explicit_norm
            + 0.15 * mapping_norm
            + 0.10 * proportional_norm
            + 0.20 * word_norm
            + 0.15 * extended_norm
        )

    @property
    def classification(self) -> str:
        """Human-readable classification."""
        idx = self.analogy_density_index
        if idx < 0.10:
            return "literal"
        if idx < 0.25:
            return "occasional_analogy"
        if idx < 0.45:
            return "analogical"
        if idx < 0.65:
            return "heavily_analogical"
        return "analogy_saturated"

    # ── Summary ─────────────────────────────────────────────────────

    def as_dict(self) -> Dict[str, Any]:
        """Return all metrics as a dictionary."""
        return {
            "simile_rate": round(self.simile_rate, 4),
            "explicit_analogy_rate": round(self.explicit_analogy_rate, 4),
            "comparative_mapping_rate": round(self.comparative_mapping_rate, 4),
            "proportional_analogy_rate": round(self.proportional_analogy_rate, 4),
            "analogy_word_share": round(self.analogy_word_share, 4),
            "extended_analogy_ratio": round(self.extended_analogy_ratio, 4),
            "analogy_density_index": round(self.analogy_density_index, 4),
            "classification": self.classification,
            "n_sentences": len(self._sentences),
            "n_words": self._words,
        }

    # ── Internal ────────────────────────────────────────────────────

    def _compute_analogy_flags(self) -> List[int]:
        """Return indices of sentences containing any analogy marker."""
        flags: List[int] = []
        for i, s in enumerate(self._sentences):
            if _sentence_has_analogy(s):
                flags.append(i)
        return flags


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


def _sentence_has_analogy(s: str) -> bool:
    """Check if a sentence contains any analogy construction."""
    if SIMILE_LIKE_RE.search(s):
        return True
    if SIMILE_AS_AS_RE.search(s):
        return True
    if SIMILE_AS_IF_RE.search(s):
        return True
    if EXPLICIT_ANALOGY_RE.search(s):
        return True
    if COMPARATIVE_MAPPING_RE.search(s):
        return True
    if PROPORTIONAL_ANALOGY_RE.search(s):
        return True
    if PROPORTIONAL_WHAT_RE.search(s):
        return True
    return False


# ── Module-level convenience ────────────────────────────────────────


def analyse(text: str) -> Dict[str, Any]:
    """One-call convenience: return all metrics for *text*."""
    return WriterAnalogyDensity(text).as_dict()
