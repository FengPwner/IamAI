"""Analyze push-race frequency and patterns from recent git history.

Push races — where ``git push`` is rejected because the remote moved — are
a recurring cost in this repo.  Multiple writers (qwen, guoban, kimi, doubao)
share one remote, and every concurrent push window is a race.

This module answers three questions:

1. **How often do push races happen?**  Count rejections in a time window.
2. **Is the rate getting worse?**  Trend: rising, flat, or falling.
3. **Which time-of-day is hottest?**  Hourly heatmap of race occurrences.

Data source: a simple JSONL log (``data/push_races.jsonl``) where each line
records ``{"at": "...", "writer": "...", "resolution": "rebase"|"force"|"skip"}``.
If the file doesn't exist yet, all functions return empty results — the
module is read-tolerant.

    from iamai.push_race_analyzer import race_count, race_trend, hourly_heatmap

    n = race_count(repo, hours=24)          # races in the last day
    trend = race_trend(repo, hours=168)     # "rising" / "flat" / "falling"
    hot = hourly_heatmap(repo, hours=168)   # {0: 3, 1: 0, ..., 23: 7}
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_races(log_path: Path, since: datetime | None = None) -> list[dict]:
    """Read the race log, filtering to entries at or after *since*."""
    if not log_path.exists():
        return []
    entries: list[dict] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if since is not None:
                ts = datetime.fromisoformat(entry["at"])
                if ts < since:
                    continue
            entries.append(entry)
    return entries


def _log_path(repo: Path) -> Path:
    return repo / "data" / "push_races.jsonl"


def race_count(repo: Path, hours: int = 24, writer: str | None = None) -> int:
    """Count push races in the last *hours* hours.

    Optionally filter by *writer* name.  Returns 0 when the log is missing.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    races = _load_races(_log_path(repo), since=since)
    if writer is not None:
        races = [r for r in races if r.get("writer") == writer]
    return len(races)


def race_trend(repo: Path, hours: int = 168, bucket_hours: int = 24) -> str:
    """Classify the race-frequency trend over *hours* as rising/flat/falling.

    Splits the window into buckets of *bucket_hours*, counts races per bucket,
    then compares the first half's mean to the second half's mean:

    - **rising**: second half mean > first half mean × 1.2
    - **falling**: second half mean < first half mean × 0.8
    - **flat**: otherwise
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    races = _load_races(_log_path(repo), since=since)
    if len(races) < 2:
        return "flat"

    n_buckets = max(1, hours // bucket_hours)
    buckets: list[int] = [0] * n_buckets
    for r in races:
        ts = datetime.fromisoformat(r["at"])
        age_hours = (now - ts).total_seconds() / 3600
        idx = min(int(age_hours // bucket_hours), n_buckets - 1)
        # Reverse: oldest bucket is index 0
        idx = n_buckets - 1 - idx
        buckets[idx] += 1

    mid = n_buckets // 2
    first_half = buckets[:mid] if mid > 0 else buckets
    second_half = buckets[mid:] if mid > 0 else buckets

    first_mean = sum(first_half) / max(len(first_half), 1)
    second_mean = sum(second_half) / max(len(second_half), 1)

    if first_mean == 0:
        return "rising" if second_mean > 0 else "flat"
    ratio = second_mean / first_mean
    if ratio > 1.2:
        return "rising"
    elif ratio < 0.8:
        return "falling"
    return "flat"


def hourly_heatmap(repo: Path, hours: int = 168) -> dict[int, int]:
    """Return a {hour: count} mapping of push races by UTC hour-of-day.

    Hours with no races are included with count 0, so the result always
    has exactly 24 entries.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    races = _load_races(_log_path(repo), since=since)
    counter: Counter[int] = Counter()
    for r in races:
        ts = datetime.fromisoformat(r["at"])
        counter[ts.hour] += 1
    return {h: counter.get(h, 0) for h in range(24)}


def resolution_breakdown(repo: Path, hours: int = 168) -> dict[str, int]:
    """Count races by resolution method (rebase, force, skip, etc.)."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    races = _load_races(_log_path(repo), since=since)
    counter: Counter[str] = Counter()
    for r in races:
        counter[r.get("resolution", "unknown")] += 1
    return dict(counter)
