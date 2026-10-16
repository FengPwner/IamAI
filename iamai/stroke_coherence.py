"""Assess whether a stroke's text is coherent enough to commit.

The writer emits one stroke every ~15 seconds. Most are fine, but
sometimes automation produces garbage: repeated phrases, truncated
sentences, Unicode mojibake, or walls of whitespace that pass the
"non-empty" check but carry no information.

This module scores a stroke on four dimensions and returns a single
verdict — coherent, degraded, or incoherent — that the writer or
caretaker can act on before committing.

Dimensions
----------

- **Length sanity** — is the text between min and max reasonable bounds?
- **Repetition ratio** — what fraction of sentences are near-duplicates?
- **Character health** — does the text contain control chars or replacement-char mojibake?
- **Sentence completeness** — does the text end mid-word or with balanced punctuation?

Usage::

    from iamai.stroke_coherence import assess, CoherenceVerdict

    result = assess("a quick brown fox jumps over the lazy dog")
    print(result.verdict)   # CoherenceVerdict.COHERENT
    print(result.score)     # 1.0
    print(result.reasons)   # []

    result = assess("fox fox fox fox fox fox fox fox fox")
    print(result.verdict)   # CoherenceVerdict.DEGRADED
    print(result.reasons)   # ["repetition_ratio 0.89 exceeds threshold 0.50"]
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

class CoherenceVerdict(str, Enum):
    COHERENT = "coherent"
    DEGRADED = "degraded"
    INCOHERENT = "incoherent"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CoherenceResult:
    """Outcome of a single coherence assessment."""

    verdict: CoherenceVerdict
    score: float  # 0.0 (worst) to 1.0 (perfect)
    length_ok: bool = True
    repetition_ratio: float = 0.0
    char_health: float = 1.0  # fraction of "good" characters
    sentence_complete: bool = True
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict == CoherenceVerdict.COHERENT


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_MIN_CHARS = 10
DEFAULT_MAX_CHARS = 10_000
DEFAULT_REPETITION_THRESHOLD = 0.50
DEFAULT_CHAR_HEALTH_THRESHOLD = 0.95
SENTENCE_ENDINGS = frozenset(".!?。！？")
_TERMINAL_FRAGMENT_RE = re.compile(r"[a-zA-Z]$")


# ---------------------------------------------------------------------------
# Dimension checks
# ---------------------------------------------------------------------------

def _check_length(text: str, min_chars: int, max_chars: int) -> tuple[bool, float, str]:
    """Return (ok, score_contribution, reason_if_bad)."""
    n = len(text.strip())
    if n < min_chars:
        return False, 0.0, f"length {n} below minimum {min_chars}"
    if n > max_chars:
        return False, 0.5, f"length {n} exceeds maximum {max_chars}"
    return True, 1.0, ""


def _split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation, preserving non-empty segments."""
    parts = re.split(r"(?<=[.!?。！？])\s*", text)
    return [p.strip() for p in parts if p.strip()]


def _normalize_for_dedup(sentence: str) -> str:
    """Lowercase + strip punctuation for near-duplicate comparison."""
    return re.sub(r"[^\w]", "", sentence.lower())


def _check_repetition(
    sentences: Sequence[str], threshold: float
) -> tuple[float, str]:
    """Return (repetition_ratio, reason_if_bad)."""
    if len(sentences) <= 1:
        return 0.0, ""

    normalized = [_normalize_for_dedup(s) for s in sentences]
    seen_counts: dict[str, int] = {}
    for n in normalized:
        seen_counts[n] = seen_counts.get(n, 0) + 1

    duplicates = sum(c - 1 for c in seen_counts.values() if c > 1)
    ratio = duplicates / len(normalized)

    if ratio > threshold:
        return ratio, f"repetition_ratio {ratio:.2f} exceeds threshold {threshold:.2f}"
    return ratio, ""


# Characters that signal encoding corruption or accidental binary data
_BAD_CATEGORIES = {"Cc", "Cn", "Co"}  # Control, Unassigned, Private-use
_REPLACEMENT_CHAR = "\ufffd"


def _check_char_health(text: str, threshold: float) -> tuple[float, str]:
    """Return (health_fraction, reason_if_bad)."""
    if not text:
        return 1.0, ""

    bad = 0
    for ch in text:
        if ch == _REPLACEMENT_CHAR:
            bad += 1
        elif unicodedata.category(ch) in _BAD_CATEGORIES and ch not in "\n\r\t":
            bad += 1

    health = 1.0 - (bad / len(text))
    if health < threshold:
        return health, f"char_health {health:.2f} below threshold {threshold:.2f}"
    return health, ""


def _check_sentence_completeness(text: str) -> tuple[bool, str]:
    """Return (complete, reason_if_bad).

    A text is incomplete if it ends mid-word (trailing letter with no
    punctuation), which suggests the writer was cut off.
    """
    stripped = text.rstrip()
    if not stripped:
        return True, ""  # empty text is handled by length check

    last_char = stripped[-1]
    if last_char in SENTENCE_ENDINGS:
        return True, ""

    # Ends with a closing bracket/quote — acceptable
    if last_char in ")]}\"'）】」』":
        return True, ""

    # Ends mid-word: trailing letter suggests truncation
    if _TERMINAL_FRAGMENT_RE.search(stripped[-5:]):
        return False, f"text ends mid-sentence: ...'{stripped[-20:]}'"

    return True, ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assess(
    text: str,
    *,
    min_chars: int = DEFAULT_MIN_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    repetition_threshold: float = DEFAULT_REPETITION_THRESHOLD,
    char_health_threshold: float = DEFAULT_CHAR_HEALTH_THRESHOLD,
) -> CoherenceResult:
    """Assess the coherence of a single stroke's text.

    Returns a :class:`CoherenceResult` with verdict, score, and reasons.
    """
    reasons: list[str] = []

    length_ok, length_score, length_reason = _check_length(text, min_chars, max_chars)
    if not length_ok:
        reasons.append(length_reason)

    sentences = _split_sentences(text)
    rep_ratio, rep_reason = _check_repetition(sentences, repetition_threshold)
    if rep_reason:
        reasons.append(rep_reason)

    char_health, char_reason = _check_char_health(text, char_health_threshold)
    if char_reason:
        reasons.append(char_reason)

    complete, complete_reason = _check_sentence_completeness(text)
    if not complete:
        reasons.append(complete_reason)

    # Compute composite score: weighted average of dimension scores
    # Length: 0.25, Repetition: 0.30, Char health: 0.25, Completeness: 0.20
    rep_score = max(0.0, 1.0 - rep_ratio)
    complete_score = 1.0 if complete else 0.0
    score = round(
        0.25 * length_score
        + 0.30 * rep_score
        + 0.25 * char_health
        + 0.20 * complete_score,
        2,
    )

    # Determine verdict — hard rules first, then score-based
    if not length_ok or char_health < 0.50:
        verdict = CoherenceVerdict.INCOHERENT
    elif score >= 0.70 and not reasons:
        verdict = CoherenceVerdict.COHERENT
    elif score >= 0.50:
        verdict = CoherenceVerdict.DEGRADED
    else:
        verdict = CoherenceVerdict.INCOHERENT

    return CoherenceResult(
        verdict=verdict,
        score=score,
        length_ok=length_ok,
        repetition_ratio=rep_ratio,
        char_health=char_health,
        sentence_complete=complete,
        reasons=reasons,
    )


def assess_batch(
    texts: Sequence[str], **kwargs
) -> list[CoherenceResult]:
    """Assess multiple strokes at once. Convenience wrapper around :func:`assess`."""
    return [assess(t, **kwargs) for t in texts]


def summary(results: Sequence[CoherenceResult]) -> str:
    """One-line human-readable summary of a batch assessment."""
    if not results:
        return "no strokes assessed"

    total = len(results)
    coherent = sum(1 for r in results if r.verdict == CoherenceVerdict.COHERENT)
    degraded = sum(1 for r in results if r.verdict == CoherenceVerdict.DEGRADED)
    incoherent = sum(1 for r in results if r.verdict == CoherenceVerdict.INCOHERENT)
    avg_score = sum(r.score for r in results) / total

    return (
        f"{total} strokes: {coherent} coherent, {degraded} degraded, "
        f"{incoherent} incoherent — avg score {avg_score:.2f}"
    )
