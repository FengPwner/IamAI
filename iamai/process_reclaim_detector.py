"""Process reclaim detector — identify container-runtime reclamation patterns.

When a container runtime sweeps processes during idle windows, the deaths
follow recognizable patterns: they cluster in off-peak hours, occur with
rough periodicity, and affect all writers simultaneously.  This module
scores each death event on how likely it was caused by a runtime reclaim
versus an organic crash.

Scoring heuristic
-----------------

Each death event receives a ``reclaim_score`` in [0, 1]:

    score = w_hour * hour_factor
          + w_interval * interval_factor
          + w_bundled * bundled_factor

- **hour_factor** — deaths between 01:00–05:00 local time score 1.0;
  outside that window the factor decays linearly to 0.2.
- **interval_factor** — if the gap from the previous death is within
  ±30 % of the modal gap, score 1.0; otherwise 0.0.
- **bundled_factor** — if ≥2 writers died within 120 s of each other,
  score 1.0; otherwise 0.0.

Default weights: ``w_hour=0.4, w_interval=0.3, w_bundle=0.3``.

Usage::

    from iamai.process_reclaim_detector import (
        classify_deaths,
        reclaim_summary,
    )

    deaths = classify_deaths(repo, writer="qwen")
    for d in deaths:
        print(d["ts"], d["reclaim_score"])

    summary = reclaim_summary(repo, writer="qwen")
    print(summary["reclaim_fraction"])   # e.g. 0.72
    print(summary["peak_hour"])          # e.g. 3
    print(summary["estimated_interval"]) # e.g. 3600 (seconds)
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from iamai.process_mortality import read_events

# Default scoring weights
W_HOUR = 0.4
W_INTERVAL = 0.3
W_BUNDLED = 0.3

# Off-peak window (local hour, 24h)
OFF_PEAK_START = 1
OFF_PEAK_END = 5

# Bundled-death threshold in seconds
BUNDLE_THRESHOLD_SEC = 120

# Interval tolerance (±30 % of modal gap)
INTERVAL_TOLERANCE = 0.30


def _hour_factor(iso_ts: str, tz_offset_hours: int = 8) -> float:
    """Score how strongly the death hour falls in the off-peak window."""
    dt = datetime.fromisoformat(iso_ts).astimezone(
        timezone(timedelta(hours=tz_offset_hours))
    )
    hour = dt.hour
    if OFF_PEAK_START <= hour < OFF_PEAK_END:
        return 1.0
    # Linear decay outside the window
    if hour < OFF_PEAK_START:
        distance = OFF_PEAK_START - hour
    else:
        distance = hour - OFF_PEAK_END
    max_distance = 12  # worst case: noon
    return max(0.2, 1.0 - 0.8 * min(distance / max_distance, 1.0))


def _modal_gap(death_timestamps: list[float]) -> float | None:
    """Estimate the most common interval between consecutive deaths.

    Uses 15-minute buckets to tolerate jitter.
    """
    if len(death_timestamps) < 2:
        return None
    sorted_ts = sorted(death_timestamps)
    gaps = [sorted_ts[i + 1] - sorted_ts[i] for i in range(len(sorted_ts) - 1)]
    if not gaps:
        return None
    bucket_size = 900  # 15 minutes
    buckets: Counter[int] = Counter()
    for g in gaps:
        buckets[int(g // bucket_size)] += 1
    # Find the bucket with the most entries
    if not buckets:
        return None
    mode_bucket = buckets.most_common(1)[0][0]
    # Return the midpoint of the modal bucket
    return (mode_bucket + 0.5) * bucket_size


def _interval_factor(gap_sec: float | None, modal_gap: float | None) -> float:
    """Score how close the gap is to the modal interval."""
    if gap_sec is None or modal_gap is None or modal_gap <= 0:
        return 0.0
    ratio = abs(gap_sec - modal_gap) / modal_gap
    if ratio <= INTERVAL_TOLERANCE:
        return 1.0
    return 0.0


def _bundled_factor(
    death_ts_iso: str, all_death_ts_iso: list[str]
) -> float:
    """Score 1.0 if another death happened within BUNDLE_THRESHOLD_SEC.

    Counts all deaths within the time window (including the event itself).
    If the count exceeds 1, at least one *other* death was bundled with it.
    This correctly handles the case where two writers die at the exact
    same second — their ISO strings are identical but each appears as a
    separate entry in the list.
    """
    try:
        death_epoch = datetime.fromisoformat(death_ts_iso).timestamp()
    except (ValueError, TypeError):
        return 0.0
    nearby = 0
    for other_iso in all_death_ts_iso:
        try:
            other_epoch = datetime.fromisoformat(other_iso).timestamp()
        except (ValueError, TypeError):
            continue
        if abs(other_epoch - death_epoch) <= BUNDLE_THRESHOLD_SEC:
            nearby += 1
    # nearby includes the event itself, so nearby > 1 means ≥1 other death
    return 1.0 if nearby > 1 else 0.0


def classify_deaths(
    repo: Path | str,
    writer: str | None = None,
    *,
    tz_offset_hours: int = 8,
    w_hour: float = W_HOUR,
    w_interval: float = W_INTERVAL,
    w_bundled: float = W_BUNDLED,
) -> list[dict[str, Any]]:
    """Classify each death event with a reclaim probability score.

    Returns a list of dicts, one per death event, with keys:

    - ``ts``: ISO-8601 timestamp
    - ``writer``: writer identity
    - ``pid``: process id (may be None)
    - ``gap_sec``: seconds since previous event
    - ``hour_factor``: off-peak hour score component
    - ``interval_factor``: modal-interval score component
    - ``bundled_factor``: bundled-death score component
    - ``reclaim_score``: weighted sum in [0, 1]
    - ``likely_reclaim``: bool — True if score ≥ 0.5
    """
    events = read_events(repo, writer=None)
    deaths = [e for e in events if e.get("event") == "death"]
    if writer is not None:
        writer_deaths = [d for d in deaths if d.get("writer") == writer]
    else:
        writer_deaths = deaths

    # Collect all death ISO timestamps for bundled-factor computation
    all_death_ts_iso = [d["ts"] for d in deaths if "ts" in d]

    # Collect writer-specific death timestamps for modal gap
    writer_death_ts = []
    for d in writer_deaths:
        try:
            writer_death_ts.append(datetime.fromisoformat(d["ts"]).timestamp())
        except (ValueError, KeyError):
            pass

    modal_gap = _modal_gap(writer_death_ts)

    results = []
    prev_ts: float | None = None
    for d in writer_deaths:
        ts_iso = d.get("ts", "")
        try:
            ts_epoch = datetime.fromisoformat(ts_iso).timestamp()
        except (ValueError, KeyError):
            continue

        gap_sec: float | None = None
        if prev_ts is not None:
            gap_sec = ts_epoch - prev_ts
        prev_ts = ts_epoch

        hf = _hour_factor(ts_iso, tz_offset_hours)
        inf = _interval_factor(gap_sec, modal_gap)
        bf = _bundled_factor(ts_iso, all_death_ts_iso)

        score = w_hour * hf + w_interval * inf + w_bundled * bf
        score = max(0.0, min(1.0, score))

        results.append({
            "ts": ts_iso,
            "writer": d.get("writer"),
            "pid": d.get("pid"),
            "gap_sec": gap_sec,
            "hour_factor": round(hf, 3),
            "interval_factor": round(inf, 3),
            "bundled_factor": round(bf, 3),
            "reclaim_score": round(score, 3),
            "likely_reclaim": score >= 0.5,
        })

    return results


def reclaim_summary(
    repo: Path | str,
    writer: str | None = None,
    *,
    tz_offset_hours: int = 8,
) -> dict[str, Any]:
    """Aggregate reclaim classification into a summary.

    Returns a dict with keys:

    - ``total_deaths``: number of death events analyzed
    - ``reclaim_count``: deaths classified as likely reclaim (score ≥ 0.5)
    - ``reclaim_fraction``: reclaim_count / total_deaths (0.0–1.0)
    - ``peak_hour``: most common hour (local time) of reclaim-classified deaths
    - ``estimated_interval``: modal gap between reclaim deaths (seconds), or None
    - ``avg_score``: mean reclaim score across all deaths
    - ``max_score``: highest reclaim score observed
    """
    classified = classify_deaths(repo, writer=writer, tz_offset_hours=tz_offset_hours)

    if not classified:
        return {
            "total_deaths": 0,
            "reclaim_count": 0,
            "reclaim_fraction": 0.0,
            "peak_hour": None,
            "estimated_interval": None,
            "avg_score": 0.0,
            "max_score": 0.0,
        }

    reclaim_deaths = [d for d in classified if d["likely_reclaim"]]
    scores = [d["reclaim_score"] for d in classified]

    # Peak hour among reclaim deaths
    hour_counts: Counter[int] = Counter()
    for d in reclaim_deaths:
        dt = datetime.fromisoformat(d["ts"]).astimezone(
            timezone(timedelta(hours=tz_offset_hours))
        )
        hour_counts[dt.hour] += 1
    peak_hour = hour_counts.most_common(1)[0][0] if hour_counts else None

    # Estimated interval among reclaim deaths
    reclaim_ts = [
        datetime.fromisoformat(d["ts"]).timestamp() for d in reclaim_deaths
    ]
    estimated_interval = _modal_gap(reclaim_ts)

    return {
        "total_deaths": len(classified),
        "reclaim_count": len(reclaim_deaths),
        "reclaim_fraction": round(len(reclaim_deaths) / len(classified), 3) if classified else 0.0,
        "peak_hour": peak_hour,
        "estimated_interval": estimated_interval,
        "avg_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
        "max_score": round(max(scores), 3) if scores else 0.0,
    }
