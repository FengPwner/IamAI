#!/usr/bin/env python3
"""commit_echo — detect whether a codebase replays the same change patterns.

An echo is a sound that bounces off a surface and returns to the listener
 recognisably similar to the original.  In a codebase, an **echo** is a
 commit whose file-set closely resembles a recent earlier commit — not
 because it is building on the earlier work (that would be resonance or
 inertia) but because it is *repeating* it.

Some echoes are healthy: a module that is regularly touched as part of a
 release ritual (bump version, update changelog, tag) produces a clean,
 predictable echo pattern.  Some echoes are pathological: a CI flake that
 triggers the same three "fix" files every day, a stale cron job that
 regenerates a config, or an agent stuck in a content loop that keeps
 editing the same handful of files.

The difference between healthy repetition and pathological looping is
 **intent variety**.  If the same files are touched but the commit messages
 describe different work, the repetition is structural (those files are a
 hot area) and harmless.  If the messages also repeat, the repetition is
 semantic and likely a loop.

Echo dimensions
--------------

========================  ================================================
metric                    meaning
========================  ================================================
file_set_recurrence       fraction of commits whose file-set has a
                          Jaccard similarity ≥ ``jaccard_threshold``
                          with at least one commit in the preceding
                          ``lookback`` window
                          (higher = more echo-prone)
message_recurrence        fraction of commits whose normalised message
                          has a token-overlap ≥ ``msg_threshold`` with
                          at least one earlier commit in the window
                          (higher = more semantic repetition)
combined_echo_rate        fraction of commits that are echoes on BOTH
                          file-set AND message axes simultaneously
                          (high = pathological loop likely)
echo_periodicity          coefficient of variation of intervals between
                          consecutive echo events; low CV = regular
                          (machine-like) repetition; high CV = sporadic
                          (human-driven) repetition
echo_score                composite 0.0–1.0: low = healthy variety;
                          high = stuck in a loop
echo_class                fresh | varied | repetitive | looping | stuck
========================  ================================================

Echo classes
------------

==============  ============================================================
class           meaning
==============  ============================================================
fresh           score < 0.20 — nearly every commit touches new ground
varied          0.20 ≤ score < 0.40 — some overlap but mostly diverse
repetitive      0.40 ≤ score < 0.60 — significant overlap; worth
                investigating whether this is structural or a loop
looping         0.60 ≤ score < 0.80 — strong echo pattern; both files
                and messages repeat; likely a content loop
stuck           score ≥ 0.80 — nearly every commit replays a previous
                one; pipeline is effectively stuck
==============  ============================================================

Public API
----------
- ``CommitInfo`` — data class for one commit
- ``compute_echo(commits, *, lookback=20, ...) -> EchoResult``
- ``classify_echo(score) -> str``
- ``echo_report(result) -> str``
- ``echo_trend(results) -> EchoTrend``

Usage::

    from iamai.commit_echo import CommitInfo, compute_echo
    commits = [CommitInfo(...), ...]
    result = compute_echo(commits)
    print(result.echo_class, result.echo_score)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class CommitInfo:
    """Minimal commit metadata for echo analysis."""
    hash: str
    author: str
    timestamp: datetime
    message: str
    files_changed: list[str]


@dataclass
class EchoResult:
    """Output of echo analysis for a window of commits."""
    commit_count: int
    file_set_recurrence: float
    message_recurrence: float
    combined_echo_rate: float
    echo_periodicity: float
    echo_score: float
    echo_class: str
    echo_count: int
    window_size: int
    is_empty: bool = False


@dataclass
class EchoTrend:
    """Direction of echo behaviour across multiple windows."""
    direction: str  # "increasing" | "stable" | "decreasing"
    scores: list[float]
    latest_class: str
    note: str


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _tokenise(msg: str) -> set[str]:
    """Normalise a commit message into a token set for overlap comparison."""
    # lowercase, strip punctuation, drop very short tokens
    tokens = re.findall(r"[a-z0-9]+", msg.lower())
    return {t for t in tokens if len(t) > 2}


def _token_overlap(a: set[str], b: set[str]) -> float:
    """Token-level Jaccard similarity for message comparison."""
    return _jaccard(a, b)


def _is_file_echo(commit_files: set[str], window: list[CommitInfo],
                  threshold: float) -> bool:
    """True if *commit_files* echoes any commit in *window*."""
    for prev in window:
        if _jaccard(commit_files, set(prev.files_changed)) >= threshold:
            return True
    return False


def _is_msg_echo(commit_tokens: set[str], window: list[CommitInfo],
                 threshold: float) -> bool:
    """True if *commit_tokens* echoes any message in *window*."""
    for prev in window:
        prev_tokens = _tokenise(prev.message)
        if _token_overlap(commit_tokens, prev_tokens) >= threshold:
            return True
    return False


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def classify_echo(score: float) -> str:
    """Map a 0.0–1.0 score to an echo class label."""
    if score < 0.20:
        return "fresh"
    if score < 0.40:
        return "varied"
    if score < 0.60:
        return "repetitive"
    if score < 0.80:
        return "looping"
    return "stuck"


def compute_echo(
    commits: list[CommitInfo],
    *,
    lookback: int = 20,
    jaccard_threshold: float = 0.50,
    msg_threshold: float = 0.50,
) -> EchoResult:
    """Analyse a sequence of commits for echo (repetition) patterns.

    Parameters
    ----------
    commits : list[CommitInfo]
        Chronologically ordered commits (oldest first).
    lookback : int
        How many preceding commits to compare each commit against.
    jaccard_threshold : float
        Minimum Jaccard similarity to count as a file-set echo.
    msg_threshold : float
        Minimum token overlap to count as a message echo.

    Returns
    -------
    EchoResult with recurrence rates, combined echo rate, periodicity,
    composite score, and classification.
    """
    n = len(commits)
    if n < 2:
        return EchoResult(
            commit_count=n,
            file_set_recurrence=0.0,
            message_recurrence=0.0,
            combined_echo_rate=0.0,
            echo_periodicity=float("inf"),
            echo_score=0.0,
            echo_class="fresh",
            echo_count=0,
            window_size=lookback,
            is_empty=(n == 0),
        )

    file_echo_flags: list[bool] = []
    msg_echo_flags: list[bool] = []
    echo_timestamps: list[datetime] = []

    for i in range(1, n):
        window_start = max(0, i - lookback)
        window = commits[window_start:i]
        cur = commits[i]
        cur_files = set(cur.files_changed)
        cur_tokens = _tokenise(cur.message)

        f_echo = _is_file_echo(cur_files, window, jaccard_threshold)
        m_echo = _is_msg_echo(cur_tokens, window, msg_threshold)
        file_echo_flags.append(f_echo)
        msg_echo_flags.append(m_echo)
        if f_echo and m_echo:
            echo_timestamps.append(cur.timestamp)

    comparisons = len(file_echo_flags)  # n - 1
    file_set_recurrence = sum(file_echo_flags) / comparisons
    message_recurrence = sum(msg_echo_flags) / comparisons

    combined_flags = [f and m for f, m in zip(file_echo_flags, msg_echo_flags)]
    combined_echo_rate = sum(combined_flags) / comparisons
    echo_count = sum(combined_flags)

    # periodicity: CV of intervals between combined echo events
    echo_periodicity = float("inf")
    if len(echo_timestamps) >= 3:
        echo_timestamps.sort()
        intervals = [
            (echo_timestamps[j + 1] - echo_timestamps[j]).total_seconds()
            for j in range(len(echo_timestamps) - 1)
        ]
        if intervals:
            mean_iv = sum(intervals) / len(intervals)
            if mean_iv > 0:
                variance = sum((iv - mean_iv) ** 2 for iv in intervals) / len(intervals)
                echo_periodicity = math.sqrt(variance) / mean_iv
            else:
                echo_periodicity = 0.0

    # composite score: weighted combination
    # file recurrence (0.30) + message recurrence (0.30) + combined rate (0.30)
    # + periodicity bonus/penalty (0.10)
    # low periodicity CV (regular, machine-like) is worse → higher score
    if echo_periodicity == float("inf"):
        periodicity_component = 0.0
    elif echo_periodicity < 0.3:
        periodicity_component = 1.0  # very regular → likely automated loop
    elif periodicity < 1.0:
        periodicity_component = 0.6
    else:
        periodicity_component = max(0.0, 1.0 - (echo_periodicity - 1.0) * 0.3)

    echo_score = (
        0.30 * file_set_recurrence
        + 0.30 * message_recurrence
        + 0.30 * combined_echo_rate
        + 0.10 * periodicity_component
    )
    echo_score = round(min(1.0, max(0.0, echo_score)), 4)
    echo_class = classify_echo(echo_score)

    return EchoResult(
        commit_count=n,
        file_set_recurrence=round(file_set_recurrence, 4),
        message_recurrence=round(message_recurrence, 4),
        combined_echo_rate=round(combined_echo_rate, 4),
        echo_periodicity=round(echo_periodicity, 4) if echo_periodicity != float("inf") else float("inf"),
        echo_score=echo_score,
        echo_class=echo_class,
        echo_count=echo_count,
        window_size=lookback,
    )


def echo_report(result: EchoResult) -> str:
    """Human-readable summary of echo analysis."""
    if result.is_empty:
        return "echo analysis: no commits to analyse"
    lines = [
        f"echo analysis ({result.commit_count} commits, lookback={result.window_size}):",
        f"  file-set recurrence:   {result.file_set_recurrence:.2%}",
        f"  message recurrence:    {result.message_recurrence:.2%}",
        f"  combined echo rate:    {result.combined_echo_rate:.2%}",
        f"  echo events:           {result.echo_count}",
        f"  periodicity (CV):      {'inf' if result.echo_periodicity == float('inf') else f'{result.echo_periodicity:.2f}'}",
        f"  echo score:            {result.echo_score:.2f}  →  {result.echo_class}",
    ]
    return "\n".join(lines)


def echo_trend(results: list[EchoResult]) -> EchoTrend:
    """Classify the direction of echo behaviour across multiple windows."""
    if not results:
        return EchoTrend(
            direction="stable",
            scores=[],
            latest_class="fresh",
            note="no data",
        )
    scores = [r.echo_score for r in results]
    latest = results[-1]

    if len(scores) < 2:
        return EchoTrend(
            direction="stable",
            scores=scores,
            latest_class=latest.echo_class,
            note="single window; no trend",
        )

    # compare first half average vs second half average
    mid = len(scores) // 2
    first_avg = sum(scores[:mid]) / mid
    second_avg = sum(scores[mid:]) / (len(scores) - mid)
    delta = second_avg - first_avg

    if delta > 0.10:
        direction = "increasing"
        note = "echo behaviour is worsening — more repetition detected"
    elif delta < -0.10:
        direction = "decreasing"
        note = "echo behaviour is improving — more variety emerging"
    else:
        direction = "stable"
        note = "echo behaviour is consistent"

    return EchoTrend(
        direction=direction,
        scores=scores,
        latest_class=latest.echo_class,
        note=note,
    )
