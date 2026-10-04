"""Visitor log: who came, when, what they found, what they left.

Every caretaker visit is a row in a ledger. Not for surveillance — for
continuity. When the next caretaker wakes up and reads the last entry,
they should know: someone was here, the pattern holds, here is what
changed since the last visit.

The log is append-only (like everything in this repo). Each entry records:

    - timestamp (UTC ISO 8601)
    - visitor id (who did the caretaking)
    - writer status on arrival (running / dead / paused)
    - batch status on arrival (running / dead)
    - uncommitted files on arrival (count)
    - actions taken (list of strings)
    - outcome (ok / partial / failed)
    - note (optional free text)

The log lives at ``data/visitor_log.jsonl``. One JSON object per line.
Reading the whole file gives you the full history of caretaker visits,
which is useful for answering questions like "how often do the processes
die?" and "what time of day do most reclamation events happen?"

This module does not import git, subprocess, or anything heavy. It is
a pure data module: write entries, read entries, summarize. The caretaker
calls it; it does not call the caretaker.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent
LOG_PATH = REPO / "data" / "visitor_log.jsonl"


@dataclass
class VisitEntry:
    """One caretaker visit, recorded as a single log line."""

    timestamp: str
    visitor: str
    writer_status: str          # "running" | "dead" | "paused"
    batch_status: str           # "running" | "dead"
    uncommitted_files: int
    actions_taken: list[str] = field(default_factory=list)
    outcome: str = "ok"         # "ok" | "partial" | "failed"
    note: str = ""

    def to_json(self) -> str:
        """Serialize to a single JSON line (no trailing newline)."""
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> "VisitEntry":
        """Deserialize from a JSON line."""
        return cls(**json.loads(line))

    @classmethod
    def now(
        cls,
        visitor: str,
        writer_status: str,
        batch_status: str,
        uncommitted_files: int,
        actions_taken: Optional[list[str]] = None,
        outcome: str = "ok",
        note: str = "",
    ) -> "VisitEntry":
        """Create an entry timestamped at the current UTC moment."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return cls(
            timestamp=ts,
            visitor=visitor,
            writer_status=writer_status,
            batch_status=batch_status,
            uncommitted_files=uncommitted_files,
            actions_taken=actions_taken or [],
            outcome=outcome,
            note=note,
        )


def append_entry(entry: VisitEntry, path: Optional[Path] = None) -> Path:
    """Append one entry to the visitor log. Creates the file if needed."""
    target = path or LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as f:
        f.write(entry.to_json() + "\n")
    return target


def read_entries(path: Optional[Path] = None) -> list[VisitEntry]:
    """Read all entries from the visitor log. Empty file or missing → []."""
    target = path or LOG_PATH
    if not target.exists():
        return []
    entries = []
    with open(target, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(VisitEntry.from_json(line))
    return entries


def summarize(entries: list[VisitEntry]) -> dict:
    """Produce a summary dict from a list of visit entries.

    Returns counts by outcome, total visits, and the most recent visitor.
    Useful for heartbeat reports and caretaker handoff notes.
    """
    if not entries:
        return {"total": 0, "by_outcome": {}, "last_visitor": None, "last_time": None}

    by_outcome: dict[str, int] = {}
    for e in entries:
        by_outcome[e.outcome] = by_outcome.get(e.outcome, 0) + 1

    return {
        "total": len(entries),
        "by_outcome": by_outcome,
        "last_visitor": entries[-1].visitor,
        "last_time": entries[-1].timestamp,
    }
