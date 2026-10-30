"""commit_age — how stale are unpushed commits?

When the push pipeline breaks (SSH key rotated, network flap, force-push
protection), local commits pile up.  The *age* of the oldest unpushed
commit is a direct measure of data-loss exposure: if the disk dies,
everything older than the last successful push is gone.

Metrics
-------

``commit_age()`` returns a dict with:

- ``oldest_unpushed_seconds``: seconds since the oldest unpushed commit
- ``unpushed_count``: total number of unpushed commits
- ``risk``: one of ``"low"``, ``"moderate"``, ``"high"``, ``"critical"``

Risk tiers
==========

========  =================================================
risk      meaning
========  =================================================
low       < 1 hour of unpushed work — normal batch window
moderate  1–6 hours — push is overdue, investigate
high      6–24 hours — significant data-loss exposure
critical  > 24 hours — stop everything and fix the push
========  =================================================

Usage::

    from iamai.commit_age import commit_age, commit_age_summary

    info = commit_age()
    # {"oldest_unpushed_seconds": 3600, "unpushed_count": 12, "risk": "moderate"}

    print(commit_age_summary())
    # "12 unpushed commits, oldest 1h0m ago — moderate risk"
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Risk thresholds in seconds
TIER_MODERATE = 3600      # 1 hour
TIER_HIGH = 21600         # 6 hours
TIER_CRITICAL = 86400     # 24 hours


def _git_unpushed_shas() -> list[str]:
    """Return SHAs of commits not yet on origin/main."""
    try:
        raw = subprocess.run(
            ["git", "log", "origin/main..HEAD", "--format=%H"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        ).stdout.strip()
    except Exception:
        return []
    return [s for s in raw.splitlines() if s]


def _git_oldest_unpushed_ts(shas: list[str]) -> datetime | None:
    """Get the timestamp of the oldest unpushed commit."""
    if not shas:
        return None
    oldest_sha = shas[-1]  # git log outputs newest first
    try:
        raw = subprocess.run(
            ["git", "log", "-1", "--format=%aI", oldest_sha],
            capture_output=True, text=True, cwd=REPO_ROOT,
        ).stdout.strip()
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _classify_risk(seconds: float) -> str:
    """Classify risk based on age of oldest unpushed commit."""
    if seconds < TIER_MODERATE:
        return "low"
    if seconds < TIER_HIGH:
        return "moderate"
    if seconds < TIER_CRITICAL:
        return "high"
    return "critical"


def commit_age() -> dict[str, Any]:
    """Compute commit-age metrics for the current repo.

    Returns a dict with keys: ``oldest_unpushed_seconds``,
    ``unpushed_count``, ``risk``.  When there are no unpushed commits,
    ``oldest_unpushed_seconds`` is 0 and ``risk`` is ``"low"``.
    """
    shas = _git_unpushed_shas()
    count = len(shas)

    if count == 0:
        return {
            "oldest_unpushed_seconds": 0,
            "unpushed_count": 0,
            "risk": "low",
        }

    oldest_ts = _git_oldest_unpushed_ts(shas)
    if oldest_ts is None:
        return {
            "oldest_unpushed_seconds": -1,
            "unpushed_count": count,
            "risk": "high",  # can't determine age — assume bad
        }

    now = datetime.now(timezone.utc)
    age_seconds = (now - oldest_ts).total_seconds()
    risk = _classify_risk(age_seconds)

    return {
        "oldest_unpushed_seconds": round(age_seconds, 1),
        "unpushed_count": count,
        "risk": risk,
    }


def commit_age_summary() -> str:
    """One-line human summary of commit-age status."""
    info = commit_age()
    count = info["unpushed_count"]
    risk = info["risk"]

    if count == 0:
        return "all commits pushed — low risk"

    seconds = info["oldest_unpushed_seconds"]
    if seconds < 0:
        return f"{count} unpushed commits, age unknown — high risk"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)

    if hours > 0:
        age_str = f"{hours}h{minutes}m"
    else:
        age_str = f"{minutes}m"

    return f"{count} unpushed commits, oldest {age_str} ago — {risk} risk"
