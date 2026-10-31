"""Push divergence resolver — classify and recover from push rejections.

Visits 441-452 all hit the same wall: the writer and batch committer
produce local commits while the remote advances (from another writer or
a guoban batch).  When the caretaker arrives, ``git push`` is rejected
because the remote has work the local branch lacks.

This module captures the *decision logic* for resolving that divergence,
turning nine visits of ad-hoc fixes into a single, testable classifier.

Divergence types
----------------

- ``"clean_ahead"``      — local is strictly ahead; push should succeed.
- ``"fast_forward"``     — remote is ahead, local has no new commits;
                           a simple ``pull`` (fast-forward) resolves it.
- ``"diverged_trivial"`` — both sides have commits, but they touch
                           different files; rebase is safe and conflict-
                           free.
- ``"diverged_conflict"`` — both sides touch the same files; rebase
                           will produce conflicts that need manual or
                           ``-X theirs`` resolution.
- ``"diverged_state"``   — the conflicting files are writer state files
                           (JSON, JSONL) where union merge or taking
                           the newer side is always correct.

Recovery strategies
-------------------

- ``"push"``          — just push (clean_ahead).
- ``"pull_ff"``       — fast-forward pull (fast_forward).
- ``"rebase"``        — ``pull --rebase`` (diverged_trivial).
- ``"rebase_theirs"`` — ``pull --rebase -X theirs`` (diverged_state).
- ``"reset_apply"``   — reset to merge-base, pull, re-apply local
                         diff (diverged_conflict when rebase fails).

Design choices
--------------

- **Pure function.**  Takes commit SHAs, file lists, and divergence
  metadata; returns a dataclass with the recommended strategy.
- **No git calls.**  The caller inspects the repository and feeds the
  results in; this module only classifies and recommends.
- **Outcome tracking.**  ``record_outcome()`` lets the caretaker log
  whether the recommended strategy succeeded, building an evidence
  base for future visits.

Usage::

    from iamai.push_divergence_resolver import classify_divergence

    report = classify_divergence(
        local_commits=2,
        remote_commits=1,
        local_files=["data/strokes.jsonl", "docs/DEVLOG.md"],
        remote_files=["guoban/guoban-note.md"],
        state_files=["data/strokes.jsonl", "data/writer_state.qwen.json"],
    )
    print(report.strategy)   # "rebase"
    print(report.summary)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DivergenceReport:
    """Classification of a push divergence and recommended recovery."""

    divergence_type: str       # clean_ahead | fast_forward | diverged_*
    strategy: str              # push | pull_ff | rebase | rebase_theirs | reset_apply
    local_commits: int
    remote_commits: int
    overlapping_files: List[str] = field(default_factory=list)
    state_file_conflicts: List[str] = field(default_factory=list)
    confidence: str = "high"   # high | medium | low
    summary: str = ""


@dataclass
class OutcomeRecord:
    """Result of applying a recommended strategy."""

    divergence_type: str
    strategy: str
    success: bool
    conflict_count: int = 0
    notes: str = ""


# ---------------------------------------------------------------------------
# State file patterns
# ---------------------------------------------------------------------------

# Files where union merge or "take newer" is always safe.
_STATE_FILE_PATTERNS = frozenset({
    "data/strokes.jsonl",
    "data/writer_state.qwen.json",
    "data/writer_state.doubao.json",
    "data/writer_state.kimi.json",
    "data/writer_state.guoban.json",
})


def _is_state_file(path: str, extra_patterns: Set[str] = frozenset()) -> bool:
    """Check if a file path matches a known state file pattern."""
    if path in _STATE_FILE_PATTERNS or path in extra_patterns:
        return True
    # JSON state files under data/ are always append-or-overwrite
    if path.startswith("data/") and (
        path.endswith(".json") or path.endswith(".jsonl")
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------

def classify_divergence(
    local_commits: int,
    remote_commits: int,
    local_files: Optional[List[str]] = None,
    remote_files: Optional[List[str]] = None,
    state_files: Optional[List[str]] = None,
) -> DivergenceReport:
    """Classify push divergence and recommend a recovery strategy.

    Parameters
    ----------
    local_commits : int
        Number of local commits not on remote.
    remote_commits : int
        Number of remote commits not on local.
    local_files : list of str, optional
        Files modified by local commits (relative paths).
    remote_files : list of str, optional
        Files modified by remote commits (relative paths).
    state_files : list of str, optional
        Additional file patterns to treat as state files.

    Returns
    -------
    DivergenceReport
    """
    local_files = local_files or []
    remote_files = remote_files or []
    extra_patterns = set(state_files or [])

    # -- trivial cases ---------------------------------------------------------
    if remote_commits == 0 and local_commits > 0:
        return DivergenceReport(
            divergence_type="clean_ahead",
            strategy="push",
            local_commits=local_commits,
            remote_commits=0,
            summary=f"local {local_commits} ahead, push directly",
        )

    if local_commits == 0 and remote_commits > 0:
        return DivergenceReport(
            divergence_type="fast_forward",
            strategy="pull_ff",
            local_commits=0,
            remote_commits=remote_commits,
            summary=f"remote {remote_commits} ahead, fast-forward pull",
        )

    if local_commits == 0 and remote_commits == 0:
        return DivergenceReport(
            divergence_type="clean_ahead",
            strategy="push",
            local_commits=0,
            remote_commits=0,
            summary="branches in sync, nothing to do",
        )

    # -- both sides have commits: check overlap --------------------------------
    local_set = set(local_files)
    remote_set = set(remote_files)
    overlap = sorted(local_set & remote_set)

    state_conflicts = [
        f for f in overlap if _is_state_file(f, extra_patterns)
    ]
    non_state_conflicts = [f for f in overlap if f not in state_conflicts]

    # -- classify --------------------------------------------------------------
    if not overlap:
        # No file overlap → clean rebase
        return DivergenceReport(
            divergence_type="diverged_trivial",
            strategy="rebase",
            local_commits=local_commits,
            remote_commits=remote_commits,
            summary=(
                f"diverged ({local_commits} local, {remote_commits} remote) "
                f"but no file overlap — rebase is safe"
            ),
        )

    if not non_state_conflicts:
        # All conflicts are in state files → rebase with -X theirs
        return DivergenceReport(
            divergence_type="diverged_state",
            strategy="rebase_theirs",
            local_commits=local_commits,
            remote_commits=remote_commits,
            overlapping_files=overlap,
            state_file_conflicts=state_conflicts,
            confidence="high",
            summary=(
                f"diverged ({local_commits} local, {remote_commits} remote), "
                f"conflicts only in state files {state_conflicts} — "
                f"rebase -X theirs or reset+apply"
            ),
        )

    # Real content conflicts in non-state files
    return DivergenceReport(
        divergence_type="diverged_conflict",
        strategy="reset_apply",
        local_commits=local_commits,
        remote_commits=remote_commits,
        overlapping_files=overlap,
        state_file_conflicts=state_conflicts,
        confidence="medium",
        summary=(
            f"diverged ({local_commits} local, {remote_commits} remote), "
            f"conflicting non-state files {non_state_conflicts} — "
            f"reset to merge-base, pull, re-apply local diff"
        ),
    )


# ---------------------------------------------------------------------------
# Outcome tracking
# ---------------------------------------------------------------------------

_outcome_log: List[OutcomeRecord] = []


def record_outcome(
    report: DivergenceReport,
    success: bool,
    conflict_count: int = 0,
    notes: str = "",
) -> OutcomeRecord:
    """Record the outcome of applying a recommended strategy.

    Parameters
    ----------
    report : DivergenceReport
        The report whose strategy was attempted.
    success : bool
        Whether the strategy resolved the divergence.
    conflict_count : int
        Number of merge conflicts encountered (0 = clean).
    notes : str
        Free-text notes for the caretaker log.

    Returns
    -------
    OutcomeRecord
    """
    record = OutcomeRecord(
        divergence_type=report.divergence_type,
        strategy=report.strategy,
        success=success,
        conflict_count=conflict_count,
        notes=notes,
    )
    _outcome_log.append(record)
    return record


def strategy_success_rate(strategy: str) -> Optional[float]:
    """Calculate historical success rate for a given strategy.

    Returns None if no outcomes have been recorded for that strategy.
    """
    records = [r for r in _outcome_log if r.strategy == strategy]
    if not records:
        return None
    successes = sum(1 for r in records if r.success)
    return successes / len(records)


def outcome_summary() -> Dict[str, Dict[str, int]]:
    """Summarize outcomes grouped by strategy."""
    summary: Dict[str, Dict[str, int]] = {}
    for record in _outcome_log:
        if record.strategy not in summary:
            summary[record.strategy] = {"success": 0, "failure": 0}
        key = "success" if record.success else "failure"
        summary[record.strategy][key] += 1
    return summary


def clear_outcomes() -> None:
    """Clear the in-memory outcome log (for testing)."""
    _outcome_log.clear()
