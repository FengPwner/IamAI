"""stroke_orphan — detect strokes written but never committed.

The writer appends to ``data/strokes.jsonl`` every 15 seconds.
The batch committer commits every 600 seconds.  Between those two
timers there is always a window of *uncommitted strokes* — work that
exists on disk but has not yet been captured in git history.

Most of the time this is fine: the committer catches up within
minutes.  But if the writer process dies **and** the committer has
not yet run, those strokes are *orphaned*.  They sit in the working
tree, invisible to git, and the next ``git checkout`` or hard reset
will destroy them.

This module answers two questions:

1. **How many strokes are orphans right now?**  (strokes in the
   working copy that don't appear in the last committed version)
2. **How old is the oldest orphan?**  (the longer an orphan lives,
   the more likely it will be lost to an accident)

Severity grades:

========  ============================================================
grade     meaning
========  ============================================================
CLEAN     0 orphans — everything written has been committed
FRESH     1–10 orphans, oldest < 120 s — normal committer lag
WARM      orphans exist but oldest < 600 s — within one commit cycle
STALE     oldest orphan ≥ 600 s — committer may have missed a beat
AT_RISK   oldest orphan ≥ 1800 s — half an hour without capture
========  ============================================================

Usage::

    from iamai.stroke_orphan import detect_orphans

    result = detect_orphans(
        working_strokes=[...],   # list of dicts from working copy
        committed_strokes=[...], # list of dicts from HEAD version
    )
    print(result.orphan_count)   # 4
    print(result.oldest_age_s)   # 237.5
    print(result.severity)       # 'WARM'
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Severity thresholds (seconds)
# ---------------------------------------------------------------------------

_THRESHOLDS = {
    "CLEAN": 0,
    "FRESH": 120,
    "WARM": 600,
    "STALE": 600,
    "AT_RISK": 1800,
}


def _classify_severity(orphan_count: int, oldest_age_s: float) -> str:
    """Return severity grade based on orphan count and age."""
    if orphan_count == 0:
        return "CLEAN"
    if oldest_age_s < _THRESHOLDS["FRESH"]:
        return "FRESH"
    if oldest_age_s < _THRESHOLDS["WARM"]:
        return "WARM"
    if oldest_age_s < _THRESHOLDS["AT_RISK"]:
        return "STALE"
    return "AT_RISK"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OrphanReport:
    """Snapshot of orphan state at a point in time."""

    orphan_count: int
    orphan_seqs: List[int]
    oldest_age_s: float
    newest_age_s: float
    severity: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "orphan_count": self.orphan_count,
            "orphan_seqs": self.orphan_seqs,
            "oldest_age_s": round(self.oldest_age_s, 1),
            "newest_age_s": round(self.newest_age_s, 1),
            "severity": self.severity,
        }


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------

def detect_orphans(
    working_strokes: Sequence[Dict[str, Any]],
    committed_strokes: Sequence[Dict[str, Any]],
    now: Optional[float] = None,
) -> OrphanReport:
    """Compare working-copy strokes against committed strokes.

    Parameters
    ----------
    working_strokes : sequence of stroke dicts
        Each dict must have at least ``seq`` (int) and ``at`` (ISO-8601
        string).  These come from the current ``data/strokes.jsonl``.
    committed_strokes : sequence of stroke dicts
        Same shape, but from the last committed version of the file
        (e.g. ``git show HEAD:data/strokes.jsonl``).
    now : float, optional
        Reference time as a Unix epoch.  Defaults to ``time.time()``.

    Returns
    -------
    OrphanReport
    """
    if now is None:
        now = time.time()

    committed_seqs = {s["seq"] for s in committed_strokes}
    orphans = [s for s in working_strokes if s["seq"] not in committed_seqs]

    if not orphans:
        return OrphanReport(
            orphan_count=0,
            orphan_seqs=[],
            oldest_age_s=0.0,
            newest_age_s=0.0,
            severity="CLEAN",
        )

    ages = []
    for s in orphans:
        from datetime import datetime, timezone

        ts = s["at"]
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        epoch = dt.replace(tzinfo=timezone.utc).timestamp()
        ages.append(now - epoch)

    oldest = max(ages)
    newest = min(ages)
    seqs = [s["seq"] for s in orphans]

    return OrphanReport(
        orphan_count=len(orphans),
        orphan_seqs=seqs,
        oldest_age_s=oldest,
        newest_age_s=newest,
        severity=_classify_severity(len(orphans), oldest),
    )


# ---------------------------------------------------------------------------
# Convenience: load from files
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load a JSONL file, skipping blank lines."""
    strokes = []
    if not path.exists():
        return strokes
    text = path.read_text(encoding="utf-8")
    for line in text.strip().splitlines():
        line = line.strip()
        if line:
            strokes.append(json.loads(line))
    return strokes


def detect_orphans_from_files(
    working_path: str | Path = "data/strokes.jsonl",
    committed_path: str | Path = "/tmp/strokes_committed.jsonl",
    now: Optional[float] = None,
) -> OrphanReport:
    """Convenience wrapper that reads from file paths.

    ``committed_path`` should be a dump of the HEAD version, e.g.::

        git show HEAD:data/strokes.jsonl > /tmp/strokes_committed.jsonl
    """
    working = _load_jsonl(Path(working_path))
    committed = _load_jsonl(Path(committed_path))
    return detect_orphans(working, committed, now=now)
