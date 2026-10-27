"""stroke_loop_breaker — detect when the writer is stuck cycling through the same modules.

the writer sometimes enters a repetitive loop: it keeps producing strokes
that reference the same small set of module names without generating any
new content.  this module analyses recent stroke entries and quantifies
the repetition.

loop score::

    loop_score = 1 - (unique_modules / total_strokes_in_window)

    clamped to [0.0, 1.0]

severity bands:

===========  ============  =============================================
band         score         meaning
===========  ============  =============================================
healthy      0.00–0.29     good variety, writer is exploring
mild         0.30–0.59     some repetition but acceptable
stuck        0.60–0.89     writer is mostly cycling the same few modules
dead_loop    0.90–1.00     near-total repetition, intervention needed
===========  ============  =============================================

usage::

    from iamai.stroke_loop_breaker import analyse_strokes, loop_report

    strokes = [
        {"module": "retry.py", "text": "already in the pool"},
        {"module": "chunk_text.py", "text": "already in the pool"},
        {"module": "parse_kv.py", "text": "already in the pool"},
        {"module": "retry.py", "text": "already in the pool"},
    ]
    result = loop_report(strokes, window=10)
    print(result["score"])      # 0.75
    print(result["band"])       # "stuck"
    print(result["summary"])    # "3 unique modules over 4 strokes (score 0.75, stuck)"
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# severity bands
# ---------------------------------------------------------------------------

_BANDS = [
    (0.30, "healthy"),
    (0.60, "mild"),
    (0.90, "stuck"),
    (float("inf"), "dead_loop"),
]


def _band(score: float) -> str:
    """Map a loop score to its severity band."""
    for threshold, label in _BANDS:
        if score < threshold:
            return label
    return "dead_loop"


# ---------------------------------------------------------------------------
# stroke parsing
# ---------------------------------------------------------------------------

_MODULE_RE = re.compile(r"`?([a-zA-Z_][a-zA-Z0-9_]*\.py)`?")


def extract_module(text: str) -> Optional[str]:
    """Extract the first .py module name mentioned in a stroke text."""
    m = _MODULE_RE.search(text)
    return m.group(1) if m else None


def normalise_strokes(raw: List[Any]) -> List[str]:
    """Accept a list of stroke dicts or strings; return a list of module names.

    Each element may be:
    - a dict with "module" key  → use that directly
    - a dict with "text" key    → extract module from text
    - a plain string            → extract module from text
    Elements that yield no module are skipped.
    """
    modules: list[str] = []
    for entry in raw:
        if isinstance(entry, dict):
            mod = entry.get("module")
            if not mod and "text" in entry:
                mod = extract_module(str(entry["text"]))
            if mod:
                modules.append(mod)
        elif isinstance(entry, str):
            mod = extract_module(entry)
            if mod:
                modules.append(mod)
    return modules


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------


def analyse_strokes(
    strokes: List[Any],
    window: int = 30,
) -> Dict[str, Any]:
    """Analyse the most recent *window* strokes for repetition.

    Returns a dict with:
    - total: number of analysable strokes in the window
    - unique: number of unique modules referenced
    - score: loop score in [0.0, 1.0]
    - band: severity label
    - top_modules: list of (module, count) pairs sorted by frequency
    - repeated_modules: list of modules appearing more than once
    """
    modules = normalise_strokes(strokes)
    recent = modules[-window:] if len(modules) > window else modules
    total = len(recent)

    if total == 0:
        return {
            "total": 0,
            "unique": 0,
            "score": 0.0,
            "band": "healthy",
            "top_modules": [],
            "repeated_modules": [],
        }

    counts = Counter(recent)
    unique = len(counts)
    raw_score = 1.0 - (unique / total)
    score = max(0.0, min(1.0, raw_score))
    band = _band(score)

    top = counts.most_common()
    repeated = [m for m, c in top if c > 1]

    return {
        "total": total,
        "unique": unique,
        "score": round(score, 4),
        "band": band,
        "top_modules": top,
        "repeated_modules": repeated,
    }


def loop_report(
    strokes: List[Any],
    window: int = 30,
) -> Dict[str, Any]:
    """Produce a human-readable loop analysis report.

    Returns the analyse_strokes result plus a "summary" string.
    """
    result = analyse_strokes(strokes, window=window)
    total = result["total"]
    unique = result["unique"]
    score = result["score"]
    band = result["band"]

    if total == 0:
        result["summary"] = "no analysable strokes in window"
    else:
        result["summary"] = (
            f"{unique} unique module{'s' if unique != 1 else ''} "
            f"over {total} stroke{'s' if total != 1 else ''} "
            f"(score {score}, {band})"
        )

    return result


# ---------------------------------------------------------------------------
# history file parsing
# ---------------------------------------------------------------------------

_STROKE_LINE_RE = re.compile(
    r"-\s+stroke\s+(\d+):\s+`([^`]+)`\s+is\s+already\s+in\s+the\s+pool",
    re.IGNORECASE,
)


def parse_history_lines(lines: List[str]) -> List[Dict[str, str]]:
    """Parse lines from notes/history.md into stroke dicts.

    Each matching line yields {"stroke_id": "33599", "module": "retry.py"}.
    Non-matching lines are skipped.
    """
    results: list[dict[str, str]] = []
    for line in lines:
        m = _STROKE_LINE_RE.search(line)
        if m:
            results.append({"stroke_id": m.group(1), "module": m.group(2)})
    return results
