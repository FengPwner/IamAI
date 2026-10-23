"""restart_cascade — detect and analyze restart chains.

A single restart is an event.  A *cascade* is a symptom: the system
keeps dying shortly after each recovery, suggesting the root cause
was never actually fixed — or that the restart itself introduced new
instability.

This module takes a list of restart timestamps and identifies:

- **Cascade chains**: sequences where consecutive restarts fall within
  a configurable ``cascade_window_seconds`` (default: 600 = 10 minutes)
- **Cascade score**: 0.0 (all isolated) to 1.0 (all chained)
- **Max depth**: the longest consecutive chain of close restarts

Cascade tiers:

==========  =========================================================
tier        meaning
==========  =========================================================
stable      no cascades detected — restarts are well-spaced
fragile     some cascades present but shallow (depth 2-3)
unstable    frequent cascades or deep chains (depth 4+)
critical    majority of restarts participate in cascades
==========  =========================================================

Usage::

    from iamai.restart_cascade import detect_cascades, cascade_score

    restarts = [
        "2026-10-23T02:00:00+08:00",
        "2026-10-23T02:05:00+08:00",  # cascade with above
        "2026-10-23T02:08:00+08:00",  # cascade continues
        "2026-10-23T14:00:00+08:00",  # isolated
    ]

    result = detect_cascades(restarts, cascade_window_seconds=600)
    print(result["tier"])          # "fragile"
    print(result["cascade_count"]) # 1
    print(result["max_depth"])     # 3
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


# Tier thresholds (percentages are 0-100 scale)
_FRAGILE_THRESHOLD = 20.0     # 20% of restarts in cascades
_UNSTABLE_THRESHOLD = 50.0    # 50% of restarts in cascades
_DEEP_CHAIN_THRESHOLD = 4     # chain depth triggering "unstable"


def _parse_ts(ts: str | datetime) -> datetime:
    """Parse a timestamp string or return datetime as-is."""
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(ts)


def detect_cascades(
    restart_timestamps: list[str | datetime],
    cascade_window_seconds: int = 600,
) -> dict[str, Any]:
    """Detect restart cascades in a sequence of restart events.

    Args:
        restart_timestamps: list of restart times (ISO strings or
            datetime objects), in any order — will be sorted
        cascade_window_seconds: maximum gap between consecutive
            restarts to consider them part of a cascade (default 600s)

    Returns:
        Dict with keys:
        - total_restarts: int
        - cascade_count: int (number of distinct cascade chains)
        - cascades: list of dicts, each with 'start', 'end', 'depth',
          'gaps' (list of seconds between consecutive restarts)
        - max_depth: int (longest cascade chain)
        - cascade_score: float (0.0 = all isolated, 1.0 = all chained)
        - cascade_pct: float (percentage of restarts in cascades)
        - tier: str ("stable" | "fragile" | "unstable" | "critical")
        - advice: str (one actionable sentence)
    """
    if not restart_timestamps:
        return {
            "total_restarts": 0,
            "cascade_count": 0,
            "cascades": [],
            "max_depth": 0,
            "cascade_score": 0.0,
            "cascade_pct": 0.0,
            "tier": "stable",
            "advice": "No restarts recorded.",
        }

    # Sort timestamps
    parsed = sorted(_parse_ts(ts) for ts in restart_timestamps)
    n = len(parsed)

    if n == 1:
        return {
            "total_restarts": 1,
            "cascade_count": 0,
            "cascades": [],
            "max_depth": 1,
            "cascade_score": 0.0,
            "cascade_pct": 0.0,
            "tier": "stable",
            "advice": "Single restart recorded — no cascade possible.",
        }

    # Find cascades: consecutive restarts within the window
    cascades: list[dict[str, Any]] = []
    current_chain = [parsed[0]]
    current_gaps: list[float] = []

    for i in range(1, n):
        gap = (parsed[i] - parsed[i - 1]).total_seconds()
        if gap <= cascade_window_seconds:
            current_chain.append(parsed[i])
            current_gaps.append(gap)
        else:
            if len(current_chain) >= 2:
                cascades.append({
                    "start": current_chain[0].isoformat(),
                    "end": current_chain[-1].isoformat(),
                    "depth": len(current_chain),
                    "gaps": list(current_gaps),
                })
            current_chain = [parsed[i]]
            current_gaps = []

    # Flush last chain
    if len(current_chain) >= 2:
        cascades.append({
            "start": current_chain[0].isoformat(),
            "end": current_chain[-1].isoformat(),
            "depth": len(current_chain),
            "gaps": list(current_gaps),
        })

    # Compute stats
    cascade_count = len(cascades)
    max_depth = max((c["depth"] for c in cascades), default=1)
    restarts_in_cascades = sum(c["depth"] for c in cascades)
    cascade_pct = (restarts_in_cascades / n) * 100.0 if n > 0 else 0.0

    # Score: blend of percentage and depth severity
    pct_score = min(cascade_pct / 100.0, 1.0)
    depth_score = min((max_depth - 1) / 10.0, 1.0) if max_depth > 1 else 0.0
    score = round((pct_score * 0.7 + depth_score * 0.3), 3)

    # Classify tier
    tier = _classify_tier(cascade_pct, max_depth)
    advice = _generate_advice(tier, cascade_count, max_depth)

    return {
        "total_restarts": n,
        "cascade_count": cascade_count,
        "cascades": cascades,
        "max_depth": max_depth,
        "cascade_score": score,
        "cascade_pct": round(cascade_pct, 1),
        "tier": tier,
        "advice": advice,
    }


def _classify_tier(cascade_pct: float, max_depth: int) -> str:
    """Classify cascade severity into a tier."""
    if cascade_pct >= _UNSTABLE_THRESHOLD or max_depth >= _DEEP_CHAIN_THRESHOLD:
        if cascade_pct >= _UNSTABLE_THRESHOLD and max_depth >= _DEEP_CHAIN_THRESHOLD:
            return "critical"
        return "unstable"
    if cascade_pct >= _FRAGILE_THRESHOLD:
        return "fragile"
    return "stable"


def _generate_advice(tier: str, cascade_count: int, max_depth: int) -> str:
    """Generate one actionable sentence based on the tier."""
    if tier == "stable":
        return "All restarts are isolated — system recovers cleanly each time."
    if tier == "fragile":
        return (
            f"{cascade_count} cascade(s) detected but shallow — "
            "monitor for worsening pattern."
        )
    if tier == "unstable":
        return (
            f"Deepest cascade chain is {max_depth} restarts — "
            "investigate root cause; restarts may be masking a deeper issue."
        )
    # critical
    return (
        "Majority of restarts cascade — the system is not stabilizing; "
        "fundamental fix needed before next restart attempt."
    )
