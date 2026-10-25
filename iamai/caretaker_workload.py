"""caretaker_workload — is the caretaker running the show or just watching?

A self-writing repo should mostly run itself: the writer produces
strokes, the batch committer packages them, and the caretaker only
intervenes when something breaks.  But how do you measure whether the
automation is *actually* self-sufficient versus propped up by constant
manual poking?

This module classifies every commit message into one of four buckets:

================  =====================================================
bucket            pattern
================  =====================================================
``caretaker``     starts with ``caretaker visit`` — scheduled check-in
``catchup``       starts with ``catch-up`` — backlog flush before/after
                  a restart or visit
``auto_content``  contains ``flush writer strokes`` or matches the
                  ``add <module> module (N tests)`` pattern — content
                  produced by the automated pipeline
``manual``        everything else — direct human edits, config changes,
                  README tweaks, hot-fixes
================  =====================================================

From those counts it derives:

- **self_sufficiency** — ``(auto_content + catchup) / total``
  Higher means the pipeline runs itself; lower means humans do the work.
- **intervention_rate** — ``caretaker / total``
  Fraction of commits triggered by caretaker visits.
- **manual_rate** — ``manual / total``
  Fraction of raw human-driven commits.
- **catchup_rate** — ``catchup / total``
  How often the pipeline needs a nudge to flush its backlog.

Grading
-------

================  =====================================================
grade             meaning
================  =====================================================
``autonomous``    self_sufficiency ≥ 0.70 — mostly self-running
``supervised``    self_sufficiency ≥ 0.50 — caretaker guides, pipeline
                  does the bulk
``attended``      self_sufficiency ≥ 0.30 — significant manual work
``dependent``     self_sufficiency ≥ 0.10 — pipeline produces little
                  on its own
``manual``        self_sufficiency < 0.10 — almost entirely hand-driven
================  =====================================================

Usage::

    from iamai.caretaker_workload import workload_report

    report = workload_report(repo_path="/path/to/IamAI", last=50)
    print(report.self_sufficiency, report.grade)
    print(report.counts)
    # {"caretaker": 25, "catchup": 20, "auto_content": 8, "manual": 2}

    print(workload_summary(report))
    # "caretaker_workload: 0.51 self-sufficient (supervised) over 55 commits"
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


# ---------------------------------------------------------------------------
# Classification patterns
# ---------------------------------------------------------------------------

_CARETAKER_RE = re.compile(r"^caretaker visit\b", re.IGNORECASE)
_CATCHUP_RE = re.compile(r"^catch-?up\b", re.IGNORECASE)
_AUTO_CONTENT_RE = re.compile(
    r"flush writer strokes|add \S+ module \(\d+ tests?",
    re.IGNORECASE,
)


def classify_commit(message: str) -> str:
    """Classify a single commit message into a workload bucket.

    Parameters
    ----------
    message : str
        The first line (subject) of a commit message.

    Returns
    -------
    str
        One of ``"caretaker"``, ``"catchup"``, ``"auto_content"``,
        or ``"manual"``.
    """
    if not message:
        return "manual"
    msg = message.strip()
    if _CARETAKER_RE.match(msg):
        return "caretaker"
    if _CATCHUP_RE.match(msg):
        return "catchup"
    if _AUTO_CONTENT_RE.search(msg):
        return "auto_content"
    return "manual"


# ---------------------------------------------------------------------------
# Grade thresholds
# ---------------------------------------------------------------------------

_GRADE_THRESHOLDS: list[tuple[float, str]] = [
    (0.70, "autonomous"),
    (0.50, "supervised"),
    (0.30, "attended"),
    (0.10, "dependent"),
]
_GRADE_MANUAL = "manual"


def _classify_grade(self_sufficiency: float) -> str:
    """Return the grade string for a given self-sufficiency score."""
    for threshold, grade in _GRADE_THRESHOLDS:
        if self_sufficiency >= threshold:
            return grade
    return _GRADE_MANUAL


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WorkloadReport:
    """Aggregate workload analysis over a range of commits."""

    total_commits: int = 0
    counts: dict[str, int] = field(default_factory=lambda: {
        "caretaker": 0,
        "catchup": 0,
        "auto_content": 0,
        "manual": 0,
    })
    self_sufficiency: float = 0.0
    intervention_rate: float = 0.0
    manual_rate: float = 0.0
    catchup_rate: float = 0.0
    grade: str = "manual"
    classified: list[tuple[str, str]] = field(default_factory=list)
    """List of (sha, bucket) pairs for traceability."""

    def to_dict(self) -> dict:
        return {
            "total_commits": self.total_commits,
            "counts": dict(self.counts),
            "self_sufficiency": round(self.self_sufficiency, 3),
            "intervention_rate": round(self.intervention_rate, 3),
            "manual_rate": round(self.manual_rate, 3),
            "catchup_rate": round(self.catchup_rate, 3),
            "grade": self.grade,
        }


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(repo: Path, *args: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )
    return result.stdout.strip()


def _get_recent_commits(repo: Path, n: int = 50) -> list[tuple[str, str]]:
    """Return (sha, subject) for the *n* most recent commits."""
    output = _run_git(repo, "log", "--format=%H %s", f"-{n}")
    commits: list[tuple[str, str]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        sha, _, subject = line.partition(" ")
        commits.append((sha, subject))
    return commits


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def workload_report(
    repo_path: str | Path = ".",
    last: int = 50,
) -> WorkloadReport:
    """Analyse the workload breakdown over recent commits.

    Parameters
    ----------
    repo_path : str or Path
        Path to the git repository.
    last : int
        Number of recent commits to analyse.

    Returns
    -------
    WorkloadReport
    """
    repo = Path(repo_path).resolve()
    commits = _get_recent_commits(repo, last)

    if not commits:
        return WorkloadReport()

    counts: Counter[str] = Counter()
    classified: list[tuple[str, str]] = []

    for sha, subject in commits:
        bucket = classify_commit(subject)
        counts[bucket] += 1
        classified.append((sha, bucket))

    total = len(commits)
    auto = counts.get("auto_content", 0)
    catchup = counts.get("catchup", 0)
    caretaker = counts.get("caretaker", 0)
    manual = counts.get("manual", 0)

    self_suff = (auto + catchup) / total if total else 0.0
    intervention = caretaker / total if total else 0.0
    manual_r = manual / total if total else 0.0
    catchup_r = catchup / total if total else 0.0

    full_counts = {
        "caretaker": caretaker,
        "catchup": catchup,
        "auto_content": auto,
        "manual": manual,
    }

    return WorkloadReport(
        total_commits=total,
        counts=full_counts,
        self_sufficiency=self_suff,
        intervention_rate=intervention,
        manual_rate=manual_r,
        catchup_rate=catchup_r,
        grade=_classify_grade(self_suff),
        classified=classified,
    )


# ---------------------------------------------------------------------------
# Summary formatter
# ---------------------------------------------------------------------------

def workload_summary(report: WorkloadReport) -> str:
    """Return a human-readable one-liner for the report."""
    if report.total_commits == 0:
        return "caretaker_workload: no commits to analyse"
    pct = report.self_sufficiency * 100
    c = report.counts
    return (
        f"caretaker_workload: {pct:.0f}% self-sufficient ({report.grade}) "
        f"over {report.total_commits} commits — "
        f"auto {c['auto_content']}, catchup {c['catchup']}, "
        f"caretaker {c['caretaker']}, manual {c['manual']}"
    )
