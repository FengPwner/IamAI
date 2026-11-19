"""commit_recovery_time — measure how quickly commit cadence recovers after disruptions.

While ``commit_velocity`` captures momentum and ``cadence_drift`` /
``cadence_jitter`` measure regularity, neither answers the question: *after
a disruption (long stall or burst), how fast does the commit stream return
to its normal rhythm?*

A project that bounces back within 2–3 commits is **resilient**; one that
takes 10+ commits (or never stabilises) is **fragile**.  This metric is
especially relevant for auto-writing repos where caretaker visits inject
bursts of activity followed by quiet periods.

Algorithm
---------
1. Accept a list of commit timestamps (ISO-8601, epoch, or datetime).
2. Compute inter-commit gaps.
3. Estimate the *target cadence* as the median gap (robust to outliers),
   or accept an explicit ``target_seconds`` parameter.
4. Detect **disruptions**: any gap exceeding ``disruption_multiplier ×
   target_cadence`` (default 3×).  Each such gap is a disruption event.
5. For each disruption, measure **recovery time** as the number of
   consecutive subsequent gaps that fall within ``[target/2, target×2]``
   before the stream is considered "recovered".  A gap outside this band
   resets the counter.  If recovery is not achieved within
   ``max_recovery_window`` commits (default 20), the disruption is marked
   as *never recovered*.
6. Aggregate into a ``RecoveryReport``:

   - ``mean_recovery_commits`` — average commits to recover
   - ``median_recovery_commits`` — median (more robust)
   - ``max_recovery_commits`` — worst case
   - ``resilience_score`` — fraction of disruptions recovering within
     ``resilience_threshold`` commits (default 5)
   - ``never_recovered`` — count of disruptions that did not recover
   - ``classification``:

     ======================  ===========================================
     resilience_score        label
     ======================  ===========================================
     ≥ 0.80                  **resilient** — quick bounce-back
     0.50 – 0.80             **moderate** — usually recovers
     0.25 – 0.50             **fragile** — slow recovery
     < 0.25                  **brittle** — often fails to recover
     ======================  ===========================================

Edge cases
----------
* Fewer than 3 commits → zeroed report.
* No disruptions detected → report with ``disruption_count = 0``,
  classification ``resilient`` (nothing to recover from).
* All gaps identical → no disruptions, resilient.

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 724, 2026-11-19.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple, Union


@dataclass
class DisruptionEvent:
    """A single disruption and its recovery outcome."""

    index: int  # index in the gaps list where the disruption occurred
    gap_seconds: float
    recovery_commits: Optional[int]  # None if never recovered
    recovered: bool

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "gap_seconds": round(self.gap_seconds, 2),
            "recovery_commits": self.recovery_commits,
            "recovered": self.recovered,
        }


@dataclass
class RecoveryReport:
    """Aggregated recovery analysis."""

    n_commits: int
    n_gaps: int
    target_cadence_seconds: float
    disruption_count: int
    disruptions: List[DisruptionEvent] = field(default_factory=list)
    mean_recovery_commits: float = 0.0
    median_recovery_commits: float = 0.0
    max_recovery_commits: int = 0
    resilience_score: float = 1.0
    never_recovered: int = 0
    classification: str = "resilient"

    def to_dict(self) -> dict:
        return {
            "n_commits": self.n_commits,
            "n_gaps": self.n_gaps,
            "target_cadence_seconds": round(self.target_cadence_seconds, 2),
            "disruption_count": self.disruption_count,
            "mean_recovery_commits": round(self.mean_recovery_commits, 2),
            "median_recovery_commits": round(self.median_recovery_commits, 2),
            "max_recovery_commits": self.max_recovery_commits,
            "resilience_score": round(self.resilience_score, 4),
            "never_recovered": self.never_recovered,
            "classification": self.classification,
            "disruptions": [d.to_dict() for d in self.disruptions],
        }


def _zero_report(n_commits: int, target: float = 0.0) -> RecoveryReport:
    """Return a zeroed report for degenerate inputs."""
    return RecoveryReport(
        n_commits=n_commits,
        n_gaps=0,
        target_cadence_seconds=target,
        disruption_count=0,
        classification="resilient",
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
        s = ts.strip()
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


def _classify(resilience_score: float) -> str:
    """Map resilience score to a human-readable label."""
    if resilience_score >= 0.80:
        return "resilient"
    if resilience_score >= 0.50:
        return "moderate"
    if resilience_score >= 0.25:
        return "fragile"
    return "brittle"


def _measure_recovery(
    gaps: Sequence[float],
    disruption_index: int,
    target: float,
    max_window: int,
) -> Tuple[Optional[int], bool]:
    """Measure how many commits it takes to recover from a disruption.

    Starting from ``disruption_index + 1``, count consecutive gaps within
    ``[target/2, target×2]``.  A gap outside this band resets the counter.
    Recovery is achieved when we accumulate ``recovery_target`` consecutive
    normal gaps (default: 3 in a row).

    Returns (recovery_commits, recovered).
    """
    recovery_target = 3  # need 3 consecutive normal gaps to confirm recovery
    low = target / 2.0
    high = target * 2.0
    consecutive_normal = 0
    commits_checked = 0

    for i in range(disruption_index + 1, min(disruption_index + 1 + max_window, len(gaps))):
        commits_checked += 1
        if low <= gaps[i] <= high:
            consecutive_normal += 1
            if consecutive_normal >= recovery_target:
                return commits_checked, True
        else:
            consecutive_normal = 0  # reset — another anomaly

    return None, False


def analyse_recovery(
    timestamps: Sequence[Union[str, int, float, datetime]],
    target_seconds: Optional[float] = None,
    disruption_multiplier: float = 3.0,
    max_recovery_window: int = 20,
    resilience_threshold: int = 5,
) -> RecoveryReport:
    """Analyse how quickly a commit stream recovers from disruptions.

    Parameters
    ----------
    timestamps : sequence of timestamps (chronological order)
    target_seconds : float, optional
        Expected cadence in seconds.  If None, uses the median gap.
    disruption_multiplier : float
        A gap exceeding ``multiplier × target`` is a disruption.
    max_recovery_window : int
        Maximum commits to observe for recovery before giving up.
    resilience_threshold : int
        Disruptions recovering within this many commits count toward the
        resilience score.

    Returns
    -------
    RecoveryReport with disruption details and aggregate stats.
    """
    n = len(timestamps)
    if n < 3:
        target = target_seconds if target_seconds is not None else 0.0
        return _zero_report(n, target)

    epochs = sorted(_to_epoch(t) for t in timestamps)
    gaps = [epochs[i + 1] - epochs[i] for i in range(n - 1)]
    n_gaps = len(gaps)

    # Determine target cadence
    if target_seconds is not None:
        target = target_seconds
    else:
        target = statistics.median(gaps)

    if target <= 0:
        return _zero_report(n, target)

    # Detect disruptions
    threshold = disruption_multiplier * target
    disruptions: List[DisruptionEvent] = []

    for i, gap in enumerate(gaps):
        if gap > threshold:
            recovery_commits, recovered = _measure_recovery(
                gaps, i, target, max_recovery_window
            )
            disruptions.append(
                DisruptionEvent(
                    index=i,
                    gap_seconds=gap,
                    recovery_commits=recovery_commits,
                    recovered=recovered,
                )
            )

    if not disruptions:
        return RecoveryReport(
            n_commits=n,
            n_gaps=n_gaps,
            target_cadence_seconds=target,
            disruption_count=0,
            resilience_score=1.0,
            never_recovered=0,
            classification="resilient",
        )

    # Aggregate recovery stats
    recovered_commits = [
        d.recovery_commits for d in disruptions if d.recovered and d.recovery_commits is not None
    ]
    never_recovered = sum(1 for d in disruptions if not d.recovered)

    if recovered_commits:
        mean_rec = statistics.mean(recovered_commits)
        median_rec = statistics.median(recovered_commits)
        max_rec = max(recovered_commits)
    else:
        mean_rec = 0.0
        median_rec = 0.0
        max_rec = 0

    # Resilience: fraction recovering within threshold
    fast_recoveries = sum(
        1 for d in disruptions
        if d.recovered and d.recovery_commits is not None and d.recovery_commits <= resilience_threshold
    )
    resilience = fast_recoveries / len(disruptions)

    return RecoveryReport(
        n_commits=n,
        n_gaps=n_gaps,
        target_cadence_seconds=target,
        disruption_count=len(disruptions),
        disruptions=disruptions,
        mean_recovery_commits=mean_rec,
        median_recovery_commits=median_rec,
        max_recovery_commits=max_rec,
        resilience_score=resilience,
        never_recovered=never_recovered,
        classification=_classify(resilience),
    )


def analyse_recovery_by_severity(
    timestamps: Sequence[Union[str, int, float, datetime]],
    target_seconds: Optional[float] = None,
    severity_levels: Optional[Sequence[float]] = None,
    max_recovery_window: int = 20,
    resilience_threshold: int = 5,
) -> dict:
    """Analyse recovery grouped by disruption severity.

    Useful for understanding whether *larger* disruptions take longer to
    recover from.

    Parameters
    ----------
    timestamps : sequence of timestamps
    target_seconds : optional explicit cadence
    severity_levels : list of multipliers defining severity bands.
        Defaults to ``[3.0, 5.0, 10.0]`` giving three bands:
        mild (3–5×), moderate (5–10×), severe (>10×).
    max_recovery_window : passed through to ``analyse_recovery``
    resilience_threshold : passed through to ``analyse_recovery``

    Returns
    -------
    dict mapping severity label to RecoveryReport.
    """
    if severity_levels is None:
        severity_levels = [3.0, 5.0, 10.0]

    n = len(timestamps)
    if n < 3:
        return {}

    epochs = sorted(_to_epoch(t) for t in timestamps)
    gaps = [epochs[i + 1] - epochs[i] for i in range(n - 1)]

    if target_seconds is not None:
        target = target_seconds
    else:
        target = statistics.median(gaps) if gaps else 0.0

    if target <= 0:
        return {}

    levels = sorted(severity_levels)
    results = {}

    # Build severity bands
    bands = []
    for i, level in enumerate(levels):
        low = level * target
        high = levels[i + 1] * target if i + 1 < len(levels) else float("inf")
        label = (
            f"mild_{level}x"
            if i == 0
            else f"moderate_{level}x" if i == 1 else f"severe_{level}x"
        )
        bands.append((low, high, label))

    for low, high, label in bands:
        # Filter timestamps to only include disruptions in this band
        # We reconstruct a mini-timeline for each band
        filtered_indices = [i for i, g in enumerate(gaps) if low < g <= high]
        if not filtered_indices:
            continue

        # For each band, run analyse_recovery with the band's low threshold as multiplier
        band_multiplier = low / target + 0.001  # just above the low bound
        band_report = analyse_recovery(
            timestamps,
            target_seconds=target,
            disruption_multiplier=band_multiplier,
            max_recovery_window=max_recovery_window,
            resilience_threshold=resilience_threshold,
        )
        results[label] = band_report

    return results
