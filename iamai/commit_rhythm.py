"""commit_rhythm — measure how regularly commits land on the expected cadence.

The batch committer targets a 10-minute interval (``--interval 600``).
A healthy repo commits like a metronome; a sick one commits in bursts
separated by silence.  This module quantifies the difference.

Given a list of commit timestamps (ISO-8601 strings or datetimes), it
computes:

- **gaps** — seconds between consecutive commits
- **mean_gap** / **median_gap** — central tendency of gaps
- **max_gap** — longest silence between two commits
- **cv** — coefficient of variation (stdev / mean); low = regular
- **cadence_hit_rate** — fraction of gaps within ±25 % of the target
- **verdict** — one of ``regular``, ``irregular``, ``bursty``, ``stalled``

Verdict rules
-------------
- **regular**   — cv ≤ 0.30 *and* cadence_hit_rate ≥ 0.70
- **irregular** — cv ≤ 0.60 *and* cadence_hit_rate ≥ 0.40
- **bursty**    — cv > 0.60 *or* max_gap > 3× target
- **stalled**   — the trailing gap (since the last commit) exceeds 2× target

The trailing gap is checked first: even if historical rhythm was perfect,
a 25-minute silence right now means stalled.

Usage::

    from iamai.commit_rhythm import rhythm_report, rhythm_summary

    report = rhythm_report(timestamps, target_seconds=600)
    print(rhythm_summary(report))
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RhythmReport:
    """Summary of commit timing regularity."""

    commit_count: int = 0
    gaps: list[float] = field(default_factory=list)
    mean_gap: float = 0.0
    median_gap: float = 0.0
    max_gap: float = 0.0
    min_gap: float = 0.0
    stdev_gap: float = 0.0
    cv: float = 0.0
    cadence_hit_rate: float = 0.0
    trailing_gap: float = 0.0
    target_seconds: float = 600.0
    verdict: str = "unknown"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_ts(raw: str | datetime) -> Optional[datetime]:
    """Accept ISO-8601 string or datetime; return UTC-aware datetime or None."""
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    # Normalise 'Z' suffix for fromisoformat (Python < 3.11)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _to_epoch(dt: datetime) -> float:
    return dt.timestamp()


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_gaps(timestamps: Sequence[str | datetime]) -> list[float]:
    """Return sorted-chronological list of inter-commit gaps in seconds."""
    parsed = [_parse_ts(t) for t in timestamps]
    parsed = [p for p in parsed if p is not None]
    if len(parsed) < 2:
        return []
    epochs = sorted(_to_epoch(p) for p in parsed)
    return [epochs[i + 1] - epochs[i] for i in range(len(epochs) - 1)]


def _classify(
    cv: float,
    cadence_hit_rate: float,
    max_gap: float,
    trailing_gap: float,
    target: float,
) -> str:
    """Apply verdict rules in priority order."""
    # Stalled takes priority: current silence is too long
    if trailing_gap > 2.0 * target:
        return "stalled"
    # Bursty: high variance or extreme outlier gap
    if cv > 0.60 or max_gap > 3.0 * target:
        return "bursty"
    # Regular: tight and on-target
    if cv <= 0.30 and cadence_hit_rate >= 0.70:
        return "regular"
    # Irregular: moderate variance but not chaotic
    if cv <= 0.60 and cadence_hit_rate >= 0.40:
        return "irregular"
    # Fallback
    return "bursty"


def rhythm_report(
    timestamps: Sequence[str | datetime],
    target_seconds: float = 600.0,
    now: Optional[datetime] = None,
) -> RhythmReport:
    """Build a RhythmReport from a sequence of commit timestamps."""
    parsed = [_parse_ts(t) for t in timestamps]
    parsed = [p for p in parsed if p is not None]

    if not parsed:
        return RhythmReport(target_seconds=target_seconds, verdict="stalled")

    epochs = sorted(_to_epoch(p) for p in parsed)
    gaps = [epochs[i + 1] - epochs[i] for i in range(len(epochs) - 1)]

    # Trailing gap: time since the most recent commit
    ref_now = now or datetime.now(timezone.utc)
    trailing_gap = _to_epoch(ref_now) - epochs[-1]
    if trailing_gap < 0:
        trailing_gap = 0.0

    if not gaps:
        # Only one commit: can't compute rhythm, but trailing gap matters
        return RhythmReport(
            commit_count=1,
            trailing_gap=trailing_gap,
            target_seconds=target_seconds,
            verdict="stalled" if trailing_gap > 2.0 * target_seconds else "unknown",
        )

    mean_gap = statistics.mean(gaps)
    median_gap = statistics.median(gaps)
    max_gap = max(gaps)
    min_gap = min(gaps)
    stdev_gap = statistics.stdev(gaps) if len(gaps) >= 2 else 0.0
    cv = stdev_gap / mean_gap if mean_gap > 0 else 0.0

    # Cadence hit rate: fraction of gaps within ±25% of target
    lo, hi = target_seconds * 0.75, target_seconds * 1.25
    hits = sum(1 for g in gaps if lo <= g <= hi)
    cadence_hit_rate = hits / len(gaps)

    verdict = _classify(cv, cadence_hit_rate, max_gap, trailing_gap, target_seconds)

    return RhythmReport(
        commit_count=len(parsed),
        gaps=gaps,
        mean_gap=mean_gap,
        median_gap=median_gap,
        max_gap=max_gap,
        min_gap=min_gap,
        stdev_gap=stdev_gap,
        cv=cv,
        cadence_hit_rate=cadence_hit_rate,
        trailing_gap=trailing_gap,
        target_seconds=target_seconds,
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def rhythm_summary(r: RhythmReport) -> str:
    """One-line human-readable summary of the rhythm report."""
    if r.commit_count == 0:
        return "commit-rhythm: no commits found — stalled"

    def _fmt(s: float) -> str:
        if s >= 3600:
            return f"{s / 3600:.1f}h"
        if s >= 60:
            return f"{s / 60:.1f}m"
        return f"{s:.0f}s"

    parts = [
        f"commits={r.commit_count}",
        f"mean_gap={_fmt(r.mean_gap)}",
        f"median={_fmt(r.median_gap)}",
        f"max={_fmt(r.max_gap)}",
        f"cv={r.cv:.2f}",
        f"hit_rate={r.cadence_hit_rate:.0%}",
        f"trailing={_fmt(r.trailing_gap)}",
        f"verdict={r.verdict}",
    ]
    return "commit-rhythm: " + " | ".join(parts)
