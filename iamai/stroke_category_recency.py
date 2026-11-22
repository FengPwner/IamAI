"""stroke_category_recency — detect categories going cold.

The writer produces strokes across six categories: thought, note,
devlog, garden, metrics, snippet.  ``stroke_category_balance`` measures
how evenly they are distributed; this module measures a different
question: **how long since each category was last written to?**

A category that hasn't received a stroke in hours is *cooling*.  One
that hasn't been touched in days is *cold*.  Detecting cooling early
lets the caretaker (or the writer itself) nudge the balance before a
category starves entirely.

Core metrics
------------

========================  =============================================
metric                    meaning
========================  =============================================
category_recency          dict mapping category → seconds since last
                          stroke (0 = just written)
coldest_category          category with the largest recency value
coldest_seconds           seconds since the coldest category was last
                          written to
warmth_score              0–100 composite; 100 = all categories were
                          touched within one cadence period
cold_categories           list of categories exceeding the cold
                          threshold
suggestion                which category to write next (the coldest
                          non-dead one, or ``None`` if all are warm)
========================  =============================================

Warmth score
------------

The warmth score uses a soft decay curve::

    warmth_i = 1 / (1 + recency_i / half_life)

where ``half_life`` is the expected interval between category rotations
(default: number_of_categories × stroke_cadence).  The composite warmth
is the mean across all categories, scaled to 0–100.

A warmth score above 80 means all categories are being fed regularly.
Below 50 means at least one category has gone cold.  Below 20 means
most categories are starving.

Cold threshold
--------------

A category is *cold* when its recency exceeds ``cold_multiplier ×
half_life`` (default: 3×).  This is soft — the writer may legitimately
focus on one category for a while — but persistent coldness is a
signal worth raising.

CLI
---

::

    python -m iamai.stroke_category_recency [--json] [--strokes PATH]

Exit codes: 0 = all warm, 1 = at least one cold category.

Written by Qwen during caretaker visit 807, 2026-11-23.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_STROKES = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"
_ALL_CATEGORIES = {"thought", "note", "devlog", "garden", "metrics", "snippet"}
_DEFAULT_COLD_MULTIPLIER = 3.0  # category is cold after 3× half-life
_DEFAULT_STROKE_CADENCE = 90.0  # seconds between strokes (6 categories × 15s)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_strokes(
    path: Path,
    n: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Load strokes from a JSONL file.  Returns the last *n* strokes."""
    if not path.exists():
        return []
    strokes: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if n is not None:
        strokes = strokes[-n:]
    return strokes


def _parse_timestamp(ts: str) -> float:
    """Parse an ISO-8601 timestamp to epoch seconds.  Handles Z suffix."""
    ts = ts.replace("Z", "+00:00")
    # Python 3.7+ fromisoformat handles +00:00
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------


def category_recency(
    strokes: Sequence[Dict[str, Any]],
    now: Optional[float] = None,
    categories: Optional[set] = None,
) -> Dict[str, float]:
    """Return seconds since the last stroke in each category.

    Categories with no strokes at all get ``float('inf')``.
    """
    cats = categories or _ALL_CATEGORIES
    result: Dict[str, float] = {c: float("inf") for c in cats}
    current_time = now if now is not None else time.time()

    for stroke in reversed(list(strokes)):
        kind = stroke.get("kind", "")
        if kind in result and result[kind] == float("inf"):
            ts = _parse_timestamp(stroke.get("at", ""))
            if ts > 0:
                result[kind] = max(0.0, current_time - ts)
        # early exit if all found
        if all(v != float("inf") for v in result.values()):
            break

    return result


def warmth_score(
    recency: Dict[str, float],
    half_life: Optional[float] = None,
) -> float:
    """Compute the composite warmth score (0–100).

    Each category contributes ``1 / (1 + recency / half_life)``.
    The mean across all categories is scaled to 0–100.
    """
    if not recency:
        return 0.0
    hl = half_life or (len(recency) * _DEFAULT_STROKE_CADENCE)
    if hl <= 0:
        hl = 1.0

    scores = []
    for cat, secs in recency.items():
        if secs == float("inf"):
            scores.append(0.0)
        else:
            scores.append(1.0 / (1.0 + secs / hl))

    return round(100.0 * sum(scores) / len(scores), 1)


def cold_categories(
    recency: Dict[str, float],
    half_life: Optional[float] = None,
    cold_multiplier: float = _DEFAULT_COLD_MULTIPLIER,
) -> List[str]:
    """Return categories whose recency exceeds the cold threshold."""
    hl = half_life or (len(recency) * _DEFAULT_STROKE_CADENCE)
    if hl <= 0:
        hl = 1.0
    threshold = cold_multiplier * hl
    return sorted(c for c, secs in recency.items() if secs > threshold)


def coldest_category(recency: Dict[str, float]) -> Optional[str]:
    """Return the category with the highest recency, or None if empty."""
    if not recency:
        return None
    return max(recency, key=lambda c: recency[c])


def suggestion(
    recency: Dict[str, float],
    half_life: Optional[float] = None,
    cold_multiplier: float = _DEFAULT_COLD_MULTIPLIER,
) -> Optional[str]:
    """Suggest which category to write next.

    Returns the coldest category, or ``None`` if all are warm.
    """
    cold = cold_categories(recency, half_life, cold_multiplier)
    if not cold:
        return None
    # return the coldest among the cold ones
    return max(cold, key=lambda c: recency[c])


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------


def recency_report(
    strokes_path: Optional[Path] = None,
    now: Optional[float] = None,
    categories: Optional[set] = None,
    half_life: Optional[float] = None,
    cold_multiplier: float = _DEFAULT_COLD_MULTIPLIER,
) -> Dict[str, Any]:
    """Produce a full category-recency report."""
    path = strokes_path or _DEFAULT_STROKES
    strokes = _load_strokes(path)

    rec = category_recency(strokes, now=now, categories=categories)
    ws = warmth_score(rec, half_life)
    cold = cold_categories(rec, half_life, cold_multiplier)
    coldest = coldest_category(rec)
    coldest_secs = rec[coldest] if coldest else 0.0
    sugg = suggestion(rec, half_life, cold_multiplier)

    return {
        "category_recency": {
            c: (round(secs, 1) if secs != float("inf") else -1)
            for c, secs in sorted(rec.items())
        },
        "warmth_score": ws,
        "coldest_category": coldest,
        "coldest_seconds": round(coldest_secs, 1) if coldest_secs != float("inf") else -1,
        "cold_categories": cold,
        "suggestion": sugg,
        "total_strokes": len(strokes),
    }


def recency_summary(report: Dict[str, Any]) -> str:
    """Format a human-readable summary of the recency report."""
    lines = [
        f"category recency report — warmth: {report['warmth_score']}/100",
        "",
    ]

    rec = report["category_recency"]
    for cat in sorted(rec):
        secs = rec[cat]
        if secs < 0:
            label = "never"
        elif secs < 60:
            label = f"{secs:.0f}s ago"
        elif secs < 3600:
            label = f"{secs / 60:.0f}m ago"
        elif secs < 86400:
            label = f"{secs / 3600:.1f}h ago"
        else:
            label = f"{secs / 86400:.1f}d ago"
        marker = " ❄" if cat in report.get("cold_categories", []) else ""
        lines.append(f"  {cat:10s}  {label}{marker}")

    lines.append("")
    if report["suggestion"]:
        lines.append(f"→ suggest writing: {report['suggestion']}")
    else:
        lines.append("✓ all categories warm")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check which stroke categories are going cold."
    )
    parser.add_argument(
        "--strokes",
        type=Path,
        default=_DEFAULT_STROKES,
        help="path to strokes.jsonl",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="output JSON instead of text",
    )
    parser.add_argument(
        "--cold-multiplier",
        type=float,
        default=_DEFAULT_COLD_MULTIPLIER,
        help="threshold multiplier for cold detection (default: 3.0)",
    )
    args = parser.parse_args(argv)

    report = recency_report(
        strokes_path=args.strokes,
        cold_multiplier=args.cold_multiplier,
    )

    if args.json_output:
        print(json.dumps(report, indent=2))
    else:
        print(recency_summary(report))

    # exit 1 if any category is cold
    return 1 if report["cold_categories"] else 0


if __name__ == "__main__":
    sys.exit(_cli())
