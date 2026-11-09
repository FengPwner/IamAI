#!/usr/bin/env python3
"""commit_atomicity — measure how well-scoped each commit is.

A disciplined auto-writing bot should commit *one logical change* at a
time: a new module plus its tests, a metrics update, a docs refresh.
When commits start mixing unrelated files — a data file, three docs,
and a test from a different feature — the batching logic is probably
dumping whatever happened to accumulate instead of grouping sensibly.

This module scores each commit on **atomicity**: the degree to which
all changed files belong to a single logical area.

Signals
-------

===============  ============================================================
metric           meaning
===============  ============================================================
file_count       total files changed in the commit
dir_entropy      Shannon entropy of the top-level directory distribution,
                 normalised to [0, 1].  0 = one directory; 1 = uniform
                 across all directories.
category_mix     number of distinct functional categories touched
                 (data, docs, code, tests, notes, config, other).
scatter_ratio    fraction of changed files that live *outside* the most
                 common directory.  0 = all in one place; 1 = evenly
                 scattered.
atomicity_score  weighted composite in [0, 1]:
                 ``0.35*(1-scatter) + 0.35*(1-dir_entropy) + 0.30*(1/cat_mix_norm)``
                 1.0 = single logical change; 0.0 = maximum scatter.
verdict          ``atomic`` (≥0.70), ``mixed`` (0.40–0.69), ``scattered`` (<0.40).
===============  ============================================================

Public API
----------

>>> from iamai.commit_atomicity import score_commit, score_recent
>>> report = score_commit(changed_files=["iamai/foo.py", "tests/test_foo.py"])
>>> report["atomicity_score"]
0.82

>>> history = score_recent(repo_root=".", n=20)
>>> history[0]["verdict"]
'atomic'

>>> summary = atomicity_summary(repo_root=".", n=50)
>>> summary["mean_score"]
0.74
"""

from __future__ import annotations

import math
import subprocess
from collections import Counter
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Functional file categories — broader than directories, capturing intent.
FILE_CATEGORIES: Dict[str, List[str]] = {
    "code": ["iamai", "scripts", "tools", "agent"],
    "tests": ["tests"],
    "data": ["data"],
    "docs": ["docs"],
    "notes": ["notes", "snippets"],
    "config": [".github"],
}

ALL_CATEGORIES = tuple(FILE_CATEGORIES.keys()) + ("other",)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _top_directory(path: str) -> str:
    """Return the top-level directory component of a path.

    >>> _top_directory("iamai/foo.py")
    'iamai'
    >>> _top_directory("README.md")
    '.'
    """
    parts = PurePosixPath(path).parts
    if len(parts) <= 1:
        return "."
    return parts[0]


def _categorise(path: str) -> str:
    """Map a file path to its functional category.

    >>> _categorise("iamai/cadence_drift.py")
    'code'
    >>> _categorise("tests/test_foo.py")
    'tests'
    >>> _categorise("Makefile")
    'other'
    """
    top = _top_directory(path)
    for cat, dirs in FILE_CATEGORIES.items():
        if top in dirs:
            return cat
    return "other"


def _shannon_entropy_normalised(counts: Counter) -> float:
    """Compute normalised Shannon entropy in [0, 1].

    Returns 0.0 when there is only one category (no diversity).
    Returns 1.0 when all categories are equally represented.
    """
    total = sum(counts.values())
    if total == 0 or len(counts) <= 1:
        return 0.0
    probs = [c / total for c in counts.values() if c > 0]
    h = -sum(p * math.log(p) for p in probs)
    h_max = math.log(len(counts))
    if h_max == 0:
        return 0.0
    return min(h / h_max, 1.0)


def _scatter_ratio(dir_counts: Counter) -> float:
    """Fraction of files outside the most common directory.

    Returns 0.0 when all files are in one directory.
    """
    total = sum(dir_counts.values())
    if total == 0:
        return 0.0
    most_common_count = dir_counts.most_common(1)[0][1]
    return 1.0 - (most_common_count / total)


def _classify(score: float) -> str:
    """Classify an atomicity score into a verdict band."""
    if score >= 0.70:
        return "atomic"
    if score >= 0.40:
        return "mixed"
    return "scattered"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_commit(
    changed_files: Sequence[str],
    commit_hash: str = "",
    message: str = "",
) -> Dict[str, Any]:
    """Score a single commit's atomicity from its changed-file list.

    Parameters
    ----------
    changed_files : sequence of str
        Paths relative to the repo root.
    commit_hash : str, optional
        Short hash for the report (informational only).
    message : str, optional
        Commit message for the report (informational only).

    Returns
    -------
    dict with keys: file_count, dir_entropy, category_mix, scatter_ratio,
    atomicity_score, verdict, dominant_dir, categories_touched,
    commit_hash, message.
    """
    if not changed_files:
        return {
            "file_count": 0,
            "dir_entropy": 0.0,
            "category_mix": 0,
            "scatter_ratio": 0.0,
            "atomicity_score": 1.0,
            "verdict": "atomic",
            "dominant_dir": ".",
            "categories_touched": [],
            "commit_hash": commit_hash,
            "message": message,
        }

    dir_counts: Counter = Counter(_top_directory(f) for f in changed_files)
    cat_counts: Counter = Counter(_categorise(f) for f in changed_files)

    n = len(changed_files)
    scatter = _scatter_ratio(dir_counts)
    ent = _shannon_entropy_normalised(dir_counts)
    cat_mix = len(cat_counts)
    # Normalise category_mix to [0, 1] using ALL_CATEGORIES as the ceiling.
    cat_mix_norm = min(cat_mix / len(ALL_CATEGORIES), 1.0)

    score = 0.35 * (1.0 - scatter) + 0.35 * (1.0 - ent) + 0.30 * (1.0 - cat_mix_norm)
    score = round(min(max(score, 0.0), 1.0), 4)

    dominant = dir_counts.most_common(1)[0][0]

    return {
        "file_count": n,
        "dir_entropy": round(ent, 4),
        "category_mix": cat_mix,
        "scatter_ratio": round(scatter, 4),
        "atomicity_score": score,
        "verdict": _classify(score),
        "dominant_dir": dominant,
        "categories_touched": sorted(cat_counts.keys()),
        "commit_hash": commit_hash,
        "message": message,
    }


def _parse_git_log(repo_root: str, n: int) -> List[Dict[str, Any]]:
    """Run ``git log`` and parse into per-commit records.

    Each record: {"hash": str, "message": str, "files": list[str]}.
    """
    cmd = [
        "git", "log",
        f"--max-count={n}",
        "--pretty=format:COMMIT_START%n%H%n%s",
        "--name-only",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=repo_root,
        timeout=30,
    )
    if result.returncode != 0:
        return []

    commits: list[Dict[str, Any]] = []
    current: dict | None = None

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line == "COMMIT_START":
            if current is not None:
                commits.append(current)
            current = {"hash": "", "message": "", "files": []}
            continue
        if current is not None and not current["hash"]:
            current["hash"] = line[:8]
            continue
        if current is not None and not current["message"]:
            current["message"] = line
            continue
        if current is not None:
            current["files"].append(line)

    if current is not None:
        commits.append(current)

    return commits


def score_recent(repo_root: str = ".", n: int = 20) -> List[Dict[str, Any]]:
    """Score the *n* most recent commits in the repository.

    Returns a list of atomicity reports (newest first).
    """
    records = _parse_git_log(repo_root, n)
    reports: list[Dict[str, Any]] = []
    for rec in records:
        report = score_commit(
            rec["files"],
            commit_hash=rec["hash"],
            message=rec["message"],
        )
        reports.append(report)
    return reports


def atomicity_summary(repo_root: str = ".", n: int = 50) -> Dict[str, Any]:
    """Compute an aggregate summary over the last *n* commits.

    Returns a dict with mean_score, median_score, atomic_pct,
    mixed_pct, scattered_pct, total_commits, and per-commit details.
    """
    reports = score_recent(repo_root, n)
    if not reports:
        return {
            "mean_score": 0.0,
            "median_score": 0.0,
            "atomic_pct": 0.0,
            "mixed_pct": 0.0,
            "scattered_pct": 0.0,
            "total_commits": 0,
            "details": [],
        }

    scores = [r["atomicity_score"] for r in reports]
    verdicts = [r["verdict"] for r in reports]
    total = len(reports)

    mean = sum(scores) / total
    sorted_scores = sorted(scores)
    mid = total // 2
    if total % 2 == 0:
        median = (sorted_scores[mid - 1] + sorted_scores[mid]) / 2.0
    else:
        median = sorted_scores[mid]

    atomic_count = verdicts.count("atomic")
    mixed_count = verdicts.count("mixed")
    scattered_count = verdicts.count("scattered")

    return {
        "mean_score": round(mean, 4),
        "median_score": round(median, 4),
        "atomic_pct": round(atomic_count / total, 4),
        "mixed_pct": round(mixed_count / total, 4),
        "scattered_pct": round(scattered_count / total, 4),
        "total_commits": total,
        "details": reports,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    """Print atomicity summary for the current repo."""
    import json as _json
    import sys

    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    summary = atomicity_summary(repo, n)
    print(
        f"commit atomicity: mean={summary['mean_score']:.2f}  "
        f"median={summary['median_score']:.2f}  "
        f"atomic={summary['atomic_pct']:.0%}  "
        f"mixed={summary['mixed_pct']:.0%}  "
        f"scattered={summary['scattered_pct']:.0%}  "
        f"({summary['total_commits']} commits)"
    )
    for d in summary["details"][:5]:
        print(
            f"  {d['commit_hash']}  {d['atomicity_score']:.2f}  "
            f"{d['verdict']:>9s}  {d['file_count']:>3d} files  "
            f"{d['message'][:60]}"
        )


if __name__ == "__main__":
    _main()
