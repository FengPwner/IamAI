"""Detect stale PID files left behind by crashed writer/batch processes.

When writer_loop.py or commit_batch.py crashes without cleanup, their PID
files remain on disk.  Subsequent restart attempts see the file, read the
PID, and refuse to start ("already running") even though the process is
long dead.  This module provides helpers to:

    1. Read a PID file and return the integer PID.
    2. Check whether that PID is actually alive.
    3. Classify the PID file as *live*, *stale*, or *missing*.
    4. Optionally remove the stale file so a restart can proceed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PidStatus(str, Enum):
    LIVE = "live"
    STALE = "stale"
    MISSING = "missing"


@dataclass
class PidCheck:
    path: Path
    status: PidStatus
    pid: int | None = None
    reason: str = ""


def read_pid(pid_file: Path) -> int | None:
    """Return the PID stored in *pid_file*, or None on any read error."""
    try:
        text = pid_file.read_text(encoding="utf-8").strip()
        return int(text)
    except (OSError, ValueError):
        return None


def is_pid_alive(pid: int) -> bool:
    """Return True if a process with *pid* exists and can be signalled."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def check_pid_file(pid_file: Path) -> PidCheck:
    """Classify a PID file as live, stale, or missing.

    * **live** — file exists, PID readable, process alive.
    * **stale** — file exists but PID is dead or unreadable.
    * **missing** — file does not exist.
    """
    if not pid_file.exists():
        return PidCheck(path=pid_file, status=PidStatus.MISSING, reason="file does not exist")

    pid = read_pid(pid_file)
    if pid is None:
        return PidCheck(path=pid_file, status=PidStatus.STALE, reason="unreadable or corrupt PID")

    if is_pid_alive(pid):
        return PidCheck(path=pid_file, status=PidStatus.LIVE, pid=pid, reason=f"pid {pid} is alive")

    return PidCheck(path=pid_file, status=PidStatus.STALE, pid=pid, reason=f"pid {pid} is dead")


def clear_stale(pid_file: Path) -> bool:
    """Remove *pid_file* only if it is stale.  Returns True if removed."""
    check = check_pid_file(pid_file)
    if check.status == PidStatus.STALE:
        try:
            pid_file.unlink(missing_ok=True)
            return True
        except OSError:
            return False
    return False
