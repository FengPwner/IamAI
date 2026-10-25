"""repo_inflammation — detect and score process stress signals.

When a living repository undergoes frequent restarts, push failures,
backlog spikes, or rapid caretaker interventions, it exhibits stress
analogous to biological inflammation. Acute inflammation is a normal
response to injury (a process crash, a network hiccup). Chronic
inflammation — persistently elevated stress signals — indicates a
deeper systemic problem.

The inflammation metaphor
--------------------------

=========================  ===================================================
concept                    what it maps to
=========================  ===================================================
**acute inflammation**     short burst of stress signals (1-2 restarts)
**chronic inflammation**   sustained elevated stress (>5 signals in window)
**inflammation score**     0-100 composite of all signal types
**C-reactive protein**     caretaker restart rate (most sensitive marker)
**white blood cell count** backlog accumulation rate
**fever**                  push failure frequency
**swelling**               commit volume spikes (oversized catch-up commits)
**recovery marker**        time since last stress signal
=========================  ===================================================

Signals detected
----------------

1. **restart_density** — caretaker restarts per hour (from visit notes)
2. **push_failure_rate** — rejected pushes in recent history
3. **backlog_growth** — uncommitted file count trending upward
4. **catch_up_mass** — size of catch-up commits relative to normal
5. **stall_frequency** — writer silence gaps exceeding cadence threshold
6. **stash_accumulation** — growing git stash list (deferred work)

Scoring
-------

Each signal produces a sub-score 0-100. The overall inflammation score
is a weighted combination:

========================  ======
signal                    weight
========================  ======
restart_density           0.25
push_failure_rate         0.15
backlog_growth            0.15
catch_up_mass             0.15
stall_frequency           0.20
stash_accumulation        0.10
========================  ======

States: calm (0-20), mild (21-40), moderate (41-60), severe (61-80),
critical (81-100).
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class InflammationSignal:
    """One detected stress signal."""

    name: str
    score: float  # 0-100
    weight: float
    evidence: str
    timestamp: Optional[datetime] = None

    @property
    def weighted(self) -> float:
        return self.score * self.weight


@dataclass
class InflammationReport:
    """Full inflammation assessment."""

    signals: List[InflammationSignal] = field(default_factory=list)
    inflammation_score: float = 0.0
    inflammation_state: str = "calm"
    primary_stressor: str = ""
    recovery_hours: float = 0.0
    recommendation: str = ""
    window_commits: int = 0
    window_hours: float = 24.0

    @property
    def chronic(self) -> bool:
        return self.inflammation_score > 40 and len(
            [s for s in self.signals if s.score > 50]
        ) >= 3


# ---------------------------------------------------------------------------
# Signal detectors
# ---------------------------------------------------------------------------


def _run(cmd: str, cwd: Optional[str] = None) -> str:
    """Run a shell command and return stdout."""
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _parse_git_log(repo_path: str, hours: float = 24) -> List[dict]:
    """Parse recent git log into structured entries."""
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    raw = _run(
        f'git log --since="{since}" --format="%H|%s|%aI" --reverse',
        cwd=repo_path,
    )
    entries = []
    for line in raw.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            entries.append(
                {"hash": parts[0], "subject": parts[1], "date": parts[2]}
            )
    return entries


def detect_restart_density(
    commits: Sequence[dict], hours: float = 24
) -> InflammationSignal:
    """Count caretaker visit / restart commits in window."""
    restart_patterns = [
        r"catch-up",
        r"restart",
        r"caretaker visit",
        r"recovery",
        r"reclamation",
        r"process restart",
    ]
    restarts = 0
    for c in commits:
        subj = c.get("subject", "")
        if any(re.search(p, subj, re.IGNORECASE) for p in restart_patterns):
            restarts += 1

    # Score: 0 restarts = 0, 10+ restarts in window = 100
    score = min(100, (restarts / max(hours, 1)) * 100 * 2.4)
    evidence = f"{restarts} restart-related commits in {hours}h window"

    return InflammationSignal(
        name="restart_density",
        score=round(score, 1),
        weight=0.25,
        evidence=evidence,
    )


def detect_push_failures(repo_path: str, hours: float = 24) -> InflammationSignal:
    """Check reflog for push rejections."""
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
    reflog = _run(
        f'git reflog --since="{since}" --format="%gs"',
        cwd=repo_path,
    )
    failures = sum(1 for line in reflog.splitlines() if "rejected" in line.lower())

    # Also check the log for push-related error commits
    log = _run(
        f'git log --since="{since}" --format="%s" --all',
        cwd=repo_path,
    )
    push_errors = sum(
        1
        for line in log.splitlines()
        if "push" in line.lower() and ("fail" in line.lower() or "reject" in line.lower())
    )

    total = failures + push_errors
    score = min(100, total * 20)  # 5+ push failures = max score
    evidence = f"{total} push failure events in {hours}h"

    return InflammationSignal(
        name="push_failure_rate",
        score=round(score, 1),
        weight=0.15,
        evidence=evidence,
    )


def detect_backlog_growth(repo_path: str) -> InflammationSignal:
    """Measure uncommitted changes as backlog stress."""
    status = _run("git status --porcelain", cwd=repo_path)
    uncommitted = len([l for l in status.splitlines() if l.strip()])

    # Score: 0 = calm, 20+ uncommitted = severe
    score = min(100, uncommitted * 5)
    evidence = f"{uncommitted} uncommitted files"

    return InflammationSignal(
        name="backlog_growth",
        score=round(score, 1),
        weight=0.15,
        evidence=evidence,
    )


def detect_catch_up_mass(
    commits: Sequence[dict], repo_path: str, hours: float = 24
) -> InflammationSignal:
    """Measure how large catch-up commits are relative to normal."""
    catch_up_sizes = []
    normal_sizes = []

    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    for c in commits:
        stat = _run(
            f'git diff --stat {c["hash"]}~1..{c["hash"]} 2>/dev/null | tail -1',
            cwd=repo_path,
        )
        # Parse "X files changed, Y insertions(+), Z deletions(-)"
        nums = re.findall(r"(\d+)", stat)
        changed = int(nums[0]) if nums else 0

        if "catch-up" in c.get("subject", "").lower():
            catch_up_sizes.append(changed)
        else:
            normal_sizes.append(changed)

    if not catch_up_sizes:
        return InflammationSignal(
            name="catch_up_mass",
            score=0.0,
            weight=0.15,
            evidence="no catch-up commits in window",
        )

    avg_catch_up = sum(catch_up_sizes) / len(catch_up_sizes)
    avg_normal = sum(normal_sizes) / len(normal_sizes) if normal_sizes else 10

    ratio = avg_catch_up / max(avg_normal, 1)
    score = min(100, ratio * 20)  # 5x normal = max
    evidence = (
        f"avg catch-up: {avg_catch_up:.0f} files, "
        f"avg normal: {avg_normal:.0f} files, ratio: {ratio:.1f}x"
    )

    return InflammationSignal(
        name="catch_up_mass",
        score=round(score, 1),
        weight=0.15,
        evidence=evidence,
    )


def detect_stall_frequency(
    repo_path: str, hours: float = 24
) -> InflammationSignal:
    """Check writer state for stall indicators."""
    state_files = list(Path(repo_path).glob("data/writer_state.*.json"))
    stalls = 0
    max_gap = 0

    for sf in state_files:
        try:
            data = json.loads(sf.read_text())
            gap = data.get("longest_gap_seconds", 0)
            max_gap = max(max_gap, gap)
            # A stall is a gap > 2x the expected cadence (default 15s)
            if gap > 30:
                stalls += 1
        except (json.JSONDecodeError, OSError):
            continue

    # Also check commit gaps
    log = _run(
        f'git log --since="{(datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")}" '
        f'--format="%aI" --reverse',
        cwd=repo_path,
    )
    timestamps = []
    for line in log.splitlines():
        try:
            # Parse ISO timestamp, strip timezone for simplicity
            ts_str = line.strip()[:19]
            timestamps.append(datetime.fromisoformat(ts_str))
        except ValueError:
            continue

    commit_gaps_over_30m = 0
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if delta > 1800:  # 30 minutes
            commit_gaps_over_30m += 1

    total_stalls = stalls + commit_gaps_over_30m
    score = min(100, total_stalls * 15)
    evidence = (
        f"{total_stalls} stall events, max writer gap: {max_gap}s"
    )

    return InflammationSignal(
        name="stall_frequency",
        score=round(score, 1),
        weight=0.20,
        evidence=evidence,
    )


def detect_stash_accumulation(repo_path: str) -> InflammationSignal:
    """Count accumulated stashes as deferred-work stress."""
    raw = _run("git stash list", cwd=repo_path)
    count = len([l for l in raw.splitlines() if l.strip()])

    # Score: 0 stashes = 0, 50+ = 100
    score = min(100, count * 2)
    evidence = f"{count} stash entries"

    return InflammationSignal(
        name="stash_accumulation",
        score=round(score, 1),
        weight=0.10,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# State classification
# ---------------------------------------------------------------------------

_STATES = [
    (20, "calm"),
    (40, "mild"),
    (60, "moderate"),
    (80, "severe"),
    (101, "critical"),
]


def _classify_state(score: float) -> str:
    for threshold, label in _STATES:
        if score <= threshold:
            return label
    return "critical"


def _make_recommendation(state: str, primary: str, chronic: bool) -> str:
    if state == "calm":
        return "Repository is healthy. No intervention needed."
    if state == "mild":
        return f"Minor stress detected ({primary}). Monitor and continue normal operation."
    if state == "moderate":
        if chronic:
            return (
                f"Chronic inflammation from {primary}. "
                "Consider reducing restart frequency and increasing commit cadence stability."
            )
        return f"Moderate stress from {primary}. A brief pause to consolidate may help."
    if state == "severe":
        return (
            f"Severe inflammation from {primary}. "
            "Reduce intervention frequency; let the writer stabilize before next caretaker visit."
        )
    return (
        f"Critical inflammation from {primary}. "
        "Halt non-essential operations. Focus on process stability and push reliability."
    )


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def analyze_inflammation(
    repo_path: str = ".",
    hours: float = 24.0,
) -> InflammationReport:
    """Run full inflammation analysis on the repository.

    Parameters
    ----------
    repo_path : str
        Path to the git repository.
    hours : float
        Look-back window in hours.

    Returns
    -------
    InflammationReport
    """
    repo_path = str(Path(repo_path).resolve())
    commits = _parse_git_log(repo_path, hours)

    signals = [
        detect_restart_density(commits, hours),
        detect_push_failures(repo_path, hours),
        detect_backlog_growth(repo_path),
        detect_catch_up_mass(commits, repo_path, hours),
        detect_stall_frequency(repo_path, hours),
        detect_stash_accumulation(repo_path),
    ]

    total_weight = sum(s.weight for s in signals)
    raw_score = sum(s.weighted for s in signals)
    score = round(raw_score / total_weight, 1) if total_weight else 0.0

    state = _classify_state(score)
    primary = max(signals, key=lambda s: s.score).name if signals else ""

    # Recovery hours: time since the last restart-related commit
    recovery = 0.0
    for c in reversed(commits):
        subj = c.get("subject", "")
        if re.search(r"catch-up|restart|recovery|reclamation", subj, re.IGNORECASE):
            try:
                ts = datetime.fromisoformat(c["date"][:19])
                recovery = (datetime.now() - ts).total_seconds() / 3600
            except (ValueError, KeyError):
                pass
            break

    chronic = score > 40 and len([s for s in signals if s.score > 50]) >= 3
    recommendation = _make_recommendation(state, primary, chronic)

    return InflammationReport(
        signals=signals,
        inflammation_score=score,
        inflammation_state=state,
        primary_stressor=primary,
        recovery_hours=round(recovery, 2),
        recommendation=recommendation,
        window_commits=len(commits),
        window_hours=hours,
    )


def inflammation_summary(report: InflammationReport) -> str:
    """One-line human-readable summary."""
    if report.inflammation_state == "calm":
        return f"calm: score={report.inflammation_score}, no stress signals elevated"
    chronic_tag = " (chronic)" if report.chronic else ""
    return (
        f"{report.inflammation_state}{chronic_tag}: "
        f"score={report.inflammation_score}, "
        f"primary={report.primary_stressor}, "
        f"recovery={report.recovery_hours}h ago, "
        f"{report.window_commits} commits in {report.window_hours}h"
    )


if __name__ == "__main__":
    report = analyze_inflammation()
    print(inflammation_summary(report))
    for s in report.signals:
        print(f"  {s.name}: {s.score} (w={s.weight}) — {s.evidence}")
    print(f"\nRecommendation: {report.recommendation}")
