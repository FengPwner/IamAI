"""visit_efficacy — measure whether caretaker visits fix things or just repeat.

A caretaker visit is supposed to leave the repo healthier than it found
it.  But how do you know if a visit *fixed* the problem or just *cleaned
up the symptoms*?  If every third visit is "restart writer, flush pending
files," the caretaker is running a mop, not performing surgery.

This module classifies recent commits into two buckets:

- **progress** — new features, new notes, new tests, content creation
- **repair** — restarts, flushes, catch-up commits, lock cleanup, recovery

It then computes:

- **efficacy_ratio** — progress commits / total commits
- **repair_streak** — longest consecutive run of repair commits
- **repeat_repair_count** — times the same repair keyword appears in
  consecutive repair commits (cleaning the same wound twice in a row)
- **verdict** — one of ``thriving``, ``mixed``, ``maintenance``, ``stuck``

Verdict rules
-------------
- **thriving**     — efficacy_ratio ≥ 0.70 and repair_streak ≤ 2
- **mixed**        — efficacy_ratio ≥ 0.40 and repair_streak ≤ 4
- **maintenance**  — efficacy_ratio ≥ 0.20 or repair_streak ≤ 6
- **stuck**        — everything else (repair dominates, progress is rare)

Usage::

    from iamai.visit_efficacy import classify_commits, efficacy_report

    report = efficacy_report(commit_messages)
    print(report.verdict)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Classification keywords
# ---------------------------------------------------------------------------

REPAIR_KEYWORDS: list[str] = [
    "restart",
    "flush",
    "catch-up",
    "recovery",
    "lock cleanup",
    "lock_clearance",
    "stall",
    "resurrection",
    "reclaim",
    "push race",
    "sync",
    "rebase",
    "uncommitted",
    "pending",
]

PROGRESS_KEYWORDS: list[str] = [
    "add",
    "new",
    "implement",
    "create",
    "introduce",
    "feature",
    "module",
    "note",
    "tests pass",
    "caretaker visit",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CommitClassification:
    """A single commit's classification."""

    message: str
    kind: str  # "progress" | "repair" | "other"
    matched_keyword: str = ""


@dataclass
class EfficacyReport:
    """Summary of visit efficacy based on recent commit history."""

    total: int = 0
    progress_count: int = 0
    repair_count: int = 0
    other_count: int = 0
    efficacy_ratio: float = 0.0
    repair_streak: int = 0
    repeat_repair_count: int = 0
    verdict: str = "stuck"
    classifications: list[CommitClassification] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def classify_commit(message: str) -> CommitClassification:
    """Classify a single commit message as progress, repair, or other."""
    lower = message.lower()

    # Check repair first — repair keywords are more specific
    for kw in REPAIR_KEYWORDS:
        if kw in lower:
            return CommitClassification(
                message=message, kind="repair", matched_keyword=kw
            )

    for kw in PROGRESS_KEYWORDS:
        if kw in lower:
            return CommitClassification(
                message=message, kind="progress", matched_keyword=kw
            )

    return CommitClassification(message=message, kind="other")


def classify_commits(messages: Sequence[str]) -> list[CommitClassification]:
    """Classify a sequence of commit messages (newest first or oldest first)."""
    return [classify_commit(m) for m in messages]


def _compute_repair_streak(classifications: list[CommitClassification]) -> int:
    """Longest consecutive run of repair commits."""
    max_streak = 0
    current = 0
    for c in classifications:
        if c.kind == "repair":
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def _compute_repeat_repairs(classifications: list[CommitClassification]) -> int:
    """Count consecutive repair commits that share a keyword."""
    count = 0
    for i in range(1, len(classifications)):
        prev = classifications[i - 1]
        curr = classifications[i]
        if (
            prev.kind == "repair"
            and curr.kind == "repair"
            and prev.matched_keyword == curr.matched_keyword
        ):
            count += 1
    return count


def _classify_verdict(
    efficacy_ratio: float, repair_streak: int
) -> str:
    """Determine verdict from ratio and streak."""
    if efficacy_ratio >= 0.70 and repair_streak <= 2:
        return "thriving"
    if efficacy_ratio >= 0.40 and repair_streak <= 4:
        return "mixed"
    if efficacy_ratio >= 0.20 or repair_streak <= 6:
        return "maintenance"
    return "stuck"


def efficacy_report(messages: Sequence[str]) -> EfficacyReport:
    """Build a full efficacy report from commit messages."""
    if not messages:
        return EfficacyReport(verdict="stuck")

    classifications = classify_commits(messages)
    total = len(classifications)
    progress = sum(1 for c in classifications if c.kind == "progress")
    repair = sum(1 for c in classifications if c.kind == "repair")
    other = total - progress - repair
    ratio = progress / total if total > 0 else 0.0
    streak = _compute_repair_streak(classifications)
    repeats = _compute_repeat_repairs(classifications)
    verdict = _classify_verdict(ratio, streak)

    return EfficacyReport(
        total=total,
        progress_count=progress,
        repair_count=repair,
        other_count=other,
        efficacy_ratio=round(ratio, 3),
        repair_streak=streak,
        repeat_repair_count=repeats,
        verdict=verdict,
        classifications=classifications,
    )


def efficacy_summary(report: EfficacyReport) -> str:
    """One-line human-readable summary."""
    if report.total == 0:
        return "no commits to evaluate"
    pct = f"{report.efficacy_ratio:.0%}"
    return (
        f"{report.verdict}: {pct} progress "
        f"({report.progress_count}/{report.total}), "
        f"repair streak {report.repair_streak}, "
        f"{report.repeat_repair_count} repeat repairs"
    )
