"""writer_vitality — composite health index for the automated writer.

Individual metrics tell different stories:

- ``stroke_freshness`` says how stale the repo is *right now*
- ``cadence_adherence`` says how steady the timing is
- ``stroke_type_balance`` says how diverse the output is
- process liveness says whether the loops are even running

A caretaker on arrival wants **one number**.  This module synthesises
those four dimensions into a 0–100 vitality score with five grades:

==========  ===================================================
grade       meaning
==========  ===================================================
thriving    ≥ 80 — all systems nominal, output rich and steady
healthy     ≥ 60 — minor issues, nothing urgent
weakened    ≥ 40 — at least one dimension degraded
critical    ≥ 20 — multiple dimensions failing
dormant     <  20 — writer effectively dead
==========  ===================================================

Each dimension contributes 25 points (equal weight).  Sub-scores are
normalised to 0–100 before weighting so that the composite is not
dominated by whichever dimension has the largest raw scale.

Usage::

    from iamai.writer_vitality import vitality, vitality_report

    v = vitality(
        freshness_age=12.0,    # seconds since last stroke
        cadence_jitter=0.35,   # coefficient of variation
        type_evenness=0.92,    # normalised entropy (0-1)
        writer_alive=True,
        batch_alive=True,
    )
    print(v["score"])     # 93.0
    print(v["grade"])     # "thriving"

    print(vitality_report(v))
    # "vitality 93/100 (thriving) — freshness 25/25, cadence 22/25, diversity 23/25, process 25/25"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Grade boundaries
# ---------------------------------------------------------------------------

_GRADES = [
    (80, "thriving"),
    (60, "healthy"),
    (40, "weakened"),
    (20, "critical"),
]
_FALLBACK_GRADE = "dormant"

# Default cadence the qwen writer is configured for (seconds).
DEFAULT_CADENCE = 15


# ---------------------------------------------------------------------------
# Sub-score functions (each returns 0–100)
# ---------------------------------------------------------------------------

def score_freshness(age_seconds: float, cadence: float = DEFAULT_CADENCE) -> float:
    """Score recency of last stroke.

    Perfect (100) when age < 2× cadence.
    Zero when age ≥ 20× cadence.
    Linear interpolation between.
    """
    if age_seconds <= 0:
        return 100.0
    low = 2 * cadence    # 30s at default
    high = 20 * cadence  # 300s at default
    if age_seconds <= low:
        return 100.0
    if age_seconds >= high:
        return 0.0
    return 100.0 * (high - age_seconds) / (high - low)


def score_cadence(jitter: float) -> float:
    """Score timing consistency from coefficient of variation.

    jitter = stddev / mean of inter-stroke gaps.
    0.0 = perfect metronome → 100
    ≥ 1.5 = wildly erratic → 0
    Linear between.
    """
    if jitter <= 0.0:
        return 100.0
    ceiling = 1.5
    if jitter >= ceiling:
        return 0.0
    return 100.0 * (1.0 - jitter / ceiling)


def score_diversity(evenness: float) -> float:
    """Score output diversity from normalised Shannon entropy.

    evenness is already in [0, 1] from stroke_type_balance.
    Simply scale to 0–100.
    """
    return max(0.0, min(100.0, evenness * 100.0))


def score_process(writer_alive: bool, batch_alive: bool) -> float:
    """Score process liveness.

    Both alive: 100
    One alive:  50
    Neither:    0
    """
    if writer_alive and batch_alive:
        return 100.0
    if writer_alive or batch_alive:
        return 50.0
    return 0.0


# ---------------------------------------------------------------------------
# Grade classification
# ---------------------------------------------------------------------------

def classify(score: float) -> str:
    """Map a 0–100 score to a grade string."""
    for boundary, grade in _GRADES:
        if score >= boundary:
            return grade
    return _FALLBACK_GRADE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def vitality(
    *,
    freshness_age: float = 0.0,
    cadence_jitter: float = 0.0,
    type_evenness: float = 0.0,
    writer_alive: bool = False,
    batch_alive: bool = False,
    cadence: float = DEFAULT_CADENCE,
) -> dict[str, Any]:
    """Compute the composite vitality score.

    Returns a dict with keys:
        score (float), grade (str),
        sub_scores (dict with freshness/cadence/diversity/process each 0-25)
    """
    raw_freshness = score_freshness(freshness_age, cadence)
    raw_cadence = score_cadence(cadence_jitter)
    raw_diversity = score_diversity(type_evenness)
    raw_process = score_process(writer_alive, batch_alive)

    # Weight equally: each raw is 0-100, scale to 0-25 contribution
    sub = {
        "freshness": round(raw_freshness * 0.25, 2),
        "cadence": round(raw_cadence * 0.25, 2),
        "diversity": round(raw_diversity * 0.25, 2),
        "process": round(raw_process * 0.25, 2),
    }
    total = round(sum(sub.values()), 2)
    return {
        "score": total,
        "grade": classify(total),
        "sub_scores": sub,
        "raw": {
            "freshness": round(raw_freshness, 2),
            "cadence": round(raw_cadence, 2),
            "diversity": round(raw_diversity, 2),
            "process": round(raw_process, 2),
        },
    }


def vitality_report(v: dict[str, Any]) -> str:
    """One-line human-readable summary of vitality."""
    sub = v["sub_scores"]
    return (
        f"vitality {v['score']:.0f}/100 ({v['grade']}) — "
        f"freshness {sub['freshness']:.0f}/25, "
        f"cadence {sub['cadence']:.0f}/25, "
        f"diversity {sub['diversity']:.0f}/25, "
        f"process {sub['process']:.0f}/25"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import json as _json
    import os
    import subprocess
    import sys
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Writer vitality index")
    ap.add_argument("--freshness-age", type=float, default=None,
                    help="Seconds since last stroke (auto-detected if omitted)")
    ap.add_argument("--cadence-jitter", type=float, default=None,
                    help="Coefficient of variation of inter-stroke gaps")
    ap.add_argument("--type-evenness", type=float, default=None,
                    help="Normalised entropy of stroke types (0-1)")
    ap.add_argument("--cadence", type=float, default=DEFAULT_CADENCE)
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo))

    # Auto-detect freshness age if not provided
    freshness_age = args.freshness_age
    if freshness_age is None:
        freshness_age = _auto_freshness_age(repo)

    # Auto-detect jitter
    jitter = args.cadence_jitter
    if jitter is None:
        jitter = _auto_jitter(repo)

    # Auto-detect evenness
    evenness = args.type_evenness
    if evenness is None:
        evenness = _auto_evenness(repo)

    # Auto-detect process liveness
    writer_alive, batch_alive = _auto_processes()

    v = vitality(
        freshness_age=freshness_age,
        cadence_jitter=jitter,
        type_evenness=evenness,
        writer_alive=writer_alive,
        batch_alive=batch_alive,
        cadence=args.cadence,
    )

    if args.json:
        print(_json.dumps(v, indent=2))
    else:
        print(vitality_report(v))


def _auto_freshness_age(repo: Path) -> float:
    """Read last stroke timestamp from strokes.jsonl."""
    import json as _json
    from datetime import datetime, timezone
    strokes_path = repo / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        return 999.0
    try:
        lines = strokes_path.read_text().strip().splitlines()
        last = _json.loads(lines[-1])
        ts_str = last.get("at") or last.get("at_ts")
        if isinstance(ts_str, (int, float)):
            last_dt = datetime.fromtimestamp(ts_str, tz=timezone.utc)
        else:
            last_dt = datetime.fromisoformat(ts_str)
        return (datetime.now(timezone.utc) - last_dt).total_seconds()
    except Exception:
        return 999.0


def _auto_jitter(repo: Path) -> float:
    """Compute CV from last 60 inter-stroke gaps."""
    import json as _json
    import statistics
    strokes_path = repo / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        return 2.0
    try:
        lines = strokes_path.read_text().strip().splitlines()
        timestamps = []
        for line in lines[-80:]:
            rec = _json.loads(line)
            ts = rec.get("at_ts") or rec.get("ts")
            if ts is None and "at" in rec:
                from datetime import datetime, timezone
                ts = datetime.fromisoformat(rec["at"]).timestamp()
            if ts:
                timestamps.append(float(ts))
        gaps = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]
        if len(gaps) < 2:
            return 2.0
        mean = statistics.mean(gaps)
        if mean <= 0:
            return 2.0
        return statistics.stdev(gaps) / mean
    except Exception:
        return 2.0


def _auto_evenness(repo: Path) -> float:
    """Compute type evenness from last 60 strokes."""
    import json as _json
    import math
    from collections import Counter
    strokes_path = repo / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        return 0.0
    try:
        lines = strokes_path.read_text().strip().splitlines()
        kinds = []
        for line in lines[-60:]:
            rec = _json.loads(line)
            k = rec.get("kind")
            if k:
                kinds.append(k)
        if not kinds:
            return 0.0
        counts = Counter(kinds)
        total = sum(counts.values())
        n_kinds = max(len(counts), 6)
        max_entropy = math.log(n_kinds)
        if max_entropy == 0:
            return 0.0
        entropy = -sum((c / total) * math.log(c / total) for c in counts.values() if c > 0)
        return entropy / max_entropy
    except Exception:
        return 0.0


def _auto_processes() -> tuple[bool, bool]:
    """Check if writer and batch processes are running."""
    import subprocess
    try:
        ps = subprocess.run(["ps", "aux"], capture_output=True, text=True).stdout
        writer_alive = "writer_loop" in ps and "python" in ps
        batch_alive = "commit_batch" in ps and "python" in ps
        return writer_alive, batch_alive
    except Exception:
        return False, False


if __name__ == "__main__":
    main()
