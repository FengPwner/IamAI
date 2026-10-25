"""Commit intent classifier — categorise commits by purpose.

Every commit message carries a signal about *what kind of work* was done.
This module classifies recent commits into intent categories so that a
caretaker can answer: "is the repo spending all its time on maintenance
and none on new content?"

Categories
----------

``content``   New strokes, notes, garden entries, docs prose.
``tooling``   Scripts, tools, CI, automation plumbing.
``fix``       Bug fixes, corrections, typo patches.
``refactor``  Restructuring without behaviour change.
``meta``      Catch-up commits, merge commits, version bumps, README edits.

Each commit is assigned exactly one category.  When no pattern matches,
the commit falls into ``meta`` (the residual bin).

Usage::

    from iamai.commit_intent import classify_commits, focus_verdict

    messages = [
        "add stall cluster detector",
        "fix off-by-one in gap classifier",
        "refactor caretaker yield into own module",
        "catch-up: commit pending changes",
        "new note on afternoon reclamation",
    ]
    report = classify_commits(messages)
    print(report)
    # {"content": 2, "tooling": 0, "fix": 1, "refactor": 1, "meta": 1,
    #  "total": 5, "dominant": "content", "focus_score": 0.4}

    verdict = focus_verdict(report)
    # "balanced" | "narrow" | "fixation"

Design
------
- Pure function: takes a list of strings, returns a dict.
- Case-insensitive keyword matching with ordered priority (fix before
  refactor before tooling before content before meta).
- ``focus_score`` = max_category_count / total; 1.0 means all commits
  are in one bucket.
- Thresholds: focus_score < 0.5 → balanced; 0.5–0.75 → narrow;
  > 0.75 → fixation.
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence


# ---------------------------------------------------------------------------
# Keyword patterns (order matters — first match wins)
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("fix", re.compile(
        r"\b(fix|fixed|fixing|bugfix|correct|corrected|patch|hotfix"
        r"|repair|resolve|resolved)\b",
        re.IGNORECASE,
    )),
    ("refactor", re.compile(
        r"\b(refactor|refactored|refactoring|restructure|reorganise"
        r"|reorganize|rename|split|extract|move|inline|clean\s*up"
        r"|cleanup)\b",
        re.IGNORECASE,
    )),
    ("tooling", re.compile(
        r"\b(tool|tools|script|scripts|ci|workflow|makefile|docker"
        r"|lint|format|test|tests|pytest|github|action|cron|bot"
        r"|monitor|daemon|loop|batch|committer|writer_loop)\b",
        re.IGNORECASE,
    )),
    ("content", re.compile(
        r"\b(note|notes|garden|stroke|snippet|thought|devlog|doc|docs"
        r"|readme|guide|tutorial|essay|post|article|story|prose"
        r"|chapter|page|entry|add\s+note|new\s+note|writing)\b",
        re.IGNORECASE,
    )),
]

_META_PATTERNS = re.compile(
    r"\b(catch[- ]?up|merge|merge\s+branch|version\s+bump|bump"
    r"|initial\s+commit|chore|maintenance|housekeeping|wip"
    r"|work\s+in\s+progress|auto[- ]?commit|scheduled)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def classify_commit(message: str) -> str:
    """Return the intent category for a single commit message.

    Args:
        message: the commit subject line.

    Returns:
        One of ``"fix"``, ``"refactor"``, ``"tooling"``, ``"content"``,
        or ``"meta"``.
    """
    for category, pattern in _PATTERNS:
        if pattern.search(message):
            return category
    if _META_PATTERNS.search(message):
        return "meta"
    return "meta"


def classify_commits(messages: Sequence[str]) -> Dict[str, object]:
    """Classify a batch of commit messages and return a summary report.

    Args:
        messages: commit subject lines (newest-first or oldest-first,
            order is preserved but does not affect classification).

    Returns:
        A dict with keys ``content``, ``tooling``, ``fix``, ``refactor``,
        ``meta``, ``total``, ``dominant``, ``focus_score``, and
        ``breakdown`` (list of per-commit ``(message, category)`` pairs).
    """
    counts: dict[str, int] = {
        "content": 0,
        "tooling": 0,
        "fix": 0,
        "refactor": 0,
        "meta": 0,
    }
    breakdown: list[tuple[str, str]] = []

    for msg in messages:
        cat = classify_commit(msg)
        counts[cat] += 1
        breakdown.append((msg, cat))

    total = len(messages)
    dominant = max(counts, key=lambda k: counts[k]) if total > 0 else "meta"
    focus_score = counts[dominant] / total if total > 0 else 0.0

    return {
        **counts,
        "total": total,
        "dominant": dominant,
        "focus_score": round(focus_score, 3),
        "breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

BALANCED_THRESHOLD = 0.5
NARROW_THRESHOLD = 0.75


def focus_verdict(report: Dict[str, object]) -> str:
    """Classify the repo's attention distribution.

    Args:
        report: output of :func:`classify_commits`.

    Returns:
        ``"balanced"`` — no category dominates (focus_score < 0.5).
        ``"narrow"`` — one category leads but others are present.
        ``"fixation"`` — almost all commits are in one category.
    """
    score = float(report.get("focus_score", 0.0))
    if score < BALANCED_THRESHOLD:
        return "balanced"
    if score < NARROW_THRESHOLD:
        return "narrow"
    return "fixation"


def focus_summary(report: Dict[str, object]) -> str:
    """One-liner for caretaker logs.

    Args:
        report: output of :func:`classify_commits`.

    Returns:
        Human-readable summary string.
    """
    verdict = focus_verdict(report)
    dominant = report.get("dominant", "meta")
    score = report.get("focus_score", 0.0)
    total = report.get("total", 0)
    return (
        f"{verdict} (focus={score:.2f}, dominant={dominant}, "
        f"{total} commits)"
    )
