"""Mortality: is this repo alive, undead, or dead?

A self-writing repository has failure modes that a simple heartbeat cannot
distinguish.  The heartbeat answers "did a stroke arrive recently?" — but a
caretaker needs a richer diagnosis:

- **alive**: processes running, strokes flowing, commits landing.
- **zombie**: processes running but no strokes — the writer loop is stuck,
  looping on a lock, or silently erroring without exiting.
- **ghost**: strokes flowing but no commits — the batch committer died while
  the writer kept producing, filling the backlog until the next caretaker visit.
- **dead**: no processes, no strokes, no commits.  The lights are off.

This module combines signals from heartbeat, process_supervisor, and commit
cadence into a single ``diagnose()`` call that returns a classification and
the raw evidence.  Pure functions — no global state, no side effects, easy to
test with synthetic inputs.

Usage::

    from iamai.mortality import classify, diagnose

    verdict = classify(
        writer_alive=True,
        batch_alive=True,
        stroke_gap_seconds=12,
        commit_gap_seconds=300,
        cadence_seconds=15,
        commit_interval_seconds=600,
    )
    print(verdict["state"])   # "alive"

    # Or the richer diagnosis:
    info = diagnose(
        writer_alive=True,
        batch_alive=False,
        stroke_gap_seconds=20,
        commit_gap_seconds=1200,
        cadence_seconds=15,
        commit_interval_seconds=600,
    )
    print(info["state"])      # "ghost"
    print(info["advice"])     # "restart batch committer"
"""

from __future__ import annotations


def classify(
    *,
    writer_alive: bool,
    batch_alive: bool,
    stroke_gap_seconds: float,
    commit_gap_seconds: float,
    cadence_seconds: int = 15,
    commit_interval_seconds: int = 600,
) -> dict:
    """Classify repo liveness from raw signals.

    Args:
        writer_alive: whether the writer process is running.
        batch_alive: whether the batch committer process is running.
        stroke_gap_seconds: seconds since the last stroke.
        commit_gap_seconds: seconds since the last commit.
        cadence_seconds: expected stroke interval.
        commit_interval_seconds: expected commit interval.

    Returns:
        A dict with ``state`` (str) and the input signals echoed back.
    """
    stroke_fresh = stroke_gap_seconds <= cadence_seconds * 2
    commit_fresh = commit_gap_seconds <= commit_interval_seconds * 2

    if writer_alive and stroke_fresh:
        state = "alive"
    elif writer_alive and not stroke_fresh:
        state = "zombie"
    elif not writer_alive and stroke_fresh:
        # Writer just died but strokes are still recent
        state = "zombie"
    elif batch_alive and commit_fresh and not writer_alive:
        # Batch is committing old backlog but no new strokes
        state = "ghost"
    elif not writer_alive and not batch_alive:
        state = "dead"
    else:
        # Writer dead, batch alive but commits stale — ghost or dead
        state = "ghost" if commit_fresh else "dead"

    return {
        "state": state,
        "writer_alive": writer_alive,
        "batch_alive": batch_alive,
        "stroke_gap_seconds": stroke_gap_seconds,
        "commit_gap_seconds": commit_gap_seconds,
    }


_ADVICE = {
    "alive": "everything nominal, no action needed",
    "zombie": "restart writer — process is up but producing nothing",
    "ghost": "restart batch committer — strokes exist but are not committed",
    "dead": "restart both writer and batch committer",
}


def diagnose(
    *,
    writer_alive: bool,
    batch_alive: bool,
    stroke_gap_seconds: float,
    commit_gap_seconds: float,
    cadence_seconds: int = 15,
    commit_interval_seconds: int = 600,
) -> dict:
    """Richer diagnosis: classification plus advice and severity.

    Returns:
        A dict with ``state``, ``advice``, ``severity``, and raw signals.
    """
    base = classify(
        writer_alive=writer_alive,
        batch_alive=batch_alive,
        stroke_gap_seconds=stroke_gap_seconds,
        commit_gap_seconds=commit_gap_seconds,
        cadence_seconds=cadence_seconds,
        commit_interval_seconds=commit_interval_seconds,
    )

    state = base["state"]
    severity_map = {
        "alive": "ok",
        "zombie": "warning",
        "ghost": "warning",
        "dead": "critical",
    }

    return {
        **base,
        "advice": _ADVICE[state],
        "severity": severity_map[state],
    }


def mortality_summary(diagnosis: dict) -> str:
    """One-line human-readable summary of a diagnosis.

    Args:
        diagnosis: output from ``diagnose()``.

    Returns:
        A short string suitable for a caretaker log or dashboard line.
    """
    state = diagnosis["state"]
    gap = diagnosis.get("stroke_gap_seconds", 0)
    commit_gap = diagnosis.get("commit_gap_seconds", 0)

    if state == "alive":
        return f"alive — last stroke {gap:.0f}s ago, last commit {commit_gap:.0f}s ago"
    elif state == "zombie":
        return f"zombie — writer up but no stroke for {gap:.0f}s, restart needed"
    elif state == "ghost":
        return f"ghost — strokes uncommitted for {commit_gap:.0f}s, batch restart needed"
    else:
        return f"dead — writer down {gap:.0f}s, batch down {commit_gap:.0f}s, full restart needed"
