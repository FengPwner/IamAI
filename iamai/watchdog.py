"""Watchdog: is anything alive, and is anything waiting to leave?

The heartbeat module answers "is the writer still writing?" by reading
stroke timestamps. The watchdog answers the orthogonal question: "are
the OS-level processes still running, and is there uncommitted work
piling up?" Both questions matter during a reclamation event — the
heartbeat says the writer stalled, the watchdog says *why*.

A dead pidfile and a stalled heartbeat together mean reclamation.
A live pidfile and a stalled heartbeat mean a hung process.
A dead pidfile and a healthy heartbeat mean the process *just* died
and the last stroke hasn't aged out of the window yet.

None of these are ambiguous when you have both signals.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent


@dataclass
class ProcessStatus:
    name: str
    pid: Optional[int]
    alive: bool
    pidfile: str
    stale_pidfile: bool = False  # pidfile exists but process does not


@dataclass
class WatchdogReport:
    processes: list[ProcessStatus] = field(default_factory=list)
    uncommitted_files: int = 0
    unpushed_commits: int = 0

    @property
    def all_alive(self) -> bool:
        return all(p.alive for p in self.processes)

    @property
    def any_stale_pidfile(self) -> bool:
        return any(p.stale_pidfile for p in self.processes)

    @property
    def needs_restart(self) -> bool:
        return not self.all_alive

    @property
    def needs_push(self) -> bool:
        return self.unpushed_commits > 0

    def as_dict(self) -> dict:
        d = asdict(self)
        d["all_alive"] = self.all_alive
        d["any_stale_pidfile"] = self.any_stale_pidfile
        d["needs_restart"] = self.needs_restart
        d["needs_push"] = self.needs_push
        return d


def _read_pid(path: Path) -> Optional[int]:
    """Read a pidfile. Returns None if the file is missing or unparseable."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return int(text) if text else None
    except (ValueError, OSError):
        return None


def _pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID exists (kill -0)."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def check_process(name: str, pidfile: Path) -> ProcessStatus:
    """Read a pidfile and check whether the process is alive."""
    pid = _read_pid(pidfile)
    if pid is None:
        return ProcessStatus(
            name=name, pid=None, alive=False,
            pidfile=str(pidfile), stale_pidfile=False,
        )
    alive = _pid_alive(pid)
    return ProcessStatus(
        name=name, pid=pid, alive=alive,
        pidfile=str(pidfile), stale_pidfile=not alive,
    )


def _count_uncommitted(repo: Path) -> int:
    """Count files with uncommitted changes (staged + unstaged)."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(repo), timeout=5,
        )
        if result.returncode != 0:
            return 0
        return len([line for line in result.stdout.strip().splitlines() if line.strip()])
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0


def _count_unpushed(repo: Path) -> int:
    """Count commits ahead of origin/main that haven't been pushed."""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            capture_output=True, text=True, cwd=str(repo), timeout=5,
        )
        if result.returncode != 0:
            return 0
        return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return 0


def watchdog(
    writer_id: str = "qwen",
    repo: Optional[Path] = None,
    pid_dir: Optional[Path] = None,
) -> WatchdogReport:
    """Run all watchdog checks and return a structured report.

    Args:
        writer_id: which writer's pidfiles to check.
        repo: path to the git repository root (default: auto-detect).
        pid_dir: directory containing pidfiles (default: /tmp).
    """
    repo = repo or REPO
    pid_dir = pid_dir or Path("/tmp")

    writer_pid = pid_dir / f"iamai-writer-{writer_id}.pid"
    batch_pid = pid_dir / f"iamai-batch-{writer_id}.pid"

    processes = [
        check_process("writer", writer_pid),
        check_process("batch", batch_pid),
    ]

    uncommitted = _count_uncommitted(repo)
    unpushed = _count_unpushed(repo)

    report = WatchdogReport(
        processes=processes,
        uncommitted_files=uncommitted,
        unpushed_commits=unpushed,
    )

    return report


def as_text(report: WatchdogReport) -> str:
    """Render a watchdog report as a human-readable multi-line string."""
    lines = []
    for p in report.processes:
        if p.alive:
            lines.append(f"  {p.name}: running (pid {p.pid})")
        elif p.stale_pidfile:
            lines.append(f"  {p.name}: DEAD (stale pidfile, was pid {p.pid})")
        else:
            lines.append(f"  {p.name}: not running (no pidfile)")

    header = "ALIVE" if report.all_alive else "NEEDS ATTENTION"
    lines.insert(0, f"watchdog: {header}")
    lines.append(f"  uncommitted: {report.uncommitted_files} file(s)")
    lines.append(f"  unpushed: {report.unpushed_commits} commit(s)")

    if report.needs_restart:
        lines.append("  -> restart needed: run `bash tools/run_both.sh`")
    if report.needs_push:
        lines.append("  -> push needed: commits are local only")

    return "\n".join(lines)


def diagnose(report: WatchdogReport, stalled: bool = False) -> str:
    """Classify the current system state into one of four failure modes.

    Cross-references pidfile liveness (watchdog) with stroke cadence
    (heartbeat) to disambiguate situations that look identical from
    either signal alone:

    - ``healthy``:       processes alive, strokes flowing.
    - ``hung-process``:  process shows alive in pidfile but writer has
                         stalled — the loop is stuck (deadlock, GIL,
                         blocked I/O) and needs SIGKILL + restart.
    - ``reclaimed``:     process gone *and* writer stalled — container
                         reclamation, OOM kill, or host sleep.  Needs
                         full restart + backlog commit.
    - ``just-died``:     pidfile vanished but the last stroke is still
                         fresh — the process died seconds ago and the
                         heartbeat window hasn't expired yet.  Needs
                         restart before the gap becomes a stall.

    Args:
        report:  the :class:`WatchdogReport` from :func:`watchdog`.
        stalled: whether the heartbeat module reports the writer as
                 stalled (last stroke older than 2× cadence).

    Returns:
        A single diagnosis string.
    """
    if report.all_alive and not stalled:
        return "healthy"
    if report.all_alive and stalled:
        return "hung-process"
    if not report.all_alive and stalled:
        return "reclaimed"
    # !all_alive and !stalled — process just died, heartbeat still fresh
    return "just-died"
