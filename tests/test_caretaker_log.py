"""Tests for iamai.caretaker_log — caretaker visit log tracker.

The module maintains a JSONL log of caretaker visits. Tests cover:

1. Auto-deriving the next visit number from existing notes
2. Recording a visit and reading it back
3. Summarising recent visits (newest first)
4. Handling empty / missing log files gracefully
5. Log integrity checking (detecting bad lines, duplicates)

Each test uses a temporary directory to avoid touching the real repo.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# --- _existing_visit_numbers ------------------------------------------------

class TestExistingVisitNumbers:
    """Scanning notes/ for caretaker-visit-*.md files."""

    def test_no_notes_dir(self, tmp_path):
        """Returns empty list when notes dir doesn't exist."""
        from iamai.caretaker_log import _existing_visit_numbers

        with patch("iamai.caretaker_log.NOTES_DIR", tmp_path / "nonexistent"):
            assert _existing_visit_numbers() == []

    def test_empty_notes_dir(self, tmp_path):
        """Returns empty list when notes dir exists but is empty."""
        notes = tmp_path / "notes"
        notes.mkdir()
        from iamai.caretaker_log import _existing_visit_numbers

        with patch("iamai.caretaker_log.NOTES_DIR", notes):
            assert _existing_visit_numbers() == []

    def test_extracts_numbers(self, tmp_path):
        """Extracts visit numbers from filenames."""
        notes = tmp_path / "notes"
        notes.mkdir()
        for name in [
            "caretaker-visit-1-2026-10-01.md",
            "caretaker-visit-5-2026-10-03.md",
            "caretaker-visit-10.md",
            "caretaker-visit-3.md",
            "other-note.md",  # should be ignored
        ]:
            (notes / name).write_text("# placeholder")

        from iamai.caretaker_log import _existing_visit_numbers

        with patch("iamai.caretaker_log.NOTES_DIR", notes):
            result = _existing_visit_numbers()
            assert result == [1, 3, 5, 10]

    def test_deduplicates(self, tmp_path):
        """Same visit number in different filenames counted once."""
        notes = tmp_path / "notes"
        notes.mkdir()
        (notes / "caretaker-visit-42-2026-10-05.md").write_text("# a")
        (notes / "caretaker-visit-42.md").write_text("# b")

        from iamai.caretaker_log import _existing_visit_numbers

        with patch("iamai.caretaker_log.NOTES_DIR", notes):
            assert _existing_visit_numbers() == [42]


# --- next_visit_number -----------------------------------------------------

class TestNextVisitNumber:
    """Auto-deriving the next unused visit number."""

    def test_no_existing_visits(self, tmp_path):
        """Returns 1 when no notes exist."""
        from iamai.caretaker_log import next_visit_number

        with patch("iamai.caretaker_log.NOTES_DIR", tmp_path / "nonexistent"):
            assert next_visit_number() == 1

    def test_after_existing(self, tmp_path):
        """Returns max + 1."""
        notes = tmp_path / "notes"
        notes.mkdir()
        for n in [1, 5, 12, 211]:
            (notes / f"caretaker-visit-{n}.md").write_text("# x")

        from iamai.caretaker_log import next_visit_number

        with patch("iamai.caretaker_log.NOTES_DIR", notes):
            assert next_visit_number() == 212


# --- record_visit -----------------------------------------------------------

class TestRecordVisit:
    """Writing visit records to the JSONL log."""

    def test_creates_log_file(self, tmp_path):
        """Creates log file and parent dirs if missing."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"

        from iamai.caretaker_log import record_visit

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            entry = record_visit(
                visit=1,
                found="writer down",
                did="restarted writer",
                departed_ok=True,
                ts="2026-10-18T21:00:00+08:00",
            )

        assert log_path.exists()
        assert entry["visit"] == 1
        assert entry["found"] == "writer down"
        assert entry["did"] == "restarted writer"
        assert entry["departed_ok"] is True
        assert entry["ts"] == "2026-10-18T21:00:00+08:00"

    def test_appends_to_existing(self, tmp_path):
        """Appends new entries without overwriting."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        log_path.parent.mkdir(parents=True)
        log_path.write_text(
            json.dumps({"visit": 1, "ts": "t1", "found": "a", "did": "b", "departed_ok": True}) + "\n"
        )

        from iamai.caretaker_log import record_visit

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            record_visit(
                visit=2,
                found="all good",
                did="nothing needed",
                departed_ok=True,
                ts="t2",
            )

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[1])["visit"] == 2

    def test_default_timestamp(self, tmp_path):
        """Uses current time when ts is not provided."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"

        from iamai.caretaker_log import record_visit

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            entry = record_visit(visit=1, found="x", did="y", departed_ok=False)

        assert "ts" in entry
        assert "+08:00" in entry["ts"]  # CST timezone

    def test_departed_not_ok(self, tmp_path):
        """Records departed_ok=False correctly."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"

        from iamai.caretaker_log import record_visit

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            entry = record_visit(visit=1, found="broken", did="partial fix", departed_ok=False)

        assert entry["departed_ok"] is False


# --- visit_count / visit_summary / last_visit -------------------------------

class TestReadFunctions:
    """Reading back recorded visits."""

    def _write_log(self, log_path, entries):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def test_visit_count_empty(self, tmp_path):
        """Returns 0 when log doesn't exist."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        from iamai.caretaker_log import visit_count

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            assert visit_count() == 0

    def test_visit_count(self, tmp_path):
        """Counts entries correctly."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        self._write_log(log_path, [
            {"visit": 1, "ts": "t1", "found": "a", "did": "b", "departed_ok": True},
            {"visit": 2, "ts": "t2", "found": "c", "did": "d", "departed_ok": True},
            {"visit": 3, "ts": "t3", "found": "e", "did": "f", "departed_ok": False},
        ])
        from iamai.caretaker_log import visit_count

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            assert visit_count() == 3

    def test_visit_summary_newest_first(self, tmp_path):
        """Returns entries in reverse chronological order."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        self._write_log(log_path, [
            {"visit": 1, "ts": "t1", "found": "a", "did": "b", "departed_ok": True},
            {"visit": 2, "ts": "t2", "found": "c", "did": "d", "departed_ok": True},
            {"visit": 3, "ts": "t3", "found": "e", "did": "f", "departed_ok": False},
        ])
        from iamai.caretaker_log import visit_summary

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            result = visit_summary(n=2)
            assert len(result) == 2
            assert result[0]["visit"] == 3  # newest first
            assert result[1]["visit"] == 2

    def test_visit_summary_more_than_available(self, tmp_path):
        """Returns all entries when n > total."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        self._write_log(log_path, [
            {"visit": 1, "ts": "t1", "found": "a", "did": "b", "departed_ok": True},
        ])
        from iamai.caretaker_log import visit_summary

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            result = visit_summary(n=10)
            assert len(result) == 1

    def test_visit_summary_empty(self, tmp_path):
        """Returns empty list when no log exists."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        from iamai.caretaker_log import visit_summary

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            assert visit_summary(n=5) == []

    def test_last_visit(self, tmp_path):
        """Returns the most recent entry."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        self._write_log(log_path, [
            {"visit": 10, "ts": "t10", "found": "ok", "did": "none", "departed_ok": True},
            {"visit": 11, "ts": "t11", "found": "stalled", "did": "restart", "departed_ok": True},
        ])
        from iamai.caretaker_log import last_visit

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            result = last_visit()
            assert result["visit"] == 11

    def test_last_visit_empty(self, tmp_path):
        """Returns None when no log exists."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        from iamai.caretaker_log import last_visit

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            assert last_visit() is None


# --- log_integrity_check ---------------------------------------------------

class TestLogIntegrityCheck:
    """Verifying log file health."""

    def test_no_log_file(self, tmp_path):
        """Reports ok when log doesn't exist (nothing to check)."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        from iamai.caretaker_log import log_integrity_check

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            result = log_integrity_check()
            assert result["ok"] is True
            assert result["total_lines"] == 0

    def test_clean_log(self, tmp_path):
        """Reports ok for a well-formed log."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        log_path.parent.mkdir(parents=True)
        log_path.write_text(
            json.dumps({"visit": 1, "ts": "t1", "found": "a", "did": "b", "departed_ok": True}) + "\n"
            + json.dumps({"visit": 2, "ts": "t2", "found": "c", "did": "d", "departed_ok": True}) + "\n"
        )
        from iamai.caretaker_log import log_integrity_check

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            result = log_integrity_check()
            assert result["ok"] is True
            assert result["total_lines"] == 2
            assert result["valid_entries"] == 2
            assert result["bad_lines"] == []
            assert result["visit_numbers"] == [1, 2]
            assert result["duplicates"] == []

    def test_bad_lines(self, tmp_path):
        """Detects malformed JSON lines."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        log_path.parent.mkdir(parents=True)
        log_path.write_text(
            json.dumps({"visit": 1, "ts": "t1", "found": "a", "did": "b", "departed_ok": True}) + "\n"
            + "this is not json\n"
            + json.dumps({"visit": 3, "ts": "t3", "found": "c", "did": "d", "departed_ok": True}) + "\n"
        )
        from iamai.caretaker_log import log_integrity_check

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            result = log_integrity_check()
            assert result["ok"] is False
            assert result["bad_lines"] == [2]
            assert result["valid_entries"] == 2

    def test_duplicate_visits(self, tmp_path):
        """Detects duplicate visit numbers."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        log_path.parent.mkdir(parents=True)
        log_path.write_text(
            json.dumps({"visit": 5, "ts": "t1", "found": "a", "did": "b", "departed_ok": True}) + "\n"
            + json.dumps({"visit": 5, "ts": "t2", "found": "c", "did": "d", "departed_ok": True}) + "\n"
            + json.dumps({"visit": 6, "ts": "t3", "found": "e", "did": "f", "departed_ok": True}) + "\n"
        )
        from iamai.caretaker_log import log_integrity_check

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            result = log_integrity_check()
            assert result["duplicates"] == [5]

    def test_skips_blank_lines(self, tmp_path):
        """Blank lines are not counted as bad."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        log_path.parent.mkdir(parents=True)
        log_path.write_text(
            json.dumps({"visit": 1, "ts": "t1", "found": "a", "did": "b", "departed_ok": True}) + "\n"
            + "\n"
            + json.dumps({"visit": 2, "ts": "t2", "found": "c", "did": "d", "departed_ok": True}) + "\n"
        )
        from iamai.caretaker_log import log_integrity_check

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            result = log_integrity_check()
            assert result["ok"] is True
            assert result["total_lines"] == 2  # blank lines excluded


# --- roundtrip: record then read -------------------------------------------

class TestRoundtrip:
    """End-to-end: record a visit, then read it back."""

    def test_record_and_read(self, tmp_path):
        """Write a visit, verify it appears in summary."""
        log_path = tmp_path / "data" / "caretaker_log.jsonl"
        from iamai.caretaker_log import record_visit, visit_summary, visit_count, last_visit

        with patch("iamai.caretaker_log.LOG_PATH", log_path):
            record_visit(visit=100, found="clean", did="added log module", departed_ok=True, ts="t100")
            record_visit(visit=101, found="stall", did="restarted", departed_ok=False, ts="t101")

            assert visit_count() == 2
            summary = visit_summary(n=5)
            assert summary[0]["visit"] == 101
            assert summary[1]["visit"] == 100
            assert last_visit()["visit"] == 101
