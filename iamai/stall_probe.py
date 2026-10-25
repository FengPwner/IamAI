"""stall_probe — multi-signal health probe for the automated writing system.

Individual monitors (stroke_freshness, process_uptime, commit_age) each answer
one narrow question.  A caretaker arriving at the repo wants a single verdict:
*is the system healthy right now?*

This module combines four signals into one health check:

===============  =================================================
signal           how it is measured
===============  =================================================
writer_alive     PID file exists and process responds to signal 0
batch_alive      same for the batch committer
stroke_fresh     last stroke age vs writer cadence
backlog_low      uncommitted file count below threshold
===============  =================================================

Verdicts:

===========  ============================================================
``healthy``  all four signals green
``degraded`` one or two signals off — system works but needs attention
``stalled``  three or more signals off — something is clearly broken
===========  ============================================================

Usage::

    from iamai.stall_probe import probe, probe_report

    result = probe(repo)
    print(result["verdict"])    # "healthy"
    print(result["signals"])    # {"writer_alive": True, ...}

    print(probe_report(repo))
    # "healthy — 4/4 signals green"
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# individual signal checks
# ---------------------------------------------------------------------------

def _pid_alive(pid_path: Path) -> bool:
    """Return True if the PID recorded in *pid_path* is a live process."""
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _last_stroke_age(strokes_path: Path) -> float:
    """Seconds since the last line in strokes.jsonl, or inf if unreadable."""
    if not strokes_path.exists():
        return float("inf")
    try:
        with open(strokes_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return float("inf")
            # scan backwards for the last newline
            pos = size - 1
            while pos > 0:
                f.seek(pos)
                if f.read(1) == b"\n" and pos < size - 1:
                    pos += 1
                    break
                pos -= 1
            else:
                pos = 0
            f.seek(pos)
            last_line = f.readline().decode("utf-8", errors="replace").strip()
        if not last_line:
            return float("inf")
        entry = json.loads(last_line)
        ts = datetime.fromisoformat(entry["at"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except (json.JSONDecodeError, KeyError, OSError, ValueError):
        return float("inf")


def _uncommitted_count(repo: Path) -> int:
    """Number of modified + untracked files according to git."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return -1  # not a git repo or git error
        return len([l for l in result.stdout.splitlines() if l.strip()])
    except (OSError, subprocess.SubprocessError):
        return -1  # signal unknown


# ---------------------------------------------------------------------------
# composite probe
# ---------------------------------------------------------------------------

def probe(
    repo: Path | str | None = None,
    *,
    writer_id: str | None = "qwen",
    cadence_seconds: float = 15.0,
    fresh_threshold: float = 5.0,
    backlog_threshold: int = 20,
) -> dict:
    """Run all four signals and return a unified health verdict.

    Parameters
    ----------
    repo : path to the repo root (defaults to this file's grandparent).
    writer_id : writer identifier used for PID file names.
    cadence_seconds : expected seconds between writer strokes.
    fresh_threshold : stroke age (in cadence multiples) above which the
        ``stroke_fresh`` signal goes red.  Default 5× = 75 s at cadence 15.
    backlog_threshold : uncommitted file count above which ``backlog_low``
        goes red.

    Returns
    -------
    dict with keys: verdict, signals (dict of bools), details (dict of raw
    measurements), green_count, total_signals.
    """
    if repo is None:
        repo = Path(__file__).resolve().parent.parent
    repo = Path(repo)

    # --- writer alive ---
    w_pid = repo / "data" / f"writer-{writer_id}.pid" if writer_id else repo / "data" / "writer.pid"
    # also try the well-known /tmp location used by iamai.writer
    if not w_pid.exists():
        wid = writer_id or "default"
        w_pid = Path(f"/tmp/iamai-writer-{wid}.pid")
    writer_alive = _pid_alive(w_pid)

    # --- batch alive ---
    b_pid = repo / "data" / f"batch-{writer_id}.pid" if writer_id else repo / "data" / "batch.pid"
    if not b_pid.exists():
        wid = writer_id or "default"
        b_pid = Path(f"/tmp/iamai-batch-{wid}.pid")
    batch_alive = _pid_alive(b_pid)

    # --- stroke freshness ---
    strokes_path = repo / "data" / "strokes.jsonl"
    stroke_age = _last_stroke_age(strokes_path)
    stroke_fresh = stroke_age < (fresh_threshold * cadence_seconds)

    # --- backlog ---
    n_uncommitted = _uncommitted_count(repo)
    backlog_low = 0 <= n_uncommitted <= backlog_threshold

    signals = {
        "writer_alive": writer_alive,
        "batch_alive": batch_alive,
        "stroke_fresh": stroke_fresh,
        "backlog_low": backlog_low,
    }
    details = {
        "writer_pid_file": str(w_pid),
        "batch_pid_file": str(b_pid),
        "stroke_age_seconds": round(stroke_age, 1) if stroke_age != float("inf") else -1,
        "uncommitted_files": n_uncommitted,
        "cadence_seconds": cadence_seconds,
        "fresh_threshold_multiples": fresh_threshold,
        "backlog_threshold": backlog_threshold,
    }

    green = sum(1 for v in signals.values() if v)
    total = len(signals)

    if green == total:
        verdict = "healthy"
    elif green >= total - 2:
        verdict = "degraded"
    else:
        verdict = "stalled"

    return {
        "verdict": verdict,
        "signals": signals,
        "details": details,
        "green_count": green,
        "total_signals": total,
    }


def probe_report(
    repo: Path | str | None = None,
    **kwargs,
) -> str:
    """One-line human-readable summary of probe()."""
    result = probe(repo, **kwargs)
    v = result["verdict"]
    g = result["green_count"]
    t = result["total_signals"]
    parts = []
    for name, ok in result["signals"].items():
        tag = "✓" if ok else "✗"
        parts.append(f"{tag} {name}")
    return f"{v} — {g}/{t} signals green  [{', '.join(parts)}]"
