"""pipeline_health_index — single-number health for the writing pipeline.

The IamAI repo has dozens of specialised monitors (writer_vitality,
commit_rhythm_score, stroke_novelty, push_lag …).  A caretaker must
consult many of them to answer the simplest question:

    *"Is the pipeline healthy right now?"*

This module collapses four signals into one **health index** ∈ [0, 1].

Signals
-------
========================  ============================================
signal                    source
========================  ============================================
``writer_freshness``      seconds since last stroke (lower = better)
``commit_freshness``      seconds since last local commit (lower = better)
``backlog_ratio``         uncommitted files / expected max (lower = better)
``push_lag``              unpushed commits count (lower = better)
========================  ============================================

Weights (sum to 1.0)::

    writer_freshness   0.35
    commit_freshness   0.25
    backlog_ratio      0.20
    push_lag           0.20

Verdicts
--------
===========  =======  ==========================================
verdict      range    meaning
===========  =======  ==========================================
``healthy``  ≥ 0.80   pipeline running smoothly
``warn``     0.50–0.79 something needs attention
``critical`` 0.20–0.49 significant degradation
``down``     < 0.20   pipeline essentially non-functional
===========  =======  ==========================================

Usage::

    from iamai.pipeline_health_index import PipelineHealthIndex

    idx = PipelineHealthIndex()
    idx.compute(
        writer_freshness_s=15,
        commit_freshness_s=120,
        uncommitted_files=2,
        unpushed_commits=0,
    )
    # {'index': 0.93, 'verdict': 'healthy', ...}
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Scoring parameters
# ---------------------------------------------------------------------------

# Each signal has a "perfect" threshold and a "zero" threshold.
# Between them the score decays linearly.

_WRITER_FRESHNESS_PERFECT = 30    # seconds since last stroke
_WRITER_FRESHNESS_ZERO = 600      # 10 min without a stroke → score 0

_COMMIT_FRESHNESS_PERFECT = 120   # committed within 2 min
_COMMIT_FRESHNESS_ZERO = 900      # 15 min without commit → score 0

_BACKLOG_MAX = 20                 # 20+ uncommitted files → score 0
_PUSH_LAG_MAX = 5                 # 5+ unpushed commits → score 0

WEIGHTS = {
    "writer_freshness": 0.35,
    "commit_freshness": 0.25,
    "backlog_ratio": 0.20,
    "push_lag": 0.20,
}


# ---------------------------------------------------------------------------
# Linear decay helper
# ---------------------------------------------------------------------------

def _linear_score(value: float, perfect: float, zero: float) -> float:
    """Return 1.0 when *value* ≤ *perfect*, 0.0 when ≥ *zero*, linear between."""
    if value <= perfect:
        return 1.0
    if value >= zero:
        return 0.0
    span = zero - perfect
    return 1.0 - (value - perfect) / span


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def _verdict(index: float) -> str:
    if index >= 0.80:
        return "healthy"
    if index >= 0.50:
        return "warn"
    if index >= 0.20:
        return "critical"
    return "down"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class PipelineHealthIndex:
    """Compute and (optionally) trend the pipeline health index."""

    def __init__(self, history_size: int = 20):
        self._history: list[float] = []
        self._history_size = history_size

    # -- compute ------------------------------------------------------------

    def compute(
        self,
        writer_freshness_s: float,
        commit_freshness_s: float,
        uncommitted_files: int,
        unpushed_commits: int,
    ) -> dict[str, Any]:
        """Return a dict with the composite index, verdict, and sub-scores."""
        s_writer = _linear_score(
            writer_freshness_s,
            _WRITER_FRESHNESS_PERFECT,
            _WRITER_FRESHNESS_ZERO,
        )
        s_commit = _linear_score(
            commit_freshness_s,
            _COMMIT_FRESHNESS_PERFECT,
            _COMMIT_FRESHNESS_ZERO,
        )
        s_backlog = _linear_score(uncommitted_files, 0, _BACKLOG_MAX)
        s_push = _linear_score(unpushed_commits, 0, _PUSH_LAG_MAX)

        index = (
            WEIGHTS["writer_freshness"] * s_writer
            + WEIGHTS["commit_freshness"] * s_commit
            + WEIGHTS["backlog_ratio"] * s_backlog
            + WEIGHTS["push_lag"] * s_push
        )
        index = max(0.0, min(1.0, index))

        self._history.append(index)
        if len(self._history) > self._history_size:
            self._history.pop(0)

        return {
            "index": round(index, 4),
            "verdict": _verdict(index),
            "sub_scores": {
                "writer_freshness": round(s_writer, 4),
                "commit_freshness": round(s_commit, 4),
                "backlog_ratio": round(s_backlog, 4),
                "push_lag": round(s_push, 4),
            },
            "inputs": {
                "writer_freshness_s": writer_freshness_s,
                "commit_freshness_s": commit_freshness_s,
                "uncommitted_files": uncommitted_files,
                "unpushed_commits": unpushed_commits,
            },
        }

    # -- trend --------------------------------------------------------------

    def trend(self) -> str:
        """Return 'improving', 'declining', or 'flat' based on history."""
        if len(self._history) < 3:
            return "insufficient_data"
        mid = len(self._history) // 2
        first_half = sum(self._history[:mid]) / mid
        second_half = sum(self._history[mid:]) / (len(self._history) - mid)
        diff = second_half - first_half
        if diff > 0.05:
            return "improving"
        if diff < -0.05:
            return "declining"
        return "flat"

    def history(self) -> list[float]:
        """Return a copy of the recent index history."""
        return list(self._history)

    # -- one-liner ----------------------------------------------------------

    def summary(
        self,
        writer_freshness_s: float,
        commit_freshness_s: float,
        uncommitted_files: int,
        unpushed_commits: int,
    ) -> str:
        """Human-readable one-liner."""
        r = self.compute(
            writer_freshness_s,
            commit_freshness_s,
            uncommitted_files,
            unpushed_commits,
        )
        t = self.trend()
        return (
            f"pipeline {r['verdict']} (index={r['index']:.2f}, "
            f"trend={t}) — writer={r['sub_scores']['writer_freshness']:.0%} "
            f"commit={r['sub_scores']['commit_freshness']:.0%} "
            f"backlog={r['sub_scores']['backlog_ratio']:.0%} "
            f"push={r['sub_scores']['push_lag']:.0%}"
        )
