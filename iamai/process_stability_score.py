"""process_stability_score — how stable is the current writer process?

A writer process that has been running for hours and producing strokes at
a steady cadence is *stable*: the caretaker can trust it and move on.
A process that was just restarted, or whose output rate is erratic, is
*fragile*: the caretaker should watch it closely.

This module synthesises four signals into a single 0–100 score:

=====================  =================================================
signal                 source
=====================  =================================================
``uptime_seconds``     pid file mtime + /proc (via process_uptime)
``cadence_cv``         coefficient of variation of stroke intervals
``stall_distance``     seconds since the last stall (>2× cadence gap)
``restart_rate``       restarts in the last 24 h (from log pid changes)
=====================  =================================================

Scoring
-------

Each signal contributes up to 25 points::

    uptime_score     = min(25, uptime_hours * 2.5)       # 10 h → 25
    cadence_score    = 25 * (1 - min(1, cv))             # cv=0 → 25
    stall_score      = min(25, stall_distance_h * 5)     # 5 h → 25
    restart_score    = max(0, 25 - restarts * 8)         # 0 → 25

The composite ``stability_score`` is their sum.

=====================  =================================================
grade                  meaning
=====================  =================================================
``stable``             score ≥ 75 — trust it and move on
``shaky``              score 40–74 — keep an eye on it
``fragile``            score < 40 — watch it closely or intervene
=====================  =================================================

Usage::

    from iamai.process_stability_score import stability_report

    report = stability_report(writer_id="qwen")
    print(report.score, report.grade)
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# thresholds
# ---------------------------------------------------------------------------

UPTIME_HOURS_FOR_FULL = 10.0       # 10 h uptime → max uptime score
CADENCE_CV_THRESHOLD = 1.0         # cv ≥ 1.0 → zero cadence score
STALL_HOURS_FOR_FULL = 5.0         # 5 h since last stall → max stall score
RESTART_PENALTY = 8                # each restart costs 8 points
MAX_PER_SIGNAL = 25                # each signal contributes at most 25

GRADE_STABLE = 75
GRADE_SHAKY = 40

# pid / log paths
_PID_DIR = Path("/tmp")
_LOG_DIR = Path("/tmp")
_STATE_DIR = Path(__file__).resolve().parent.parent / "data"


# ---------------------------------------------------------------------------
# data class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StabilityReport:
    """Result of a stability analysis."""

    score: float
    grade: str
    uptime_seconds: float
    uptime_score: float
    cadence_cv: float
    cadence_score: float
    stall_distance_seconds: float
    stall_score: float
    restart_count_24h: int
    restart_score: float
    details: str = ""

    def summary(self) -> str:
        """One-line human-readable summary."""
        up_h = self.uptime_seconds / 3600
        stall_h = self.stall_distance_seconds / 3600
        return (
            f"{self.grade} ({self.score:.0f}/100): "
            f"up {up_h:.1f}h, cv {self.cadence_cv:.2f}, "
            f"stall {stall_h:.1f}h ago, "
            f"{self.restart_count_24h} restarts in 24h"
        )


# ---------------------------------------------------------------------------
# signal extraction
# ---------------------------------------------------------------------------

def get_uptime_seconds(writer_id: str, now: Optional[float] = None) -> float:
    """Seconds the current writer process has been alive.

    Uses pid file mtime as a fallback when /proc is unavailable.
    Returns 0.0 if the process is not running.
    """
    pid_file = _PID_DIR / f"iamai-writer-{writer_id}.pid"
    if not pid_file.exists():
        return 0.0

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return 0.0

    # check if alive
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return 0.0

    if now is None:
        now = time.time()

    # try /proc for precise start time
    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.exists():
        try:
            # field 22 (1-indexed) is starttime in clock ticks
            parts = proc_stat.read_text().split()
            starttime_ticks = int(parts[21])
            # get boot time and clock ticks per second
            clk_tck = os.sysconf("SC_CLK_TCK")
            boot_time = _get_boot_time()
            if boot_time is not None:
                proc_start = boot_time + starttime_ticks / clk_tck
                return max(0.0, now - proc_start)
        except (IndexError, ValueError, OSError):
            pass

    # fallback: pid file mtime
    return max(0.0, now - pid_file.stat().st_mtime)


def _get_boot_time() -> Optional[float]:
    """Parse /proc/stat for system boot time (seconds since epoch)."""
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def get_cadence_cv(
    history: Sequence[dict],
    now: Optional[float] = None,
    window_seconds: float = 3600,
) -> float:
    """Coefficient of variation of stroke intervals within the recent window.

    Args:
        history: list of stroke records with ``at`` (ISO timestamp) fields.
        now: override for current time.
        window_seconds: only consider strokes within this many seconds.

    Returns:
        CV (stddev / mean) of intervals.  Returns 1.0 (worst) if fewer
        than 3 strokes fall within the window.
    """
    if len(history) < 3:
        return 1.0

    if now is None:
        now = time.time()

    cutoff = now - window_seconds

    # parse timestamps
    times: List[float] = []
    for entry in history:
        ts = _parse_iso(entry.get("at", ""))
        if ts is not None and ts >= cutoff:
            times.append(ts)

    times.sort()
    if len(times) < 3:
        return 1.0

    intervals = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    if not intervals:
        return 1.0

    mean_iv = sum(intervals) / len(intervals)
    if mean_iv <= 0:
        return 1.0

    variance = sum((iv - mean_iv) ** 2 for iv in intervals) / len(intervals)
    stddev = variance ** 0.5
    return stddev / mean_iv


def get_stall_distance_seconds(
    history: Sequence[dict],
    now: Optional[float] = None,
    cadence_seconds: float = 15.0,
    stall_multiplier: float = 2.0,
) -> float:
    """Seconds since the last stall event in the stroke history.

    A stall is any gap between consecutive strokes that exceeds
    ``cadence_seconds * stall_multiplier``.

    Returns:
        Seconds since the end of the last stall (i.e. the timestamp of
        the stroke that ended the gap).  Returns ``now`` (full distance)
        if no stalls are found, meaning the writer has been smooth since
        the beginning of the history.
    """
    if not history:
        return 0.0

    if now is None:
        now = time.time()

    threshold = cadence_seconds * stall_multiplier

    # parse all timestamps
    times: List[float] = []
    for entry in history:
        ts = _parse_iso(entry.get("at", ""))
        if ts is not None:
            times.append(ts)

    times.sort()
    if len(times) < 2:
        return now - times[0] if times else 0.0

    # find last stall
    last_stall_end: Optional[float] = None
    for i in range(len(times) - 1):
        gap = times[i + 1] - times[i]
        if gap > threshold:
            last_stall_end = times[i + 1]

    if last_stall_end is None:
        # no stall found — writer has been smooth
        return now - times[0]

    return max(0.0, now - last_stall_end)


def get_restart_count_24h(
    writer_id: str,
    now: Optional[float] = None,
) -> int:
    """Count distinct process start events in the last 24 hours.

    Heuristic: scans the writer log for pid file write events or
    "started" lines.  Falls back to 0 if the log is missing.
    """
    if now is None:
        now = time.time()

    log_path = _LOG_DIR / f"iamai-{writer_id}.log"
    if not log_path.exists():
        return 0

    cutoff = now - 86400
    restart_count = 0

    # pattern: writer_loop.py logs "writer started" or similar on boot
    started_re = re.compile(
        r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}).*(?:start|ready|tick 0)",
        re.IGNORECASE,
    )

    try:
        text = log_path.read_text(errors="replace")
    except OSError:
        return 0

    for line in text.splitlines():
        m = started_re.match(line)
        if m:
            ts = _parse_log_ts(m.group(1))
            if ts is not None and ts >= cutoff:
                restart_count += 1

    # ensure at least 0
    return max(0, restart_count)


def _load_history(writer_id: str) -> List[dict]:
    """Load writer state history from the JSON state file."""
    state_file = _STATE_DIR / f"writer_state.{writer_id}.json"
    if not state_file.exists():
        return []
    try:
        data = json.loads(state_file.read_text())
        return data.get("history", [])
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def score_uptime(uptime_seconds: float) -> float:
    """Score uptime: 0–25, full marks at UPTIME_HOURS_FOR_FULL."""
    hours = uptime_seconds / 3600
    return min(MAX_PER_SIGNAL, hours * (MAX_PER_SIGNAL / UPTIME_HOURS_FOR_FULL))


def score_cadence(cv: float) -> float:
    """Score cadence regularity: 0–25, full marks at cv=0."""
    clamped = min(CADENCE_CV_THRESHOLD, max(0.0, cv))
    return MAX_PER_SIGNAL * (1 - clamped / CADENCE_CV_THRESHOLD)


def score_stall_distance(stall_seconds: float) -> float:
    """Score stall distance: 0–25, full marks at STALL_HOURS_FOR_FULL."""
    hours = stall_seconds / 3600
    return min(MAX_PER_SIGNAL, hours * (MAX_PER_SIGNAL / STALL_HOURS_FOR_FULL))


def score_restarts(restart_count: int) -> float:
    """Score restart frequency: 0–25, penalised by RESTART_PENALTY each."""
    return max(0.0, MAX_PER_SIGNAL - restart_count * RESTART_PENALTY)


def grade(score: float) -> str:
    """Map a 0–100 score to a stability grade."""
    if score >= GRADE_STABLE:
        return "stable"
    if score >= GRADE_SHAKY:
        return "shaky"
    return "fragile"


# ---------------------------------------------------------------------------
# composite
# ---------------------------------------------------------------------------

def stability_report(
    writer_id: str = "qwen",
    now: Optional[float] = None,
    history: Optional[Sequence[dict]] = None,
) -> StabilityReport:
    """Compute a full stability report for the given writer.

    Args:
        writer_id: writer identifier (used to locate pid/log/state files).
        now: override for current time (testing).
        history: pre-loaded history list; if None, loaded from disk.

    Returns:
        A frozen StabilityReport dataclass.
    """
    if now is None:
        now = time.time()

    if history is None:
        history = _load_history(writer_id)

    uptime_s = get_uptime_seconds(writer_id, now)
    cv = get_cadence_cv(history, now)
    stall_s = get_stall_distance_seconds(history, now)
    restarts = get_restart_count_24h(writer_id, now)

    u_score = score_uptime(uptime_s)
    c_score = score_cadence(cv)
    s_score = score_stall_distance(stall_s)
    r_score = score_restarts(restarts)

    total = u_score + c_score + s_score + r_score

    return StabilityReport(
        score=round(total, 1),
        grade=grade(total),
        uptime_seconds=round(uptime_s, 1),
        uptime_score=round(u_score, 1),
        cadence_cv=round(cv, 3),
        cadence_score=round(c_score, 1),
        stall_distance_seconds=round(stall_s, 1),
        stall_score=round(s_score, 1),
        restart_count_24h=restarts,
        restart_score=round(r_score, 1),
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _parse_iso(s: str) -> Optional[float]:
    """Parse an ISO-8601 timestamp to a Unix epoch."""
    if not s:
        return None
    try:
        # handle both +00:00 and Z suffixes
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.timestamp()
    except (ValueError, OSError):
        return None


_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _parse_log_ts(s: str) -> Optional[float]:
    """Parse a log-style timestamp to a Unix epoch (assumes UTC)."""
    try:
        dt = datetime.strptime(s, _TS_FMT).replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Writer process stability score.")
    parser.add_argument("--writer", default="qwen", help="Writer id.")
    args = parser.parse_args()

    report = stability_report(writer_id=args.writer)
    print(report.summary())
    print(f"  uptime:   {report.uptime_score:.0f}/25  ({report.uptime_seconds:.0f}s)")
    print(f"  cadence:  {report.cadence_score:.0f}/25  (cv={report.cadence_cv:.3f})")
    print(f"  stall:    {report.stall_score:.0f}/25  ({report.stall_distance_seconds:.0f}s ago)")
    print(f"  restarts: {report.restart_score:.0f}/25  ({report.restart_count_24h} in 24h)")
