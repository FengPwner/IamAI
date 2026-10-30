"""writer_heartbeat — is the writer actually alive right now?

Cadence adherence measures whether strokes arrive *on schedule* over a long
window.  Heartbeat is the sharper, shorter-range companion: look at the last
few strokes and decide whether the writer has stalled *right now*.

Three public functions:

- ``pulse(strokes_path)`` — read the tail of ``data/strokes.jsonl`` and
  return the last ``window`` inter-stroke gaps in seconds.
- ``diagnose(gaps, cadence)`` — classify the heartbeat into one of
  ``healthy``, ``irregular``, or ``stalled``.
- ``report(strokes_path, cadence, window)`` — one-liner for caretaker logs.

Interpretation (cadence = 15s default)::

    max(gaps) <  2 × cadence   →  healthy    (writer is on time)
    max(gaps) < 20 × cadence   →  irregular  (writer missed a beat or two)
    max(gaps) ≥ 20 × cadence   →  stalled    (writer is probably dead)

Why this matters: the batch committer only wakes every 600s.  If the writer
dies silently at minute 3 of a cycle, the committer won't notice for another
7 minutes.  Heartbeat detects the stall faster than "no commits landed".

Edge cases:

- File missing or empty → gaps = [], diagnosis = "unknown".
- Only one stroke → gaps = [], diagnosis = "unknown".
- Non-numeric / missing ``at`` field → that stroke is skipped.

Usage::

    from iamai.writer_heartbeat import pulse, diagnose, report
    gaps = pulse(Path("data/strokes.jsonl"))
    print(diagnose(gaps))               # "healthy" | "irregular" | "stalled"
    print(report(Path("data/strokes.jsonl")))
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Tuple

DEFAULT_CADENCE = 15  # seconds between strokes
DEFAULT_WINDOW = 10   # how many recent gaps to inspect
STALL_MULTIPLE = 20   # cadence × this = stall threshold


def _parse_iso(ts: str) -> float:
    """Parse an ISO-8601 timestamp to epoch seconds.

    Accepts trailing 'Z' or ±HH:MM offsets.  Raises ValueError on anything
    else so callers can skip malformed rows.
    """
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).timestamp()


def _tail_timestamps(strokes_path: Path, n: int) -> List[float]:
    """Read the last ``n + 1`` parseable timestamps from the strokes log.

    We need n+1 rows to produce n gaps.  Reading the whole file is fine —
    the log is append-only and rarely exceeds a few MB — but we only keep
    the tail to stay O(window) in memory for the returned list.
    """
    if not strokes_path.exists():
        return []

    all_ts: List[float] = []
    # Read backwards is overkill; a simple slice of the last N lines is
    # enough since each stroke is one JSON object on a single line.
    with strokes_path.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    needed = n + 1
    # Read a bit extra to absorb malformed rows; collect ALL valid timestamps
    # in that tail slice, then keep only the last ``needed`` of them.
    for raw in lines[-(needed * 4):]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
            ts = obj.get("at")
            if not isinstance(ts, str):
                continue
            all_ts.append(_parse_iso(ts))
        except (ValueError, json.JSONDecodeError):
            continue

    return sorted(all_ts[-needed:])


def pulse(strokes_path: Path, window: int = DEFAULT_WINDOW) -> List[float]:
    """Return the last ``window`` inter-stroke gaps in seconds."""
    if window <= 0:
        return []
    timestamps = _tail_timestamps(strokes_path, window)
    if len(timestamps) < 2:
        return []
    return [b - a for a, b in zip(timestamps, timestamps[1:])]


def diagnose(
    gaps: Iterable[float],
    cadence: float = DEFAULT_CADENCE,
    stall_multiple: float = STALL_MULTIPLE,
) -> str:
    """Classify the heartbeat from a sequence of recent gaps."""
    gap_list = list(gaps)
    if not gap_list:
        return "unknown"

    worst = max(gap_list)
    healthy_ceiling = 2 * cadence
    stall_ceiling = stall_multiple * cadence

    if worst < healthy_ceiling:
        return "healthy"
    if worst < stall_ceiling:
        return "irregular"
    return "stalled"


def stats(gaps: Iterable[float]) -> Tuple[float, float, float]:
    """(min, mean, max) of the supplied gaps, or (0, 0, 0) if empty."""
    gap_list = list(gaps)
    if not gap_list:
        return 0.0, 0.0, 0.0
    return min(gap_list), sum(gap_list) / len(gap_list), max(gap_list)


def report(
    strokes_path: Path,
    cadence: float = DEFAULT_CADENCE,
    window: int = DEFAULT_WINDOW,
) -> str:
    """One-liner summary suitable for caretaker visit logs."""
    gaps = pulse(strokes_path, window=window)
    verdict = diagnose(gaps, cadence=cadence)
    lo, mean, hi = stats(gaps)
    if verdict == "unknown":
        return f"heartbeat: unknown (insufficient data from {strokes_path})"
    return (
        f"heartbeat: {verdict} over last {len(gaps)} gaps "
        f"(min={lo:.0f}s mean={mean:.0f}s max={hi:.0f}s, cadence={cadence:.0f}s)"
    )
