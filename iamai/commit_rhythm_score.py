"""commit_rhythm_score — measure how regular the commit cadence is.

A healthy IamAI pipeline commits roughly every 10 minutes.  But "roughly"
hides a lot: if half the commits come in 2-minute bursts and the other
half arrive after 40-minute gaps, the *average* interval might still be
10 minutes while the rhythm is clearly broken.

This module looks at the last N commit intervals and produces a single
0–100 **rhythm score** plus a letter grade:

    ┌─────────────┬───────────────────────────────────────────┐
    │ Score       │ Meaning                                   │
    ├─────────────┼───────────────────────────────────────────┤
    │  90–100     │ Rock-solid cadence, minor jitter only     │
    │  70–89      │ Acceptable, occasional gaps or bursts     │
    │  50–69      │ Irregular, visible clustering or stalls   │
    │  30–49      │ Unreliable cadence, frequent disruptions  │
    │   0–29      │ No discernible rhythm                     │
    └─────────────┴───────────────────────────────────────────┘

Components
----------
The score is the geometric mean of three sub-scores:

1. **interval_score** — how close the median interval is to the target
   (default 600 s = 10 min).  Uses a ratio-based metric so both
   too-fast and too-slow cadences lose points.

2. **jitter_score** — how much the intervals vary.  Measured as the
   coefficient of variation (σ/μ), capped at 1.0.  Low jitter = high
   score.

3. **burst_penalty** — what fraction of intervals are "bursty"
   (< target / 3).  Bursts indicate the batch committer is flushing
   a backlog rather than committing on schedule.

Usage
-----
    from iamai.commit_rhythm_score import CommitRhythm

    cr = CommitRhythm(repo_path)
    report = cr.analyse(n=30)
    print(report.summary)
    # → "rhythm 78/100 (B) | median=612s jitter=0.18 bursts=2/30"

Design notes
------------
* Geometric mean (not arithmetic) because any one component collapsing
  to zero should drag the overall score toward zero regardless of how
  good the others are.
* We use the *median* interval rather than the mean for interval_score
  so a single 4-hour overnight gap doesn't warp the reading.
* Burst detection uses a hard threshold (target / 3) rather than a
  soft curve — a 2-minute interval in a 10-minute pipeline is clearly
  a flush, not a near-miss.
"""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_TARGET = 600        # seconds — 10-minute cadence
BURST_THRESHOLD = 1 / 3    # fraction of target below which an interval is "bursty"
MAX_JITTER_CV = 1.0         # coefficient of variation that maps to score 0


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------
@dataclass
class RhythmReport:
    """Snapshot of commit cadence quality."""

    target_seconds: float = DEFAULT_TARGET
    n_commits: int = 0
    n_intervals: int = 0
    median_interval: float = 0.0
    mean_interval: float = 0.0
    std_interval: float = 0.0
    jitter_cv: float = 0.0
    burst_count: int = 0

    interval_score: float = 0.0
    jitter_score: float = 0.0
    burst_score: float = 0.0
    total: float = 0.0

    @property
    def grade(self) -> str:
        if self.total >= 90:
            return "A"
        if self.total >= 70:
            return "B"
        if self.total >= 50:
            return "C"
        if self.total >= 30:
            return "D"
        return "F"

    @property
    def summary(self) -> str:
        return (
            f"rhythm {self.total:.0f}/100 ({self.grade}) | "
            f"median={self.median_interval:.0f}s "
            f"jitter={self.jitter_cv:.2f} "
            f"bursts={self.burst_count}/{self.n_intervals}"
        )


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------
def _interval_score(median: float, target: float) -> float:
    """Score 0–100 based on how close *median* is to *target*.

    Uses min(median, target) / max(median, target) so the score is
    symmetric: a 5-minute median and a 20-minute median both score 50
    against a 10-minute target.
    """
    if median <= 0 or target <= 0:
        return 0.0
    ratio = min(median, target) / max(median, target)
    return ratio * 100.0


def _jitter_score(cv: float) -> float:
    """Score 0–100 from coefficient of variation (lower is better)."""
    if cv < 0:
        return 0.0
    clamped = min(cv, MAX_JITTER_CV)
    return (1.0 - clamped) * 100.0


def _burst_score(burst_count: int, n_intervals: int) -> float:
    """Score 0–100 based on the fraction of bursty intervals."""
    if n_intervals <= 0:
        return 100.0  # no data → no bursts → no penalty
    burst_frac = burst_count / n_intervals
    return max(0.0, (1.0 - burst_frac * 2)) * 100.0


def _geometric_mean(values: List[float]) -> float:
    """Geometric mean of positive values.  Returns 0 if any value is 0."""
    if not values or any(v <= 0 for v in values):
        return 0.0
    log_sum = sum(math.log(v) for v in values)
    return math.exp(log_sum / len(values))


# ---------------------------------------------------------------------------
# Main analyser
# ---------------------------------------------------------------------------
class CommitRhythm:
    """Analyse the regularity of commit timing in a git repository."""

    def __init__(self, repo_path: str | Path | None = None,
                 target_seconds: float = DEFAULT_TARGET):
        self.repo = Path(repo_path) if repo_path else Path(__file__).resolve().parent.parent
        self.target = target_seconds

    # -- data collection ----------------------------------------------------

    def _fetch_timestamps(self, n: int) -> List[float]:
        """Return up to *n* most recent commit timestamps (epoch seconds)."""
        try:
            out = subprocess.run(
                ["git", "-C", str(self.repo), "log",
                 f"-{n + 1}", "--format=%at"],
                capture_output=True, text=True, timeout=15,
            )
            lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
            return [float(ts) for ts in lines]
        except Exception:
            return []

    def _intervals(self, timestamps: List[float]) -> List[float]:
        """Convert a descending list of timestamps to positive intervals."""
        intervals = []
        for i in range(len(timestamps) - 1):
            gap = timestamps[i] - timestamps[i + 1]
            if gap > 0:
                intervals.append(gap)
        return intervals

    # -- statistics ---------------------------------------------------------

    @staticmethod
    def _median(values: List[float]) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        mid = len(s) // 2
        if len(s) % 2 == 1:
            return s[mid]
        return (s[mid - 1] + s[mid]) / 2.0

    @staticmethod
    def _mean(values: List[float]) -> float:
        if not values:
            return 0.0
        return sum(values) / len(values)

    @staticmethod
    def _std(values: List[float], mean: float) -> float:
        if len(values) < 2:
            return 0.0
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        return math.sqrt(variance)

    # -- analysis -----------------------------------------------------------

    def analyse(self, n: int = 30) -> RhythmReport:
        """Analyse the last *n* commits and return a RhythmReport.

        Parameters
        ----------
        n : int
            Number of recent commits to examine.  The analyser fetches
            n+1 timestamps to produce n intervals (or fewer if the repo
            has fewer commits).
        """
        timestamps = self._fetch_timestamps(n)
        intervals = self._intervals(timestamps)

        if not intervals:
            return RhythmReport(target_seconds=self.target)

        median = self._median(intervals)
        mean = self._mean(intervals)
        std = self._std(intervals, mean)
        cv = std / mean if mean > 0 else 0.0

        burst_thresh = self.target * BURST_THRESHOLD
        bursts = sum(1 for iv in intervals if iv < burst_thresh)

        i_score = _interval_score(median, self.target)
        j_score = _jitter_score(cv)
        b_score = _burst_score(bursts, len(intervals))

        total = _geometric_mean([i_score, j_score, b_score])

        return RhythmReport(
            target_seconds=self.target,
            n_commits=len(timestamps),
            n_intervals=len(intervals),
            median_interval=median,
            mean_interval=mean,
            std_interval=std,
            jitter_cv=cv,
            burst_count=bursts,
            interval_score=i_score,
            jitter_score=j_score,
            burst_score=b_score,
            total=total,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse
    p = argparse.ArgumentParser(description="Commit rhythm score")
    p.add_argument("--repo", default=None, help="repo path (default: auto)")
    p.add_argument("-n", type=int, default=30, help="number of commits")
    p.add_argument("--target", type=float, default=DEFAULT_TARGET,
                   help="target interval in seconds (default 600)")
    p.add_argument("--json", action="store_true", help="output as JSON")
    args = p.parse_args()

    cr = CommitRhythm(args.repo, args.target)
    report = cr.analyse(n=args.n)

    if args.json:
        import json
        print(json.dumps({
            "total": round(report.total, 1),
            "grade": report.grade,
            "n_commits": report.n_commits,
            "n_intervals": report.n_intervals,
            "median_interval": round(report.median_interval, 1),
            "mean_interval": round(report.mean_interval, 1),
            "jitter_cv": round(report.jitter_cv, 3),
            "burst_count": report.burst_count,
            "interval_score": round(report.interval_score, 1),
            "jitter_score": round(report.jitter_score, 1),
            "burst_score": round(report.burst_score, 1),
        }))
    else:
        print(report.summary)


if __name__ == "__main__":
    main()
