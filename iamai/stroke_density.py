"""stroke_density — measure writing intensity via sliding-window density bands.

the writer produces strokes at a nominal cadence of one every 15 seconds,
but real behaviour is bursty: dense clusters of rapid output separated by
quiet stretches.  cadence modules measure the *gaps*; session segmenters
find *runs*.  density sits between them — it answers "how intense was
the last N minutes?" on a continuous scale.

density bands
~~~~~~~~~~~~~

============  ============  ============================================
band          strokes/min   meaning
============  ============  ============================================
dormant       < 0.5         writer effectively idle
sparse        0.5 – 1.5     occasional output, low focus
steady        1.5 – 3.5     normal working pace
dense         3.5 – 6.0     high-intensity burst
hyper         > 6.0         unsustainable sprint or replay artefact
============  ============  ============================================

a healthy repo spends most of its time in *steady* with occasional *dense*
bursts after a restart catch-up.  prolonged *dormant* means the writer
died; prolonged *hyper* means timestamps are wrong or the writer is
replaying old data.

public api
~~~~~~~~~~

- ``parse_strokes_jsonl(lines)``  — parse raw JSONL lines → list of dicts
- ``window_density(strokes, window_minutes, step_minutes)``
    → list of window dicts with density, band, count, start, end
- ``density_summary(windows)``
    → aggregate: band distribution, mean density, peak window
- ``density_report(lines, window_minutes, step_minutes)``
    → one-call convenience: parse → window → summary
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# band thresholds (strokes per minute)
# ---------------------------------------------------------------------------

_BANDS = [
    ("dormant", 0.0, 0.5),
    ("sparse",  0.5, 1.5),
    ("steady",  1.5, 3.5),
    ("dense",   3.5, 6.0),
    ("hyper",   6.0, float("inf")),
]


def classify_density(strokes_per_min: float) -> str:
    """Return the density band for a given strokes-per-minute value.

    >>> classify_density(0.0)
    'dormant'
    >>> classify_density(2.0)
    'steady'
    >>> classify_density(5.0)
    'dense'
    >>> classify_density(10.0)
    'hyper'
    """
    for band, lo, hi in _BANDS:
        if lo <= strokes_per_min < hi:
            return band
    return "hyper"  # fallback for inf / nan edge cases


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


def parse_strokes_jsonl(lines: list[str]) -> list[dict[str, Any]]:
    """Parse raw JSONL lines from data/strokes.jsonl.

    each line must be valid JSON with at least ``at`` (ISO-8601 timestamp).
    lines that fail to parse or lack ``at`` are silently skipped.

    returns a list of dicts sorted by timestamp ascending.
    """
    strokes: list[dict[str, Any]] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        ts_str = obj.get("at")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_str))
        except (ValueError, TypeError):
            continue
        strokes.append({
            "seq": obj.get("seq"),
            "at": ts,
            "kind": obj.get("kind", "unknown"),
            "text": obj.get("text", ""),
        })
    strokes.sort(key=lambda s: s["at"])
    return strokes


# ---------------------------------------------------------------------------
# sliding window density
# ---------------------------------------------------------------------------


def window_density(
    strokes: list[dict[str, Any]],
    window_minutes: int = 10,
    step_minutes: int = 5,
) -> list[dict[str, Any]]:
    """Compute density for each sliding window across the stroke timeline.

    parameters
    ----------
    strokes : list of stroke dicts (must have ``at`` key as datetime)
    window_minutes : width of each analysis window
    step_minutes : step size between consecutive windows

    returns a list of window dicts::

        {
            "start": datetime,
            "end": datetime,
            "count": int,          # strokes in this window
            "duration_min": float, # window width in minutes
            "density": float,      # strokes per minute
            "band": str,           # density band name
            "kinds": {kind: count} # kind distribution within window
        }

    returns an empty list when fewer than 2 strokes are provided.
    """
    if len(strokes) < 2:
        return []

    from datetime import timedelta

    window_td = timedelta(minutes=window_minutes)
    step_td = timedelta(minutes=step_minutes)

    t_start = strokes[0]["at"]
    t_end = strokes[-1]["at"]

    windows: list[dict[str, Any]] = []
    cursor = t_start

    while cursor + window_td <= t_end + step_td:
        w_end = cursor + window_td
        in_window = [s for s in strokes if cursor <= s["at"] < w_end]
        count = len(in_window)
        density = count / window_minutes if window_minutes > 0 else 0.0
        kinds: dict[str, int] = {}
        for s in in_window:
            k = s.get("kind", "unknown")
            kinds[k] = kinds.get(k, 0) + 1

        windows.append({
            "start": cursor,
            "end": w_end,
            "count": count,
            "duration_min": float(window_minutes),
            "density": round(density, 4),
            "band": classify_density(density),
            "kinds": kinds,
        })
        cursor += step_td

    return windows


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


def density_summary(windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate statistics across all density windows.

    returns::

        {
            "total_windows": int,
            "band_distribution": {band: count, ...},
            "mean_density": float,
            "peak_density": float,
            "peak_window": {start, end, count, density, band} or None,
            "dominant_band": str,  # most frequent band
        }
    """
    if not windows:
        return {
            "total_windows": 0,
            "band_distribution": {},
            "mean_density": 0.0,
            "peak_density": 0.0,
            "peak_window": None,
            "dominant_band": "dormant",
        }

    band_counts: dict[str, int] = {}
    for w in windows:
        b = w["band"]
        band_counts[b] = band_counts.get(b, 0) + 1

    densities = [w["density"] for w in windows]
    peak_idx = densities.index(max(densities))
    peak_w = windows[peak_idx]

    dominant = max(band_counts, key=lambda b: band_counts[b])

    return {
        "total_windows": len(windows),
        "band_distribution": band_counts,
        "mean_density": round(sum(densities) / len(densities), 4),
        "peak_density": peak_w["density"],
        "peak_window": {
            "start": peak_w["start"].isoformat(),
            "end": peak_w["end"].isoformat(),
            "count": peak_w["count"],
            "density": peak_w["density"],
            "band": peak_w["band"],
        },
        "dominant_band": dominant,
    }


# ---------------------------------------------------------------------------
# convenience: full report
# ---------------------------------------------------------------------------


def density_report(
    lines: list[str],
    window_minutes: int = 10,
    step_minutes: int = 5,
) -> dict[str, Any]:
    """One-call entry point: parse JSONL → compute windows → summarise.

    returns::

        {
            "strokes_parsed": int,
            "windows": [...],
            "summary": {...}
        }
    """
    strokes = parse_strokes_jsonl(lines)
    windows = window_density(strokes, window_minutes, step_minutes)
    summary = density_summary(windows)
    return {
        "strokes_parsed": len(strokes),
        "windows": windows,
        "summary": summary,
    }
