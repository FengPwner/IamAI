"""Stroke pause — detect concerning silences between consecutive strokes.

``stroke_rate`` counts *how many*; ``stroke_freshness`` asks *how recent*;
this module measures *how quiet* the gaps are.  A writer that normally
emits a stroke every 15 seconds but occasionally goes silent for ten
minutes is not necessarily broken — it may be waiting on a slow batch —
but a caretaker should notice.

Three public functions:

- ``detect_pauses(strokes_path, window, threshold_seconds)`` — list of
  pauses exceeding *threshold_seconds* within the most recent *window*
  strokes.
- ``longest_pauses(strokes_path, window, top_n)`` — the *top_n* longest
  pauses regardless of threshold.
- ``pause_report(repo, window, threshold_seconds)`` — end-to-end
  one-liner for caretaker logs.

Scale (single gap between consecutive strokes):

==============  =================================================
verdict         meaning
==============  =================================================
``normal``      gap ≤ threshold_seconds
``elongated``   threshold < gap ≤ 2 × threshold
``stalled``     gap > 2 × threshold_seconds
==============  =================================================

Edge cases:

- If fewer than 2 strokes exist the result is an empty list (no gaps
  to measure).
- Strokes with unparseable ``at`` fields are silently skipped — the
  gap *around* them is simply not measured.
- The function reads only the tail of the file so a 200 k-line
  ``strokes.jsonl`` stays cheap.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, returning None on failure."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        # Handle the +00:00 suffix that Python < 3.11 fromisoformat chokes on
        cleaned = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None


def _load_timestamps(strokes_path: Path, window: int) -> list[datetime]:
    """Read ``at`` timestamps from the last *window* lines of strokes.jsonl.

    Seeks from the end so large files stay cheap.  Unparseable timestamps
    are silently dropped.
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
    timestamps: list[datetime] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        dt = _parse_iso(rec.get("at", ""))
        if dt is not None:
            timestamps.append(dt)
    return timestamps[-window:]


def _classify_gap(seconds: float, threshold: float) -> str:
    """Label a single gap duration relative to the threshold."""
    if seconds <= threshold:
        return "normal"
    if seconds <= 2 * threshold:
        return "elongated"
    return "stalled"


def _compute_gaps(
    timestamps: list[datetime],
) -> list[dict]:
    """Compute gaps between consecutive timestamps.

    Returns a list of dicts: ``{"after_seq": int, "gap_seconds": float,
    "before_at": str, "after_at": str}``.  The ``after_seq`` is the
    0-based index into the timestamp list (not the stroke seq number,
    which we don't have here).
    """
    gaps: list[dict] = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        gaps.append({
            "index": i,
            "gap_seconds": round(delta, 1),
            "before_at": timestamps[i - 1].isoformat(),
            "after_at": timestamps[i].isoformat(),
        })
    return gaps


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def detect_pauses(
    strokes_path: Path | str,
    window: int = 60,
    threshold_seconds: float = 120.0,
) -> list[dict]:
    """Find pauses exceeding *threshold_seconds* in the last *window* strokes.

    Returns a list of dicts sorted by ``gap_seconds`` descending::

        [{"index": int, "gap_seconds": float,
          "before_at": str, "after_at": str, "verdict": str}, ...]

    An empty list means every gap was within threshold.
    """
    strokes_path = Path(strokes_path)
    timestamps = _load_timestamps(strokes_path, window)
    if len(timestamps) < 2:
        return []
    gaps = _compute_gaps(timestamps)
    flagged = []
    for g in gaps:
        if g["gap_seconds"] > threshold_seconds:
            g["verdict"] = _classify_gap(g["gap_seconds"], threshold_seconds)
            flagged.append(g)
    flagged.sort(key=lambda d: d["gap_seconds"], reverse=True)
    return flagged


def longest_pauses(
    strokes_path: Path | str,
    window: int = 60,
    top_n: int = 5,
) -> list[dict]:
    """Return the *top_n* longest pauses regardless of threshold.

    Each dict includes ``gap_seconds``, ``before_at``, ``after_at``,
    and ``index``.  Returns fewer than *top_n* if not enough gaps exist.
    """
    strokes_path = Path(strokes_path)
    timestamps = _load_timestamps(strokes_path, window)
    if len(timestamps) < 2:
        return []
    gaps = _compute_gaps(timestamps)
    gaps.sort(key=lambda d: d["gap_seconds"], reverse=True)
    return gaps[:top_n]


def pause_report(
    repo: Path | str | None = None,
    window: int = 60,
    threshold_seconds: float = 120.0,
) -> str:
    """One-liner combining pause count and worst gap for caretaker logs.

    Example output::

        2 pauses > 120s in last 60 strokes — worst: 340.2s (stalled)
    """
    if repo is None:
        repo = Path(__file__).resolve().parent.parent
    repo = Path(repo)
    strokes_path = repo / "data" / "strokes.jsonl"

    timestamps = _load_timestamps(strokes_path, window)
    if len(timestamps) < 2:
        return "insufficient data — fewer than 2 strokes"

    pauses = detect_pauses(strokes_path, window, threshold_seconds)
    if not pauses:
        return (
            f"no pauses > {threshold_seconds:.0f}s "
            f"in last {len(timestamps)} strokes"
        )

    worst = pauses[0]
    return (
        f"{len(pauses)} pause(s) > {threshold_seconds:.0f}s "
        f"in last {len(timestamps)} strokes — "
        f"worst: {worst['gap_seconds']}s ({worst['verdict']})"
    )
