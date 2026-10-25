"""Note index — catalog and search the notes directory.

The notes/ directory has grown past the point where ``ls`` is useful.
Over 130 files spanning visit reports, recovery logs, reflections, and
operational playbooks. ``note_index`` scans the directory, classifies
each file by type, extracts metadata (date, visit number, tags), and
provides search and filter operations.

Usage::

    from iamai.note_index import NoteIndex

    idx = NoteIndex("notes/")
    idx.scan()

    # filter by type
    visits = idx.filter(type="visit")

    # search by keyword
    results = idx.search("reclamation")

    # summary statistics
    print(idx.summary())
    # {'total': 134, 'visits': 98, 'recoveries': 12, 'reflections': 8, ...}

Design notes:

- Classification is filename-based, not content-based, to keep scanning
  fast. A file is a "visit" if its name matches ``caretaker-visit-*``,
  a "recovery" if it contains "recovery" or "reclamation", etc.
- ``scan()`` reads only filenames and first lines (for date extraction).
  Call ``load_content()`` explicitly when you need full text.
- All methods return plain dicts or lists — no custom objects that would
  need serialization for the JSON-based stroke pipeline.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


# filename patterns → note type (checked in order; first match wins).
# More specific patterns must come before broader ones: e.g. "push-race"
# before "recovery" so that push-race-recovery.md is a push_race, not a
# recovery; time-prefix patterns before bare "caretaker-" so that
# dawn-caretaker.md is a time_event, not caretaker_ops.
_PATTERNS = [
    (re.compile(r"caretaker-visit-\d+"), "visit"),
    (re.compile(r"push-race|push.*race"), "push_race"),
    (re.compile(r"recovery|reclamation"), "recovery"),
    (re.compile(r"workbuddy"), "workbuddy"),
    (re.compile(r"guoban"), "guoban"),
    (re.compile(r"dawn-|midnight-|overnight-|afternoon-"), "time_event"),
    (re.compile(r"caretaker-(?!visit)"), "caretaker_ops"),
    (re.compile(r"stroke-\d+"), "stroke_reflection"),
    (re.compile(r"process-"), "process"),
    (re.compile(r"signal-|cadence|rhythm"), "cadence"),
]

# date pattern in filenames (YYYY-MM-DD)
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# visit number pattern
_VISIT_NUM_RE = re.compile(r"caretaker-visit-(\d+)")


@dataclass
class NoteEntry:
    """One note in the index."""
    filename: str
    path: str
    note_type: str
    date: Optional[str] = None          # YYYY-MM-DD or None
    visit_number: Optional[int] = None  # only for visit notes
    size_bytes: int = 0
    first_line: str = ""
    loaded: bool = False
    content: str = ""


class NoteIndex:
    """Scan, classify, and search notes in a directory."""

    def __init__(self, notes_dir: str = "notes"):
        self.notes_dir = notes_dir
        self.entries: List[NoteEntry] = []
        self._scanned = False

    def scan(self) -> int:
        """Scan the notes directory and classify each file.

        Returns the number of files indexed.
        """
        self.entries = []
        notes_path = Path(self.notes_dir)
        if not notes_path.is_dir():
            self._scanned = True
            return 0

        for entry in sorted(notes_path.iterdir()):
            if not entry.is_file():
                continue
            if entry.name.startswith("."):
                continue

            note_type = self._classify(entry.name)
            date = self._extract_date(entry.name)
            visit_num = self._extract_visit_number(entry.name)
            size = entry.stat().st_size

            # read first line for quick preview, skipping YAML frontmatter
            first_line = ""
            try:
                with open(entry, "r", encoding="utf-8", errors="replace") as f:
                    in_frontmatter = False
                    for line in f:
                        stripped = line.strip()
                        if stripped == "---":
                            if not in_frontmatter:
                                in_frontmatter = True
                                continue
                            else:
                                in_frontmatter = False
                                continue
                        if in_frontmatter:
                            continue
                        if stripped:
                            first_line = stripped[:120]
                            break
            except (OSError, UnicodeDecodeError):
                pass

            self.entries.append(NoteEntry(
                filename=entry.name,
                path=str(entry),
                note_type=note_type,
                date=date,
                visit_number=visit_num,
                size_bytes=size,
                first_line=first_line,
            ))

        self._scanned = True
        return len(self.entries)

    def filter(
        self,
        type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        min_size: int = 0,
    ) -> List[NoteEntry]:
        """Return entries matching all given criteria.

        Args:
            type: exact note type match (e.g. "visit", "recovery")
            date_from: inclusive start date "YYYY-MM-DD"
            date_to: inclusive end date "YYYY-MM-DD"
            min_size: minimum file size in bytes
        """
        self._ensure_scanned()
        results = self.entries

        if type is not None:
            results = [e for e in results if e.note_type == type]

        if date_from is not None:
            results = [e for e in results if e.date and e.date >= date_from]

        if date_to is not None:
            results = [e for e in results if e.date and e.date <= date_to]

        if min_size > 0:
            results = [e for e in results if e.size_bytes >= min_size]

        return results

    def search(self, query: str, in_content: bool = False) -> List[NoteEntry]:
        """Search notes by keyword (case-insensitive).

        Args:
            query: search term
            in_content: if True, also search file content (slower;
                        calls load_content on each match candidate)
        """
        self._ensure_scanned()
        q = query.lower()
        results = []

        for entry in self.entries:
            # always check filename and first line
            if q in entry.filename.lower() or q in entry.first_line.lower():
                results.append(entry)
                continue

            if in_content:
                content = self.load_content(entry)
                if q in content.lower():
                    results.append(entry)

        return results

    def load_content(self, entry: NoteEntry) -> str:
        """Load full text content for a note entry."""
        if entry.loaded:
            return entry.content
        try:
            with open(entry.path, "r", encoding="utf-8", errors="replace") as f:
                entry.content = f.read()
        except (OSError, UnicodeDecodeError):
            entry.content = ""
        entry.loaded = True
        return entry.content

    def summary(self) -> Dict[str, int]:
        """Return counts by note type."""
        self._ensure_scanned()
        counts: Dict[str, int] = {}
        for entry in self.entries:
            counts[entry.note_type] = counts.get(entry.note_type, 0) + 1
        counts["total"] = len(self.entries)
        return counts

    def date_range(self) -> Optional[Dict[str, str]]:
        """Return the earliest and latest dates found in filenames."""
        self._ensure_scanned()
        dates = sorted(e.date for e in self.entries if e.date)
        if not dates:
            return None
        return {"earliest": dates[0], "latest": dates[-1]}

    def visit_numbers(self) -> List[int]:
        """Return sorted list of all visit numbers (for gap detection)."""
        self._ensure_scanned()
        nums = sorted(
            e.visit_number for e in self.entries
            if e.visit_number is not None
        )
        return nums

    def missing_visits(self) -> List[int]:
        """Find gaps in the visit number sequence."""
        nums = self.visit_numbers()
        if len(nums) < 2:
            return []
        full_range = set(range(nums[0], nums[-1] + 1))
        present = set(nums)
        return sorted(full_range - present)

    def _ensure_scanned(self) -> None:
        if not self._scanned:
            self.scan()

    @staticmethod
    def _classify(filename: str) -> str:
        for pattern, note_type in _PATTERNS:
            if pattern.search(filename):
                return note_type
        return "other"

    @staticmethod
    def _extract_date(filename: str) -> Optional[str]:
        m = _DATE_RE.search(filename)
        return m.group(1) if m else None

    @staticmethod
    def _extract_visit_number(filename: str) -> Optional[int]:
        m = _VISIT_NUM_RE.search(filename)
        return int(m.group(1)) if m else None
