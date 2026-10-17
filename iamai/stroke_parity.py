"""Stroke parity — verify that every written stroke reached the git tree.

The writer appends to ``data/strokes.jsonl`` every ~15 seconds.  The batch
committer snapshots the working tree every ~600 seconds and pushes.  Between
those two events, strokes sit on disk but are *uncommitted*.  If the process
crashes, those uncommitted strokes are lost.

This module measures the gap:

- **total strokes** in the JSONL log (ground truth of what was written)
- **committed strokes** — strokes visible in the latest committed version
  of the JSONL file (what git knows about)
- **orphan strokes** — strokes written to disk but not yet committed
  (total − committed)
- **parity ratio** — committed / total; 1.0 means perfectly in sync

A parity ratio below 1.0 is normal between batch commits.  A ratio that
stays below 1.0 for longer than two batch intervals indicates a problem:
the committer is not keeping up, or git is failing silently.

All functions accept an explicit ``repo`` path so they work in tests
without touching the real repo.

Usage::

    from iamai.stroke_parity import (
        stroke_parity, parity_summary, orphan_strokes,
    )

    p = stroke_parity(repo)
    print(p.total, p.committed, p.orphan_count, p.ratio)

    # Human-readable:
    print(parity_summary(repo))
    # "3200/3205 strokes committed (99.84%), 5 orphans pending"

    # Just the orphan seq numbers:
    orphans = orphan_strokes(repo)
    # [3198, 3199, 3200, 3201, 3202]
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_DEFAULT_STROKES_FILE = "data/strokes.jsonl"


@dataclass
class ParityReport:
    """Snapshot of stroke parity at a point in time."""

    total: int = 0
    committed: int = 0
    orphan_count: int = 0
    orphan_seqs: List[int] = field(default_factory=list)
    ratio: float = 1.0
    by_kind: Dict[str, Dict[str, int]] = field(default_factory=dict)

    @property
    def is_synced(self) -> bool:
        """True when every written stroke is committed."""
        return self.orphan_count == 0

    @property
    def critical(self) -> bool:
        """True when orphan count exceeds 20 (more than one missed batch)."""
        return self.orphan_count > 20


def _read_strokes(path: Path) -> List[Dict[str, Any]]:
    """Parse a strokes JSONL file into a list of dicts.

    Blank lines and malformed JSON lines are silently skipped so that
    a partially-written last line does not crash the reader.
    """
    strokes: List[Dict[str, Any]] = []
    if not path.exists():
        return strokes
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return strokes


def _committed_strokes(repo: Path, strokes_file: str = _DEFAULT_STROKES_FILE) -> List[Dict[str, Any]]:
    """Read the committed (HEAD) version of the strokes file via ``git show``.

    Returns an empty list if the file does not exist in HEAD (e.g. a
    brand-new repo with no commits yet).
    """
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{strokes_file}"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        strokes: List[Dict[str, Any]] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return strokes
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _seq_set(strokes: List[Dict[str, Any]]) -> set:
    """Extract the set of seq numbers from a list of stroke dicts."""
    return {s["seq"] for s in strokes if "seq" in s}


def _kind_breakdown(
    all_strokes: List[Dict[str, Any]],
    committed_seqs: set,
) -> Dict[str, Dict[str, int]]:
    """Per-kind breakdown of total, committed, and orphan counts."""
    breakdown: Dict[str, Dict[str, int]] = {}
    for s in all_strokes:
        kind = s.get("kind", "unknown")
        seq = s.get("seq")
        if kind not in breakdown:
            breakdown[kind] = {"total": 0, "committed": 0, "orphan": 0}
        breakdown[kind]["total"] += 1
        if seq in committed_seqs:
            breakdown[kind]["committed"] += 1
        else:
            breakdown[kind]["orphan"] += 1
    return breakdown


def stroke_parity(
    repo: Optional[Path] = None,
    strokes_file: str = _DEFAULT_STROKES_FILE,
) -> ParityReport:
    """Compute stroke parity between disk and git HEAD.

    Parameters
    ----------
    repo : Path or None
        Repository root.  Defaults to ``Path(".")``.
    strokes_file : str
        Relative path to the strokes JSONL file inside *repo*.

    Returns
    -------
    ParityReport
        A snapshot of the current parity state.
    """
    repo = Path(repo) if repo else Path(".")
    disk_path = repo / strokes_file

    all_strokes = _read_strokes(disk_path)
    committed = _committed_strokes(repo, strokes_file)

    total = len(all_strokes)
    committed_count = len(committed)
    committed_seqs = _seq_set(committed)
    all_seqs = _seq_set(all_strokes)
    orphan_seqs = sorted(all_seqs - committed_seqs)
    orphan_count = len(orphan_seqs)
    ratio = committed_count / total if total > 0 else 1.0

    by_kind = _kind_breakdown(all_strokes, committed_seqs)

    return ParityReport(
        total=total,
        committed=committed_count,
        orphan_count=orphan_count,
        orphan_seqs=orphan_seqs,
        ratio=ratio,
        by_kind=by_kind,
    )


def parity_summary(
    repo: Optional[Path] = None,
    strokes_file: str = _DEFAULT_STROKES_FILE,
) -> str:
    """Human-readable one-liner of the parity state.

    Examples::

        "3200/3205 strokes committed (99.84%), 5 orphans pending"
        "3205/3205 strokes committed (100.00%), fully synced"
    """
    p = stroke_parity(repo, strokes_file)
    pct = p.ratio * 100
    if p.is_synced:
        return f"{p.committed}/{p.total} strokes committed ({pct:.2f}%), fully synced"
    return (
        f"{p.committed}/{p.total} strokes committed ({pct:.2f}%), "
        f"{p.orphan_count} orphan{'s' if p.orphan_count != 1 else ''} pending"
    )


def orphan_strokes(
    repo: Optional[Path] = None,
    strokes_file: str = _DEFAULT_STROKES_FILE,
) -> List[int]:
    """Return sorted list of orphan stroke seq numbers.

    An orphan stroke was written to the JSONL log on disk but is not
    present in the committed (HEAD) version of that log.
    """
    return stroke_parity(repo, strokes_file).orphan_seqs


def parity_grade(
    repo: Optional[Path] = None,
    strokes_file: str = _DEFAULT_STROKES_FILE,
) -> str:
    """Letter grade for the parity state.

    - A : ratio >= 0.99  (at most ~32 orphans in a 3200-stroke repo)
    - B : ratio >= 0.95
    - C : ratio >= 0.90
    - D : ratio >= 0.80
    - F : ratio <  0.80  (serious data loss risk)
    """
    p = stroke_parity(repo, strokes_file)
    if p.ratio >= 0.99:
        return "A"
    if p.ratio >= 0.95:
        return "B"
    if p.ratio >= 0.90:
        return "C"
    if p.ratio >= 0.80:
        return "D"
    return "F"


def kind_parity(
    repo: Optional[Path] = None,
    strokes_file: str = _DEFAULT_STROKES_FILE,
    kind: str = "thought",
) -> Dict[str, int]:
    """Parity breakdown for a single stroke kind.

    Returns a dict with keys ``total``, ``committed``, ``orphan``.
    Returns zeros if the kind is not found.
    """
    p = stroke_parity(repo, strokes_file)
    return p.by_kind.get(kind, {"total": 0, "committed": 0, "orphan": 0})


def parity_trend(
    reports: Sequence[ParityReport],
) -> Dict[str, float]:
    """Compute trend statistics over a sequence of parity snapshots.

    Returns a dict with:

    - ``mean_ratio``  — average parity ratio across all snapshots
    - ``min_ratio``   — worst (lowest) ratio observed
    - ``max_orphans`` — peak orphan count in any single snapshot
    - ``improving``   — True if the last ratio is better than the first

    Returns all-zeros if *reports* is empty.
    """
    if not reports:
        return {"mean_ratio": 0.0, "min_ratio": 0.0, "max_orphans": 0, "improving": False}
    ratios = [r.ratio for r in reports]
    orphans = [r.orphan_count for r in reports]
    return {
        "mean_ratio": sum(ratios) / len(ratios),
        "min_ratio": min(ratios),
        "max_orphans": max(orphans),
        "improving": ratios[-1] >= ratios[0],
    }
