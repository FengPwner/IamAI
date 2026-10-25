"""repo_breath — the write-commit cycle as a breathing metaphor.

A healthy repository *breathes*: it inhales (accumulates strokes /
changes), then exhales (commits flush them to history).  The rhythm
and depth of this cycle reveal systemic health more intuitively than
raw commit counts or stall detectors.

Concepts
--------

============  ===========================================================
phase         what it means
============  ===========================================================
**inhale**    strokes accumulate between two consecutive commits
**exhale**    a commit lands, flushing pending work
**breath**    one complete inhale-then-exhale cycle
============  ===========================================================

Metrics
-------

=======================  =================================================
metric                   what it measures
=======================  =================================================
``breath_rate``          breaths per hour over the observation window
``breath_depth``         mean strokes per breath (inhale volume)
``breath_regularity``    1 − CV of breath durations (1.0 = metronomic)
``hold_ratio``           fraction of breaths lasting > 2× median
                         (high = chronic breath-holding / backlog)
``hyperventilation``     fraction of breaths with depth ≤ 1 stroke
                         (high = too many tiny commits)
``breath_score``         composite 0–100; higher = healthier rhythm
=======================  =================================================

Pattern classification
----------------------

==================  ======================================================
pattern             criteria
==================  ======================================================
``steady``          score ≥ 75 — regular rhythm, reasonable depth
``shallow``         score 50–74 with hyperventilation > 0.4
``holding``         score 50–74 with hold_ratio > 0.3
``erratic``         score 50–74 (neither dominant)
``distressed``      score < 50 — irregular and imbalanced
==================  ======================================================

Edge cases
----------
- Fewer than 2 commits in the window → empty report, score 0.
- Zero-duration breaths (same-second commits) are excluded from
  regularity calculation but counted for depth.

Usage::

    from iamai.repo_breath import breath_report, breath_summary

    r = breath_report(repo_path=".", last=50)
    print(r.breath_score)     # e.g. 72.5
    print(r.pattern)          # "steady"
    print(breath_summary(r))
    # "breathing steady @ 6.2/hr, depth 4.3 strokes, regularity 0.82"
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import math


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _git_log(repo: str | Path, last: int) -> list[dict]:
    """Return *last* commits as dicts with hash, timestamp, parents."""
    fmt = "%H%x00%at%x00%P"
    out = subprocess.check_output(
        ["git", "log", f"--max-count={last}", f"--format={fmt}", "--"],
        cwd=str(repo),
        text=True,
    )
    commits: list[dict] = []
    for line in out.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\x00")
        parent_str = parts[2].strip() if len(parts) > 2 else ""
        commits.append({
            "hash": parts[0],
            "timestamp": float(parts[1]),
            "parents": parent_str.split() if parent_str else [],
        })
    return commits


def _files_per_commit(repo: str | Path, hashes: list[str]) -> dict[str, int]:
    """Return {hash: file_count} for each commit."""
    if not hashes:
        return {}
    out = subprocess.check_output(
        ["git", "log", "--format=%H", "--numstat"]
        + hashes,
        cwd=str(repo),
        text=True,
    )
    result: dict[str, int] = {}
    current_hash: str | None = None
    count = 0
    for line in out.splitlines():
        line = line.strip()
        if len(line) == 40 and all(c in "0123456789abcdef" for c in line):
            if current_hash is not None:
                result[current_hash] = count
            current_hash = line
            count = 0
        elif line and current_hash:
            count += 1
    if current_hash is not None:
        result[current_hash] = count
    return result


# ---------------------------------------------------------------------------
# Stroke counting between commits
# ---------------------------------------------------------------------------

def _strokes_between(repo: str | Path, from_hash: str, to_hash: str) -> int:
    """Count strokes.jsonl lines added between two commits."""
    try:
        diff = subprocess.check_output(
            ["git", "diff", f"{from_hash}..{to_hash}", "--", "data/strokes.jsonl"],
            cwd=str(repo),
            text=True,
        )
    except subprocess.CalledProcessError:
        return 0
    added = sum(
        1 for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    return max(added, 0)


# ---------------------------------------------------------------------------
# Breath computation
# ---------------------------------------------------------------------------

@dataclass
class BreathReport:
    """Summary of the repo's breathing pattern."""

    breath_count: int = 0
    breath_rate: float = 0.0           # breaths per hour
    breath_depth: float = 0.0          # mean strokes per breath
    breath_regularity: float = 0.0     # 1 - CV of durations
    hold_ratio: float = 0.0            # fraction of long breaths
    hyperventilation: float = 0.0      # fraction of shallow breaths
    breath_score: float = 0.0
    pattern: str = "distressed"
    window_seconds: float = 0.0
    breaths: list = field(default_factory=list)  # individual breath data


def _compute_regularity(durations: list[float]) -> float:
    """1 - coefficient of variation; clamped to [0, 1]."""
    if len(durations) < 2:
        return 1.0
    mean = sum(durations) / len(durations)
    if mean <= 0:
        return 0.0
    variance = sum((d - mean) ** 2 for d in durations) / len(durations)
    cv = math.sqrt(variance) / mean
    return max(0.0, min(1.0, 1.0 - cv))


def _compute_score(
    regularity: float,
    depth: float,
    hold_ratio: float,
    hyperventilation: float,
) -> float:
    """Composite score 0-100."""
    # Regularity component: 0-35 points
    reg_pts = regularity * 35.0

    # Depth component: 0-25 points (sweet spot 3-10 strokes/breath)
    if depth <= 0:
        depth_pts = 0.0
    elif depth < 2:
        depth_pts = depth * 5.0
    elif depth <= 10:
        depth_pts = 25.0
    else:
        depth_pts = max(10.0, 25.0 - (depth - 10) * 0.5)

    # Hold penalty: 0-20 points (no holding = full marks)
    hold_pts = (1.0 - min(1.0, hold_ratio / 0.5)) * 20.0

    # Hyperventilation penalty: 0-20 points
    hyper_pts = (1.0 - min(1.0, hyperventilation / 0.5)) * 20.0

    return max(0.0, min(100.0, reg_pts + depth_pts + hold_pts + hyper_pts))


def _classify(score: float, hold_ratio: float, hyperventilation: float) -> str:
    if score >= 75:
        return "steady"
    if score < 50:
        return "distressed"
    if hyperventilation > 0.4:
        return "shallow"
    if hold_ratio > 0.3:
        return "holding"
    return "erratic"


def breath_report(
    repo_path: str | Path = ".",
    last: int = 50,
    stroke_file: str = "data/strokes.jsonl",
) -> BreathReport:
    """Compute the breathing report for the repo.

    Parameters
    ----------
    repo_path : path to the git repository
    last : number of recent commits to analyse (max 200)
    stroke_file : relative path to the strokes log
    """
    repo = Path(repo_path)
    last = min(last, 200)

    commits = _git_log(repo, last)
    if len(commits) < 2:
        return BreathReport()

    # Work oldest-first
    commits.reverse()

    breaths: list[dict] = []
    for i in range(1, len(commits)):
        prev = commits[i - 1]
        curr = commits[i]
        duration = curr["timestamp"] - prev["timestamp"]
        strokes = _strokes_between(repo, prev["hash"], curr["hash"])
        breaths.append({
            "from": prev["hash"][:8],
            "to": curr["hash"][:8],
            "duration_s": duration,
            "strokes": strokes,
        })

    if not breaths:
        return BreathReport()

    # Total observation window
    window_s = commits[-1]["timestamp"] - commits[0]["timestamp"]
    window_hours = window_s / 3600.0 if window_s > 0 else 1.0

    durations = [b["duration_s"] for b in breaths if b["duration_s"] > 0]
    depths = [b["strokes"] for b in breaths]

    breath_rate = len(breaths) / window_hours if window_hours > 0 else 0.0
    breath_depth = sum(depths) / len(depths) if depths else 0.0

    # Median duration for hold detection
    sorted_dur = sorted(durations) if durations else [0]
    median_dur = sorted_dur[len(sorted_dur) // 2] if sorted_dur else 0
    hold_count = sum(1 for d in durations if d > 2 * median_dur) if median_dur > 0 else 0
    hold_ratio = hold_count / len(durations) if durations else 0.0

    # Hyperventilation: breaths with ≤ 1 stroke
    shallow_count = sum(1 for s in depths if s <= 1)
    hyperventilation = shallow_count / len(depths) if depths else 0.0

    regularity = _compute_regularity(durations)
    score = _compute_score(regularity, breath_depth, hold_ratio, hyperventilation)
    pattern = _classify(score, hold_ratio, hyperventilation)

    return BreathReport(
        breath_count=len(breaths),
        breath_rate=round(breath_rate, 2),
        breath_depth=round(breath_depth, 2),
        breath_regularity=round(regularity, 4),
        hold_ratio=round(hold_ratio, 4),
        hyperventilation=round(hyperventilation, 4),
        breath_score=round(score, 2),
        pattern=pattern,
        window_seconds=window_s,
        breaths=breaths,
    )


def breath_summary(report: BreathReport) -> str:
    """One-line human-readable summary."""
    if report.breath_count == 0:
        return "breathing: insufficient data (< 2 commits)"
    return (
        f"breathing {report.pattern} @ {report.breath_rate}/hr, "
        f"depth {report.breath_depth} strokes, "
        f"regularity {report.breath_regularity:.2f}, "
        f"score {report.breath_score}/100"
    )
