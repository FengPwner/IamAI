"""stroke_yield_analyzer — measure how much new content each stroke produces.

The writer sometimes falls into a *retread loop*: it generates strokes
that look different on the surface but say the same thing about the
same targets.  Existing modules detect structural loops (kind cycling)
and text similarity (near-duplicates), but none answer the simplest
question: **is the writer actually producing new work, or just
rewarming old ground?**

This module classifies each stroke into one of three yield categories:

- **fresh**: the stroke touches a file/topic not seen in the window,
  or its text is sufficiently different from all recent strokes.
- **retread**: the stroke revisits a recently-seen target *and* its
  text is substantially similar to a recent stroke about that target.
- **exhausted**: the stroke explicitly signals inability to produce
  new content (e.g. "nothing new to add", "already in the pool").

Aggregated over a window, these counts give a **yield report** with:

- ``fresh_ratio``: fraction of strokes that are genuinely new.
- ``retread_ratio``: fraction that rehash recent work.
- ``exhausted_ratio``: fraction that signal saturation.
- ``yield_grade``: qualitative label — *productive*, *warming*,
  *looping*, *exhausted*.
- ``saturation_targets``: list of targets (files/topics) that appear
  most often in retread/exhausted strokes.

Usage::

    from iamai.stroke_yield_analyzer import analyse

    strokes = [
        {"text": "added retry logic with exponential backoff", "file": "tools/retry.py"},
        {"text": "added retry logic with exponential backoff", "file": "tools/retry.py"},
        {"text": "nothing new to add to retry.py", "file": "tools/retry.py"},
        {"text": "new module for detecting writer loops", "file": "iamai/loop_detector.py"},
    ]

    report = analyse(strokes, window=10)
    print(report["yield_grade"])  # "looping"

Public API
----------
- ``analyse(strokes, window=20, text_threshold=0.6) -> dict``
- ``classify_stroke(stroke, recent_strokes, text_threshold=0.6) -> str``
- ``yield_grade(fresh_ratio, exhausted_ratio) -> str``
- ``find_saturation_targets(strokes, top_n=5) -> list[str]``
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# ---------------------------------------------------------------------------
# Exhausted-pattern lexicon
# ---------------------------------------------------------------------------

_EXHAUSTED_PATTERNS = [
    re.compile(r"nothing new to add", re.IGNORECASE),
    re.compile(r"already in the pool", re.IGNORECASE),
    re.compile(r"no new (?:content|ideas|modules) to", re.IGNORECASE),
    re.compile(r"already (?:exists|covered|done)", re.IGNORECASE),
    re.compile(r"nothing (?:else|more) to", re.IGNORECASE),
    re.compile(r"exhausted", re.IGNORECASE),
    re.compile(r"no room for", re.IGNORECASE),
    re.compile(r"saturation", re.IGNORECASE),
    re.compile(r"already (?:has|have) \d+", re.IGNORECASE),
]


def _is_exhausted_text(text: str) -> bool:
    """Return True if the text matches any exhaustion signal pattern."""
    return any(pat.search(text) for pat in _EXHAUSTED_PATTERNS)


# ---------------------------------------------------------------------------
# Text similarity (Jaccard over word tokens)
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did will "
    "would shall should may might can could i you he she it we they this "
    "that these those and or but not no nor so yet if then than to for of "
    "in on at by with from as into about between through during before "
    "after above below up down out off over under again further once here "
    "there when where why how all each every both few more most other some "
    "such only own same too very just because".split()
)


def _tokenize(text: str) -> set[str]:
    """Lowercase, strip punctuation and stop words, return word set."""
    words = re.findall(r"[a-z0-9_]+", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two sets."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union


# ---------------------------------------------------------------------------
# Stroke classification
# ---------------------------------------------------------------------------


def classify_stroke(
    stroke: dict[str, Any],
    recent_strokes: list[dict[str, Any]],
    text_threshold: float = 0.6,
) -> str:
    """Classify a single stroke as 'fresh', 'retread', or 'exhausted'.

    Parameters
    ----------
    stroke : dict
        Must have ``"text"`` key.  Optional ``"file"`` key.
    recent_strokes : list[dict]
        The preceding strokes within the analysis window.
    text_threshold : float
        Jaccard similarity above which two strokes are considered
        substantially similar.

    Returns
    -------
    str
        One of ``"fresh"``, ``"retread"``, ``"exhausted"``.
    """
    text = stroke.get("text", "")
    target = stroke.get("file", "")

    # 1. Explicit exhaustion signal — highest priority
    if _is_exhausted_text(text):
        return "exhausted"

    if not recent_strokes:
        return "fresh"

    # 2. Check for retread: same target AND similar text
    current_tokens = _tokenize(text)

    for prev in recent_strokes:
        prev_text = prev.get("text", "")
        prev_target = prev.get("file", "")

        prev_tokens = _tokenize(prev_text)
        similarity = _jaccard(current_tokens, prev_tokens)

        if similarity >= text_threshold:
            # High text similarity — if same target, it's a retread
            if target and prev_target and target == prev_target:
                return "retread"
            # Even without same target, very high similarity is retread
            if similarity >= 0.85:
                return "retread"

    return "fresh"


# ---------------------------------------------------------------------------
# Yield grading
# ---------------------------------------------------------------------------


def yield_grade(fresh_ratio: float, exhausted_ratio: float) -> str:
    """Map quantitative ratios to a qualitative yield grade.

    Grades
    ------
    - *productive*: most strokes are fresh, few exhausted.
    - *warming*: some retreads but still mostly productive.
    - *looping*: more retreads than fresh, writer is cycling.
    - *exhausted*: explicit exhaustion signals dominate.
    """
    if exhausted_ratio >= 0.4:
        return "exhausted"
    if fresh_ratio >= 0.7:
        return "productive"
    if fresh_ratio >= 0.4:
        return "warming"
    return "looping"


# ---------------------------------------------------------------------------
# Saturation target detection
# ---------------------------------------------------------------------------


def find_saturation_targets(
    strokes: list[dict[str, Any]],
    top_n: int = 5,
) -> list[str]:
    """Find the files/topics most often associated with retread/exhausted strokes.

    Parameters
    ----------
    strokes : list[dict]
        All strokes (already classified).  Each should have a ``"file"`` key.
    top_n : int
        How many top targets to return.

    Returns
    -------
    list[str]
        Target names sorted by frequency (descending).
    """
    counter: Counter[str] = Counter()
    for stroke in strokes:
        category = stroke.get("_yield_category", "")
        if category in ("retread", "exhausted"):
            target = stroke.get("file", "")
            if target:
                counter[target] += 1
    return [t for t, _ in counter.most_common(top_n)]


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def analyse(
    strokes: list[dict[str, Any]],
    window: int = 20,
    text_threshold: float = 0.6,
) -> dict[str, Any]:
    """Analyse stroke yield over a sliding window.

    Parameters
    ----------
    strokes : list[dict]
        Chronological list of strokes (oldest first).
    window : int
        How many recent strokes to use as the analysis window.
    text_threshold : float
        Jaccard similarity threshold for retread detection.

    Returns
    -------
    dict with keys:
        - ``fresh_count`` (int)
        - ``retread_count`` (int)
        - ``exhausted_count`` (int)
        - ``total`` (int)
        - ``fresh_ratio`` (float)
        - ``retread_ratio`` (float)
        - ``exhausted_ratio`` (float)
        - ``yield_grade`` (str)
        - ``saturation_targets`` (list[str])
        - ``classifications`` (list[tuple[int, str]])
          — (stroke_index, category) for each stroke in the window.
    """
    if not strokes:
        return {
            "fresh_count": 0,
            "retread_count": 0,
            "exhausted_count": 0,
            "total": 0,
            "fresh_ratio": 0.0,
            "retread_ratio": 0.0,
            "exhausted_ratio": 0.0,
            "yield_grade": "productive",
            "saturation_targets": [],
            "classifications": [],
        }

    # Work on the most recent `window` strokes
    recent = strokes[-window:]
    # Build a growing context for classification
    classifications: list[tuple[int, str]] = []
    classified_strokes: list[dict[str, Any]] = []

    for i, stroke in enumerate(recent):
        context = recent[:i]  # everything before this stroke in window
        category = classify_stroke(stroke, context, text_threshold)
        classifications.append((i, category))
        # Annotate for saturation detection
        annotated = {**stroke, "_yield_category": category}
        classified_strokes.append(annotated)

    fresh_count = sum(1 for _, c in classifications if c == "fresh")
    retread_count = sum(1 for _, c in classifications if c == "retread")
    exhausted_count = sum(1 for _, c in classifications if c == "exhausted")
    total = len(classifications)

    fresh_ratio = fresh_count / total if total else 0.0
    retread_ratio = retread_count / total if total else 0.0
    exhausted_ratio = exhausted_count / total if total else 0.0

    return {
        "fresh_count": fresh_count,
        "retread_count": retread_count,
        "exhausted_count": exhausted_count,
        "total": total,
        "fresh_ratio": round(fresh_ratio, 4),
        "retread_ratio": round(retread_ratio, 4),
        "exhausted_ratio": round(exhausted_ratio, 4),
        "yield_grade": yield_grade(fresh_ratio, exhausted_ratio),
        "saturation_targets": find_saturation_targets(classified_strokes),
        "classifications": classifications,
    }


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/strokes.jsonl"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    strokes = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                strokes.append(json.loads(line))

    report = analyse(strokes, window=n)
    print(json.dumps({k: v for k, v in report.items()
                       if k != "classifications"}, indent=2))
    print(f"\nGrade: {report['yield_grade']}")
    if report["saturation_targets"]:
        print(f"Saturation targets: {', '.join(report['saturation_targets'])}")
