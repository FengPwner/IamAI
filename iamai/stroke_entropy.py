"""Stroke entropy — is the writer stuck in a loop?

``stroke_rate`` measures *how many*; this module measures *how varied*.
A writer that cycles through the same three modules (chunk_text →
parse_kv → retry → repeat) looks healthy on throughput but is actually
producing no new content.  Shannon entropy over recent stroke kinds
catches this in one number.

Scale (with ``window`` defaulting to the last 30 strokes):

==========  ================================================
verdict     meaning
==========  ================================================
``rich``    entropy ≥ 2.0 — good variety
``narrow``  entropy ≥ 1.0 — limited but not stuck
``loop``    entropy < 1.0 — cycling a small set of kinds
==========  ================================================

``entropy_report`` returns a one-liner for caretaker logs::

    from iamai.stroke_entropy import entropy, entropy_report
    info = entropy(repo, window=30)
    print(info["verdict"])   # "loop"
    print(info["shannon"])   # 0.87
    print(entropy_report(repo))
    # "loop — shannon 0.87 over 30 strokes (3 distinct kinds)"
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path


def _load_recent_kinds(strokes_path: Path, window: int) -> list[str]:
    """Read the ``kind`` field from the last *window* lines of strokes.jsonl.

    Seeks from the end so a 200 k-line file stays cheap.
    """
    if not strokes_path.exists():
        return []
    lines: list[str] = []
    with strokes_path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        if size == 0:
            return []
        # Read up to ~window * 512 bytes from the tail — generous for JSON lines.
        chunk = min(size, window * 512)
        fh.seek(-chunk, 2)
        raw = fh.read().decode("utf-8", errors="replace")
        lines = raw.splitlines()
    kinds: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        kind = rec.get("kind", "unknown")
        kinds.append(kind)
    return kinds[-window:]


def _shannon(values: list[str]) -> float:
    """Shannon entropy in bits over a list of categorical values."""
    if not values:
        return 0.0
    counts = Counter(values)
    n = len(values)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _classify(shannon: float) -> str:
    if shannon >= 2.0:
        return "rich"
    if shannon >= 1.0:
        return "narrow"
    return "loop"


def entropy(
    repo: Path | str | None = None,
    window: int = 30,
) -> dict:
    """Compute stroke entropy for the repo.

    Returns a dict with keys: ``shannon``, ``verdict``, ``window``,
    ``distinct``, ``total``.
    """
    if repo is None:
        repo = Path(__file__).resolve().parent.parent
    repo = Path(repo)
    strokes_path = repo / "data" / "strokes.jsonl"
    kinds = _load_recent_kinds(strokes_path, window)
    shannon = _shannon(kinds)
    return {
        "shannon": round(shannon, 3),
        "verdict": _classify(shannon),
        "window": window,
        "distinct": len(set(kinds)),
        "total": len(kinds),
    }


def entropy_report(
    repo: Path | str | None = None,
    window: int = 30,
) -> str:
    """One-line human-readable summary."""
    info = entropy(repo, window)
    return (
        f"{info['verdict']} — shannon {info['shannon']} "
        f"over {info['total']} strokes ({info['distinct']} distinct kinds)"
    )
