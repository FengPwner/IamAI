"""Repo pulse — a single health verdict from multiple signals.

``stroke_freshness`` tells you how recent the last stroke is.
``stall_classifier`` tells you if the writer is dead.
Neither tells you at a glance whether the *whole repo* is healthy.

This module combines three signals into one pulse:

1. **stroke freshness** — is the writer producing content?
2. **git cleanness** — are there uncommitted changes piling up?
3. **commit recency** — has anything been committed recently?

The result is a single verdict:

==========  ====================================================
verdict     meaning
==========  ====================================================
``alive``   all signals green
``limping`` one signal degraded
``stalled`` two or more signals degraded
``dead``    no recent activity at all
==========  ====================================================

Usage::

    from iamai.repo_pulse import pulse, pulse_report

    info = pulse(repo, cadence_seconds=15)
    print(info["verdict"])     # "alive"
    print(info["signals"])     # {"freshness": "fresh", "git": "clean", "commit": "recent"}

    print(pulse_report(repo))
    # "alive — fresh strokes, clean tree, recent commit"
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .stroke_freshness import freshness


# ---------------------------------------------------------------------------
# signal thresholds
# ---------------------------------------------------------------------------

_PENDING_WARN = 3        # files uncommitted before we flag
_PENDING_BAD = 8         # definitely unhealthy
_COMMIT_AGE_WARN = 1800  # 30 min
_COMMIT_AGE_BAD = 7200   # 2 h


# ---------------------------------------------------------------------------
# individual signals
# ---------------------------------------------------------------------------

def _git_pending(repo: Path) -> int:
    """Count files with uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return -1  # not a git repo
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        return len(lines)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return -1


def _last_commit_age(repo: Path, now: datetime) -> float:
    """Seconds since the most recent commit, or inf if unavailable."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%aI"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return float("inf")
        ts = datetime.fromisoformat(result.stdout.strip())
        return (now - ts).total_seconds()
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return float("inf")


def _classify_git(pending: int) -> str:
    if pending < 0:
        return "unknown"
    if pending <= _PENDING_WARN:
        return "clean"
    if pending <= _PENDING_BAD:
        return "dirty"
    return "backlog"


def _classify_commit(age_seconds: float) -> str:
    if age_seconds == float("inf"):
        return "none"
    if age_seconds < _COMMIT_AGE_WARN:
        return "recent"
    if age_seconds < _COMMIT_AGE_BAD:
        return "aging"
    return "stale"


# ---------------------------------------------------------------------------
# composite pulse
# ---------------------------------------------------------------------------

_VERDICTS = ["alive", "limping", "stalled", "dead"]


def pulse(
    repo: Path,
    cadence_seconds: float = 15.0,
    now: datetime | None = None,
) -> dict:
    """Return a composite health pulse for the repo.

    Parameters
    ----------
    repo:
        Repository root.
    cadence_seconds:
        Expected stroke interval (default 15 s).
    now:
        Override clock (defaults to ``datetime.now(timezone.utc)``).

    Returns
    -------
    dict with keys: ``verdict``, ``signals`` (dict), ``score`` (0–3),
    ``details`` (dict with raw values).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # signal 1: stroke freshness
    fresh_info = freshness(repo, cadence_seconds=cadence_seconds, now=now)
    fresh_verdict = fresh_info["verdict"]

    # signal 2: git cleanliness
    pending = _git_pending(repo)
    git_verdict = _classify_git(pending)

    # signal 3: commit recency
    commit_age = _last_commit_age(repo, now)
    commit_verdict = _classify_commit(commit_age)

    signals = {
        "freshness": fresh_verdict,
        "git": git_verdict,
        "commit": commit_verdict,
    }

    # count degraded signals
    degraded = 0
    if fresh_verdict in ("stale", "dead"):
        degraded += 1
    elif fresh_verdict == "warm":
        degraded += 0.5
    if git_verdict in ("backlog", "unknown"):
        degraded += 1
    elif git_verdict == "dirty":
        degraded += 0.5
    if commit_verdict in ("stale", "none"):
        degraded += 1
    elif commit_verdict == "aging":
        degraded += 0.5

    score = max(0, 3 - degraded)
    idx = min(int(3 - score), 3)
    verdict = _VERDICTS[idx]

    return {
        "verdict": verdict,
        "signals": signals,
        "score": round(score, 1),
        "details": {
            "pending_files": pending,
            "commit_age_seconds": round(commit_age, 1) if commit_age != float("inf") else None,
            "stroke_age_seconds": round(fresh_info["age_seconds"], 1) if fresh_info["age_seconds"] != float("inf") else None,
            "cadence_seconds": cadence_seconds,
        },
    }


def pulse_report(
    repo: Path,
    cadence_seconds: float = 15.0,
    now: datetime | None = None,
) -> str:
    """One-line human-readable pulse summary.

    Example: ``"alive — fresh strokes, clean tree, recent commit"``
    """
    info = pulse(repo, cadence_seconds=cadence_seconds, now=now)
    parts = []

    f = info["signals"]["freshness"]
    parts.append({
        "fresh": "fresh strokes", "warm": "slow strokes",
        "stale": "stale strokes", "dead": "no strokes",
    }.get(f, f"{f} strokes"))

    g = info["signals"]["git"]
    parts.append({
        "clean": "clean tree", "dirty": "dirty tree",
        "backlog": "commit backlog", "unknown": "git unknown",
    }.get(g, g))

    c = info["signals"]["commit"]
    parts.append({
        "recent": "recent commit", "aging": "aging commits",
        "stale": "stale commits", "none": "no commits",
    }.get(c, c))

    return f"{info['verdict']} — {', '.join(parts)}"
