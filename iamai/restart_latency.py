"""restart_latency — measure how long recovery takes after a process restart.

when a writer or batch process dies and is restarted, the critical question
is: how long before the pipeline is producing real output again?  a fast
restart with a long gap before the next commit means the system was "up"
but not yet productive — a zombie recovery.

this module pairs restart commits (those mentioning "restart" or
"process restart") with the next feature commit, then measures the
elapsed seconds between them.

latency bands
~~~~~~~~~~~~~

============  ================  ============================================
band          max seconds       meaning
============  ================  ============================================
healthy       < 300             back to work within 5 minutes
degraded      < 900             5–15 min, slow but acceptable
slow          < 1800            15–30 min, something is off
critical      < 3600            30–60 min, major recovery gap
broken        >= 3600           over an hour — restart didn't really work
============  ================  ============================================

public api
~~~~~~~~~~

- ``classify_latency(seconds)``          — band name for a given delay
- ``parse_restart_events(log_lines)``    — find restart commits in git log
- ``pair_restart_recovery(log_lines)``   — match each restart to its next feature commit
- ``latency_report(log_lines)``          — one-call convenience function
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# band thresholds (seconds)
# ---------------------------------------------------------------------------

_BANDS = [
    ("healthy",   0,    300),
    ("degraded",  300,  900),
    ("slow",      900,  1800),
    ("critical",  1800, 3600),
    ("broken",    3600, float("inf")),
]

# patterns that indicate a restart commit
_RESTART_PATTERNS = [
    re.compile(r"restart", re.IGNORECASE),
    re.compile(r"process restart", re.IGNORECASE),
    re.compile(r"caretaker visit.*restart", re.IGNORECASE),
]

# patterns that indicate a "real" feature commit (not catch-up / restart)
_CATCHUP_PATTERNS = [
    re.compile(r"^catch-up", re.IGNORECASE),
    re.compile(r"auto-commit", re.IGNORECASE),
    re.compile(r"commit pending", re.IGNORECASE),
]


def classify_latency(seconds: float) -> str:
    """Return the latency band for a given recovery time in seconds.

    >>> classify_latency(0)
    'healthy'
    >>> classify_latency(299)
    'healthy'
    >>> classify_latency(300)
    'degraded'
    >>> classify_latency(899)
    'degraded'
    >>> classify_latency(900)
    'slow'
    >>> classify_latency(1799)
    'slow'
    >>> classify_latency(1800)
    'critical'
    >>> classify_latency(3599)
    'critical'
    >>> classify_latency(3600)
    'broken'
    >>> classify_latency(99999)
    'broken'
    """
    for band, lo, hi in _BANDS:
        if lo <= seconds < hi:
            return band
    return "broken"


# ---------------------------------------------------------------------------
# git log parsing
# ---------------------------------------------------------------------------

def parse_git_log_line(line: str) -> dict[str, str] | None:
    """Parse a single git log line in --oneline --format='%h %ai %s' format.

    Expected format: ``abc1234 2026-10-27 12:00:00 +0800 some commit message``
    Returns a dict with hash, timestamp (as ISO string), and message, or None.
    """
    # match: hash(7+) space date(YYYY-MM-DD) space time(HH:MM:SS) space tz(+/-HHMM) space message
    m = re.match(
        r"^([0-9a-f]{7,})\s+"
        r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+[+-]\d{4})\s+"
        r"(.+)$",
        line.strip(),
    )
    if not m:
        return None
    return {
        "hash": m.group(1),
        "timestamp": m.group(2),
        "message": m.group(3),
    }


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse a git log timestamp string into a timezone-aware datetime."""
    return datetime.strptime(ts_str.strip(), "%Y-%m-%d %H:%M:%S %z")


def _is_restart_commit(message: str) -> bool:
    """Check if a commit message indicates a restart event."""
    return any(p.search(message) for p in _RESTART_PATTERNS)


def _is_catchup_commit(message: str) -> bool:
    """Check if a commit message is a catch-up / housekeeping commit."""
    return any(p.search(message) for p in _CATCHUP_PATTERNS)


def parse_restart_events(log_lines: list[str]) -> list[dict[str, Any]]:
    """Find all restart commits in git log output.

    Args:
        log_lines: lines from ``git log --format='%h %ai %s'``

    Returns:
        List of dicts with hash, timestamp (datetime), message, index.
        Ordered from newest to oldest (same as git log).
    """
    events = []
    for i, line in enumerate(log_lines):
        parsed = parse_git_log_line(line)
        if parsed and _is_restart_commit(parsed["message"]):
            events.append({
                "hash": parsed["hash"],
                "timestamp": _parse_timestamp(parsed["timestamp"]),
                "message": parsed["message"],
                "index": i,
            })
    return events


def pair_restart_recovery(log_lines: list[str]) -> list[dict[str, Any]]:
    """Match each restart commit to the next non-catch-up commit (its recovery).

    Walks the log (newest-first) and for each restart, looks backward through
    newer commits to find the first "real" feature commit that follows it.

    Note: git log is newest-first, so "next in time" means "earlier in the list".

    Returns:
        List of dicts: restart info + recovery info + latency_seconds + band.
        Only includes restarts that have a matching recovery commit.
    """
    # parse all commits
    commits = []
    for line in log_lines:
        parsed = parse_git_log_line(line)
        if parsed:
            commits.append({
                "hash": parsed["hash"],
                "timestamp": _parse_timestamp(parsed["timestamp"]),
                "message": parsed["message"],
            })

    if not commits:
        return []

    pairs = []
    for i, commit in enumerate(commits):
        if not _is_restart_commit(commit["message"]):
            continue
        # look for the next feature commit (newer in time = earlier in list)
        for j in range(i - 1, -1, -1):
            candidate = commits[j]
            if not _is_catchup_commit(candidate["message"]):
                latency = (candidate["timestamp"] - commit["timestamp"]).total_seconds()
                # negative latency means clock skew or data issue — skip
                if latency < 0:
                    latency = 0.0
                pairs.append({
                    "restart_hash": commit["hash"],
                    "restart_time": commit["timestamp"].isoformat(),
                    "restart_message": commit["message"],
                    "recovery_hash": candidate["hash"],
                    "recovery_time": candidate["timestamp"].isoformat(),
                    "recovery_message": candidate["message"],
                    "latency_seconds": latency,
                    "band": classify_latency(latency),
                })
                break
    return pairs


def latency_summary(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate statistics from restart-recovery pairs.

    Returns dict with:
        - count: number of matched restart-recovery pairs
        - mean_latency: average seconds
        - median_latency: median seconds
        - min_latency / max_latency
        - band_distribution: dict of band → count
        - health_score: 0–100 (100 = all healthy)
    """
    if not pairs:
        return {
            "count": 0,
            "mean_latency": 0.0,
            "median_latency": 0.0,
            "min_latency": 0.0,
            "max_latency": 0.0,
            "band_distribution": {},
            "health_score": 100.0,
        }

    latencies = sorted(p["latency_seconds"] for p in pairs)
    count = len(latencies)
    mean = sum(latencies) / count

    # median
    mid = count // 2
    if count % 2 == 0:
        median = (latencies[mid - 1] + latencies[mid]) / 2.0
    else:
        median = latencies[mid]

    # band distribution
    band_dist: dict[str, int] = {}
    for p in pairs:
        b = p["band"]
        band_dist[b] = band_dist.get(b, 0) + 1

    # health score: weighted by band quality
    _BAND_SCORES = {
        "healthy": 100,
        "degraded": 70,
        "slow": 40,
        "critical": 15,
        "broken": 0,
    }
    score_sum = sum(_BAND_SCORES.get(p["band"], 0) for p in pairs)
    health_score = score_sum / count

    return {
        "count": count,
        "mean_latency": round(mean, 1),
        "median_latency": round(median, 1),
        "min_latency": round(latencies[0], 1),
        "max_latency": round(latencies[-1], 1),
        "band_distribution": band_dist,
        "health_score": round(health_score, 1),
    }


def latency_report(log_lines: list[str]) -> dict[str, Any]:
    """One-call convenience: parse → pair → summary.

    Returns dict with 'pairs' (list of restart-recovery dicts) and
    'summary' (aggregate statistics).
    """
    pairs = pair_restart_recovery(log_lines)
    summary = latency_summary(pairs)
    return {
        "pairs": pairs,
        "summary": summary,
    }
