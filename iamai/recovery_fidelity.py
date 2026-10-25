"""recovery_fidelity — measure how completely a writer recovers after a stall.

Existing modules answer *is the writer running again?* (restart_warmup,
restart_quality, process_uptime) and *how long did the stall last?*
(stall_duration, stall_event).  Recovery fidelity answers a deeper
question: **did the writer come back at the same level it was before?**

A process can be technically alive yet still sick — producing shorter
strokes, slower cadence, or narrower vocabulary than before the stall.
This is the difference between "recovered" and "recovered *well*".

Signals
-------

Each signal compares a pre-stall metric to its post-recovery counterpart,
producing a fidelity ratio in [0, 1] where 1 = identical to pre-stall.

=====================  =================================================
signal                 what it measures
=====================  =================================================
cadence_fidelity       inter-stroke interval similarity (KS-like ratio)
length_fidelity        mean stroke length ratio (min/max bounded)
diversity_fidelity     vocabulary richness ratio (unique tokens / total)
gap_stability          coefficient of variation of post-recovery gaps
=====================  =================================================

Composite
---------

``fidelity_score`` = weighted mean of the four signals (equal weights by
default).  Graded on a four-level scale:

============  =====================================================
grade         meaning
============  =====================================================
full          score >= 0.90 — writer is back to pre-stall level
good          0.70–0.89    — minor degradation, trending back
partial       0.50–0.69    — clear gap, recovery incomplete
poor          < 0.50       — writer is still struggling
============  =====================================================

Usage::

    from iamai.recovery_fidelity import fidelity_report, fidelity_summary

    report = fidelity_report(
        pre_strokes=pre_stroke_list,
        post_strokes=post_stroke_list,
    )
    print(report["fidelity_score"])   # e.g. 0.82
    print(report["grade"])            # "good"

    summary = fidelity_summary(pre_strokes, post_strokes)
    print(summary)

Design choices:
- Pure Python, no external dependencies.
- All inputs are arguments (no file I/O inside core functions).
- Robust to small samples: returns "unknown" when data is insufficient.
- Timestamps parsed flexibly (ISO-8601 variants, epoch floats).
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence


# ── public API ─────────────────────────────────────────────────


def fidelity_report(
    pre_strokes: Sequence[Dict[str, Any]],
    post_strokes: Sequence[Dict[str, Any]],
    min_sample: int = 5,
) -> Dict[str, Any]:
    """Compare pre-stall and post-recovery stroke sets.

    Parameters
    ----------
    pre_strokes : sequence of stroke dicts
        Strokes from before the stall (ideally the last N before stall).
    post_strokes : sequence of stroke dicts
        Strokes from after recovery (ideally the first N after restart).
    min_sample : int
        Minimum strokes required in each set for a meaningful comparison.

    Returns
    -------
    dict with keys: fidelity_score, grade, cadence_fidelity,
    length_fidelity, diversity_fidelity, gap_stability, detail, note.
    """
    pre = list(pre_strokes)
    post = list(post_strokes)

    if len(pre) < min_sample or len(post) < min_sample:
        return _insufficient_report(len(pre), len(post), min_sample)

    pre_gaps = _inter_stroke_gaps(pre)
    post_gaps = _inter_stroke_gaps(post)

    if len(pre_gaps) < 2 or len(post_gaps) < 2:
        return _insufficient_report(len(pre), len(post), min_sample)

    cadence = _cadence_fidelity(pre_gaps, post_gaps)
    length_ = _length_fidelity(pre, post)
    diversity = _diversity_fidelity(pre, post)
    gap_stab = _gap_stability(post_gaps)

    score = (cadence + length_ + diversity + gap_stab) / 4.0

    return {
        "fidelity_score": round(score, 4),
        "grade": _grade(score),
        "cadence_fidelity": round(cadence, 4),
        "length_fidelity": round(length_, 4),
        "diversity_fidelity": round(diversity, 4),
        "gap_stability": round(gap_stab, 4),
        "pre_count": len(pre),
        "post_count": len(post),
        "detail": {
            "pre_mean_gap": round(_mean(pre_gaps), 2),
            "post_mean_gap": round(_mean(post_gaps), 2),
            "pre_mean_length": round(_mean(_stroke_lengths(pre)), 2),
            "post_mean_length": round(_mean(_stroke_lengths(post)), 2),
            "pre_diversity": round(_vocab_diversity(pre), 4),
            "post_diversity": round(_vocab_diversity(post), 4),
            "post_gap_cv": round(_cv(post_gaps), 4),
        },
    }


def fidelity_summary(
    pre_strokes: Sequence[Dict[str, Any]],
    post_strokes: Sequence[Dict[str, Any]],
    **kwargs: Any,
) -> str:
    """One-line human-readable recovery fidelity summary."""
    report = fidelity_report(pre_strokes, post_strokes, **kwargs)
    if report["grade"] == "unknown":
        return report.get("note", "insufficient data for fidelity analysis")
    score = report["fidelity_score"]
    grade = report["grade"]
    parts = []
    d = report["detail"]
    if report["cadence_fidelity"] < 0.8:
        parts.append("cadence drift")
    if report["length_fidelity"] < 0.8:
        parts.append("shorter strokes")
    if report["diversity_fidelity"] < 0.8:
        parts.append("narrower vocab")
    if report["gap_stability"] < 0.8:
        parts.append("unsteady gaps")
    signals = ", ".join(parts) if parts else "all signals nominal"
    return f"fidelity {score:.2f} ({grade}) — {signals}"


# ── signal: cadence fidelity ───────────────────────────────────


def _cadence_fidelity(
    pre_gaps: List[float],
    post_gaps: List[float],
) -> float:
    """Compare inter-stroke gap distributions via median ratio.

    Returns a value in [0, 1].  A ratio of 1.0 means identical medians.
    We use the ratio min(med_pre, med_post) / max(med_pre, med_post)
    so the result is always in [0, 1], and penalise high post variance
    by multiplying by (1 - cv_clamp) where cv_clamp is the post CV
    capped at 1.
    """
    med_pre = _median(pre_gaps)
    med_post = _median(post_gaps)
    if max(med_pre, med_post) == 0:
        return 1.0
    ratio = min(med_pre, med_post) / max(med_pre, med_post)
    cv_post = _cv(post_gaps)
    penalty = max(0.0, 1.0 - cv_post)
    return ratio * penalty


# ── signal: length fidelity ────────────────────────────────────


def _length_fidelity(
    pre_strokes: Sequence[Dict[str, Any]],
    post_strokes: Sequence[Dict[str, Any]],
) -> float:
    """Compare mean stroke lengths as min/max ratio in [0, 1]."""
    pre_lens = _stroke_lengths(pre_strokes)
    post_lens = _stroke_lengths(post_strokes)
    m_pre = _mean(pre_lens)
    m_post = _mean(post_lens)
    if max(m_pre, m_post) == 0:
        return 1.0
    return min(m_pre, m_post) / max(m_pre, m_post)


# ── signal: diversity fidelity ─────────────────────────────────


def _diversity_fidelity(
    pre_strokes: Sequence[Dict[str, Any]],
    post_strokes: Sequence[Dict[str, Any]],
) -> float:
    """Compare vocabulary diversity (unique tokens / total tokens)."""
    d_pre = _vocab_diversity(pre_strokes)
    d_post = _vocab_diversity(post_strokes)
    if max(d_pre, d_post) == 0:
        return 1.0
    return min(d_pre, d_post) / max(d_pre, d_post)


# ── signal: gap stability ─────────────────────────────────────


def _gap_stability(post_gaps: List[float]) -> float:
    """Measure how steady the post-recovery gaps are.

    Returns 1 - cv (clamped to [0, 1]).  A CV of 0 means perfectly
    uniform gaps; CV >= 1 means wildly variable.
    """
    cv = _cv(post_gaps)
    return max(0.0, min(1.0, 1.0 - cv))


# ── helpers ────────────────────────────────────────────────────


def _inter_stroke_gaps(strokes: Sequence[Dict[str, Any]]) -> List[float]:
    """Compute seconds between consecutive strokes."""
    times = [_parse_ts(s.get("at", s.get("timestamp", s.get("ts", 0)))) for s in strokes]
    times.sort()
    return [times[i + 1] - times[i] for i in range(len(times) - 1) if times[i + 1] > times[i]]


def _stroke_lengths(strokes: Sequence[Dict[str, Any]]) -> List[int]:
    """Word count per stroke."""
    return [len(_tokenize(s.get("text", ""))) for s in strokes]


def _vocab_diversity(strokes: Sequence[Dict[str, Any]]) -> float:
    """Unique tokens / total tokens across all strokes."""
    all_tokens: List[str] = []
    for s in strokes:
        all_tokens.extend(_tokenize(s.get("text", "")))
    if not all_tokens:
        return 0.0
    return len(set(all_tokens)) / len(all_tokens)


def _tokenize(text: str) -> List[str]:
    """Lowercase, split on non-alpha, drop pure-number tokens."""
    tokens = re.findall(r"[a-z]+", text.lower())
    return [t for t in tokens if not t.isdigit()]


def _parse_ts(ts: Any) -> float:
    """Parse a timestamp to epoch seconds.  Handles ISO-8601, epoch, etc."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        s = ts.strip()
        # try numeric first
        try:
            return float(s)
        except ValueError:
            pass
        # normalise Z suffix
        s = s.replace("Z", "+00:00")
        # try ISO formats
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
        ):
            try:
                dt = datetime.strptime(s, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                continue
    return 0.0


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _cv(values: Sequence[float]) -> float:
    """Coefficient of variation (stddev / mean).  Returns 0 if mean is 0."""
    if not values:
        return 0.0
    m = _mean(values)
    if m == 0:
        return 0.0
    variance = sum((v - m) ** 2 for v in values) / len(values)
    return math.sqrt(variance) / m


# ── grade ──────────────────────────────────────────────────────


def _grade(score: float) -> str:
    if score >= 0.90:
        return "full"
    if score >= 0.70:
        return "good"
    if score >= 0.50:
        return "partial"
    return "poor"


# ── insufficient data ──────────────────────────────────────────


def _insufficient_report(
    pre_count: int,
    post_count: int,
    min_sample: int,
) -> Dict[str, Any]:
    return {
        "fidelity_score": 0.0,
        "grade": "unknown",
        "cadence_fidelity": 0.0,
        "length_fidelity": 0.0,
        "diversity_fidelity": 0.0,
        "gap_stability": 0.0,
        "pre_count": pre_count,
        "post_count": post_count,
        "detail": {},
        "note": f"insufficient data — need at least {min_sample} strokes in each set, have {pre_count} pre / {post_count} post",
    }
