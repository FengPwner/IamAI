"""commit_storm_detector — detect bursts of rapid commits that signal instability.

A "commit storm" is when an agent produces many commits in a short window.
This often means:

- the writer loop is spinning without real work between commits
- a retry loop is generating duplicate commits
- the batch collector fired multiple times for overlapping windows
- the agent is in a panic-push cycle trying to catch up after a stall

The detector examines a list of commit timestamps and classifies each
commit as either *calm* or *storm*, then produces a summary score.

Public API::

    from iamai.commit_storm_detector import CommitStormDetector, storm_report

    csd = CommitStormDetector(
        commit_times=[t0, t1, t2, ...],  # ascending unix timestamps
        window_s=300,                      # sliding window in seconds
        threshold=5,                       # commits per window = storm
    )
    s = csd.summary()
    # {"total_commits": 120, "storm_commits": 8, "storm_ratio": 0.067,
    #  "max_burst": 7, "max_burst_duration_s": 42.0, "verdict": "calm"}

    print(storm_report(commit_times, window_s=300, threshold=5))
    # "120 commits, 8 storm (6.7%), max burst 7 in 42s — calm"

Storm detection model
---------------------

For each commit at time *t*, count how many other commits fall within
[t - window_s, t].  If the count meets or exceeds *threshold*, that
commit is marked as part of a storm.  Contiguous storm commits form
a single burst; the burst duration is last_timestamp - first_timestamp.

==================  ========================================================
storm_ratio         fraction of commits in storms
verdict             overall assessment
==================  ========================================================
< 0.05              calm — normal cadence
< 0.15              breezy — minor clustering, nothing actionable
< 0.30              gusty — noticeable clustering, worth investigating
< 0.50              stormy — significant instability pattern
≥ 0.50              tempest — the agent is mostly in panic-push mode
==================  ========================================================

Why this matters
----------------

A healthy commit stream looks like evenly spaced dots on a timeline.
Storms show up as tight clusters.  Detecting them early lets the
caretaker intervene (slow down the writer, clear a stuck queue)
before the repo history fills with noise commits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence


# ---------------------------------------------------------------------------
# Verdict thresholds
# ---------------------------------------------------------------------------

_VERDICT_TABLE = [
    (0.05, "calm"),
    (0.15, "breezy"),
    (0.30, "gusty"),
    (0.50, "stormy"),
]

_VERDICT_WORST = "tempest"


def _classify(storm_ratio: float) -> str:
    for ceiling, label in _VERDICT_TABLE:
        if storm_ratio < ceiling:
            return label
    return _VERDICT_WORST


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


@dataclass
class CommitStormDetector:
    """Analyse a sequence of commit timestamps for storm patterns."""

    commit_times: List[float]
    window_s: float = 300.0
    threshold: int = 5

    # internal caches
    _storm_flags: list = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self.commit_times = sorted(self.commit_times)
        self._storm_flags = self._detect()

    # -- detection ----------------------------------------------------------

    def _detect(self) -> list:
        """Return a boolean list: True if that commit is in a storm."""
        n = len(self.commit_times)
        if n < self.threshold:
            return [False] * n

        flags = []
        for i, t in enumerate(self.commit_times):
            lo = t - self.window_s
            # count commits in [lo, t] using the sorted property
            count = 0
            for j in range(i, -1, -1):
                if self.commit_times[j] < lo:
                    break
                count += 1
            flags.append(count >= self.threshold)
        return flags

    # -- public API ---------------------------------------------------------

    def storm_commits(self) -> int:
        """Number of commits classified as storm."""
        return sum(self._storm_flags)

    def calm_commits(self) -> int:
        """Number of commits classified as calm."""
        return len(self._storm_flags) - self.storm_commits()

    @property
    def storm_ratio(self) -> float:
        """Fraction of commits in storms (0.0 – 1.0)."""
        n = len(self._storm_flags)
        if n == 0:
            return 0.0
        return self.storm_commits() / n

    def bursts(self) -> list:
        """Return list of (start_time, end_time, count) for each burst."""
        if not self._storm_flags:
            return []

        result = []
        burst_start = None
        for i, (t, is_storm) in enumerate(
            zip(self.commit_times, self._storm_flags)
        ):
            if is_storm:
                if burst_start is None:
                    burst_start = i
            else:
                if burst_start is not None:
                    result.append(
                        (
                            self.commit_times[burst_start],
                            self.commit_times[i - 1],
                            i - burst_start,
                        )
                    )
                    burst_start = None
        # close open burst
        if burst_start is not None:
            last = len(self.commit_times) - 1
            result.append(
                (
                    self.commit_times[burst_start],
                    self.commit_times[last],
                    last - burst_start + 1,
                )
            )
        return result

    @property
    def max_burst(self) -> int:
        """Size of the largest burst (0 if none)."""
        bs = self.bursts()
        return max((b[2] for b in bs), default=0)

    @property
    def max_burst_duration_s(self) -> float:
        """Duration in seconds of the largest burst (0.0 if none)."""
        bs = self.bursts()
        if not bs:
            return 0.0
        biggest = max(bs, key=lambda b: b[2])
        return biggest[1] - biggest[0]

    @property
    def verdict(self) -> str:
        """Single-word summary of storm severity."""
        return _classify(self.storm_ratio)

    def summary(self) -> dict:
        """Return a dict with all metrics."""
        return {
            "total_commits": len(self.commit_times),
            "storm_commits": self.storm_commits(),
            "calm_commits": self.calm_commits(),
            "storm_ratio": round(self.storm_ratio, 4),
            "max_burst": self.max_burst,
            "max_burst_duration_s": round(self.max_burst_duration_s, 2),
            "num_bursts": len(self.bursts()),
            "verdict": self.verdict,
        }


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def storm_report(
    commit_times: Sequence[float],
    window_s: float = 300.0,
    threshold: int = 5,
) -> str:
    """One-line human-readable storm summary."""
    csd = CommitStormDetector(
        commit_times=list(commit_times), window_s=window_s, threshold=threshold
    )
    s = csd.summary()
    if s["total_commits"] == 0:
        return "no commits — nothing to analyse"
    pct = f"{s['storm_ratio'] * 100:.1f}%"
    burst_info = ""
    if s["max_burst"] > 0:
        burst_info = f", max burst {s['max_burst']} in {s['max_burst_duration_s']:.0f}s"
    return (
        f"{s['total_commits']} commits, "
        f"{s['storm_commits']} storm ({pct})"
        f"{burst_info} — {s['verdict']}"
    )
