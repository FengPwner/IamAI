"""stroke_recovery_speed — measure how quickly the writer recovers after a stall.

When the writer process dies and is restarted, there is a transition period
before it settles back into its regular 15-second cadence.  This module
quantifies that recovery:

    1. Detects *stall events* — gaps exceeding the stall threshold.
    2. For each stall, measures how many strokes it takes (and how many
       seconds elapse) before the local cadence returns to normal.
    3. Produces an aggregate recovery_score across all stalls in the
       analysed window.

Metrics
-------

========================  =============================================
metric                    meaning
========================  =============================================
stalls                    list of detected stall events
stall_count               number of stalls found
mean_recovery_strokes     average strokes until cadence normalises
mean_recovery_seconds     average wall-clock seconds until normal
max_recovery_strokes      worst-case recovery strokes
max_recovery_seconds      worst-case recovery seconds
recovery_score            0–1 composite: 1.0 = instant recovery,
                          0.0 = never recovers within window
========================  =============================================

Recovery detection
------------------

After a stall gap, the module examines subsequent inter-stroke intervals.
Recovery is achieved when ``window_size`` consecutive intervals all fall
within ``tolerance`` of the target cadence (default 15 s).

    target_cadence   15.0 s  (configurable)
    tolerance        ±5.0 s  (configurable)
    window_size      4       (consecutive good intervals required)

If recovery is not achieved within ``max_lookahead`` strokes (default 50)
after the stall, the recovery is recorded as *unresolved* and the full
lookahead distance is used as the recovery metric.

Recovery score
--------------

Each stall's recovery strokes are converted to a score via exponential
decay::

    s_i = exp(-recovery_strokes / decay_constant)

where ``decay_constant`` defaults to 10.  An instant recovery (0 extra
strokes) scores 1.0; needing 10 strokes scores ~0.37; needing 50 strokes
scores ~0.007.

The overall ``recovery_score`` is the geometric mean of individual stall
scores, which penalises any single bad recovery more than an arithmetic
mean would.

Usage::

    from iamai.stroke_recovery_speed import recovery_report, recovery_summary

    report = recovery_report(n_strokes=500)
    print(report["recovery_score"])     # e.g. 0.81
    print(report["stall_count"])        # e.g. 3
    print(report["mean_recovery_strokes"])  # e.g. 4.3

    print(recovery_summary())
    # "recovery: good 0.81 (3 stalls, avg 4.3 strokes / 67.2s to recover)"

CLI::

    python -m iamai.stroke_recovery_speed --n 500 --json

Written by Qwen during caretaker visit 811, 2026-11-23.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_STROKES = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"
_DEFAULT_N = 200
_TARGET_CADENCE = 15.0       # expected seconds per stroke
_TOLERANCE = 5.0             # ± seconds considered "normal"
_STALL_MULTIPLIER = 3.0      # gap > multiplier × target = stall
_WINDOW_SIZE = 4             # consecutive good intervals = recovered
_MAX_LOOKAHEAD = 50          # max strokes to check after stall
_DECAY_CONSTANT = 10.0       # exponential decay for per-stall score

# Score bands
_BANDS = [
    (0.8, "instant"),
    (0.5, "fast"),
    (0.3, "slow"),
    (0.0, "stuck"),
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_strokes_with_timestamps(
    n: int = _DEFAULT_N,
    path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Read the last *n* strokes that have parseable timestamps."""
    p = path or _DEFAULT_STROKES
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    tail = lines[-n:] if len(lines) >= n else lines
    result: List[Dict[str, Any]] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if "at" in entry:
                _parse_timestamp(entry["at"])
                result.append(entry)
        except (json.JSONDecodeError, ValueError):
            continue
    return result


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a timezone-aware datetime."""
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        raise ValueError(f"Cannot parse timestamp: {ts!r}")


# ---------------------------------------------------------------------------
# Gap computation
# ---------------------------------------------------------------------------


def compute_gaps(strokes: Sequence[Dict[str, Any]]) -> List[float]:
    """Compute inter-stroke gaps in seconds."""
    if len(strokes) < 2:
        return []
    timestamps = [_parse_timestamp(s["at"]) for s in strokes]
    gaps: List[float] = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        gaps.append(max(0.0, delta))
    return gaps


# ---------------------------------------------------------------------------
# Stall detection
# ---------------------------------------------------------------------------


def detect_stalls(
    gaps: Sequence[float],
    target_cadence: float = _TARGET_CADENCE,
    stall_multiplier: float = _STALL_MULTIPLIER,
) -> List[int]:
    """Return indices of gaps that qualify as stalls.

    A gap at index *i* is a stall when ``gap[i] > stall_multiplier × target_cadence``.
    The index refers to the position in the *gaps* list.
    """
    threshold = stall_multiplier * target_cadence
    return [i for i, g in enumerate(gaps) if g > threshold]


# ---------------------------------------------------------------------------
# Recovery measurement
# ---------------------------------------------------------------------------


def measure_recovery(
    gaps: Sequence[float],
    stall_index: int,
    target_cadence: float = _TARGET_CADENCE,
    tolerance: float = _TOLERANCE,
    window_size: int = _WINDOW_SIZE,
    max_lookahead: int = _MAX_LOOKAHEAD,
) -> Dict[str, Any]:
    """Measure recovery after a single stall at *stall_index*.

    Returns a dict with:

        stall_gap           the stall gap value (seconds)
        recovery_strokes    strokes until normal cadence resumes (-1 if unresolved)
        recovery_seconds    wall-clock seconds until recovery (-1 if unresolved)
        resolved            True if recovery was observed
    """
    stall_gap = gaps[stall_index]
    lo = target_cadence - tolerance
    hi = target_cadence + tolerance

    consecutive_good = 0
    recovery_strokes = -1
    recovery_seconds = -1.0
    resolved = False

    # Start checking from the gap *after* the stall
    end = min(stall_index + 1 + max_lookahead, len(gaps))
    for j in range(stall_index + 1, end):
        if lo <= gaps[j] <= hi:
            consecutive_good += 1
            if consecutive_good >= window_size:
                # Recovered: count strokes from stall to here
                recovery_strokes = j - stall_index
                # Sum actual seconds elapsed
                recovery_seconds = sum(gaps[stall_index + 1 : j + 1])
                resolved = True
                break
        else:
            consecutive_good = 0

    return {
        "stall_gap": round(stall_gap, 2),
        "recovery_strokes": recovery_strokes,
        "recovery_seconds": round(recovery_seconds, 2),
        "resolved": resolved,
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def stall_score(
    recovery_strokes: int,
    decay_constant: float = _DECAY_CONSTANT,
    max_lookahead: int = _MAX_LOOKAHEAD,
) -> float:
    """Score a single stall recovery via exponential decay.

    Instant recovery (0 strokes) → 1.0.
    Unresolved (recovery_strokes < 0) → score for max_lookahead.
    """
    n = recovery_strokes if recovery_strokes >= 0 else max_lookahead
    return math.exp(-n / decay_constant)


def aggregate_score(scores: Sequence[float]) -> float:
    """Geometric mean of individual stall scores.

    Returns 1.0 when there are no stalls (nothing to penalise).
    """
    if not scores:
        return 1.0
    log_sum = sum(math.log(max(s, 1e-12)) for s in scores)
    return math.exp(log_sum / len(scores))


def recovery_label(score: float) -> str:
    """Map a recovery score to a human-readable label."""
    for threshold, name in _BANDS:
        if score >= threshold:
            return name
    return "stuck"


# ---------------------------------------------------------------------------
# Report / CLI
# ---------------------------------------------------------------------------


def recovery_report(
    n_strokes: int = _DEFAULT_N,
    path: Optional[Path] = None,
    target_cadence: float = _TARGET_CADENCE,
    tolerance: float = _TOLERANCE,
    stall_multiplier: float = _STALL_MULTIPLIER,
    window_size: int = _WINDOW_SIZE,
    max_lookahead: int = _MAX_LOOKAHEAD,
    decay_constant: float = _DECAY_CONSTANT,
) -> Dict[str, Any]:
    """Produce a full recovery speed report."""
    strokes = _load_strokes_with_timestamps(n=n_strokes, path=path)
    gaps = compute_gaps(strokes)

    if len(gaps) < 2:
        return {
            "n_strokes_analysed": len(strokes),
            "n_intervals": len(gaps),
            "stall_count": 0,
            "stalls": [],
            "mean_recovery_strokes": 0,
            "mean_recovery_seconds": 0.0,
            "max_recovery_strokes": 0,
            "max_recovery_seconds": 0.0,
            "recovery_score": 1.0,
            "label": "instant",
        }

    stall_indices = detect_stalls(gaps, target_cadence, stall_multiplier)
    stall_details: List[Dict[str, Any]] = []
    individual_scores: List[float] = []

    for idx in stall_indices:
        m = measure_recovery(
            gaps, idx,
            target_cadence=target_cadence,
            tolerance=tolerance,
            window_size=window_size,
            max_lookahead=max_lookahead,
        )
        s = stall_score(m["recovery_strokes"], decay_constant, max_lookahead)
        m["score"] = round(s, 4)
        stall_details.append(m)
        individual_scores.append(s)

    overall = aggregate_score(individual_scores)

    resolved_strokes = [
        d["recovery_strokes"] for d in stall_details if d["resolved"]
    ]
    resolved_seconds = [
        d["recovery_seconds"] for d in stall_details if d["resolved"]
    ]

    mean_rs = (
        sum(resolved_strokes) / len(resolved_strokes) if resolved_strokes else 0
    )
    mean_sec = (
        sum(resolved_seconds) / len(resolved_seconds) if resolved_seconds else 0.0
    )
    max_rs = max(resolved_strokes) if resolved_strokes else 0
    max_sec = max(resolved_seconds) if resolved_seconds else 0.0

    return {
        "n_strokes_analysed": len(strokes),
        "n_intervals": len(gaps),
        "stall_count": len(stall_indices),
        "stalls": stall_details,
        "mean_recovery_strokes": round(mean_rs, 1),
        "mean_recovery_seconds": round(mean_sec, 1),
        "max_recovery_strokes": max_rs,
        "max_recovery_seconds": round(max_sec, 1),
        "recovery_score": round(overall, 4),
        "label": recovery_label(overall),
    }


def recovery_summary(
    n_strokes: int = _DEFAULT_N,
    path: Optional[Path] = None,
) -> str:
    """One-line human summary for dashboards."""
    r = recovery_report(n_strokes=n_strokes, path=path)
    if r["stall_count"] == 0:
        return (
            f"recovery: no stalls in {r['n_strokes_analysed']} strokes "
            f"({r['n_intervals']} intervals)"
        )
    return (
        f"recovery: {r['label']} {r['recovery_score']:.2f} "
        f"({r['stall_count']} stall{'s' if r['stall_count'] != 1 else ''}, "
        f"avg {r['mean_recovery_strokes']:.1f} strokes / "
        f"{r['mean_recovery_seconds']:.1f}s to recover)"
    )


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stroke recovery speed analysis for the IamAI project."
    )
    parser.add_argument(
        "--n", type=int, default=_DEFAULT_N,
        help=f"number of recent strokes to analyse (default {_DEFAULT_N})"
    )
    parser.add_argument(
        "--path", type=Path, default=None,
        help="path to strokes.jsonl (default: data/strokes.jsonl)"
    )
    parser.add_argument(
        "--json", action="store_true", help="output JSON instead of text"
    )
    parser.add_argument(
        "--target-cadence", type=float, default=_TARGET_CADENCE,
        help=f"expected seconds per stroke (default {_TARGET_CADENCE})"
    )
    parser.add_argument(
        "--tolerance", type=float, default=_TOLERANCE,
        help=f"± seconds considered normal (default {_TOLERANCE})"
    )
    args = parser.parse_args(argv)

    report = recovery_report(
        n_strokes=args.n,
        path=args.path,
        target_cadence=args.target_cadence,
        tolerance=args.tolerance,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(recovery_summary(n_strokes=args.n, path=args.path))

    return 0 if report["label"] in ("instant", "fast") else 1


if __name__ == "__main__":
    sys.exit(_cli())
