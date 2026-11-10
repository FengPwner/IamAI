#!/usr/bin/env python3
"""commit_reverb — measure how a change echoes through future commits.

When you push a commit, its influence doesn't stop at the files it
touched.  Good changes propagate: follow-up commits fix typos they
introduced, update tests they forgot, refactor callers they affected.
Bad changes also propagate, but differently — they spawn reverts,
workarounds, and band-aid fixes.

This module measures the **reverberation** of a commit: how many
subsequent commits touch files the original touched, how quickly
the echoes decay, and what the echo pattern says about codebase health.

Reverb dimensions
-----------------

========================  ================================================
metric                    meaning
========================  ================================================
echo_count                number of subsequent commits that share ≥ 1
                          file with the source commit (within the
                          analysis window)
echo_ratio                echo_count / total subsequent commits
first_echo_hours          hours between the source commit and its first
                          echo (lower = more immediate follow-up)
decay_rate                exponential decay constant λ fitted to the
                          echo distribution over time (higher = faster
                          fade-out; 0 = constant echoing)
half_life_hours           time for echo probability to halve (ln2 / λ)
concentrated_fraction     fraction of echoes that hit the *same* subset
                          of files the source touched (high = deepening
                          the same spot; low = spreading outward)
reverb_score              composite 0.0–1.0 score: high = healthy echo
                          pattern (quick follow-up, clean decay); low =
                          either silence (no echoes) or chaos (endless
                          rework)
reverb_class              resonant | warm | quiet | silent | chaotic
========================  ================================================

Reverb classes
--------------

==============  ============================================================
class           meaning
==============  ============================================================
resonant        score ≥ 0.80 — changes echo productively then fade cleanly
warm            0.60 ≤ score < 0.80 — good follow-up, mild lingering
quiet           0.40 ≤ score < 0.60 — some follow-up but decays too fast
                  or too slow
silent          0.20 ≤ score < 0.40 — changes land and are never revisited
                  (possible neglect)
chaotic         score < 0.20 — endless rework echoes that never decay
                  (possible thrashing)
==============  ============================================================

Public API
----------
- ``CommitInfo`` — data class for one commit's metadata
- ``compute_reverb(source, subsequent, ...) -> ReverbResult``
- ``classify_reverb(score) -> str``
- ``reverb_report(result) -> str``
- ``reverb_trend(results) -> ReverbTrend``

Usage::

    from iamai.commit_reverb import CommitInfo, compute_reverb
    from datetime import datetime

    source = CommitInfo(
        sha="abc123",
        timestamp=datetime(2026, 11, 10, 10, 0),
        files={"iamai/foo.py", "tests/test_foo.py"},
    )
    subsequent = [
        CommitInfo(sha="def456",
                   timestamp=datetime(2026, 11, 10, 10, 15),
                   files={"iamai/foo.py", "iamai/bar.py"}),
        CommitInfo(sha="ghi789",
                   timestamp=datetime(2026, 11, 10, 11, 0),
                   files={"tests/test_bar.py"}),
        CommitInfo(sha="jkl012",
                   timestamp=datetime(2026, 11, 10, 12, 0),
                   files={"iamai/foo.py", "docs/FOO.md"}),
    ]
    r = compute_reverb(source, subsequent)
    print(r.reverb_class)   # "resonant"
    print(r.echo_count)     # 2
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommitInfo:
    """Lightweight commit metadata for reverb analysis."""

    sha: str
    timestamp: object  # datetime; not typed to avoid import at module level
    files: frozenset = field(default_factory=frozenset)

    def __post_init__(self):
        # Accept any iterable; freeze to frozenset.
        if not isinstance(self.files, frozenset):
            object.__setattr__(self, "files", frozenset(self.files))


@dataclass
class ReverbResult:
    """Complete reverb analysis for one source commit."""

    source_sha: str
    window_commits: int
    echo_count: int
    echo_ratio: float
    first_echo_hours: Optional[float]
    decay_rate: float
    half_life_hours: Optional[float]
    concentrated_fraction: float
    reverb_score: float
    reverb_class: str


@dataclass
class ReverbTrend:
    """Direction of reverb scores over time."""

    direction: str          # improving | stable | declining
    score_delta: float
    earliest_score: float
    latest_score: float
    sample_count: int


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_THRESHOLDS = [
    (0.80, "resonant"),
    (0.60, "warm"),
    (0.40, "quiet"),
    (0.20, "silent"),
    (0.00, "chaotic"),
]


def classify_reverb(score: float) -> str:
    """Map a 0.0–1.0 reverb score to a class label."""
    for threshold, label in _THRESHOLDS:
        if score >= threshold:
            return label
    return "chaotic"


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _hours_between(dt1, dt2) -> float:
    """Hours between two datetimes (absolute value)."""
    delta = dt2 - dt1
    return abs(delta.total_seconds()) / 3600.0


def _fit_decay(hours_list: List[float], window_hours: float) -> float:
    """Estimate exponential decay rate λ from echo timestamps.

    Uses a simple moment-matching estimator: for an exponential
    distribution with rate λ, the mean is 1/λ.  We set λ = 1/mean
    when there are enough data points; otherwise return a default
    indicating no measurable decay.
    """
    if not hours_list or window_hours <= 0:
        return 0.0
    if len(hours_list) < 2:
        # Single echo: use the ratio of its position in the window
        # as a rough proxy.
        return 1.0 / max(hours_list[0], 0.01)
    mean_hours = sum(hours_list) / len(hours_list)
    if mean_hours <= 0:
        return 0.0
    return 1.0 / mean_hours


def compute_reverb(
    source: CommitInfo,
    subsequent: Sequence[CommitInfo],
    *,
    window_hours: float = 72.0,
) -> ReverbResult:
    """Analyse how a source commit echoes through subsequent commits.

    Parameters
    ----------
    source : CommitInfo
        The commit whose reverberation we want to measure.
    subsequent : sequence of CommitInfo
        Commits that came *after* the source, in chronological order.
        Commits with timestamps before the source are silently ignored.
    window_hours : float
        Only consider echoes within this many hours after the source.

    Returns
    -------
    ReverbResult
    """
    source_files = source.files
    if not source_files:
        return ReverbResult(
            source_sha=source.sha,
            window_commits=0,
            echo_count=0,
            echo_ratio=0.0,
            first_echo_hours=None,
            decay_rate=0.0,
            half_life_hours=None,
            concentrated_fraction=0.0,
            reverb_score=0.0,
            reverb_class="silent",
        )

    # Filter to commits within the window and after the source.
    in_window: List[CommitInfo] = []
    for c in subsequent:
        if c.timestamp <= source.timestamp:
            continue
        if _hours_between(source.timestamp, c.timestamp) > window_hours:
            continue
        in_window.append(c)

    if not in_window:
        return ReverbResult(
            source_sha=source.sha,
            window_commits=0,
            echo_count=0,
            echo_ratio=0.0,
            first_echo_hours=None,
            decay_rate=0.0,
            half_life_hours=None,
            concentrated_fraction=0.0,
            reverb_score=0.0,
            reverb_class="silent",
        )

    # Identify echoes: subsequent commits sharing ≥ 1 file with source.
    echoes: List[CommitInfo] = []
    echo_hours: List[float] = []
    for c in in_window:
        if c.files & source_files:
            echoes.append(c)
            echo_hours.append(_hours_between(source.timestamp, c.timestamp))

    echo_count = len(echoes)
    echo_ratio = echo_count / len(in_window) if in_window else 0.0

    first_echo_hours = min(echo_hours) if echo_hours else None

    # Decay rate
    decay_rate = _fit_decay(echo_hours, window_hours)
    half_life_hours = math.log(2) / decay_rate if decay_rate > 0 else None

    # Concentrated fraction: how many echoes only touch the *same* files
    # as the source (no expansion to new files).
    if echoes:
        same_only = sum(
            1 for c in echoes if c.files <= source_files
        )
        concentrated_fraction = same_only / echo_count
    else:
        concentrated_fraction = 0.0

    # --- Composite score ---
    # Three sub-scores, equally weighted:
    #
    # 1. Response score (0–1): Is there *some* follow-up?  A healthy
    #    codebase revisits changes.  Zero echoes = neglect.
    #    Optimal echo_ratio ≈ 0.2–0.5 (some follow-up, not everything).
    if echo_ratio <= 0.0:
        response_score = 0.0
    elif echo_ratio <= 0.5:
        response_score = echo_ratio / 0.5  # ramp up to 1.0 at 0.5
    else:
        response_score = max(0.3, 1.0 - (echo_ratio - 0.5))  # decay past 0.5

    # 2. Decay score (0–1): Do echoes fade, or do they persist forever?
    #    Fast decay (high λ) means changes settle quickly.  We want
    #    moderate-to-fast decay.  λ in [0.05, 2.0] maps to the best range.
    if decay_rate <= 0:
        decay_score = 0.0  # no measurable decay = persistent echoes
    elif decay_rate >= 0.1:
        decay_score = min(1.0, decay_rate / 0.5)
    else:
        decay_score = decay_rate / 0.1 * 0.5

    # 3. Spread score (0–1): Are echoes expanding or just re-digging?
    #    Lower concentrated_fraction = more expansion = healthier.
    spread_score = 1.0 - concentrated_fraction

    reverb_score = (response_score + decay_score + spread_score) / 3.0
    reverb_score = round(max(0.0, min(1.0, reverb_score)), 4)
    reverb_class = classify_reverb(reverb_score)

    return ReverbResult(
        source_sha=source.sha,
        window_commits=len(in_window),
        echo_count=echo_count,
        echo_ratio=round(echo_ratio, 4),
        first_echo_hours=round(first_echo_hours, 4) if first_echo_hours is not None else None,
        decay_rate=round(decay_rate, 4),
        half_life_hours=round(half_life_hours, 2) if half_life_hours is not None else None,
        concentrated_fraction=round(concentrated_fraction, 4),
        reverb_score=reverb_score,
        reverb_class=reverb_class,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def reverb_report(result: ReverbResult) -> str:
    """Human-readable summary of a reverb analysis."""
    lines = [
        f"Reverb analysis for {result.source_sha[:12]}",
        f"  class:             {result.reverb_class}",
        f"  score:             {result.reverb_score:.2f}",
        f"  window commits:    {result.window_commits}",
        f"  echo count:        {result.echo_count}",
        f"  echo ratio:        {result.echo_ratio:.2%}",
    ]
    if result.first_echo_hours is not None:
        lines.append(f"  first echo:        {result.first_echo_hours:.1f}h after source")
    else:
        lines.append("  first echo:        (none)")
    if result.decay_rate > 0:
        lines.append(f"  decay rate (λ):    {result.decay_rate:.3f}")
    if result.half_life_hours is not None:
        lines.append(f"  half-life:         {result.half_life_hours:.1f}h")
    lines.append(f"  concentrated frac: {result.concentrated_fraction:.2%}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def reverb_trend(results: Sequence[ReverbResult]) -> ReverbTrend:
    """Classify how reverb scores evolve over a series of measurements."""
    if not results:
        return ReverbTrend(
            direction="stable",
            score_delta=0.0,
            earliest_score=0.0,
            latest_score=0.0,
            sample_count=0,
        )

    scores = [r.reverb_score for r in results]
    earliest = scores[0]
    latest = scores[-1]
    delta = latest - earliest

    if len(scores) < 2:
        direction = "stable"
    elif delta > 0.05:
        direction = "improving"
    elif delta < -0.05:
        direction = "declining"
    else:
        direction = "stable"

    return ReverbTrend(
        direction=direction,
        score_delta=round(delta, 4),
        earliest_score=earliest,
        latest_score=latest,
        sample_count=len(scores),
    )
