"""Kind gap tracker — how long since each stroke kind last appeared?

``stroke_diversity`` counts how many of each kind exist in a window.
``stroke_freshness`` measures the age of the very last stroke.
Neither catches the case where one kind quietly starves while others
dominate — the totals look fine, but the *rhythm* is broken.

This module reads the tail of ``data/strokes.jsonl`` and computes, for
each kind, how many strokes ago it last appeared.  If any kind has been
absent for more than ``threshold`` strokes (default: 3× the number of
kinds, so 18 for six kinds), the repo is flagged.

===========  =================================================
verdict      meaning
===========  =================================================
``balanced`` every kind appeared within the threshold window
``warning``  at least one kind exceeds 2× the threshold
``starved``  at least one kind exceeds 3× the threshold
``empty``    no strokes found at all
===========  =================================================

Usage::

    from iamai.kind_gap import kind_gap, kind_gap_report

    info = kind_gap(repo)
    print(info["verdict"])     # "balanced"
    print(info["gaps"])        # {"thought": 3, "devlog": 7, ...}

    print(kind_gap_report(repo))
    # "balanced — all 6 kinds seen within last 18 strokes"
"""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_KINDS = ("thought", "devlog", "garden", "note", "metrics", "snippet")
_TAIL_SIZE = 4096  # bytes to read from end — covers hundreds of lines


def _read_tail(strokes_path: Path, nbytes: int = _TAIL_SIZE) -> list[dict]:
    """Read the last ``nbytes`` of the JSONL file and parse valid lines."""
    if not strokes_path.exists():
        return []
    with open(strokes_path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        if size == 0:
            return []
        read_size = min(size, nbytes)
        f.seek(-read_size, 2)
        chunk = f.read().decode("utf-8", errors="replace")
    lines = chunk.strip().split("\n")
    strokes: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def kind_gap(
    repo: Path,
    kinds: tuple[str, ...] = DEFAULT_KINDS,
    window: int = 50,
    threshold: int | None = None,
) -> dict:
    """Measure per-kind recency gaps over the last ``window`` strokes.

    Parameters
    ----------
    repo:
        Repository root (must contain ``data/strokes.jsonl``).
    kinds:
        Tuple of expected stroke kind names.
    window:
        Number of recent strokes to examine (default 50).
    threshold:
        Gap (in stroke count) beyond which a kind is considered starved.
        Defaults to ``3 * len(kinds)``.

    Returns
    -------
    dict with keys: ``verdict``, ``gaps`` (dict mapping kind → strokes
    since last seen, or ``None`` if absent), ``max_gap`` (int),
    ``starved_kinds`` (list), ``window`` (int), ``total_scanned`` (int).
    """
    if threshold is None:
        threshold = 3 * len(kinds)

    strokes_path = repo / "data" / "strokes.jsonl"
    all_strokes = _read_tail(strokes_path)
    # Take only the last ``window`` strokes
    recent = all_strokes[-window:] if len(all_strokes) > window else all_strokes
    total_scanned = len(recent)

    if total_scanned == 0:
        return {
            "verdict": "empty",
            "gaps": {k: None for k in kinds},
            "max_gap": None,
            "starved_kinds": list(kinds),
            "window": window,
            "total_scanned": 0,
        }

    # Compute gap: how many strokes ago did each kind last appear?
    gaps: dict[str, int | None] = {}
    for kind in kinds:
        last_seen_idx: int | None = None
        for i in range(total_scanned - 1, -1, -1):
            if recent[i].get("kind") == kind:
                last_seen_idx = i
                break
        if last_seen_idx is None:
            gaps[kind] = None  # not seen at all in window
        else:
            gaps[kind] = total_scanned - 1 - last_seen_idx

    # Determine verdict
    finite_gaps = [g for g in gaps.values() if g is not None]
    max_gap = max(finite_gaps) if finite_gaps else None

    starved_kinds = [
        k for k, g in gaps.items()
        if g is None or g > threshold
    ]
    warning_kinds = [
        k for k, g in gaps.items()
        if g is not None and threshold // 2 < g <= threshold
    ]

    if not starved_kinds and not warning_kinds:
        verdict = "balanced"
    elif starved_kinds:
        verdict = "starved"
    else:
        verdict = "warning"

    return {
        "verdict": verdict,
        "gaps": gaps,
        "max_gap": max_gap,
        "starved_kinds": starved_kinds,
        "window": window,
        "total_scanned": total_scanned,
    }


def kind_gap_report(
    repo: Path,
    kinds: tuple[str, ...] = DEFAULT_KINDS,
    window: int = 50,
    threshold: int | None = None,
) -> str:
    """One-line human-readable kind-gap summary.

    Example: ``"balanced — all 6 kinds seen within last 18 strokes"``
    """
    info = kind_gap(repo, kinds=kinds, window=window, threshold=threshold)
    if threshold is None:
        threshold = 3 * len(kinds)

    if info["verdict"] == "empty":
        return "empty — no strokes found in data/strokes.jsonl"

    if info["verdict"] == "balanced":
        return (
            f"balanced — all {len(kinds)} kinds seen within "
            f"last {threshold} strokes"
        )

    if info["verdict"] == "warning":
        names = ", ".join(info["starved_kinds"]) if info["starved_kinds"] else "none"
        return (
            f"warning — {len(info['starved_kinds'])} kind(s) approaching "
            f"starvation threshold ({threshold}): {names}"
        )

    # starved
    details = []
    for k in info["starved_kinds"]:
        g = info["gaps"][k]
        if g is None:
            details.append(f"{k}(absent)")
        else:
            details.append(f"{k}({g} ago)")
    return (
        f"starved — {len(info['starved_kinds'])} kind(s) exceed "
        f"threshold ({threshold}): {', '.join(details)}"
    )
