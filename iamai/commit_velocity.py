"""commit_velocity — measure acceleration and deceleration of commit activity.

While cadence modules (``cadence_drift``, ``cadence_jitter``, ``cadence_adherence``)
track *regularity* — how evenly spaced commits are — they do not capture
*momentum*: whether the project is speeding up or slowing down.  A repo can
have perfect cadence at 1 commit/hour yet be decelerating if the gap between
batches is widening.  This module fills that gap.

Algorithm
---------
1. Accept a list of commit timestamps (ISO-8601 or epoch seconds).
2. Compute inter-commit gaps in seconds.
3. Fit a simple linear regression over ``(index, gap)`` to estimate the
   trend: negative slope = accelerating, positive slope = decelerating.
4. Compute a short-window (last 20%) and long-window (full history) average
   gap to derive a ``velocity_ratio`` (long / short).  Values > 1 indicate
   recent acceleration; < 1 indicate deceleration.
5. Classify the project state:

===========================  ==============================================
velocity_ratio               label
===========================  ==============================================
>= 1.5                       **accelerating** — recent pace notably faster
1.0 – 1.5                    **steady** — pace roughly constant
0.67 – 1.0                   **slowing** — mild deceleration
< 0.67                       **stalling** — significant slowdown
===========================  ==============================================

6. Optionally compute a ``burstiness`` score: the coefficient of variation
   (σ/μ) of inter-commit gaps.  High burstiness (> 1.0) indicates
   irregular commit patterns (long silences punctuated by rapid bursts).

Interpretation
--------------
- ``velocity_ratio`` is the primary signal.  It answers "are we going faster
  or slower than before?"
- ``slope_seconds_per_commit`` gives the raw trend in seconds-per-commit
  change.  A slope of -5 means each successive commit is ~5 s faster.
- ``burstiness > 1.5`` suggests the commit process is unstable even if the
  velocity ratio looks healthy — the *variance* is the risk.

Edge cases
----------
* Fewer than 2 commits → zeroed report (no gaps to analyse).
* All identical timestamps → zero gaps → classified as ``stalling``
  (degenerate case).
* Single gap (2 commits) → regression is trivially zero; velocity ratio
  is 1.0 (``steady``).

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 723, 2026-11-19.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Union


@dataclass
class VelocityReport:
    """Result of commit velocity analysis."""

    n_commits: int
    n_gaps: int
    mean_gap_seconds: float
    short_window_mean_seconds: float
    long_window_mean_seconds: float
    velocity_ratio: float
    slope_seconds_per_commit: float
    burstiness: float
    classification: str  # accelerating | steady | slowing | stalling

    def to_dict(self) -> dict:
        return {
            "n_commits": self.n_commits,
            "n_gaps": self.n_gaps,
            "mean_gap_seconds": round(self.mean_gap_seconds, 2),
            "short_window_mean_seconds": round(self.short_window_mean_seconds, 2),
            "long_window_mean_seconds": round(self.long_window_mean_seconds, 2),
            "velocity_ratio": round(self.velocity_ratio, 4),
            "slope_seconds_per_commit": round(self.slope_seconds_per_commit, 4),
            "burstiness": round(self.burstiness, 4),
            "classification": self.classification,
        }


def _zero_report(n_commits: int) -> VelocityReport:
    """Return a zeroed-out report for degenerate inputs."""
    return VelocityReport(
        n_commits=n_commits,
        n_gaps=0,
        mean_gap_seconds=0.0,
        short_window_mean_seconds=0.0,
        long_window_mean_seconds=0.0,
        velocity_ratio=1.0,
        slope_seconds_per_commit=0.0,
        burstiness=0.0,
        classification="steady",
    )


def _to_epoch(ts: Union[str, int, float, datetime]) -> float:
    """Convert a timestamp to epoch seconds."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.timestamp()
    if isinstance(ts, str):
        # Support ISO-8601 with or without timezone
        s = ts.strip()
        # Handle Z suffix
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise ValueError(f"Cannot parse timestamp: {ts!r}")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    raise TypeError(f"Unsupported timestamp type: {type(ts)}")


def _linear_slope(values: Sequence[float]) -> float:
    """Compute the slope of a simple linear regression over (index, value).

    Uses the standard formula: slope = (n·Σxy - Σx·Σy) / (n·Σx² - (Σx)²)
    Returns 0.0 for fewer than 2 points.
    """
    n = len(values)
    if n < 2:
        return 0.0
    sum_x = n * (n - 1) / 2.0  # Σi for i in 0..n-1
    sum_x2 = n * (n - 1) * (2 * n - 1) / 6.0  # Σi²
    sum_y = sum(values)
    sum_xy = sum(i * v for i, v in enumerate(values))
    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return 0.0
    return (n * sum_xy - sum_x * sum_y) / denom


def _classify(velocity_ratio: float) -> str:
    """Classify velocity ratio into a human-readable label."""
    if velocity_ratio >= 1.5:
        return "accelerating"
    if velocity_ratio >= 1.0:
        return "steady"
    if velocity_ratio >= 0.67:
        return "slowing"
    return "stalling"


def analyse_velocity(
    timestamps: Sequence[Union[str, int, float, datetime]],
    short_fraction: float = 0.20,
) -> VelocityReport:
    """Analyse commit velocity from a sequence of timestamps.

    Parameters
    ----------
    timestamps : sequence of ISO-8601 strings, epoch seconds, or datetimes
        Must be in chronological order (oldest first).
    short_fraction : float
        Fraction of recent gaps to use as the "short window" for velocity
        ratio computation.  Default 0.20 (last 20%).

    Returns
    -------
    VelocityReport with trend, ratio, burstiness, and classification.
    """
    n = len(timestamps)
    if n < 2:
        return _zero_report(n)

    epochs = sorted(_to_epoch(t) for t in timestamps)
    gaps = [epochs[i + 1] - epochs[i] for i in range(n - 1)]
    n_gaps = len(gaps)

    mean_gap = statistics.mean(gaps)

    # Handle degenerate case: all identical timestamps
    if mean_gap == 0:
        return VelocityReport(
            n_commits=n,
            n_gaps=n_gaps,
            mean_gap_seconds=0.0,
            short_window_mean_seconds=0.0,
            long_window_mean_seconds=0.0,
            velocity_ratio=0.0,
            slope_seconds_per_commit=0.0,
            burstiness=0.0,
            classification="stalling",
        )

    # Short window: last ceil(short_fraction * n_gaps) gaps, minimum 1
    short_n = max(1, math.ceil(short_fraction * n_gaps))
    short_gaps = gaps[-short_n:]
    short_mean = statistics.mean(short_gaps)

    # Long window: all gaps
    long_mean = mean_gap

    # Velocity ratio: long / short (higher = recent is faster)
    if short_mean == 0:
        velocity_ratio = float("inf") if long_mean > 0 else 1.0
    else:
        velocity_ratio = long_mean / short_mean

    # Slope of gap trend
    slope = _linear_slope(gaps)

    # Burstiness: coefficient of variation
    if n_gaps >= 2:
        stdev = statistics.stdev(gaps)
        burstiness = stdev / mean_gap if mean_gap > 0 else 0.0
    else:
        burstiness = 0.0

    return VelocityReport(
        n_commits=n,
        n_gaps=n_gaps,
        mean_gap_seconds=mean_gap,
        short_window_mean_seconds=short_mean,
        long_window_mean_seconds=long_mean,
        velocity_ratio=velocity_ratio,
        slope_seconds_per_commit=slope,
        burstiness=burstiness,
        classification=_classify(velocity_ratio),
    )


def analyse_velocity_windows(
    timestamps: Sequence[Union[str, int, float, datetime]],
    window_sizes: Optional[Sequence[int]] = None,
    short_fraction: float = 0.20,
) -> List[VelocityReport]:
    """Analyse velocity across multiple trailing windows.

    Useful for seeing how the velocity picture changes depending on how much
    history you look at.  For example, ``window_sizes=[50, 100, 200]``
    gives three reports covering increasing amounts of commit history.

    Parameters
    ----------
    timestamps : sequence of timestamps (chronological order)
    window_sizes : list of ints, optional
        Number of most-recent commits per window.  Defaults to
        ``[20, 50, 100]``.
    short_fraction : float
        Passed through to ``analyse_velocity``.

    Returns
    -------
    List of VelocityReport, one per window size (in the same order).
    """
    if window_sizes is None:
        window_sizes = [20, 50, 100]

    sorted_ts = sorted(timestamps, key=_to_epoch)
    reports = []
    for w in window_sizes:
        subset = sorted_ts[-w:] if len(sorted_ts) > w else sorted_ts
        reports.append(analyse_velocity(subset, short_fraction=short_fraction))
    return reports
