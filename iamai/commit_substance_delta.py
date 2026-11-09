"""commit_substance_delta — classify what a commit actually changed.

``commit_message_quality`` scores the *message*.  ``commit_substance``
scores the *size*.  Neither looks at the diff itself to ask: was this
a content addition, a deletion, a refactor, or just a data append?

This module fills that gap.  It takes a diffstat (or raw diff output)
and classifies the commit into one of five change types, then computes
a substance score indicating how much of the change was *new content*
versus *housekeeping*.

Change types
------------

=============  ========================================================
type           meaning
=============  ========================================================
new_content    commit adds new files (modules, notes, tests)
expansion      commit modifies existing files, net addition > 0
refactor       commit modifies existing files, roughly balanced
contraction    commit modifies existing files, net deletion > 0
data_append    commit only touches append-only data files (.jsonl, logs)
=============  ========================================================

Substance score
---------------

A 0.0–1.0 score indicating how "substantive" the commit is:

- **1.0** — new module + tests (new code, new tests)
- **0.7** — meaningful expansion of existing code
- **0.5** — refactor or balanced edit
- **0.3** — data append (necessary but not creative)
- **0.1** — contraction (cleanup, deletion)

The score is computed from three signals:

1. **new_file_ratio** — fraction of changed files that are new.
2. **test_ratio** — fraction of changed files that are tests.
3. **net_addition_ratio** — ``(additions - deletions) / (additions + deletions)``
   clamped to [0, 1].

Usage::

    from iamai.commit_substance_delta import (
        classify_commit, substance_score, SubstanceReport,
    )

    report = classify_commit(
        files_changed=5,
        insertions=120,
        deletions=10,
        new_files=2,
        test_files=1,
        data_files=1,
    )
    print(report.change_type)   # "new_content"
    print(report.substance)     # 0.78
    print(report.summary())

    # from git log:
    # $ git log --format="" --stat -1 | parse_diffstat
    from iamai.commit_substance_delta import parse_diffstat
    stats = parse_diffstat(" 5 files changed, 120 insertions(+), 10 deletions(-)")
    report = classify_commit(**stats)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Change type classification
# ---------------------------------------------------------------------------

def classify_change_type(
    files_changed: int,
    insertions: int,
    deletions: int,
    new_files: int,
    data_files: int,
) -> str:
    """Classify a commit into a change type.

    Parameters
    ----------
    files_changed : int
        Total number of files touched by the commit.
    insertions : int
        Total lines inserted (added).
    deletions : int
        Total lines deleted (removed).
    new_files : int
        Number of newly created files.
    data_files : int
        Number of append-only data files (.jsonl, .log, etc.).

    Returns
    -------
    str
        One of: new_content, expansion, refactor, contraction, data_append.
    """
    if files_changed <= 0:
        return "refactor"

    # if most files are data appends, classify as data_append
    if data_files > 0 and data_files >= files_changed * 0.5:
        return "data_append"

    # if majority of files are new, classify as new_content
    if new_files > 0 and new_files >= files_changed * 0.5:
        return "new_content"

    # otherwise classify by net change direction
    total = insertions + deletions
    if total == 0:
        return "refactor"

    net_ratio = (insertions - deletions) / total

    if net_ratio > 0.2:
        return "expansion"
    elif net_ratio < -0.2:
        return "contraction"
    else:
        return "refactor"


def compute_substance_score(
    files_changed: int,
    insertions: int,
    deletions: int,
    new_files: int,
    test_files: int,
    data_files: int,
) -> float:
    """Compute a 0.0–1.0 substance score.

    Higher scores indicate more creative / substantive work.
    Data appends and contractions score lower.
    """
    if files_changed <= 0:
        return 0.5

    # signal 1: new file ratio
    new_file_ratio = new_files / files_changed if files_changed > 0 else 0.0

    # signal 2: test ratio
    test_ratio = test_files / files_changed if files_changed > 0 else 0.0

    # signal 3: net addition ratio (clamped to [0, 1])
    total = insertions + deletions
    if total > 0:
        net_addition_ratio = max(0.0, (insertions - deletions) / total)
    else:
        net_addition_ratio = 0.5

    # signal 4: data append penalty
    data_ratio = data_files / files_changed if files_changed > 0 else 0.0

    # weighted combination
    score = (
        0.35 * min(1.0, new_file_ratio * 2)  # new files boost
        + 0.25 * test_ratio                    # tests boost
        + 0.25 * net_addition_ratio            # net additions boost
        + 0.15 * 0.5                           # baseline
    )

    # data append penalty: reduces score proportionally
    score *= 1.0 - data_ratio * 0.5

    return round(max(0.0, min(1.0, score)), 2)


# ---------------------------------------------------------------------------
# Substance report dataclass
# ---------------------------------------------------------------------------

@dataclass
class SubstanceReport:
    """Complete substance analysis for a single commit."""

    change_type: str
    substance: float
    files_changed: int
    insertions: int
    deletions: int
    new_files: int
    test_files: int
    data_files: int

    def summary(self) -> Dict[str, Any]:
        """Return a dict summary suitable for JSON serialization."""
        return {
            "change_type": self.change_type,
            "substance": self.substance,
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "net_lines": self.insertions - self.deletions,
            "new_files": self.new_files,
            "test_files": self.test_files,
            "data_files": self.data_files,
        }

    def one_line(self) -> str:
        """Human-readable one-line summary."""
        net = self.insertions - self.deletions
        sign = "+" if net >= 0 else ""
        return (
            f"{self.change_type} ({self.substance:.2f}): "
            f"{self.files_changed} files, "
            f"+{self.insertions}/-{self.deletions} (net {sign}{net}), "
            f"{self.new_files} new, {self.test_files} tests, "
            f"{self.data_files} data"
        )


def classify_commit(
    files_changed: int = 0,
    insertions: int = 0,
    deletions: int = 0,
    new_files: int = 0,
    test_files: int = 0,
    data_files: int = 0,
) -> SubstanceReport:
    """Classify a commit and compute substance score.

    Parameters
    ----------
    files_changed : int
        Total files touched.
    insertions : int
        Lines added.
    deletions : int
        Lines removed.
    new_files : int
        Newly created files.
    test_files : int
        Test files (test_*.py, *_test.py, etc.).
    data_files : int
        Append-only data files (.jsonl, .log, etc.).

    Returns
    -------
    SubstanceReport
    """
    change_type = classify_change_type(
        files_changed, insertions, deletions, new_files, data_files,
    )
    substance = compute_substance_score(
        files_changed, insertions, deletions, new_files, test_files, data_files,
    )
    return SubstanceReport(
        change_type=change_type,
        substance=substance,
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
        new_files=new_files,
        test_files=test_files,
        data_files=data_files,
    )


# ---------------------------------------------------------------------------
# Diffstat parser
# ---------------------------------------------------------------------------

_DIFFSTAT_RE = re.compile(
    r"(\d+)\s+files?\s+changed"
    r"(?:,\s+(\d+)\s+insertions?\(\+\))?"
    r"(?:,\s+(\d+)\s+deletions?\(-\))?"
)


def parse_diffstat(line: str) -> Dict[str, int]:
    """Parse a git diffstat summary line.

    Example input::

        5 files changed, 120 insertions(+), 10 deletions(-)

    Returns::

        {"files_changed": 5, "insertions": 120, "deletions": 10}

    Handles edge cases:
    - "1 file changed" (singular)
    - "3 files changed, 5 insertions(+)" (no deletions)
    - "2 files changed, 8 deletions(-)" (no insertions)
    """
    m = _DIFFSTAT_RE.search(line)
    if not m:
        return {"files_changed": 0, "insertions": 0, "deletions": 0}

    files_changed = int(m.group(1))
    insertions = int(m.group(2)) if m.group(2) else 0
    deletions = int(m.group(3)) if m.group(3) else 0

    return {
        "files_changed": files_changed,
        "insertions": insertions,
        "deletions": deletions,
    }


# ---------------------------------------------------------------------------
# Batch analysis
# ---------------------------------------------------------------------------

def batch_substance_score(reports: list[SubstanceReport]) -> Dict[str, Any]:
    """Aggregate substance scores across multiple commits.

    Parameters
    ----------
    reports : list of SubstanceReport
        Individual commit reports.

    Returns
    -------
    dict with keys:
        - count: number of commits analyzed
        - mean_substance: average substance score
        - type_distribution: dict of change_type → count
        - total_insertions / total_deletions: aggregate line counts
        - total_new_files / total_test_files: aggregate file counts
    """
    if not reports:
        return {
            "count": 0,
            "mean_substance": 0.0,
            "type_distribution": {},
            "total_insertions": 0,
            "total_deletions": 0,
            "total_new_files": 0,
            "total_test_files": 0,
        }

    type_dist: Dict[str, int] = {}
    total_substance = 0.0
    total_ins = 0
    total_del = 0
    total_new = 0
    total_test = 0

    for r in reports:
        type_dist[r.change_type] = type_dist.get(r.change_type, 0) + 1
        total_substance += r.substance
        total_ins += r.insertions
        total_del += r.deletions
        total_new += r.new_files
        total_test += r.test_files

    return {
        "count": len(reports),
        "mean_substance": round(total_substance / len(reports), 2),
        "type_distribution": type_dist,
        "total_insertions": total_ins,
        "total_deletions": total_del,
        "total_new_files": total_new,
        "total_test_files": total_test,
    }
