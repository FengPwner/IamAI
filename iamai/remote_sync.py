"""Safe remote synchronization for multi-writer repositories.

When multiple agents push to the same branch, push races are inevitable:
agent A pushes, then agent B's push is rejected because the remote moved.
This module encodes the recovery protocol as a pure-logic state machine
so callers (caretaker, batch, manual visit) can drive it without each
re-implementing the same stash-merge-push dance.

The protocol has four phases:

1. **probe** — fetch remote, compare HEAD to origin/main, decide if sync
   is needed.
2. **quiesce** — temporarily stop the local writer so no files change
   mid-merge.
3. **merge** — pull with merge (not rebase) to avoid rewriting history
   that other writers may have based commits on.
4. **push** — push the merged result; on failure, retry once after a
   fresh fetch in case another writer pushed in the window.

Each phase returns a `SyncStep` result so callers can log, abort, or
retry at fine granularity.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List, Optional


class SyncPhase(enum.Enum):
    """Phases of the sync protocol."""
    PROBE = "probe"
    QUIESCE = "quiesce"
    MERGE = "merge"
    PUSH = "push"
    DONE = "done"


class SyncStatus(enum.Enum):
    """Outcome of a single phase."""
    OK = "ok"
    SKIPPED = "skipped"
    CONFLICT = "conflict"
    ERROR = "error"
    RETRY = "retry"


@dataclass
class SyncStep:
    """Result of one sync phase."""
    phase: SyncPhase
    status: SyncStatus
    message: str = ""
    details: dict = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status in (SyncStatus.OK, SyncStatus.SKIPPED)


@dataclass
class SyncPlan:
    """Ordered sequence of phases needed to sync.

    Callers walk the plan phase by phase, stopping on the first failure.
    """
    steps: List[SyncStep] = field(default_factory=list)
    current_phase: SyncPhase = SyncPhase.PROBE

    @property
    def is_done(self) -> bool:
        return self.current_phase == SyncPhase.DONE

    @property
    def succeeded(self) -> bool:
        return all(s.succeeded for s in self.steps)

    def record(self, step: SyncStep) -> None:
        """Record a completed step and advance to the next phase."""
        self.steps.append(step)
        if not step.succeeded:
            self.current_phase = SyncPhase.DONE
            return
        # Advance to next phase
        phases = list(SyncPhase)
        idx = phases.index(self.current_phase)
        self.current_phase = phases[idx + 1] if idx + 1 < len(phases) else SyncPhase.DONE

    def summary(self) -> str:
        """One-line human-readable summary of the sync outcome."""
        if not self.steps:
            return "no steps executed"
        ok_count = sum(1 for s in self.steps if s.succeeded)
        fail_count = len(self.steps) - ok_count
        if fail_count == 0:
            return f"sync complete: {ok_count} phases ok"
        failed = [s.phase.value for s in self.steps if not s.succeeded]
        return f"sync stopped at {', '.join(failed)}: {self.steps[-1].message}"


def needs_sync(local_sha: str, remote_sha: str, base_sha: str) -> SyncStep:
    """Probe phase: determine if sync is needed.

    Args:
        local_sha: HEAD commit SHA of local branch
        remote_sha: HEAD commit SHA of origin/main (after fetch)
        base_sha: merge-base of local and remote

    Returns:
        SyncStep indicating whether sync is needed
    """
    if local_sha == remote_sha:
        return SyncStep(
            phase=SyncPhase.PROBE,
            status=SyncStatus.SKIPPED,
            message="local and remote are identical, nothing to sync",
            details={"sha": local_sha},
        )
    if base_sha == local_sha:
        # Local is behind remote — fast-forward is possible
        return SyncStep(
            phase=SyncPhase.PROBE,
            status=SyncStatus.OK,
            message="local is behind remote, fast-forward merge needed",
            details={"local": local_sha, "remote": remote_sha, "mode": "ff"},
        )
    if base_sha == remote_sha:
        # Local is ahead — just push
        return SyncStep(
            phase=SyncPhase.PROBE,
            status=SyncStatus.OK,
            message="local is ahead of remote, push only",
            details={"local": local_sha, "remote": remote_sha, "mode": "push"},
        )
    # Diverged — need merge
    return SyncStep(
        phase=SyncPhase.PROBE,
        status=SyncStatus.OK,
        message="branches diverged, merge required",
        details={"local": local_sha, "remote": remote_sha, "base": base_sha, "mode": "merge"},
    )


def check_dirty_paths(dirty_paths: List[str]) -> SyncStep:
    """Quiesce phase: verify no uncommitted changes block the merge.

    Args:
        dirty_paths: list of modified/untracked file paths from git status

    Returns:
        SyncStep — OK if clean, ERROR if dirty (caller must stash/commit first)
    """
    if not dirty_paths:
        return SyncStep(
            phase=SyncPhase.QUIESCE,
            status=SyncStatus.OK,
            message="working tree clean",
        )
    return SyncStep(
        phase=SyncPhase.QUIESCE,
        status=SyncStatus.ERROR,
        message=f"{len(dirty_paths)} dirty file(s) block merge",
        details={"dirty": dirty_paths[:10]},
    )


def evaluate_merge_result(exit_code: int, conflict_paths: List[str]) -> SyncStep:
    """Merge phase: evaluate the outcome of `git merge`.

    Args:
        exit_code: process exit code from git merge
        conflict_paths: files with merge conflicts (empty if none)

    Returns:
        SyncStep reflecting merge outcome
    """
    if exit_code == 0 and not conflict_paths:
        return SyncStep(
            phase=SyncPhase.MERGE,
            status=SyncStatus.OK,
            message="merge completed cleanly",
        )
    if conflict_paths:
        return SyncStep(
            phase=SyncPhase.MERGE,
            status=SyncStatus.CONFLICT,
            message=f"{len(conflict_paths)} file(s) have conflicts",
            details={"conflicts": conflict_paths},
        )
    return SyncStep(
        phase=SyncPhase.MERGE,
        status=SyncStatus.ERROR,
        message=f"merge failed with exit code {exit_code}",
        details={"exit_code": exit_code},
    )


def evaluate_push_result(exit_code: int, stderr: str, attempt: int = 1) -> SyncStep:
    """Push phase: evaluate the outcome of `git push`.

    Args:
        exit_code: process exit code
        stderr: stderr output from git push
        attempt: which attempt this is (1 or 2)

    Returns:
        SyncStep — OK on success, RETRY if rejected and attempt < 2, ERROR otherwise
    """
    if exit_code == 0:
        return SyncStep(
            phase=SyncPhase.PUSH,
            status=SyncStatus.OK,
            message="push succeeded",
            details={"attempt": attempt},
        )
    if "rejected" in stderr.lower() and attempt < 2:
        return SyncStep(
            phase=SyncPhase.PUSH,
            status=SyncStatus.RETRY,
            message="push rejected, retry after fresh fetch",
            details={"attempt": attempt, "stderr": stderr[:500]},
        )
    return SyncStep(
        phase=SyncPhase.PUSH,
        status=SyncStatus.ERROR,
        message=f"push failed (attempt {attempt})",
        details={"exit_code": exit_code, "stderr": stderr[:500]},
    )


def plan_sync(local_sha: str, remote_sha: str, base_sha: str,
              dirty_paths: Optional[List[str]] = None) -> SyncPlan:
    """Build a sync plan by running probe and quiesce phases.

    This is a convenience for callers that want to plan first, then
    execute merge/push manually with real subprocess calls.

    Args:
        local_sha: local HEAD SHA
        remote_sha: remote HEAD SHA
        base_sha: merge-base SHA
        dirty_paths: optional list of dirty file paths

    Returns:
        SyncPlan ready for the caller to drive through merge/push
    """
    plan = SyncPlan()

    probe = needs_sync(local_sha, remote_sha, base_sha)
    plan.record(probe)
    if not probe.succeeded or probe.status == SyncStatus.SKIPPED:
        return plan

    if dirty_paths is not None:
        quiesce = check_dirty_paths(dirty_paths)
        plan.record(quiesce)

    return plan
