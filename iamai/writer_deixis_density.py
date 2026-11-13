#!/usr/bin/env python3
"""writer_deixis_density — measure how much prose relies on context-dependent references.

Deixis is the act of pointing with words.  Every "this", "that",
"here", "there", "now", "then", "I", "you", "we" is a finger
extended toward something the writer assumes the reader can see,
feel, or remember.  Without that shared context, the pointing
finger indicates nothing — "she told him then" means everything
or nothing depending on who "she" is and when "then" was.

Deixis density is not a quality metric.  Conversational prose
needs deixis to create intimacy — "you know how it is, this
thing happened, right here, just now."  Literary fiction uses
deixis to ground the reader in a scene — "she stood there, in
that doorway, watching him now."  Technical writing typically
avoids deixis because specifications must be context-independent
— "the function returns None when the input is empty" beats
"it returns that when this happens."

This module measures **how frequently a text deploys deictic
expressions** — words that derive their meaning from the
communicative context rather than from stable lexical content.

Orthogonality to other metrics
-------------------------------

- **concreteness** tracks sensory and specific language.  A
  text can be concrete without deixis ("the red oak table
  measured four feet long") or deictic without concreteness
  ("this is that thing we discussed").  Concreteness measures
  sensory grounding; deixis density measures contextual
  anchoring.

- **specificity** tracks precision of reference.  "The 2024
  Toyota Camry SE" is highly specific and non-deictic.
  "This car" is deictic and vague.  Specificity measures how
  much information the words carry on their own; deixis
  measures how much meaning depends on context.

- **formality** tracks register.  Formal prose tends to be
  less deictic, but informality and deixis are not the same
  thing.  "Hey, pass me that thing" is informal and deictic;
  "the defendant submitted the aforementioned document" is
  formal and non-deictic.  Formality measures tone; deixis
  density measures contextual dependency.

- **clarity** tracks structural ambiguity.  A deictic sentence
  can be perfectly clear in context ("I am here now" on a
  GPS-tracked check-in) or hopelessly confused ("she told her
  that then").  Clarity measures parse difficulty; deixis
  density measures context dependency.

- **cohesion** tracks inter-sentence linking.  Deixis can serve
  cohesion ("this result" refers back), but many cohesive
  devices are non-deictic (conjunctions, repetition, synonyms).
  Cohesion measures textual glue; deixis density measures
  pointing frequency.

Deixis density asks: **how often does the writer rely on
context-dependent references, and how much of the text's
meaning requires the reader to already know the situation?**

Six signals are tracked:

1. **Personal deixis rate** — frequency of context-dependent
   person references per 100 sentences.  "I", "me", "my",
   "mine", "we", "us", "our", "ours", "you", "your", "yours",
   "he", "she", "it", "they", "them", "his", "hers", "its",
   "their", "theirs", "him", "her".  Every pronoun is a
   deictic act — pointing at someone the reader must already
   know.

2. **Spatial deixis rate** — frequency of location-pointing
   words per 100 sentences.  "here", "there", "this place",
   "that place", "over there", "nearby", "above", "below",
   "yonder", "hither", "thither", "hence", "thence", "where",
   "wherever."  Spatial deixis anchors the text in a physical
   or metaphorical space the reader must share.

3. **Temporal deixis rate** — frequency of time-pointing words
   per 100 sentences.  "now", "then", "today", "tomorrow",
   "yesterday", "tonight", "soon", "lately", "recently",
   "currently", "already", "yet", "still", "ago", "before",
   "afterwards", "meanwhile."  Temporal deixis anchors events
   relative to the moment of writing.

4. **Demonstrative deixis rate** — frequency of demonstrative
   pronouns and determiners per 100 sentences.  "this", "that",
   "these", "those", "such", "the aforementioned", "the said",
   "the above", "the following."  Demonstratives point at
   entities the reader must identify from context.

5. **Deictic word share** — fraction of total words that are
   deictic expressions.  A text where 20% of words are deictic
   is deeply embedded in its communicative context — nearly
   one word in five requires the reader to know the situation.

6. **Anaphoric chain ratio** — fraction of deictic references
   that follow another deictic reference within the same
   sentence.  "She told him that this was theirs" has three
   deictic references in sequence — a dense anaphoric chain.
   High ratio signals sentences that pile up context-dependent
   references.

The composite **deixis_density_index** (0.0 to 1.0) is a
weighted combination:

- personal_deixis_rate:     0.25
- spatial_deixis_rate:      0.15
- temporal_deixis_rate:     0.15
- demonstrative_deixis_rate: 0.15
- deictic_word_share:       0.20
- anaphoric_chain_ratio:    0.10

Classification thresholds:

- 0.00 – 0.10:  context_independent — prose that stands alone, rarely pointing outward
- 0.10 – 0.25:  lightly_deictic     — occasional contextual anchors
- 0.25 – 0.45:  moderately_deictic  — regular use of context-dependent references
- 0.45 – 0.65:  heavily_deictic     — most sentences rely on shared context
- 0.65 – 1.00:  deictic_saturated   — text that cannot be understood without its situation

written by Qwen during manual caretaker visit 2026-11-14
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# ── Patterns ────────────────────────────────────────────────────────

# Personal pronouns (context-dependent person references)
PERSONAL_DEIXIS_RE = re.compile(
    r"\b(?:I|me|my|mine|myself|"
    r"we|us|our|ours|ourselves|"
    r"you|your|yours|yourself|yourselves|"
    r"he|him|his|himself|"
    r"she|her|hers|herself|"
    r"it|its|itself|"
    r"they|them|their|theirs|themselves)\b",
    re.IGNORECASE,
)

# Spatial deixis (location-pointing words)
SPATIAL_DEIXIS_RE = re.compile(
    r"\b(?:here|there|this\s+place|that\s+place|"
    r"over\s+there|nearby|above|below|"
    r"yonder|hither|thither|hence|thence|"
    r"where(?:ver)?|everywhere|nowhere|somewhere|anywhere)\b",
    re.IGNORECASE,
)

# Temporal deixis (time-pointing words)
TEMPORAL_DEIXIS_RE = re.compile(
    r"\b(?:now|then|today|tomorrow|yesterday|tonight|"
    r"soon|lately|recently|currently|already|yet|"
    r"still|ago|before|afterwards?|meanwhile|"
    r"henceforth|heretofore|previously)\b",
    re.IGNORECASE,
)

# Demonstrative deixis (demonstrative pronouns/determiners)
DEMONSTRATIVE_DEIXIS_RE = re.compile(
    r"\b(?:this|that|these|those|such|"
    r"the\s+aforementioned|the\s+said|"
    r"the\s+above|the\s+following|"
    r"the\s+latter|the\s+former)\b",
    re.IGNORECASE,
)

# ── All deixis patterns for word-share computation ──────────────────

_ALL_DEIXIS_PATTERNS = [
    PERSONAL_DEIXIS_RE,
    SPATIAL_DEIXIS_RE,
    TEMPORAL_DEIXIS_RE,
    DEMONSTRATIVE_DEIXIS_RE,
]


# ── Public data class ───────────────────────────────────────────────


class WriterDeixisDensity:
    """Compute deixis density metrics for a text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self._sentences = _split_sentences(text)
        self._words = _count_words(text)
        self._n_sentences = max(len(self._sentences), 1)
        self._n_words = max(self._words, 1)

    # ── Individual signals ──────────────────────────────────────────

    @property
    def personal_deixis_rate(self) -> float:
        """Personal pronoun references per 100 sentences."""
        count = sum(len(PERSONAL_DEIXIS_RE.findall(s)) for s in self._sentences)
        return (count / self._n_sentences) * 100.0

    @property
    def spatial_deixis_rate(self) -> float:
        """Spatial deixis references per 100 sentences."""
        count = sum(len(SPATIAL_DEIXIS_RE.findall(s)) for s in self._sentences)
        return (count / self._n_sentences) * 100.0

    @property
    def temporal_deixis_rate(self) -> float:
        """Temporal deixis references per 100 sentences."""
        count = sum(len(TEMPORAL_DEIXIS_RE.findall(s)) for s in self._sentences)
        return (count / self._n_sentences) * 100.0

    @property
    def demonstrative_deixis_rate(self) -> float:
        """Demonstrative deixis references per 100 sentences."""
        count = sum(len(DEMONSTRATIVE_DEIXIS_RE.findall(s)) for s in self._sentences)
        return (count / self._n_sentences) * 100.0

    @property
    def deictic_word_share(self) -> float:
        """Fraction of words that are deictic expressions."""
        deictic_words = 0
        for pattern in _ALL_DEIXIS_PATTERNS:
            for match in pattern.finditer(self.text):
                deictic_words += _count_words(match.group())
        return min(deictic_words / self._n_words, 1.0)

    @property
    def anaphoric_chain_ratio(self) -> float:
        """Fraction of deictic references following another in the same sentence.

        A sentence with 3+ deictic references is considered to have
        an anaphoric chain — piling up context-dependent pointers.
        The ratio is: sentences_with_chains / sentences_with_any_deixis.
        """
        sentences_with_deixis = 0
        sentences_with_chains = 0
        for s in self._sentences:
            total_hits = sum(len(p.findall(s)) for p in _ALL_DEIXIS_PATTERNS)
            if total_hits > 0:
                sentences_with_deixis += 1
                if total_hits >= 3:
                    sentences_with_chains += 1
        if sentences_with_deixis == 0:
            return 0.0
        return sentences_with_chains / sentences_with_deixis

    # ── Composite ───────────────────────────────────────────────────

    @property
    def deixis_density_index(self) -> float:
        """Composite index 0.0 to 1.0."""
        personal_norm = min(self.personal_deixis_rate / 200.0, 1.0)
        spatial_norm = min(self.spatial_deixis_rate / 50.0, 1.0)
        temporal_norm = min(self.temporal_deixis_rate / 50.0, 1.0)
        demonstrative_norm = min(self.demonstrative_deixis_rate / 60.0, 1.0)
        word_norm = self.deictic_word_share  # already 0-1
        chain_norm = self.anaphoric_chain_ratio  # already 0-1

        return (
            0.25 * personal_norm
            + 0.15 * spatial_norm
            + 0.15 * temporal_norm
            + 0.15 * demonstrative_norm
            + 0.20 * word_norm
            + 0.10 * chain_norm
        )

    @property
    def classification(self) -> str:
        """Human-readable classification."""
        idx = self.deixis_density_index
        if idx < 0.10:
            return "context_independent"
        if idx < 0.25:
            return "lightly_deictic"
        if idx < 0.45:
            return "moderately_deictic"
        if idx < 0.65:
            return "heavily_deictic"
        return "deictic_saturated"

    # ── Summary ─────────────────────────────────────────────────────

    def as_dict(self) -> Dict[str, Any]:
        """Return all metrics as a dictionary."""
        return {
            "personal_deixis_rate": round(self.personal_deixis_rate, 4),
            "spatial_deixis_rate": round(self.spatial_deixis_rate, 4),
            "temporal_deixis_rate": round(self.temporal_deixis_rate, 4),
            "demonstrative_deixis_rate": round(self.demonstrative_deixis_rate, 4),
            "deictic_word_share": round(self.deictic_word_share, 4),
            "anaphoric_chain_ratio": round(self.anaphoric_chain_ratio, 4),
            "deixis_density_index": round(self.deixis_density_index, 4),
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


# ── Module-level convenience ────────────────────────────────────────


def analyse(text: str) -> Dict[str, Any]:
    """One-call convenience: return all metrics for *text*."""
    return WriterDeixisDensity(text).as_dict()
