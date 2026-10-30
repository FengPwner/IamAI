"""Caretaker patience — how long should the caretaker wait before escalating?

A caretaker that escalates on the first stall is a nervous wreck.
A caretaker that never escalates is asleep at the wheel.

This module computes a **patience budget** — how many consecutive stalls
the caretaker should tolerate before escalating — based on the repo's
recent reliability history. A repo that has been reliable for days earns
more patience; one that stalls every hour gets less.

The intuition is borrowed from TCP congestion control: after a long
period of healthy throughput, you can afford to lose a few packets
before panicking. After a recent congestion event, every loss matters.

Patience interpretation
-----------------------

========  ============================================================
budget    meaning
========  ============================================================
≥ 5       generous — repo has been rock-solid, tolerate short stalls
3–4       normal — average reliability, standard escalation window
1–2       tight — recent problems, escalate quickly
0         immediate — no patience left, escalate on next stall
========  ============================================================

Formula::

    reliability = healthy_visits / total_visits  (capped at 1.0)
    patience    = floor(reliability * max_budget)

``max_budget`` defaults to 6 — the caretaker never tolerates more than
six consecutive stalls regardless of how good things have been.

Design choices
--------------

- **Pure computation.**  Reads visit logs and stall data; writes nothing.
- **Window-based.**  Only the last ``window_hours`` (default 24) matter.
  What happened last week is not relevant to today's patience.
- **Visit-based, not time-based.**  Counts caretaker visits, not elapsed
  time, because a visit is the unit of caretaker attention.

Usage::

    from iamai.caretaker_patience import patience_budget, patience_report

    info = patience_budget(repo_root=".", window_hours=24)
    print(info["budget"])       # 4
    print(info["reliability"])  # 0.82

    print(patience_report(repo_root="."))
    # "patience 4/6 (reliability 0.82, 9/11 visits healthy in 24h)"
"""

from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_MAX_BUDGET = 6
DEFAULT_WINDOW_HOURS = 24.0


def _count_visits_in_window(
    repo_root: Path,
    since: datetime,
) -> dict[str, int]:
    """Count caretaker visits and stalls from git log within the window.

    Returns a dict with keys ``visits`` and ``stalls``.
    """
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%S")
    visits = 0
    stalls = 0

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"--since={since_iso}"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                visits += 1
                lower = line.lower()
                if "stall" in lower or "recovery" in lower or "reclaim" in lower:
                    stalls += 1
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return {"visits": visits, "stalls": stalls}


def _parse_strokes_since(
    repo_root: Path,
    since: datetime,
) -> int:
    """Count strokes written since a given time."""
    strokes_path = repo_root / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        return 0
    count = 0
    with open(strokes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            at_str = record.get("at", "")
            if not at_str:
                continue
            try:
                at = datetime.fromisoformat(at_str)
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if at >= since:
                count += 1
    return count


def patience_budget(
    repo_root: str | Path = ".",
    max_budget: int = DEFAULT_MAX_BUDGET,
    window_hours: float = DEFAULT_WINDOW_HOURS,
) -> dict[str, Any]:
    """Compute the caretaker's patience budget.

    Parameters
    ----------
    repo_root:
        Path to the repository root.
    max_budget:
        Maximum patience budget (default 6).
    window_hours:
        How many hours of history to analyse (default 24).

    Returns
    -------
    dict with keys: ``budget``, ``reliability``, ``visits``,
    ``stalls``, ``healthy_visits``, ``max_budget``, ``window_hours``.
    """
    root = Path(repo_root).resolve()
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=window_hours)

    visit_info = _count_visits_in_window(root, since)
    total_visits = visit_info["visits"]
    stalls = visit_info["stalls"]
    healthy_visits = max(total_visits - stalls, 0)

    if total_visits == 0:
        # No visits in window — assume healthy but grant minimal patience.
        reliability = 1.0
    else:
        reliability = min(healthy_visits / total_visits, 1.0)

    budget = math.floor(reliability * max_budget)

    return {
        "budget": budget,
        "reliability": round(reliability, 4),
        "visits": total_visits,
        "stalls": stalls,
        "healthy_visits": healthy_visits,
        "max_budget": max_budget,
        "window_hours": window_hours,
    }


def patience_report(
    repo_root: str | Path = ".",
    max_budget: int = DEFAULT_MAX_BUDGET,
    window_hours: float = DEFAULT_WINDOW_HOURS,
) -> str:
    """One-line human-readable patience summary."""
    info = patience_budget(repo_root, max_budget, window_hours)
    return (
        f"patience {info['budget']}/{info['max_budget']} "
        f"(reliability {info['reliability']:.2f}, "
        f"{info['healthy_visits']}/{info['visits']} visits healthy "
        f"in {info['window_hours']:.0f}h)"
    )
