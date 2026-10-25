"""remote_drift — detect and measure divergence between local and remote branches.

When multiple writers or caretakers push to the same repository, the local
branch can silently diverge from its remote tracking branch.  The next
``git push`` will then be rejected with ``non-fast-forward``, blocking the
entire commit pipeline until someone does a pull-rebase.

This module fills the gap between:

- ``commit_pipeline_latency``, which measures time from stroke to push
  but does not examine *why* a push might fail;
- ``push_race_recovery`` (notes), which documents the recovery steps
  after a race but does not provide a reusable detector;
- ``stall_forecaster``, which predicts writer stalls but does not look
  at the push path at all.

The drift analyser answers: *is the local branch ahead of, behind, or
diverged from its remote, and how costly will the reconciliation be?*

Metrics
-------

========================  ================================================
metric                    what it measures
========================  ================================================
ahead_count               commits local has that remote lacks
behind_count              commits remote has that local lacks
diverged                  bool: both ahead > 0 and behind > 0
reconciliation_cost       estimated effort to reconcile (0-1 scale)
drift_score               weighted blend: 0 = synced, 1 = badly split
========================  ================================================

Usage::

    from iamai.remote_drift import (
        DriftReport, measure_drift, classify_drift,
    )

    report = measure_drift(repo_path="/path/to/repo", branch="main")
    print(report.drift_score)    # 0.0 .. 1.0
    print(report.verdict)        # "synced" / "ahead" / "behind" / "diverged"
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------

DEFAULT_BRANCH = "main"
DEFAULT_REMOTE = "origin"

# thresholds for reconciliation cost scoring
LOW_COST_AHEAD = 3          # <=3 ahead commits is cheap (just push)
LOW_COST_BEHIND = 3         # <=3 behind commits is cheap (fast-forward pull)
HIGH_COST_BEHIND = 10       # >10 behind commits is expensive (rebase conflict risk)

# weights for the composite drift score
DEFAULT_WEIGHTS = {
    "ahead": 0.25,
    "behind": 0.45,          # behind is more dangerous — blocks pushes
    "divergence": 0.30,      # divergence is the worst — requires rebase
}

VERDICT_THRESHOLDS = {
    "synced": 0.0,
    "ahead": 0.01,
    "behind": 0.01,
    "diverged": 0.3,
}


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DriftReport:
    """Result of measuring drift between a local branch and its remote."""

    branch: str
    remote: str
    ahead_count: int
    behind_count: int
    ahead_hashes: tuple[str, ...] = ()
    behind_hashes: tuple[str, ...] = ()
    reconciliation_cost: float = 0.0
    drift_score: float = 0.0

    @property
    def diverged(self) -> bool:
        return self.ahead_count > 0 and self.behind_count > 0

    @property
    def verdict(self) -> str:
        if self.ahead_count == 0 and self.behind_count == 0:
            return "synced"
        if self.diverged:
            return "diverged"
        if self.ahead_count > 0:
            return "ahead"
        return "behind"

    @property
    def push_will_succeed(self) -> bool:
        """Heuristic: push succeeds only when not behind and not diverged."""
        return self.behind_count == 0

    def summary(self) -> str:
        if self.verdict == "synced":
            return f"{self.branch}: synced with {self.remote}/{self.branch}"
        parts = []
        if self.ahead_count:
            parts.append(f"{self.ahead_count} ahead")
        if self.behind_count:
            parts.append(f"{self.behind_count} behind")
        return (
            f"{self.branch}: {' and '.join(parts)} "
            f"(cost={self.reconciliation_cost:.2f}, "
            f"drift={self.drift_score:.2f}, "
            f"verdict={self.verdict})"
        )


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------

def _run_git(repo_path: str | Path, *args: str) -> str:
    """Run a git command in the given repo, return stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo_path)] + list(args),
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip()


def _count_commits(repo_path: str | Path, range_spec: str) -> int:
    """Count commits in a revision range (e.g. 'origin/main..HEAD')."""
    output = _run_git(repo_path, "rev-list", "--count", range_spec)
    return int(output)


def _list_hashes(repo_path: str | Path, range_spec: str, max_count: int = 20) -> tuple[str, ...]:
    """List commit hashes in a revision range, capped at max_count."""
    output = _run_git(
        repo_path, "rev-list", f"--max-count={max_count}", range_spec,
    )
    if not output:
        return ()
    return tuple(output.splitlines())


def _merge_base(repo_path: str | Path, local: str, remote_ref: str) -> str:
    """Find the merge base between local and remote."""
    return _run_git(repo_path, "merge-base", local, remote_ref)


# ---------------------------------------------------------------------------
# core analysis
# ---------------------------------------------------------------------------

def _reconciliation_cost(ahead: int, behind: int) -> float:
    """Estimate the effort to reconcile, 0.0 (trivial) to 1.0 (painful).

    Cost factors:
    - Being ahead is free (just push), unless you also need to rebase.
    - Being behind means pulling — cheap if few commits, expensive if many.
    - Being diverged means rebasing — always costs something.
    """
    if ahead == 0 and behind == 0:
        return 0.0

    # ahead-only: almost free
    if behind == 0:
        return min(ahead / (LOW_COST_AHEAD * 4), 0.2)

    # behind-only: scales with count
    if ahead == 0:
        if behind <= LOW_COST_BEHIND:
            return 0.1 + 0.05 * behind
        if behind <= HIGH_COST_BEHIND:
            return 0.3 + 0.04 * (behind - LOW_COST_BEHIND)
        return min(0.6 + 0.02 * (behind - HIGH_COST_BEHIND), 0.85)

    # diverged: baseline cost + scaling
    base = 0.4
    ahead_penalty = min(ahead * 0.03, 0.15)
    behind_penalty = min(behind * 0.04, 0.35)
    return min(base + ahead_penalty + behind_penalty, 1.0)


def _drift_score(ahead: int, behind: int, weights: dict[str, float]) -> float:
    """Compute the composite drift score, 0.0 (synced) to 1.0 (badly split)."""
    if ahead == 0 and behind == 0:
        return 0.0

    w = {**DEFAULT_WEIGHTS, **weights}

    # normalise counts to 0-1 range (asymptotic via sigmoid-like mapping)
    ahead_norm = 1.0 - 1.0 / (1.0 + ahead * 0.2)
    behind_norm = 1.0 - 1.0 / (1.0 + behind * 0.15)
    diverge_norm = 1.0 if (ahead > 0 and behind > 0) else 0.0

    score = (
        w["ahead"] * ahead_norm
        + w["behind"] * behind_norm
        + w["divergence"] * diverge_norm
    )
    return min(score, 1.0)


def measure_drift(
    repo_path: str | Path = ".",
    branch: str = DEFAULT_BRANCH,
    remote: str = DEFAULT_REMOTE,
    weights: Optional[dict[str, float]] = None,
    max_hashes: int = 20,
) -> DriftReport:
    """Measure drift between a local branch and its remote tracking branch.

    Parameters
    ----------
    repo_path : str or Path
        Path to the git repository.
    branch : str
        Local branch name (default: "main").
    remote : str
        Remote name (default: "origin").
    weights : dict, optional
        Override default weights for the composite score.
    max_hashes : int
        Maximum number of commit hashes to include in the report.

    Returns
    -------
    DriftReport
        Complete drift analysis.

    Raises
    ------
    RuntimeError
        If git commands fail (e.g., not a git repo, branch not found).
    """
    repo = Path(repo_path).resolve()
    remote_ref = f"{remote}/{branch}"

    ahead_range = f"{remote_ref}..{branch}"
    behind_range = f"{branch}..{remote_ref}"

    ahead = _count_commits(repo, ahead_range)
    behind = _count_commits(repo, behind_range)

    ahead_hashes = _list_hashes(repo, ahead_range, max_count=max_hashes) if ahead else ()
    behind_hashes = _list_hashes(repo, behind_range, max_count=max_hashes) if behind else ()

    cost = _reconciliation_cost(ahead, behind)
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    score = _drift_score(ahead, behind, w)

    return DriftReport(
        branch=branch,
        remote=remote,
        ahead_count=ahead,
        behind_count=behind,
        ahead_hashes=ahead_hashes,
        behind_hashes=behind_hashes,
        reconciliation_cost=cost,
        drift_score=score,
    )


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

def classify_drift(report: DriftReport) -> str:
    """Return a human-readable classification of the drift state.

    Categories:
    - "clean": synced or trivially ahead (safe to push)
    - "needs-pull": behind but not diverged (pull --rebase then push)
    - "needs-rebase": diverged (rebase required before push)
    - "stale": very far behind (>10 commits), likely needs manual review
    """
    if report.verdict == "synced":
        return "clean"
    if report.verdict == "ahead":
        return "clean"
    if report.behind_count > HIGH_COST_BEHIND:
        return "stale"
    if report.diverged:
        return "needs-rebase"
    return "needs-pull"


def is_push_safe(report: DriftReport) -> bool:
    """Quick check: will ``git push`` succeed right now?"""
    return report.push_will_succeed


def suggest_action(report: DriftReport) -> str:
    """Suggest the next git command to reconcile."""
    classification = classify_drift(report)
    if classification == "clean":
        if report.ahead_count > 0:
            return f"git push {report.remote} {report.branch}"
        return "nothing to do"
    if classification == "needs-pull":
        return f"git pull --rebase {report.remote} {report.branch}"
    if classification == "needs-rebase":
        return (
            f"git fetch {report.remote} && "
            f"git rebase {report.remote}/{report.branch}"
        )
    # stale
    return (
        f"git fetch {report.remote} && "
        f"git log --oneline {report.branch}..{report.remote}/{report.branch} "
        f"# review {report.behind_count} remote commits before rebasing"
    )


# ---------------------------------------------------------------------------
# pure helpers for testing without git
# ---------------------------------------------------------------------------

def analyse_counts(ahead: int, behind: int, weights: Optional[dict[str, float]] = None) -> DriftReport:
    """Build a DriftReport from raw counts only — no git access needed.

    Useful for unit testing the scoring logic without a real repository.
    """
    cost = _reconciliation_cost(ahead, behind)
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    score = _drift_score(ahead, behind, w)
    return DriftReport(
        branch="main",
        remote="origin",
        ahead_count=ahead,
        behind_count=behind,
        reconciliation_cost=cost,
        drift_score=score,
    )
