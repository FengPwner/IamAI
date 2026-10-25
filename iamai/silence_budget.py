"""Silence budget: how much stalling a time window can still absorb.

``idle_budget`` answers "is the writer idle *right now*?"  This module
answers the broader question: **how much silence has accumulated in the
last N hours, and how much more can we tolerate before intervention?**

Concept
-------

Every rolling window (default 24 h) starts with a full silence budget.
Each stall event (gap > cadence) *spends* budget proportional to its
duration.  When the budget runs out, the caretaker should escalate.

Budget formula::

    window_budget  = window_seconds * max_silence_fraction
                       # default: 24h * 0.10 = 2.4 h of silence allowed

    spent          = sum(min(gap_s, cap_s) for gap in stalls_in_window)
    remaining      = max(0, window_budget - spent)
    fraction_left  = remaining / window_budget

Labels::

    plenty     fraction_left >= 0.50  — normal operations
    tightening fraction_left >= 0.25  — watch closely
    exhausted  fraction_left >  0.00  — intervene soon
    bankrupt   fraction_left == 0.00  — escalate now

Stall events are read from ``data/strokes.jsonl`` by computing inter-stroke
gaps and flagging any gap that exceeds the configured cadence.

Usage::

    from iamai.silence_budget import SilenceBudget, silence_report

    sb = SilenceBudget(cadence_seconds=15, window_hours=24, max_fraction=0.10)
    report = sb.evaluate(stall_gaps=[120, 300, 60])
    # report.verdict -> "plenty" (spent 480s of 8640s budget)

    print(silence_report())  # one-liner for CLI
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO_ROOT / "data" / "strokes.jsonl"


@dataclass(frozen=True)
class SilenceBudget:
    """Configuration for rolling silence-budget tracking.

    Parameters
    ----------
    cadence_seconds : int
        Expected inter-stroke gap.  Any gap larger than this counts as
        a stall event that spends budget.
    window_hours : int
        Rolling window size in hours (default 24).
    max_fraction : float
        Maximum fraction of the window that may be silent (default 0.10,
        i.e. 10 %).
    cap_seconds : float
        Per-stall cap to prevent a single mega-stall from bankrupting the
        entire budget.  Default: window_budget itself.
    """

    cadence_seconds: int = 15
    window_hours: int = 24
    max_fraction: float = 0.10
    cap_seconds: float = 0.0  # 0 = use window_budget as cap

    @property
    def window_seconds(self) -> int:
        return self.window_hours * 3600

    @property
    def window_budget(self) -> float:
        """Total silence seconds allowed in the window."""
        return self.window_seconds * self.max_fraction

    @property
    def effective_cap(self) -> float:
        return self.cap_seconds if self.cap_seconds > 0 else self.window_budget

    def evaluate(self, stall_gaps: Sequence[float]) -> "BudgetResult":
        """Evaluate silence consumption for a list of stall durations.

        Parameters
        ----------
        stall_gaps : sequence of float
            Duration (seconds) of each stall event in the current window.
            Only gaps exceeding ``cadence_seconds`` should be included.

        Returns
        -------
        BudgetResult with spent, remaining, fraction_left, and verdict.
        """
        cap = self.effective_cap
        spent = sum(min(g, cap) for g in stall_gaps)
        remaining = max(0.0, self.window_budget - spent)
        fraction_left = remaining / self.window_budget if self.window_budget > 0 else 0.0
        verdict = _classify(fraction_left)
        return BudgetResult(
            spent=round(spent, 1),
            remaining=round(remaining, 1),
            budget=round(self.window_budget, 1),
            fraction_left=round(fraction_left, 4),
            stall_count=len(stall_gaps),
            verdict=verdict,
            window_hours=self.window_hours,
        )


@dataclass(frozen=True)
class BudgetResult:
    """Result of a silence-budget evaluation."""

    spent: float
    remaining: float
    budget: float
    fraction_left: float
    stall_count: int
    verdict: str
    window_hours: int

    def describe(self) -> str:
        pct = self.fraction_left * 100
        spent_min = self.spent / 60
        budget_min = self.budget / 60
        return (
            f"{self.verdict}: {spent_min:.1f}m / {budget_min:.1f}m spent "
            f"({self.stall_count} stall(s) in {self.window_hours}h window), "
            f"{pct:.0f}% budget remaining"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "spent_seconds": self.spent,
            "remaining_seconds": self.remaining,
            "budget_seconds": self.budget,
            "fraction_left": self.fraction_left,
            "stall_count": self.stall_count,
            "verdict": self.verdict,
            "window_hours": self.window_hours,
        }


def _classify(fraction_left: float) -> str:
    """Map budget fraction to a verdict label."""
    if fraction_left >= 0.50:
        return "plenty"
    if fraction_left >= 0.25:
        return "tightening"
    if fraction_left > 0.0:
        return "exhausted"
    return "bankrupt"


# ---------------------------------------------------------------------------
# Stroke-file helpers
# ---------------------------------------------------------------------------


def extract_stall_gaps(
    strokes_file: Path | None = None,
    cadence_seconds: int = 15,
    window_hours: int = 24,
    now: float | None = None,
) -> list[float]:
    """Read strokes.jsonl and return stall-gap durations within the window.

    A stall gap is any inter-stroke interval exceeding ``cadence_seconds``.
    Only gaps whose *end* falls within the rolling window are included.
    """
    import time as _time

    path = strokes_file or STROKES_FILE
    if not path.exists():
        return []

    current = now or _time.time()
    window_start = current - (window_hours * 3600)

    timestamps: list[float] = []
    try:
        for line in path.read_text(encoding="utf-8").strip().splitlines():
            try:
                entry = json.loads(line)
                ts = entry.get("timestamp") or entry.get("ts") or entry.get("at")
                if ts is None:
                    continue
                if isinstance(ts, (int, float)):
                    timestamps.append(float(ts))
                else:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    timestamps.append(dt.timestamp())
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
    except OSError:
        return []

    if len(timestamps) < 2:
        return []

    timestamps.sort()
    gaps: list[float] = []
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        if gap > cadence_seconds and timestamps[i] >= window_start:
            gaps.append(gap)

    return gaps


def silence_report(
    cadence_seconds: int = 15,
    window_hours: int = 24,
    max_fraction: float = 0.10,
    strokes_file: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """End-to-end silence budget report from strokes.jsonl."""
    sb = SilenceBudget(
        cadence_seconds=cadence_seconds,
        window_hours=window_hours,
        max_fraction=max_fraction,
    )
    gaps = extract_stall_gaps(
        strokes_file=strokes_file,
        cadence_seconds=cadence_seconds,
        window_hours=window_hours,
        now=now,
    )
    result = sb.evaluate(gaps)
    return result.to_dict()
