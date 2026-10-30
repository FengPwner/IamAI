"""Repo pulse — a single-shot health reading for external monitors.

When a caretaker, dashboard, or cron job asks "is the repo alive right now?",
the answer should be cheap to compute and easy to interpret.  ``repo_pulse``
reads the most recent strokes, commit timestamps, and (optionally) process
state, then returns a structured verdict.

Three health levels:

* **healthy** — strokes arriving on cadence, no uncommitted backlog.
* **degraded** — strokes arriving but cadence is slipping, or there are
  uncommitted files piling up.
* **stalled** — no strokes within ``stall_threshold`` seconds (default 2× the
  writer's nominal cadence).

Usage::

    from iamai.repo_pulse import take_pulse

    pulse = take_pulse()
    print(pulse["verdict"])      # "healthy" | "degraded" | "stalled"
    print(pulse["strokes_1h"])   # strokes in the last hour
    print(pulse["lag_seconds"])  # seconds since the most recent stroke

Design notes:

- ``take_pulse`` reads only ``data/strokes.jsonl`` (tail) and ``git log``
  output; it does *not* import heavy modules or scan the whole tree.
- The function is deterministic given the same inputs, which makes it safe
  to call from tests with a synthetic strokes file.
- ``stall_threshold`` defaults to 1800 s (30 min), which is twice the
  writer's 15-second cadence multiplied by a generous buffer.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_DEFAULT_STROKES_PATH = Path("data/strokes.jsonl")

# Two health constants.
WRITER_CADENCE_SECONDS = 15          # nominal inter-stroke gap
DEFAULT_STALL_THRESHOLD = 1800       # 30 min — anything longer is "stalled"
DEGRADED_MULTIPLIER = 4.0            # 4× cadence = degraded zone


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp to a timezone-aware UTC datetime."""
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _tail_strokes(
    strokes_path: Path,
    max_lines: int = 2000,
) -> List[Dict[str, Any]]:
    """Read the last *max_lines* strokes from the JSONL file.

    Returns an empty list if the file is missing or corrupt.
    """
    if not strokes_path.is_file():
        return []

    lines: List[str] = []
    try:
        with strokes_path.open("r", encoding="utf-8") as fh:
            # Read from the end for efficiency on large files.
            all_lines = fh.readlines()
            lines = all_lines[-max_lines:]
    except OSError:
        return []

    strokes: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def _count_recent_strokes(
    strokes: List[Dict[str, Any]],
    window_seconds: int,
    reference: Optional[datetime] = None,
) -> int:
    """Count strokes whose timestamp falls within *window_seconds* of *reference*."""
    ref = reference or _now()
    cutoff = ref.timestamp() - window_seconds
    count = 0
    for s in strokes:
        ts_str = s.get("at", "")
        if not ts_str:
            continue
        try:
            ts = _parse_ts(ts_str)
        except (ValueError, TypeError):
            continue
        if ts.timestamp() >= cutoff:
            count += 1
    return count


def _latest_stroke_ts(
    strokes: List[Dict[str, Any]],
) -> Optional[datetime]:
    """Return the timestamp of the most recent stroke, or None."""
    best: Optional[datetime] = None
    for s in strokes:
        ts_str = s.get("at", "")
        if not ts_str:
            continue
        try:
            ts = _parse_ts(ts_str)
        except (ValueError, TypeError):
            continue
        if best is None or ts > best:
            best = ts
    return best


def _lag_seconds(
    strokes: List[Dict[str, Any]],
    reference: Optional[datetime] = None,
) -> Optional[float]:
    """Seconds since the most recent stroke.  None if no strokes exist."""
    latest = _latest_stroke_ts(strokes)
    if latest is None:
        return None
    ref = reference or _now()
    return max(0.0, (ref - latest).total_seconds())


def _recent_commit_count(window_seconds: int = 3600) -> int:
    """Count commits in the last *window_seconds* via ``git log``."""
    try:
        since = (
            datetime.now(timezone.utc).timestamp() - window_seconds
        )
        since_iso = datetime.fromtimestamp(since, tz=timezone.utc).isoformat()
        result = subprocess.run(
            ["git", "log", f"--since={since_iso}", "--oneline"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return 0
        return len([ln for ln in result.stdout.strip().splitlines() if ln.strip()])
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return 0


def _uncommitted_count() -> int:
    """Count files with uncommitted changes via ``git status --porcelain``."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return 0
        return len([ln for ln in result.stdout.strip().splitlines() if ln.strip()])
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return 0


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def take_pulse(
    strokes_path: Optional[Path] = None,
    stall_threshold: int = DEFAULT_STALL_THRESHOLD,
    reference: Optional[datetime] = None,
    include_git: bool = True,
) -> Dict[str, Any]:
    """Take a single health reading of the repository.

    Parameters
    ----------
    strokes_path:
        Path to ``data/strokes.jsonl``.  Defaults to the repo-local path.
    stall_threshold:
        Seconds of silence before the verdict becomes ``"stalled"``.
    reference:
        Override "now" for deterministic testing.
    include_git:
        Whether to query git for commit count and uncommitted files.
        Set to False in tests or when git is unavailable.

    Returns
    -------
    dict with keys:
        ``verdict``         — ``"healthy"`` | ``"degraded"`` | ``"stalled"``
        ``lag_seconds``     — seconds since the last stroke (None if no strokes)
        ``strokes_1h``      — strokes in the last hour
        ``strokes_6h``      — strokes in the last 6 hours
        ``latest_seq``      — sequence number of the most recent stroke
        ``commits_1h``      — git commits in the last hour (0 if include_git=False)
        ``uncommitted``     — files with uncommitted changes (0 if include_git=False)
        ``stall_threshold`` — the threshold used for the stalled verdict
    """
    path = strokes_path or _DEFAULT_STROKES_PATH
    strokes = _tail_strokes(path)

    lag = _lag_seconds(strokes, reference=reference)
    s1h = _count_recent_strokes(strokes, 3600, reference=reference)
    s6h = _count_recent_strokes(strokes, 21600, reference=reference)

    # Latest sequence number.
    latest_seq = 0
    for s in strokes:
        seq = s.get("seq", 0)
        if isinstance(seq, int) and seq > latest_seq:
            latest_seq = seq

    # Verdict logic.
    if lag is None:
        verdict = "stalled"  # no strokes at all
    elif lag >= stall_threshold:
        verdict = "stalled"
    elif lag >= WRITER_CADENCE_SECONDS * DEGRADED_MULTIPLIER:
        verdict = "degraded"
    else:
        verdict = "healthy"

    commits_1h = 0
    uncommitted = 0
    if include_git:
        commits_1h = _recent_commit_count(3600)
        uncommitted = _uncommitted_count()

    return {
        "verdict": verdict,
        "lag_seconds": round(lag, 1) if lag is not None else None,
        "strokes_1h": s1h,
        "strokes_6h": s6h,
        "latest_seq": latest_seq,
        "commits_1h": commits_1h,
        "uncommitted": uncommitted,
        "stall_threshold": stall_threshold,
    }


def pulse_one_liner(pulse: Dict[str, Any]) -> str:
    """Render a pulse dict as a single human-readable line.

    >>> pulse_one_liner({"verdict": "healthy", "lag_seconds": 12.3, "strokes_1h": 240, "latest_seq": 2804, "commits_1h": 4, "uncommitted": 0, "strokes_6h": 1200, "stall_threshold": 1800})
    'healthy | lag 12s | 240 strokes/1h | seq 2804 | 4 commits/1h | 0 dirty'
    """
    lag_str = f"{int(pulse['lag_seconds'])}s" if pulse.get("lag_seconds") is not None else "n/a"
    return (
        f"{pulse['verdict']} | lag {lag_str} | "
        f"{pulse['strokes_1h']} strokes/1h | "
        f"seq {pulse['latest_seq']} | "
        f"{pulse['commits_1h']} commits/1h | "
        f"{pulse['uncommitted']} dirty"
    )
