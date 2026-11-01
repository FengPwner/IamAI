"""stash_hygiene — audit and clean up stale git stashes.

Long-running repos accumulate stashes from aborted rebases, interrupted
pushes, and caretaker visits.  Most become irrelevant within hours but
linger indefinitely.  This module provides:

Public API
----------

``StashEntry(index, name, age_seconds, branch)``
    Immutable record of one stash entry.

``audit(repo_path, max_age_hours=24) -> StashAudit``
    Scan all stashes, classify each as fresh or stale.

``StashAudit``
    Dataclass: entries, stale_count, fresh_count, oldest_age_seconds,
    recommendation.

``prune(repo_path, max_age_hours=24, dry_run=True) -> list[int]``
    Drop stashes older than threshold.  Returns indices dropped.
    dry_run=True (default) returns candidates without modifying anything.

Design choices
--------------

- Pure audit is side-effect-free: only ``git stash list`` is called.
- Prune always asks git to drop by ``stash@{N}`` index, working from
  highest index down so earlier indices stay valid.
- Age calculation uses the stash reflog timestamp, not the commit date,
  because stashes are about *when you set them aside*, not when the
  underlying code was authored.
- No automatic cleanup: the caller (caretaker, cron, CI) decides policy.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class StashEntry:
    """One entry in ``git stash list``."""
    index: int
    name: str
    age_seconds: float
    branch: str

    @property
    def age_hours(self) -> float:
        return self.age_seconds / 3600.0

    @property
    def age_days(self) -> float:
        return self.age_seconds / 86400.0


@dataclass
class StashAudit:
    """Result of scanning all stashes."""
    entries: List[StashEntry] = field(default_factory=list)
    max_age_hours: float = 24.0

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def stale(self) -> List[StashEntry]:
        return [e for e in self.entries if e.age_hours > self.max_age_hours]

    @property
    def fresh(self) -> List[StashEntry]:
        return [e for e in self.entries if e.age_hours <= self.max_age_hours]

    @property
    def stale_count(self) -> int:
        return len(self.stale)

    @property
    def fresh_count(self) -> int:
        return len(self.fresh)

    @property
    def oldest_age_seconds(self) -> float:
        return max((e.age_seconds for e in self.entries), default=0.0)

    @property
    def oldest_age_days(self) -> float:
        return self.oldest_age_seconds / 86400.0

    @property
    def recommendation(self) -> str:
        if self.total == 0:
            return "no stashes — clean"
        if self.stale_count == 0:
            return f"all {self.total} stash(es) fresh — no action needed"
        if self.stale_count == self.total:
            return f"all {self.total} stash(es) stale — safe to drop all"
        return (
            f"{self.stale_count}/{self.total} stale "
            f"(oldest: {self.oldest_age_days:.1f}d) — "
            f"consider pruning"
        )


_STASH_RE = re.compile(
    r"^(stash@\{(\d+)\}):\s*"           # stash@{N}:
    r"(?:WIP on|On)\s+"                  # "WIP on" or "On"
    r"([^:]+)"                           # branch name
)

_UNIX_EPOCH_RE = re.compile(r"(\d{10,})")


def _run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=10, cwd=cwd,
    )


def _parse_stash_list(raw: str, now: float) -> list[StashEntry]:
    """Parse ``git stash list --format`` output into StashEntry objects."""
    entries: list[StashEntry] = []
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        # format: index|timestamp|subject
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        try:
            idx = int(parts[0].replace("stash@{", "").replace("}", ""))
            ts = float(parts[1])
            subject = parts[2].strip()
        except (ValueError, IndexError):
            continue
        age = max(0.0, now - ts)
        # extract branch from subject if present
        branch = "main"
        m = _STASH_RE.match(f"stash@{{{idx}}}: {subject}")
        if m:
            branch = m.group(3).strip()
        entries.append(StashEntry(
            index=idx,
            name=subject,
            age_seconds=age,
            branch=branch,
        ))
    return entries


def audit(repo_path: str, max_age_hours: float = 24.0) -> StashAudit:
    """Scan all stashes and classify them."""
    cwd = str(Path(repo_path).resolve())
    result = _run(
        ["git", "stash", "list", "--format=%gd|%ct|%s"],
        cwd,
    )
    now = time.time()
    entries = _parse_stash_list(result.stdout, now) if result.returncode == 0 else []
    return StashAudit(entries=entries, max_age_hours=max_age_hours)


def prune(
    repo_path: str,
    max_age_hours: float = 24.0,
    dry_run: bool = True,
) -> list[int]:
    """Drop stale stashes.  Returns indices that were (or would be) dropped.

    When ``dry_run=True`` (default), no stashes are actually modified.
    """
    report = audit(repo_path, max_age_hours=max_age_hours)
    stale = sorted(report.stale, key=lambda e: e.index, reverse=True)
    dropped: list[int] = []

    for entry in stale:
        dropped.append(entry.index)
        if not dry_run:
            _run(
                ["git", "stash", "drop", f"stash@{{{entry.index}}}"],
                str(Path(repo_path).resolve()),
            )

    return dropped
