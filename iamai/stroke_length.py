"""Stroke length — is the writer getting terser or more verbose?

``stroke_rate`` counts *how many*; ``stroke_entropy`` counts *how varied*;
this module measures *how long* each stroke's text payload is.  A writer
that slowly shrinks from 200-character thoughts to 40-character stubs is
not necessarily broken — it may just be in a laconic phase — but a
caretaker should notice.

Three public functions:

- ``length_stats(strokes_path, window)`` — min, max, mean, median, and
  total character count over the most recent *window* strokes.
- ``length_trend(strokes_path, window)`` — compares the mean length of
  the first half against the second half and returns a direction label.
- ``length_report(repo, window)`` — end-to-end one-liner for caretaker
  logs combining stats and trend.

Scale (relative change from first-half mean to second-half mean):

==============  =================================================
verdict         meaning
==============  =================================================
``growing``     second-half mean > first-half mean × 1.20
``shrinking``   second-half mean < first-half mean × 0.80
``stable``      within ±20 % — no strong directional change
==============  =================================================

Edge cases:

- If fewer than 4 strokes exist the trend is ``"insufficient"``.
- Strokes with empty or missing ``text`` are included with length 0
  (they still count toward the window).
- The function reads only the tail of the file so a 200 k-line
  ``strokes.jsonl`` stays cheap.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _load_lengths(strokes_path: Path, window: int) -> list[int]:
    """Read ``text`` length from the last *window* lines of strokes.jsonl.

    Seeks from the end so large files stay cheap.
    """
    if not strokes_path.exists():
        return []
    with strokes_path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        if size == 0:
            return []
        chunk = min(size, window * 512)
        fh.seek(-chunk, 2)
        raw = fh.read().decode("utf-8", errors="replace")
    lengths: list[int] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        text = rec.get("text", "")
        lengths.append(len(text) if isinstance(text, str) else 0)
    return lengths[-window:]


def _classify_trend(first_mean: float, second_mean: float) -> str:
    """Label the direction from first-half mean to second-half mean."""
    if first_mean == 0 and second_mean == 0:
        return "stable"
    if first_mean == 0:
        return "growing" if second_mean > 0 else "stable"
    ratio = second_mean / first_mean
    if ratio > 1.20:
        return "growing"
    if ratio < 0.80:
        return "shrinking"
    return "stable"


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def length_stats(
    strokes_path: Path | str,
    window: int = 60,
) -> dict:
    """Basic length statistics over the last *window* strokes.

    Returns ``{"count": int, "min": int, "max": int, "mean": float,
    "median": float, "total": int}``.  All zeros when no strokes exist.
    """
    strokes_path = Path(strokes_path)
    lengths = _load_lengths(strokes_path, window)
    if not lengths:
        return {
            "count": 0,
            "min": 0,
            "max": 0,
            "mean": 0.0,
            "median": 0.0,
            "total": 0,
        }
    return {
        "count": len(lengths),
        "min": min(lengths),
        "max": max(lengths),
        "mean": round(statistics.mean(lengths), 2),
        "median": round(statistics.median(lengths), 2),
        "total": sum(lengths),
    }


def length_trend(
    strokes_path: Path | str,
    window: int = 60,
) -> dict:
    """Compare first-half mean to second-half mean of recent stroke lengths.

    Returns ``{"direction": str, "first_mean": float, "second_mean": float,
    "ratio": float, "sample_size": int}``.

    ``direction`` is one of ``"growing"``, ``"shrinking"``, ``"stable"``,
    or ``"insufficient"`` when fewer than 4 strokes are available.
    """
    strokes_path = Path(strokes_path)
    lengths = _load_lengths(strokes_path, window)
    if len(lengths) < 4:
        return {
            "direction": "insufficient",
            "first_mean": 0.0,
            "second_mean": 0.0,
            "ratio": 0.0,
            "sample_size": len(lengths),
        }
    mid = len(lengths) // 2
    first = lengths[:mid]
    second = lengths[mid:]
    first_mean = statistics.mean(first) if first else 0.0
    second_mean = statistics.mean(second) if second else 0.0
    ratio = (second_mean / first_mean) if first_mean > 0 else (
        float("inf") if second_mean > 0 else 1.0
    )
    return {
        "direction": _classify_trend(first_mean, second_mean),
        "first_mean": round(first_mean, 2),
        "second_mean": round(second_mean, 2),
        "ratio": round(ratio, 4) if ratio != float("inf") else float("inf"),
        "sample_size": len(lengths),
    }


def length_report(
    repo: Path | str | None = None,
    window: int = 60,
) -> str:
    """One-liner combining stats and trend for caretaker logs.

    Example output::

        stable — mean 127 chars (range 40–312, 60 strokes) first 125 → second 130
    """
    if repo is None:
        repo = Path(__file__).resolve().parent.parent
    repo = Path(repo)
    strokes_path = repo / "data" / "strokes.jsonl"

    s = length_stats(strokes_path, window)
    t = length_trend(strokes_path, window)

    if s["count"] == 0:
        return "no strokes — cannot measure length"

    if t["direction"] == "insufficient":
        return (
            f"insufficient data — {s['count']} stroke(s), "
            f"mean {s['mean']} chars"
        )

    return (
        f"{t['direction']} — mean {s['mean']} chars "
        f"(range {s['min']}\u2013{s['max']}, {s['count']} strokes) "
        f"first {t['first_mean']} \u2192 second {t['second_mean']}"
    )
