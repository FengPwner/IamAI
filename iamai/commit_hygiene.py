"""commit_hygiene — composite health score for the commit graph.

``commit_velocity`` tells you *speed*; ``commit_focus`` tells you
*cohesion*; ``cadence_drift`` tells you *pace accuracy*.  None of
them gives a single "how healthy is this repo's commit history right
now?" answer.  This module synthesises multiple signals into one
score.

Signals
-------
Five independent signals are combined with equal weight:

=======================  =================================================
signal                   what it measures
=======================  =================================================
``message_quality``      do commit messages follow conventions?
                         (length ≥ 8 chars, not a single generic word,
                         no ALL-CAPS shouting)
``size_health``          are commits reasonable size?
                         (not empty, not > 50 files)
``focus``                are commits cohesive?
                         (delegates to commit_focus.focus_score)
``regularity``           are commits evenly spaced?
                         (coefficient of variation of intervals)
``type_diversity``       is the commit-type mix balanced?
                         (no single category > 80 % of recent commits)
=======================  =================================================

Each signal scores 0.0 – 1.0.  The composite ``hygiene_score`` is the
unweighted mean × 100, yielding 0 – 100.

Verdicts
--------
==============  =================================================
verdict         range
==============  =================================================
``healthy``     score ≥ 75
``fair``        50 ≤ score < 75
``poor``        score < 50
==============  =================================================

Usage::

    from iamai.commit_hygiene import hygiene_report, hygiene_summary

    report = hygiene_report(repo, n=30)
    print(hygiene_summary(report))
    # "healthy (82/100) — message 0.90, size 1.00, focus 0.78, regularity 0.65, diversity 0.77"
"""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _recent_commits(repo: Path, n: int) -> list[dict]:
    """Return last *n* commits as dicts with hash, message, timestamp, files."""
    raw = _git(
        ["log", f"-{n}", "--format=%H|%s|%ct", "--no-merges"],
        repo,
    )
    if not raw:
        return []

    commits: list[dict] = []
    for line in raw.splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        h, msg, ts_str = parts
        try:
            ts = float(ts_str)
        except ValueError:
            continue

        # file count
        files_raw = _git(
            ["diff-tree", "--no-commit-id", "-r", "--name-only", h],
            repo,
        )
        files = [f for f in files_raw.splitlines() if f.strip()] if files_raw else []

        commits.append({
            "hash": h[:7],
            "message": msg,
            "timestamp": ts,
            "files": files,
        })

    return commits


# ---------------------------------------------------------------------------
# signal: message quality
# ---------------------------------------------------------------------------

# Generic single-word messages that indicate lazy commits
_GENERIC_WORDS = frozenset({
    "fix", "update", "wip", "save", "changes", "commit",
    "stuff", "work", "progress", "tmp", "temp", "test",
})


def message_score(message: str) -> float:
    """Score a single commit message for quality.

    Rules:
    - Length ≥ 8 chars → 1.0, 4-7 → 0.5, < 4 → 0.0
    - Single generic word (fix, update, wip…) → 0.0
    - ALL-CAPS message (shouting) → 0.3
    - Otherwise → 1.0
    """
    stripped = message.strip()
    if not stripped:
        return 0.0

    # length check
    length = len(stripped)
    if length < 4:
        return 0.0
    if length < 8:
        base = 0.5
    else:
        base = 1.0

    # single generic word
    lower = stripped.lower().rstrip(": .!")
    if lower in _GENERIC_WORDS:
        return 0.0

    # ALL-CAPS (only check alpha messages)
    alpha_chars = [c for c in stripped if c.isalpha()]
    if len(alpha_chars) > 5 and all(c.isupper() for c in alpha_chars):
        return 0.3

    return base


def message_quality_score(commits: list[dict]) -> float:
    """Average message quality across a set of commits."""
    if not commits:
        return 1.0
    scores = [message_score(c["message"]) for c in commits]
    return round(sum(scores) / len(scores), 4)


# ---------------------------------------------------------------------------
# signal: size health
# ---------------------------------------------------------------------------

def size_health_score(commit: dict) -> float:
    """Score a commit by its file-change count.

    - 0 files (merge or empty) → 0.8  (acceptable but not ideal)
    - 1-10 files → 1.0
    - 11-25 files → 0.7
    - 26-50 files → 0.4
    - > 50 files → 0.1
    """
    n = len(commit.get("files", []))
    if n == 0:
        return 0.8
    if n <= 10:
        return 1.0
    if n <= 25:
        return 0.7
    if n <= 50:
        return 0.4
    return 0.1


def size_health_score_batch(commits: list[dict]) -> float:
    """Average size health across a set of commits."""
    if not commits:
        return 1.0
    scores = [size_health_score(c) for c in commits]
    return round(sum(scores) / len(scores), 4)


# ---------------------------------------------------------------------------
# signal: focus (reuse commit_focus logic)
# ---------------------------------------------------------------------------

def _dirs_from_paths(files: list[str]) -> set[str]:
    """Extract parent directories from file paths."""
    dirs: set[str] = set()
    for f in files:
        parent = str(Path(f).parent)
        dirs.add(parent if parent != "." else "")
    return dirs


def _focus_score_for_commit(files: list[str]) -> float:
    """Focus score for a single commit's file list."""
    n = len(files)
    if n <= 0:
        return 1.0
    dirs = _dirs_from_paths(files)
    d = len(dirs) if dirs else 1
    return round(1.0 / (1.0 + math.log2(max(n, 1)) + math.log2(max(d, 1))), 4)


def focus_score_batch(commits: list[dict]) -> float:
    """Average focus score across a set of commits."""
    if not commits:
        return 1.0
    scores = [_focus_score_for_commit(c.get("files", [])) for c in commits]
    return round(sum(scores) / len(scores), 4)


# ---------------------------------------------------------------------------
# signal: regularity (commit interval CV)
# ---------------------------------------------------------------------------

def regularity_score(commits: list[dict]) -> float:
    """Score commit-timing regularity via coefficient of variation.

    CV < 0.3 → 1.0 (very regular)
    CV 0.3-0.7 → linear interpolation to 0.5
    CV 0.7-1.5 → linear interpolation to 0.2
    CV > 1.5 → 0.0 (very erratic)

    Fewer than 3 commits → 1.0 (not enough data, assume fine).
    """
    if len(commits) < 3:
        return 1.0

    timestamps = sorted(c["timestamp"] for c in commits)
    intervals = [
        timestamps[i + 1] - timestamps[i]
        for i in range(len(timestamps) - 1)
        if timestamps[i + 1] > timestamps[i]
    ]

    if len(intervals) < 2:
        return 1.0

    mean = sum(intervals) / len(intervals)
    if mean <= 0:
        return 1.0

    variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
    stddev = variance ** 0.5
    cv = stddev / mean

    if cv < 0.3:
        return 1.0
    if cv < 0.7:
        # linear 1.0 → 0.5 over [0.3, 0.7]
        return round(1.0 - (cv - 0.3) / 0.4 * 0.5, 4)
    if cv < 1.5:
        # linear 0.5 → 0.2 over [0.7, 1.5]
        return round(0.5 - (cv - 0.7) / 0.8 * 0.3, 4)
    return 0.0


# ---------------------------------------------------------------------------
# signal: type diversity
# ---------------------------------------------------------------------------

# Commit-type classification by message pattern
_PATTERNS = [
    ("caretaker", re.compile(r"^caretaker visit \d+", re.I)),
    ("catch-up", re.compile(r"^catch-up:", re.I)),
    ("writer_flush", re.compile(r"^writer strokes: flush", re.I)),
    ("feature", re.compile(r"^add \w+|^feat(ure)?:", re.I)),
    ("fix", re.compile(r"^fix:|^bugfix:", re.I)),
    ("docs", re.compile(r"^docs?:|^note[s:]|^update (note|doc|readme)", re.I)),
    ("test", re.compile(r"^test[s:]|^add test", re.I)),
    ("merge", re.compile(r"^merge ", re.I)),
]


def classify_commit(message: str) -> str:
    """Classify a commit message into a type category."""
    for label, pattern in _PATTERNS:
        if pattern.search(message):
            return label
    return "other"


def type_diversity_score(commits: list[dict]) -> float:
    """Score how balanced the commit-type distribution is.

    Uses a simplified evenness metric: 1 - (max_share - 1/k) / (1 - 1/k)
    where k = number of distinct types present.

    - All commits in one category → 0.0
    - Perfectly balanced → 1.0
    - Single commit → 1.0 (not enough data)
    """
    if len(commits) <= 1:
        return 1.0

    counts: dict[str, int] = {}
    for c in commits:
        t = classify_commit(c["message"])
        counts[t] = counts.get(t, 0) + 1

    k = len(counts)
    if k <= 1:
        return 0.0

    total = sum(counts.values())
    max_share = max(counts.values()) / total

    # Normalised evenness: 0 when max_share = 1, 1 when max_share = 1/k
    expected = 1.0 / k
    if max_share <= expected:
        return 1.0
    normalised = (max_share - expected) / (1.0 - expected)
    return round(max(0.0, 1.0 - normalised), 4)


# ---------------------------------------------------------------------------
# composite score
# ---------------------------------------------------------------------------

@dataclass
class HygieneReport:
    """Composite commit hygiene assessment."""
    n: int = 0
    message: float = 1.0
    size: float = 1.0
    focus: float = 1.0
    regularity: float = 1.0
    diversity: float = 1.0
    score: float = 100.0
    verdict: str = "healthy"

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "signals": {
                "message": self.message,
                "size": self.size,
                "focus": self.focus,
                "regularity": self.regularity,
                "diversity": self.diversity,
            },
            "score": self.score,
            "verdict": self.verdict,
        }


def hygiene_report(
    repo: Path | str | None = None,
    n: int = 20,
) -> HygieneReport:
    """Compute a composite hygiene score over the last *n* commits.

    Returns a HygieneReport with individual signal scores and a composite.
    """
    if repo is None:
        repo = REPO
    repo = Path(repo)

    commits = _recent_commits(repo, n)
    if not commits:
        return HygieneReport()

    msg = message_quality_score(commits)
    sz = size_health_score_batch(commits)
    foc = focus_score_batch(commits)
    reg = regularity_score(commits)
    div = type_diversity_score(commits)

    composite = round((msg + sz + foc + reg + div) / 5.0 * 100, 1)

    if composite >= 75:
        verdict = "healthy"
    elif composite >= 50:
        verdict = "fair"
    else:
        verdict = "poor"

    return HygieneReport(
        n=len(commits),
        message=msg,
        size=sz,
        focus=foc,
        regularity=reg,
        diversity=div,
        score=composite,
        verdict=verdict,
    )


def hygiene_summary(report: HygieneReport) -> str:
    """One-liner for caretaker logs."""
    if report.n == 0:
        return "no commits — cannot measure hygiene"
    return (
        f"{report.verdict} ({report.score}/100) — "
        f"message {report.message:.2f}, size {report.size:.2f}, "
        f"focus {report.focus:.2f}, regularity {report.regularity:.2f}, "
        f"diversity {report.diversity:.2f}"
    )
