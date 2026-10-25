"""Stroke continuity — is the sequence unbroken and regular?

Freshness tells you *how recent*, momentum tells you *how fast*,
continuity tells you *how consistent*.  A writer that produces 400
strokes over two hours looks healthy on rate alone — but if 380 of
those came in the first 30 minutes and the remaining 20 were spaced
across the next 90, that "healthy" rate masks a near-stall that the
caretaker needs to know about.

This module computes three metrics:

=====================  ================================================
metric                 meaning
=====================  ================================================
``sequence_integrity`` fraction of consecutive strokes with
                       monotonically increasing sequence numbers
                       and no duplicates (1.0 = perfect)
``temporal_regularity`` 1 − CV of inter-stroke intervals, clamped
                       to [0, 1] (1.0 = clockwork, 0.0 = chaos)
``continuity_score``   geometric mean of the two above
=====================  ================================================

The key insight: continuity is the *second derivative* of throughput.
Rate tells you position, momentum tells you velocity, and continuity
tells you whether the velocity itself is stable.  A writer with
perfect freshness and momentum but broken continuity is a writer
that recovered from a crash — functional but scarred.

Usage::

    from iamai.stroke_continuity import continuity, continuity_summary

    info = continuity(strokes_path=Path("data/strokes.jsonl"))
    print(info["continuity_score"])     # 0.87
    print(info["sequence_integrity"])   # 0.95
    print(info["temporal_regularity"])  # 0.80

    summary = continuity_summary(strokes_path=...)
    # "continuity 0.87 — seq_integrity 0.95, temporal_regularity 0.80, 400 strokes"
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_STROKES_PATH = Path("data/strokes.jsonl")


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a timezone-aware datetime.

    Handles ``+00:00``, ``Z`` suffixes, and bare datetimes (assumed UTC).
    """
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_strokes(path: Path) -> list[dict]:
    """Load strokes from a JSONL file, adding ``_dt`` and ``_seq`` keys."""
    strokes: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                obj["_dt"] = _parse_timestamp(obj["at"])
                obj["_seq"] = int(obj["seq"])
                strokes.append(obj)
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                continue
    return strokes


# ---------------------------------------------------------------------------
# Sequence integrity
# ---------------------------------------------------------------------------

def sequence_integrity(strokes: list[dict]) -> float:
    """Fraction of consecutive pairs that are strictly consecutive (seq+1).

    Returns 1.0 for an empty list or a single stroke (vacuously ordered).
    Gaps (seq jumps by >1), duplicates, and descents all count as violations.
    """
    if len(strokes) < 2:
        return 1.0

    ok = 0
    total = len(strokes) - 1
    for i in range(total):
        if strokes[i + 1]["_seq"] == strokes[i]["_seq"] + 1:
            ok += 1
    return ok / total


# ---------------------------------------------------------------------------
# Temporal regularity
# ---------------------------------------------------------------------------

def temporal_regularity(strokes: list[dict]) -> float:
    """1 − coefficient_of_variation of inter-stroke intervals (seconds).

    Returns 1.0 for a single stroke or empty list (no intervals to vary).
    Clamped to [0.0, 1.0].
    """
    if len(strokes) < 2:
        return 1.0

    intervals: list[float] = []
    for i in range(len(strokes) - 1):
        dt = (strokes[i + 1]["_dt"] - strokes[i]["_dt"]).total_seconds()
        intervals.append(max(dt, 0.0))  # negative gaps → 0 (clock skew)

    if not intervals:
        return 1.0

    mean = sum(intervals) / len(intervals)
    if mean <= 0:
        return 0.0  # all strokes at the same instant → maximum irregularity

    variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
    std = math.sqrt(variance)
    cv = std / mean
    return max(0.0, min(1.0, 1.0 - cv))


# ---------------------------------------------------------------------------
# Composite score
# ---------------------------------------------------------------------------

def continuity(
    repo: Path | None = None,
    strokes_path: Path | None = None,
    tail: int = 0,
) -> dict:
    """Compute stroke continuity metrics.

    Args:
        repo: repository root (used to locate strokes file)
        strokes_path: explicit path to strokes JSONL (overrides repo)
        tail: if > 0, only examine the last ``tail`` strokes;
              if 0, examine all strokes.

    Returns:
        dict with keys:
            - ``sequence_integrity``: 0.0–1.0
            - ``temporal_regularity``: 0.0–1.0
            - ``continuity_score``: geometric mean of the two above
            - ``stroke_count``: number of strokes examined
            - ``seq_violations``: count of non-increasing consecutive pairs
            - ``mean_interval_s``: mean inter-stroke interval in seconds
    """
    if strokes_path is None:
        base = Path(repo) if repo else Path(".")
        strokes_path = base / _DEFAULT_STROKES_PATH

    strokes = _load_strokes(strokes_path)
    if tail > 0:
        strokes = strokes[-tail:]

    seq_int = sequence_integrity(strokes)
    temp_reg = temporal_regularity(strokes)

    # Geometric mean: penalises lopsided scores more than arithmetic mean
    if seq_int > 0 and temp_reg > 0:
        score = math.sqrt(seq_int * temp_reg)
    else:
        score = 0.0

    # Count violations for diagnostics
    violations = 0
    if len(strokes) >= 2:
        for i in range(len(strokes) - 1):
            if strokes[i + 1]["_seq"] != strokes[i]["_seq"] + 1:
                violations += 1

    # Mean interval
    mean_interval = 0.0
    if len(strokes) >= 2:
        total_s = (strokes[-1]["_dt"] - strokes[0]["_dt"]).total_seconds()
        mean_interval = total_s / (len(strokes) - 1)

    return {
        "sequence_integrity": round(seq_int, 4),
        "temporal_regularity": round(temp_reg, 4),
        "continuity_score": round(score, 4),
        "stroke_count": len(strokes),
        "seq_violations": violations,
        "mean_interval_s": round(mean_interval, 1),
    }


def continuity_summary(
    repo: Path | None = None,
    strokes_path: Path | None = None,
    tail: int = 100,
) -> str:
    """One-liner continuity summary for caretaker logs.

    Example::

        "continuity 0.8700 — seq_integrity 0.9500, temporal_regularity 0.7970, 100 strokes"
    """
    info = continuity(repo=repo, strokes_path=strokes_path, tail=tail)
    return (
        f"continuity {info['continuity_score']} — "
        f"seq_integrity {info['sequence_integrity']}, "
        f"temporal_regularity {info['temporal_regularity']}, "
        f"{info['stroke_count']} strokes"
    )
