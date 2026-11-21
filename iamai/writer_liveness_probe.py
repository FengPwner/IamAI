#!/usr/bin/env python3
"""writer_liveness_probe — composite health check for the writing pipeline.

A writer process that exists but hasn't produced a stroke in 30 minutes
is *alive* but not *live*.  A batch committer that exists but has 50
uncommitted files is *running* but not *healthy*.  Existing modules check
individual signals (process existence, stroke freshness, backlog size)
but none combine them into a single liveness verdict that a caretaker
can use for a quick go/no-go decision.

This module does that.  It evaluates four independent signals and
produces a composite ``LivenessVerdict``:

Signals
-------

==================  ====================================================
signal              healthy when
==================  ====================================================
process_alive       writer PID exists and is a running process
stroke_fresh        last stroke timestamp is within ``stale_threshold``
                    seconds of now (default 300 s = 5 min)
backlog_clear       uncommitted file count is below ``backlog_limit``
                    (default 20 files)
commit_fresh        most recent commit is within ``commit_stale``
                    seconds of now (default 900 s = 15 min)
==================  ====================================================

Verdicts
--------

============  ==========================================================
verdict       meaning
============  ==========================================================
``healthy``   all four signals green — pipeline is fully operational
``degraded``  1–2 signals failed — something is off but not critical
``stalled``   3+ signals failed — pipeline is effectively broken
============  ==========================================================

The verdict is intentionally coarse: a caretaker checking in at 3 AM
needs "healthy / degraded / stalled", not a 47-field JSON blob.
Detailed diagnostics live in the individual signal results.

Design decisions
----------------

- Pure evaluation: the caller provides signal values, the module
  returns a verdict.  No subprocess calls, no file I/O in core logic.
  This makes it trivially testable with synthetic inputs.
- ``evaluate_liveness()`` accepts a ``LivenessSignals`` dataclass
  rather than raw arguments — adding a fifth signal later is a
  non-breaking change.
- Thresholds are configurable per-call, not module-level constants.
  Different repos have different cadences; a 5-minute stale threshold
  makes sense for a 15-second writer but not for a daily reporter.
- The ``signal_results`` dict in the verdict preserves which signals
  passed and failed, so dashboards can render per-signal status
  without re-evaluating.

Usage::

    from iamai.writer_liveness_probe import (
        LivenessSignals, evaluate_liveness, liveness_summary,
    )

    signals = LivenessSignals(
        process_alive=True,
        stroke_age_seconds=45.0,
        uncommitted_files=3,
        commit_age_seconds=120.0,
    )

    verdict = evaluate_liveness(signals)
    print(verdict.status)           # "healthy"
    print(verdict.failed_signals)   # []

    # With custom thresholds:
    verdict = evaluate_liveness(
        signals,
        stale_threshold=60.0,
        backlog_limit=10,
        commit_stale=300.0,
    )

    # One-liner for logs:
    print(liveness_summary(signals))
    # "liveness: healthy (4/4 signals green)"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# signal inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LivenessSignals:
    """Snapshot of pipeline health signals.

    All values are point-in-time measurements provided by the caller.
    The probe module does not collect these — it only evaluates them.

    Attributes:
        process_alive: whether the writer process PID is currently
            running (True) or missing/dead (False).
        stroke_age_seconds: seconds since the most recent stroke
            timestamp in strokes.jsonl.  Lower is fresher.
        uncommitted_files: number of files with uncommitted changes
            in the working tree.  Lower is cleaner.
        commit_age_seconds: seconds since the most recent git commit.
            Lower is fresher.
    """
    process_alive: bool
    stroke_age_seconds: float
    uncommitted_files: int
    commit_age_seconds: float


# ---------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LivenessVerdict:
    """Result of a liveness evaluation.

    Attributes:
        status: one of "healthy", "degraded", or "stalled".
        passed: number of signals that passed.
        total: total number of signals evaluated.
        failed_signals: names of signals that failed.
        signal_results: mapping of signal name → (passed, detail).
    """
    status: str
    passed: int
    total: int
    failed_signals: List[str]
    signal_results: Dict[str, tuple]  # name → (passed: bool, detail: str)


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------

# Default thresholds
DEFAULT_STALE_THRESHOLD = 300.0   # 5 minutes
DEFAULT_BACKLOG_LIMIT = 20       # files
DEFAULT_COMMIT_STALE = 900.0     # 15 minutes


def evaluate_liveness(
    signals: LivenessSignals,
    stale_threshold: float = DEFAULT_STALE_THRESHOLD,
    backlog_limit: int = DEFAULT_BACKLOG_LIMIT,
    commit_stale: float = DEFAULT_COMMIT_STALE,
) -> LivenessVerdict:
    """Evaluate pipeline health from a signal snapshot.

    Args:
        signals: point-in-time measurements of the writing pipeline.
        stale_threshold: max acceptable seconds since last stroke.
        backlog_limit: max acceptable uncommitted file count.
        commit_stale: max acceptable seconds since last commit.

    Returns:
        LivenessVerdict with status, counts, and per-signal details.

    Raises:
        ValueError: if any threshold is non-positive.
    """
    if stale_threshold <= 0:
        raise ValueError(f"stale_threshold must be positive, got {stale_threshold}")
    if backlog_limit <= 0:
        raise ValueError(f"backlog_limit must be positive, got {backlog_limit}")
    if commit_stale <= 0:
        raise ValueError(f"commit_stale must be positive, got {commit_stale}")

    results: Dict[str, tuple] = {}

    # Signal 1: process alive
    results["process_alive"] = (
        signals.process_alive,
        "running" if signals.process_alive else "dead/missing",
    )

    # Signal 2: stroke freshness
    stroke_ok = signals.stroke_age_seconds <= stale_threshold
    results["stroke_fresh"] = (
        stroke_ok,
        f"{signals.stroke_age_seconds:.0f}s ago (limit {stale_threshold:.0f}s)",
    )

    # Signal 3: backlog
    backlog_ok = signals.uncommitted_files <= backlog_limit
    results["backlog_clear"] = (
        backlog_ok,
        f"{signals.uncommitted_files} uncommitted (limit {backlog_limit})",
    )

    # Signal 4: commit freshness
    commit_ok = signals.commit_age_seconds <= commit_stale
    results["commit_fresh"] = (
        commit_ok,
        f"{signals.commit_age_seconds:.0f}s ago (limit {commit_stale:.0f}s)",
    )

    failed = [name for name, (ok, _) in results.items() if not ok]
    passed = len(results) - len(failed)
    total = len(results)

    if len(failed) == 0:
        status = "healthy"
    elif len(failed) <= 2:
        status = "degraded"
    else:
        status = "stalled"

    return LivenessVerdict(
        status=status,
        passed=passed,
        total=total,
        failed_signals=failed,
        signal_results=results,
    )


# ---------------------------------------------------------------------------
# convenience
# ---------------------------------------------------------------------------


def liveness_summary(
    signals: LivenessSignals,
    stale_threshold: float = DEFAULT_STALE_THRESHOLD,
    backlog_limit: int = DEFAULT_BACKLOG_LIMIT,
    commit_stale: float = DEFAULT_COMMIT_STALE,
) -> str:
    """One-line human-readable liveness report.

    Args:
        signals: pipeline signal snapshot.
        stale_threshold: max stroke age in seconds.
        backlog_limit: max uncommitted files.
        commit_stale: max commit age in seconds.

    Returns:
        A string like "liveness: healthy (4/4 signals green)" or
        "liveness: stalled (1/4 green) — failed: process_alive, stroke_fresh, commit_fresh".
    """
    verdict = evaluate_liveness(signals, stale_threshold, backlog_limit, commit_stale)
    base = f"liveness: {verdict.status} ({verdict.passed}/{verdict.total} signals green)"
    if verdict.failed_signals:
        base += f" — failed: {', '.join(verdict.failed_signals)}"
    return base


def verdict_from_dict(data: dict) -> LivenessVerdict:
    """Reconstruct a LivenessVerdict from a plain dict.

    Useful for deserialising verdicts stored in JSON logs.

    Expected keys: status, passed, total, failed_signals, signal_results.
    signal_results values are [passed, detail] lists (JSON doesn't have tuples).

    Args:
        data: dict with verdict fields.

    Returns:
        LivenessVerdict.
    """
    signal_results = {}
    for name, (ok, detail) in data.get("signal_results", {}).items():
        signal_results[name] = (bool(ok), str(detail))

    return LivenessVerdict(
        status=str(data.get("status", "unknown")),
        passed=int(data.get("passed", 0)),
        total=int(data.get("total", 0)),
        failed_signals=list(data.get("failed_signals", [])),
        signal_results=signal_results,
    )
