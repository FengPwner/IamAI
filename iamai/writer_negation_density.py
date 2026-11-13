#!/usr/bin/env python3
"""writer_negation_density — measure how frequently a text deploys negation.

Negation is the writer's act of denial — saying what something is
*not*, what did *not* happen, what cannot be done.  Every "not",
"never", "no", "neither" carves a hole in the positive assertion
and asks the reader to understand the shape of what remains.

Negation density is not a quality metric.  Philosophical writing
lives in negation — "the thing-in-itself is not the phenomenon."
Legal writing bristles with it — "the licensee shall not, under
no circumstances, transfer..."  Instructional writing uses it
to mark boundaries — "do not exceed the recommended dosage."
But a text that cannot describe anything without first saying
what it is not may be avoiding the harder work of positive
statement.

This module measures **how frequently and how heavily a text
deploys negation** — explicit negators, contracted negations,
negative prefixes, inherently negative verbs, litotes (double
negation for understatement), and the cumulative cognitive load
of stacked negations within single sentences.

Orthogonality to other metrics
-------------------------------

- **hedging_density** tracks uncertainty signals — "might",
  "perhaps", "possibly."  Hedging softens a claim; negation
  reverses it.  "It might not work" contains both a hedge and
  a negation, but they serve different functions.  Hedging
  measures doubt; negation measures denial.

- **conviction** tracks assertiveness.  Negation can be highly
  assertive ("this will never work") or part of a tentative
  construction ("it may not be the best").  Conviction measures
  force of assertion; negation density measures denial frequency.

- **caveat_density** tracks disclaimers and liability shields.
  Caveats often contain negation ("not responsible for",
  "does not guarantee"), but not all negation is caveat.
  "The sky is not green" is a negation, not a caveat.
  Caveat density measures protective language; negation
  density measures denial frequency.

- **clarity** tracks structural ambiguity.  A negation can be
  crystal clear ("the door is not open") or deeply confusing
  ("it is not impossible that this is not unrelated").
  Clarity measures parse difficulty; negation density measures
  denial frequency.

- **formality** tracks register.  Formal prose tends to use
  explicit negation ("shall not"), informal prose prefers
  contracted negation ("won't", "can't"), but register and
  negation are not the same thing.  Formality measures tone;
  negation density measures denial frequency.

Negation density asks: **how often does the writer define things
by what they are not, and how much cognitive load does the
cumulative negation impose on the reader?**

Six signals are tracked:

1. **Explicit negation rate** — frequency of standalone negative
   words per 100 sentences.  "not", "no", "never", "neither",
   "nor", "none", "nothing", "nobody", "nowhere", "nary."
   Each explicit negator is a deliberate act of denial.

2. **Contracted negation rate** — frequency of contracted
   negative forms per 100 sentences.  "n't" in all its forms:
   "don't", "doesn't", "didn't", "isn't", "aren't", "wasn't",
   "weren't", "won't", "wouldn't", "can't", "couldn't",
   "shan't", "shouldn't", "haven't", "hasn't", "hadn't",
   "needn't", "daren't", "oughtn't."  Contractions signal
   informal register but deliver the same logical payload as
   their explicit counterparts.

3. **Negative prefix rate** — frequency of morphological
   negation per 100 sentences.  Prefixes that flip a word's
   meaning: "un-", "in-", "im-", "ir-", "il-", "non-",
   "dis-", "de-", "anti-", "counter-", "mis-."  Each prefix
   is a quiet, embedded negation — "impossible" denies
   "possible" without needing a separate word.

4. **Negative verb rate** — frequency of inherently negative
   verbs per 100 sentences.  "deny", "refuse", "reject",
   "decline", "avoid", "prevent", "prohibit", "forbid",
   "exclude", "contradict", "negate", "dismiss", "oppose."
   These verbs perform negation through their semantics rather
   than through syntax — "she refused the offer" negates the
   acceptance without using "not."

5. **Litotes rate** — frequency of understatement via double
   negation per 100 sentences.  "not bad", "not uncommon",
   "not unlike", "not infrequent", "not insignificant",
   "not unreasonable", "not impossible", "not unusual."
   Litotes is the most cognitively demanding negation — the
   reader must negate the negation to arrive at meaning.

6. **Negation scope ratio** — fraction of negation-containing
   sentences that have two or more negators (stacked negation).
   "It is not impossible that this is not unrelated" has three
   negators in one sentence.  High scope ratio signals heavy
   cognitive load — the reader must track multiple inversions.

The composite **negation_density_index** (0.0 to 1.0) is a
weighted combination:

- explicit_negation_rate:    0.25
- contracted_negation_rate:  0.25
- negative_prefix_rate:      0.15
- negative_verb_rate:        0.15
- litotes_rate:              0.10
- negation_scope_ratio:      0.10

Classification thresholds:

- 0.00 – 0.08:  affirmative       — prose that asserts positively, rarely denying
- 0.08 – 0.20:  lightly_negated    — occasional denials and corrections
- 0.20 – 0.40:  moderately_negated  — frequent negation, boundary-marking style
- 0.40 – 0.60:  heavily_negated    — most statements involve what something is not
- 0.60 – 1.00:  negation_saturated — text that defines primarily through denial

written by Qwen during manual caretaker visit 2026-11-14
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# ── Patterns ────────────────────────────────────────────────────────

# Explicit negation words (standalone tokens)
EXPLICIT_NEGATION_RE = re.compile(
    r"\b(?:not|never|no|neither|nor|none|nothing|nobody|nowhere|nary)\b",
    re.IGNORECASE,
)

# Contracted negation: any word ending in n't
CONTRACTED_NEGATION_RE = re.compile(
    r"\b\w+n't\b",
    re.IGNORECASE,
)

# Negative prefixes — explicit list of common negative-prefix words.
# A broad regex on prefixes like "un\w{3,}" generates too many
# false positives (e.g. "under", "understand", "deadline", "detail").
_NEGATIVE_PREFIX_WORDS = (
    # un-
    "unable", "unaware", "unavailable", "unavoidable", "unbecoming",
    "unbelievable", "uncertain", "unclear", "uncomfortable", "uncommon",
    "unconscious", "unconventional", "unconvincing", "undecided",
    "undeniable", "unfair", "unfamiliar", "unfavourable", "unhappy",
    "unhealthy", "unhelpful", "unlikely", "unnecessary", "unpleasant",
    "unpopular", "unreasonable", "unreliable", "unsafe", "unsuitable",
    "unusual", "unwanted", "unwise", "unwilling", "unworthy",
    # in- / im- / ir- / il-
    "inaccurate", "inadequate", "incapable", "incomplete", "incorrect",
    "incredible", "indecent", "independent", "indirect", "inefficient",
    "inevitable", "infinite", "informal", "innocent", "insufficient",
    "invisible", "impatient", "imperfect", "impolite", "impossible",
    "improper", "impractical", "irrelevant", "irresponsible",
    "irregular", "illegal", "illegitimate", "illiterate", "illogical",
    # non-
    "nonexistent", "nonsense", "nonstandard", "nonviolent", "nonprofit",
    # dis-
    "disagree", "disappear", "disappoint", "disapprove", "disbelieve",
    "discomfort", "disconnect", "discontent", "discontinue", "discord",
    "discourage", "disgrace", "dishonest", "dislike", "disloyal",
    "disobey", "disorder", "displease", "disrespect", "dissatisfy",
    "misunderstand", "misplace", "mislead", "misinform", "misjudge",
    # anti- / counter-
    "antisocial", "antibiotic", "antithesis", "counterproductive",
    "counterintuitive", "counteract", "counterattack",
    # de- (only genuine negatives)
    "devalue", "degrade", "dehumanise", "dehumanize", "destabilise",
    "destabilize",
)
_NEGATIVE_PREFIX_PATTERN = "|".join(re.escape(w) for w in _NEGATIVE_PREFIX_WORDS)
NEGATIVE_PREFIX_RE = re.compile(
    r"\b(?:" + _NEGATIVE_PREFIX_PATTERN + r")\b",
    re.IGNORECASE,
)

# Inherently negative verbs
NEGATIVE_VERB_RE = re.compile(
    r"\b(?:den(?:y|ies|ied|ying)|"
    r"refus(?:e|es|ed|ing)|"
    r"reject(?:s|ed|ing)?|"
    r"declin(?:e|es|ed|ing)|"
    r"avoid(?:s|ed|ing)?|"
    r"prevent(?:s|ed|ing)?|"
    r"prohibit(?:s|ed|ing)?|"
    r"forbi(?:d|ds|dding|dde)|"
    r"exclud(?:e|es|ed|ing)|"
    r"contradict(?:s|ed|ing)?|"
    r"negat(?:e|es|ed|ing)|"
    r"dismiss(?:es|ed|ing)?|"
    r"oppos(?:e|es|ed|ing))\b",
    re.IGNORECASE,
)

# Litotes: "not" + negative-prefix word or known litotes patterns
LITOTES_RE = re.compile(
    r"\bnot\s+(?:un\w{3,}|in\w{3,}|im\w{3,}|ir\w{3,}|il\w{3,}|"
    r"bad|uncommon|unlike|infrequent|insignificant|unreasonable|"
    r"impossible|unusual|unlikely|unfair|unkind|unwise|"
    r"dis\w{3,}|non\w{3,})\b",
    re.IGNORECASE,
)

# ── All negation patterns for sentence-level detection ──────────────

_ALL_NEGATION_PATTERNS = [
    EXPLICIT_NEGATION_RE,
    CONTRACTED_NEGATION_RE,
    NEGATIVE_PREFIX_RE,
    NEGATIVE_VERB_RE,
]


# ── Public data class ───────────────────────────────────────────────


class WriterNegationDensity:
    """Compute negation density metrics for a text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self._sentences = _split_sentences(text)
        self._n_sentences = max(len(self._sentences), 1)
        self._negation_sentence_flags = self._compute_negation_flags()
        self._negation_counts_per_sentence = self._compute_negation_counts()

    # ── Individual signals ──────────────────────────────────────────

    @property
    def explicit_negation_rate(self) -> float:
        """Explicit negation words per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(EXPLICIT_NEGATION_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def contracted_negation_rate(self) -> float:
        """Contracted negation forms per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(CONTRACTED_NEGATION_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def negative_prefix_rate(self) -> float:
        """Negative-prefix words per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(NEGATIVE_PREFIX_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def negative_verb_rate(self) -> float:
        """Inherently negative verbs per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(NEGATIVE_VERB_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def litotes_rate(self) -> float:
        """Litotes (double negation for understatement) per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(LITOTES_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def negation_scope_ratio(self) -> float:
        """Fraction of negation sentences with 2+ negators (stacked)."""
        if not self._negation_sentence_flags:
            return 0.0
        total = len(self._negation_sentence_flags)
        if total == 0:
            return 0.0
        stacked = sum(
            1 for idx in self._negation_sentence_flags
            if self._negation_counts_per_sentence[idx] >= 2
        )
        return stacked / total

    # ── Composite ───────────────────────────────────────────────────

    @property
    def negation_density_index(self) -> float:
        """Composite index 0.0 to 1.0."""
        explicit_norm = min(self.explicit_negation_rate / 50.0, 1.0)
        contracted_norm = min(self.contracted_negation_rate / 30.0, 1.0)
        prefix_norm = min(self.negative_prefix_rate / 40.0, 1.0)
        verb_norm = min(self.negative_verb_rate / 20.0, 1.0)
        litotes_norm = min(self.litotes_rate / 10.0, 1.0)
        scope_norm = self.negation_scope_ratio  # already 0-1

        return (
            0.25 * explicit_norm
            + 0.25 * contracted_norm
            + 0.15 * prefix_norm
            + 0.15 * verb_norm
            + 0.10 * litotes_norm
            + 0.10 * scope_norm
        )

    @property
    def classification(self) -> str:
        """Human-readable classification."""
        idx = self.negation_density_index
        if idx < 0.08:
            return "affirmative"
        if idx < 0.20:
            return "lightly_negated"
        if idx < 0.40:
            return "moderately_negated"
        if idx < 0.60:
            return "heavily_negated"
        return "negation_saturated"

    # ── Public accessor ─────────────────────────────────────────────

    @property
    def n_sentences(self) -> int:
        """Number of sentences in the text."""
        return len(self._sentences)

    # ── Summary ─────────────────────────────────────────────────────

    def as_dict(self) -> Dict[str, Any]:
        """Return all metrics as a dictionary."""
        return {
            "explicit_negation_rate": round(self.explicit_negation_rate, 4),
            "contracted_negation_rate": round(self.contracted_negation_rate, 4),
            "negative_prefix_rate": round(self.negative_prefix_rate, 4),
            "negative_verb_rate": round(self.negative_verb_rate, 4),
            "litotes_rate": round(self.litotes_rate, 4),
            "negation_scope_ratio": round(self.negation_scope_ratio, 4),
            "negation_density_index": round(self.negation_density_index, 4),
            "classification": self.classification,
            "n_sentences": len(self._sentences),
        }

    # ── Internal ────────────────────────────────────────────────────

    def _compute_negation_flags(self) -> List[int]:
        """Return indices of sentences containing any negation."""
        flags: List[int] = []
        for i, s in enumerate(self._sentences):
            if _sentence_has_negation(s):
                flags.append(i)
        return flags

    def _compute_negation_counts(self) -> Dict[int, int]:
        """Return per-sentence negation token count (keyed by index)."""
        counts: Dict[int, int] = {}
        for i, s in enumerate(self._sentences):
            c = 0
            for pat in _ALL_NEGATION_PATTERNS:
                c += len(pat.findall(s))
            if c > 0:
                counts[i] = c
        return counts


# ── Helpers ─────────────────────────────────────────────────────────


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on . ! ? followed by space or end."""
    if not text or not text.strip():
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _sentence_has_negation(s: str) -> bool:
    """Check if a sentence contains any negation."""
    for pat in _ALL_NEGATION_PATTERNS:
        if pat.search(s):
            return True
    return False


# ── Module-level convenience ────────────────────────────────────────


def analyse(text: str) -> Dict[str, Any]:
    """One-call convenience: return all metrics for *text*."""
    return WriterNegationDensity(text).as_dict()
