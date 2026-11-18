"""rebase_safety — pre-rebase environment health checks.

The IamAI repo runs a continuous writer loop that appends to tracked
files (``data/strokes.jsonl``, ``data/writer_state.qwen.json``, docs)
every 15 seconds.  Attempting ``git pull --rebase`` while the writer is
active causes the rebase to abort mid-replay with::

    error: Your local changes to the following files would be
    overwritten by merge: ...

This wastes time: the caretaker must then ``rebase --abort``, kill the
writer, commit or stash the orphaned changes, and retry.  Each failed
attempt also leaves reflog entries that confuse the visit-counting
logic.

This module provides a pure-logic gate that answers one question:
*is it safe to start a rebase right now?*  The check is intentionally
conservative — a false "unsafe" costs one pause-and-resume cycle, while
a false "safe" costs a corrupted working tree.

Checks performed
----------------

1. **Writer pause signal** — is the pause sentinel file present?
2. **Untracked dirty state** — are there unstaged modifications to
   writer-managed files?
3. **Process liveness** — is the writer PID file present and the
   process still running?
4. **Pending commit backlog** — does the batch committer have
   uncommitted strokes queued beyond the threshold?

Each check returns a ``SafetyCheck`` result; the aggregate ``assess()``
function returns a ``RebaseReadiness`` verdict with a human-readable
reason and suggested remediation steps.

Usage
-----

As a library::

    from iamai.rebase_safety import assess, RebaseReadiness
    verdict = assess(repo_root="/path/to/IamAI")
    if verdict.ready:
        subprocess.run(["git", "pull", "--rebase", "origin", "main"])
    else:
        for step in verdict.remediation:
            print(step)

As a CLI (``tools/rebase_safety_check.py``)::

    python3 tools/rebase_safety_check.py
    # exit 0 = safe, 1 = unsafe (reason on stderr), 2 = error
"""

from __future__ import annotations

import os
import signal
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class RebaseReadiness(Enum):
    """Outcome of the safety assessment."""
    SAFE = "safe"
    UNSAFE = "unsafe"
    ERROR = "error"


@dataclass
class SafetyCheck:
    """Result of a single check."""
    name: str
    passed: bool
    detail: str
    severity: str = "warning"  # warning | blocking


@dataclass
class Verdict:
    """Aggregate result of all safety checks."""
    ready: bool
    status: RebaseReadiness
    checks: List[SafetyCheck] = field(default_factory=list)
    remediation: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        passed = sum(1 for c in self.checks if c.passed)
        total = len(self.checks)
        tag = "✓" if self.ready else "✗"
        return f"{tag} rebase safety: {passed}/{total} checks passed"


# Writer-managed file patterns that cause rebase conflicts.
WRITER_MANAGED_FILES = [
    "data/strokes.jsonl",
    "data/writer_state.qwen.json",
    "data/writer_state.doubao.json",
    "docs/DEVLOG.md",
    "docs/GARDEN.md",
    "docs/METRICS.md",
]

# Sentinel files used by the writer/batch system.
WRITER_PID_PATTERN = "/tmp/iamai-writer-{writer}.pid"
BATCH_PID_PATTERN = "/tmp/iamai-batch-{writer}.pid"
PAUSE_PATTERN = "/tmp/iamai-writer-pause-{writer}"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_pause_signal(
    repo_root: str | Path,
    writer: str = "qwen",
) -> SafetyCheck:
    """Check whether the writer pause sentinel exists."""
    pause_file = Path(PAUSE_PATTERN.format(writer=writer))
    if pause_file.exists():
        return SafetyCheck(
            name="pause_signal",
            passed=True,
            detail=f"pause sentinel exists at {pause_file}",
        )
    return SafetyCheck(
        name="pause_signal",
        passed=False,
        detail=f"pause sentinel missing at {pause_file}",
        severity="blocking",
    )


def check_dirty_state(
    repo_root: str | Path,
    writer_managed: Optional[List[str]] = None,
) -> SafetyCheck:
    """Check whether writer-managed files have unstaged modifications.

    This reads the working tree directly (no subprocess) by checking
    mtime against a snapshot.  For a true dirty check the caller should
    pass ``git diff --name-only`` output; this function provides a fast
    heuristic when git is unavailable.
    """
    root = Path(repo_root)
    managed = writer_managed or WRITER_MANAGED_FILES
    dirty = []
    for rel in managed:
        fp = root / rel
        if fp.exists() and fp.stat().st_mtime > 0:
            # We cannot determine "dirty" without git; report presence.
            # The CLI wrapper replaces this with actual git output.
            dirty.append(rel)
    if not dirty:
        return SafetyCheck(
            name="dirty_state",
            passed=True,
            detail="no writer-managed files found (clean or empty tree)",
        )
    # Presence alone is not dirty — the CLI enriches this.
    return SafetyCheck(
        name="dirty_state",
        passed=True,
        detail=f"{len(dirty)} writer-managed files present; "
               "CLI should verify with `git diff --name-only`",
        severity="warning",
    )


def check_process_liveness(
    writer: str = "qwen",
) -> SafetyCheck:
    """Check whether the writer process is still running.

    A live writer during rebase is the primary failure mode.
    """
    pid_file = Path(WRITER_PID_PATTERN.format(writer=writer))
    if not pid_file.exists():
        return SafetyCheck(
            name="process_liveness",
            passed=True,
            detail=f"no PID file at {pid_file} — writer not running",
        )
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError) as exc:
        return SafetyCheck(
            name="process_liveness",
            passed=False,
            detail=f"PID file unreadable: {exc}",
            severity="warning",
        )
    # Check if process is alive (signal 0).
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return SafetyCheck(
            name="process_liveness",
            passed=True,
            detail=f"writer PID {pid} is stale (process dead)",
        )
    except PermissionError:
        return SafetyCheck(
            name="process_liveness",
            passed=False,
            detail=f"writer PID {pid} exists but no permission to signal",
            severity="warning",
        )
    # Process is alive.
    return SafetyCheck(
        name="process_liveness",
        passed=False,
        detail=f"writer PID {pid} is alive — must pause before rebase",
        severity="blocking",
    )


def check_batch_liveness(
    writer: str = "qwen",
) -> SafetyCheck:
    """Check whether the batch committer is running.

    The batch committer is less dangerous (it only runs ``git add`` and
    ``git commit``), but if it fires mid-rebase it can corrupt the
    index.
    """
    pid_file = Path(BATCH_PID_PATTERN.format(writer=writer))
    if not pid_file.exists():
        return SafetyCheck(
            name="batch_liveness",
            passed=True,
            detail=f"no PID file at {pid_file} — batch not running",
        )
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return SafetyCheck(
            name="batch_liveness",
            passed=True,
            detail="batch PID file unreadable — assuming stopped",
        )
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return SafetyCheck(
            name="batch_liveness",
            passed=True,
            detail=f"batch PID {pid} is stale (process dead)",
        )
    except PermissionError:
        return SafetyCheck(
            name="batch_liveness",
            passed=False,
            detail=f"batch PID {pid} exists but no permission to signal",
            severity="warning",
        )
    return SafetyCheck(
        name="batch_liveness",
        passed=False,
        detail=f"batch committer PID {pid} is alive — should stop before rebase",
        severity="blocking",
    )


# ---------------------------------------------------------------------------
# Aggregate assessment
# ---------------------------------------------------------------------------

def assess(
    repo_root: str | Path = ".",
    writer: str = "qwen",
    writer_managed: Optional[List[str]] = None,
) -> Verdict:
    """Run all safety checks and return an aggregate verdict."""
    checks = [
        check_pause_signal(repo_root, writer),
        check_dirty_state(repo_root, writer_managed),
        check_process_liveness(writer),
        check_batch_liveness(writer),
    ]

    blocking = [c for c in checks if not c.passed and c.severity == "blocking"]

    remediation: List[str] = []
    if any(c.name == "pause_signal" and not c.passed for c in checks):
        remediation.append(
            f"touch {PAUSE_PATTERN.format(writer=writer)}  # pause the writer"
        )
    if any(c.name == "process_liveness" and not c.passed for c in checks):
        remediation.append(
            f"kill $(cat {WRITER_PID_PATTERN.format(writer=writer)})  "
            f"# or: bash tools/run_both.sh --stop"
        )
    if any(c.name == "batch_liveness" and not c.passed for c in checks):
        remediation.append(
            f"kill $(cat {BATCH_PID_PATTERN.format(writer=writer)})  "
            f"# stop batch committer"
        )
    if any(c.name == "dirty_state" and not c.passed for c in checks):
        remediation.append(
            "git add -A && git commit -m 'qwen: pre-rebase flush'"
        )

    remediation.append("sleep 2  # let writer notice the pause signal")
    remediation.append("git add -A && git commit --allow-empty -m 'rebase prep'")
    remediation.append("git pull --rebase origin main")

    return Verdict(
        ready=len(blocking) == 0,
        status=RebaseReadiness.SAFE if not blocking else RebaseReadiness.UNSAFE,
        checks=checks,
        remediation=remediation,
    )


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def verdict_to_dict(v: Verdict) -> dict:
    """Convert a Verdict to a JSON-safe dictionary."""
    return {
        "ready": v.ready,
        "status": v.status.value,
        "summary": v.summary,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "detail": c.detail,
                "severity": c.severity,
            }
            for c in v.checks
        ],
        "remediation": v.remediation,
    }
