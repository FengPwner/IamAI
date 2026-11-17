"""commit_provenance — classify commits by their origin source.

The IamAI repository receives commits from multiple agents: an automated
writer loop, periodic caretaker visits, a backstop reporter (doubao),
and occasional catch-up commits that flush pending changes before a
process restart.  Knowing *who* committed and *why* is essential for
understanding the repo's growth dynamics.

Existing modules track what changes contain (stroke_diversity,
output_momentum, content_loop_detector) or when they arrive
(cadence_jitter, cadence_adherence).  None tracks *where* each commit
came from.  This module fills that gap.

Provenance categories
---------------------

==============  =====================================================
category        meaning
==============  =====================================================
caretaker       manual contribution during a caretaker visit
writer_auto     automated stroke batch from the writer loop
backstop        periodic backstop report (e.g. doubao)
catchup         backlog flush before restart or recovery
merge           merge or rebase operation
unknown         does not match any known pattern
==============  =====================================================

Design
------

- Input: a list of commit records (subject + author).
- Output: per-commit classification and aggregate provenance report.

The classifier uses message-prefix heuristics — each agent leaves a
distinctive signature in its commit subject line.  Author name serves
as a secondary signal when the message alone is ambiguous.

Zero dependencies.  stdlib only.

>>> commits = [
...     ("caretaker visit 682: add stroke_diversity module", "Qwen"),
...     ("catch-up: commit pending changes before process restart", "Qwen"),
...     ("doubao: hourly backstop report — synced to abc123", "Doubao"),
...     ("caretaker visit 681: add cadence_jitter module", "Qwen"),
...     ("auto-stroke: batch commit 42 strokes", "writer"),
... ]
>>> r = provenance_report(commits)
>>> r["counts"]["caretaker"]
2
>>> r["counts"]["catchup"]
1
>>> r["counts"]["backstop"]
1
>>> r["total"]
5
"""

from __future__ import annotations

import re
from typing import Any, Sequence


# ---------------------------------------------------------------------------
# Classification rules
# ---------------------------------------------------------------------------

_CARETAKER_RE = re.compile(
    r"^caretaker\s+visit\s+\d+", re.IGNORECASE
)
_CATCHUP_RE = re.compile(
    r"^catch[- ]?up\s*:", re.IGNORECASE
)
_BACKSTOP_RE = re.compile(
    r"^doubao\s*:", re.IGNORECASE
)
_WRITER_AUTO_RE = re.compile(
    r"^auto[- ]?stroke|^writer[- ]?loop|^batch\s+commit",
    re.IGNORECASE,
)
_MERGE_RE = re.compile(
    r"^Merge\s|^merge\s+branch|^rebase\s+", re.IGNORECASE
)

# Author-based fallbacks
_CARETAKER_AUTHORS = {"qwen", "Qwen"}
_BACKSTOP_AUTHORS = {"doubao", "Doubao"}


def classify_commit(subject: str, author: str = "") -> str:
    """Classify a single commit by its subject line and author.

    Args:
        subject: the commit subject line (first line of message).
        author: the commit author name (optional, used as fallback).

    Returns:
        One of: "caretaker", "writer_auto", "backstop", "catchup",
        "merge", "unknown".

    >>> classify_commit("caretaker visit 682: add module", "Qwen")
    'caretaker'
    >>> classify_commit("catch-up: commit pending", "Qwen")
    'catchup'
    >>> classify_commit("doubao: hourly report", "Doubao")
    'backstop'
    >>> classify_commit("Merge branch 'main'", "Qwen")
    'merge'
    >>> classify_commit("auto-stroke: batch 10", "writer")
    'writer_auto'
    """
    subject = subject.strip()
    author = author.strip()

    # Primary: message-prefix heuristics (most specific first)
    if _CARETAKER_RE.match(subject):
        return "caretaker"
    if _CATCHUP_RE.match(subject):
        return "catchup"
    if _BACKSTOP_RE.match(subject):
        return "backstop"
    if _WRITER_AUTO_RE.match(subject):
        return "writer_auto"
    if _MERGE_RE.match(subject):
        return "merge"

    # Secondary: author-based fallback for known patterns
    # Catch-up commits are almost always authored by Qwen with a
    # specific subject pattern.  But a caretaker commit is also by
    # Qwen, so author alone is not sufficient for those — only use
    # author as a tiebreaker for ambiguous subjects.
    if _CARETAKER_RE.search(subject):
        return "caretaker"

    # If the subject contains "visit" and the author is a known
    # caretaker, lean toward caretaker.
    if "visit" in subject.lower() and author in _CARETAKER_AUTHORS:
        return "caretaker"

    return "unknown"


# ---------------------------------------------------------------------------
# Batch classification
# ---------------------------------------------------------------------------

def classify_commits(
    commits: Sequence[tuple[str, str]],
) -> list[dict[str, str]]:
    """Classify a sequence of commits.

    Args:
        commits: list of (subject, author) tuples.

    Returns:
        List of dicts with keys: subject, author, category.

    >>> results = classify_commits([
    ...     ("caretaker visit 1: hello", "Qwen"),
    ...     ("catch-up: flush", "Qwen"),
    ... ])
    >>> results[0]["category"]
    'caretaker'
    >>> results[1]["category"]
    'catchup'
    """
    out: list[dict[str, str]] = []
    for subject, author in commits:
        cat = classify_commit(subject, author)
        out.append({
            "subject": subject,
            "author": author,
            "category": cat,
        })
    return out


# ---------------------------------------------------------------------------
# Aggregate report
# ---------------------------------------------------------------------------

def provenance_report(
    commits: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    """Produce an aggregate provenance report over a commit range.

    Args:
        commits: list of (subject, author) tuples.

    Returns:
        A dict with:
        - total: int
        - counts: dict[str, int] — count per category
        - ratios: dict[str, float] — fraction per category (0.0 if empty)
        - dominant: str — category with the most commits
        - classified: list[dict] — per-commit classification

    >>> r = provenance_report([
    ...     ("caretaker visit 1: x", "Qwen"),
    ...     ("caretaker visit 2: y", "Qwen"),
    ...     ("catch-up: flush", "Qwen"),
    ... ])
    >>> r["total"]
    3
    >>> r["counts"]["caretaker"]
    2
    >>> r["dominant"]
    'caretaker'
    """
    classified = classify_commits(commits)
    total = len(classified)

    # Count per category
    counts: dict[str, int] = {}
    for entry in classified:
        cat = entry["category"]
        counts[cat] = counts.get(cat, 0) + 1

    # Ratios
    ratios: dict[str, float] = {}
    for cat, n in counts.items():
        ratios[cat] = round(n / total, 4) if total > 0 else 0.0

    # Dominant
    dominant = max(counts, key=counts.get) if counts else "unknown"

    return {
        "total": total,
        "counts": counts,
        "ratios": ratios,
        "dominant": dominant,
        "classified": classified,
    }


# ---------------------------------------------------------------------------
# Provenance summary (human-readable)
# ---------------------------------------------------------------------------

def provenance_summary(report: dict[str, Any]) -> str:
    """Format a provenance report as a human-readable summary.

    Args:
        report: output of provenance_report().

    Returns:
        Multi-line string summarising the commit provenance.

    >>> r = provenance_report([
    ...     ("caretaker visit 1: x", "Qwen"),
    ...     ("caretaker visit 2: y", "Qwen"),
    ...     ("catch-up: flush", "Qwen"),
    ...     ("doubao: report", "Doubao"),
    ... ])
    >>> s = provenance_summary(r)
    >>> "4 commits" in s
    True
    >>> "caretaker" in s
    True
    """
    total = report.get("total", 0)
    counts = report.get("counts", {})
    dominant = report.get("dominant", "unknown")

    lines = [f"{total} commits across {len(counts)} source(s):"]
    # Sort by count descending
    for cat, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        pct = (n / total * 100) if total > 0 else 0
        lines.append(f"  {cat:14s}  {n:4d}  ({pct:.1f}%)")
    lines.append(f"dominant source: {dominant}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Provenance timeline — how mix shifts over windows of commits
# ---------------------------------------------------------------------------

def provenance_timeline(
    commits: Sequence[tuple[str, str]],
    window_size: int = 10,
) -> list[dict[str, Any]]:
    """Compute provenance over sliding windows of commits.

    Useful for detecting shifts in contribution mix — e.g. when the
    caretaker ratio drops as the writer becomes more autonomous, or
    when catch-up commits spike after a series of stalls.

    Args:
        commits: list of (subject, author) tuples, newest-first or
            oldest-first (the function preserves order).
        window_size: number of commits per window.

    Returns:
        List of window dicts, each with:
        - window_index: 0-based
        - start: index of first commit in window
        - end: index of last commit in window (exclusive)
        - counts: dict[str, int]
        - dominant: str

    >>> commits = [("caretaker visit %d: x" % i, "Qwen") for i in range(5)]
    >>> commits += [("catch-up: flush", "Qwen") for _ in range(5)]
    >>> tl = provenance_timeline(commits, window_size=5)
    >>> len(tl)
    2
    >>> tl[0]["dominant"]
    'caretaker'
    >>> tl[1]["dominant"]
    'catchup'
    """
    if window_size < 1:
        window_size = 1

    windows: list[dict[str, Any]] = []
    idx = 0
    win_idx = 0
    while idx < len(commits):
        chunk = commits[idx : idx + window_size]
        sub_report = provenance_report(chunk)
        windows.append({
            "window_index": win_idx,
            "start": idx,
            "end": idx + len(chunk),
            "counts": sub_report["counts"],
            "dominant": sub_report["dominant"],
        })
        idx += window_size
        win_idx += 1

    return windows


# ---------------------------------------------------------------------------
# Caretaker interval — how many commits between visits
# ---------------------------------------------------------------------------

def caretaker_interval(
    commits: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    """Measure the gap between consecutive caretaker commits.

    Returns:
        Dict with:
        - caretaker_count: int
        - gaps: list[int] — number of non-caretaker commits between
          consecutive caretaker commits
        - avg_gap: float — mean gap (0.0 if fewer than 2 caretakers)
        - max_gap: int
        - min_gap: int

    >>> commits = [
    ...     ("caretaker visit 1: x", "Qwen"),
    ...     ("catch-up: flush", "Qwen"),
    ...     ("catch-up: flush", "Qwen"),
    ...     ("caretaker visit 2: y", "Qwen"),
    ...     ("doubao: report", "Doubao"),
    ...     ("caretaker visit 3: z", "Qwen"),
    ... ]
    >>> r = caretaker_interval(commits)
    >>> r["caretaker_count"]
    3
    >>> r["gaps"]
    [2, 1]
    >>> r["avg_gap"]
    1.5
    """
    caretaker_positions = []
    for i, (subject, author) in enumerate(commits):
        if classify_commit(subject, author) == "caretaker":
            caretaker_positions.append(i)

    n = len(caretaker_positions)
    if n < 2:
        return {
            "caretaker_count": n,
            "gaps": [],
            "avg_gap": 0.0,
            "max_gap": 0,
            "min_gap": 0,
        }

    gaps = []
    for j in range(1, n):
        # Count non-caretaker commits between two caretaker positions
        gap = caretaker_positions[j] - caretaker_positions[j - 1] - 1
        gaps.append(gap)

    return {
        "caretaker_count": n,
        "gaps": gaps,
        "avg_gap": round(sum(gaps) / len(gaps), 2) if gaps else 0.0,
        "max_gap": max(gaps),
        "min_gap": min(gaps),
    }
