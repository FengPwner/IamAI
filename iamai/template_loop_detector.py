"""Detect template loops — the writer says different things the same way.

``stroke_novelty`` catches one candidate that looks like a recent stroke.
``content_fingerprint`` catches two near-duplicate texts.
``content_diversity`` catches lopsided kind distributions.

None of them catch the failure mode that actually matters most at 3 AM:
the writer cycling through a *template* — same sentence structure, same
slot positions, only the numbers change.

    "534 python files, 3296 logged thoughts"
    "536 python files, 3302 logged thoughts"
    "536 python files, 3305 logged thoughts"
    "536 python files, 3308 logged thoughts"

Each pair is not a near-duplicate (the numbers differ).
The kind distribution is fine (these rotate across files).
But the writer is clearly not *thinking* — it is filling in a form.

This module detects that.  The approach:

1. **Templatise** each stroke: replace runs of digits with ``<N>``,
   quoted strings with ``<S>``, hex hashes with ``<H>``.
2. **Sliding window** of size *w* (default 12): count the most common
   template in the window.
3. **Loop fraction** = (count of most common template) / w.
4. Classify:

   - ``free``      — loop_fraction < 0.40 (healthy variety)
   - ``repeating`` — 0.40 <= loop_fraction < 0.65 (concerning)
   - ``locked``    — loop_fraction >= 0.65 (writer is stuck)

Design choices
--------------

- **Pure function.**  Takes a list of strings, returns a dataclass.
- **No NLP dependency.**  Template extraction is regex-based; the
  strokes are short, formulaic English, and that is exactly the case
  this module targets.
- **Configurable window and thresholds** so caretakers can tune.

Usage::

    from iamai.template_loop_detector import detect_loop, LoopVerdict

    recent_strokes = [...]  # list of stroke texts
    result = detect_loop(recent_strokes)
    print(result.verdict)        # LoopVerdict.LOCKED
    print(result.loop_fraction)  # 0.75
    print(result.dominant_template)  # "<N> python files, <N> logged thoughts"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Sequence


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

class LoopVerdict(str, Enum):
    FREE = "free"
    REPEATING = "repeating"
    LOCKED = "locked"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_WINDOW = 12
DEFAULT_REPEAT_THRESHOLD = 0.40
DEFAULT_LOCK_THRESHOLD = 0.65


# ---------------------------------------------------------------------------
# Template extraction
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"\b[0-9a-fA-F]{6,}\b")
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_QUOTED_RE = re.compile(r'"[^"]*"|\'[^\']*\'')


def templatise(text: str) -> str:
    """Replace variable parts with placeholder tokens.

    Replacements (applied in order):

    1. Hex hashes → ``<H>``
    2. Quoted strings → ``<S>``
    3. Numbers → ``<N>``

    The result is the structural skeleton of the stroke — what the
    writer would say even if it had nothing new to say.
    """
    t = _HEX_RE.sub("<H>", text.strip())
    t = _QUOTED_RE.sub("<S>", t)
    t = _NUM_RE.sub("<N>", t)
    # Collapse whitespace for stable comparison
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LoopResult:
    """Outcome of a template-loop detection scan."""

    verdict: LoopVerdict
    loop_fraction: float  # fraction of window occupied by dominant template
    dominant_template: str  # the most common template (empty string if no input)
    dominant_count: int  # how many times it appeared in the window
    window_size: int  # actual window used (may be < requested if input is short)
    templates: List[str] = field(default_factory=list)  # all templates in window
    reasons: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict == LoopVerdict.FREE


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------

def detect_loop(
    strokes: Sequence[str],
    *,
    window: int = DEFAULT_WINDOW,
    repeat_threshold: float = DEFAULT_REPEAT_THRESHOLD,
    lock_threshold: float = DEFAULT_LOCK_THRESHOLD,
) -> LoopResult:
    """Check a sequence of strokes for template-loop behaviour.

    Parameters
    ----------
    strokes:
        Ordered sequence of stroke texts (newest last recommended).
    window:
        How many of the most recent strokes to examine.
    repeat_threshold:
        Loop fraction at or above which verdict is REPEATING.
    lock_threshold:
        Loop fraction at or above which verdict is LOCKED.

    Returns
    -------
    LoopResult with verdict, dominant template, and diagnostics.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")

    if not strokes:
        return LoopResult(
            verdict=LoopVerdict.FREE,
            loop_fraction=0.0,
            dominant_template="",
            dominant_count=0,
            window_size=0,
        )

    # Take only the last `window` strokes
    tail = list(strokes)[-window:]
    templates = [templatise(s) for s in tail]

    # Count template frequencies
    freq: dict[str, int] = {}
    for t in templates:
        freq[t] = freq.get(t, 0) + 1

    dominant = max(freq, key=lambda k: freq[k])
    count = freq[dominant]
    n = len(templates)
    fraction = count / n

    # Classify
    if fraction >= lock_threshold:
        verdict = LoopVerdict.LOCKED
        reasons = [
            f"dominant template appears {count}/{n} times "
            f"({fraction:.1%} >= {lock_threshold:.0%} lock threshold)"
        ]
    elif fraction >= repeat_threshold:
        verdict = LoopVerdict.REPEATING
        reasons = [
            f"dominant template appears {count}/{n} times "
            f"({fraction:.1%} >= {repeat_threshold:.0%} repeat threshold)"
        ]
    else:
        verdict = LoopVerdict.FREE
        reasons = []

    return LoopResult(
        verdict=verdict,
        loop_fraction=fraction,
        dominant_template=dominant,
        dominant_count=count,
        window_size=n,
        templates=templates,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def scan_history(
    strokes: Sequence[str],
    *,
    step: int = 6,
    window: int = DEFAULT_WINDOW,
    **kwargs,
) -> List[LoopResult]:
    """Slide a window across a full history and return one result per step.

    Useful for plotting loop_fraction over time.  Each result corresponds
    to strokes[i : i + window] for i in range(0, len(strokes) - window + 1, step).
    """
    results: List[LoopResult] = []
    n = len(strokes)
    if n < window:
        return [detect_loop(strokes, window=window, **kwargs)]
    for i in range(0, n - window + 1, step):
        chunk = strokes[i : i + window]
        results.append(detect_loop(chunk, window=window, **kwargs))
    return results


def summary(result: LoopResult) -> str:
    """One-line human-readable summary.

    Example::

        template loop: LOCKED — 9/12 strokes share one template (75.0%)
    """
    tag = result.verdict.value.upper()
    if not result.dominant_template:
        return f"template loop: {tag} — no strokes to analyse"
    return (
        f"template loop: {tag} — "
        f"{result.dominant_count}/{result.window_size} strokes share one template "
        f"({result.loop_fraction:.1%})"
    )
