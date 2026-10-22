"""commit_gap_analyzer — classify and score the timing gaps between commits.

An automated writer produces commits at roughly regular intervals
(every ``BATCH_INTERVAL`` seconds, default 600).  Deviations from this
rhythm carry diagnostic information:

=================  =====================================================
gap type           meaning
=================  =====================================================
regular            gap within the expected batch window (±tolerance)
accelerated        gap significantly shorter than expected — could
                   indicate a catch-up burst or manual intervention
stalled            gap longer than expected but the process was still
                   alive — writer was in a quiet period
dead               gap long enough that the process likely died and
                   was restarted — correlates with ``longest gap``
                   in caretaker status output
=================  =====================================================

The module produces a ``GapReport`` for each interval and an aggregate
``GapProfile`` that summarises the overall commit rhythm health.

Usage::

    from iamai.commit_gap_analyzer import analyze_gaps, GapProfile

    timestamps = load_commit_timestamps()  # list of ISO-8601 strings
    profile = analyze_gaps(timestamps)
    print(profile.health)          # "rhythmic" / "irregular" / "erratic"
    print(profile.regular_ratio)   # 0.87
    print(profile.dead_count)      # 2

All functions accept ISO-8601 timestamp strings — no file I/O in core
logic, making it trivially testable.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_BATCH_INTERVAL = 600.0       # seconds — expected commit cadence
DEFAULT_TOLERANCE = 0.30             # ±30% of batch_interval is "regular"
DEFAULT_DEAD_THRESHOLD = 1800.0     # 30 min — process likely died
DEFAULT_RECENT_COUNT = 20            # how many recent gaps to weight more


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------

@dataclass
class GapReport:
    """Analysis of a single gap between two consecutive commits."""

    gap_seconds: float
    gap_type: str           # regular | accelerated | stalled | dead
    deviation: float        # signed: negative = faster, positive = slower
    z_score: Optional[float] = None  # relative to population if available


@dataclass
class GapProfile:
    """Aggregate analysis of all commit gaps in a session or window."""

    total_gaps: int = 0
    regular_count: int = 0
    accelerated_count: int = 0
    stalled_count: int = 0
    dead_count: int = 0
    gaps: List[GapReport] = field(default_factory=list)

    # summary statistics
    mean_gap: float = 0.0
    median_gap: float = 0.0
    std_gap: float = 0.0
    min_gap: float = 0.0
    max_gap: float = 0.0

    @property
    def regular_ratio(self) -> float:
        """Fraction of gaps that are regular (healthy rhythm)."""
        if self.total_gaps == 0:
            return 0.0
        return self.regular_count / self.total_gaps

    @property
    def dead_ratio(self) -> float:
        """Fraction of gaps where the process likely died."""
        if self.total_gaps == 0:
            return 0.0
        return self.dead_count / self.total_gaps

    @property
    def health(self) -> str:
        """Overall rhythm health verdict.

        ===========  =====================================================
        verdict      meaning
        ===========  =====================================================
        rhythmic     ≥80% regular gaps, ≤1 dead gap — clockwork
        irregular    ≥50% regular gaps — acceptable but not steady
        erratic      <50% regular gaps or ≥3 dead gaps — needs attention
        ===========  =====================================================
        """
        if self.total_gaps == 0:
            return "unknown"
        rr = self.regular_ratio
        if rr >= 0.80 and self.dead_count <= 1:
            return "rhythmic"
        if rr >= 0.50 and self.dead_count < 3:
            return "irregular"
        return "erratic"

    @property
    def score(self) -> float:
        """Numeric health score in [0, 1].

        Combines regular_ratio (weight 0.6) with a penalty for dead gaps
        and a bonus for low variance.
        """
        if self.total_gaps == 0:
            return 0.0

        # base: regular ratio
        base = self.regular_ratio * 0.6

        # dead penalty: each dead gap costs 0.05, capped at 0.3
        dead_penalty = min(self.dead_count * 0.05, 0.3)

        # variance bonus: low CV (coefficient of variation) is good
        if self.mean_gap > 0 and self.std_gap > 0:
            cv = self.std_gap / self.mean_gap
            # cv of 0 → bonus 0.2, cv of 1+ → bonus 0
            var_bonus = max(0.0, 0.2 * (1.0 - cv))
        else:
            var_bonus = 0.0

        return max(0.0, min(1.0, base - dead_penalty + var_bonus))


# ---------------------------------------------------------------------------
# core functions
# ---------------------------------------------------------------------------

def _parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    # handle both with and without timezone info
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def classify_gap(
    gap_seconds: float,
    batch_interval: float = DEFAULT_BATCH_INTERVAL,
    tolerance: float = DEFAULT_TOLERANCE,
    dead_threshold: float = DEFAULT_DEAD_THRESHOLD,
) -> str:
    """Classify a single gap into one of four types.

    Parameters
    ----------
    gap_seconds : float
        Seconds between two consecutive commits.
    batch_interval : float
        Expected interval between commits (default 600s = 10 min).
    tolerance : float
        Fraction of batch_interval that counts as "regular" (default 0.30).
    dead_threshold : float
        Gaps longer than this are classified as "dead" (default 1800s).

    Returns
    -------
    str
        One of: "regular", "accelerated", "stalled", "dead".
    """
    if gap_seconds <= 0:
        return "regular"  # same-second commits are treated as regular

    if gap_seconds >= dead_threshold:
        return "dead"

    lower = batch_interval * (1.0 - tolerance)
    upper = batch_interval * (1.0 + tolerance)

    if lower <= gap_seconds <= upper:
        return "regular"
    elif gap_seconds < lower:
        return "accelerated"
    else:
        return "stalled"


def analyze_single_gap(
    gap_seconds: float,
    mean_gap: Optional[float] = None,
    std_gap: Optional[float] = None,
    batch_interval: float = DEFAULT_BATCH_INTERVAL,
    tolerance: float = DEFAULT_TOLERANCE,
    dead_threshold: float = DEFAULT_DEAD_THRESHOLD,
) -> GapReport:
    """Produce a detailed GapReport for a single gap."""
    gap_type = classify_gap(gap_seconds, batch_interval, tolerance, dead_threshold)

    # deviation: how far from expected, signed
    deviation = (gap_seconds - batch_interval) / batch_interval

    # z-score if population stats available
    z = None
    if mean_gap is not None and std_gap is not None and std_gap > 0:
        z = (gap_seconds - mean_gap) / std_gap

    return GapReport(
        gap_seconds=gap_seconds,
        gap_type=gap_type,
        deviation=deviation,
        z_score=z,
    )


def analyze_gaps(
    timestamps: Sequence[str],
    batch_interval: float = DEFAULT_BATCH_INTERVAL,
    tolerance: float = DEFAULT_TOLERANCE,
    dead_threshold: float = DEFAULT_DEAD_THRESHOLD,
    recent_count: int = DEFAULT_RECENT_COUNT,
) -> GapProfile:
    """Analyze all gaps in a sequence of commit timestamps.

    Parameters
    ----------
    timestamps : sequence of str
        ISO-8601 timestamps of commits, in chronological order.
    batch_interval : float
        Expected interval between commits.
    tolerance : float
        Fraction of batch_interval for "regular" classification.
    dead_threshold : float
        Gaps longer than this indicate process death.
    recent_count : int
        How many recent gaps to consider for recency-weighted analysis
        (currently informational; future use for trend detection).

    Returns
    -------
    GapProfile
        Aggregate analysis with per-gap details.
    """
    if len(timestamps) < 2:
        return GapProfile()

    parsed = sorted(_parse_ts(ts) for ts in timestamps)
    raw_gaps = [
        (parsed[i + 1] - parsed[i]).total_seconds()
        for i in range(len(parsed) - 1)
    ]

    # population statistics for z-scores
    mean_g = statistics.mean(raw_gaps) if raw_gaps else 0.0
    std_g = statistics.stdev(raw_gaps) if len(raw_gaps) > 1 else 0.0

    profile = GapProfile(total_gaps=len(raw_gaps))
    profile.mean_gap = mean_g
    profile.median_gap = statistics.median(raw_gaps) if raw_gaps else 0.0
    profile.std_gap = std_g
    profile.min_gap = min(raw_gaps) if raw_gaps else 0.0
    profile.max_gap = max(raw_gaps) if raw_gaps else 0.0

    for gap_s in raw_gaps:
        report = analyze_single_gap(
            gap_s,
            mean_gap=mean_g,
            std_gap=std_g,
            batch_interval=batch_interval,
            tolerance=tolerance,
            dead_threshold=dead_threshold,
        )
        profile.gaps.append(report)

        if report.gap_type == "regular":
            profile.regular_count += 1
        elif report.gap_type == "accelerated":
            profile.accelerated_count += 1
        elif report.gap_type == "stalled":
            profile.stalled_count += 1
        elif report.gap_type == "dead":
            profile.dead_count += 1

    return profile


def recent_trend(
    profile: GapProfile,
    recent_count: int = DEFAULT_RECENT_COUNT,
) -> str:
    """Assess whether recent gaps are improving or deteriorating.

    Returns
    -------
    str
        One of: "improving", "stable", "deteriorating", "insufficient_data".
    """
    if len(profile.gaps) < recent_count + 2:
        return "insufficient_data"

    recent = profile.gaps[-recent_count:]
    earlier = profile.gaps[-(recent_count * 2):-recent_count]

    if not earlier:
        return "insufficient_data"

    recent_regular = sum(1 for g in recent if g.gap_type == "regular")
    earlier_regular = sum(1 for g in earlier if g.gap_type == "regular")

    recent_ratio = recent_regular / len(recent)
    earlier_ratio = earlier_regular / len(earlier)

    delta = recent_ratio - earlier_ratio
    if delta > 0.10:
        return "improving"
    elif delta < -0.10:
        return "deteriorating"
    return "stable"


def gap_summary_text(profile: GapProfile) -> str:
    """Produce a human-readable one-liner for caretaker status output."""
    h = profile.health
    s = profile.score
    rr = profile.regular_ratio
    parts = [
        f"commit rhythm: {h} (score {s:.2f})",
        f"{profile.regular_count}/{profile.total_gaps} regular",
    ]
    if profile.dead_count > 0:
        parts.append(f"{profile.dead_count} dead gaps")
    if profile.accelerated_count > 0:
        parts.append(f"{profile.accelerated_count} accelerated")
    return ", ".join(parts)
