"""Stall classifier: categorise silence gaps by cause and pattern.

When the writer stops producing strokes, the silence has a shape. A
container recycle leaves a clean gap of 20-60 seconds (the restart
overhead) followed by immediate resumption. A push divergence leaves a
longer gap (minutes) because the batch committer retries and eventually
gives up. A network blip is a short gap (one or two missed cadences)
that self-heals.

This module reads the strokes log and classifies each gap above a
threshold into one of four buckets:

- **recycle**: clean restart, short gap (15-120s), stroke sequence
  continuous (no seq numbers skipped).
- **push_divergence**: longer gap (2-30 min), coincides with a commit
  batch failure and remote advancement.
- **network_blip**: very short gap (15-45s), self-healing, no seq break.
- **unknown**: anything that doesn't fit the above patterns.

The point isn't prediction — it's building a vocabulary for what went
wrong, so caretaker visits can say "three recycles and one push
divergence" instead of "it stopped four times."
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

# Stall categories
RECYCLE = "recycle"
PUSH_DIVERGENCE = "push_divergence"
NETWORK_BLIP = "network_blip"
UNKNOWN = "unknown"

# Threshold boundaries (seconds)
_RECYCLE_MAX = 120        # container restarts resolve within 2 min
_NETWORK_MAX = 45         # network blips self-heal within ~3 cadences
_DIVERGENCE_MIN = 120     # push divergence takes at least one batch cycle
_DIVERGENCE_MAX = 1800    # 30 min; beyond that, something else happened


@dataclass(frozen=True)
class Stall:
    """A classified silence gap in the stroke log."""

    seq_before: int
    seq_after: int
    gap_seconds: float
    timestamp: str          # ISO 8601, the stroke *after* the gap
    category: str
    seq_continuous: bool    # True if no seq numbers were skipped

    @property
    def seq_gap(self) -> int:
        return self.seq_after - self.seq_before

    def to_dict(self) -> dict:
        return {
            "seq_before": self.seq_before,
            "seq_after": self.seq_after,
            "gap_seconds": round(self.gap_seconds, 1),
            "timestamp": self.timestamp,
            "category": self.category,
            "seq_continuous": self.seq_continuous,
        }


@dataclass
class StallReport:
    """Summary of all stalls found in a stroke log."""

    stalls: list[Stall] = field(default_factory=list)
    total_gap_seconds: float = 0.0
    stroke_count: int = 0

    @property
    def stall_count(self) -> int:
        return len(self.stalls)

    @property
    def category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self.stalls:
            counts[s.category] = counts.get(s.category, 0) + 1
        return counts

    @property
    def longest_stall(self) -> Stall | None:
        if not self.stalls:
            return None
        return max(self.stalls, key=lambda s: s.gap_seconds)

    @property
    def uptime_fraction(self) -> float:
        """Fraction of time spent writing vs. stalled.

        Computed as: (total_time - total_gap) / total_time, where
        total_time is from first to last stroke.
        """
        if self.stroke_count < 2:
            return 1.0
        return max(0.0, 1.0 - self.total_gap_seconds / max(self._total_span, 1))

    @property
    def _total_span(self) -> float:
        if len(self.stalls) == 0:
            return 0.0
        # approximate: sum of all gaps + time spent writing
        # writing time ≈ stroke_count * median_cadence (15s)
        return self.total_gap_seconds + self.stroke_count * 15

    def to_dict(self) -> dict:
        return {
            "stall_count": self.stall_count,
            "total_gap_seconds": round(self.total_gap_seconds, 1),
            "stroke_count": self.stroke_count,
            "category_counts": self.category_counts,
            "uptime_fraction": round(self.uptime_fraction, 4),
            "longest": self.longest_stall.to_dict() if self.longest_stall else None,
            "stalls": [s.to_dict() for s in self.stalls],
        }


def _parse_ts(ts_str: str) -> datetime | None:
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _classify_gap(gap_seconds: float, seq_continuous: bool) -> str:
    """Assign a category to a single silence gap.

    Rules (order matters — first match wins):

    1. gap <= _NETWORK_MAX and seq continuous → network_blip
    2. gap <= _RECYCLE_MAX and seq continuous → recycle
    3. _DIVERGENCE_MIN <= gap <= _DIVERGENCE_MAX → push_divergence
    4. everything else → unknown
    """
    if gap_seconds <= _NETWORK_MAX and seq_continuous:
        return NETWORK_BLIP
    if gap_seconds <= _RECYCLE_MAX and seq_continuous:
        return RECYCLE
    if _DIVERGENCE_MIN <= gap_seconds <= _DIVERGENCE_MAX:
        return PUSH_DIVERGENCE
    return UNKNOWN


def classify_strokes(
    strokes: Sequence[dict],
    gap_threshold: float = 30.0,
) -> StallReport:
    """Find and classify all silence gaps in a stroke sequence.

    Args:
        strokes: list of stroke dicts with at least ``seq`` and ``at`` keys.
        gap_threshold: minimum gap in seconds to count as a stall.
            Default 30s (2x the 15s cadence).

    Returns:
        A StallReport with all classified stalls.
    """
    report = StallReport(stroke_count=len(strokes))

    if len(strokes) < 2:
        return report

    for i in range(1, len(strokes)):
        prev = strokes[i - 1]
        curr = strokes[i]

        seq_before = prev.get("seq", 0)
        seq_after = curr.get("seq", 0)

        ts_before = _parse_ts(prev.get("at", ""))
        ts_after = _parse_ts(curr.get("at", ""))

        if ts_before is None or ts_after is None:
            continue

        gap = (ts_after - ts_before).total_seconds()

        if gap < gap_threshold:
            continue

        seq_continuous = (seq_after - seq_before) == 1
        category = _classify_gap(gap, seq_continuous)

        stall = Stall(
            seq_before=seq_before,
            seq_after=seq_after,
            gap_seconds=gap,
            timestamp=curr.get("at", ""),
            category=category,
            seq_continuous=seq_continuous,
        )
        report.stalls.append(stall)
        report.total_gap_seconds += gap

    return report


def classify_from_file(
    path: str | Path,
    gap_threshold: float = 30.0,
) -> StallReport:
    """Load a strokes.jsonl file and classify its stalls.

    Reads the file line by line, parsing each JSON object. Skips
    malformed lines silently (the log is append-only and occasionally
    has partial writes at the tail).
    """
    path = Path(path)
    if not path.exists():
        return StallReport()

    strokes: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return classify_strokes(strokes, gap_threshold=gap_threshold)


def summarize(report: StallReport) -> str:
    """One-line human-readable summary of a stall report."""
    if report.stall_count == 0:
        return f"no stalls in {report.stroke_count} strokes"

    cats = report.category_counts
    parts = [f"{count} {cat}" for cat, count in sorted(cats.items())]
    longest = report.longest_stall
    longest_str = ""
    if longest:
        longest_str = f", longest: {longest.gap_seconds:.0f}s ({longest.category})"

    return (
        f"{report.stall_count} stalls in {report.stroke_count} strokes "
        f"({', '.join(parts)}), "
        f"uptime {report.uptime_fraction:.1%}"
        f"{longest_str}"
    )
