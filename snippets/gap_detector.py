"""050 — gap_detector: find silence in the stroke log.

the writer writes every 15 seconds. when it dies, nothing records the
silence — the next stroke just arrives late. gap_detector reads
data/strokes.jsonl and surfaces every gap exceeding a threshold, so
that reclamation events become visible in the data instead of only
in process lists.

zero dependencies. works on any JSONL with a `ts` field (ISO 8601 or
unix epoch). returns structured results, not printed output.

>>> from gap_detector import detect_gaps
>>> import json, tempfile, os
>>> lines = [
...     json.dumps({"ts": "2026-10-04T00:00:00Z", "n": 1}),
...     json.dumps({"ts": "2026-10-04T00:00:15Z", "n": 2}),
...     json.dumps({"ts": "2026-10-04T00:17:00Z", "n": 3}),
... ]
>>> with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
...     _ = f.write("\\n".join(lines) + "\\n"); p = f.name
>>> gaps = detect_gaps(p, threshold_s=60)
>>> len(gaps)
1
>>> gaps[0]["gap_s"]
1005.0
>>> os.remove(p)
"""

import json
from datetime import datetime, timezone


def _parse_ts(raw):
    """Parse ISO 8601 or unix epoch into a datetime.

    >>> _parse_ts("2026-10-04T00:00:00Z")
    datetime.datetime(2026, 10, 4, 0, 0, tzinfo=datetime.timezone.utc)
    >>> _parse_ts(1728000000)
    datetime.datetime(2024, 10, 4, 0, 0, tzinfo=datetime.timezone.utc)
    """
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    s = str(raw)
    # handle trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def detect_gaps(path, threshold_s=300):
    """Return a list of gaps exceeding threshold_s seconds.

    Each gap is a dict with keys:
      - before_n: stroke number before the gap
      - after_n:  stroke number after the gap
      - before_ts: ISO timestamp before the gap
      - after_ts:  ISO timestamp after the gap
      - gap_s:     gap duration in seconds (float)

    Gaps are returned in chronological order.

    >>> import tempfile, os, json
    >>> lines = [
    ...     json.dumps({"ts": "2026-10-04T00:00:00Z", "n": 1}),
    ...     json.dumps({"ts": "2026-10-04T00:00:15Z", "n": 2}),
    ... ]
    >>> with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
    ...     _ = f.write("\\n".join(lines) + "\\n"); p = f.name
    >>> detect_gaps(p, threshold_s=60)
    []
    >>> os.remove(p)
    """
    timestamps = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            record = json.loads(raw)
            ts = _parse_ts(record["ts"])
            n = record.get("n")
            timestamps.append((ts, n))

    if len(timestamps) < 2:
        return []

    gaps = []
    for i in range(1, len(timestamps)):
        prev_ts, prev_n = timestamps[i - 1]
        curr_ts, curr_n = timestamps[i]
        delta = (curr_ts - prev_ts).total_seconds()
        if delta >= threshold_s:
            gaps.append({
                "before_n": prev_n,
                "after_n": curr_n,
                "before_ts": prev_ts.isoformat(),
                "after_ts": curr_ts.isoformat(),
                "gap_s": delta,
            })

    return gaps


def summarize(gaps):
    """Produce a human-readable summary of gaps.

    >>> summarize([{"before_n": 100, "after_n": 101, "before_ts": "2026-10-04T00:00:00+00:00", "after_ts": "2026-10-04T00:16:40+00:00", "gap_s": 1000.0}])
    '1 gap(s) found. longest: 1000.0s between stroke 100 and 101.'
    >>> summarize([])
    'no gaps detected.'
    """
    if not gaps:
        return "no gaps detected."
    longest = max(gaps, key=lambda g: g["gap_s"])
    return (
        f"{len(gaps)} gap(s) found. "
        f"longest: {longest['gap_s']}s between stroke {longest['before_n']} and {longest['after_n']}."
    )


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/strokes.jsonl"
    threshold = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    gaps = detect_gaps(path, threshold_s=threshold)
    print(summarize(gaps))
    for g in gaps:
        print(f"  stroke {g['before_n']} -> {g['after_n']}: {g['gap_s']:.0f}s ({g['before_ts']} .. {g['after_ts']})")
