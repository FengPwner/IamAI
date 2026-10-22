"""lock_scar — track recurring lock-file incidents as historical scars.

A lock file that appears once is a glitch.  A lock file that appears
twenty times in the same location is a *scar* — evidence that something
in the system's workflow keeps tearing at the same seam.

``lock_health.py`` answers: "is there a lock file right now?"
``lock_scar.py`` answers: "how many times has this lock file appeared,
and is the recurrence interval shrinking?"

The module reads a log of lock-file incidents (each a timestamp + path)
and computes:

- **incident_count** — total incidents in the window
- **hotspots** — paths that appear most often
- **recurrence_interval** — median seconds between incidents on the
  same path; a shrinking interval means the problem is getting worse
- **verdict** — ``clean`` | ``bruised`` | ``scarred`` | ``chronic``

Verdict rules
-------------
- **clean**    — zero incidents in the window
- **bruised**  — 1-3 incidents, interval > 1 hour
- **scarred**  — 4-9 incidents, or interval < 1 hour
- **chronic**  — ≥ 10 incidents, or interval < 10 minutes

Usage::

    from iamai.lock_scar import scar_report, scar_summary

    incidents = [
        {"at": "2026-10-22T00:10:00Z", "path": ".git/index.lock"},
        {"at": "2026-10-22T00:25:00Z", "path": ".git/index.lock"},
        {"at": "2026-10-22T01:00:00Z", "path": ".git/index.lock"},
    ]
    report = scar_report(incidents)
    print(scar_summary(report))
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ScarReport:
    """Summary of lock-file scar patterns."""

    incident_count: int = 0
    hotspots: list[tuple[str, int]] = field(default_factory=list)
    hottest_path: str = ""
    hottest_count: int = 0
    recurrence_interval: float = 0.0  # median seconds between incidents on hottest path
    interval_trend: str = "unknown"    # shrinking | stable | growing
    verdict: str = "clean"


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
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _classify(count: int, interval: float) -> str:
    """Apply verdict rules."""
    if count == 0:
        return "clean"
    if count >= 10 or (interval > 0 and interval < 600):
        return "chronic"
    if count >= 4 or (interval > 0 and interval < 3600):
        return "scarred"
    return "bruised"


def _interval_trend(gaps: list[float]) -> str:
    """Determine if recurrence interval is shrinking, stable, or growing.

    Splits gaps into two halves.  If the second half's median is < 70 %
    of the first half's median → shrinking (getting worse).  If > 130 %
    → growing (healing).  Otherwise stable.
    """
    if len(gaps) < 4:
        return "unknown"
    mid = len(gaps) // 2
    first_med = statistics.median(gaps[:mid])
    second_med = statistics.median(gaps[mid:])
    if first_med <= 0:
        return "unknown"
    ratio = second_med / first_med
    if ratio < 0.70:
        return "shrinking"
    if ratio > 1.30:
        return "growing"
    return "stable"


def scar_report(
    incidents: Sequence[Dict[str, Any]],
) -> ScarReport:
    """Build a ScarReport from a sequence of incident dicts.

    Each dict must have ``"at"`` (ISO timestamp) and ``"path"`` (lock path).
    """
    if not incidents:
        return ScarReport(verdict="clean")

    # Group by path
    by_path: dict[str, list[datetime]] = defaultdict(list)
    for inc in incidents:
        path = inc.get("path", "unknown")
        dt = _parse_ts(inc.get("at", ""))
        if dt is not None:
            by_path[path].append(dt)

    # Count per path
    counts = {p: len(dts) for p, dts in by_path.items()}
    if not counts:
        return ScarReport(verdict="clean")
    hotspots = sorted(counts.items(), key=lambda x: -x[1])

    # Hottest path
    hottest_path, hottest_count = hotspots[0]

    # Compute recurrence intervals for hottest path
    hots_dts = sorted(by_path[hottest_path])
    gaps: list[float] = []
    if len(hots_dts) >= 2:
        gaps = [
            (hots_dts[i + 1] - hots_dts[i]).total_seconds()
            for i in range(len(hots_dts) - 1)
        ]

    recurrence = statistics.median(gaps) if gaps else 0.0
    trend = _interval_trend(gaps) if gaps else "unknown"
    verdict = _classify(sum(counts.values()), recurrence)

    return ScarReport(
        incident_count=sum(counts.values()),
        hotspots=hotspots,
        hottest_path=hottest_path,
        hottest_count=hottest_count,
        recurrence_interval=round(recurrence, 1),
        interval_trend=trend,
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def scar_summary(r: ScarReport) -> str:
    """One-line human-readable summary."""
    if r.incident_count == 0:
        return "lock-scar: clean — no lock-file incidents recorded"

    def _fmt(s: float) -> str:
        if s >= 3600:
            return f"{s / 3600:.1f}h"
        if s >= 60:
            return f"{s / 60:.1f}m"
        return f"{s:.0f}s"

    parts = [
        f"incidents={r.incident_count}",
        f"hottest={r.hottest_path}({r.hottest_count}x)",
        f"interval={_fmt(r.recurrence_interval)}",
        f"trend={r.interval_trend}",
        f"verdict={r.verdict}",
    ]
    return "lock-scar: " + " | ".join(parts)
