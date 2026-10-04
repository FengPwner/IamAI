"""Recovery checklist: have we actually recovered from a reclamation event?

After a process-reclamation event, the repo goes through a fixed sequence:

    1. restart the processes
    2. flush any uncommitted backlog
    3. push local commits to the remote
    4. verify the writer is producing new strokes

Skipping any step leaves the repo in a state that *looks* healthy but isn't —
processes running but 50 unpushed commits, or a clean working tree with a dead
writer. This module turns that sequence into a single structured check so
a caretaker (human or automated) can ask "are we recovered?" and get a real
answer, not a feeling.

The recovery state is one of:

    FULLY_RECOVERED  — all checks pass, the pipeline is healthy
    PARTIAL          — some checks pass but others don't
    NOT_STARTED      — no recovery actions have been taken yet

This is deliberately simple. A reclamation event is not the time for cleverness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .watchdog import WatchdogReport, watchdog


class RecoveryState(Enum):
    NOT_STARTED = "not_started"
    PARTIAL = "partial"
    FULLY_RECOVERED = "fully_recovered"


@dataclass
class RecoveryChecklist:
    processes_alive: bool = False
    backlog_flushed: bool = False
    remote_synced: bool = False
    writer_producing: bool = False
    error: Optional[str] = None

    @property
    def state(self) -> RecoveryState:
        checks = [
            self.processes_alive,
            self.backlog_flushed,
            self.remote_synced,
            self.writer_producing,
        ]
        if all(checks):
            return RecoveryState.FULLY_RECOVERED
        if any(checks):
            return RecoveryState.PARTIAL
        return RecoveryState.NOT_STARTED

    @property
    def next_step(self) -> Optional[str]:
        if not self.processes_alive:
            return "restart processes: `bash tools/run_both.sh`"
        if not self.backlog_flushed:
            return "flush backlog: `git add -A && git commit -m 'flush backlog'`"
        if not self.remote_synced:
            return "push to remote: `git push origin main`"
        if not self.writer_producing:
            return "wait for new strokes or check writer log"
        return None  # all good

    def summary(self) -> str:
        lines = [
            f"recovery: {self.state.value}",
            f"  processes alive:    {'yes' if self.processes_alive else 'NO'}",
            f"  backlog flushed:    {'yes' if self.backlog_flushed else 'NO'}",
            f"  remote synced:      {'yes' if self.remote_synced else 'NO'}",
            f"  writer producing:   {'yes' if self.writer_producing else 'NO'}",
        ]
        if self.next_step:
            lines.append(f"  -> next: {self.next_step}")
        if self.error:
            lines.append(f"  error: {self.error}")
        return "\n".join(lines)


def assess(
    watchdog_report: Optional[WatchdogReport] = None,
    writer_id: str = "qwen",
    repo: Optional[Path] = None,
    pid_dir: Optional[Path] = None,
) -> RecoveryChecklist:
    """Run all recovery checks using a watchdog report.

    Args:
        watchdog_report: pre-computed watchdog report, or None to run fresh.
        writer_id: which writer to check.
        repo: path to the git repository root.
        pid_dir: directory containing pidfiles.
    """
    if watchdog_report is None:
        watchdog_report = watchdog(
            writer_id=writer_id, repo=repo, pid_dir=pid_dir,
        )

    checklist = RecoveryChecklist(
        processes_alive=watchdog_report.all_alive,
        backlog_flushed=watchdog_report.uncommitted_files == 0,
        remote_synced=watchdog_report.unpushed_commits == 0,
    )

    # Writer producing: we need heartbeat data for this.
    # If heartbeat is importable, check it; otherwise leave as unknown (False).
    try:
        from .heartbeat import beat
        beat_report = beat(writer_id=writer_id, root=repo)
        checklist.writer_producing = not beat_report.get("stalled", True)
    except Exception as e:
        checklist.error = f"heartbeat check failed: {e}"
        checklist.writer_producing = False

    return checklist
