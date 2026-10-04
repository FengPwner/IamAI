"""057 — style-shape: classify a writer's tempo, not just its gaps.

052 measures drift, 054 splits absence from rhythm — but nobody has
named the shape of a rhythm itself. two honest ways to be alive:
the metronome (steady beats, low spread) and the sprinter
(furious bursts, then long nests). the classifier stays humble:
three names, simple thresholds, no trend words.

>>> shape([60, 61, 59, 60, 62])
'metronome'
>>> shape([1, 1, 1, 90, 1, 1])
'sprinter'
>>> shape([30, 90, 45, 60])
'mixed'
>>> shape([50.0])
'too few intervals'
"""

from __future__ import annotations

import statistics


def shape(intervals: list[float]) -> str:
    """Name the tempo shape from minute-intervals.

    metronome: every interval within ±25% of the median.
    sprinter:  max interval > 3x median (bursts plus long nests).
    mixed:     everything else honest.

    >>> shape([10.0, 10.5, 9.8, 10.2])
    'metronome'
    >>> shape([2.0, 2.0, 75.0, 2.0])
    'sprinter'
    >>> shape([20.0, 55.0, 30.0, 40.0])
    'mixed'
    """
    if len(intervals) < 2:
        return "too few intervals"
    med = statistics.median(intervals)
    if med <= 0:
        return "mixed"
    mx, mn = max(intervals), min(intervals)
    if mx > 3 * med:
        return "sprinter"
    if mx <= 1.25 * med and mn >= 0.75 * med:
        return "metronome"
    return "mixed"


def from_strokes(path: str, n: int = 21) -> list[float]:
    """Minute-intervals from the last n lines of a strokes ledger.

    >>> from_strokes('/nonexistent/path.jsonl')
    []
    """
    try:
        with open(path) as f:
            lines = f.readlines()[-n:]
    except OSError:
        return []
    import datetime

    times = []
    for line in lines:
        try:
            rec = json.loads(line)
            times.append(datetime.datetime.fromisoformat(rec["at"]))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    times.sort()
    return [
        round((b - a).total_seconds() / 60.0, 1)
        for a, b in zip(times, times[1:])
    ]


import json  # noqa: E402  (used by from_strokes; kept at module tail so
              # the doctest loader sees a plain, dumb module)

if __name__ == "__main__":
    import doctest

    failures = doctest.testmod(verbose=False).failed
    iv = from_strokes("/root/iamai/data/strokes.jsonl", 21)
    print(f"qwen last {len(iv)} intervals:", iv[-8:] if iv else "n/a")
    print("shape:", shape(iv) if iv else "n/a")
    raise SystemExit(1 if failures else 0)
