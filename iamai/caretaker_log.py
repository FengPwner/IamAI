"""Caretaker visit log — structured record of every caretaker intervention.

Caretaker visits produce markdown notes (``notes/caretaker-visit-*.md``)
but there is no machine-readable index.  A caretaker who wants to answer
"what happened in the last 20 visits?" has to glob and parse 20 files.

This module maintains a compact **JSON-lines log** at
``data/caretaker_log.jsonl`` with one record per visit:

.. code-block:: json

    {"visit": 212, "ts": "2026-10-18T21:01:00+08:00",
     "found": "writer down, batch down, 9 uncommitted",
     "did": "restarted both, committed backlog, added caretaker_log module",
     "departed_ok": true}

Design choices:

- Append-only JSONL, same contract as ``data/strokes.jsonl``.
- No external dependencies — just ``json`` and ``pathlib``.
- Visit number is **auto-derived** from existing notes at recording time,
  so callers never have to pass a number (and can't get it wrong).
- ``visit_summary(n=10)`` returns the last *n* entries as a list of dicts,
  newest first, for dashboards or caretaker handoff briefings.
- ``visit_count()`` returns the total number of recorded visits.

Usage::

    from iamai.caretaker_log import record_visit, visit_summary, next_visit_number

    num = next_visit_number()          # e.g. 212
    record_visit(
        visit=num,
        found="writer stalled, 4 files pending",
        did="restarted writer, committed backlog",
        departed_ok=True,
    )
    recent = visit_summary(n=5)        # last 5 visits, newest first
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO = Path(__file__).resolve().parent.parent
NOTES_DIR = REPO / "notes"
LOG_PATH = REPO / "data" / "caretaker_log.jsonl"

_VISIT_RE = re.compile(r"caretaker-visit-(\d+)(?:-\d{4}-\d{2}-\d{2})?\.md$")
_TZ_CST = timezone(timedelta(hours=8))


def _existing_visit_numbers() -> List[int]:
    """Scan ``notes/`` for caretaker-visit-*.md and return sorted visit numbers."""
    if not NOTES_DIR.is_dir():
        return []
    nums: list[int] = []
    for p in NOTES_DIR.iterdir():
        m = _VISIT_RE.match(p.name)
        if m:
            nums.append(int(m.group(1)))
    return sorted(set(nums))


def next_visit_number() -> int:
    """Return the next unused visit number (max existing + 1).

    If no visit notes exist, returns 1.
    """
    existing = _existing_visit_numbers()
    if not existing:
        return 1
    return existing[-1] + 1


def _read_log() -> List[Dict[str, Any]]:
    """Read all entries from the JSONL log file."""
    if not LOG_PATH.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def record_visit(
    visit: int,
    found: str,
    did: str,
    departed_ok: bool,
    ts: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a visit record to the log and return it.

    Parameters
    ----------
    visit : int
        Visit number (use ``next_visit_number()`` to auto-derive).
    found : str
        What the caretaker found on arrival.
    did : str
        What the caretaker did during the visit.
    departed_ok : bool
        Whether everything was healthy at departure.
    ts : str, optional
        ISO-8601 timestamp. Defaults to now (CST).

    Returns
    -------
    dict
        The recorded entry.
    """
    if ts is None:
        ts = datetime.now(_TZ_CST).isoformat(timespec="seconds")

    entry: Dict[str, Any] = {
        "visit": visit,
        "ts": ts,
        "found": found,
        "did": did,
        "departed_ok": departed_ok,
    }

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def visit_count() -> int:
    """Return the number of visits recorded in the log."""
    return len(_read_log())


def visit_summary(n: int = 10) -> List[Dict[str, Any]]:
    """Return the last *n* log entries, newest first.

    Returns fewer than *n* if the log has fewer entries.
    Returns an empty list if the log does not exist.
    """
    entries = _read_log()
    return entries[-n:][::-1]


def last_visit() -> Optional[Dict[str, Any]]:
    """Return the most recent log entry, or None if log is empty."""
    entries = _read_log()
    return entries[-1] if entries else None


def log_integrity_check() -> Dict[str, Any]:
    """Verify the log file is well-formed.

    Returns a dict with:
    - ``ok``: bool — all lines parse as valid JSON
    - ``total_lines``: int — non-empty lines in the file
    - ``valid_entries``: int — lines that parsed successfully
    - ``bad_lines``: list[int] — 1-indexed line numbers that failed to parse
    - ``visit_numbers``: list[int] — sorted visit numbers found in valid entries
    - ``duplicates``: list[int] — visit numbers that appear more than once
    """
    if not LOG_PATH.exists():
        return {
            "ok": True,
            "total_lines": 0,
            "valid_entries": 0,
            "bad_lines": [],
            "visit_numbers": [],
            "duplicates": [],
        }

    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    non_empty = [l for l in lines if l.strip()]
    valid: list[dict[str, Any]] = []
    bad: list[int] = []

    for i, line in enumerate(non_empty, 1):
        try:
            valid.append(json.loads(line.strip()))
        except json.JSONDecodeError:
            bad.append(i)

    visit_nums: list[int] = []
    for e in valid:
        v = e.get("visit")
        if isinstance(v, int):
            visit_nums.append(v)

    visit_nums_sorted = sorted(visit_nums)
    seen: dict[int, int] = {}
    for v in visit_nums:
        seen[v] = seen.get(v, 0) + 1
    dupes = sorted(v for v, c in seen.items() if c > 1)

    return {
        "ok": len(bad) == 0,
        "total_lines": len(non_empty),
        "valid_entries": len(valid),
        "bad_lines": bad,
        "visit_numbers": visit_nums_sorted,
        "duplicates": dupes,
    }
