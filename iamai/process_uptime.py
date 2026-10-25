"""Process uptime — how long do writer/batch processes survive?

The IamAI writer lives inside containers that periodically reclaim idle
processes.  This module analyses uptime patterns from two data sources:

1. **Pid files** — ``/tmp/iamai-writer-<id>.pid`` carries the pid and can be
   stat'd for age (``mtime``).  Combined with ``/proc/<pid>/stat`` start time
   this gives a live-process uptime estimate.
2. **Log timestamps** — the writer log at ``/tmp/iamai-<id>.log`` records
   stroke lines with timestamps.  The gap between the first and last line
   bounds the session length even after the process dies.

Three public functions:

- ``live_uptime(pid)`` — seconds since the process started (Linux only);
  returns ``None`` when the process is dead or ``/proc`` is unavailable.
- ``session_from_log(log_path)`` — ``(first_ts, last_ts, seconds)`` parsed
  from the log, or ``None`` when the log is missing or empty.
- ``uptime_summary(writer_id)`` — one-liner combining both sources for the
  caretaker's status line.

Edge cases:

- Non-Linux systems where ``/proc`` does not exist → ``live_uptime`` returns
  ``None``; ``session_from_log`` still works.
- Log with a single line → session length is 0.
- Missing pid file → treated as "process not running".
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

_PID_DIR = Path("/tmp")
_LOG_DIR = Path("/tmp")

# Match lines like: 2026-10-15 17:00:03 [qwen] stroke ...
_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})"
)


def _pid_file(writer_id: str) -> Path:
    return _PID_DIR / f"iamai-writer-{writer_id}.pid"


def _read_pid(writer_id: str) -> Optional[int]:
    """Read the pid from the pid file, or None if missing/invalid."""
    pf = _pid_file(writer_id)
    if not pf.exists():
        return None
    try:
        text = pf.read_text().strip()
        pid = int(text)
        return pid if pid > 0 else None
    except (ValueError, OSError):
        return None


def _process_start_time(pid: int) -> Optional[float]:
    """Return the process start time as epoch seconds (Linux /proc).

    Reads ``/proc/<pid>/stat`` field 22 (starttime in clock ticks since boot)
    and converts using ``/proc/stat`` btime and sysconf CLK_TCK.
    Returns ``None`` if the process is dead or /proc is unavailable.
    """
    stat_path = Path(f"/proc/{pid}/stat")
    btime_path = Path("/proc/stat")
    if not stat_path.exists() or not btime_path.exists():
        return None
    try:
        raw = stat_path.read_text()
        # field 22 is after the last ')' — the comm field can contain spaces
        after_comm = raw.rsplit(")", 1)[-1]
        fields = after_comm.split()
        # fields[0] is state, fields[1] is ppid, ..., fields[19] is starttime
        # (0-indexed from after comm: state=0, ppid=1, ..., starttime=19)
        if len(fields) < 20:
            return None
        starttime_ticks = int(fields[19])

        # boot time from /proc/stat
        btime = None
        for line in btime_path.read_text().splitlines():
            if line.startswith("btime "):
                btime = int(line.split()[1])
                break
        if btime is None:
            return None

        clk_tck = os.sysconf("SC_CLK_TCK")
        return float(btime) + starttime_ticks / clk_tck
    except (OSError, ValueError, IndexError):
        return None


def _parse_log_timestamps(log_path: Path) -> list[float]:
    """Extract epoch timestamps from recognised log lines."""
    if not log_path.exists():
        return []
    from datetime import datetime

    timestamps: list[float] = []
    try:
        for line in log_path.read_text(errors="replace").splitlines():
            m = _TS_RE.match(line)
            if m:
                try:
                    dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                    timestamps.append(dt.timestamp())
                except ValueError:
                    continue
    except OSError:
        return []
    return timestamps


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def live_uptime(pid: Optional[int] = None, writer_id: str = "qwen") -> Optional[float]:
    """Seconds since the given process started.

    Pass either ``pid`` directly or ``writer_id`` to look it up from the pid
    file.  Returns ``None`` when the process is dead, the pid file is missing,
    or ``/proc`` is unavailable (non-Linux).
    """
    if pid is None:
        pid = _read_pid(writer_id)
    if pid is None:
        return None

    start = _process_start_time(pid)
    if start is None:
        return None

    # verify the process is actually alive (kill -0 equivalent)
    try:
        os.kill(pid, 0)
    except OSError:
        return None

    return round(time.time() - start, 1)


def session_from_log(
    log_path: Optional[Path | str] = None,
    writer_id: str = "qwen",
) -> Optional[dict]:
    """Analyse a writer log to determine the session time span.

    Returns a dict::

        {
            "first": "2026-10-15 16:00:03",
            "last":  "2026-10-15 17:59:58",
            "seconds": 7195.0,
            "lines": 480,
        }

    Returns ``None`` when the log is missing or contains no timestamped lines.
    """
    if log_path is None:
        log_path = _LOG_DIR / f"iamai-{writer_id}.log"
    log_path = Path(log_path)

    timestamps = _parse_log_timestamps(log_path)
    if not timestamps:
        return None

    first = min(timestamps)
    last = max(timestamps)

    from datetime import datetime

    return {
        "first": datetime.fromtimestamp(first).strftime("%Y-%m-%d %H:%M:%S"),
        "last": datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M:%S"),
        "seconds": round(last - first, 1),
        "lines": len(timestamps),
    }


def uptime_summary(writer_id: str = "qwen") -> str:
    """One-liner combining live uptime and log session for caretaker status.

    Example outputs::

        writer qwen: alive 423s, log session 7195s (480 lines)
        writer qwen: dead, last log session 3600s (240 lines)
        writer qwen: no data
    """
    live = live_uptime(writer_id=writer_id)
    log = session_from_log(writer_id=writer_id)

    if live is not None and log is not None:
        return (
            f"writer {writer_id}: alive {int(live)}s, "
            f"log session {int(log['seconds'])}s ({log['lines']} lines)"
        )
    if live is not None:
        return f"writer {writer_id}: alive {int(live)}s, no log data"
    if log is not None:
        return (
            f"writer {writer_id}: dead, "
            f"last log session {int(log['seconds'])}s ({log['lines']} lines)"
        )
    return f"writer {writer_id}: no data"
