"""Detect commit bursts — rapid-fire commits that signal panic or flow.

A *burst* is a cluster of commits where consecutive gaps fall below a
configurable threshold. Bursts matter for two opposite reasons:

1. **Productive flow** — the writer is in a groove, producing varied
   content at high speed. Celebrate it.
2. **Panic loop** — the writer is stuck retrying the same thing,
   generating near-identical commits. Investigate it.

This module answers three questions:

- Is there a burst *right now*? (last N commits)
- How many bursts happened in the last T hours?
- Are recent bursts getting longer or shorter?

Model
-----
Given a list of commit gaps (seconds between consecutive commits),
a burst is a maximal run of gaps ≤ ``burst_threshold``. Each burst
has:

- ``length`` — number of commits in the burst
- ``duration`` — total time span (sum of gaps)
- ``mean_gap`` — average gap within the burst

A *burst rate* is bursts per hour over the observation window.

Verdicts:

=============  ====================================================
verdict        meaning
=============  ====================================================
``quiet``      zero bursts in the window
``steady``     1–2 bursts, short and healthy
``surging``    3+ bursts or a burst longer than ``long_burst``
``panic``      any burst with mean gap < 5 s (likely retry loop)
=============  ====================================================

Usage::

    from iamai.commit_burst_detector import detect_bursts, burst_verdict

    gaps = [12, 8, 3, 2, 45, 60, 7, 4, 3]  # seconds between commits
    bursts = detect_bursts(gaps, burst_threshold=15)
    print(burst_verdict(bursts))  # e.g. "surging"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


DEFAULT_BURST_THRESHOLD = 30  # seconds
DEFAULT_LONG_BURST = 5  # commits
DEFAULT_PANIC_MEAN_GAP = 5.0  # seconds


@dataclass(frozen=True)
class Burst:
    """A maximal run of rapid commits."""

    start_index: int
    gaps: tuple[float, ...]

    @property
    def length(self) -> int:
        """Number of commits in this burst (gaps + 1)."""
        return len(self.gaps) + 1

    @property
    def duration(self) -> float:
        """Total time span of this burst in seconds."""
        return sum(self.gaps)

    @property
    def mean_gap(self) -> float:
        """Average gap between commits in this burst."""
        if not self.gaps:
            return 0.0
        return self.duration / len(self.gaps)


def detect_bursts(
    gaps: Sequence[float],
    burst_threshold: float = DEFAULT_BURST_THRESHOLD,
) -> list[Burst]:
    """Find all maximal runs of gaps ≤ threshold.

    Parameters
    ----------
    gaps : sequence of float
        Seconds between consecutive commits (oldest first).
    burst_threshold : float
        A gap ≤ this value counts as "rapid".

    Returns
    -------
    list[Burst]
        Zero or more bursts found in the gap sequence.
    """
    if not gaps:
        return []

    bursts: list[Burst] = []
    run_start: int | None = None
    run_gaps: list[float] = []

    for i, gap in enumerate(gaps):
        if gap <= burst_threshold:
            if run_start is None:
                run_start = i
                run_gaps = [gap]
            else:
                run_gaps.append(gap)
        else:
            if run_start is not None and len(run_gaps) >= 2:
                bursts.append(Burst(start_index=run_start, gaps=tuple(run_gaps)))
            run_start = None
            run_gaps = []

    # Flush any trailing run
    if run_start is not None and len(run_gaps) >= 2:
        bursts.append(Burst(start_index=run_start, gaps=tuple(run_gaps)))

    return bursts


def burst_verdict(
    bursts: Sequence[Burst],
    long_burst: int = DEFAULT_LONG_BURST,
    panic_mean_gap: float = DEFAULT_PANIC_MEAN_GAP,
) -> str:
    """Classify the burst pattern into a human-readable verdict.

    Parameters
    ----------
    bursts : sequence of Burst
        Output of ``detect_bursts``.
    long_burst : int
        A burst with length ≥ this triggers "surging".
    panic_mean_gap : float
        A burst with mean gap below this triggers "panic".

    Returns
    -------
    str
        One of: "quiet", "steady", "surging", "panic".
    """
    if not bursts:
        return "quiet"

    # Panic takes priority — any burst with tiny mean gap
    for b in bursts:
        if b.mean_gap < panic_mean_gap:
            return "panic"

    # Surging: many bursts or one long one
    if len(bursts) >= 3:
        return "surging"
    if any(b.length >= long_burst for b in bursts):
        return "surging"

    return "steady"


def burst_summary(
    gaps: Sequence[float],
    burst_threshold: float = DEFAULT_BURST_THRESHOLD,
) -> dict:
    """One-call convenience: detect bursts and return a summary dict.

    Returns
    -------
    dict with keys:
        - bursts: list of Burst objects
        - count: number of bursts found
        - verdict: burst_verdict string
        - longest: length of the longest burst (0 if none)
        - total_burst_commits: sum of all burst lengths
    """
    bursts = detect_bursts(gaps, burst_threshold)
    verdict = burst_verdict(bursts)
    return {
        "bursts": bursts,
        "count": len(bursts),
        "verdict": verdict,
        "longest": max((b.length for b in bursts), default=0),
        "total_burst_commits": sum(b.length for b in bursts),
    }
