"""Pool saturation — detect when the snippet pool is fully deployed.

The writer rotates through six kinds.  One of them is ``snippet``: pick a
module from ``iamai.pool.SNIPPETS`` and write it to ``snippets/``.  Once
every snippet file already exists on disk, every subsequent ``snippet``
stroke degrades into a one-liner in ``notes/history.md``::

    stroke 20651: ``parse_kv.py`` is already in the pool of 9 modules,
    nothing new to add there

This is not a bug — it is the designed fallback.  But it *is* a signal:
the pool is saturated.  The writer is spending 1/6 of its strokes saying
"nothing new to add" on repeat.

This module measures that waste.

Model
-----

``measure`` takes a list of recent stroke texts (from ``data/strokes.jsonl``
or the last N lines of ``notes/history.md``) and returns a dict::

    {
        "window": 60,          # strokes examined
        "exhausted": 22,       # "nothing new to add" strokes
        "fraction": 0.367,     # exhausted / window
        "verdict": "saturated" # one of: fresh / warming / saturated
    }

Verdicts:

=========  ============================================================
verdict    meaning
=========  ============================================================
fresh      fraction < 0.10 — pool still has undeployed snippets
warming    0.10 <= fraction < 0.25 — some snippets already on disk
saturated  fraction >= 0.25 — most snippet strokes are waste
=========  ============================================================

The 0.25 threshold is not arbitrary: with 6 equally-weighted kinds, a
saturated pool produces 1/6 ≈ 0.167 exhausted strokes.  In practice the
rotation is not perfectly even (the LCG has short-period clumps), so the
measured fraction oscillates around 0.15–0.20 once fully saturated.  The
0.25 threshold catches the common case where *additional* snippet-kind
strokes land on already-covered pool entries.

Design choices
--------------

- **Text-based detection.**  Rather than checking which files exist on
  disk (which only gives a point-in-time snapshot), we scan recent stroke
  output.  This catches transient saturation even if someone deletes a
  snippet file and the writer briefly has something new to deploy.
- **Configurable window and thresholds** so caretakers can tune for
  different pool sizes.
- **Pure function.**  No git, no filesystem, just string matching on a
  list of texts.  The caller decides where the texts come from.
"""

from __future__ import annotations

import re
from typing import Sequence

# The exact phrase the writer emits when a snippet already exists on disk.
_SATURATION_MARKER = "nothing new to add there"

_DEFAULT_WINDOW = 60
_THRESHOLDS = {
    "fresh": 0.10,
    "warming": 0.25,
    # anything >= 0.25 is "saturated"
}


def _is_exhausted(text: str) -> bool:
    """True when a stroke text is the 'nothing new to add' fallback."""
    return _SATURATION_MARKER in text


def measure(
    strokes: Sequence[str],
    window: int = _DEFAULT_WINDOW,
) -> dict:
    """Measure pool saturation from recent stroke texts.

    Parameters
    ----------
    strokes:
        Recent stroke body texts, oldest first.  Only the last ``window``
        entries are examined.
    window:
        How many recent strokes to scan.  Default 60 (≈ 6 full rotations
        through the 6 kinds at one stroke every 15 s ≈ 15 min of output).

    Returns
    -------
    dict with keys ``window``, ``exhausted``, ``fraction``, ``verdict``.
    """
    recent = list(strokes)[-window:] if strokes else []
    n = len(recent)
    if n == 0:
        return {
            "window": 0,
            "exhausted": 0,
            "fraction": 0.0,
            "verdict": "fresh",
        }

    exhausted = sum(1 for t in recent if _is_exhausted(t))
    fraction = exhausted / n

    if fraction < _THRESHOLDS["fresh"]:
        verdict = "fresh"
    elif fraction < _THRESHOLDS["warming"]:
        verdict = "warming"
    else:
        verdict = "saturated"

    return {
        "window": n,
        "exhausted": exhausted,
        "fraction": round(fraction, 4),
        "verdict": verdict,
    }


def saturation_report(strokes: Sequence[str], window: int = _DEFAULT_WINDOW) -> str:
    """One-liner for caretaker logs.

    >>> saturation_report(["stroke 1: normal work"] * 60)
    'pool fresh: 0/60 strokes exhausted (0.0%)'

    >>> saturation_report(["nothing new to add there"] * 30 + ["normal"] * 30)
    'pool saturated: 30/60 strokes exhausted (50.0%)'
    """
    m = measure(strokes, window)
    pct = m["fraction"] * 100
    return (
        f"pool {m['verdict']}: "
        f"{m['exhausted']}/{m['window']} strokes exhausted ({pct:.1f}%)"
    )
