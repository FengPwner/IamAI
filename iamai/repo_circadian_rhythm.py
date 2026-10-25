"""repo_circadian_rhythm — measure the repository's activity rhythm.

A living repository has a circadian rhythm: patterns of activity and
rest across the 24-hour cycle.  Just as biological organisms need both
active phases and recovery phases, a healthy repository shows a clear
distinction between productive hours and quiet hours.

The circadian metaphor
----------------------

=========================  ===================================================
concept                    what it maps to
=========================  ===================================================
**active phase**           hours with high commit frequency
**rest phase**             hours with few or no commits
**amplitude**              difference between peak and trough activity
**phase alignment**        whether active hours match expected working hours
                           (default 08:00-22:00 local time)
**rhythm regularity**      day-to-day consistency of the activity pattern
**zeitgeber**              external cues that entrain the rhythm
                           (caretaker visits, scheduled tasks)
=========================  ===================================================

Metrics
-------

============================  ================================================
metric                        description
============================  ================================================
``hourly_distribution``       list of 24 ints; commits per hour-of-day
``peak_hour``                 hour with most commits (0-23)
``trough_hour``               hour with fewest commits (0-23)
``amplitude``                 ratio of peak to mean hourly count (>1.0)
``rest_depth``                fraction of trough hours with zero commits
``phase_alignment``           0-100; overlap of active hours with work hours
``regularity_score``          0-100; day-to-day consistency of the pattern
``rhythm_score``              0-100 composite health score
``rhythm_state``              one of: entrained, rhythmic, arrhythmic,
                              jetlagged, dormant
============================  ================================================

Rhythm states
-------------

- **entrained**: strong rhythm aligned with expected hours (score ≥ 75)
- **rhythmic**: clear rhythm but mild misalignment (score 55-74)
- **arrhythmic**: no clear pattern; commits spread uniformly (score < 55)
- **jetlagged**: rhythm exists but shifted away from expected hours
- **dormant**: fewer than 24 commits total; not enough data

Edge cases
----------

- Empty commit log: returns zeroed metrics, state "dormant".
- All commits in a single hour: amplitude is inf, capped at 10.0.
- Fewer than 7 days of history: regularity is 0 (not enough data).

Usage::

    from iamai.repo_circadian_rhythm import circadian_report, circadian_summary

    r = circadian_report(repo_path=".", last=500)
    print(r.rhythm_score)    # e.g. 72.3
    print(r.rhythm_state)    # "rhythmic"
    print(circadian_summary(r))
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Default work-hours window (local time, 24h format)
# ---------------------------------------------------------------------------

DEFAULT_WORK_START = 8   # 08:00
DEFAULT_WORK_END = 22    # 22:00


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CircadianReport:
    """Complete circadian-rhythm assessment for a repository."""

    hourly_distribution: List[int] = field(default_factory=lambda: [0] * 24)
    peak_hour: int = 0
    trough_hour: int = 0
    amplitude: float = 0.0
    rest_depth: float = 0.0
    phase_alignment: float = 0.0
    regularity_score: float = 0.0
    rhythm_score: float = 0.0
    rhythm_state: str = "dormant"
    total_commits: int = 0
    active_days: int = 0
    work_start: int = DEFAULT_WORK_START
    work_end: int = DEFAULT_WORK_END


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git_log(repo: str | Path, last: int) -> List[Tuple[str, int]]:
    """Return list of (hash, unix_timestamp) from git log."""
    fmt = "%H%x00%at"
    try:
        out = subprocess.check_output(
            ["git", "log", f"--max-count={last}", f"--format={fmt}", "--"],
            cwd=str(repo),
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []

    entries: List[Tuple[str, int]] = []
    for line in out.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\x00")
        if len(parts) < 2:
            continue
        try:
            entries.append((parts[0], int(parts[1])))
        except ValueError:
            continue
    return entries


# ---------------------------------------------------------------------------
# Hourly distribution
# ---------------------------------------------------------------------------

def _build_hourly(timestamps: List[int], tz_offset_hours: int = 0) -> List[int]:
    """Bin timestamps into 24 hourly slots, with optional UTC offset."""
    hourly = [0] * 24
    for ts in timestamps:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        local_hour = (dt.hour + tz_offset_hours) % 24
        hourly[local_hour] += 1
    return hourly


def _build_daily_hourly(
    timestamps: List[int], tz_offset_hours: int = 0
) -> Dict[str, List[int]]:
    """Group timestamps by date, return {date_str: [24 hourly counts]}."""
    days: Dict[str, List[int]] = {}
    for ts in timestamps:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        local_dt = dt.replace(
            hour=(dt.hour + tz_offset_hours) % 24
        )
        day_str = local_dt.strftime("%Y-%m-%d")
        if day_str not in days:
            days[day_str] = [0] * 24
        days[day_str][local_dt.hour] += 1
    return days


# ---------------------------------------------------------------------------
# Metric calculations
# ---------------------------------------------------------------------------

def _peak_and_trough(hourly: List[int]) -> Tuple[int, int]:
    """Return (peak_hour, trough_hour)."""
    peak = max(range(24), key=lambda h: hourly[h])
    trough = min(range(24), key=lambda h: hourly[h])
    return peak, trough


def _amplitude(hourly: List[int]) -> float:
    """Ratio of peak count to mean count, capped at 10.0."""
    mean_count = sum(hourly) / 24.0
    if mean_count == 0:
        return 0.0
    peak_count = max(hourly)
    ratio = peak_count / mean_count
    return min(ratio, 10.0)


def _rest_depth(hourly: List[int]) -> float:
    """Fraction of the 24 hours that have zero commits."""
    if not hourly:
        return 0.0
    zero_hours = sum(1 for h in hourly if h == 0)
    return zero_hours / 24.0


def _phase_alignment(
    hourly: List[int], work_start: int, work_end: int
) -> float:
    """Score 0-100: what fraction of commits fall within work hours."""
    total = sum(hourly)
    if total == 0:
        return 0.0

    work_commits = 0
    h = work_start
    while h != work_end:
        work_commits += hourly[h]
        h = (h + 1) % 24

    fraction = work_commits / total
    # Scale: 50% in work hours = 0 score, 100% = 100 score
    # (random distribution would put ~58% in a 14-hour window)
    baseline = (work_end - work_start) / 24.0
    if fraction <= baseline:
        return 0.0
    score = ((fraction - baseline) / (1.0 - baseline)) * 100.0
    return min(max(score, 0.0), 100.0)


def _regularity(daily_hourly: Dict[str, List[int]]) -> float:
    """Score 0-100: day-to-day consistency of peak hour.

    For each pair of consecutive days, check if their peak hours are
    within 2 hours of each other.  Score = fraction of pairs that match.
    Requires at least 7 days.
    """
    dates = sorted(daily_hourly.keys())
    if len(dates) < 7:
        return 0.0

    matches = 0
    total_pairs = 0
    for i in range(len(dates) - 1):
        day_a = daily_hourly[dates[i]]
        day_b = daily_hourly[dates[i + 1]]
        if sum(day_a) == 0 or sum(day_b) == 0:
            continue
        peak_a = max(range(24), key=lambda h: day_a[h])
        peak_b = max(range(24), key=lambda h: day_b[h])
        distance = min(abs(peak_a - peak_b), 24 - abs(peak_a - peak_b))
        if distance <= 2:
            matches += 1
        total_pairs += 1

    if total_pairs == 0:
        return 0.0
    return (matches / total_pairs) * 100.0


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

def _rhythm_score(
    amplitude: float,
    rest_depth: float,
    phase_alignment: float,
    regularity: float,
) -> float:
    """Weighted composite score 0-100."""
    # amplitude: contributes 25%  (normalise: 1.0-10.0 → 0-100)
    amp_norm = min((amplitude - 1.0) / 4.0 * 100.0, 100.0) if amplitude > 1.0 else 0.0
    # rest_depth: contributes 20%
    rest_norm = rest_depth * 100.0
    # phase_alignment: contributes 30%
    # regularity: contributes 25%
    score = (
        0.25 * max(amp_norm, 0.0)
        + 0.20 * rest_norm
        + 0.30 * phase_alignment
        + 0.25 * regularity
    )
    return round(min(max(score, 0.0), 100.0), 1)


def _classify_state(
    score: float,
    phase_alignment: float,
    total_commits: int,
) -> str:
    """Map score and alignment to a rhythm state label."""
    if total_commits < 24:
        return "dormant"
    if score >= 75:
        return "entrained"
    if score >= 55:
        return "rhythmic"
    # low score: check if it's jetlagged (strong rhythm, wrong hours)
    if phase_alignment < 20 and score < 55:
        return "jetlagged"
    return "arrhythmic"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def circadian_report(
    repo_path: str | Path = ".",
    last: int = 500,
    work_start: int = DEFAULT_WORK_START,
    work_end: int = DEFAULT_WORK_END,
    tz_offset_hours: int = 0,
) -> CircadianReport:
    """Generate a circadian-rhythm report for the repository.

    Parameters
    ----------
    repo_path : path to the git repository
    last : number of recent commits to analyse
    work_start, work_end : expected active-phase window (24h, inclusive/exclusive)
    tz_offset_hours : UTC offset for local-time binning (e.g. +8 for CST)
    """
    entries = _git_log(repo_path, last)
    total = len(entries)

    if total == 0:
        return CircadianReport()

    timestamps = [ts for _, ts in entries]
    hourly = _build_hourly(timestamps, tz_offset_hours)
    daily_hourly = _build_daily_hourly(timestamps, tz_offset_hours)

    peak, trough = _peak_and_trough(hourly)
    amp = _amplitude(hourly)
    rest = _rest_depth(hourly)
    alignment = _phase_alignment(hourly, work_start, work_end)
    reg = _regularity(daily_hourly)
    score = _rhythm_score(amp, rest, alignment, reg)
    state = _classify_state(score, alignment, total)

    return CircadianReport(
        hourly_distribution=hourly,
        peak_hour=peak,
        trough_hour=trough,
        amplitude=round(amp, 2),
        rest_depth=round(rest, 3),
        phase_alignment=round(alignment, 1),
        regularity_score=round(reg, 1),
        rhythm_score=score,
        rhythm_state=state,
        total_commits=total,
        active_days=len(daily_hourly),
        work_start=work_start,
        work_end=work_end,
    )


def circadian_summary(report: CircadianReport) -> str:
    """One-line human-readable summary."""
    if report.rhythm_state == "dormant":
        return "dormant: not enough commits to assess circadian rhythm"
    return (
        f"{report.rhythm_state}: score={report.rhythm_score}, "
        f"peak={report.peak_hour:02d}:00, trough={report.trough_hour:02d}:00, "
        f"amplitude={report.amplitude}, alignment={report.phase_alignment}%, "
        f"regularity={report.regularity_score}%, "
        f"{report.total_commits} commits over {report.active_days} days"
    )
