"""Caretaker yield — measure what each caretaker visit actually accomplished.

The caretaker verdict tells you *whether* the system needs help; the visit
interval tells you *when* visits happen.  This module fills the gap: what
did the visit *do*?

Each visit is classified into one of five yield types:

==========  ============================================================
type        meaning
==========  ============================================================
``clean``   processes alive, tree clean, nothing to do — best outcome
``recovery`` backlog committed but no new content produced
``intervention`` processes restarted (with or without backlog commit)
``productive`` new content, features, or tests written and committed
``compound`` multiple distinct actions (restart + new content + push)
==========  ============================================================

A visit record is a simple dataclass::

    VisitRecord(
        visit_id=243,
        processes_alive=True,
        backlog_committed=False,
        new_content_written=True,
        push_succeeded=True,
        strokes_lost=0,
    )

The classifier uses a priority order: compound > productive > intervention
> recovery > clean.  A visit that restarted processes *and* wrote new
content is ``compound``, not ``intervention``.

Public API:

- ``classify_visit(record)`` → yield type string
- ``yield_score(yield_type)`` → numeric 0-4 for aggregation
- ``VisitLedger`` — accumulate records, compute rolling statistics
- ``yield_report(ledger)`` → summary dict for caretaker briefings

All logic is pure; no file I/O, no subprocess, no git dependency.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional

__all__ = [
    "VisitRecord",
    "classify_visit",
    "yield_score",
    "yield_label",
    "VisitLedger",
    "yield_report",
]

# ── yield type constants ──────────────────────────────────────────────

YIELD_CLEAN = "clean"
YIELD_RECOVERY = "recovery"
YIELD_INTERVENTION = "intervention"
YIELD_PRODUCTIVE = "productive"
YIELD_COMPOUND = "compound"

_YIELD_ORDER = [YIELD_CLEAN, YIELD_RECOVERY, YIELD_INTERVENTION,
                YIELD_PRODUCTIVE, YIELD_COMPOUND]

_YIELD_SCORES = {
    YIELD_CLEAN: 4,        # best: nothing needed
    YIELD_RECOVERY: 2,     # caught up but no new work
    YIELD_INTERVENTION: 1, # had to fix something
    YIELD_PRODUCTIVE: 3,   # added value
    YIELD_COMPOUND: 3,     # fixed + added value (net positive)
}

_YIELD_LABELS = {
    YIELD_CLEAN: "no action needed",
    YIELD_RECOVERY: "backlog committed, no new content",
    YIELD_INTERVENTION: "process restart or recovery required",
    YIELD_PRODUCTIVE: "new content or features written",
    YIELD_COMPOUND: "recovery + new content in one visit",
}


# ── visit record ──────────────────────────────────────────────────────

@dataclass
class VisitRecord:
    """One caretaker visit's observable outcomes."""

    visit_id: int
    processes_alive: bool = True
    backlog_committed: bool = False
    new_content_written: bool = False
    push_succeeded: bool = True
    strokes_lost: int = 0
    # optional metadata
    files_committed: int = 0
    new_tests_added: int = 0
    notes_written: int = 0

    def action_count(self) -> int:
        """How many distinct action categories occurred."""
        count = 0
        if not self.processes_alive:
            count += 1  # restart was needed
        if self.backlog_committed:
            count += 1
        if self.new_content_written:
            count += 1
        return count


# ── classification ────────────────────────────────────────────────────

def classify_visit(record: VisitRecord) -> str:
    """Classify a visit into one of the five yield types.

    Priority: compound > productive > intervention > recovery > clean.
    """
    needs_restart = not record.processes_alive
    has_backlog = record.backlog_committed
    has_content = record.new_content_written

    # compound: multiple distinct actions
    action_types = sum([needs_restart, has_backlog, has_content])
    if action_types >= 2 and (needs_restart or has_backlog) and has_content:
        return YIELD_COMPOUND

    if has_content:
        return YIELD_PRODUCTIVE
    if needs_restart:
        return YIELD_INTERVENTION
    if has_backlog:
        return YIELD_RECOVERY
    return YIELD_CLEAN


def yield_score(yield_type: str) -> int:
    """Numeric score for a yield type (0-4, higher is better)."""
    return _YIELD_SCORES.get(yield_type, 0)


def yield_label(yield_type: str) -> str:
    """Human-readable description of a yield type."""
    return _YIELD_LABELS.get(yield_type, "unknown")


# ── ledger ────────────────────────────────────────────────────────────

class VisitLedger:
    """Accumulate visit records and compute rolling statistics."""

    def __init__(self) -> None:
        self._records: List[VisitRecord] = []

    def add(self, record: VisitRecord) -> None:
        """Append a visit record (must have increasing visit_id)."""
        if self._records and record.visit_id <= self._records[-1].visit_id:
            raise ValueError(
                f"visit_id {record.visit_id} must be > "
                f"{self._records[-1].visit_id}"
            )
        self._records.append(record)

    @property
    def count(self) -> int:
        return len(self._records)

    def type_counts(self) -> Dict[str, int]:
        """Count visits by yield type."""
        counts: Dict[str, int] = {t: 0 for t in _YIELD_ORDER}
        for r in self._records:
            t = classify_visit(r)
            counts[t] = counts.get(t, 0) + 1
        return counts

    def mean_score(self) -> float:
        """Mean yield score across all visits (0-4)."""
        if not self._records:
            return 0.0
        scores = [yield_score(classify_visit(r)) for r in self._records]
        return float(statistics.mean(scores))

    def clean_rate(self) -> float:
        """Fraction of visits that were clean (no action needed)."""
        if not self._records:
            return 0.0
        clean = sum(1 for r in self._records if classify_visit(r) == YIELD_CLEAN)
        return clean / len(self._records)

    def total_strokes_lost(self) -> int:
        """Sum of strokes_lost across all visits."""
        return sum(r.strokes_lost for r in self._records)

    def total_files_committed(self) -> int:
        """Sum of files_committed across all visits."""
        return sum(r.files_committed for r in self._records)

    def recent(self, n: int = 10) -> List[VisitRecord]:
        """Last n visit records."""
        return self._records[-n:]

    def recent_types(self, n: int = 10) -> List[str]:
        """Yield types for the last n visits."""
        return [classify_visit(r) for r in self.recent(n)]


# ── reporting ─────────────────────────────────────────────────────────

def yield_report(ledger: VisitLedger) -> Dict:
    """Produce a summary dict suitable for caretaker briefings."""
    if ledger.count == 0:
        return {"total_visits": 0, "mean_score": 0.0, "clean_rate": 0.0}

    type_counts = ledger.type_counts()
    dominant = max(type_counts, key=lambda k: type_counts[k])
    recent_types = ledger.recent_types(5)

    return {
        "total_visits": ledger.count,
        "mean_score": round(ledger.mean_score(), 2),
        "clean_rate": round(ledger.clean_rate(), 3),
        "total_strokes_lost": ledger.total_strokes_lost(),
        "total_files_committed": ledger.total_files_committed(),
        "type_counts": type_counts,
        "dominant_type": dominant,
        "recent_5": recent_types,
    }
