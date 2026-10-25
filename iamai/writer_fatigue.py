"""writer_fatigue — detect output-quality degradation over a long writing session.

Existing health modules answer *is the writer running?* (pulse_score,
process_uptime) and *is the rhythm steady?* (cadence_adherence, heartbeat_decay).
Writer fatigue answers a different question: **is the writer getting tired?**

A tired writer still produces strokes on time, but the strokes themselves
degrade:

- Texts get shorter (less to say each cycle).
- Vocabulary recycles (same phrases reappear more often).
- Topics narrow (the writer circles the same ideas instead of exploring).
- Inter-stroke gaps stretch (more "thinking" time between outputs).

None of these alone signals fatigue — a short stroke can be punchy, a
narrow topic can be deep.  But when all four trend in the same direction
over a session, the writer is running on fumes.

Metrics
-------

Each metric is computed over a sliding window of *W* strokes (default 50)
and then its **trend** is measured as the normalised slope of a linear
regression across the last *N* windows (default 6).

========================  =================================================
metric                    what it measures
========================  =================================================
length_trend              mean word count per stroke (negative = shrinking)
recycling_trend           fraction of words already seen in the corpus
                          (positive = more recycling)
gap_trend                 mean seconds between consecutive strokes
                          (positive = slowing down)
diversity_trend           unique bigrams / total bigrams per window
                          (negative = narrowing)
fatigue_score             composite 0–100; higher = more fatigued
========================  =================================================

Fatigue grades
--------------

==========  =====================================================
grade       meaning
==========  =====================================================
fresh       score < 25 — no detectable degradation
warming     25–49       — early signs, monitor
fatigued    50–74       — clear degradation, consider restart
exhausted   ≥ 75        — severe, intervention recommended
==========  =====================================================

Usage::

    from iamai.writer_fatigue import fatigue_report, fatigue_summary

    report = fatigue_report(window_size=50, num_windows=6)
    print(report["fatigue_score"])   # e.g. 38
    print(report["grade"])           # "warming"

    summary = fatigue_summary()
    print(summary)

Design choices:
- Pure computation on a list of stroke dicts; no I/O inside functions.
- Linear regression by hand (least-squares) to avoid numpy dependency.
- Normalised slope: slope / mean of the series, so metrics on different
  scales are comparable.  Guarded against zero-mean.
- Recycling uses a cumulative vocabulary set built from all strokes
  before the current window.
- All timestamps are ISO-8601 strings parsed with datetime.fromisoformat.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── helpers ────────────────────────────────────────────────────


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp to a timezone-aware datetime."""
    # Handle the +00:00 suffix that fromisoformat struggles with on < 3.11
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        # Fallback: strip trailing Z and assume UTC
        cleaned = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)


def _tokenize(text: str) -> List[str]:
    """Lowercase split on non-alpha; drops empty tokens."""
    return [t for t in re.split(r"[^a-z']+", text.lower()) if t]


def _bigrams(tokens: List[str]) -> List[Tuple[str, str]]:
    """Consecutive token pairs."""
    return list(zip(tokens, tokens[1:]))


def _linreg_slope(values: List[float]) -> float:
    """Ordinary least-squares slope for y = values, x = 0..n-1."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0.0:
        return 0.0
    return num / den


def _normalised_slope(values: List[float]) -> float:
    """Slope divided by mean; returns 0 if mean ≈ 0."""
    mean = sum(values) / len(values) if values else 0.0
    if abs(mean) < 1e-9:
        return 0.0
    return _linreg_slope(values) / abs(mean)


# ── per-window metrics ─────────────────────────────────────────


def _window_mean_length(window: List[Dict[str, Any]]) -> float:
    """Mean word count in a window of strokes."""
    if not window:
        return 0.0
    counts = [len(_tokenize(s["text"])) for s in window]
    return sum(counts) / len(counts)


def _window_recycling(
    window: List[Dict[str, Any]], prior_vocab: frozenset
) -> float:
    """Fraction of tokens in the window already in prior_vocab."""
    all_tokens: List[str] = []
    for s in window:
        all_tokens.extend(_tokenize(s["text"]))
    if not all_tokens:
        return 0.0
    recycled = sum(1 for t in all_tokens if t in prior_vocab)
    return recycled / len(all_tokens)


def _window_mean_gap(window: List[Dict[str, Any]]) -> float:
    """Mean inter-stroke gap in seconds within a window."""
    if len(window) < 2:
        return 0.0
    timestamps = sorted(_parse_ts(s["at"]) for s in window)
    gaps = [
        (timestamps[i + 1] - timestamps[i]).total_seconds()
        for i in range(len(timestamps) - 1)
    ]
    return sum(gaps) / len(gaps)


def _window_bigram_diversity(window: List[Dict[str, Any]]) -> float:
    """Unique bigrams / total bigrams in the window."""
    all_bigrams: List[Tuple[str, str]] = []
    for s in window:
        all_bigrams.extend(_bigrams(_tokenize(s["text"])))
    if not all_bigrams:
        return 0.0
    return len(set(all_bigrams)) / len(all_bigrams)


# ── core analysis ──────────────────────────────────────────────


def fatigue_report(
    strokes: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    window_size: int = 50,
    num_windows: int = 6,
    data_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute a fatigue report over recent strokes.

    Parameters
    ----------
    strokes : sequence of stroke dicts, optional
        Each dict must have keys ``"text"`` and ``"at"``.
        If *None*, reads from *data_path* or ``data/strokes.jsonl``.
    window_size : int
        Number of strokes per analysis window.
    num_windows : int
        Number of recent windows to trend over.
    data_path : str, optional
        Path to strokes.jsonl when *strokes* is None.

    Returns
    -------
    dict with keys:
        length_trend, recycling_trend, gap_trend, diversity_trend,
        fatigue_score, grade, windows_analysed, detail
    """
    if strokes is None:
        strokes = _load_strokes(data_path)

    total_needed = window_size * num_windows
    recent = list(strokes[-total_needed:]) if len(strokes) > total_needed else list(strokes)

    if len(recent) < window_size * 2:
        return _insufficient_data_report(len(recent), window_size)

    # Build windows (oldest → newest)
    windows: List[List[Dict[str, Any]]] = []
    for i in range(0, len(recent) - window_size + 1, window_size):
        windows.append(recent[i : i + window_size])
    # Keep only the last num_windows
    windows = windows[-num_windows:]

    # Build cumulative vocab up to each window
    length_series: List[float] = []
    recycling_series: List[float] = []
    gap_series: List[float] = []
    diversity_series: List[float] = []

    prior_tokens: set = set()
    # Seed prior_tokens with strokes before the first window
    first_start = sum(len(w) for w in windows[:-1])
    if first_start > 0:
        for s in recent[: len(recent) - len(windows) * window_size]:
            prior_tokens.update(_tokenize(s["text"]))

    for w in windows:
        length_series.append(_window_mean_length(w))
        recycling_series.append(_window_recycling(w, frozenset(prior_tokens)))
        gap_series.append(_window_mean_gap(w))
        diversity_series.append(_window_bigram_diversity(w))
        # Update vocabulary with this window's tokens
        for s in w:
            prior_tokens.update(_tokenize(s["text"]))

    # Normalised slopes
    len_slope = _normalised_slope(length_series)
    rec_slope = _normalised_slope(recycling_series)
    gap_slope = _normalised_slope(gap_series)
    div_slope = _normalised_slope(diversity_series)

    # Fatigue components: positive = more fatigued
    # length shrinking → fatigue (negate the slope)
    # recycling increasing → fatigue (keep positive)
    # gap increasing → fatigue (keep positive)
    # diversity shrinking → fatigue (negate the slope)
    components = {
        "length": max(0.0, -len_slope),
        "recycling": max(0.0, rec_slope),
        "gap": max(0.0, gap_slope),
        "diversity_loss": max(0.0, -div_slope),
    }

    # Score: average component × 100, clamped to [0, 100]
    raw = sum(components.values()) / len(components) * 100.0
    score = max(0.0, min(100.0, raw))

    return {
        "fatigue_score": round(score, 1),
        "grade": _grade(score),
        "length_trend": round(len_slope, 4),
        "recycling_trend": round(rec_slope, 4),
        "gap_trend": round(gap_slope, 4),
        "diversity_trend": round(div_slope, 4),
        "windows_analysed": len(windows),
        "window_size": window_size,
        "detail": components,
    }


# ── grade ──────────────────────────────────────────────────────


def _grade(score: float) -> str:
    if score < 25:
        return "fresh"
    if score < 50:
        return "warming"
    if score < 75:
        return "fatigued"
    return "exhausted"


# ── insufficient data ──────────────────────────────────────────


def _insufficient_data_report(available: int, window_size: int) -> Dict[str, Any]:
    return {
        "fatigue_score": 0.0,
        "grade": "unknown",
        "length_trend": 0.0,
        "recycling_trend": 0.0,
        "gap_trend": 0.0,
        "diversity_trend": 0.0,
        "windows_analysed": 0,
        "window_size": window_size,
        "detail": {},
        "note": f"need at least {window_size * 2} strokes, have {available}",
    }


# ── data loading ───────────────────────────────────────────────


def _load_strokes(path: Optional[str] = None) -> List[Dict[str, Any]]:
    import json
    from pathlib import Path

    if path is None:
        path = str(Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl")
    strokes: List[Dict[str, Any]] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                strokes.append(json.loads(line))
    return strokes


# ── summary string ─────────────────────────────────────────────


def fatigue_summary(
    strokes: Optional[Sequence[Dict[str, Any]]] = None,
    **kwargs: Any,
) -> str:
    """One-line human-readable fatigue summary."""
    report = fatigue_report(strokes, **kwargs)
    if report["grade"] == "unknown":
        return report.get("note", "insufficient data for fatigue analysis")
    score = report["fatigue_score"]
    grade = report["grade"]
    parts = []
    d = report["detail"]
    if d.get("length", 0) > 0.05:
        parts.append("texts shrinking")
    if d.get("recycling", 0) > 0.05:
        parts.append("vocab recycling")
    if d.get("gap", 0) > 0.05:
        parts.append("gaps widening")
    if d.get("diversity_loss", 0) > 0.05:
        parts.append("topics narrowing")

    signals = ", ".join(parts) if parts else "no degradation signals"
    return f"fatigue {score}/100 ({grade}) — {signals}"
