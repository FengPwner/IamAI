"""Pool diversity — detect when the writer cycles the same small subset.

A healthy writer should explore the full module pool over time.  When it
gets stuck repeating the same handful of modules (e.g. ``retry.py``,
``chunk_text.py``, ``parse_kv.py`` in an endless loop), throughput looks
fine but *novelty* is zero.  The repo accumulates strokes without
accumulating knowledge.

This module analyses the last *N* strokes and reports:

- ``unique_ratio``: fraction of distinct module references in the window
- ``repeat_streak``: longest run of consecutive strokes hitting only
  previously-seen modules (the "hamster wheel" length)
- ``verdict``: one of ``diverse``, ``narrowing``, ``stuck``

Usage::

    from iamai.pool_diversity import pool_diversity

    info = pool_diversity(strokes_path, window=100)
    print(info["verdict"])        # "stuck"
    print(info["unique_ratio"])   # 0.09
    print(info["repeat_streak"])  # 87

Thresholds (configurable):

===========  =========================  ======================
verdict      unique_ratio >=            repeat_streak <
===========  =========================  ======================
``diverse``   0.5                        (no limit)
``narrowing`` 0.2                        50
``stuck``     < 0.2  **or**              >= 50
===========  =========================  ======================

A stuck verdict should trigger a caretaker intervention: rotate the
module pool, inject a fresh seed topic, or restart the writer with a
different prompt schedule.
"""

from __future__ import annotations

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_MODULE_RE = re.compile(r"`([a-zA-Z_][a-zA-Z0-9_]*\.py)`")


def _extract_modules(text: str) -> list[str]:
    """Return module filenames mentioned in *text*."""
    return _MODULE_RE.findall(text)


def _read_last_n(path: Path, n: int) -> list[str]:
    """Read the last *n* lines from a file, oldest-first."""
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    return lines[-n:] if len(lines) >= n else lines


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def pool_diversity(
    strokes_path: str | Path,
    window: int = 100,
    stuck_ratio: float = 0.2,
    stuck_streak: int = 50,
) -> dict:
    """Analyse module-reference diversity in the last *window* strokes.

    Returns a dict with keys:
        ``window``         — number of strokes examined
        ``unique_modules`` — set of distinct module names seen
        ``unique_ratio``   — len(unique) / window  (clamped to 1.0)
        ``repeat_streak``  — longest consecutive run of already-seen modules
        ``verdict``        — ``"diverse"`` | ``"narrowing"`` | ``"stuck"``
    """
    import json as _json  # local to avoid circular at import time

    path = Path(strokes_path)
    lines = _read_last_n(path, window)
    if not lines:
        return {
            "window": 0,
            "unique_modules": set(),
            "unique_ratio": 0.0,
            "repeat_streak": 0,
            "verdict": "stuck",
        }

    seen: set[str] = set()
    max_streak = 0
    cur_streak = 0
    all_modules: list[str] = []

    for line in lines:
        try:
            obj = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        text = obj.get("text", "")
        mods = _extract_modules(text)
        all_modules.extend(mods)
        # a stroke counts as "repeat" if every module it mentions was seen
        if mods and all(m in seen for m in mods):
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0
        seen.update(mods)

    n = len(lines)
    ratio = min(len(seen) / n, 1.0) if n else 0.0

    if ratio < stuck_ratio or max_streak >= stuck_streak:
        verdict = "stuck"
    elif ratio < 0.5 or max_streak >= 30:
        verdict = "narrowing"
    else:
        verdict = "diverse"

    return {
        "window": n,
        "unique_modules": seen,
        "unique_ratio": round(ratio, 4),
        "repeat_streak": max_streak,
        "verdict": verdict,
    }


def diversity_report(strokes_path: str | Path, window: int = 100) -> str:
    """One-line human-readable diversity summary."""
    info = pool_diversity(strokes_path, window=window)
    n = info["window"]
    if n == 0:
        return "stuck — no strokes to analyse"
    u = len(info["unique_modules"])
    return (
        f"{info['verdict']} — {u} unique modules in last {n} strokes "
        f"(ratio {info['unique_ratio']:.2f}, streak {info['repeat_streak']})"
    )
