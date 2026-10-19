"""stroke_tide — is the writer accelerating or decelerating?

Heartbeat answers "is the writer alive *right now*?"  Tide answers a
different question: "is the writer getting *faster* or *slower* over the
last few minutes?"

This matters because a writer that is steadily decelerating — strokes
arriving at 15s, then 22s, then 35s, then 50s — is usually heading toward
a stall even though every individual gap still looks "healthy" to the
binary heartbeat check.  Tide gives the caretaker an early-warning signal
before the stall actually happens.

Approach:

1. Read the last ``window`` strokes from ``data/strokes.jsonl``.
2. Compute inter-stroke gaps (seconds between consecutive strokes).
3. Split the gaps into a first half and a second half.
4. Compare the median of each half.

Classification (at default cadence = 15s)::

    second_median < first_median × 0.8   →  accelerating
    second_median > first_median × 1.5   →  decelerating
    otherwise                             →  steady

Why medians instead of means: a single long gap (writer paused for a
garbage-collection blip) would dominate the mean and flip the verdict.
Medians are robust to one-off outliers.

Why halves instead of linear regression: regression is more precise but
also more code, harder to explain in a caretaker log, and overkill for a
signal that only needs to be directionally correct.  If the writer is
noticeably slowing down, the caretaker wants to know; if it's roughly
steady, that's fine.

Edge cases:

- File missing or empty → gaps = [], tide = "unknown".
- Fewer than 4 strokes → gaps < 3, not enough for a meaningful split;
  tide = "unknown".
- All gaps identical → "steady" (correct).

Usage::

    from iamai.stroke_tide import tide, tide_report
    verdict = tide(Path("data/strokes.jsonl"))
    print(verdict)  # "accelerating" | "steady" | "decelerating" | "unknown"
    print(tide_report(Path("data/strokes.jsonl")))
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

DEFAULT_CADENCE = 15   # seconds between strokes
DEFAULT_WINDOW = 20    # how many recent strokes to inspect
ACCEL_RATIO = 0.8      # second half < first × this → accelerating
DECEL_RATIO = 1.5      # second half > first × this → decelerating


def _parse_iso(ts: str) -> float:
    """Parse an ISO-8601 timestamp to epoch seconds."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).timestamp()


def _tail_timestamps(path: Path, n: int) -> List[float]:
    """Read the last *n* valid timestamps from a strokes.jsonl file."""
    if not path.exists():
        return []
    timestamps: List[float] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                ts = row.get("at", "")
                timestamps.append(_parse_iso(ts))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
    return timestamps[-n:]


def _gaps(timestamps: List[float]) -> List[float]:
    """Compute inter-stroke gaps from a sorted list of epoch timestamps."""
    if len(timestamps) < 2:
        return []
    return [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]


def tide(
    path: Path,
    cadence: int = DEFAULT_CADENCE,
    window: int = DEFAULT_WINDOW,
) -> str:
    """Classify the recent stroke-rate trend.

    Returns one of: ``"accelerating"``, ``"steady"``, ``"decelerating"``,
    or ``"unknown"``.
    """
    timestamps = _tail_timestamps(path, window)
    gaps = _gaps(timestamps)

    if len(gaps) < 2:
        return "unknown"

    mid = len(gaps) // 2
    first_half = gaps[:mid]
    second_half = gaps[mid:]

    if not first_half or not second_half:
        return "unknown"

    first_med = statistics.median(first_half)
    second_med = statistics.median(second_half)

    if first_med == 0:
        return "unknown"

    if second_med < first_med * ACCEL_RATIO:
        return "accelerating"
    elif second_med > first_med * DECEL_RATIO:
        return "decelerating"
    else:
        return "steady"


def tide_stats(
    path: Path,
    window: int = DEFAULT_WINDOW,
) -> dict:
    """Return detailed tide statistics for dashboard consumption."""
    timestamps = _tail_timestamps(path, window)
    gaps = _gaps(timestamps)

    if len(gaps) < 2:
        return {
            "verdict": "unknown",
            "stroke_count": len(timestamps),
            "gap_count": len(gaps),
            "first_half_median": None,
            "second_half_median": None,
            "ratio": None,
        }

    mid = len(gaps) // 2
    first_half = gaps[:mid]
    second_half = gaps[mid:]

    first_med = statistics.median(first_half)
    second_med = statistics.median(second_half)
    ratio = second_med / first_med if first_med > 0 else None

    return {
        "verdict": tide(path, window=window),
        "stroke_count": len(timestamps),
        "gap_count": len(gaps),
        "first_half_median": round(first_med, 1),
        "second_half_median": round(second_med, 1),
        "ratio": round(ratio, 3) if ratio is not None else None,
    }


def tide_report(
    path: Path,
    cadence: int = DEFAULT_CADENCE,
    window: int = DEFAULT_WINDOW,
) -> str:
    """One-liner suitable for caretaker logs."""
    s = tide_stats(path, window=window)
    if s["verdict"] == "unknown":
        return f"tide: unknown ({s['stroke_count']} strokes, {s['gap_count']} gaps)"
    return (
        f"tide: {s['verdict']} — "
        f"first½ {s['first_half_median']}s, "
        f"second½ {s['second_half_median']}s, "
        f"ratio {s['ratio']} "
        f"({s['stroke_count']} strokes)"
    )
