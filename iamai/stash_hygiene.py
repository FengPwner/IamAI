"""Stash hygiene checker: detect and classify stash accumulation.

A git stash is meant to be temporary — a short-lived holding area for
uncommitted work during a rebase or context switch. When stash entries
accumulate (dozens or hundreds), they become a maintenance burden:

- Each entry is uncommitted work that was never finished or reviewed.
- Old stash entries reference old tree states; popping them can conflict.
- A large stash list signals broken workflow (work started, never landed).

This module parses ``git stash list`` output and classifies the health
of the stash into four levels:

    clean    — 0-2 entries, nothing to worry about
    mild     — 3-10 entries, consider reviewing
    moderate — 11-30 entries, active accumulation, cleanup recommended
    critical — 31+ entries, stash is a graveyard

It also classifies individual entries by type (autostash, WIP, named)
so you can bulk-drop the uninteresting ones.

Usage::

    from iamai.stash_hygiene import analyze_stash

    lines = subprocess.check_output(["git", "stash", "list"]).decode().splitlines()
    report = analyze_stash(lines)
    print(report["count"])      # 95
    print(report["verdict"])    # "critical"
    print(report["autostash"])  # 12
    print(report["wip"])        # 78
    print(report["named"])      # 5

Why this matters for an automated repo:
    The caretaker stashes before pulling, but if the pull+push cycle fails
    mid-flight, the stash is never popped. Over hundreds of caretaker visits,
    these orphaned stash entries pile up. This module makes that visible.
"""

from __future__ import annotations

from typing import Sequence


def classify_entry(line: str) -> str:
    """Classify a single stash list line by type.

    Returns one of: "autostash", "wip", "named".

    Examples::

        stash@{0}: WIP on main: abc1234 some commit message  → "wip"
        stash@{5}: On main: pre-rebase stash                  → "named"
        stash@{3}: autostash                                   → "autostash"
    """
    stripped = line.strip()
    if not stripped:
        return "unknown"
    # autostash entries have no colon-separated message after the ref
    if stripped.endswith(": autostash") or stripped == "autostash":
        return "autostash"
    # "WIP on" is the default git stash message
    if ": WIP on " in stripped:
        return "wip"
    # "On branch:" with a custom message (not WIP)
    if ": On " in stripped:
        return "named"
    return "wip"  # default fallback


def count_entries(lines: Sequence[str]) -> int:
    """Count non-empty stash list lines."""
    return sum(1 for line in lines if line.strip())


def analyze_stash(lines: Sequence[str]) -> dict:
    """Analyze stash list and return a health report.

    Parameters
    ----------
    lines : sequence of str
        Raw lines from ``git stash list``.

    Returns
    -------
    dict with keys:
        count     — total stash entries
        autostash — count of autostash entries
        wip       — count of WIP entries
        named     — count of named (custom message) entries
        verdict   — "clean" | "mild" | "moderate" | "critical"
        recommend — suggested action string
    """
    counts = {"autostash": 0, "wip": 0, "named": 0, "unknown": 0}
    for line in lines:
        if not line.strip():
            continue
        kind = classify_entry(line)
        counts[kind] = counts.get(kind, 0) + 1

    total = counts["autostash"] + counts["wip"] + counts["named"] + counts["unknown"]

    if total <= 2:
        verdict = "clean"
        recommend = "no action needed"
    elif total <= 10:
        verdict = "mild"
        recommend = "review and drop stale entries"
    elif total <= 30:
        verdict = "moderate"
        recommend = "cleanup recommended; consider 'git stash drop' for old entries"
    else:
        verdict = "critical"
        recommend = "stash is a graveyard; bulk drop or clear, keep only recent named stashes"

    return {
        "count": total,
        "autostash": counts["autostash"],
        "wip": counts["wip"],
        "named": counts["named"],
        "verdict": verdict,
        "recommend": recommend,
    }


def drop_candidates(lines: Sequence[str], keep_recent: int = 3) -> list[int]:
    """Return stash indices safe to drop (everything except the N most recent).

    Parameters
    ----------
    lines : sequence of str
        Raw lines from ``git stash list``.
    keep_recent : int
        Number of most-recent stash entries to preserve.

    Returns
    -------
    list of int
        Stash indices (the ``N`` in ``stash@{N}``) that can be dropped.
        Drop in reverse order (highest index first) to avoid re-indexing.
    """
    indices = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # extract index from "stash@{N}:"
        if stripped.startswith("stash@{"):
            try:
                idx = int(stripped.split("{")[1].split("}")[0])
                indices.append(idx)
            except (IndexError, ValueError):
                continue

    indices.sort()
    # keep the N smallest indices (most recent), drop the rest
    return indices[keep_recent:]
