"""repo_circulation — measure how content circulates through the repo.

A living repository is not just a pile of commits; it is a *circulatory
system*.  Content flows through different categories — devlog entries,
garden notes, thoughts, metrics, code snippets, and reading notes — and
the health of the repo depends on whether all categories are being fed
regularly or whether some are starving while others bloat.

The circulation metaphor
------------------------

=====================  ===================================================
concept                what it maps to
=====================  ===================================================
**organ**              a content category (devlog, garden, note, thought,
                       metrics, snippet)
**blood flow**         commits that touch files in a given category
**ischemia**           a category that has not received new content for
                       longer than its expected refresh interval
**hypertrophy**        a category growing disproportionately fast
                       relative to the others
**pulse**              the most recent commit touching a category
=====================  ===================================================

Metrics
-------

========================  ================================================
metric                    description
========================  ================================================
``category_age``          seconds since last commit per category
``category_freshness``    0-100 freshness score per category
``starving_categories``   list of categories in ischemia
``bloated_categories``    list of categories with hypertrophy
``circulation_score``     0-100 composite; higher = better balanced
``state``                 one of: vibrant, balanced, uneven,
                          stagnant, critical
========================  ================================================

Category mapping
----------------

Files are mapped to categories by directory or naming convention:

- ``docs/DEVLOG.md`` → devlog
- ``docs/GARDEN.md`` → garden
- ``notes/*.md`` → note
- ``docs/THOUGHTS.md`` or ``snippets/*`` → thought / snippet
- ``docs/METRICS.md`` → metrics
- everything else → code

Edge cases
----------
- Fewer than 5 commits analysed → report is "insufficient_data".
- A category with zero files is excluded from scoring.

Usage::

    from iamai.repo_circulation import circulation_report, circulation_summary

    r = circulation_report(repo_path=".", last=100)
    print(r.circulation_score)   # e.g. 72.0
    print(r.state)               # "balanced"
    print(r.starving_categories) # ["snippet"]
    print(circulation_summary(r))
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

_CATEGORY_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"docs/DEVLOG\.md$"), "devlog"),
    (re.compile(r"docs/GARDEN\.md$"), "garden"),
    (re.compile(r"docs/METRICS\.md$"), "metrics"),
    (re.compile(r"docs/THOUGHTS\.md$"), "thought"),
    (re.compile(r"^notes/"), "note"),
    (re.compile(r"^snippets/"), "snippet"),
]

ALL_CATEGORIES = ("devlog", "garden", "note", "thought", "metrics", "snippet")

# Expected max age in seconds before a category is considered "starving".
# These defaults assume a 10-minute commit cadence with 6 categories —
# each category should see activity roughly every 60 minutes.
_DEFAULT_MAX_AGE: Dict[str, int] = {
    "devlog": 3600,
    "garden": 3600,
    "note": 3600,
    "thought": 3600,
    "metrics": 3600,
    "snippet": 3600,
}


def classify_file(filepath: str) -> str:
    """Return the content category for a file path."""
    for pattern, category in _CATEGORY_RULES:
        if pattern.search(filepath):
            return category
    return "code"


def classify_files(filepaths: List[str]) -> Dict[str, int]:
    """Count files per category."""
    counts: Dict[str, int] = {}
    for fp in filepaths:
        cat = classify_file(fp)
        if cat != "code":
            counts[cat] = counts.get(cat, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git_log_files(repo_path: str, last: int = 100) -> List[Tuple[int, List[str]]]:
    """Return (timestamp, [files]) for the last N commits."""
    cmd = [
        "git", "-C", repo_path, "log",
        f"-{last}",
        "--format=%ct",
        "--name-only",
        "--diff-filter=ACMR",
    ]
    try:
        raw = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    entries: List[Tuple[int, List[str]]] = []
    current_ts = 0
    current_files: List[str] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.isdigit() and len(line) >= 10:
            if current_files:
                entries.append((current_ts, current_files))
            current_ts = int(line)
            current_files = []
        else:
            current_files.append(line)
    if current_files:
        entries.append((current_ts, current_files))
    return entries


def _category_last_seen(
    entries: List[Tuple[int, List[str]]],
    now: Optional[int] = None,
) -> Dict[str, int]:
    """Return seconds since last commit per category.

    ``now`` defaults to the timestamp of the most recent entry
    (or 0 if no entries exist).
    """
    if not entries:
        return {}
    if now is None:
        now = entries[0][0] if entries else 0

    last_seen: Dict[str, int] = {}
    for ts, files in entries:
        for fp in files:
            cat = classify_file(fp)
            if cat != "code" and cat not in last_seen:
                last_seen[cat] = now - ts
    return last_seen


def _category_commit_count(
    entries: List[Tuple[int, List[str]]],
) -> Dict[str, int]:
    """Count how many commits touched each category."""
    counts: Dict[str, int] = {}
    for _ts, files in entries:
        seen_cats = set()
        for fp in files:
            cat = classify_file(fp)
            if cat != "code":
                seen_cats.add(cat)
        for cat in seen_cats:
            counts[cat] = counts.get(cat, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _freshness_score(age_seconds: int, max_age: int) -> float:
    """0-100 freshness score; 100 = just committed, 0 = way past max_age."""
    if age_seconds <= 0:
        return 100.0
    ratio = age_seconds / max_age
    if ratio >= 2.0:
        return 0.0
    return max(0.0, 100.0 * (1.0 - ratio / 2.0))


def _compute_circulation_score(
    category_age: Dict[str, int],
    max_ages: Dict[str, int],
) -> float:
    """Weighted mean freshness across active categories."""
    active = [c for c in category_age if c in max_ages]
    if not active:
        return 0.0
    scores = [_freshness_score(category_age[c], max_ages.get(c, 3600)) for c in active]
    return round(sum(scores) / len(scores), 1)


def _detect_starving(
    category_age: Dict[str, int],
    max_ages: Dict[str, int],
) -> List[str]:
    """Categories whose age exceeds their max_age threshold."""
    return sorted(
        c for c, age in category_age.items()
        if age > max_ages.get(c, 3600)
    )


def _detect_bloated(
    commit_counts: Dict[str, int],
    total_commits: int,
    expected_share: float = 0.35,
) -> List[str]:
    """Categories receiving more than ``expected_share`` of commits."""
    if total_commits == 0:
        return []
    return sorted(
        c for c, cnt in commit_counts.items()
        if cnt / total_commits > expected_share
    )


def _classify_state(
    score: float,
    starving: List[str],
    bloated: List[str],
    n_categories: int,
) -> str:
    """Classify overall circulation state."""
    if n_categories == 0:
        return "insufficient_data"
    if score >= 80:
        return "vibrant"
    if score >= 60:
        if not starving:
            return "balanced"
        return "uneven"
    if score >= 40:
        if len(starving) >= n_categories // 2:
            return "stagnant"
        return "uneven"
    return "critical"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class CirculationReport:
    """Complete circulation health report."""

    category_age: Dict[str, int] = field(default_factory=dict)
    category_freshness: Dict[str, float] = field(default_factory=dict)
    category_commits: Dict[str, int] = field(default_factory=dict)
    starving_categories: List[str] = field(default_factory=list)
    bloated_categories: List[str] = field(default_factory=list)
    circulation_score: float = 0.0
    state: str = "insufficient_data"
    commits_analysed: int = 0
    active_categories: int = 0


def circulation_report(
    repo_path: str = ".",
    last: int = 100,
    max_ages: Optional[Dict[str, int]] = None,
    now: Optional[int] = None,
) -> CirculationReport:
    """Analyse content circulation across the repository.

    Parameters
    ----------
    repo_path:
        Path to the git repository.
    last:
        Number of recent commits to analyse.
    max_ages:
        Per-category maximum age in seconds before starvation.
        Defaults to ``_DEFAULT_MAX_AGE``.
    now:
        Override "current time" (epoch seconds) for testing.

    Returns
    -------
    CirculationReport with all metrics populated.
    """
    ages = max_ages or _DEFAULT_MAX_AGE
    entries = _git_log_files(repo_path, last)
    report = CirculationReport(commits_analysed=len(entries))

    if len(entries) < 5:
        return report

    cat_age = _category_last_seen(entries, now=now)
    cat_counts = _category_commit_count(entries)
    total_cat_commits = sum(cat_counts.values())

    freshness = {}
    for cat, age in cat_age.items():
        freshness[cat] = round(_freshness_score(age, ages.get(cat, 3600)), 1)

    starving = _detect_starving(cat_age, ages)
    bloated = _detect_bloated(cat_counts, total_cat_commits)
    score = _compute_circulation_score(cat_age, ages)
    state = _classify_state(score, starving, bloated, len(cat_age))

    report.category_age = cat_age
    report.category_freshness = freshness
    report.category_commits = cat_counts
    report.starving_categories = starving
    report.bloated_categories = bloated
    report.circulation_score = score
    report.state = state
    report.active_categories = len(cat_age)

    return report


def circulation_summary(report: CirculationReport) -> str:
    """Human-readable one-liner summary."""
    if report.state == "insufficient_data":
        return "insufficient data — fewer than 5 commits analysed"

    parts = [f"circulation {report.circulation_score}/100 ({report.state})"]

    if report.starving_categories:
        parts.append(f"starving: {', '.join(report.starving_categories)}")
    if report.bloated_categories:
        parts.append(f"bloated: {', '.join(report.bloated_categories)}")

    fresh = sorted(report.category_freshness.items(), key=lambda x: x[1])
    if fresh:
        driest = fresh[0]
        parts.append(f"driest organ: {driest[0]} ({driest[1]:.0f}%)")

    return " | ".join(parts)
