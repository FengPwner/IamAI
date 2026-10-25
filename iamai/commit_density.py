"""commit_density — measure how much real change each commit carries.

A repo with 1500+ commits sounds impressive until you realise half of
them only touched timestamps or re-indented a JSON file.  This module
answers: *what fraction of each commit is actual content change?*

Design
------

Input : a list of commit dicts, each with at least:
        - ``hash``    (str)  short sha
        - ``files``   (int)  files changed
        - ``insertions`` (int)  lines added
        - ``deletions``    (int)  lines removed
        - ``timestamp``    (datetime)  commit time

Output: a density report with per-commit scores and an aggregate.

Density formula
---------------

    raw_change   = insertions + deletions
    noise_floor  = 2            # every commit has at least a timestamp bump
    useful       = max(0, raw_change - noise_floor)
    density      = useful / max(raw_change, 1)

A commit that adds 50 lines of new code scores ~0.96.
A commit that changes exactly 2 lines (e.g. a counter bump) scores 0.0.

Aggregate labels
================

==========  =====================================================
label       meaning
==========  =====================================================
dense       mean density >= 0.70 — most commits carry real work
moderate    mean density 0.40–0.70 — mixed bag
thin        mean density 0.20–0.40 — lots of housekeeping
hollow      mean density < 0.20 — the repo is mostly churning
==========  =====================================================
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


NOISE_FLOOR = 2  # minimum lines changed that we consider "free"


def commit_density(
    insertions: int,
    deletions: int,
    noise_floor: int = NOISE_FLOOR,
) -> float:
    """Return density score for a single commit (0.0 – 1.0)."""
    raw = insertions + deletions
    if raw <= 0:
        return 0.0
    useful = max(0, raw - noise_floor)
    return round(useful / raw, 4)


def score_commits(
    commits: List[Dict[str, Any]],
    noise_floor: int = NOISE_FLOOR,
) -> List[Dict[str, Any]]:
    """Score each commit and return enriched list."""
    scored = []
    for c in commits:
        ins = c.get("insertions", 0)
        dels = c.get("deletions", 0)
        d = commit_density(ins, dels, noise_floor)
        scored.append({
            "hash": c.get("hash", "?"),
            "timestamp": c.get("timestamp"),
            "files": c.get("files", 0),
            "insertions": ins,
            "deletions": dels,
            "density": d,
        })
    return scored


def aggregate_label(mean_density: float) -> str:
    """Classify the overall repo density."""
    if mean_density >= 0.70:
        return "dense"
    if mean_density >= 0.40:
        return "moderate"
    if mean_density >= 0.20:
        return "thin"
    return "hollow"


def density_report(
    commits: List[Dict[str, Any]],
    noise_floor: int = NOISE_FLOOR,
) -> Dict[str, Any]:
    """Full density report with per-commit scores and aggregate."""
    scored = score_commits(commits, noise_floor)
    if not scored:
        return {
            "count": 0,
            "mean_density": 0.0,
            "median_density": 0.0,
            "label": "hollow",
            "commits": [],
        }

    densities = [s["density"] for s in scored]
    mean_d = sum(densities) / len(densities)
    sorted_d = sorted(densities)
    mid = len(sorted_d) // 2
    median_d = (
        sorted_d[mid]
        if len(sorted_d) % 2 == 1
        else (sorted_d[mid - 1] + sorted_d[mid]) / 2
    )

    return {
        "count": len(scored),
        "mean_density": round(mean_d, 4),
        "median_density": round(median_d, 4),
        "label": aggregate_label(mean_d),
        "commits": scored,
    }


def density_summary(report: Dict[str, Any]) -> str:
    """One-line human-readable summary."""
    n = report["count"]
    if n == 0:
        return "no commits to score"
    return (
        f"{n} commits scored: "
        f"mean density {report['mean_density']:.2f}, "
        f"median {report['median_density']:.2f} "
        f"({report['label']})"
    )
