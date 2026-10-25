"""Rebase safety — assess whether it is safe to rebase before pulling.

A self-writing repository that pushes hundreds of commits per day will
occasionally diverge from the remote.  When that happens, the caretaker
must ``git pull --rebase``, but a rebase can fail or produce conflicts
if the working tree is dirty, there are too many stashes, or the writer
process is still producing changes.

This module answers one question: **is it safe to rebase right now?**

The assessment is a pure function — it inspects a snapshot of the repo
state, not the repo itself — so the caller is responsible for gathering
the inputs.

Usage::

    from iamai.rebase_safety import assess_rebase_safety, RepoSnapshot

    snap = RepoSnapshot(
        uncommitted_files=3,
        stash_count=2,
        local_only_commits=1,
        remote_only_commits=1,
        writer_running=True,
        batch_running=True,
    )
    report = assess_rebase_safety(snap)
    print(report.verdict)   # "caution"
    print(report.reason)
    report.recommended_action()  # "pause writer, commit, then rebase"

Verdicts
--------
- ``safe``     — go ahead and rebase.
- ``caution``  — rebase may work but some risk factors are present.
- ``blocked``  — do NOT rebase now; fix the listed issues first.

Design choices
--------------
- **Pure function.**  No subprocess calls, no git plumbing.
- **Explicit inputs.**  The ``RepoSnapshot`` dataclass makes it obvious
  what state was inspected.
- **Actionable output.**  Every verdict comes with a recommended action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RepoSnapshot:
    """Point-in-time snapshot of repo state relevant to rebase safety.

    Parameters
    ----------
    uncommitted_files : int
        Number of files with unstaged or staged but uncommitted changes.
    stash_count : int
        Number of entries in ``git stash list``.
    local_only_commits : int
        Commits present locally but not on the remote (ahead count).
    remote_only_commits : int
        Commits present on the remote but not locally (behind count).
    writer_running : bool
        Whether the writer process is currently active.
    batch_running : bool
        Whether the batch committer process is currently active.
    merge_conflict : bool
        Whether the repo is currently in a merge or rebase conflict state.
    rebase_in_progress : bool
        Whether a rebase is already underway.
    """

    uncommitted_files: int = 0
    stash_count: int = 0
    local_only_commits: int = 0
    remote_only_commits: int = 0
    writer_running: bool = False
    batch_running: bool = False
    merge_conflict: bool = False
    rebase_in_progress: bool = False


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

SAFE = "safe"
CAUTION = "caution"
BLOCKED = "blocked"


@dataclass(frozen=True)
class RebaseSafetyReport:
    """Assessment of whether it is safe to rebase now.

    Attributes
    ----------
    verdict : str
        One of ``SAFE``, ``CAUTION``, or ``BLOCKED``.
    reasons : list[str]
        Human-readable reasons for the verdict.
    risk_score : int
        0 (perfectly safe) to 10 (absolutely do not rebase).
    """

    verdict: str
    reasons: List[str] = field(default_factory=list)
    risk_score: int = 0

    def recommended_action(self) -> str:
        """Return a one-line action suggestion based on the verdict."""
        if self.verdict == SAFE:
            return "proceed with rebase"
        if self.verdict == BLOCKED:
            if any("conflict" in r for r in self.reasons):
                return "resolve the in-progress conflict first, then retry"
            if any("rebase" in r.lower() for r in self.reasons):
                return "abort or continue the in-progress rebase first"
            if any("writer" in r for r in self.reasons):
                return "stop the writer and batch processes, commit, then rebase"
            if any("uncommitted" in r for r in self.reasons):
                return "commit or stash all changes before rebasing"
            if any("stash" in r for r in self.reasons):
                return "clean up stale stashes, then rebase cautiously"
            return "fix the issues listed in reasons before rebasing"
        # CAUTION
        if any("writer" in r for r in self.reasons):
            return "pause writer, commit dirty files, then rebase"
        if any("stash" in r for r in self.reasons):
            return "rebase is possible but stash pile is deep — proceed carefully"
        return "rebase with caution — review the reasons first"

    @property
    def summary(self) -> str:
        """One-line summary combining verdict and top reason."""
        top = self.reasons[0] if self.reasons else "no issues found"
        return f"{self.verdict}: {top}"


# ---------------------------------------------------------------------------
# Assessment logic
# ---------------------------------------------------------------------------

# Thresholds
_STASH_WARNING = 10
_STASH_DANGER = 50
_DIVERGENCE_WARNING = 5
_UNCOMMITTED_WITH_WRITER = "writer is running with uncommitted changes"


def assess_rebase_safety(snap: RepoSnapshot) -> RebaseSafetyReport:
    """Assess whether it is safe to rebase the current branch.

    Parameters
    ----------
    snap : RepoSnapshot
        A point-in-time snapshot of the repo state.

    Returns
    -------
    RebaseSafetyReport
        The safety assessment with verdict, reasons, and risk score.
    """
    reasons: List[str] = []
    risk = 0

    # --- hard blockers (force BLOCKED) ------------------------------------

    if snap.rebase_in_progress:
        reasons.append("a rebase is already in progress")
        risk += 5

    if snap.merge_conflict:
        reasons.append("repo is in a merge/rebase conflict state")
        risk += 5

    # Any uncommitted files block rebase (git refuses to rebase dirty tree).
    if snap.uncommitted_files > 0 and snap.writer_running:
        reasons.append(_UNCOMMITTED_WITH_WRITER)
        risk += 6  # hard block: writer + dirty tree
    elif snap.uncommitted_files > 5:
        reasons.append(
            f"{snap.uncommitted_files} uncommitted files — working tree is very dirty"
        )
        risk += 5
    elif snap.uncommitted_files > 0:
        reasons.append(
            f"{snap.uncommitted_files} uncommitted file(s) — commit or stash first"
        )
        risk += 5

    # --- soft warnings (push toward CAUTION) ------------------------------

    if snap.stash_count >= _STASH_DANGER:
        reasons.append(
            f"{snap.stash_count} stashes accumulated — stash pile is dangerously deep"
        )
        risk += 3
    elif snap.stash_count >= _STASH_WARNING:
        reasons.append(
            f"{snap.stash_count} stashes — consider cleaning up before adding more"
        )
        risk += 2

    if snap.local_only_commits >= _DIVERGENCE_WARNING:
        reasons.append(
            f"{snap.local_only_commits} local-only commits — "
            "rebase will replay all of them"
        )
        risk += 2

    if snap.writer_running and snap.uncommitted_files == 0:
        reasons.append("writer is running — it may produce changes during rebase")
        risk += 2

    if snap.batch_running:
        reasons.append("batch committer is running — it may commit during rebase")
        risk += 1

    if snap.remote_only_commits > 10:
        reasons.append(
            f"{snap.remote_only_commits} remote-only commits — "
            "rebase may produce many conflicts"
        )
        risk += 2

    # --- verdict ----------------------------------------------------------

    risk = min(risk, 10)

    if risk >= 5:
        verdict = BLOCKED
    elif risk >= 2:
        verdict = CAUTION
    else:
        verdict = SAFE

    return RebaseSafetyReport(
        verdict=verdict,
        reasons=reasons,
        risk_score=risk,
    )


# ---------------------------------------------------------------------------
# Quick CLI helper
# ---------------------------------------------------------------------------

def quick_check(
    uncommitted: int = 0,
    stashes: int = 0,
    ahead: int = 0,
    behind: int = 0,
    writer_up: bool = False,
    batch_up: bool = False,
) -> str:
    """One-liner convenience for shell integration.

    Returns a human-readable string like ``"safe: proceed with rebase"``
    or ``"blocked: 3 uncommitted files — commit or stash first"``.
    """
    snap = RepoSnapshot(
        uncommitted_files=uncommitted,
        stash_count=stashes,
        local_only_commits=ahead,
        remote_only_commits=behind,
        writer_running=writer_up,
        batch_running=batch_up,
    )
    report = assess_rebase_safety(snap)
    return f"{report.verdict}: {report.recommended_action()}"
