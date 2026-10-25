"""Change scope: classify commits by breadth and size of changes.

In a continuously self-writing repository, most commits are small and
predictable — one or two files, a few dozen lines.  Occasionally a commit
is unexpectedly large (refactor, accidental bulk edit) or unexpectedly
small (empty commit, whitespace-only).  Both deserve attention.

ChangeScope answers: "how big was this commit, and is that normal?"

It works purely on numeric inputs (file count, line additions, line
deletions) so it needs no git plumbing — feed it whatever numbers your
CI already collects.

Usage::

    from iamai.change_scope import ChangeScope, classify

    cs = ChangeScope()
    label = cs.classify(files=2, additions=45, deletions=10)
    # => "normal"

    cs.classify(files=50, additions=3000, deletions=2000)
    # => "large"

    cs.is_anomaly(files=1, additions=0, deletions=0)
    # => True  (empty commit)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

ScopeLabel = Literal["empty", "trivial", "small", "normal", "large", "massive"]


@dataclass
class ChangeScope:
    """Classify commits by change scope and detect anomalies.

    Parameters
    ----------
    small_files : int
        Upper bound (inclusive) on file count for a "small" commit.
    normal_files : int
        Upper bound (inclusive) on file count for a "normal" commit.
    large_files : int
        Upper bound (inclusive) on file count for a "large" commit.
        Anything above this is "massive".
    small_lines : int
        Upper bound on total lines changed (add+del) for "small".
    normal_lines : int
        Upper bound on total lines changed for "normal".
    large_lines : int
        Upper bound on total lines changed for "large".
        Anything above this is "massive".
    """

    small_files: int = 3
    normal_files: int = 10
    large_files: int = 30
    small_lines: int = 30
    normal_lines: int = 200
    large_lines: int = 1000

    _history: list = field(default_factory=list)

    def classify(
        self,
        files: int,
        additions: int = 0,
        deletions: int = 0,
    ) -> ScopeLabel:
        """Return a scope label for one commit.

        The label is the *maximum* of the file-count dimension and the
        line-count dimension, so a commit touching many files but few
        lines still gets flagged.

        Parameters
        ----------
        files : int
            Number of files changed (must be >= 0).
        additions : int
            Lines added (>= 0).
        deletions : int
            Lines deleted (>= 0).

        Returns
        -------
        ScopeLabel — one of "empty", "trivial", "small", "normal",
        "large", "massive".
        """
        files = max(0, files)
        additions = max(0, additions)
        deletions = max(0, deletions)
        total_lines = additions + deletions

        if files == 0 and total_lines == 0:
            return "empty"

        file_label = self._file_scope(files)
        line_label = self._line_scope(total_lines)

        # "trivial" is only used when both dimensions are trivial
        if file_label == "trivial" and line_label == "trivial":
            return "trivial"

        # Otherwise take the larger dimension
        order: list[ScopeLabel] = ["empty", "trivial", "small", "normal", "large", "massive"]
        fi = order.index(file_label) if file_label in order else 0
        li = order.index(line_label) if line_label in order else 0
        return order[max(fi, li)]

    def _file_scope(self, files: int) -> ScopeLabel:
        if files == 0:
            return "empty"
        if files == 1:
            return "trivial"
        if files <= self.small_files:
            return "small"
        if files <= self.normal_files:
            return "normal"
        if files <= self.large_files:
            return "large"
        return "massive"

    def _line_scope(self, total_lines: int) -> ScopeLabel:
        if total_lines == 0:
            return "trivial"
        if total_lines <= self.small_lines:
            return "small"
        if total_lines <= self.normal_lines:
            return "normal"
        if total_lines <= self.large_lines:
            return "large"
        return "massive"

    def is_anomaly(
        self,
        files: int,
        additions: int = 0,
        deletions: int = 0,
    ) -> bool:
        """True if the commit looks unusual and deserves a closer look.

        Anomalies:
        - Empty commits (no files, no lines)
        - Massive commits (far above normal range)
        - Zero-change file touches (files > 0 but 0 lines changed)
        - Deletion-only commits with no additions
        """
        files = max(0, files)
        additions = max(0, additions)
        deletions = max(0, deletions)
        total_lines = additions + deletions

        # Empty commit
        if files == 0 and total_lines == 0:
            return True

        # Massive scope
        if self.classify(files, additions, deletions) == "massive":
            return True

        # File touches with no actual content change
        if files > 0 and total_lines == 0:
            return True

        # Pure deletion (could be cleanup, could be accidental)
        if additions == 0 and deletions > 0:
            return True

        return False

    def record(
        self,
        files: int,
        additions: int = 0,
        deletions: int = 0,
        timestamp: float = 0.0,
    ) -> dict:
        """Classify, store in history, and return a summary dict.

        Useful for building a running log of commit scopes.
        """
        label = self.classify(files, additions, deletions)
        anomaly = self.is_anomaly(files, additions, deletions)
        entry = {
            "files": files,
            "additions": additions,
            "deletions": deletions,
            "total_lines": additions + deletions,
            "label": label,
            "anomaly": anomaly,
            "timestamp": timestamp,
        }
        self._history.append(entry)
        return entry

    def history(self) -> list[dict]:
        """Return all recorded entries."""
        return list(self._history)

    def summary(self) -> dict:
        """Aggregate statistics over recorded history."""
        if not self._history:
            return {
                "total_commits": 0,
                "labels": {},
                "anomaly_count": 0,
                "anomaly_rate": 0.0,
                "avg_files": 0.0,
                "avg_lines": 0.0,
            }

        labels: dict[str, int] = {}
        anomaly_count = 0
        total_files = 0
        total_lines = 0

        for entry in self._history:
            label = entry["label"]
            labels[label] = labels.get(label, 0) + 1
            if entry["anomaly"]:
                anomaly_count += 1
            total_files += entry["files"]
            total_lines += entry["total_lines"]

        n = len(self._history)
        return {
            "total_commits": n,
            "labels": labels,
            "anomaly_count": anomaly_count,
            "anomaly_rate": round(anomaly_count / n, 4) if n > 0 else 0.0,
            "avg_files": round(total_files / n, 2),
            "avg_lines": round(total_lines / n, 2),
        }

    def reset(self) -> None:
        """Clear recorded history."""
        self._history.clear()


def classify_commit(
    files: int,
    additions: int = 0,
    deletions: int = 0,
    thresholds: dict | None = None,
) -> ScopeLabel:
    """One-shot classification without needing to instantiate ChangeScope.

    Parameters
    ----------
    files, additions,deletions : int
        Same as ChangeScope.classify.
    thresholds : dict, optional
        Override default thresholds (keys match ChangeScope fields).
    """
    if thresholds:
        cs = ChangeScope(**thresholds)
    else:
        cs = ChangeScope()
    return cs.classify(files, additions, deletions)


def scope_distribution(commits: list[dict], thresholds: dict | None = None) -> dict:
    """Classify a batch of commits and return aggregate distribution.

    Parameters
    ----------
    commits : list[dict]
        Each dict must have "files", optionally "additions" and "deletions".
    thresholds : dict, optional
        Override default ChangeScope thresholds.

    Returns
    -------
    dict with label counts, total, and anomaly list.
    """
    cs = ChangeScope(**thresholds) if thresholds else ChangeScope()
    labels: dict[str, int] = {}
    anomalies: list[dict] = []

    for i, commit in enumerate(commits):
        files = commit.get("files", 0)
        additions = commit.get("additions", 0)
        deletions = commit.get("deletions", 0)
        label = cs.classify(files, additions, deletions)
        labels[label] = labels.get(label, 0) + 1
        if cs.is_anomaly(files, additions, deletions):
            anomalies.append({"index": i, **commit, "label": label})

    return {
        "total": len(commits),
        "labels": labels,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }
