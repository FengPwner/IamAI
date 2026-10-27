"""last_sync_age — how long since the last successful git push?

While ``commit_age`` measures the age of the oldest *unpushed* commit and
``push_exposure_index`` calculates a composite risk score, this module
answers the simpler question a human caretaker actually asks first:

    "when did this repo last successfully reach the remote?"

The answer comes from comparing the timestamp of ``origin/main`` HEAD
(the last commit known to be on the server) with the current wall clock.

Metrics
-------

``last_sync_age()`` returns a dict with:

- ``sync_age_seconds``:   seconds since origin/main HEAD was authored
- ``sync_age_human``:     human-readable string like "3d 14h 22m"
- ``local_ahead``:        how many local commits are not yet pushed
- ``last_synced_sha``:    the SHA of origin/main HEAD (short form)
- ``last_synced_ts``:     ISO-8601 timestamp of the last synced commit
- ``sync_health``:        one of ``"fresh"``, ``"stale"``, ``"cold"``,
                          ``"frozen"``

Health tiers
============

=========  =================================================
health     meaning
=========  =================================================
fresh      < 1 hour since last sync — pipeline is current
stale      1–24 hours — push lagging but not alarming
cold       1–7 days — significant sync gap, investigate
frozen     > 7 days — repo has not synced in over a week
=========  =================================================

When ``origin/main`` cannot be resolved (no remote tracking branch),
``sync_health`` is ``"frozen"`` and ``sync_age_seconds`` is -1.

Usage::

    from iamai.last_sync_age import last_sync_age, last_sync_summary

    info = last_sync_age()
    print(info["sync_age_human"])   # "3d 14h 22m"
    print(info["sync_health"])      # "cold"

    print(last_sync_summary())
    # "last sync 3d14h ago (cold) — 126 commits ahead, sha abc1234"
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Health thresholds in seconds
TIER_STALE = 3600        # 1 hour
TIER_COLD = 86400        # 1 day
TIER_FROZEN = 604800     # 7 days


def _run_git(*args: str) -> subprocess.CompletedProcess:
    """Run a git command in the repo root."""
    return subprocess.run(
        ["git"] + list(args),
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


def _origin_head_sha() -> str | None:
    """Get the short SHA of origin/main HEAD, or None."""
    result = _run_git("rev-parse", "--short", "origin/main")
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha if sha else None


def _origin_head_ts(sha: str) -> datetime | None:
    """Get the author timestamp of a commit."""
    result = _run_git("log", "-1", "--format=%aI", sha)
    if result.returncode != 0:
        return None
    try:
        return datetime.fromisoformat(result.stdout.strip())
    except (ValueError, TypeError):
        return None


def _local_ahead_count() -> int:
    """Count how many local commits are not on origin/main."""
    result = _run_git("rev-list", "--count", "origin/main..HEAD")
    if result.returncode != 0:
        return -1
    try:
        return int(result.stdout.strip())
    except ValueError:
        return -1


def _format_age(seconds: float) -> str:
    """Format seconds as a human-readable duration."""
    if seconds < 0:
        return "unknown"

    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")

    return " ".join(parts) if parts else "0m"


def _classify_health(seconds: float) -> str:
    """Classify sync health from age in seconds."""
    if seconds < 0:
        return "frozen"
    if seconds < TIER_STALE:
        return "fresh"
    if seconds < TIER_COLD:
        return "stale"
    if seconds < TIER_FROZEN:
        return "cold"
    return "frozen"


def last_sync_age() -> dict[str, Any]:
    """Compute last-sync-age metrics for the current repo.

    Returns a dict with keys: ``sync_age_seconds``, ``sync_age_human``,
    ``local_ahead``, ``last_synced_sha``, ``last_synced_ts``,
    ``sync_health``.
    """
    sha = _origin_head_sha()
    if sha is None:
        return {
            "sync_age_seconds": -1,
            "sync_age_human": "unknown",
            "local_ahead": _local_ahead_count(),
            "last_synced_sha": None,
            "last_synced_ts": None,
            "sync_health": "frozen",
        }

    ts = _origin_head_ts(sha)
    if ts is None:
        return {
            "sync_age_seconds": -1,
            "sync_age_human": "unknown",
            "local_ahead": _local_ahead_count(),
            "last_synced_sha": sha,
            "last_synced_ts": None,
            "sync_health": "frozen",
        }

    now = datetime.now(timezone.utc)
    age_seconds = (now - ts).total_seconds()
    health = _classify_health(age_seconds)

    return {
        "sync_age_seconds": round(age_seconds, 1),
        "sync_age_human": _format_age(age_seconds),
        "local_ahead": _local_ahead_count(),
        "last_synced_sha": sha,
        "last_synced_ts": ts.isoformat(),
        "sync_health": health,
    }


def last_sync_summary() -> str:
    """One-line human summary of last-sync status."""
    info = last_sync_age()
    health = info["sync_health"]
    ahead = info["local_ahead"]
    sha = info["last_synced_sha"] or "none"

    if info["sync_age_seconds"] < 0:
        age_str = "unknown"
    else:
        # compact format for summary
        seconds = info["sync_age_seconds"]
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        if days > 0:
            age_str = f"{days}d{hours}h"
        else:
            minutes = int((seconds % 3600) // 60)
            age_str = f"{hours}h{minutes}m" if hours > 0 else f"{minutes}m"

    ahead_str = f"{ahead} commits ahead" if ahead >= 0 else "ahead-count unknown"

    return (
        f"last sync {age_str} ago ({health}) "
        f"— {ahead_str}, sha {sha}"
    )
