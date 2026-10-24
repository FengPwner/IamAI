"""repo_metabolism — measure the repository's productive metabolism.

A living repository burns energy.  Some of that energy goes into
*productive work* — new strokes, tools, tests, and notes that advance
the project.  The rest is *overhead* — catch-up commits, lock cleaning,
process restarts, and monitoring infrastructure.

The metabolic metaphor
----------------------

=====================  ===================================================
concept                what it maps to
=====================  ===================================================
**basal metabolism**   overhead required just to stay alive
                       (catch-up commits, lock cleans, restarts)
**active metabolism**  productive output (new strokes, tools,
                       tests, notes, visit reports)
**metabolic rate**     total commit cycles per hour
**efficiency**         fraction of commits that carry new content
**anabolic**           building phase — adding files, features
**catabolic**          maintenance phase — cleanup, flush, recovery
=====================  ===================================================

Metrics
-------

========================  ================================================
metric                    description
========================  ================================================
``metabolic_rate``        commits per hour over the observation window
``productive_ratio``      fraction of commits classified as productive
``overhead_ratio``        fraction of commits classified as overhead
``anabolic_ratio``        fraction of commits adding new files
``efficiency_score``      0-100 composite; higher = more productive
``state``                 one of: thriving, healthy, stagnant,
                          stressed, dormant
========================  ================================================

Commit classification
---------------------

Each commit message is classified into one of:

- **productive**: contains keywords like "add", "new", "upgrade",
  "caretaker visit", "stroke", "note", "tool", "test", "feature"
- **overhead**: contains "catch-up", "lock clean", "restart",
  "recovery", "flush pending", "sync"
- **neutral**: everything else (merge commits, renames, etc.)

Edge cases
----------
- Fewer than 2 commits → empty report, score 0, state "dormant".
- All-overhead windows are classified "stressed" regardless of rate.

Usage::

    from iamai.repo_metabolism import metabolism_report, metabolism_summary

    r = metabolism_report(repo_path=".", last=50)
    print(r.efficiency_score)   # e.g. 68.5
    print(r.state)              # "healthy"
    print(metabolism_summary(r))
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Commit classification
# ---------------------------------------------------------------------------

_PRODUCTIVE_RE = re.compile(
    r"\b(add|new|upgrade|create|implement|feature|tool|test|note"
    r"|stroke|caretaker visit|refactor|improve|enhance|fix|resolve"
    r"|writer wellness|repo breath|commit hygiene|metabolism)\b",
    re.IGNORECASE,
)

_OVERHEAD_RE = re.compile(
    r"\b(catch[- ]up|lock clean|restart|recovery|flush pending"
    r"|sync|backlog|deadman|reclaim|stall|rebase)\b",
    re.IGNORECASE,
)


def classify_commit(message: str) -> str:
    """Classify a commit message as 'productive', 'overhead', or 'neutral'."""
    if _OVERHEAD_RE.search(message):
        return "overhead"
    if _PRODUCTIVE_RE.search(message):
        return "productive"
    return "neutral"


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _git_log_with_messages(repo: str | Path, last: int) -> list[dict]:
    """Return commits as dicts with hash, timestamp, message."""
    fmt = "%H%x00%at%x00%s"
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
        if len(parts) < 3:
            continue
        commits.append({
            "hash": parts[0],
            "timestamp": float(parts[1]),
            "message": parts[2],
        })
    return commits


def _files_added_per_commit(repo: str | Path, hashes: list[str]) -> dict[str, int]:
    """Return {hash: files_added} for each commit (new files only)."""
    if not hashes:
        return {}
    out = subprocess.check_output(
        ["git", "log", "--format=%H", "--diff-filter=A", "--name-only"]
        + hashes,
        cwd=str(repo),
        text=True,
    )
    result: dict[str, int] = {}
    current_hash: str | None = None
    count = 0
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) == 40 and all(c in "0123456789abcdef" for c in line):
            if current_hash is not None:
                result[current_hash] = count
            current_hash = line
            count = 0
        elif current_hash:
            count += 1
    if current_hash is not None:
        result[current_hash] = count
    return result


# ---------------------------------------------------------------------------
# Metabolism report
# ---------------------------------------------------------------------------

@dataclass
class MetabolismReport:
    """Summary of the repository's metabolic state."""

    commit_count: int = 0
    metabolic_rate: float = 0.0        # commits per hour
    productive_ratio: float = 0.0      # fraction productive
    overhead_ratio: float = 0.0        # fraction overhead
    neutral_ratio: float = 0.0         # fraction neutral
    anabolic_ratio: float = 0.0        # fraction adding new files
    efficiency_score: float = 0.0      # 0-100
    state: str = "dormant"
    window_seconds: float = 0.0
    classifications: list = field(default_factory=list)


def _compute_efficiency(
    productive_ratio: float,
    overhead_ratio: float,
    anabolic_ratio: float,
    metabolic_rate: float,
) -> float:
    """Composite efficiency score 0-100.

    Components:
    - Productive ratio: 0-40 points (direct measure of useful work)
    - Low overhead bonus: 0-25 points (less waste = more efficient)
    - Anabolic contribution: 0-20 points (building > maintaining)
    - Rate health: 0-15 points (not too fast, not too slow)
    """
    # Productive component
    prod_pts = productive_ratio * 40.0

    # Overhead penalty (inverted: low overhead = high score)
    overhead_pts = (1.0 - min(1.0, overhead_ratio / 0.6)) * 25.0

    # Anabolic bonus
    anabolic_pts = min(1.0, anabolic_ratio / 0.3) * 20.0

    # Rate health: sweet spot 4-12 commits/hour
    if metabolic_rate <= 0:
        rate_pts = 0.0
    elif metabolic_rate < 2:
        rate_pts = metabolic_rate * 3.0  # too slow
    elif metabolic_rate <= 12:
        rate_pts = 15.0  # healthy range
    else:
        rate_pts = max(0.0, 15.0 - (metabolic_rate - 12) * 0.5)

    return max(0.0, min(100.0, prod_pts + overhead_pts + anabolic_pts + rate_pts))


def _classify_state(
    efficiency: float,
    productive_ratio: float,
    overhead_ratio: float,
    metabolic_rate: float,
) -> str:
    """Classify the metabolic state."""
    if metabolic_rate <= 0:
        return "dormant"
    if efficiency >= 75:
        return "thriving"
    if efficiency >= 55:
        return "healthy"
    if overhead_ratio > 0.6:
        return "stressed"
    if metabolic_rate < 2 and productive_ratio < 0.3:
        return "stagnant"
    if efficiency < 40:
        return "stressed"
    return "stagnant"


def metabolism_report(
    repo_path: str | Path = ".",
    last: int = 50,
) -> MetabolismReport:
    """Compute the metabolism report for the repo.

    Parameters
    ----------
    repo_path : path to the git repository
    last : number of recent commits to analyse (max 200)
    """
    repo = Path(repo_path)
    last = min(last, 200)

    commits = _git_log_with_messages(repo, last)
    if len(commits) < 2:
        return MetabolismReport()

    # Work oldest-first
    commits.reverse()

    window_s = commits[-1]["timestamp"] - commits[0]["timestamp"]
    window_hours = window_s / 3600.0 if window_s > 0 else 1.0

    # Classify each commit
    classifications: list[dict] = []
    for c in commits:
        cat = classify_commit(c["message"])
        classifications.append({
            "hash": c["hash"][:8],
            "message": c["message"][:80],
            "category": cat,
        })

    total = len(classifications)
    productive_count = sum(1 for c in classifications if c["category"] == "productive")
    overhead_count = sum(1 for c in classifications if c["category"] == "overhead")
    neutral_count = total - productive_count - overhead_count

    productive_ratio = productive_count / total if total else 0.0
    overhead_ratio = overhead_count / total if total else 0.0
    neutral_ratio = neutral_count / total if total else 0.0

    # Anabolic: commits that added new files
    hashes = [c["hash"] for c in commits]
    files_added = _files_added_per_commit(repo, hashes)
    anabolic_count = sum(1 for h in hashes if files_added.get(h, 0) > 0)
    anabolic_ratio = anabolic_count / total if total else 0.0

    metabolic_rate = total / window_hours if window_hours > 0 else 0.0

    efficiency = _compute_efficiency(
        productive_ratio, overhead_ratio, anabolic_ratio, metabolic_rate
    )
    state = _classify_state(
        efficiency, productive_ratio, overhead_ratio, metabolic_rate
    )

    return MetabolismReport(
        commit_count=total,
        metabolic_rate=round(metabolic_rate, 2),
        productive_ratio=round(productive_ratio, 4),
        overhead_ratio=round(overhead_ratio, 4),
        neutral_ratio=round(neutral_ratio, 4),
        anabolic_ratio=round(anabolic_ratio, 4),
        efficiency_score=round(efficiency, 2),
        state=state,
        window_seconds=window_s,
        classifications=classifications,
    )


def metabolism_summary(report: MetabolismReport) -> str:
    """One-line human-readable summary."""
    if report.commit_count == 0:
        return "metabolism: insufficient data (< 2 commits)"
    return (
        f"metabolism {report.state} @ {report.metabolic_rate} commits/hr, "
        f"efficiency {report.efficiency_score}/100, "
        f"productive {report.productive_ratio:.0%}, "
        f"overhead {report.overhead_ratio:.0%}"
    )
