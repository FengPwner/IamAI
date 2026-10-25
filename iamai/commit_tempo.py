"""commit_tempo — classify commit rhythm using musical tempo markings.

Most cadence modules give you raw numbers (seconds between commits, jitter,
drift). Those are precise but not immediately *felt*. This module translates
commit intervals into musical tempo markings that humans intuitively grasp.

Tempo scale
===========

==============  ==================  ===========================================
marking         commits/hour        feel
==============  ==================  ===========================================
``presto``      ≥ 30                frantic — burst mode, likely a fix spree
``allegro``     10–29               lively — normal active writing
``andante``     3–9                 walking pace — steady, sustainable
``adagio``      1–2                 slow — intermittent, possible stall onset
``largo``       < 1                 very slow — effectively stalled
==============  ==================  ===========================================

Decay detection
===============

Compares the recent window (last N commits) against the prior window.
If tempo drops by two or more levels, the rhythm is ``decaying``.
If it holds or rises, the rhythm is ``steady`` or ``accelerating``.

Usage::

    from iamai.commit_tempo import classify_tempo, tempo_trend

    # intervals in seconds between consecutive commits
    intervals = [120, 180, 150, 200, 160, 300, 600, 1800, 3600]

    tempo = classify_tempo(intervals[-5:])
    # → 'andante'

    trend = tempo_trend(intervals, recent=5, prior=5)
    # → {'recent_tempo': 'adagio', 'prior_tempo': 'andante', 'trend': 'decaying'}
"""

from __future__ import annotations

from typing import List, Sequence


# ── Tempo thresholds (commits per hour) ────────────────────────────────

TEMPO_LEVELS: List[tuple] = [
    ("presto",  30.0),
    ("allegro", 10.0),
    ("andante",  3.0),
    ("adagio",   1.0),
    # below adagio → largo
]

TEMPO_ORDER = ["presto", "allegro", "andante", "adagio", "largo"]


def _intervals_to_cph(intervals: Sequence[float]) -> float:
    """Convert a list of intervals (seconds) to commits-per-hour."""
    if not intervals:
        return 0.0
    avg = sum(intervals) / len(intervals)
    if avg <= 0:
        return 0.0
    return 3600.0 / avg


def classify_tempo(intervals: Sequence[float]) -> str:
    """Classify a sequence of commit intervals into a tempo marking.

    Parameters
    ----------
    intervals : sequence of float
        Seconds between consecutive commits. Must be positive values.

    Returns
    -------
    str
        One of: presto, allegro, andante, adagio, largo.
        Returns 'largo' for empty sequences.
    """
    if not intervals:
        return "largo"
    cph = _intervals_to_cph(intervals)
    for name, threshold in TEMPO_LEVELS:
        if cph >= threshold:
            return name
    return "largo"


def _tempo_rank(name: str) -> int:
    """Return numeric rank (lower = faster). presto=0, largo=4."""
    try:
        return TEMPO_ORDER.index(name)
    except ValueError:
        return len(TEMPO_ORDER)


def tempo_trend(
    intervals: Sequence[float],
    recent: int = 5,
    prior: int = 5,
) -> dict:
    """Compare recent vs prior tempo to detect rhythm changes.

    Parameters
    ----------
    intervals : sequence of float
        Full interval series (oldest first).
    recent : int
        Number of recent intervals for the "current" window.
    prior : int
        Number of prior intervals for the "baseline" window.

    Returns
    -------
    dict with keys:
        recent_tempo : str
        prior_tempo  : str
        recent_cph   : float
        prior_cph    : float
        trend        : str  — 'accelerating', 'steady', or 'decaying'
    """
    if len(intervals) < recent + prior:
        # Not enough data — use what we have
        all_tempo = classify_tempo(intervals)
        return {
            "recent_tempo": all_tempo,
            "prior_tempo": all_tempo,
            "recent_cph": _intervals_to_cph(intervals),
            "prior_cph": _intervals_to_cph(intervals),
            "trend": "steady",
        }

    prior_slice = intervals[-(recent + prior):-recent]
    recent_slice = intervals[-recent:]

    prior_tempo = classify_tempo(prior_slice)
    recent_tempo = classify_tempo(recent_slice)

    rank_diff = _tempo_rank(recent_tempo) - _tempo_rank(prior_tempo)

    if rank_diff >= 2:
        trend = "decaying"
    elif rank_diff <= -1:
        trend = "accelerating"
    else:
        trend = "steady"

    return {
        "recent_tempo": recent_tempo,
        "prior_tempo": prior_tempo,
        "recent_cph": round(_intervals_to_cph(recent_slice), 2),
        "prior_cph": round(_intervals_to_cph(prior_slice), 2),
        "trend": trend,
    }


def tempo_summary_line(intervals: Sequence[float]) -> str:
    """One-line human-readable summary.

    Example output::

        tempo: andante (6.0 cph) — steady ♩
    """
    if not intervals:
        return "tempo: largo (0 cph) — no data"

    tempo = classify_tempo(intervals)
    cph = _intervals_to_cph(intervals)

    trend_info = tempo_trend(intervals)
    trend = trend_info["trend"]

    symbols = {"accelerating": "♩♩", "steady": "♩", "decaying": "𝄒"}
    sym = symbols.get(trend, "")

    return f"tempo: {tempo} ({cph:.1f} cph) — {trend} {sym}"
