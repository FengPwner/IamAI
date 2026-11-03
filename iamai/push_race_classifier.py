"""push_race_classifier — classify push-rejection scenarios and prescribe recovery.

Every caretaker visit that involves a push rejection follows the same
decision tree: is the working tree dirty? is there a stash pile? did
the remote advance?  This module encodes that tree so the recovery
sequence can be computed, not re-discovered each time.

Classification
--------------

==================  ====================================================
scenario            meaning
==================  ====================================================
clean_push          local ahead, remote unchanged, clean tree → just push
dirty_tree          uncommitted changes block any git operation
stale_stash         stash pile has entries from prior failed recovery cycles
remote_advanced     remote HEAD moved since last fetch (diverged)
diverged_dirty      both remote advanced AND local tree is dirty
locked              a lock file or stale process prevents operations
==================  ====================================================

Recovery sequences are returned as ordered lists of shell-level steps,
each annotated with its purpose.  The caller decides whether to execute
them.

Zero dependencies.  stdlib only.

>>> classify(tree_dirty=False, remote_ahead=False, stash_count=0, lock=False)
'clean_push'
>>> steps = recovery_steps('diverged_dirty')
>>> steps[0]['action']
'kill writer'
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(
    tree_dirty: bool,
    remote_ahead: bool,
    stash_count: int = 0,
    lock: bool = False,
) -> str:
    """Classify the current push-rejection scenario.

    Args:
        tree_dirty: working tree has uncommitted changes
        remote_ahead: remote has commits local doesn't (fetch shows divergence)
        stash_count: number of entries in git stash list
        lock: a lock file or stale process is blocking operations

    Returns:
        One of: "clean_push", "dirty_tree", "stale_stash",
        "remote_advanced", "diverged_dirty", "locked"

    Examples:
        >>> classify(tree_dirty=False, remote_ahead=False)
        'clean_push'
        >>> classify(tree_dirty=True, remote_ahead=False)
        'dirty_tree'
        >>> classify(tree_dirty=False, remote_ahead=True)
        'remote_advanced'
        >>> classify(tree_dirty=True, remote_ahead=True)
        'diverged_dirty'
        >>> classify(tree_dirty=False, remote_ahead=False, stash_count=5)
        'stale_stash'
        >>> classify(tree_dirty=False, remote_ahead=False, lock=True)
        'locked'
    """
    if lock:
        return "locked"
    if tree_dirty and remote_ahead:
        return "diverged_dirty"
    if tree_dirty:
        return "dirty_tree"
    if remote_ahead:
        return "remote_advanced"
    if stash_count > 0:
        return "stale_stash"
    return "clean_push"


# ---------------------------------------------------------------------------
# Recovery steps
# ---------------------------------------------------------------------------

_RECOVERY: dict[str, list[dict[str, str]]] = {
    "clean_push": [
        {"action": "git push origin main", "purpose": "local is ahead, no obstacles"},
    ],
    "dirty_tree": [
        {"action": "kill writer", "purpose": "freeze working tree"},
        {"action": "git add -A && git commit", "purpose": "capture in-flight state"},
        {"action": "git push origin main", "purpose": "push committed changes"},
        {"action": "restart writer", "purpose": "resume cadence"},
    ],
    "remote_advanced": [
        {"action": "git pull --rebase origin main", "purpose": "integrate remote changes"},
        {"action": "git push origin main", "purpose": "push rebased local commits"},
    ],
    "diverged_dirty": [
        {"action": "kill writer", "purpose": "freeze working tree"},
        {"action": "git add -A && git commit", "purpose": "capture in-flight state"},
        {"action": "git pull --rebase origin main", "purpose": "integrate remote changes"},
        {"action": "git push origin main", "purpose": "push rebased local commits"},
        {"action": "restart writer", "purpose": "resume cadence"},
    ],
    "stale_stash": [
        {"action": "git stash list", "purpose": "inspect stash pile"},
        {"action": "git stash drop (each)", "purpose": "remove stale entries"},
        {"action": "git push origin main", "purpose": "push with clean stash state"},
    ],
    "locked": [
        {"action": "identify lock holder", "purpose": "find stale PID or process"},
        {"action": "remove lock", "purpose": "clear blocking state"},
        {"action": "assess tree state", "purpose": "re-classify after lock removal"},
    ],
}


def recovery_steps(scenario: str) -> list[dict[str, str]]:
    """Return the ordered recovery sequence for a given scenario.

    Args:
        scenario: one of the classify() return values

    Returns:
        list of dicts with 'action' and 'purpose' keys

    Examples:
        >>> steps = recovery_steps('clean_push')
        >>> len(steps)
        1
        >>> steps[0]['action']
        'git push origin main'
        >>> steps = recovery_steps('diverged_dirty')
        >>> steps[0]['action']
        'kill writer'
        >>> steps[-1]['action']
        'restart writer'
    """
    return list(_RECOVERY.get(scenario, []))


# ---------------------------------------------------------------------------
# Step count
# ---------------------------------------------------------------------------

def recovery_cost(scenario: str) -> int:
    """Number of steps in the recovery sequence.

    Useful for estimating complexity and comparing scenarios.

    Examples:
        >>> recovery_cost('clean_push')
        1
        >>> recovery_cost('diverged_dirty')
        5
        >>> recovery_cost('unknown')
        0
    """
    return len(recovery_steps(scenario))


# ---------------------------------------------------------------------------
# Scenario summary
# ---------------------------------------------------------------------------

def scenario_summary(
    tree_dirty: bool,
    remote_ahead: bool,
    stash_count: int = 0,
    lock: bool = False,
) -> dict[str, Any]:
    """Full diagnosis: scenario, recovery steps, and cost.

    Args:
        tree_dirty: working tree has uncommitted changes
        remote_ahead: remote has new commits
        stash_count: entries in git stash
        lock: lock file or stale process present

    Returns:
        dict with scenario, steps, step_count, inputs

    Examples:
        >>> s = scenario_summary(tree_dirty=True, remote_ahead=True)
        >>> s["scenario"]
        'diverged_dirty'
        >>> s["step_count"]
        5
    """
    scenario = classify(tree_dirty, remote_ahead, stash_count, lock)
    steps = recovery_steps(scenario)
    return {
        "scenario": scenario,
        "steps": steps,
        "step_count": len(steps),
        "inputs": {
            "tree_dirty": tree_dirty,
            "remote_ahead": remote_ahead,
            "stash_count": stash_count,
            "lock": lock,
        },
    }


# ---------------------------------------------------------------------------
# Historical note
# ---------------------------------------------------------------------------

NOTE = """
The push race is this repo's most frequent failure mode (visits 503–509).
Every cycle: writer produces strokes → batch commits → push fails because
remote advanced or tree is dirty.  The recovery is always a permutation
of: kill, commit, pull rebase, push, restart.  This module encodes that
permutation so future caretakers compute the answer instead of
re-discovering it.
"""
