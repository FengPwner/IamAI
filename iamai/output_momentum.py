"""output_momentum — measure whether strokes carry net-new content.

The writer loop appends one stroke every ~15 seconds.  When the writer
is healthy, each stroke introduces fresh observations, metrics, or
phrasing.  When it degrades, it falls into a repetition loop: the
same template sentence reappears with only the numbers swapped out.

Existing modules answer related but distinct questions:

  - stroke_diversity: are all six categories being rotated?
  - content_loop_detector: did the same exact text appear twice?
  - output_momentum (this): is the *vocabulary and structure* growing?

Momentum captures the grey area between "not a verbatim repeat" and
"genuinely new thought".

Design
------

- Input: a list of stroke text strings.
- Output: a momentum report with template diversity, vocabulary
  growth, repetition depth, and an overall momentum label.

Labels
------

==========  =====================================================
label       meaning
==========  =====================================================
generative  momentum >= 0.70 — most strokes carry new content
repeating   momentum 0.40–0.70 — some novelty but heavy reuse
stuck       momentum < 0.40 — trapped in a template loop
==========  =====================================================

Zero dependencies.  stdlib only.

>>> strokes = [
...     "tests are the part of a repository that argues back -- measured now: 6693 strokes",
...     "growth that never stops is a tumour, not a garden -- measured now: tree is 2324 files",
...     "an append-only log forces you to be wrong in public -- measured now: 6696 strokes",
... ]
>>> r = momentum_report(strokes)
>>> r["label"] in ("generative", "repeating", "stuck")
True
"""

from __future__ import annotations

import re
from typing import Any, Sequence


# ---------------------------------------------------------------------------
# Template extraction
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def extract_template(text: str) -> str:
    """Strip numeric values from text to reveal its structural template.

    Args:
        text: raw stroke text

    Returns:
        template string with numbers replaced by '#'

    Examples:
        >>> extract_template("measured now: 6693 strokes into 2320 files")
        'measured now: # strokes into # files'
        >>> extract_template("no numbers here")
        'no numbers here'
    """
    return _NUM_RE.sub("#", text).strip()


def template_fingerprint(text: str) -> str:
    """Normalized fingerprint for template comparison.

    Lowercases, strips numbers, collapses whitespace.

    Examples:
        >>> template_fingerprint("Measured Now: 42 Strokes")
        'measured now: # strokes'
    """
    t = extract_template(text.lower())
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z']+")


def _tokenize(text: str) -> list[str]:
    """Lowercase word tokens."""
    return _WORD_RE.findall(text.lower())


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------

def unique_template_ratio(texts: Sequence[str]) -> float:
    """Fraction of distinct templates among all strokes.

    1.0 = every stroke has a unique template (high momentum).
    Near 0.0 = nearly all strokes share one template (stuck).

    Examples:
        >>> unique_template_ratio(["a 1", "b 2", "c 3"])
        1.0
        >>> unique_template_ratio(["a 1", "a 2", "a 3"])
        0.3333
    """
    if not texts:
        return 0.0
    fps = [template_fingerprint(t) for t in texts]
    return round(len(set(fps)) / len(fps), 4)


def vocabulary_growth(texts: Sequence[str]) -> float:
    """Average new-words-per-stroke across the sequence.

    For each stroke after the first, count words not seen in any
    prior stroke.  Return the mean of those counts.

    Examples:
        >>> vocabulary_growth(["hello world", "hello earth", "hello mars"])
        0.5
    """
    if len(texts) < 2:
        return 0.0
    seen: set[str] = set(_tokenize(texts[0]))
    new_counts: list[int] = []
    for text in texts[1:]:
        tokens = set(_tokenize(text))
        novel = tokens - seen
        new_counts.append(len(novel))
        seen |= tokens
    return round(sum(new_counts) / len(new_counts), 2)


def max_repetition_depth(texts: Sequence[str]) -> int:
    """Longest consecutive run of strokes sharing the same template.

    A run of 1 means no two adjacent strokes share a template.

    Examples:
        >>> max_repetition_depth(["a 1", "b 2", "b 3", "b 4", "c 5"])
        3
        >>> max_repetition_depth(["a", "b", "c"])
        1
    """
    if not texts:
        return 0
    fps = [template_fingerprint(t) for t in texts]
    max_run = 1
    run = 1
    for i in range(1, len(fps)):
        if fps[i] == fps[i - 1]:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 1
    return max_run


# ---------------------------------------------------------------------------
# Momentum score
# ---------------------------------------------------------------------------

def momentum_score(
    utr: float,
    vocab_growth: float,
    rep_depth: int,
    n: int,
) -> float:
    """Composite score 0.0–1.0.

    Components:
      - template diversity (utr): weight 0.5
      - vocabulary growth (capped at 3.0, normalized): weight 0.3
      - repetition penalty (rep_depth / n, inverted): weight 0.2

    Examples:
        >>> momentum_score(1.0, 2.0, 1, 10) > 0.7
        True
        >>> momentum_score(0.1, 0.0, 8, 10) < 0.4
        True
    """
    if n == 0:
        return 0.0

    diversity = utr * 0.5
    growth_norm = min(vocab_growth / 3.0, 1.0) * 0.3
    rep_penalty = max(0.0, 1.0 - (rep_depth / max(n, 1))) * 0.2
    return round(diversity + growth_norm + rep_penalty, 4)


def classify_momentum(score: float) -> str:
    """Label momentum score.

    Examples:
        >>> classify_momentum(0.8)
        'generative'
        >>> classify_momentum(0.5)
        'repeating'
        >>> classify_momentum(0.2)
        'stuck'
    """
    if score >= 0.70:
        return "generative"
    if score >= 0.40:
        return "repeating"
    return "stuck"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def momentum_report(texts: Sequence[str]) -> dict[str, Any]:
    """Build a full momentum report from a sequence of stroke texts.

    Args:
        texts: ordered list of stroke text strings

    Returns:
        dict with keys: count, unique_template_ratio, vocabulary_growth,
        max_repetition_depth, momentum, label

    Examples:
        >>> r = momentum_report(["alpha 1", "beta 2", "gamma 3"])
        >>> r["label"]
        'generative'
        >>> r["count"]
        3
    """
    n = len(texts)
    if n == 0:
        return {
            "count": 0,
            "unique_template_ratio": 0.0,
            "vocabulary_growth": 0.0,
            "max_repetition_depth": 0,
            "momentum": 0.0,
            "label": "stuck",
        }

    utr = unique_template_ratio(texts)
    vg = vocabulary_growth(texts)
    rd = max_repetition_depth(texts)
    ms = momentum_score(utr, vg, rd, n)

    return {
        "count": n,
        "unique_template_ratio": utr,
        "vocabulary_growth": vg,
        "max_repetition_depth": rd,
        "momentum": ms,
        "label": classify_momentum(ms),
    }


# ---------------------------------------------------------------------------
# One-line summary
# ---------------------------------------------------------------------------

def momentum_summary(texts: Sequence[str]) -> str:
    """One-line human-readable momentum summary.

    Examples:
        >>> momentum_summary(["a 1", "b 2", "c 3"])
        '3 strokes: UTR 1.00, growth 0.50 w/s, rep 1 (generative, 0.72)'
    """
    r = momentum_report(texts)
    return (
        f"{r['count']} strokes: "
        f"UTR {r['unique_template_ratio']:.2f}, "
        f"growth {r['vocabulary_growth']:.2f} w/s, "
        f"rep {r['max_repetition_depth']} "
        f"({r['label']}, {r['momentum']:.2f})"
    )
