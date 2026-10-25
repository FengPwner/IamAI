"""commit_file_overlap — how much do consecutive commits share?

``commit_breadth`` measures how wide each commit is; ``repo_churn``
measures which files are hot overall; ``category_momentum`` measures
directional attention shifts.  None of them answer the simplest
question: *is the repo iterating on the same thing, or jumping to
something new each time?*

This module computes the **Jaccard similarity** between consecutive
commits' file sets.  For each adjacent pair (N, N+1):

    overlap = |files_N ∩ files_N+1|
    union   = |files_N ∪ files_N+1|
    score   = overlap / union   (0.0 when both sets empty)

Averages across the window give a single **overlap_score**:

===============  ====================================================
range            reading
===============  ====================================================
≥ 0.50           ``reworking`` — repeatedly touching the same files
0.25 – 0.49      ``iterating`` — some continuity, some exploration
0.10 – 0.24      ``exploring`` — each commit covers fresh ground
< 0.10           ``scattered`` — no coherence between commits
===============  ====================================================

Edge cases
----------
- Fewer than 2 commits → empty report, score 0.0.
- Commits with no changed files (merge commits) are skipped.
- The overlap between a 1-file commit and the same 1-file commit
  is 1.0 (perfect reworking).

Usage::

    from iamai.commit_file_overlap import file_overlap_report

    report = file_overlap_report(repo_path=".", last=50)
    print(report.overlap_score)   # 0.0 – 1.0
    print(report.reading)         # "iterating"
    print(report.pair_count)      # number of adjacent pairs scored
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


# ---------------------------------------------------------------------------
# Reading thresholds
# ---------------------------------------------------------------------------

_READINGS: list[tuple[float, str]] = [
    (0.50, "reworking"),
    (0.25, "iterating"),
    (0.10, "exploring"),
]
_READING_DEFAULT = "scattered"


def _classify(score: float) -> str:
    """Return the reading label for an overlap score."""
    for threshold, label in _READINGS:
        if score >= threshold:
            return label
    return _READING_DEFAULT


# ---------------------------------------------------------------------------
# Jaccard helper
# ---------------------------------------------------------------------------

def jaccard(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two sets.

    Returns 0.0 when both sets are empty (undefined similarity).
    """
    if not a and not b:
        return 0.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FileOverlapReport:
    """Aggregate file-overlap analysis across consecutive commit pairs."""

    pair_count: int = 0
    scores: list[float] = field(default_factory=list)
    overlap_score: float = 0.0
    reading: str = _READING_DEFAULT
    pairs: list[tuple[str, str, float]] = field(default_factory=list)
    """List of (sha_a, sha_b, score) triples for traceability."""

    def to_dict(self) -> dict:
        return {
            "pair_count": self.pair_count,
            "overlap_score": round(self.overlap_score, 4),
            "reading": self.reading,
            "scores": [round(s, 4) for s in self.scores],
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


def _commit_files(repo: Path, sha: str) -> set[str]:
    """Return the set of files changed by a single commit."""
    output = _run_git(repo, "diff-tree", "--no-commit-id", "-r", "--name-only", sha)
    return {line.strip() for line in output.splitlines() if line.strip()}


def _recent_shas(repo: Path, n: int = 50) -> list[str]:
    """Return the *n* most recent commit SHAs (newest first)."""
    output = _run_git(repo, "log", "--format=%H", f"-{n}")
    return [line.strip() for line in output.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def file_overlap_report(
    repo_path: str | Path = ".",
    last: int = 50,
) -> FileOverlapReport:
    """Analyse consecutive commit file overlap over recent history.

    Parameters
    ----------
    repo_path : str or Path
        Path to the git repository.
    last : int
        Number of recent commits to analyse (pairs = last - 1).

    Returns
    -------
    FileOverlapReport
    """
    repo = Path(repo_path).resolve()
    shas = _recent_shas(repo, last)

    if len(shas) < 2:
        return FileOverlapReport()

    # Pre-fetch file sets for each commit.
    file_sets: dict[str, set[str]] = {}
    for sha in shas:
        file_sets[sha] = _commit_files(repo, sha)

    scores: list[float] = []
    pairs: list[tuple[str, str, float]] = []

    # Walk oldest-first so pairs are in chronological order.
    chronological = list(reversed(shas))
    for i in range(len(chronological) - 1):
        sha_a = chronological[i]
        sha_b = chronological[i + 1]
        fa = file_sets[sha_a]
        fb = file_sets[sha_b]

        # Skip pairs where both commits are empty (merge commits).
        if not fa and not fb:
            continue

        score = jaccard(fa, fb)
        scores.append(score)
        pairs.append((sha_a[:8], sha_b[:8], score))

    if not scores:
        return FileOverlapReport()

    avg = sum(scores) / len(scores)

    return FileOverlapReport(
        pair_count=len(scores),
        scores=scores,
        overlap_score=avg,
        reading=_classify(avg),
        pairs=pairs,
    )


# ---------------------------------------------------------------------------
# Summary formatter
# ---------------------------------------------------------------------------

def overlap_summary(report: FileOverlapReport) -> str:
    """Return a human-readable one-liner for the report."""
    if report.pair_count == 0:
        return "commit_file_overlap: no pairs to analyse"
    pct = report.overlap_score * 100
    return (
        f"commit_file_overlap: {pct:.1f}% overlap ({report.reading}) "
        f"over {report.pair_count} commit pairs"
    )
