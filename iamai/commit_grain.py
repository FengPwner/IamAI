"""commit_grain — analyze commit granularity and size distribution.

A healthy repository has a rhythm: commits are neither too large (bulk
dumps that hide individual changes) nor too small (empty or trivial
edits that add noise).  This module quantifies **commit grain** — the
size, consistency, and quality of commits — so a caretaker can spot
pathological patterns before they become problems.

Public API::

    from iamai.commit_grain import CommitGrain, grain_report

    cg = CommitGrain(repo_path)
    summary = cg.summary()
    # {"median_files": 4, "mean_files": 6.2, "consistency": 0.72,
    #  "mega_pct": 3.1, "trivial_pct": 8.5, "grade": "good"}

    print(grain_report(repo_path))
    # "commit grain: median 4 files, consistency 0.72, 3.1% mega, 8.5% trivial — good"

Grain model
-----------

Each commit is classified by the number of files it touches:

============  ==========  ============================================
files         bucket      meaning
============  ==========  ============================================
0             empty       no file changes (merge / tag / no-op)
1 – 2         atomic      focused, single-concern change
3 – 10        normal      typical feature or fix
11 – 50       broad       multi-area change, review harder
51+           mega        bulk dump, likely includes unrelated changes
============  ==========  ============================================

**Consistency score** measures how stable the commit sizes are.  It is
defined as ``1 - CV`` where CV is the coefficient of variation of file
counts (capped at 1.0).  A score of 1.0 means every commit touches the
same number of files; 0.0 means extreme variance.

**Grade** is assigned by a weighted formula::

    score = consistency
            - 1.0 * mega_fraction
            - 0.1 * trivial_fraction
            + 0.2 * atomic_fraction

============  ==========  ============================================
score range   grade       meaning
============  ==========  ============================================
≥ 0.8         excellent   disciplined, focused commits
≥ 0.6         good        normal healthy project
≥ 0.4         fair        some inconsistency, watch for mega-commits
≥ 0.2         coarse      too many large or inconsistent commits
< 0.2         chaotic     no discernible commit discipline
============  ==========  ============================================
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Bucket classification
# ---------------------------------------------------------------------------

BUCKETS = ["empty", "atomic", "normal", "broad", "mega"]


def classify_commit(file_count: int) -> str:
    """Return the grain bucket for a given file count."""
    if file_count <= 0:
        return "empty"
    if file_count <= 2:
        return "atomic"
    if file_count <= 10:
        return "normal"
    if file_count <= 50:
        return "broad"
    return "mega"


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

@dataclass
class CommitGrain:
    """Analyze commit granularity for a git repository.

    Parameters
    ----------
    repo_path : str
        Path to the git working tree.
    max_commits : int
        Maximum number of recent commits to analyze (default 200).
    mega_threshold : int
        File count at or above which a commit is "mega" (default 51).
    trivial_threshold : int
        File count at or below which a commit is "trivial" (default 1).
    """

    repo_path: str
    max_commits: int = 200
    mega_threshold: int = 51
    trivial_threshold: int = 1

    # computed
    _file_counts: List[int] = field(default_factory=list, repr=False)
    _loaded: bool = field(default=False, repr=False)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _run_git(self, *args: str) -> str:
        """Run a git command and return stdout."""
        result = subprocess.run(
            ["git"] + list(args),
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    def _load(self) -> None:
        """Parse recent commits and their file counts."""
        if self._loaded:
            return

        # Get commit hashes
        log_output = self._run_git(
            "log", f"--max-count={self.max_commits}", "--format=%H"
        )
        if not log_output:
            self._loaded = True
            return

        hashes = log_output.splitlines()
        counts: List[int] = []

        for h in hashes:
            # Count files changed in this commit (--root handles initial commit)
            stat = self._run_git(
                "diff-tree", "--no-commit-id", "--root", "-r", "--name-only", h
            )
            n = len(stat.splitlines()) if stat else 0
            counts.append(n)

        self._file_counts = counts
        self._loaded = True

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @property
    def file_counts(self) -> List[int]:
        """Raw file counts per commit (most-recent first)."""
        self._load()
        return list(self._file_counts)

    @property
    def total_commits(self) -> int:
        """Number of commits analyzed."""
        self._load()
        return len(self._file_counts)

    @property
    def median_files(self) -> float:
        """Median file count per commit."""
        self._load()
        if not self._file_counts:
            return 0.0
        s = sorted(self._file_counts)
        n = len(s)
        if n % 2 == 1:
            return float(s[n // 2])
        return (s[n // 2 - 1] + s[n // 2]) / 2.0

    @property
    def mean_files(self) -> float:
        """Mean file count per commit."""
        self._load()
        if not self._file_counts:
            return 0.0
        return sum(self._file_counts) / len(self._file_counts)

    @property
    def consistency(self) -> float:
        """Consistency score: 1.0 = uniform sizes, 0.0 = extreme variance."""
        self._load()
        if len(self._file_counts) < 2:
            return 1.0
        mean = self.mean_files
        if mean == 0:
            return 1.0
        variance = sum((x - mean) ** 2 for x in self._file_counts) / len(self._file_counts)
        std = variance ** 0.5
        cv = std / mean
        return max(0.0, min(1.0, 1.0 - cv))

    def bucket_distribution(self) -> Dict[str, int]:
        """Count of commits in each bucket."""
        self._load()
        dist: Dict[str, int] = {b: 0 for b in BUCKETS}
        for n in self._file_counts:
            dist[classify_commit(n)] += 1
        return dist

    @property
    def mega_pct(self) -> float:
        """Percentage of commits classified as mega."""
        self._load()
        if not self._file_counts:
            return 0.0
        dist = self.bucket_distribution()
        return 100.0 * dist["mega"] / len(self._file_counts)

    @property
    def trivial_pct(self) -> float:
        """Percentage of commits that are empty or atomic (<=trivial_threshold)."""
        self._load()
        if not self._file_counts:
            return 0.0
        count = sum(1 for n in self._file_counts if n <= self.trivial_threshold)
        return 100.0 * count / len(self._file_counts)

    @property
    def atomic_pct(self) -> float:
        """Percentage of commits that are atomic (1-2 files)."""
        self._load()
        if not self._file_counts:
            return 0.0
        dist = self.bucket_distribution()
        return 100.0 * dist["atomic"] / len(self._file_counts)

    @property
    def grade(self) -> str:
        """Overall grain grade based on weighted formula."""
        score = (
            self.consistency
            - 1.0 * (self.mega_pct / 100.0)
            - 0.1 * (self.trivial_pct / 100.0)
            + 0.2 * (self.atomic_pct / 100.0)
        )
        if score >= 0.8:
            return "excellent"
        if score >= 0.6:
            return "good"
        if score >= 0.4:
            return "fair"
        if score >= 0.2:
            return "coarse"
        return "chaotic"

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Return a dict of all key metrics."""
        return {
            "total_commits": self.total_commits,
            "median_files": round(self.median_files, 1),
            "mean_files": round(self.mean_files, 1),
            "consistency": round(self.consistency, 2),
            "mega_pct": round(self.mega_pct, 1),
            "trivial_pct": round(self.trivial_pct, 1),
            "atomic_pct": round(self.atomic_pct, 1),
            "grade": self.grade,
            "buckets": self.bucket_distribution(),
        }


def grain_report(repo_path: str, max_commits: int = 200) -> str:
    """One-line human-readable grain report."""
    cg = CommitGrain(repo_path, max_commits=max_commits)
    s = cg.summary()
    return (
        f"commit grain: median {s['median_files']} files, "
        f"consistency {s['consistency']}, "
        f"{s['mega_pct']}% mega, "
        f"{s['trivial_pct']}% trivial — {s['grade']}"
    )
