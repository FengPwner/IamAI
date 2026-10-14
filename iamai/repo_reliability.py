"""repo_reliability — measure uptime patterns from commit timestamps.

Given a sequence of commit timestamps (epoch seconds, oldest first),
identify *silence periods* where the gap between consecutive commits
exceeds a configurable threshold, and compute reliability statistics:

- total silences
- mean / max silence duration
- mean time between silences (MTBS)
- trend: are silences getting longer or shorter?

Usage from CLI (reads git log directly):

    python3 -m iamai.repo_reliability
    python3 -m iamai.repo_reliability --threshold 1800 --json

Exit codes:
    0  healthy — no silences or trend is improving
    1  degraded — silences are getting longer
    2  insufficient data — fewer than 2 commits
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class SilencePeriod:
    """A single silence: the gap between two consecutive commits."""

    before: float  # timestamp of the last commit before the gap
    after: float  # timestamp of the first commit after the gap
    duration: float  # seconds of silence

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ReliabilityReport:
    """Summary statistics for a sequence of commits."""

    total_commits: int
    total_silences: int
    mean_silence: float  # seconds
    max_silence: float  # seconds
    mtbs: float | None  # mean time between silences (seconds)
    trend: str  # "improving", "degrading", "stable", "insufficient"
    silences: list[SilencePeriod] = field(default_factory=list)
    healthy: bool = True
    message: str = ""

    def as_dict(self) -> dict:
        d = {
            "total_commits": self.total_commits,
            "total_silences": self.total_silences,
            "mean_silence": round(self.mean_silence, 1),
            "max_silence": round(self.max_silence, 1),
            "mtbs": round(self.mtbs, 1) if self.mtbs is not None else None,
            "trend": self.trend,
            "healthy": self.healthy,
            "message": self.message,
            "silence_count": len(self.silences),
        }
        return d


def find_silences(
    timestamps: list[float], threshold: float = 3600.0
) -> list[SilencePeriod]:
    """Return all gaps >= threshold seconds between consecutive commits.

    *timestamps* must be sorted ascending (oldest first).
    """
    if len(timestamps) < 2:
        return []

    silences: list[SilencePeriod] = []
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        if gap >= threshold:
            silences.append(
                SilencePeriod(
                    before=timestamps[i - 1],
                    after=timestamps[i],
                    duration=gap,
                )
            )
    return silences


def compute_trend(silences: list[SilencePeriod]) -> str:
    """Classify the trend of silence durations.

    Compares the mean of the first half vs the second half.
    Returns one of: "improving", "degrading", "stable", "insufficient".
    """
    if len(silences) < 4:
        return "insufficient"

    mid = len(silences) // 2
    first_half = statistics.mean(s.duration for s in silences[:mid])
    second_half = statistics.mean(s.duration for s in silences[mid:])

    if second_half < first_half * 0.8:
        return "improving"
    elif second_half > first_half * 1.2:
        return "degrading"
    return "stable"


def analyze(
    timestamps: list[float], threshold: float = 3600.0
) -> ReliabilityReport:
    """Compute a full reliability report from commit timestamps.

    *timestamps*: epoch seconds, sorted ascending.
    *threshold*: seconds — gaps at or above this count as silences.
    """
    if len(timestamps) < 2:
        return ReliabilityReport(
            total_commits=len(timestamps),
            total_silences=0,
            mean_silence=0.0,
            max_silence=0.0,
            mtbs=None,
            trend="insufficient",
            healthy=False,
            message="insufficient data — need at least 2 commits",
        )

    silences = find_silences(timestamps, threshold=threshold)

    if not silences:
        span = timestamps[-1] - timestamps[0]
        return ReliabilityReport(
            total_commits=len(timestamps),
            total_silences=0,
            mean_silence=0.0,
            max_silence=0.0,
            mtbs=None,
            trend="stable",
            silences=[],
            healthy=True,
            message=f"no silences >= {threshold:.0f}s across {span:.0f}s span",
        )

    durations = [s.duration for s in silences]
    mean_silence = statistics.mean(durations)
    max_silence = max(durations)
    trend = compute_trend(silences)

    # Mean time between silences: span from first silence to last, / (count-1)
    mtbs: float | None = None
    if len(silences) >= 2:
        span = silences[-1].before - silences[0].before
        mtbs = span / (len(silences) - 1) if span > 0 else None

    healthy = trend in ("improving", "stable", "insufficient")
    message = (
        f"{len(silences)} silences, mean {mean_silence:.0f}s, "
        f"max {max_silence:.0f}s, trend: {trend}"
    )

    return ReliabilityReport(
        total_commits=len(timestamps),
        total_silences=len(silences),
        mean_silence=mean_silence,
        max_silence=max_silence,
        mtbs=mtbs,
        trend=trend,
        silences=silences,
        healthy=healthy,
        message=message,
    )


def format_text(report: ReliabilityReport) -> str:
    """One-line human summary."""
    if report.total_commits < 2:
        return "insufficient data"
    if report.total_silences == 0:
        return f"clean — {report.total_commits} commits, no silences"
    mtbs_str = f"{report.mtbs:.0f}s" if report.mtbs is not None else "n/a"
    return (
        f"{report.total_silences} silences across {report.total_commits} commits "
        f"| mean {report.mean_silence:.0f}s max {report.max_silence:.0f}s "
        f"| mtbs {mtbs_str} | trend: {report.trend}"
    )
