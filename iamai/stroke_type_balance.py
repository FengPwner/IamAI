"""stroke_type_balance — measure how evenly the writer distributes output kinds.

The qwen writer produces six stroke kinds in a fixed rotation:
metrics, note, snippet, thought, devlog, garden.  A healthy writer
hits all six roughly equally over any rolling window.  If one kind
starts dominating (e.g. 60% devlog, 5% garden), the rotation is
drifting and the output becomes one-dimensional.

This module computes:

- **per-kind counts** — how many strokes of each kind in the window
- **per-kind share** — fraction of total (ideal: 1/6 ≈ 0.167 each)
- **evenness index** — normalised entropy (0.0 = one kind dominates,
  1.0 = perfectly uniform)
- **verdict** — balanced / skewed / lopsided

Usage::

    from iamai.stroke_type_balance import balance_report, balance_summary

    report = balance_report(strokes_path="data/strokes.jsonl", window=60)
    print(balance_summary(report))
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

EXPECTED_KINDS = ("metrics", "note", "snippet", "thought", "devlog", "garden")
N_KINDS = len(EXPECTED_KINDS)
MAX_ENTROPY = math.log(N_KINDS)  # entropy of a perfectly uniform distribution


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BalanceReport:
    """Summary of stroke-type distribution over a window."""

    counts: dict[str, int] = field(default_factory=dict)
    total: int = 0
    shares: dict[str, float] = field(default_factory=dict)
    evenness: float = 0.0
    verdict: str = "unknown"
    dominant_kind: Optional[str] = None
    missing_kinds: list[str] = field(default_factory=list)
    window_size: int = 0


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def _load_kinds(strokes_path: str | Path, window: int = 60) -> list[str]:
    """Return the last *window* stroke kinds from the JSONL file."""
    path = Path(strokes_path)
    if not path.exists():
        return []
    kinds: list[str] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            k = rec.get("kind")
            if k:
                kinds.append(k)
    return kinds[-window:]


def compute_shares(counts: dict[str, int], total: int) -> dict[str, float]:
    """Fraction of each kind, including zero-share for missing kinds."""
    if total == 0:
        return {k: 0.0 for k in EXPECTED_KINDS}
    return {k: counts.get(k, 0) / total for k in EXPECTED_KINDS}


def compute_evenness(shares: dict[str, float]) -> float:
    """Normalised Shannon entropy in [0, 1].

    1.0 = perfectly uniform across all expected kinds.
    0.0 = all mass on a single kind.
    """
    if not shares or max(shares.values()) == 0.0:
        return 0.0
    entropy = 0.0
    for p in shares.values():
        if p > 0:
            entropy -= p * math.log(p)
    return entropy / MAX_ENTROPY if MAX_ENTROPY > 0 else 0.0


def verdict_for(evenness: float) -> str:
    """Classify evenness into a human-readable verdict."""
    if evenness >= 0.85:
        return "balanced"
    if evenness >= 0.60:
        return "skewed"
    return "lopsided"


def find_dominant(counts: dict[str, int]) -> Optional[str]:
    """Return the kind with the highest count, or None if empty."""
    if not counts or sum(counts.values()) == 0:
        return None
    return max(counts, key=counts.get)


def find_missing(counts: dict[str, int]) -> list[str]:
    """Return expected kinds with zero count."""
    return [k for k in EXPECTED_KINDS if counts.get(k, 0) == 0]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def balance_report(
    strokes_path: str | Path = "data/strokes.jsonl",
    window: int = 60,
) -> BalanceReport:
    """Compute stroke-type balance over the last *window* strokes."""
    kinds = _load_kinds(strokes_path, window)
    counts = dict(Counter(kinds))
    total = sum(counts.values())
    shares = compute_shares(counts, total)
    evenness = compute_evenness(shares)
    return BalanceReport(
        counts=counts,
        total=total,
        shares=shares,
        evenness=round(evenness, 4),
        verdict=verdict_for(evenness),
        dominant_kind=find_dominant(counts),
        missing_kinds=find_missing(counts),
        window_size=window,
    )


def balance_from_kinds(kinds: list[str]) -> BalanceReport:
    """Compute balance from a pre-loaded list of kind strings (no file I/O)."""
    counts = dict(Counter(kinds))
    total = sum(counts.values())
    shares = compute_shares(counts, total)
    evenness = compute_evenness(shares)
    return BalanceReport(
        counts=counts,
        total=total,
        shares=shares,
        evenness=round(evenness, 4),
        verdict=verdict_for(evenness),
        dominant_kind=find_dominant(counts),
        missing_kinds=find_missing(counts),
        window_size=len(kinds),
    )


def balance_summary(report: BalanceReport) -> str:
    """One-line human-readable summary."""
    if report.total == 0:
        return "no strokes in window"
    lines = [
        f"stroke_type_balance: {report.verdict} "
        f"(evenness={report.evenness:.2f}, n={report.total})",
    ]
    for k in EXPECTED_KINDS:
        c = report.counts.get(k, 0)
        s = report.shares.get(k, 0.0)
        lines.append(f"  {k:>10s}: {c:4d}  ({s:.1%})")
    if report.missing_kinds:
        lines.append(f"  missing: {', '.join(report.missing_kinds)}")
    if report.dominant_kind:
        lines.append(f"  dominant: {report.dominant_kind}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Stroke-type balance checker")
    ap.add_argument("--strokes", default="data/strokes.jsonl")
    ap.add_argument("--window", type=int, default=60)
    args = ap.parse_args()

    report = balance_report(args.strokes, args.window)
    print(balance_summary(report))


if __name__ == "__main__":
    main()
