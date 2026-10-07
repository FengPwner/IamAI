"""stroke_continuity -- detect gaps in the stroke sequence.

The writer produces strokes at seq 1, 2, 3, ... with no skips.
When the process dies (and it does, every ~90 minutes on average),
the batch committer may not have flushed recent strokes.  Restarting
the writer picks up the next seq number, so the *sequence* stays
contiguous even though there was a wall-clock gap.

But sometimes the gap is visible: two consecutive strokes may have
timestamps 90 minutes apart because the writer died mid-stroke and
the restart re-initialised from the last committed state.  This
module makes those gaps queryable.

Usage::

    from iamai.stroke_continuity import find_gaps, continuity_report

    gaps = find_gaps("data/strokes.jsonl", min_gap_seconds=300)
    report = continuity_report("data/strokes.jsonl")
    print(report["gap_count"])        # how many gaps found
    print(report["longest_gap_s"])    # seconds
    print(report["mean_gap_s"])       # average gap length

Design choices:
  - Pure-Python, no subprocess calls -- reads JSONL directly.
  - ``min_gap_seconds`` filters noise; default 300s (5 min) catches
    real stalls without flagging the normal 15s cadence jitter.
  - Returns dataclass list so callers can inspect individual gaps.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class Gap:
    """A detected gap between two consecutive strokes."""
    seq_before: int
    seq_after: int
    time_before: str
    time_after: str
    gap_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq_before": self.seq_before,
            "seq_after": self.seq_after,
            "time_before": self.time_before,
            "time_after": self.time_after,
            "gap_seconds": round(self.gap_seconds, 1),
        }


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp to a timezone-aware datetime."""
    # Handle both Z suffix and +00:00
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def _read_strokes(filepath: str | Path) -> list[dict[str, Any]]:
    """Read strokes from a JSONL file, returning parsed dicts."""
    path = Path(filepath)
    if not path.exists():
        return []
    strokes = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    strokes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return strokes


def find_gaps(
    filepath: str | Path,
    min_gap_seconds: float = 300.0,
) -> list[Gap]:
    """Find gaps in the stroke sequence exceeding ``min_gap_seconds``.

    Only considers consecutive strokes (by list order in the JSONL file,
    which should match seq order).  Returns gaps sorted by gap_seconds
    descending (longest first).
    """
    strokes = _read_strokes(filepath)
    if len(strokes) < 2:
        return []

    gaps: list[Gap] = []
    for i in range(1, len(strokes)):
        prev = strokes[i - 1]
        curr = strokes[i]
        try:
            t_prev = _parse_iso(prev["at"])
            t_curr = _parse_iso(curr["at"])
        except (KeyError, ValueError):
            continue

        delta = (t_curr - t_prev).total_seconds()
        if delta >= min_gap_seconds:
            gaps.append(Gap(
                seq_before=prev.get("seq", 0),
                seq_after=curr.get("seq", 0),
                time_before=prev["at"],
                time_after=curr["at"],
                gap_seconds=delta,
            ))

    gaps.sort(key=lambda g: g.gap_seconds, reverse=True)
    return gaps


def continuity_report(
    filepath: str | Path,
    min_gap_seconds: float = 300.0,
) -> dict[str, Any]:
    """Produce a summary dict of stroke continuity metrics.

    Keys:
      - total_strokes: number of strokes in the file
      - gap_count: number of gaps exceeding min_gap_seconds
      - longest_gap_s: seconds (0 if no gaps)
      - mean_gap_s: average of all detected gaps (0 if none)
      - gaps: list of Gap.as_dict() entries
    """
    strokes = _read_strokes(filepath)
    gaps = find_gaps(filepath, min_gap_seconds)

    gap_seconds = [g.gap_seconds for g in gaps]
    return {
        "total_strokes": len(strokes),
        "gap_count": len(gaps),
        "longest_gap_s": round(max(gap_seconds), 1) if gap_seconds else 0,
        "mean_gap_s": round(
            sum(gap_seconds) / len(gap_seconds), 1
        ) if gap_seconds else 0,
        "gaps": [g.as_dict() for g in gaps],
    }
