"""commit_pipeline_latency — how fast do strokes reach git?

``commit_lag`` measures gaps between *consecutive commits*.
``commit_freshness`` measures the age of files at commit time.
Neither answers the question a pipeline engineer actually asks:
**how many seconds elapsed between a stroke being written to disk
and that stroke appearing in a committed tree?**

This module fills the gap.  It takes two already-parsed sequences —
stroke timestamps and commit timestamps — and pairs them into a
latency distribution.  The design is intentionally pure-Python and
side-effect-free so that caretakers and dashboards can call it without
spawning subprocesses or touching the filesystem.

Data model
----------

A **stroke event** is ``(at: float,)`` where *at* is a Unix epoch.
A **commit event** is ``(at: float, strokes_covered: int)`` where
*strokes_covered* is how many previously-uncommitted strokes this
commit includes.

The pairing algorithm is greedy and chronological:

1. Sort both sequences ascending by *at*.
2. Walk through commits; for each commit, consume all pending strokes
   whose *at* <= the commit *at*.  The latency for each consumed stroke
   is ``commit.at − stroke.at``.
3. Strokes with no subsequent commit are returned as **orphaned**.

From the paired latencies we derive:

- ``median_latency_s`` — middle value (robust to outlier stalls)
- ``p95_latency_s``    — 95th percentile
- ``max_latency_s``    — worst case
- ``orphan_count``     — strokes not yet committed
- ``healthy``          — bool, True when p95 < threshold

Usage::

    from iamai.commit_pipeline_latency import PipelineLatency, pair

    strokes = [
        {"at": 1000.0},
        {"at": 1015.0},
        {"at": 1030.0},
        {"at": 1045.0},
    ]
    commits = [
        {"at": 1060.0, "strokes_covered": 3},  # covers first 3 strokes
        {"at": 1120.0, "strokes_covered": 1},  # covers stroke 4
    ]

    result = pair(strokes, commits)
    print(result.median_latency_s)  # 30.0
    print(result.orphan_count)      # 0
    print(result.healthy)           # True

Thresholds
----------

- **HEALTHY_P95_S**  = 900   (15 min — one batch interval)
- **WARN_P95_S**     = 1800  (30 min — two batch intervals)
- p95 above WARN → the pipeline is broken, not just slow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

HEALTHY_P95_S: float = 900.0    # 15 min
WARN_P95_S: float = 1800.0      # 30 min


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PipelineLatency:
    """Outcome of a pipeline-latency analysis."""

    latencies: list[float] = field(default_factory=list)
    orphan_count: int = 0
    stroke_count: int = 0
    commit_count: int = 0
    threshold_s: float = HEALTHY_P95_S

    # -- derived metrics --------------------------------------------------

    @property
    def median_latency_s(self) -> float:
        return _percentile(self.latencies, 50)

    @property
    def p95_latency_s(self) -> float:
        return _percentile(self.latencies, 95)

    @property
    def max_latency_s(self) -> float:
        return max(self.latencies) if self.latencies else 0.0

    @property
    def mean_latency_s(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    @property
    def healthy(self) -> bool:
        if not self.latencies:
            return False
        return self.p95_latency_s < self.threshold_s

    @property
    def verdict(self) -> str:
        """Human-readable verdict: 'healthy', 'degraded', or 'broken'."""
        if not self.latencies:
            return "no-data"
        p95 = self.p95_latency_s
        if p95 < HEALTHY_P95_S:
            return "healthy"
        if p95 < WARN_P95_S:
            return "degraded"
        return "broken"

    def summary(self) -> str:
        """One-line human-readable summary."""
        if not self.latencies:
            return (
                f"pipeline latency: no paired data "
                f"({self.stroke_count} strokes, {self.commit_count} commits, "
                f"{self.orphan_count} orphaned)"
            )
        return (
            f"pipeline {self.verdict} — "
            f"median {self.median_latency_s:.0f}s, "
            f"p95 {self.p95_latency_s:.0f}s, "
            f"max {self.max_latency_s:.0f}s "
            f"({len(self.latencies)} paired, {self.orphan_count} orphaned)"
        )


# ---------------------------------------------------------------------------
# Core pairing
# ---------------------------------------------------------------------------

def pair(
    strokes: Sequence[Dict[str, Any]],
    commits: Sequence[Dict[str, Any]],
    threshold_s: float = HEALTHY_P95_S,
) -> PipelineLatency:
    """Pair strokes with the commits that captured them.

    Parameters
    ----------
    strokes:
        Sequence of dicts, each with at least ``{"at": float}``.
    commits:
        Sequence of dicts, each with at least
        ``{"at": float, "strokes_covered": int}``.
    threshold_s:
        P95 threshold for the ``healthy`` flag.

    Returns
    -------
    PipelineLatency with paired latencies and orphan count.
    """
    if not strokes:
        return PipelineLatency(
            stroke_count=0,
            commit_count=len(commits),
            threshold_s=threshold_s,
        )

    sorted_strokes = sorted(strokes, key=lambda s: s["at"])
    sorted_commits = sorted(commits, key=lambda c: c["at"])

    latencies: list[float] = []
    stroke_idx = 0
    total_strokes = len(sorted_strokes)

    for commit in sorted_commits:
        commit_at = commit["at"]
        covered = commit.get("strokes_covered", 0)
        consumed = 0
        while stroke_idx < total_strokes and sorted_strokes[stroke_idx]["at"] <= commit_at:
            if covered > 0 and consumed >= covered:
                break
            gap = commit_at - sorted_strokes[stroke_idx]["at"]
            latencies.append(max(gap, 0.0))
            stroke_idx += 1
            consumed += 1

    orphan_count = total_strokes - stroke_idx

    return PipelineLatency(
        latencies=latencies,
        orphan_count=orphan_count,
        stroke_count=total_strokes,
        commit_count=len(sorted_commits),
        threshold_s=threshold_s,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile.  Returns 0.0 for empty input."""
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(len(s) * pct / 100.0)))
    return round(s[k], 2)


def latency_from_epochs(
    stroke_epochs: Sequence[float],
    commit_epochs: Sequence[float],
    strokes_per_commit: int = 4,
    threshold_s: float = HEALTHY_P95_S,
) -> PipelineLatency:
    """Convenience wrapper when you only have epoch floats.

    Builds the stroke/commit dicts with a uniform ``strokes_per_commit``
    assumption.  Useful for quick caretaker dashboards.

    Parameters
    ----------
    stroke_epochs:
        Unix timestamps of individual strokes.
    commit_epochs:
        Unix timestamps of commits.
    strokes_per_commit:
        How many strokes each commit covers (uniform assumption).
    threshold_s:
        P95 threshold for healthy flag.
    """
    strokes = [{"at": t} for t in stroke_epochs]
    commits = [{"at": t, "strokes_covered": strokes_per_commit} for t in commit_epochs]
    return pair(strokes, commits, threshold_s=threshold_s)
