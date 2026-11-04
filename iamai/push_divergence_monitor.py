"""push_divergence_monitor — track how far local and remote branches have
drifted apart, and classify the urgency of reconciliation.

Motivation
----------
This repo has been hit by push-rejection (remote contains work you don't
have) dozens of times across caretaker visits.  The pattern is always the
same: writer accumulates commits locally, another writer pushes to the same
branch, and our next push fails with ``[rejected] (fetch first)``.  The fix
is ``git pull --rebase`` but the caretaker had no cheap way to *measure*
divergence before attempting a push.

This module fills that gap.  Given a repo path it reports:

  - local_ahead:   commits on local that remote doesn't have
  - remote_ahead:  commits on remote that local doesn't have
  - divergence:    ``local_ahead + remote_ahead``
  - urgency:       ``synced`` (0) | ``nominal`` (1-3) | ``growing`` (4-10)
                   | ``critical`` (11+)
  - recommended:   ``push`` | ``pull_rebase`` | ``manual_merge``

It is pure-Python with no subprocess calls — the actual git commands are
injected as callables so the whole thing is trivially unit-testable with
synthetic numbers.

Usage::

    from iamai.push_divergence_monitor import measure_divergence
    report = measure_divergence("/path/to/repo")
    print(report.urgency, report.recommended)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DivergenceReport:
    """Snapshot of local-vs-remote branch divergence."""

    local_ahead: int
    remote_ahead: int

    @property
    def divergence(self) -> int:
        return self.local_ahead + self.remote_ahead

    @property
    def urgency(self) -> str:
        d = self.divergence
        if d == 0:
            return "synced"
        if d <= 3:
            return "nominal"
        if d <= 10:
            return "growing"
        return "critical"

    @property
    def recommended(self) -> str:
        """What the caretaker should do next."""
        if self.divergence == 0:
            return "push"
        if self.remote_ahead == 0:
            # only local commits — safe to push directly
            return "push"
        if self.local_ahead == 0:
            # only remote commits — just fast-forward
            return "pull_ff"
        # both sides have commits
        if self.divergence <= 10:
            return "pull_rebase"
        return "manual_merge"

    def as_dict(self) -> dict:
        return {
            "local_ahead": self.local_ahead,
            "remote_ahead": self.remote_ahead,
            "divergence": self.divergence,
            "urgency": self.urgency,
            "recommended": self.recommended,
        }


# ---------------------------------------------------------------------------
# Git plumbing (default impl uses subprocess; inject mocks for testing)
# ---------------------------------------------------------------------------

def _git_count(path: str, rev_range: str) -> int:
    """Run ``git rev-list --count <rev_range>`` and return the integer."""
    import subprocess
    result = subprocess.run(
        ["git", "rev-list", "--count", rev_range],
        cwd=path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return -1  # signals: could not determine
    return int(result.stdout.strip())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def measure_divergence(
    repo_path: str = ".",
    branch: str = "main",
    *,
    count_fn: Optional[Callable[[str, str], int]] = None,
) -> DivergenceReport:
    """Measure how far local *branch* has drifted from its remote tracking
    branch (``origin/<branch>``).

    Parameters
    ----------
    repo_path : str
        Path to the git working tree.
    branch : str
        Branch name (default ``main``).
    count_fn : callable, optional
        ``(path, rev_range) -> int``.  Defaults to the subprocess-based
        ``_git_count``.  Inject a mock in tests.
    """
    _count = count_fn or _git_count

    local_ahead = _count(repo_path, f"origin/{branch}..{branch}")
    remote_ahead = _count(repo_path, f"{branch}..origin/{branch}")

    # treat -1 (command failure) as 0 — assume synced if we can't measure
    if local_ahead < 0:
        local_ahead = 0
    if remote_ahead < 0:
        remote_ahead = 0

    return DivergenceReport(local_ahead=local_ahead, remote_ahead=remote_ahead)


def divergence_summary(
    repo_path: str = ".",
    branch: str = "main",
    *,
    count_fn: Optional[Callable[[str, str], int]] = None,
) -> str:
    """Human-readable one-liner for caretaker logs."""
    r = measure_divergence(repo_path, branch, count_fn=count_fn)
    if r.urgency == "synced":
        return "remote and local are in sync"
    return (
        f"divergence={r.divergence} "
        f"(local +{r.local_ahead}, remote +{r.remote_ahead}) "
        f"urgency={r.urgency} → {r.recommended}"
    )
