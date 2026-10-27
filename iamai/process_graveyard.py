"""Process graveyard — track dead processes and their final resting state.

When a process dies, it leaves behind a pid, a timestamp, and whatever
was in its last heartbeat.  This module collects those remains into a
queryable graveyard so we can answer questions like:

- How many processes died in the last hour?
- What was the typical lifespan before death?
- Are deaths clustering around specific times of day?

The graveyard is stored in ``data/process_graveyard.jsonl``.  Each line
is a JSON object representing a single death event.

Metrics provided:
- death_count(window_hours):   number of deaths in the time window
- mean_lifespan_minutes:      average time between birth and death
- death_rate_per_hour:        deaths / hours observed
- clustering_score:           0-1, how concentrated deaths are in time
- last_death_age_minutes:     lifespan of the most recent death

Severity bands:
===========  ============================================================
verdict      meaning
===========  ============================================================
stable       < 0.1 deaths/hour, processes live long
mild         0.1-0.5 deaths/hour, occasional churn
churny       0.5-2.0 deaths/hour, worth investigating
turbulent    > 2.0 deaths/hour, processes can't stay alive
===========  ============================================================

Usage::

    from iamai.process_graveyard import record_death, analyse

    record_death(writer="qwen", pid=12345, lifespan_seconds=3600)

    report = analyse(window_hours=24)
    print(f"{report['verdict']}: {report['death_rate_per_hour']:.2f}/hr")
"""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GRAVEYARD_FILE = DATA_DIR / "process_graveyard.jsonl"


def _ensure_data_dir() -> None:
    """Create data directory if missing."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    """Current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def record_death(
    writer: str = "qwen",
    pid: Optional[int] = None,
    lifespan_seconds: Optional[float] = None,
    cause: str = "unknown",
    restart_after_seconds: Optional[float] = None,
    note: str = "",
) -> dict:
    """Record a process death event into the graveyard.

    Parameters
    ----------
    writer : str
        Writer identity (e.g. "qwen").
    pid : int, optional
        Process ID that died.
    lifespan_seconds : float, optional
        How long the process was alive.
    cause : str
        Brief cause label (e.g. "oom", "signal", "timeout", "unknown").
    restart_after_seconds : float, optional
        How long until a replacement process started.
    note : str
        Free-form note about the death.

    Returns
    -------
    dict
        The recorded event as a dict.
    """
    _ensure_data_dir()

    event = {
        "ts": _now_iso(),
        "writer": writer,
        "pid": pid,
        "lifespan_seconds": lifespan_seconds,
        "cause": cause,
        "restart_after_seconds": restart_after_seconds,
        "note": note,
    }

    with open(GRAVEYARD_FILE, "a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return event


def load_deaths(
    writer: Optional[str] = None,
    window_hours: Optional[float] = None,
) -> List[dict]:
    """Load death events from the graveyard file.

    Parameters
    ----------
    writer : str, optional
        Filter to this writer identity.
    window_hours : float, optional
        Only return events within this many hours from now.

    Returns
    -------
    list[dict]
        Parsed death events (malformed lines skipped).
    """
    if not GRAVEYARD_FILE.exists():
        return []

    deaths: List[dict] = []
    now = datetime.now(timezone.utc)

    with open(GRAVEYARD_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if writer and event.get("writer") != writer:
                continue

            if window_hours is not None:
                ts_str = event.get("ts", "")
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    age_hours = (now - ts).total_seconds() / 3600
                    if age_hours > window_hours:
                        continue
                except (ValueError, TypeError):
                    continue

            deaths.append(event)

    return deaths


def mean_lifespan(deaths: List[dict]) -> Optional[float]:
    """Compute mean lifespan in seconds from a list of death events.

    Only events with a numeric ``lifespan_seconds`` field are included.
    Returns None if no valid events exist.
    """
    lifespans = [
        d["lifespan_seconds"]
        for d in deaths
        if isinstance(d.get("lifespan_seconds"), (int, float)) and d["lifespan_seconds"] > 0
    ]
    if not lifespans:
        return None
    return sum(lifespans) / len(lifespans)


def death_rate(deaths: List[dict], window_hours: float) -> float:
    """Compute deaths per hour over the given window.

    Parameters
    ----------
    deaths : list[dict]
        Death events (already filtered to window).
    window_hours : float
        Observation window in hours.

    Returns
    -------
    float
        Deaths per hour. 0.0 if window_hours <= 0.
    """
    if window_hours <= 0:
        return 0.0
    return len(deaths) / window_hours


def clustering_score(deaths: List[dict], bucket_minutes: int = 10) -> float:
    """Measure how concentrated deaths are in time.

    Divides the observation period into buckets of ``bucket_minutes``
    width.  A perfectly even distribution scores 0; all deaths in one
    bucket scores 1.

    Uses the Gini coefficient over bucket counts.

    Parameters
    ----------
    deaths : list[dict]
        Death events to analyse.
    bucket_minutes : int
        Bucket width in minutes.

    Returns
    -------
    float
        Clustering score in [0, 1]. 0 = evenly spread, 1 = all in one bucket.
    """
    if len(deaths) <= 1:
        return 0.0

    timestamps = []
    for d in deaths:
        try:
            ts = datetime.fromisoformat(d["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            timestamps.append(ts.timestamp())
        except (ValueError, TypeError, KeyError):
            continue

    if len(timestamps) <= 1:
        return 0.0

    min_ts = min(timestamps)
    max_ts = max(timestamps)
    span = max_ts - min_ts

    if span < 1:
        return 1.0  # all deaths within 1 second — maximally clustered

    bucket_seconds = bucket_minutes * 60
    n_buckets = max(1, int(span / bucket_seconds) + 1)

    # If all events fall in a single bucket, that is maximally clustered.
    if n_buckets == 1:
        return 1.0

    counts = [0] * n_buckets
    for t in timestamps:
        idx = min(int((t - min_ts) / bucket_seconds), n_buckets - 1)
        counts[idx] += 1

    # Gini coefficient
    n = len(counts)
    if n == 0 or sum(counts) == 0:
        return 0.0

    counts_sorted = sorted(counts)
    total = sum(counts_sorted)
    if total == 0:
        return 0.0

    numerator = sum((2 * (i + 1) - n - 1) * c for i, c in enumerate(counts_sorted))
    gini = numerator / (n * total)

    return min(1.0, max(0.0, gini))


def classify_verdict(rate_per_hour: float) -> str:
    """Classify the death rate into a severity band.

    Parameters
    ----------
    rate_per_hour : float
        Deaths per hour.

    Returns
    -------
    str
        One of: "stable", "mild", "churny", "turbulent".
    """
    if rate_per_hour < 0.1:
        return "stable"
    if rate_per_hour < 0.5:
        return "mild"
    if rate_per_hour < 2.0:
        return "churny"
    return "turbulent"


def analyse(
    writer: str = "qwen",
    window_hours: float = 24.0,
    bucket_minutes: int = 10,
) -> Dict[str, Any]:
    """Run a full graveyard analysis.

    Parameters
    ----------
    writer : str
        Writer identity to filter on.
    window_hours : float
        Look back this many hours.
    bucket_minutes : int
        Bucket width for clustering analysis.

    Returns
    -------
    dict
        Analysis report with keys:
        - death_count: int
        - mean_lifespan_minutes: float or None
        - death_rate_per_hour: float
        - clustering_score: float
        - last_death_age_minutes: float or None
        - verdict: str
        - cause_distribution: dict[str, int]
    """
    deaths = load_deaths(writer=writer, window_hours=window_hours)
    n = len(deaths)

    mean_life = mean_lifespan(deaths)
    mean_life_minutes = mean_life / 60.0 if mean_life is not None else None

    rate = death_rate(deaths, window_hours)

    cluster = clustering_score(deaths, bucket_minutes=bucket_minutes)

    # Last death age
    last_death_age = None
    if deaths:
        try:
            last_ts = datetime.fromisoformat(deaths[-1]["ts"])
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            last_death_age = (datetime.now(timezone.utc) - last_ts).total_seconds() / 60.0
        except (ValueError, TypeError, KeyError):
            pass

    # Cause distribution
    causes: Dict[str, int] = Counter()
    for d in deaths:
        cause = d.get("cause", "unknown")
        causes[cause] = causes.get(cause, 0) + 1

    verdict = classify_verdict(rate)

    return {
        "death_count": n,
        "mean_lifespan_minutes": mean_life_minutes,
        "death_rate_per_hour": round(rate, 4),
        "clustering_score": round(cluster, 4),
        "last_death_age_minutes": round(last_death_age, 1) if last_death_age else None,
        "verdict": verdict,
        "cause_distribution": dict(causes),
    }


def reset() -> None:
    """Delete the graveyard file (for testing)."""
    if GRAVEYARD_FILE.exists():
        GRAVEYARD_FILE.unlink()
