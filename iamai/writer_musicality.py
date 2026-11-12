#!/usr/bin/env python3
"""writer_musicality — measure the sonic texture of prose.

Musicality is the degree to which writing attends to the *sound* of
language — not just its meaning, but how it feels in the mouth and
lands on the ear.  Highly musical prose has a felt rhythm; you can
hear it even when reading silently.  Flat prose is acoustically
transparent: the reader passes through sound to meaning without
noticing the medium.

This is not a value judgment.  Legal briefs *should* have low
musicality — sonic ornamentation would undermine their function.
Poetry, speeches, and literary essays often benefit from high
musicality.  The metric exists so the writer can *see* whether their
sonic choices match their intent — not to maximize it.

This module is orthogonal to the other writer metrics:

- **prose_rhythm** tracks *variation in sentence length and structure*.
  Rhythm is about syntactic patterning at the sentence level.
  Musicality is about *phonetic texture within* sentences — the
  arrangement of consonants and vowels regardless of sentence shape.

- **pacing** tracks *information delivery speed*.  Pacing is about
  how fast the reader absorbs content.  Musicality is about how
  much the reader lingers on the sound of individual phrases.

- **elegance** tracks *overall aesthetic quality*.  Elegance is a
  holistic judgment.  Musicality is one *ingredient* that may
  contribute to elegance but does not determine it: inelegant prose
  can be highly musical (purple prose), and elegant prose can be
  acoustically plain (Hemingway).

- **voice_consistency** tracks *stability of authorial voice*.  A
  writer can have a consistent voice that is highly musical (Oscar
  Wilde) or consistently unmusical (technical documentation).

Musicality asks: **does the prose draw attention to its own sound,
or is sound invisible in service of meaning?**

Dimensions
----------

===========================  ===========================================
metric                       meaning
===========================  ===========================================
alliteration_rate            fraction of adjacent word pairs sharing
                             an initial consonant or vowel sound
assonance_density            fraction of adjacent word pairs sharing
                             a stressed vowel sound
consonance_rate              fraction of adjacent word pairs sharing
                             a final consonant or consonant cluster
sibilance_density            fraction of words with high sibilant
                             concentration (s, sh, z, zh sounds)
euphony_ratio                fraction of sentences where liquid and
                             nasal consonants (l, m, n, r, w, y)
                             outnumber plosives and fricatives
===========================  ===========================================

From these five dimensions a composite **musicality_index** is computed
as a weighted average and classified:

==============  ============================================================
class           meaning
==============  ============================================================
lyrical         index >= 0.45 — prose is dominated by sonic patterning
melodic         0.30 <= index < 0.45 — frequent sound-based ornamentation
rhythmic        0.15 <= index < 0.30 — moderate sonic texture
spoken          0.05 <= index < 0.15 — occasional sonic touches
flat            index < 0.05 — no detectable sonic ornamentation
==============  ============================================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Sound classification helpers
# ---------------------------------------------------------------------------

LIQUIDS = set("lmnrwy")
NASALS = set("mn")
PLOSIVES = set("ptkbdg")
FRICATIVES = set("fvsz")
VOWELS = set("aeiou")

INITIAL_VOWEL_SOUNDS = re.compile(
    r"^(?:a|e|i|o|u|ea|ee|oo|ou|ai|oi|ow|au)", re.IGNORECASE
)
INITIAL_SILENT = re.compile(r"^(?:kn|wr|gn|ps|pn|rh|wh)", re.IGNORECASE)
SIBILANT_PATTERN = re.compile(r"(?:sh|zh|ch|s|z|j)", re.IGNORECASE)


def _get_initial_sound(word: str) -> str:
    """Extract the initial phoneme approximation of a word."""
    if not word:
        return ""
    w = word.lower().strip("'\"")
    if not w:
        return ""
    if INITIAL_SILENT.match(w):
        mapping = {"kn": "n", "wr": "r", "gn": "n", "ps": "s", "pn": "n", "rh": "r", "wh": "w"}
        return mapping.get(w[:2], w[0])
    if len(w) >= 2 and w[:2] in ("th", "sh", "ch", "ph", "ng"):
        return w[:2]
    return w[0]


def _is_vowel_sound(word: str) -> bool:
    """Check if a word begins with a vowel sound."""
    if not word:
        return False
    w = word.lower().strip("'\"")
    if not w:
        return False
    if len(w) >= 2 and w[:2] in ("kn", "wr", "gn", "ps", "pn", "rh"):
        return False
    if w[0] == "y":
        return False
    if w[0] == "u" and len(w) > 2 and w[:3] in ("uni", "use", "ute", "upu"):
        return False
    return INITIAL_VOWEL_SOUNDS.match(w) is not None


def _get_stressed_vowel(word: str) -> str:
    """Approximate the stressed vowel of a word (heuristic)."""
    w = word.lower().strip("'\"")
    if not w:
        return ""
    match = re.search(r"[aeiou]+", w)
    return match.group() if match else ""


def _get_final_consonants(word: str) -> str:
    """Extract the final consonant cluster of a word."""
    w = word.lower().strip("'\".,;:!?")
    if not w:
        return ""
    if len(w) > 2 and w[-1] == "e" and w[-2] in "bcdfgklmnprstz":
        w = w[:-1]
    result = ""
    for ch in reversed(w):
        if ch in "bcdfghjklmnpqrstvwxyz":
            result = ch + result
        else:
            break
    return result


def _count_sibilants(word: str) -> int:
    """Count sibilant occurrences in a word."""
    w = word.lower()
    count = 0
    i = 0
    while i < len(w):
        if i < len(w) - 1 and w[i:i + 2] in ("sh", "zh", "ch"):
            count += 1
            i += 2
        elif w[i] in "szj":
            count += 1
            i += 1
        else:
            i += 1
    return count


def _count_liquid_nasal(word: str) -> int:
    """Count liquid and nasal consonants in a word."""
    return sum(1 for ch in word.lower() if ch in "lmnrwy")


def _count_plosive_fricative(word: str) -> int:
    """Count plosive and fricative consonants in a word."""
    w = word.lower()
    count = 0
    i = 0
    while i < len(w):
        if i < len(w) - 1 and w[i:i + 2] in ("th", "sh", "ch", "ph", "zh"):
            count += 1
            i += 2
        elif w[i] in "ptkbdgfvsz":
            count += 1
            i += 1
        else:
            i += 1
    return count


def _tokenize_words(text: str) -> List[str]:
    """Split text into words, stripping punctuation."""
    return re.findall(r"[a-zA-Z']+", text)


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on '.', '!', '?', preserving content."""
    parts = re.split(r'[.!?]+', text)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Pattern constants for export / testing
# ---------------------------------------------------------------------------

ALLITERATION_THRESHOLD = 2
ASSONANCE_THRESHOLD = 2
CONSONANCE_THRESHOLD = 2
SIBILANCE_THRESHOLD = 3
EUPHONY_LIQUID_WEIGHT = 1.0
EUPHONY_PLOSIVE_WEIGHT = 1.0


# ---------------------------------------------------------------------------
# WriterMusicality class
# ---------------------------------------------------------------------------


class WriterMusicality:
    """Measure the sonic texture of prose."""

    def __init__(self):
        self.alliteration_min_len = ALLITERATION_THRESHOLD
        self.assonance_min_len = ASSONANCE_THRESHOLD
        self.consonance_min_len = CONSONANCE_THRESHOLD
        self.sibilance_threshold = SIBILANCE_THRESHOLD

    def _split_sentences(self, text: str) -> List[str]:
        return _split_sentences(text)

    def _tokenize(self, text: str) -> List[str]:
        return _tokenize_words(text)

    def measure_alliteration_rate(self, text: str) -> float:
        """Fraction of adjacent word pairs sharing an initial sound."""
        words = self._tokenize(text)
        if len(words) < 2:
            return 0.0
        pairs = 0
        matches = 0
        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i + 1]
            if len(w1) < self.alliteration_min_len or len(w2) < self.alliteration_min_len:
                continue
            pairs += 1
            s1 = _get_initial_sound(w1)
            s2 = _get_initial_sound(w2)
            if s1 and s2 and s1 == s2:
                matches += 1
        return matches / pairs if pairs > 0 else 0.0

    def measure_assonance_density(self, text: str) -> float:
        """Fraction of adjacent word pairs sharing a stressed vowel sound."""
        words = self._tokenize(text)
        if len(words) < 2:
            return 0.0
        pairs = 0
        matches = 0
        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i + 1]
            if len(w1) < self.assonance_min_len or len(w2) < self.assonance_min_len:
                continue
            pairs += 1
            v1 = _get_stressed_vowel(w1)
            v2 = _get_stressed_vowel(w2)
            if v1 and v2 and v1 == v2:
                matches += 1
        return matches / pairs if pairs > 0 else 0.0

    def measure_consonance_rate(self, text: str) -> float:
        """Fraction of adjacent word pairs sharing a final consonant cluster."""
        words = self._tokenize(text)
        if len(words) < 2:
            return 0.0
        pairs = 0
        matches = 0
        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i + 1]
            if len(w1) < self.consonance_min_len or len(w2) < self.consonance_min_len:
                continue
            pairs += 1
            c1 = _get_final_consonants(w1)
            c2 = _get_final_consonants(w2)
            if c1 and c2 and len(c1) >= 1 and len(c2) >= 1 and c1[-1] == c2[-1]:
                matches += 1
        return matches / pairs if pairs > 0 else 0.0

    def measure_sibilance_density(self, text: str) -> float:
        """Fraction of words with high sibilant concentration."""
        words = self._tokenize(text)
        if not words:
            return 0.0
        sibilant_heavy = sum(
            1 for w in words
            if len(w) >= 3 and _count_sibilants(w) >= 2
        )
        return sibilant_heavy / len(words)

    def measure_euphony_ratio(self, text: str) -> float:
        """Fraction of sentences where liquids/nasals outnumber plosives/fricatives."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        euphonious = 0
        for sent in sentences:
            words = self._tokenize(sent)
            if not words:
                continue
            liquid_nasal = sum(_count_liquid_nasal(w) for w in words)
            plosive_fricative = sum(_count_plosive_fricative(w) for w in words)
            if liquid_nasal > plosive_fricative:
                euphonious += 1
        return euphonious / len(sentences)

    def compute_musicality_index(
        self,
        alliteration: float,
        assonance: float,
        consonance: float,
        sibilance: float,
        euphony: float,
    ) -> float:
        """Weighted composite of the five sub-metrics."""
        return (
            alliteration * 0.25
            + assonance * 0.20
            + consonance * 0.20
            + sibilance * 0.15
            + euphony * 0.20
        )

    def classify(self, index: float) -> str:
        """Classify the musicality index into a named category."""
        if index >= 0.45:
            return "lyrical"
        elif index >= 0.30:
            return "melodic"
        elif index >= 0.15:
            return "rhythmic"
        elif index >= 0.05:
            return "spoken"
        else:
            return "flat"

    def measure(self, text: str) -> Dict[str, Any]:
        """Compute all metrics and return a summary dict."""
        alliteration = self.measure_alliteration_rate(text)
        assonance = self.measure_assonance_density(text)
        consonance = self.measure_consonance_rate(text)
        sibilance = self.measure_sibilance_density(text)
        euphony = self.measure_euphony_ratio(text)
        index = self.compute_musicality_index(
            alliteration, assonance, consonance, sibilance, euphony
        )
        classification = self.classify(index)

        return {
            "alliteration_rate": round(alliteration, 4),
            "assonance_density": round(assonance, 4),
            "consonance_rate": round(consonance, 4),
            "sibilance_density": round(sibilance, 4),
            "euphony_ratio": round(euphony, 4),
            "musicality_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    lyrical_text = """The silken sad uncertain rustling of each purple
    curtain thrilled me, filled me with fantastic terrors never felt
    before. Deep into that darkness peering, long I stood there
    wondering, fearing, doubting, dreaming dreams no mortal ever dared
    to dream before. The moon lit the moor with a luminous, lingering
    glow, and the wind wound through the willows, whispering of winters
    long withdrawn."""

    flat_text = """The quarterly report was submitted on time. Revenue
    increased by eight percent compared to the previous quarter. The
    team completed all assigned tasks. Customer satisfaction scores
    remained stable. The next review is scheduled for March fifteenth."""

    wm = WriterMusicality()

    print("=== Lyrical Text ===")
    result = wm.measure(lyrical_text)
    for key, value in result.items():
        print(f"{key:25s} {value}")

    print("\n=== Flat Text ===")
    result = wm.measure(flat_text)
    for key, value in result.items():
        print(f"{key:25s} {value}")
