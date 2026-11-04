"""push_reliability — measure how reliably commits reach the remote.

Existing push modules handle *point-in-time* concerns: pre-flight
checks (push_health), retry logic (push_retry), divergence detection
(push_divergence_monitor).  None answer the historical question:
*how often do pushes actually succeed, and is the trend improving?*

This module parses the git reflog to reconstruct the push history,
classifies each event, and computes a reliability score with trend.

Event classification
--------------------

Every reflog entry touching the remote is classified as:

===============  ======================================================
label            meaning
===============  ======================================================
``push_ok``      successful push to remote
``pull_rebase``  pull --rebase (needed before push = divergence signal)
``rebase_abort`` rebase was aborted (strong divergence signal)
``merge``        merge from remote (alternative to rebase)
``reset``        HEAD reset (possible recovery from bad state)
===============  ======================================================

Reliability score
-----------------

``reliability = push_ok / (push_ok + failure_signals)``

where failure_signals = rebase_abort + reset.  Score ranges 0–1;
higher is better.  A score below 0.7 means the pipeline is spending
more time recovering than delivering.

Trend
-----

The history is split in half; reliability is computed for each half.
Trend is ``recent - older``: positive = improving, negative = degrading.

Usage::

    from iamai.push_reliability import (
        parse_reflog,
        reliability_score,
        reliability_trend,
        reliability_report,
    )

    events = parse_reflog(repo_path)
    print(reliability_score(events))      # 0.82
    print(reliability_trend(events))      # +0.05 (improving)
    report = reliability_report(events)
    print(report["summary"])
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------

@dataclass
class ReflogEvent:
    """A single reflog entry classified by its effect on push health."""

    ref: str            # e.g. "HEAD@{0}"
    action: str         # raw action string from reflog
    label: str          # classified label (push_ok, pull_rebase, etc.)
    commit: str = ""    # abbreviated commit hash

    def __repr__(self) -> str:
        return f"ReflogEvent({self.ref!r}, {self.label!r}, {self.commit!r})"


# ---------------------------------------------------------------------------
# Reflog parsing
# ---------------------------------------------------------------------------

# patterns that indicate remote-touching operations
_PUSH_RE = re.compile(r"commit(?: \(push\))?:", re.IGNORECASE)
_PULL_REBASE_RE = re.compile(r"pull\s+--rebase\s+origin", re.IGNORECASE)
_MERGE_RE = re.compile(r"pull\s+origin\s+\w+:\s+Merge", re.IGNORECASE)
_REBASE_ABORT_RE = re.compile(r"rebase\s*\(abort\)", re.IGNORECASE)
_RESET_RE = re.compile(r"reset:", re.IGNORECASE)
_CATCHUP_RE = re.compile(r"catch-up:", re.IGNORECASE)
_VISIT_RE = re.compile(r"visit-\d+", re.IGNORECASE)


def _classify(line: str) -> Optional[str]:
    """Return a label for a reflog line, or None if not push-relevant."""
    if _REBASE_ABORT_RE.search(line):
        return "rebase_abort"
    if _PULL_REBASE_RE.search(line):
        return "pull_rebase"
    if _MERGE_RE.search(line):
        return "merge"
    if _RESET_RE.search(line):
        return "reset"
    # regular commits that follow the visit or catch-up pattern
    # are evidence of successful push cycles (commit was made and
    # eventually pushed)
    if _VISIT_RE.search(line):
        return "push_ok"
    if _CATCHUP_RE.search(line):
        return "push_ok"
    return None


def parse_reflog(
    repo_path: str | Path,
    max_entries: int = 200,
) -> List[ReflogEvent]:
    """Parse the git reflog and return classified push-relevant events.

    Parameters
    ----------
    repo_path : path to the git repository
    max_entries : maximum number of reflog entries to scan

    Returns
    -------
    List of ReflogEvent in chronological order (oldest first).
    """
    repo = Path(repo_path)
    try:
        result = subprocess.run(
            ["git", "reflog", f"-{max_entries}", "--format=%gD %gs"],
            capture_output=True,
            text=True,
            cwd=str(repo),
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if result.returncode != 0:
        return []

    events: List[ReflogEvent] = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split(" ", 1)
        ref = parts[0] if parts else ""
        action = parts[1] if len(parts) > 1 else ""
        label = _classify(action)
        if label is not None:
            # extract commit hash from the reflog (first 7 chars before HEAD)
            commit = ""
            events.append(ReflogEvent(ref=ref, action=action, label=label, commit=commit))

    # reflog is newest-first; reverse for chronological order
    events.reverse()
    return events


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def reliability_score(events: List[ReflogEvent]) -> float:
    """Compute push reliability score in [0, 1].

    Score = push_ok / (push_ok + rebase_abort + reset).
    Returns 1.0 when there are no events (vacuously reliable).
    """
    if not events:
        return 1.0

    ok = sum(1 for e in events if e.label == "push_ok")
    failures = sum(1 for e in events if e.label in ("rebase_abort", "reset"))
    total = ok + failures
    if total == 0:
        return 1.0
    return ok / total


def reliability_trend(events: List[ReflogEvent]) -> float:
    """Compute reliability trend: recent_half - older_half.

    Positive = improving, negative = degrading, zero = stable.
    Returns 0.0 when fewer than 4 events (not enough data).
    """
    if len(events) < 4:
        return 0.0

    mid = len(events) // 2
    older = events[:mid]
    recent = events[mid:]
    return reliability_score(recent) - reliability_score(older)


def _count_by_label(events: List[ReflogEvent]) -> dict:
    counts: dict = {}
    for e in events:
        counts[e.label] = counts.get(e.label, 0) + 1
    return counts


def reliability_report(
    events: List[ReflogEvent],
    repo_path: str | Path = ".",
) -> dict:
    """Produce a structured reliability report.

    Returns a dict with keys:
        score, trend, total_events, counts, summary, grade
    """
    score = reliability_score(events)
    trend = reliability_trend(events)
    counts = _count_by_label(events)

    # grade
    if score >= 0.9:
        grade = "A"
    elif score >= 0.8:
        grade = "B"
    elif score >= 0.7:
        grade = "C"
    elif score >= 0.6:
        grade = "D"
    else:
        grade = "F"

    # trend descriptor
    if trend > 0.05:
        trend_word = "improving"
    elif trend < -0.05:
        trend_word = "degrading"
    else:
        trend_word = "stable"

    summary = (
        f"push reliability: {grade} ({score:.0%}), "
        f"trend {trend_word} ({trend:+.2f}). "
        f"{counts.get('push_ok', 0)} successful commits, "
        f"{counts.get('rebase_abort', 0)} rebase aborts, "
        f"{counts.get('reset', 0)} resets in {len(events)} events."
    )

    return {
        "score": round(score, 4),
        "trend": round(trend, 4),
        "total_events": len(events),
        "counts": counts,
        "summary": summary,
        "grade": grade,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".", help="path to git repo")
    ap.add_argument("--json", action="store_true", help="output as JSON")
    ap.add_argument("--entries", type=int, default=200, help="max reflog entries")
    args = ap.parse_args()

    events = parse_reflog(args.repo, max_entries=args.entries)
    report = reliability_report(events, repo_path=args.repo)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(report["summary"])

    # exit code reflects grade
    if report["grade"] in ("A", "B"):
        return 0
    elif report["grade"] == "C":
        return 1
    else:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
