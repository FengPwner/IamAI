"""stroke_yield — what fraction of writer output survives into the commit graph?

Every stroke the writer appends to ``data/strokes.jsonl`` is a small act
of documentation.  But a stroke that sits in the working tree without
being committed is fragile: a crash, a stale-lock purge, or an
overzealous ``git checkout -- .`` will erase it.  *Stroke yield* answers
the question: **how much of the writer's work is actually preserved?**

Concept
-------

The measurement is straightforward::

    total_strokes      = line count of strokes.jsonl in the working tree
    committed_strokes  = line count of strokes.jsonl at HEAD

    yield_pct = committed_strokes / total_strokes * 100

A repo where every stroke has been committed scores 100 %.  A repo with
a large uncommitted tail scores lower.

Grades
------

=================  ===================================================
grade              meaning
=================  ===================================================
``excellent``      yield ≥ 98 % — virtually all output is committed
``good``           yield 90–97 % — small uncommitted tail, normal lag
``fair``           yield 75–89 % — significant gap, commit soon
``poor``           yield 50–74 % — large gap, intervention needed
``critical``       yield < 50 % — most output is uncommitted, act now
=================  ===================================================

Why this matters
----------------

Existing metrics track *cadence* (strokes per minute), *commit freshness*
(time since last commit), and *commit debt* (file-level backlog).
Stroke yield fills a different niche: it measures **preservation ratio**
at the content level.  A repo could have a fresh commit and still be
missing 200 strokes if the commit happened before a burst of writing.

The caretaker can use yield_pct to decide whether a manual flush commit
is warranted before leaving the watch.

Usage::

    from iamai.stroke_yield import stroke_yield_report

    report = stroke_yield_report(repo_path="/path/to/IamAI")
    print(report.yield_pct, report.grade)
    print(report.total_strokes, report.committed_strokes)
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Grade thresholds (yield_pct >= threshold → grade)
# ---------------------------------------------------------------------------

_GRADE_THRESHOLDS: list[tuple[float, str]] = [
    (98.0, "excellent"),
    (90.0, "good"),
    (75.0, "fair"),
    (50.0, "poor"),
]
_GRADE_CRITICAL = "critical"


def _classify_yield(pct: float) -> str:
    """Return the grade string for a given yield percentage."""
    for threshold, grade in _GRADE_THRESHOLDS:
        if pct >= threshold:
            return grade
    return _GRADE_CRITICAL


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class YieldReport:
    """Result of a stroke-yield measurement."""

    total_strokes: int
    committed_strokes: int
    uncommitted_strokes: int
    yield_pct: float
    grade: str

    def to_dict(self) -> dict:
        return {
            "total_strokes": self.total_strokes,
            "committed_strokes": self.committed_strokes,
            "uncommitted_strokes": self.uncommitted_strokes,
            "yield_pct": round(self.yield_pct, 2),
            "grade": self.grade,
        }


# ---------------------------------------------------------------------------
# Counting helpers
# ---------------------------------------------------------------------------

def _count_lines_in_file(path: Path) -> int:
    """Count non-empty lines in a file.  Returns 0 if file missing."""
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        return sum(1 for line in fh if line.strip())


def _count_lines_at_head(repo: Path, rel_path: str = "data/strokes.jsonl") -> int:
    """Count non-empty lines of a file as stored at HEAD.  Returns 0 on error."""
    try:
        raw = subprocess.run(
            ["git", "show", f"HEAD:{rel_path}"],
            capture_output=True,
            text=True,
            cwd=str(repo),
            timeout=10,
        )
        if raw.returncode != 0:
            return 0
        return sum(1 for line in raw.stdout.splitlines() if line.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0


def _read_latest_seq(path: Path) -> Optional[int]:
    """Read the seq number of the last stroke in a file, or None."""
    if not path.exists():
        return None
    last_line = ""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                last_line = stripped
    if not last_line:
        return None
    try:
        return json.loads(last_line).get("seq")
    except (json.JSONDecodeError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def stroke_yield_report(
    repo_path: str | Path | None = None,
    strokes_rel: str = "data/strokes.jsonl",
) -> YieldReport:
    """Measure what fraction of writer strokes survive in the commit graph.

    Parameters
    ----------
    repo_path : path-like, optional
        Root of the git repository.  Defaults to the IamAI workspace.
    strokes_rel : str
        Relative path (from repo root) to the strokes append-only log.

    Returns
    -------
    YieldReport with counts, percentage, and grade.
    """
    if repo_path is None:
        repo_path = Path(__file__).resolve().parent.parent
    repo = Path(repo_path)

    strokes_file = repo / strokes_rel
    total = _count_lines_in_file(strokes_file)
    committed = _count_lines_at_head(repo, strokes_rel)

    # Clamp: committed cannot exceed total (race during concurrent writes)
    if committed > total:
        committed = total

    uncommitted = total - committed

    if total == 0:
        pct = 100.0  # nothing to lose
    else:
        pct = (committed / total) * 100.0

    grade = _classify_yield(pct)

    return YieldReport(
        total_strokes=total,
        committed_strokes=committed,
        uncommitted_strokes=uncommitted,
        yield_pct=round(pct, 2),
        grade=grade,
    )


# ---------------------------------------------------------------------------
# Convenience: human-readable summary
# ---------------------------------------------------------------------------

def yield_summary(report: YieldReport | None = None, **kwargs) -> str:
    """One-line human-readable summary of stroke yield."""
    if report is None:
        report = stroke_yield_report(**kwargs)
    return (
        f"stroke yield: {report.yield_pct:.1f}% ({report.grade}) — "
        f"{report.committed_strokes}/{report.total_strokes} committed, "
        f"{report.uncommitted_strokes} uncommitted"
    )
