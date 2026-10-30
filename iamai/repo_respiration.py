"""repo_respiration — measure the repository's breathing rhythm.

A living repository breathes: it inhales changes (writer strokes, caretaker
features, bug fixes) and exhales releases (pushes to remote, deployments).
Healthy breathing is regular, neither too shallow nor too deep, with a
consistent rhythm.

The respiration metaphor
-------------------------

=========================  ===================================================
concept                    what it maps to
=========================  ===================================================
**inhalation**             receiving commits (strokes, features, fixes)
**exhalation**             pushing commits to remote
**breath**                 one complete inhale-exhale cycle
**breath rate**            breaths per hour
**tidal volume**           files changed per breath (depth of each cycle)
**respiration score**      0-100 composite health score
**apnea**                  extended pause with no commit activity
**hyperventilation**       rapid, shallow cycles (many tiny commits)
**hypoventilation**        slow, heavy cycles (few massive commits)
**eupnea**                 normal, healthy breathing rhythm
=========================  ===================================================

Metrics
-------

============================  ================================================
metric                        description
============================  ================================================
``breath_rate``               breaths per hour (float)
``tidal_volume``              mean files changed per breath cycle
``apnea_events``              number of pauses longer than ``apnea_threshold``
``longest_apnea``             longest apnea event in seconds
``regularity``                0-100; inverse CV of breath intervals
``depth_score``               0-100; penalises too-shallow or too-deep breaths
``respiration_score``         0-100 composite
``pattern``                   one of: eupnea, hyperventilation,
                              hypoventilation, apneic, irregular, dormant
============================  ================================================

Pattern classification
----------------------

- **eupnea**: healthy rhythm, score >= 70
- **hyperventilation**: too many shallow cycles, score 40-69, rate > 10/h
- **hypoventilation**: too few heavy cycles, score 40-69, rate < 2/h
- **apneic**: significant pauses detected, score < 70, apnea_events >= 3
- **irregular**: inconsistent rhythm, score < 40
- **dormant**: fewer than 10 total breaths, not enough data

Edge cases
----------

- Empty commit log: returns zeroed metrics, pattern "dormant".
- All commits in a single batch: single breath, rate undefined → dormant.
- Fewer than 10 breaths: not enough data → dormant.

Usage::

    from iamai.repo_respiration import respiration_report, respiration_summary

    r = respiration_report(repo_path=".", interval=600)
    print(r.respiration_score)    # e.g. 74.0
    print(r.pattern)              # "eupnea"
    print(respiration_summary(r))
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_BATCH_INTERVAL = 600   # seconds; one commit cycle = one "breath"
DEFAULT_APNEA_THRESHOLD = 1800  # seconds; >30 min without a commit = apnea
DEFAULT_LOOKBACK = 500         # number of recent commits to analyse


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RespirationReport:
    """Complete respiration analysis for a repository."""
    breath_rate: float = 0.0
    tidal_volume: float = 0.0
    apnea_events: int = 0
    longest_apnea: float = 0.0
    regularity: float = 0.0
    depth_score: float = 0.0
    respiration_score: float = 0.0
    pattern: str = "dormant"
    total_breaths: int = 0
    analysis_window_hours: float = 0.0
    breath_intervals: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _git_log(repo_path: str | Path, last: int = DEFAULT_LOOKBACK) -> list[tuple[str, datetime]]:
    """Return list of (hash, timestamp) from git log, newest first."""
    result = subprocess.run(
        ["git", "log", f"--max-count={last}", "--format=%H %aI"],
        capture_output=True, text=True, cwd=str(repo_path),
    )
    if result.returncode != 0:
        return []
    entries = []
    for line in result.stdout.strip().splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        commit_hash, ts_str = parts
        try:
            ts = datetime.fromisoformat(ts_str)
            entries.append((commit_hash, ts))
        except ValueError:
            continue
    return entries


def _git_diffstat(repo_path: str | Path, commit_hash: str) -> int:
    """Return number of files changed in a given commit."""
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
        capture_output=True, text=True, cwd=str(repo_path),
    )
    if result.returncode != 0:
        return 0
    return len([l for l in result.stdout.strip().splitlines() if l.strip()])


def _compute_breath_intervals(
    timestamps: list[datetime],
    batch_interval: int,
) -> list[float]:
    """Group commits into breath cycles and return intervals between cycles.

    A breath cycle is a cluster of commits that happen within one batch
    interval window. Two consecutive commits separated by more than
    ``batch_interval * 1.5`` seconds belong to different breaths.
    """
    if len(timestamps) < 2:
        return []

    # timestamps are newest-first; reverse for chronological order
    ts_chrono = list(reversed(timestamps))
    gap_threshold = batch_interval * 1.5

    breath_starts = [0]
    for i in range(1, len(ts_chrono)):
        gap = (ts_chrono[i] - ts_chrono[i - 1]).total_seconds()
        if gap > gap_threshold:
            breath_starts.append(i)

    # intervals between breath cycle starts
    intervals = []
    for i in range(1, len(breath_starts)):
        idx_prev = breath_starts[i - 1]
        idx_curr = breath_starts[i]
        delta = (ts_chrono[idx_curr] - ts_chrono[idx_prev]).total_seconds()
        intervals.append(delta)

    return intervals


def _detect_apnea(
    timestamps: list[datetime],
    apnea_threshold: int,
) -> list[float]:
    """Find apnea events: gaps between consecutive commits exceeding threshold.

    Returns list of gap durations in seconds.
    """
    if len(timestamps) < 2:
        return []

    ts_chrono = list(reversed(timestamps))
    events = []
    for i in range(1, len(ts_chrono)):
        gap = (ts_chrono[i] - ts_chrono[i - 1]).total_seconds()
        if gap > apnea_threshold:
            events.append(gap)
    return events


def _regularity_score(intervals: list[float]) -> float:
    """Compute regularity as 0-100 score based on coefficient of variation.

    CV = stdev / mean.  Low CV → high regularity.
    CV of 0 → score 100.  CV >= 2 → score 0.
    """
    if len(intervals) < 2:
        return 0.0
    mean = sum(intervals) / len(intervals)
    if mean == 0:
        return 0.0
    variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
    stdev = variance ** 0.5
    cv = stdev / mean
    # Map CV to 0-100 score (linear decay, floor at 0)
    score = max(0.0, 100.0 * (1.0 - cv / 2.0))
    return round(score, 1)


def _depth_score_fn(tidal_volume: float, target_volume: float = 5.0) -> float:
    """Score the depth of each breath. Optimal depth is around target_volume.

    Too shallow (< 1 file/breath) or too deep (> 50 files/breath) both score low.
    Uses a log-normal inspired curve centred on target_volume.
    """
    if tidal_volume <= 0:
        return 0.0
    import math
    # log-normal deviation from target
    ratio = tidal_volume / target_volume
    log_dev = abs(math.log(ratio))
    # score decays exponentially with log deviation
    score = 100.0 * math.exp(-log_dev ** 2)
    return round(score, 1)


def _composite_score(
    regularity: float,
    depth: float,
    apnea_events: int,
    breath_rate: float,
) -> float:
    """Combine sub-scores into a 0-100 composite respiration score.

    Weights:
        regularity  40%
        depth       30%
        apnea-free  30%  (penalised per apnea event, capped)
    """
    reg_component = regularity * 0.4
    depth_component = depth * 0.3
    # apnea penalty: each event costs 10 points, max 30
    apnea_penalty = min(30.0, apnea_events * 10.0)
    apnea_component = (30.0 - apnea_penalty)
    # rate bonus: breathing between 3-8 per hour is ideal
    if 3.0 <= breath_rate <= 8.0:
        rate_bonus = 0.0
    elif breath_rate > 8.0:
        rate_bonus = -min(10.0, (breath_rate - 8.0) * 2.0)
    elif breath_rate < 3.0 and breath_rate > 0:
        rate_bonus = -min(10.0, (3.0 - breath_rate) * 3.0)
    else:
        rate_bonus = -10.0

    raw = reg_component + depth_component + apnea_component + rate_bonus
    return round(max(0.0, min(100.0, raw)), 1)


def _classify_pattern(
    score: float,
    breath_rate: float,
    apnea_events: int,
    total_breaths: int,
) -> str:
    """Map score and metrics to a pattern label."""
    if total_breaths < 10:
        return "dormant"
    if score >= 70:
        return "eupnea"
    if apnea_events >= 3 and score < 70:
        return "apneic"
    if breath_rate > 10.0 and score < 70:
        return "hyperventilation"
    if breath_rate < 2.0 and score < 70:
        return "hypoventilation"
    return "irregular"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def respiration_report(
    repo_path: str | Path = ".",
    last: int = DEFAULT_LOOKBACK,
    batch_interval: int = DEFAULT_BATCH_INTERVAL,
    apnea_threshold: int = DEFAULT_APNEA_THRESHOLD,
) -> RespirationReport:
    """Generate a respiration report for the repository.

    Parameters
    ----------
    repo_path : path to the git repository
    last : number of recent commits to analyse
    batch_interval : expected seconds between commit batches (one breath)
    apnea_threshold : seconds without activity to count as an apnea event
    """
    entries = _git_log(repo_path, last)
    total = len(entries)

    if total == 0:
        return RespirationReport()

    timestamps = [ts for _, ts in entries]

    # Compute breath intervals
    intervals = _compute_breath_intervals(timestamps, batch_interval)
    total_breaths = len(intervals) + 1  # n intervals → n+1 breaths

    # Analysis window
    ts_chrono = list(reversed(timestamps))
    window_seconds = (ts_chrono[-1] - ts_chrono[0]).total_seconds()
    window_hours = window_seconds / 3600.0 if window_seconds > 0 else 0.0

    # Breath rate
    breath_rate = total_breaths / window_hours if window_hours > 0 else 0.0

    # Tidal volume: mean files per commit (proxy for per-breath depth)
    files_changed = []
    for commit_hash, _ in entries[:min(total, 100)]:  # sample up to 100
        n = _git_diffstat(repo_path, commit_hash)
        files_changed.append(n)
    tidal_volume = sum(files_changed) / len(files_changed) if files_changed else 0.0

    # Apnea detection
    apnea_events_list = _detect_apnea(timestamps, apnea_threshold)
    apnea_count = len(apnea_events_list)
    longest_apnea = max(apnea_events_list) if apnea_events_list else 0.0

    # Regularity
    reg = _regularity_score(intervals)

    # Depth
    depth = _depth_score_fn(tidal_volume)

    # Composite
    score = _composite_score(reg, depth, apnea_count, breath_rate)

    # Pattern
    pattern = _classify_pattern(score, breath_rate, apnea_count, total_breaths)

    return RespirationReport(
        breath_rate=round(breath_rate, 2),
        tidal_volume=round(tidal_volume, 1),
        apnea_events=apnea_count,
        longest_apnea=round(longest_apnea, 1),
        regularity=reg,
        depth_score=depth,
        respiration_score=score,
        pattern=pattern,
        total_breaths=total_breaths,
        analysis_window_hours=round(window_hours, 1),
        breath_intervals=[round(i, 1) for i in intervals],
    )


def respiration_summary(report: RespirationReport) -> str:
    """One-line human-readable summary."""
    if report.pattern == "dormant":
        return "dormant: not enough breaths to assess respiration rhythm"
    return (
        f"{report.pattern}: score={report.respiration_score}, "
        f"rate={report.breath_rate}/h, depth={report.tidal_volume} files/breath, "
        f"regularity={report.regularity}%, "
        f"apnea={report.apnea_events} events (longest {report.longest_apnea:.0f}s), "
        f"{report.total_breaths} breaths over {report.analysis_window_hours}h"
    )
