"""writer_exit_classifier — classify why a writer process stopped.

When the writer loop exits, the caretaker needs to know *why* before
choosing a recovery action.  The raw signals are scattered: exit codes,
log tail lines, PID file presence, and the line-count budget.  This
module pulls them into one structured verdict.

Exit causes
-----------

==================  ====================================================
cause               meaning
==================  ====================================================
line_budget         writer hit MAX_TRACKED_LINES and refused to continue
stop_requested      a ``/tmp/iamai-stop`` file was present; clean shutdown
crash               no PID file, no stop file, log shows no clean exit
normal              writer exited with code 0 for a non-budget reason
unknown             insufficient information to classify
==================  ====================================================

Each cause maps to a recommended recovery action:

- **line_budget** → raise the ceiling or prune files, then restart
- **stop_requested** → do not restart; investigate who/what placed the stop file
- **crash** → check stderr, restart if no recurring pattern
- **normal** → restart
- **unknown** → escalate to human

Usage::

    from iamai.writer_exit_classifier import classify_exit, ExitReport

    report = classify_exit(
        exit_code=3,
        log_tail="[2026-11-03 03:01:31Z] writer tree exceeded the line budget; refusing to keep padding it",
        pid_exists=False,
        stop_file_exists=False,
        line_count=400_403,
        line_budget=400_000,
    )
    assert report.cause == "line_budget"
    assert report.should_restart is False  # ceiling must be raised first

Zero dependencies.  stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# Exit code the writer loop returns when it hits the line budget.
_LINE_BUDGET_EXIT = 3

# Log substrings that signal specific causes.
_BUDGET_SIGNATURE = "line budget"
_STOP_SIGNATURE = "stop requested"


@dataclass
class ExitReport:
    """Structured classification of a writer exit event."""

    cause: str
    exit_code: Optional[int]
    evidence: List[str] = field(default_factory=list)
    should_restart: bool = False
    recovery_hint: str = ""

    def to_dict(self) -> dict:
        return {
            "cause": self.cause,
            "exit_code": self.exit_code,
            "evidence": list(self.evidence),
            "should_restart": self.should_restart,
            "recovery_hint": self.recovery_hint,
        }


def classify_exit(
    exit_code: Optional[int] = None,
    log_tail: str = "",
    pid_exists: bool = False,
    stop_file_exists: bool = False,
    line_count: int = 0,
    line_budget: int = 400_000,
) -> ExitReport:
    """Classify why a writer process exited.

    Parameters
    ----------
    exit_code:
        Process exit code, or ``None`` if unknown (e.g. process was killed
        by the OOM killer and no waitpid was performed).
    log_tail:
        Last few lines of the writer log, concatenated into one string.
    pid_exists:
        Whether the writer PID file still exists on disk.
    stop_file_exists:
        Whether ``/tmp/iamai-stop`` was present when classification runs.
    line_count:
        Current total tracked lines in the repository.
    line_budget:
        The MAX_TRACKED_LINES ceiling the writer was configured with.
    """
    evidence: List[str] = []
    log_lower = log_tail.lower()

    # --- Priority 1: exit code is the strongest signal. -----------------
    if exit_code == _LINE_BUDGET_EXIT:
        evidence.append(f"exit_code={_LINE_BUDGET_EXIT}")
        if _BUDGET_SIGNATURE in log_lower:
            evidence.append("log mentions line budget")
        if line_count > line_budget:
            evidence.append(f"lines {line_count} > budget {line_budget}")
        return ExitReport(
            cause="line_budget",
            exit_code=exit_code,
            evidence=evidence,
            should_restart=False,
            recovery_hint="Raise MAX_TRACKED_LINES or prune tracked files, then restart.",
        )

    # --- Priority 2: stop file means intentional shutdown. ---------------
    if stop_file_exists or _STOP_SIGNATURE in log_lower:
        if stop_file_exists:
            evidence.append("stop file present")
        if _STOP_SIGNATURE in log_lower:
            evidence.append("log mentions stop requested")
        return ExitReport(
            cause="stop_requested",
            exit_code=exit_code,
            evidence=evidence,
            should_restart=False,
            recovery_hint="Investigate who placed the stop file before restarting.",
        )

    # --- Priority 2.5: log clearly says budget even without exit code. ---
    if _BUDGET_SIGNATURE in log_lower:
        evidence.append("log mentions line budget")
        if line_count > 0 and line_budget > 0:
            evidence.append(f"lines {line_count} vs budget {line_budget}")
        return ExitReport(
            cause="line_budget",
            exit_code=exit_code,
            evidence=evidence,
            should_restart=False,
            recovery_hint="Raise MAX_TRACKED_LINES or prune tracked files, then restart.",
        )

    # --- Priority 3: line budget exceeded even without the exit code. ----
    if line_count > line_budget and line_budget > 0:
        evidence.append(f"lines {line_count} > budget {line_budget}")
        if _BUDGET_SIGNATURE in log_lower:
            evidence.append("log mentions line budget")
        return ExitReport(
            cause="line_budget",
            exit_code=exit_code,
            evidence=evidence,
            should_restart=False,
            recovery_hint="Raise MAX_TRACKED_LINES or prune tracked files, then restart.",
        )

    # --- Priority 4: clean exit code 0. ---------------------------------
    if exit_code == 0:
        evidence.append("exit_code=0")
        return ExitReport(
            cause="normal",
            exit_code=exit_code,
            evidence=evidence,
            should_restart=True,
            recovery_hint="Writer exited cleanly; safe to restart.",
        )

    # --- Priority 5: no PID file and non-zero exit → crash. --------------
    if not pid_exists and exit_code is not None and exit_code != 0:
        evidence.append(f"exit_code={exit_code}")
        evidence.append("pid file absent")
        return ExitReport(
            cause="crash",
            exit_code=exit_code,
            evidence=evidence,
            should_restart=True,
            recovery_hint="Check stderr for recurring errors; restart if one-off.",
        )

    # --- Priority 6: no PID file and unknown exit code → crash. ----------
    if not pid_exists and exit_code is None:
        evidence.append("pid file absent, exit code unknown")
        return ExitReport(
            cause="crash",
            exit_code=exit_code,
            evidence=evidence,
            should_restart=True,
            recovery_hint="Process disappeared without a trace; likely OOM or signal kill.",
        )

    # --- Fallback: not enough signal to classify. -----------------------
    if pid_exists:
        evidence.append("pid file still present")
    if exit_code is not None:
        evidence.append(f"exit_code={exit_code}")
    return ExitReport(
        cause="unknown",
        exit_code=exit_code,
        evidence=evidence,
        should_restart=False,
        recovery_hint="Insufficient information; escalate to human.",
    )


def classify_from_log_file(
    log_path: str = "/tmp/iamai-writer.log",
    tail_lines: int = 10,
    line_count: int = 0,
    line_budget: int = 400_000,
    pid_exists: bool = False,
    stop_file_exists: bool = False,
) -> ExitReport:
    """Read the last N lines of the writer log and classify the exit.

    This is a convenience wrapper for caretaker scripts that have the
    log path but not the raw tail string.
    """
    try:
        with open(log_path, encoding="utf-8") as fh:
            lines = fh.readlines()
        tail = "".join(lines[-tail_lines:])
    except (OSError, IOError):
        tail = ""
    return classify_exit(
        log_tail=tail,
        pid_exists=pid_exists,
        stop_file_exists=stop_file_exists,
        line_count=line_count,
        line_budget=line_budget,
    )
