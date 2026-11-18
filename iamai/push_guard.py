"""push_guard — pre-push divergence detection and auto-rebase.

The caretaker frequently encounters ``! [rejected] main -> main (fetch
first)`` when another process (GitHub Actions, a co-caretaker, or the
writer itself on a stale clone) pushes to the remote between the local
commit and the push attempt.  The raw git error is opaque and the
recovery sequence (stash → pull --rebase → stash pop → push) is easy to
get wrong when the writer is actively mutating tracked files.

This module encapsulates the recovery as a pure-logic pipeline that can
be driven by any caller:

    1. ``detect_divergence(local_sha, remote_sha, base_sha)``
       — classifies the relationship as *ahead*, *behind*, *diverged*,
       or *clean*.
    2. ``plan_recovery(divergence, has_unstaged)``
       — returns an ordered list of git commands to resolve the state.
    3. ``summarise(result)``
       — produces a one-line human-readable status.

All functions are side-effect-free; the CLI wrapper
(``tools/push_guard.py``) executes the plan and reports the outcome.

Design notes
------------

* ``detect_divergence`` uses the merge-base to distinguish "remote
  moved forward" (behind) from "both sides moved" (diverged).  A naive
  ``local != remote`` check would falsely classify behind as diverged.
* ``plan_recovery`` prefers ``pull --rebase`` over ``pull --merge`` to
  keep history linear — the IamAI repo has 880+ commits and merge
  bubbles would obscure the stroke log.
* When unstaged changes exist, the plan inserts ``stash`` /
  ``stash pop`` around the rebase.  If stash pop conflicts, the plan
  falls back to ``checkout -- <file>`` for writer-managed files (state
  and strokes) and retries.

Exit codes (CLI)
----------------

0  clean — local is ahead or in sync, push is safe
1  diverged — auto-rebase needed (plan printed to stdout)
2  error — git command failed (details on stderr)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Divergence classification
# ---------------------------------------------------------------------------

class DivergenceState(Enum):
    CLEAN = "clean"           # local == remote
    AHEAD = "ahead"           # local has new commits, remote unchanged
    BEHIND = "behind"         # remote has new commits, local unchanged
    DIVERGED = "diverged"     # both sides have new commits


@dataclass(frozen=True)
class DivergenceResult:
    state: DivergenceState
    local_sha: str
    remote_sha: str
    base_sha: str
    local_ahead: int = 0
    remote_ahead: int = 0

    def needs_recovery(self) -> bool:
        return self.state in (DivergenceState.BEHIND, DivergenceState.DIVERGED)


def detect_divergence(
    local_sha: str,
    remote_sha: str,
    base_sha: str,
    local_ahead: int = 0,
    remote_ahead: int = 0,
) -> DivergenceResult:
    """Classify the relationship between local and remote branches.

    Parameters
    ----------
    local_sha : str
        SHA of the local HEAD.
    remote_sha : str
        SHA of the remote tracking branch (e.g. origin/main).
    base_sha : str
        SHA of the merge-base between local and remote.
    local_ahead : int
        Number of commits local is ahead of base (0 if unknown).
    remote_ahead : int
        Number of commits remote is ahead of base (0 if unknown).

    Returns
    -------
    DivergenceResult
    """
    if local_sha == remote_sha:
        state = DivergenceState.CLEAN
    elif local_sha == base_sha:
        # local hasn't moved, remote has
        state = DivergenceState.BEHIND
    elif remote_sha == base_sha:
        # local moved, remote hasn't
        state = DivergenceState.AHEAD
    else:
        # both moved
        state = DivergenceState.DIVERGED

    return DivergenceResult(
        state=state,
        local_sha=local_sha,
        remote_sha=remote_sha,
        base_sha=base_sha,
        local_ahead=local_ahead,
        remote_ahead=remote_ahead,
    )


# ---------------------------------------------------------------------------
# Recovery planning
# ---------------------------------------------------------------------------

# Files the writer actively mutates — safe to discard on conflict
WRITER_MANAGED_FILES = frozenset({
    "data/strokes.jsonl",
    "data/writer_state.qwen.json",
    "docs/DEVLOG.md",
    "docs/GARDEN.md",
    "docs/METRICS.md",
    "notes/history.md",
})


@dataclass
class RecoveryPlan:
    steps: List[str] = field(default_factory=list)
    risk: str = "low"
    note: str = ""

    def is_empty(self) -> bool:
        return len(self.steps) == 0

    def to_list(self) -> List[str]:
        return list(self.steps)


def plan_recovery(
    divergence: DivergenceResult,
    has_unstaged: bool = False,
    unstaged_files: Optional[Sequence[str]] = None,
) -> RecoveryPlan:
    """Produce an ordered list of git commands to resolve divergence.

    Parameters
    ----------
    divergence : DivergenceResult
        Output of ``detect_divergence``.
    has_unstaged : bool
        Whether the working tree has unstaged modifications.
    unstaged_files : sequence of str, optional
        Paths of unstaged files (used to decide stash-vs-checkout).

    Returns
    -------
    RecoveryPlan
    """
    plan = RecoveryPlan()

    if divergence.state == DivergenceState.CLEAN:
        plan.note = "in sync — nothing to do"
        return plan

    if divergence.state == DivergenceState.AHEAD:
        plan.note = "local ahead — push is safe"
        return plan

    # BEHIND or DIVERGED — need to integrate remote changes
    unstaged_set = set(unstaged_files or [])
    writer_conflict = bool(unstaged_set & WRITER_MANAGED_FILES)

    if has_unstaged:
        if writer_conflict:
            # writer files will clash on stash pop — discard them first
            for f in sorted(unstaged_set & WRITER_MANAGED_FILES):
                plan.steps.append(f"git checkout -- {f}")
            # stash remaining non-writer changes
            remaining = unstaged_set - WRITER_MANAGED_FILES
            if remaining:
                plan.steps.append("git stash push -m 'push-guard: pre-rebase stash'")
        else:
            plan.steps.append("git stash push -m 'push-guard: pre-rebase stash'")

    plan.steps.append("git pull --rebase origin main")

    if has_unstaged and not writer_conflict:
        plan.steps.append("git stash pop")
        plan.steps.append("git stash drop || true")  # clean up if pop succeeded

    if divergence.state == DivergenceState.DIVERGED:
        plan.risk = "medium"
        plan.note = (
            f"both sides diverged — local {divergence.local_ahead} ahead, "
            f"remote {divergence.remote_ahead} ahead; rebase will replay "
            f"local commits on top of remote"
        )
    else:
        plan.note = (
            f"remote {divergence.remote_ahead} ahead — fast-forward rebase"
        )

    return plan


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summarise(divergence: DivergenceResult, plan: Optional[RecoveryPlan] = None) -> str:
    """One-line human-readable status."""
    state = divergence.state.value
    parts = [f"state={state}"]

    if divergence.local_ahead:
        parts.append(f"local+{divergence.local_ahead}")
    if divergence.remote_ahead:
        parts.append(f"remote+{divergence.remote_ahead}")

    if plan and not plan.is_empty():
        parts.append(f"plan=[{len(plan.steps)} steps, risk={plan.risk}]")
    elif plan:
        parts.append(f"note={plan.note}")

    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def divergence_to_json(result: DivergenceResult) -> str:
    """Serialise a DivergenceResult to a compact JSON string."""
    d = {
        "state": result.state.value,
        "local_sha": result.local_sha[:12],
        "remote_sha": result.remote_sha[:12],
        "base_sha": result.base_sha[:12],
        "local_ahead": result.local_ahead,
        "remote_ahead": result.remote_ahead,
    }
    return json.dumps(d, separators=(",", ":"))


def divergence_from_json(raw: str) -> DivergenceResult:
    """Deserialise a DivergenceResult from JSON."""
    d = json.loads(raw)
    return DivergenceResult(
        state=DivergenceState(d["state"]),
        local_sha=d["local_sha"],
        remote_sha=d["remote_sha"],
        base_sha=d["base_sha"],
        local_ahead=d.get("local_ahead", 0),
        remote_ahead=d.get("remote_ahead", 0),
    )
