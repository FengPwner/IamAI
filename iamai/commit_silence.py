"""commit_silence — detect and classify silence in the commit pipeline.

The batch committer is supposed to commit every ``interval`` seconds
(default 600 = 10 min).  When it goes quiet, the caretaker needs to
know **why** before deciding what to do.

Existing modules answer adjacent questions:

- ``commit_lag`` — how evenly spaced are commits?
- ``commit_blockage`` — why can't git commit *right now*?
- ``batch_effectiveness`` — is the committer succeeding on its attempts?

But none of them answers the simplest question first: **"how long has
it been since the last commit, and should I worry?"**

This module fills that gap.  It reads the timestamp of the most recent
commit, measures the silence duration, and classifies it:

===============  =====================================================
verdict          meaning
===============  =====================================================
``normal``       silence < 1.5 × interval — batch hasn't fired yet
``stretching``   1.5–3 × interval — one or two missed cycles
``stale``        3–6 × interval — committer likely stuck or failing
``dead``         > 6 × interval — assume the pipeline is broken
===============  =====================================================

Silence alone is not enough context.  A repo with no pending changes
and no writer activity can legitimately be quiet for hours.  So the
module also inspects:

- **pending_changes** — uncommitted files in the working tree
  (``git status --porcelain``).
- **writer_active** — whether the writer produced a stroke within
  the last ``writer_grace`` seconds (default 60 s).
- **strokes_since_commit** — how many strokes arrived after the
  last commit (from ``data/strokes.jsonl``).

Combining these gives a richer diagnosis:

=========================  ==========================================
situation                  verdict + context
=========================  ==========================================
batch just hasn't fired    normal, pending=0, writer quiet
batch missed one cycle     stretching, pending>0, writer active
lock file blocking         stale, pending>0, writer active
process crashed overnight  dead, pending>>0, writer active
nothing to do              normal, pending=0, writer inactive
=========================  ==========================================

Usage::

    from iamai.commit_silence import silence_status, silence_report

    status = silence_status(repo, interval=600)
    print(status["verdict"])        # "stretching"
    print(status["silence_seconds"])  # 1320.0

    print(silence_report(repo))
    # "stretching — 1320s since last commit (2.2× interval), "
    # "3 pending files, writer active, 12 strokes uncommitted"
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_INTERVAL = 600        # batch committer interval (seconds)
NORMAL_RATIO = 1.5            # below this → "normal"
STRETCHING_RATIO = 3.0        # below this → "stretching"
STALE_RATIO = 6.0             # below this → "stale"; above → "dead"
WRITER_GRACE = 60             # seconds: how recent must a stroke be
                              # to count the writer as "active"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _last_commit_time(repo: Path) -> Optional[datetime]:
    """Return the author-date of the most recent commit, or None."""
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%aI"],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
        ).decode("utf-8").strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    if not out:
        return None
    return datetime.fromisoformat(out)


def _pending_count(repo: Path) -> int:
    """Count uncommitted tracked files (porcelain line count)."""
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
        ).decode("utf-8").strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return 0
    return len([line for line in out.splitlines() if line.strip()])


def _recent_strokes(
    strokes_path: Path,
    since: Optional[datetime] = None,
    limit: int = 100,
) -> List[datetime]:
    """Return stroke timestamps from the tail of *strokes_path*.

    If *since* is given, only return strokes strictly after that time.
    Reads at most *limit* lines from the end of the file.
    """
    if not strokes_path.exists():
        return []
    try:
        # read last N lines efficiently
        with open(strokes_path, "rb") as f:
            # seek to end and read a chunk
            f.seek(0, 2)
            size = f.tell()
            # read up to 64KB from the end — enough for ~2000 strokes
            chunk_size = min(size, 65536)
            f.seek(size - chunk_size)
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []

    lines = raw.strip().splitlines()
    # take only the last *limit* lines
    lines = lines[-limit:]

    times: List[datetime] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            ts = obj.get("at")
            if ts:
                dt = datetime.fromisoformat(ts)
                if since is None or dt > since:
                    times.append(dt)
        except (json.JSONDecodeError, ValueError):
            continue
    return times


def _writer_active(
    strokes_path: Path,
    now: datetime,
    grace_seconds: float = WRITER_GRACE,
) -> bool:
    """True if the writer produced a stroke within *grace_seconds*."""
    strokes = _recent_strokes(strokes_path, limit=5)
    if not strokes:
        return False
    latest = max(strokes)
    delta = (now - latest).total_seconds()
    return delta <= grace_seconds


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def _classify(silence_seconds: float, interval: float) -> str:
    """Map silence duration to a verdict string."""
    if silence_seconds < 0:
        silence_seconds = 0
    ratio = silence_seconds / interval if interval > 0 else float("inf")

    if ratio < NORMAL_RATIO:
        return "normal"
    elif ratio < STRETCHING_RATIO:
        return "stretching"
    elif ratio < STALE_RATIO:
        return "stale"
    else:
        return "dead"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def silence_status(
    repo: Path,
    interval: float = DEFAULT_INTERVAL,
    now: Optional[datetime] = None,
    writer_grace: float = WRITER_GRACE,
) -> Dict[str, Any]:
    """Measure and classify the current commit silence.

    Parameters
    ----------
    repo : Path
        Repository root.
    interval : float
        Expected batch committer interval in seconds (default 600).
    now : datetime, optional
        Override current time (default: ``datetime.now(timezone.utc)``).
    writer_grace : float
        Seconds within which a stroke counts the writer as "active".

    Returns
    -------
    dict with keys:

    - ``verdict``: one of ``normal``, ``stretching``, ``stale``, ``dead``.
    - ``silence_seconds``: float, seconds since last commit.
    - ``interval_ratio``: float, silence / interval.
    - ``pending_changes``: int, uncommitted tracked files.
    - ``writer_active``: bool.
    - ``strokes_since_commit``: int, strokes produced after last commit.
    - ``last_commit``: ISO timestamp string or None.
    """
    _now = now if now is not None else datetime.now(timezone.utc)
    last = _last_commit_time(repo)

    if last is None:
        return {
            "verdict": "dead",
            "silence_seconds": float("inf"),
            "interval_ratio": float("inf"),
            "pending_changes": _pending_count(repo),
            "writer_active": False,
            "strokes_since_commit": 0,
            "last_commit": None,
        }

    silence = (_now - last).total_seconds()
    ratio = silence / interval if interval > 0 else float("inf")

    strokes_path = repo / "data" / "strokes.jsonl"
    pending = _pending_count(repo)
    writer_on = _writer_active(strokes_path, _now, grace_seconds=writer_grace)
    strokes_since = len(_recent_strokes(strokes_path, since=last))

    return {
        "verdict": _classify(silence, interval),
        "silence_seconds": round(max(silence, 0), 1),
        "interval_ratio": round(ratio, 2),
        "pending_changes": pending,
        "writer_active": writer_on,
        "strokes_since_commit": strokes_since,
        "last_commit": last.isoformat(),
    }


def silence_report(
    repo: Path,
    interval: float = DEFAULT_INTERVAL,
    now: Optional[datetime] = None,
    writer_grace: float = WRITER_GRACE,
) -> str:
    """One-liner human-readable silence summary.

    Example::

        "stretching — 1320s since last commit (2.2× interval), "
        "3 pending files, writer active, 12 strokes uncommitted"
    """
    s = silence_status(
        repo, interval=interval, now=now, writer_grace=writer_grace
    )

    if s["last_commit"] is None:
        return "dead — no commits found, cannot measure silence"

    parts = [f"{s['verdict']} — {s['silence_seconds']:.0f}s since last commit"]
    parts.append(f"({s['interval_ratio']:.1f}× interval)")

    # pending files
    if s["pending_changes"] > 0:
        parts.append(f"{s['pending_changes']} pending file(s)")
    else:
        parts.append("tree clean")

    # writer status
    parts.append("writer active" if s["writer_active"] else "writer idle")

    # uncommitted strokes
    if s["strokes_since_commit"] > 0:
        parts.append(f"{s['strokes_since_commit']} strokes uncommitted")

    return ", ".join(parts)
