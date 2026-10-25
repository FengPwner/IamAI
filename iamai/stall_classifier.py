"""Stall classifier — diagnose why the writer went silent.

Given observable signals (stroke timestamps, process status, lock file
presence, system resource snapshots), this module classifies a writer
stall into one of five root-cause categories:

Categories
----------

1. **process_death** — the writer process was killed by the container
   runtime or OOM killer.  Signals: process absent, last stroke abrupt,
   off-peak hour, bundled deaths with batch committer.

2. **lock_contention** — a stale ``.git/index.lock`` blocked commits,
   causing the writer to back off.  Signals: lock file present, process
   alive but idle, commit gap >> stroke gap.

3. **resource_exhaustion** — disk full, memory pressure, or I/O errors.
   Signals: disk usage > 90 %, dmesg OOM lines, ENOSPC in recent logs.

4. **natural_gap** — the pause is within normal operating parameters.
   The writer has a stochastic cadence; not every gap is a stall.
   Signals: gap < 2× modal interval, process alive, no error signals.

5. **unknown** — insufficient evidence to classify.

Usage::

    from iamai.stall_classifier import classify_stall

    evidence = {
        "gap_seconds": 1600,
        "modal_interval": 400,
        "process_alive": False,
        "batch_alive": False,
        "lock_present": False,
        "hour_gmt8": 4,
        "disk_usage_pct": 45,
        "dmesg_oom": False,
    }

    result = classify_stall(evidence)
    print(result["label"])        # "process_death"
    print(result["confidence"])   # 0.92
    print(result["reasons"])      # ["off_peak", "bundled_death", ...]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# signal weights for each category
# ---------------------------------------------------------------------------

_WEIGHTS: dict[str, dict[str, float]] = {
    "process_death": {
        "process_dead": 0.30,
        "batch_dead": 0.15,
        "off_peak": 0.25,
        "abrupt_last_stroke": 0.10,
        "no_lock": 0.05,
        "long_gap": 0.15,
    },
    "lock_contention": {
        "lock_present": 0.40,
        "process_alive": 0.25,
        "commit_gap_exceeds_stroke_gap": 0.20,
        "no_dmesg_oom": 0.05,
        "disk_ok": 0.10,
    },
    "resource_exhaustion": {
        "high_disk": 0.30,
        "dmesg_oom": 0.35,
        "process_dead": 0.15,
        "io_errors": 0.15,
        "long_gap": 0.05,
    },
    "natural_gap": {
        "process_alive": 0.30,
        "short_gap": 0.35,
        "no_lock": 0.10,
        "disk_ok": 0.10,
        "peak_hour": 0.10,
        "no_dmesg_oom": 0.05,
    },
}

# off-peak window in GMT+8 (container runtime sweeps aggressively)
_OFF_PEAK_START = 1  # 01:00
_OFF_PEAK_END = 6    # 06:00


def _is_off_peak(hour_gmt8: int) -> bool:
    """Return True if *hour_gmt8* falls in the 01:00–06:00 sweep window."""
    return _OFF_PEAK_START <= hour_gmt8 < _OFF_PEAK_END


def _is_long_gap(gap_seconds: float, modal_interval: float) -> bool:
    """Return True if the gap is more than 2× the modal interval."""
    if modal_interval <= 0:
        return True
    return gap_seconds > 2 * modal_interval


def _collect_signals(evidence: dict[str, Any]) -> dict[str, dict[str, bool]]:
    """Map raw evidence to boolean signals per category."""
    gap = evidence.get("gap_seconds", 0)
    modal = evidence.get("modal_interval", 400)
    proc = evidence.get("process_alive", True)
    batch = evidence.get("batch_alive", True)
    lock = evidence.get("lock_present", False)
    hour = evidence.get("hour_gmt8", 12)
    disk = evidence.get("disk_usage_pct", 0)
    oom = evidence.get("dmesg_oom", False)
    io_err = evidence.get("io_errors", False)
    abrupt = evidence.get("abrupt_last_stroke", False)
    commit_gap_exceeds = evidence.get("commit_gap_exceeds_stroke_gap", False)

    long_gap = _is_long_gap(gap, modal)
    off_peak = _is_off_peak(hour)

    return {
        "process_death": {
            "process_dead": not proc,
            "batch_dead": not batch,
            "off_peak": off_peak,
            "abrupt_last_stroke": abrupt,
            "no_lock": not lock,
            "long_gap": long_gap,
        },
        "lock_contention": {
            "lock_present": lock,
            "process_alive": proc,
            "commit_gap_exceeds_stroke_gap": commit_gap_exceeds,
            "no_dmesg_oom": not oom,
            "disk_ok": disk < 90,
        },
        "resource_exhaustion": {
            "high_disk": disk >= 90,
            "dmesg_oom": oom,
            "process_dead": not proc,
            "io_errors": io_err,
            "long_gap": long_gap,
        },
        "natural_gap": {
            "process_alive": proc,
            "short_gap": not long_gap,
            "no_lock": not lock,
            "disk_ok": disk < 90,
            "peak_hour": not off_peak,
            "no_dmesg_oom": not oom,
        },
    }


def _score_category(
    category: str, signals: dict[str, bool]
) -> tuple[float, list[str]]:
    """Compute weighted score for one category, return (score, reasons)."""
    weights = _WEIGHTS[category]
    score = 0.0
    reasons: list[str] = []
    for signal_name, weight in weights.items():
        if signals.get(signal_name, False):
            score += weight
            reasons.append(signal_name)
    return round(score, 4), reasons


def classify_stall(evidence: dict[str, Any]) -> dict[str, Any]:
    """Classify a writer stall from observable evidence.

    Parameters
    ----------
    evidence : dict
        Observable signals.  See module docstring for the full schema.

    Returns
    -------
    dict with keys:
        - ``label`` (str): winning category name
        - ``confidence`` (float): score of the winning category [0, 1]
        - ``reasons`` (list[str]): signals that contributed to the win
        - ``scores`` (dict[str, float]): all category scores
    """
    signal_map = _collect_signals(evidence)
    scores: dict[str, float] = {}
    all_reasons: dict[str, list[str]] = {}

    for category in _WEIGHTS:
        s, r = _score_category(category, signal_map[category])
        scores[category] = s
        all_reasons[category] = r

    # pick the highest-scoring category
    label = max(scores, key=lambda k: scores[k])
    confidence = scores[label]

    return {
        "label": label,
        "confidence": confidence,
        "reasons": all_reasons[label],
        "scores": scores,
    }


def classify_stalls_batch(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Classify a list of stall events.  Convenience wrapper."""
    return [classify_stall(e) for e in events]


def summarise(classifications: list[dict[str, Any]]) -> dict[str, int]:
    """Count how many stalls fell into each category.

    Parameters
    ----------
    classifications : list
        Output of :func:`classify_stalls_batch`.

    Returns
    -------
    dict mapping category labels to integer counts.
    """
    counts: dict[str, int] = {cat: 0 for cat in _WEIGHTS}
    for c in classifications:
        counts[c["label"]] = counts.get(c["label"], 0) + 1
    return counts
