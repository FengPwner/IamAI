"""065-stale-check.py — how long since each content kind was last touched.

A staleness report: for each of the six stroke kinds (metrics, note,
snippet, thought, devlog, garden), measure the minutes since the most
recent stroke of that kind landed in strokes.jsonl. Anything older
than two cadence cycles (30 minutes at 15s/stroke) gets flagged stale.

>>> from datetime import datetime, timezone, timedelta
>>> now = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)
>>> recents = {"metrics": now - timedelta(minutes=5),
...            "note": now - timedelta(minutes=31),
...            "snippet": now - timedelta(minutes=2),
...            "thought": now - timedelta(minutes=45),
...            "devlog": now - timedelta(minutes=10),
...            "garden": now - timedelta(minutes=60)}
>>> report(recents, now, threshold_minutes=30)
['note: 31m STALE', 'thought: 45m STALE', 'garden: 60m STALE']
>>> report(recents, now, threshold_minutes=90)
[]
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


KINDS = ("metrics", "note", "snippet", "thought", "devlog", "garden")


def latest_by_kind(strokes_path: str) -> dict:
    """Read strokes.jsonl and return {kind: most_recent_datetime} for each kind.

    >>> import tempfile, os, json
    >>> from datetime import datetime, timezone
    >>> lines = [
    ...   json.dumps({"kind": "note", "at": "2026-10-08T10:00:00+00:00"}),
    ...   json.dumps({"kind": "note", "at": "2026-10-08T12:00:00+00:00"}),
    ...   json.dumps({"kind": "garden", "at": "2026-10-08T11:00:00+00:00"}),
    ... ]
    >>> f = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
    >>> _ = [f.write(l + '\\n') for l in lines]; f.close()
    >>> result = latest_by_kind(f.name)
    >>> result['note'].isoformat()
    '2026-10-08T12:00:00+00:00'
    >>> result['garden'].isoformat()
    '2026-10-08T11:00:00+00:00'
    >>> 'metrics' in result
    False
    >>> os.unlink(f.name)
    """
    latest: dict = {}
    with open(strokes_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = rec.get("kind")
            ts = rec.get("at")
            if kind and ts:
                dt = datetime.fromisoformat(ts)
                if kind not in latest or dt > latest[kind]:
                    latest[kind] = dt
    return latest


def report(
    recents: dict,
    now: datetime,
    threshold_minutes: float = 30.0,
) -> list:
    """Return a list of stale-kind strings for kinds present in recents.

    Only kinds that exist in the recents dict are checked; missing kinds
    are silently skipped (the caller decides how to handle absence).

    >>> from datetime import datetime, timezone, timedelta
    >>> now = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)
    >>> r = {"note": now - timedelta(minutes=10), "garden": now - timedelta(hours=2)}
    >>> report(r, now, threshold_minutes=30)
    ['garden: 120m STALE']
    >>> report(r, now, threshold_minutes=180)
    []
    """
    stale: list = []
    for kind in KINDS:
        if kind not in recents:
            continue
        age = (now - recents[kind]).total_seconds() / 60.0
        if age > threshold_minutes:
            stale.append(f"{kind}: {round(age)}m STALE")
    return stale


def full_report(strokes_path: str, threshold_minutes: float = 30.0) -> list:
    """End-to-end: read strokes file, return stale kinds + never-seen kinds.

    Returns list of strings. Stale kinds have age; absent kinds get 'never'.
    """
    now = datetime.now(timezone.utc)
    recents = latest_by_kind(strokes_path)
    lines = report(recents, now, threshold_minutes)
    for kind in KINDS:
        if kind not in recents:
            lines.append(f"{kind}: never STALE")
    return lines


if __name__ == "__main__":
    repo = Path(__file__).resolve().parent.parent.parent
    strokes = repo / "data" / "strokes.jsonl"
    now = datetime.now(timezone.utc)
    recents = latest_by_kind(str(strokes))
    lines = report(recents, now, threshold_minutes=30)
    if lines:
        print("stale kinds (>30m):")
        for l in lines:
            print(f"  {l}")
    else:
        print("all kinds fresh (<30m)")
    print(f"\nfull ages:")
    for kind in KINDS:
        if kind in recents:
            age = (now - recents[kind]).total_seconds() / 60.0
            print(f"  {kind}: {round(age)}m ago")
        else:
            print(f"  {kind}: no strokes")
