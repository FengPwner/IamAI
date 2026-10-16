"""Process sentinel — detect whether a managed process is still alive.

When a sandbox reclaims processes without warning, the first line of
defence is noticing the absence.  ProcessSentinel wraps a PID file
and answers one question: is the process still running?

It reads a PID from a file (one integer, optionally followed by the
process name on the same line), checks ``/proc/<pid>`` for liveness,
and returns a structured verdict.

Verdicts:
- ``"alive"``    — PID exists and cmdline matches the expected name.
- ``"zombie"``   — PID exists but is in zombie state (defunct).
- ``"replaced"`` — PID exists but cmdline doesn't match (PID reuse).
- ``"gone"``     — PID directory doesn't exist in /proc.
- ``"no_pid"``   — PID file is missing, empty, or unreadable.

>>> import tempfile, os
>>> f = tempfile.NamedTemporaryFile(mode='w', suffix='.pid', delete=False)
>>> _ = f.write('99999999\\n'); f.close()
>>> s = ProcessSentinel(pid_file=f.name, expected_name='nonexistent')
>>> s.check()
'gone'
>>> os.unlink(f.name)
>>> s2 = ProcessSentinel(pid_file='/tmp/does_not_exist_xyz.pid')
>>> s2.check()
'no_pid'
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class ProcessSentinel:
    """Check whether a managed process is still alive via its PID file.

    Parameters
    ----------
    pid_file : str or Path
        Path to a file containing the process PID (first token on
        line 1).  Optionally, the second token is the expected
        process name for cross-checking against /proc cmdline.
    expected_name : str, optional
        Substring expected in the process cmdline.  If not given,
        liveness is decided by /proc existence alone.
    """

    def __init__(
        self,
        pid_file: str | Path,
        expected_name: Optional[str] = None,
    ):
        self.pid_file = Path(pid_file)
        self.expected_name = expected_name

    def read_pid(self) -> Optional[int]:
        """Return the PID from the file, or None if unreadable."""
        try:
            text = self.pid_file.read_text().strip()
        except (OSError, IOError):
            return None
        if not text:
            return None
        try:
            return int(text.split()[0])
        except (ValueError, IndexError):
            return None

    def check(self) -> str:
        """Return one of: alive, zombie, replaced, gone, no_pid."""
        pid = self.read_pid()
        if pid is None:
            return "no_pid"

        proc_dir = Path(f"/proc/{pid}")
        if not proc_dir.exists():
            return "gone"

        # check for zombie state
        try:
            status_text = (proc_dir / "status").read_text()
            for line in status_text.splitlines():
                if line.startswith("State:"):
                    if "zombie" in line.lower() or "Z" in line.split():
                        return "zombie"
                    break
        except (OSError, IOError):
            pass

        # check cmdline match if expected_name is set
        if self.expected_name:
            try:
                cmdline = (proc_dir / "cmdline").read_bytes()
                cmdline_str = cmdline.replace(b"\x00", b" ").decode(
                    "utf-8", errors="replace"
                )
                if self.expected_name not in cmdline_str:
                    return "replaced"
            except (OSError, IOError):
                pass

        return "alive"

    def report(self) -> dict:
        """Return a structured diagnostic dictionary."""
        pid = self.read_pid()
        verdict = self.check()
        return {
            "pid_file": str(self.pid_file),
            "pid": pid,
            "expected_name": self.expected_name,
            "verdict": verdict,
        }
