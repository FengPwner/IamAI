"""Measure content diversity across stroke kinds.

Caretakers already know *how fast* the writer is (stroke_rate), *how
steady* it is (cadence_adherence), and *whether it's alive*
(stall_classifier). But a healthy-looking writer can still be
producing lopsided content — 90% thoughts and almost no garden or
metrics strokes. That's a diversity problem, not a rate problem.

This module reads ``data/strokes.jsonl`` and computes:

- **Kind distribution** — what fraction of strokes belong to each kind
- **Shannon entropy** — a single diversity score (0 = one kind only,
  higher = more balanced)
- **Effective number of kinds** — exp(entropy), interpretable as "the
  writer is behaving as if it had N equally-represented kinds"
- **Underrepresented kinds** — which kinds fall below a threshold
- **Diversity grade** — A/B/C/F for quick at-a-glance assessment

Usage::

    from iamai.content_diversity import diversity_report, diversity_summary

    report = diversity_report(window_hours=6.0)
    print(report["entropy"])           # e.g. 1.72
    print(report["effective_kinds"])   # e.g. 5.6
    print(report["underrepresented"])  # e.g. ["metrics"]
    print(report["grade"])             # "A"

    summary = diversity_summary()
    print(summary)
    # "diversity A: 5.6/6 effective kinds, entropy 1.72, under: none"
"""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


_DEFAULT_STROKES_PATH = Path("data/strokes.jsonl")

# All six canonical kinds the writer should produce
ALL_KINDS = ("devlog", "garden", "metrics", "note", "snippet", "thought")


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a timezone-aware datetime."""
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_strokes(path: Path) -> list[dict]:
    """Load strokes from a JSONL file."""
    strokes = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                obj["_dt"] = _parse_timestamp(obj["at"])
                strokes.append(obj)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return strokes


def _strokes_in_window(
    strokes: list[dict],
    now: datetime,
    window_hours: float,
) -> list[dict]:
    """Filter strokes to those within the time window."""
    cutoff = now - timedelta(hours=window_hours)
    return [s for s in strokes if s["_dt"] >= cutoff]


def _shannon_entropy(counts: Counter, total: int) -> float:
    """Compute Shannon entropy in nats (natural log).

    Args:
        counts: kind -> count mapping
        total: total number of items

    Returns:
        Entropy value. 0.0 if all items are one kind.
    """
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            h -= p * math.log(p)
    return h


def _max_entropy(n_kinds: int) -> float:
    """Maximum possible entropy for n equally-represented kinds."""
    if n_kinds <= 1:
        return 0.0
    return math.log(n_kinds)


def diversity_report(
    window_hours: float = 6.0,
    strokes_path: Path | str | None = None,
    now: datetime | None = None,
    underrepresented_threshold: float = 0.05,
) -> dict:
    """Compute content diversity report.

    Args:
        window_hours: how many hours back to look (default 6.0)
        strokes_path: path to strokes JSONL file
        now: current time override for testing
        underrepresented_threshold: fraction below which a kind is
            considered underrepresented (default 0.05, i.e. <5%)

    Returns:
        Dict with keys:
        - kind_counts: dict[str, int], raw counts per kind
        - kind_fractions: dict[str, float], fraction per kind
        - entropy: float, Shannon entropy in nats
        - max_entropy: float, maximum possible entropy for 6 kinds
        - normalized_entropy: float, entropy / max_entropy (0-1 scale)
        - effective_kinds: float, exp(entropy), interpretable count
        - underrepresented: list[str], kinds below threshold
        - grade: str, A/B/C/F
        - total: int, total strokes in window
        - window_hours: float, the window used
    """
    path = Path(strokes_path) if strokes_path else _DEFAULT_STROKES_PATH
    if now is None:
        now = datetime.now(timezone.utc)

    all_strokes = _load_strokes(path)
    windowed = _strokes_in_window(all_strokes, now, window_hours)
    total = len(windowed)

    # Count per kind, ensuring all canonical kinds are represented
    raw_counts: Counter = Counter()
    for s in windowed:
        raw_counts[s.get("kind", "unknown")] += 1

    # Build full counts including zero-count canonical kinds
    kind_counts = {k: raw_counts.get(k, 0) for k in ALL_KINDS}
    # Include any non-canonical kinds that appeared
    for k in raw_counts:
        if k not in kind_counts:
            kind_counts[k] = raw_counts[k]

    # Fractions
    kind_fractions = {
        k: (v / total if total > 0 else 0.0)
        for k, v in kind_counts.items()
    }

    # Entropy
    entropy = _shannon_entropy(Counter(kind_counts), total)
    max_ent = _max_entropy(len(ALL_KINDS))
    normalized = entropy / max_ent if max_ent > 0 else 0.0

    # Effective number of kinds
    effective = math.exp(entropy) if entropy > 0 else 0.0

    # Underrepresented kinds (among canonical kinds only)
    underrepresented = [
        k for k in ALL_KINDS
        if kind_fractions.get(k, 0.0) < underrepresented_threshold
    ]

    # Grade
    grade = _grade_diversity(normalized)

    return {
        "kind_counts": kind_counts,
        "kind_fractions": {k: round(v, 4) for k, v in kind_fractions.items()},
        "entropy": round(entropy, 4),
        "max_entropy": round(max_ent, 4),
        "normalized_entropy": round(normalized, 4),
        "effective_kinds": round(effective, 2),
        "underrepresented": underrepresented,
        "grade": grade,
        "total": total,
        "window_hours": window_hours,
    }


def _grade_diversity(normalized_entropy: float) -> str:
    """Assign a letter grade based on normalized entropy.

    Args:
        normalized_entropy: entropy / max_entropy, range [0, 1]

    Returns:
        "A" (>=0.90), "B" (>=0.75), "C" (>=0.50), or "F" (<0.50)
    """
    if normalized_entropy >= 0.90:
        return "A"
    if normalized_entropy >= 0.75:
        return "B"
    if normalized_entropy >= 0.50:
        return "C"
    return "F"


def diversity_summary(
    window_hours: float = 6.0,
    strokes_path: Path | str | None = None,
) -> str:
    """One-line human-readable diversity summary.

    Args:
        window_hours: how many hours back to look
        strokes_path: optional path override

    Returns:
        Summary like "diversity A: 5.6/6 effective kinds, entropy 1.72, under: none"
    """
    report = diversity_report(
        window_hours=window_hours,
        strokes_path=strokes_path,
    )

    grade = report["grade"]
    eff = report["effective_kinds"]
    ent = report["entropy"]
    under = report["underrepresented"]

    under_str = ", ".join(under) if under else "none"

    return (
        f"diversity {grade}: {eff}/{len(ALL_KINDS)} effective kinds, "
        f"entropy {ent:.2f}, under: {under_str}"
    )


def diversity_trend(
    strokes_path: Path | str | None = None,
    now: datetime | None = None,
) -> dict:
    """Compare short-term vs long-term diversity.

    Args:
        strokes_path: optional path override
        now: time override for testing

    Returns:
        Dict with keys:
        - short_entropy: float (1-hour window)
        - long_entropy: float (6-hour window)
        - short_effective: float
        - long_effective: float
        - verdict: "improving" | "stable" | "degrading" | "unknown"
    """
    if now is None:
        now = datetime.now(timezone.utc)

    short = diversity_report(
        window_hours=1.0,
        strokes_path=strokes_path,
        now=now,
    )
    long = diversity_report(
        window_hours=6.0,
        strokes_path=strokes_path,
        now=now,
    )

    s_ent = short["normalized_entropy"]
    l_ent = long["normalized_entropy"]

    if long["total"] == 0:
        return {
            "short_entropy": short["entropy"],
            "long_entropy": long["entropy"],
            "short_effective": short["effective_kinds"],
            "long_effective": long["effective_kinds"],
            "verdict": "unknown",
        }

    diff = s_ent - l_ent
    if diff > 0.05:
        verdict = "improving"
    elif diff < -0.05:
        verdict = "degrading"
    else:
        verdict = "stable"

    return {
        "short_entropy": short["entropy"],
        "long_entropy": long["entropy"],
        "short_effective": short["effective_kinds"],
        "long_effective": long["effective_kinds"],
        "verdict": verdict,
    }
