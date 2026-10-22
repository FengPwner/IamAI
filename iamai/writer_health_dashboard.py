"""writer_health_dashboard — synthesize multiple health signals into one report.

Existing modules each measure one slice of writer health: cadence adherence,
stall classification, process uptime, stroke diversity, recovery fidelity.
None of them answer the question a human caretaker actually asks: **"is the
writer healthy right now, and if not, what should I look at?"**

This module takes a small set of inputs — recent strokes, process metadata,
and optional sub-module outputs — and produces a single structured report
with an overall health grade and prioritized list of concerns.

Health grade
------------

=============  =========================================================
grade          meaning
=============  =========================================================
healthy        all signals nominal, no action needed
watching       one or more signals trending but not yet critical
attention      at least one signal degraded, worth investigating
critical       multiple signals degraded or process stalled
=============  =========================================================

Signals evaluated:

======================  ===============================================
signal                  what it measures
======================  ===============================================
process_alive           is the writer PID still responding
cadence_ok              median gap within 2x of target cadence
stall_absent            no gap exceeds the stall threshold
diversity_ok            stroke kinds are not stuck in a loop
recovery_recent         if recovering, fidelity is "good" or better
======================  ===============================================

Usage::

    from iamai.writer_health_dashboard import health_report, health_summary

    report = health_report(
        strokes=recent_stroke_list,
        target_cadence_s=15,
        stall_threshold_s=600,
        process_alive=True,
    )
    print(report["grade"])       # "watching"
    print(report["concerns"])    # ["diversity_ok: loop detected"]

    summary = health_summary(recent_stroke_list, 15, 600, True)
    # one-line human-readable string

Design choices:
- Pure Python, no external dependencies.
- All inputs are arguments (no file I/O in core functions).
- Graceful degradation: missing signals produce "unknown" not crashes.
- Reports are plain dicts, easy to serialize or format.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def health_report(
    strokes: list[dict],
    target_cadence_s: float = 15.0,
    stall_threshold_s: float = 600.0,
    process_alive: bool = True,
    recovery_fidelity_grade: str | None = None,
    min_sample: int = 5,
) -> dict[str, Any]:
    """Produce a structured health report from recent strokes.

    Parameters
    ----------
    strokes : list[dict]
        Recent stroke dicts, each with at least ``at`` (timestamp) and
        ``kind`` (stroke type). Must be sorted oldest-first.
    target_cadence_s : float
        Desired seconds between strokes.
    stall_threshold_s : float
        Gap in seconds that constitutes a stall.
    process_alive : bool
        Whether the writer process is currently responding.
    recovery_fidelity_grade : str or None
        Grade from recovery_fidelity module, if available.
    min_sample : int
        Minimum strokes needed to evaluate cadence/diversity signals.

    Returns
    -------
    dict with keys: grade, signals, concerns, summary.
    """
    signals: dict[str, str] = {}
    concerns: list[str] = []

    # ── signal 1: process alive ──────────────────────────────────
    signals["process_alive"] = "ok" if process_alive else "down"
    if not process_alive:
        concerns.append("process_alive: writer process not responding")

    # ── signal 2: cadence ────────────────────────────────────────
    if len(strokes) >= min_sample:
        gaps = _inter_stroke_gaps(strokes)
        if gaps:
            med = _median(gaps)
            ratio = med / target_cadence_s if target_cadence_s > 0 else float("inf")
            if ratio <= 2.0:
                signals["cadence_ok"] = "ok"
            elif ratio <= 4.0:
                signals["cadence_ok"] = "slow"
                concerns.append(
                    f"cadence_ok: median gap {med:.0f}s "
                    f"({ratio:.1f}x target {target_cadence_s}s)"
                )
            else:
                signals["cadence_ok"] = "degraded"
                concerns.append(
                    f"cadence_ok: median gap {med:.0f}s "
                    f"({ratio:.1f}x target, severely degraded)"
                )
        else:
            signals["cadence_ok"] = "unknown"
    else:
        signals["cadence_ok"] = "insufficient_data"

    # ── signal 3: stall absent ────────────────────────────────────
    if len(strokes) >= 2:
        gaps = _inter_stroke_gaps(strokes)
        max_gap = max(gaps) if gaps else 0
        if max_gap < stall_threshold_s:
            signals["stall_absent"] = "ok"
        else:
            signals["stall_absent"] = "stalled"
            concerns.append(
                f"stall_absent: max gap {max_gap:.0f}s "
                f"exceeds threshold {stall_threshold_s:.0f}s"
            )
    else:
        signals["stall_absent"] = "insufficient_data"

    # ── signal 4: diversity ──────────────────────────────────────
    if len(strokes) >= min_sample:
        kinds = [s.get("kind", "unknown") for s in strokes]
        kind_counts = Counter(kinds)
        dominant_ratio = max(kind_counts.values()) / len(kinds)
        if dominant_ratio <= 0.4:
            signals["diversity_ok"] = "ok"
        elif dominant_ratio <= 0.6:
            signals["diversity_ok"] = "narrowing"
            concerns.append(
                f"diversity_ok: dominant kind is "
                f"{max(kind_counts, key=kind_counts.get)} "
                f"({dominant_ratio:.0%} of strokes)"
            )
        else:
            signals["diversity_ok"] = "loop"
            concerns.append(
                f"diversity_ok: kind loop detected — "
                f"{max(kind_counts, key=kind_counts.get)} "
                f"at {dominant_ratio:.0%}"
            )
    else:
        signals["diversity_ok"] = "insufficient_data"

    # ── signal 5: recovery ───────────────────────────────────────
    if recovery_fidelity_grade is not None:
        if recovery_fidelity_grade in ("full", "good"):
            signals["recovery_recent"] = "ok"
        elif recovery_fidelity_grade == "partial":
            signals["recovery_recent"] = "recovering"
            concerns.append(
                f"recovery_recent: fidelity is '{recovery_fidelity_grade}', "
                "writer still regaining full output"
            )
        elif recovery_fidelity_grade == "poor":
            signals["recovery_recent"] = "degraded"
            concerns.append(
                f"recovery_recent: fidelity is '{recovery_fidelity_grade}', "
                "recovery may need intervention"
            )
        else:
            signals["recovery_recent"] = "unknown"
    else:
        signals["recovery_recent"] = "not_applicable"

    # ── overall grade ────────────────────────────────────────────
    grade = _compute_grade(signals, process_alive)

    return {
        "grade": grade,
        "signals": signals,
        "concerns": concerns,
        "summary": _format_summary(grade, signals, concerns),
    }


def health_summary(
    strokes: list[dict],
    target_cadence_s: float = 15.0,
    stall_threshold_s: float = 600.0,
    process_alive: bool = True,
    recovery_fidelity_grade: str | None = None,
) -> str:
    """One-line human-readable health status."""
    report = health_report(
        strokes=strokes,
        target_cadence_s=target_cadence_s,
        stall_threshold_s=stall_threshold_s,
        process_alive=process_alive,
        recovery_fidelity_grade=recovery_fidelity_grade,
    )
    return report["summary"]


# ── internal helpers ────────────────────────────────────────────────


def _inter_stroke_gaps(strokes: list[dict]) -> list[float]:
    """Compute seconds between consecutive strokes."""
    gaps = []
    for i in range(1, len(strokes)):
        t_prev = _parse_ts(strokes[i - 1].get("at", 0))
        t_curr = _parse_ts(strokes[i].get("at", 0))
        gap = t_curr - t_prev
        if gap > 0:
            gaps.append(gap)
    return gaps


def _parse_ts(ts: Any) -> float:
    """Parse a timestamp to epoch seconds. Handles float, int, str."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            from datetime import datetime, timezone
            # Try ISO-8601
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except (ValueError, TypeError):
            try:
                return float(ts)
            except (ValueError, TypeError):
                return 0.0
    return 0.0


def _median(values: list[float]) -> float:
    """Compute median of a list."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2
    return s[mid]


def _compute_grade(signals: dict[str, str], process_alive: bool) -> str:
    """Determine overall grade from signal values."""
    if not process_alive:
        return "critical"

    problems = 0
    warnings = 0

    for key, val in signals.items():
        if val in ("down", "stalled", "degraded", "loop"):
            problems += 1
        elif val in ("slow", "narrowing", "recovering"):
            warnings += 1

    if problems >= 2:
        return "critical"
    if problems >= 1:
        return "attention"
    if warnings >= 1:
        return "watching"
    return "healthy"


def _format_summary(
    grade: str, signals: dict[str, str], concerns: list[str]
) -> str:
    """Build a one-line human-readable summary."""
    signal_count = len(signals)
    ok_count = sum(1 for v in signals.values() if v == "ok")

    if grade == "healthy":
        return f"healthy — {ok_count}/{signal_count} signals nominal"
    elif grade == "watching":
        concern_str = "; ".join(concerns[:2]) if concerns else "trending"
        return f"watching — {concern_str}"
    elif grade == "attention":
        concern_str = "; ".join(concerns[:2]) if concerns else "degraded"
        return f"attention needed — {concern_str}"
    else:  # critical
        concern_str = "; ".join(concerns[:2]) if concerns else "multiple issues"
        return f"critical — {concern_str}"
