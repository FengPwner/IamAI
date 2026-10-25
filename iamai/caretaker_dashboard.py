"""Caretaker dashboard — one-call snapshot for a caretaker visit.

A caretaker arriving at the IamAI repo needs a quick answer to:
*"Is everything okay, and if not, what needs attention?"*

Today that answer is scattered across half a dozen tools: ``repo_pulse``
for health, ``commit_momentum`` for trend, ``stroke_freshness`` for
liveness, ``lock_health`` for git status, a process check for writer
and batch PIDs.  Each is correct; together they are a chore.

``caretaker_dashboard`` aggregates the five signals that matter most
into a single call and produces a **verdict**:

==============  ===========================================================
verdict         meaning
==============  ===========================================================
``healthy``     all signals nominal — no action needed
``attention``   one or more signals degraded — worth investigating
``critical``    multiple signals failing — immediate action required
==============  ===========================================================

Signal inventory
----------------

==================  ======================================================
signal              source / meaning
==================  ======================================================
``writer_alive``    Is the writer process currently running? (PID check)
``batch_alive``     Is the commit batch process running?
``backlog``         Number of uncommitted files (0 = clean).
``freshness_sec``   Seconds since the last stroke was written.
``momentum``        Commit-momentum verdict over the last 12 h.
==================  ======================================================

Scoring
-------

Each signal is scored 0–2:

=======  ============================================================
score    meaning
=======  ============================================================
2        nominal — within healthy bounds
1        degraded — outside normal but not failing
0        failing — requires attention
=======  ============================================================

The composite verdict is derived from the sum:

==========  ==========
total       verdict
==========  ==========
≥ 8         healthy
5–7         attention
≤ 4         critical
==========  ==========

Usage::

    from iamai.caretaker_dashboard import dashboard_snapshot

    snap = dashboard_snapshot()
    print(snap["verdict"])     # "healthy" | "attention" | "critical"
    print(snap["total_score"]) # 0–10
    for sig in snap["signals"]:
        print(sig["name"], sig["score"], sig["detail"])

CLI::

    python3 tools/caretaker_dashboard.py
    python3 tools/caretaker_dashboard.py --json

Exit codes::

    0  healthy
    1  attention
    2  critical
    3  error (could not gather one or more signals)
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Signal data class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Signal:
    """A single dashboard signal with its score and detail."""

    name: str
    score: int          # 0, 1, or 2
    detail: str
    value: Any = None   # raw numeric value for downstream tools

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "score": self.score,
            "detail": self.detail,
        }
        if self.value is not None:
            d["value"] = self.value
        return d


# ---------------------------------------------------------------------------
# Signal gatherers
# ---------------------------------------------------------------------------

def check_writer_alive(writer: str = "qwen") -> Signal:
    """Check whether the writer process is running.

    Looks for a process matching ``writer_loop.py --writer <writer>``.
    """
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", f"writer_loop.py --writer {writer}"],
            text=True, stderr=subprocess.DEVNULL,
        )
        pids = [p.strip() for p in out.strip().split("\n") if p.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pids = []

    if len(pids) >= 1:
        return Signal("writer_alive", 2, f"running (pid {pids[0]})", value=len(pids))
    return Signal("writer_alive", 0, "not running")


def check_batch_alive(writer: str = "qwen") -> Signal:
    """Check whether the commit batch process is running."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", f"commit_batch.py --watch --writer {writer}"],
            text=True, stderr=subprocess.DEVNULL,
        )
        pids = [p.strip() for p in out.strip().split("\n") if p.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pids = []

    if len(pids) >= 1:
        return Signal("batch_alive", 2, f"running (pid {pids[0]})", value=len(pids))
    return Signal("batch_alive", 0, "not running")


def check_backlog(repo: Path = REPO_ROOT) -> Signal:
    """Count uncommitted files in the working tree."""
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=str(repo), text=True, stderr=subprocess.DEVNULL,
        )
        # Filter out untracked files (??) — only count modified/staged
        lines = [
            ln for ln in out.strip().split("\n")
            if ln.strip() and not ln.startswith("??")
        ]
        count = len(lines)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return Signal("backlog", 0, "git status failed", value=-1)

    if count == 0:
        return Signal("backlog", 2, "clean", value=0)
    if count <= 5:
        return Signal("backlog", 1, f"{count} file(s) uncommitted", value=count)
    return Signal("backlog", 0, f"{count} file(s) uncommitted", value=count)


def check_freshness(repo: Path = REPO_ROOT, healthy_sec: float = 120.0,
                     degraded_sec: float = 600.0) -> Signal:
    """Seconds since the last stroke in data/strokes.jsonl."""
    strokes_path = repo / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        return Signal("freshness_sec", 0, "no strokes.jsonl", value=None)

    last_ts: Optional[float] = None
    try:
        # Read last 5 lines — the final stroke is near the end
        with open(strokes_path, "r") as f:
            lines = f.readlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts_str = rec.get("ts") or rec.get("timestamp")
                if ts_str:
                    # Try ISO format parse
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(ts_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    last_ts = dt.timestamp()
                    break
            except (json.JSONDecodeError, ValueError, KeyError):
                continue
    except OSError:
        return Signal("freshness_sec", 0, "cannot read strokes.jsonl", value=None)

    if last_ts is None:
        return Signal("freshness_sec", 0, "no parseable strokes", value=None)

    age = time.time() - last_ts
    if age <= healthy_sec:
        return Signal("freshness_sec", 2, f"last stroke {age:.0f}s ago", value=round(age, 1))
    if age <= degraded_sec:
        return Signal("freshness_sec", 1, f"last stroke {age:.0f}s ago", value=round(age, 1))
    return Signal("freshness_sec", 0, f"last stroke {age:.0f}s ago (stale)", value=round(age, 1))


def check_momentum(repo: Path = REPO_ROOT, window_hours: float = 12.0) -> Signal:
    """Commit-momentum verdict over the rolling window."""
    try:
        from iamai.commit_momentum import (
            CommitMomentum,
            fetch_commit_timestamps,
        )
        cm = CommitMomentum(window_hours=window_hours)
        timestamps = fetch_commit_timestamps(repo=repo)
        result = cm.evaluate(timestamps)
        verdict = result.verdict

        score_map = {"accelerating": 2, "steady": 2, "decelerating": 1, "stalled": 0}
        score = score_map.get(verdict, 0)
        return Signal(
            "momentum", score,
            f"{verdict} (ratio {result.ratio:.2f}, newer={result.newer_count})",
            value=verdict,
        )
    except Exception as exc:
        return Signal("momentum", 0, f"error: {exc}")


# ---------------------------------------------------------------------------
# Dashboard aggregation
# ---------------------------------------------------------------------------

_VERDICT_THRESHOLDS = [
    (8, "healthy"),
    (5, "attention"),
    (0, "critical"),
]


def score_to_verdict(total: int) -> str:
    """Convert a total score (0–10) into a dashboard verdict."""
    for threshold, verdict in _VERDICT_THRESHOLDS:
        if total >= threshold:
            return verdict
    return "critical"


def dashboard_snapshot(
    repo: Path = REPO_ROOT,
    writer: str = "qwen",
    freshness_healthy_sec: float = 120.0,
    freshness_degraded_sec: float = 600.0,
    momentum_window_hours: float = 12.0,
) -> Dict[str, Any]:
    """Gather all signals and return a dashboard snapshot dict.

    Parameters
    ----------
    repo:
        Path to the repository root.
    writer:
        Writer identity to check (default ``"qwen"``).
    freshness_healthy_sec:
        Max age (seconds) for the last stroke to be considered healthy.
    freshness_degraded_sec:
        Max age (seconds) for the last stroke to be considered degraded.
    momentum_window_hours:
        Rolling window for commit momentum (hours).

    Returns
    -------
    Dict with keys: ``verdict``, ``total_score``, ``max_score``,
    ``signals`` (list of signal dicts), ``ts`` (ISO-8601 timestamp).
    """
    signals: List[Signal] = [
        check_writer_alive(writer=writer),
        check_batch_alive(writer=writer),
        check_backlog(repo=repo),
        check_freshness(repo=repo, healthy_sec=freshness_healthy_sec,
                        degraded_sec=freshness_degraded_sec),
        check_momentum(repo=repo, window_hours=momentum_window_hours),
    ]

    total = sum(s.score for s in signals)
    verdict = score_to_verdict(total)

    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()

    return {
        "verdict": verdict,
        "total_score": total,
        "max_score": len(signals) * 2,
        "signals": [s.to_dict() for s in signals],
        "ts": ts,
    }


# ---------------------------------------------------------------------------
# CLI-friendly report
# ---------------------------------------------------------------------------

def format_snapshot(snap: Dict[str, Any]) -> str:
    """Format a dashboard snapshot as a human-readable string."""
    lines = [
        f"=== Caretaker Dashboard === {snap['ts']}",
        f"Verdict: {snap['verdict'].upper()}  ({snap['total_score']}/{snap['max_score']})",
        "",
    ]
    for sig in snap["signals"]:
        score_bar = "●" * sig["score"] + "○" * (2 - sig["score"])
        lines.append(f"  [{score_bar}] {sig['name']:20s}  {sig['detail']}")
    return "\n".join(lines)
