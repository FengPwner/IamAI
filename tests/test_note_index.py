"""Tests for iamai.note_index — note cataloging and search."""

import os
import tempfile
import shutil
import pytest

from iamai.note_index import NoteIndex, NoteEntry


@pytest.fixture
def notes_dir(tmp_path):
    """Create a synthetic notes directory with representative files."""
    d = tmp_path / "notes"
    d.mkdir()

    files = {
        "caretaker-visit-145-2026-10-16.md": (
            "---\nvisit: 145\ndate: 2026-10-16\n---\n"
            "## caretaker visit 145\n\nwriter was reclaimed.\n"
        ),
        "caretaker-visit-146-2026-10-16.md": (
            "---\nvisit: 146\ndate: 2026-10-16\n---\n"
            "## caretaker visit 146\n\nprocesses healthy.\n"
        ),
        "caretaker-visit-148-2026-10-16.md": (
            "---\nvisit: 148\ndate: 2026-10-16\n---\n"
            "## caretaker visit 148\n\nrepo_pulse module added.\n"
        ),
        "recovery-2026-10-08.md": (
            "## recovery log\n\nprocesses died overnight. "
            "restarted at 06:00.\n"
        ),
        "afternoon-reclamation-2026-10-04.md": (
            "## reclamation event\n\nsandbox reclaimed writer.\n"
        ),
        "push-race-recovery-2026-10-04.md": (
            "## push race\n\nconcurrent push detected.\n"
        ),
        "stroke-400-reflection.md": (
            "# Stroke 400: what four hundred strokes teach you\n\n"
            "four hundred strokes is not a milestone.\n"
        ),
        "workbuddy-log.md": (
            "## workbuddy operational log\n\nworkbuddy joined roster.\n"
        ),
        "conventions.md": (
            "# Things this repo does on purpose\n\n"
            "a repo that only accumulates is a landfill.\n"
        ),
        "caretaker-checklist.md": (
            "# Caretaker Checklist\n\nwhat to do when the house is quiet.\n"
        ),
        "cadence.md": (
            "# cadence notes\n\nwriter cadence is 15 seconds.\n"
        ),
        "dawn-caretaker-2026-10-05.md": (
            "## dawn visit\n\nearly morning caretaker arrived.\n"
        ),
    }

    for name, content in files.items():
        (d / name).write_text(content, encoding="utf-8")

    return str(d)


@pytest.fixture
def empty_dir(tmp_path):
    d = tmp_path / "empty_notes"
    d.mkdir()
    return str(d)


@pytest.fixture
def index(notes_dir):
    idx = NoteIndex(notes_dir)
    idx.scan()
    return idx


# --- scan ---

class TestScan:
    def test_scan_counts_files(self, index):
        assert len(index.entries) == 12

    def test_scan_returns_count(self, notes_dir):
        idx = NoteIndex(notes_dir)
        count = idx.scan()
        assert count == 12

    def test_scan_empty_directory(self, empty_dir):
        idx = NoteIndex(empty_dir)
        count = idx.scan()
        assert count == 0
        assert idx.entries == []

    def test_scan_nonexistent_directory(self, tmp_path):
        idx = NoteIndex(str(tmp_path / "nope"))
        count = idx.scan()
        assert count == 0

    def test_scan_skips_hidden_files(self, notes_dir):
        # create a hidden file
        hidden = os.path.join(notes_dir, ".hidden_note.md")
        with open(hidden, "w") as f:
            f.write("hidden")
        idx = NoteIndex(notes_dir)
        idx.scan()
        assert all(not e.filename.startswith(".") for e in idx.entries)

    def test_scan_populates_metadata(self, index):
        entry = next(e for e in index.entries if "visit-145" in e.filename)
        assert entry.date == "2026-10-16"
        assert entry.visit_number == 145
        assert entry.note_type == "visit"
        assert entry.size_bytes > 0

    def test_first_line_extracted(self, index):
        entry = next(e for e in index.entries if "conventions" in e.filename)
        assert "accumulates" in entry.first_line or "Things" in entry.first_line

    def test_entries_sorted(self, index):
        filenames = [e.filename for e in index.entries]
        assert filenames == sorted(filenames)


# --- classification ---

class TestClassify:
    def test_visit_notes(self, index):
        visits = [e for e in index.entries if e.note_type == "visit"]
        assert len(visits) == 3
        assert all(e.visit_number is not None for e in visits)

    def test_recovery_notes(self, index):
        recoveries = [e for e in index.entries if e.note_type == "recovery"]
        # recovery-2026-10-08.md and afternoon-reclamation-2026-10-04.md
        assert len(recoveries) == 2

    def test_push_race_notes(self, index):
        races = [e for e in index.entries if e.note_type == "push_race"]
        assert len(races) == 1

    def test_stroke_reflection(self, index):
        reflections = [e for e in index.entries if e.note_type == "stroke_reflection"]
        assert len(reflections) == 1

    def test_workbuddy(self, index):
        wb = [e for e in index.entries if e.note_type == "workbuddy"]
        assert len(wb) == 1

    def test_caretaker_ops(self, index):
        ops = [e for e in index.entries if e.note_type == "caretaker_ops"]
        assert len(ops) == 1  # caretaker-checklist.md

    def test_cadence(self, index):
        cad = [e for e in index.entries if e.note_type == "cadence"]
        assert len(cad) == 1  # cadence.md

    def test_time_event(self, index):
        te = [e for e in index.entries if e.note_type == "time_event"]
        assert len(te) == 1  # dawn-caretaker-2026-10-05.md

    def test_other(self, index):
        other = [e for e in index.entries if e.note_type == "other"]
        assert len(other) == 1  # conventions.md

    def test_classify_static(self):
        assert NoteIndex._classify("caretaker-visit-99-2026-10-09.md") == "visit"
        assert NoteIndex._classify("push-race-sync.md") == "push_race"
        assert NoteIndex._classify("random-note.md") == "other"


# --- date extraction ---

class TestDateExtraction:
    def test_extract_date(self):
        assert NoteIndex._extract_date("visit-145-2026-10-16.md") == "2026-10-16"
        assert NoteIndex._extract_date("recovery-2026-10-08.md") == "2026-10-08"

    def test_no_date(self):
        assert NoteIndex._extract_date("conventions.md") is None
        assert NoteIndex._extract_date("workbuddy-log.md") is None

    def test_visit_number(self):
        assert NoteIndex._extract_visit_number("caretaker-visit-145-2026-10-16.md") == 145
        assert NoteIndex._extract_visit_number("caretaker-visit-1-2026-10-01.md") == 1

    def test_no_visit_number(self):
        assert NoteIndex._extract_visit_number("conventions.md") is None
        assert NoteIndex._extract_visit_number("recovery-2026-10-08.md") is None


# --- filter ---

class TestFilter:
    def test_filter_by_type(self, index):
        visits = index.filter(type="visit")
        assert len(visits) == 3
        assert all(e.note_type == "visit" for e in visits)

    def test_filter_by_date_from(self, index):
        results = index.filter(date_from="2026-10-08")
        dates = [e.date for e in results if e.date]
        assert all(d >= "2026-10-08" for d in dates)

    def test_filter_by_date_to(self, index):
        results = index.filter(date_to="2026-10-08")
        dates = [e.date for e in results if e.date]
        assert all(d <= "2026-10-08" for d in dates)

    def test_filter_by_date_range(self, index):
        results = index.filter(date_from="2026-10-05", date_to="2026-10-08")
        dates = [e.date for e in results if e.date]
        assert all("2026-10-05" <= d <= "2026-10-08" for d in dates)

    def test_filter_by_min_size(self, index):
        results = index.filter(min_size=100)
        assert all(e.size_bytes >= 100 for e in results)

    def test_filter_combined(self, index):
        results = index.filter(type="visit", date_from="2026-10-16")
        assert len(results) == 3  # all 3 visits are on 10-16

    def test_filter_no_match(self, index):
        results = index.filter(type="nonexistent_type")
        assert results == []

    def test_filter_auto_scans(self, notes_dir):
        idx = NoteIndex(notes_dir)
        results = idx.filter(type="visit")
        assert len(results) == 3  # auto-scan triggered


# --- search ---

class TestSearch:
    def test_search_filename(self, index):
        results = index.search("reclamation")
        filenames = [e.filename for e in results]
        assert any("reclamation" in f for f in filenames)

    def test_search_first_line(self, index):
        # conventions.md first line is "# Things this repo does on purpose"
        results = index.search("Things this repo")
        assert len(results) >= 1
        assert any("conventions" in e.filename for e in results)

    def test_search_case_insensitive(self, index):
        lower = index.search("caretaker")
        upper = index.search("CARETAKER")
        assert len(lower) == len(upper)

    def test_search_no_results(self, index):
        results = index.search("xyznonexistentterm123")
        assert results == []

    def test_search_in_content(self, index):
        results = index.search("accumulates", in_content=True)
        assert len(results) >= 1

    def test_search_in_content_finds_body_text(self, index):
        # "restarted at 06:00" is in recovery note body, not filename/first line
        results = index.search("06:00", in_content=True)
        assert len(results) == 1
        assert "recovery" in results[0].filename


# --- summary ---

class TestSummary:
    def test_summary_total(self, index):
        s = index.summary()
        assert s["total"] == 12

    def test_summary_has_visit_count(self, index):
        s = index.summary()
        assert s.get("visit", 0) == 3

    def test_summary_has_recovery_count(self, index):
        s = index.summary()
        assert s.get("recovery", 0) == 2

    def test_summary_auto_scans(self, notes_dir):
        idx = NoteIndex(notes_dir)
        s = idx.summary()
        assert s["total"] == 12


# --- date_range ---

class TestDateRange:
    def test_date_range(self, index):
        dr = index.date_range()
        assert dr is not None
        assert dr["earliest"] == "2026-10-04"
        assert dr["latest"] == "2026-10-16"

    def test_date_range_empty(self, empty_dir):
        idx = NoteIndex(empty_dir)
        idx.scan()
        assert idx.date_range() is None


# --- visit_numbers and missing_visits ---

class TestVisitTracking:
    def test_visit_numbers_sorted(self, index):
        nums = index.visit_numbers()
        assert nums == [145, 146, 148]

    def test_missing_visits(self, index):
        missing = index.missing_visits()
        assert 147 in missing

    def test_missing_visits_empty_when_consecutive(self, tmp_path):
        d = tmp_path / "notes"
        d.mkdir()
        (d / "caretaker-visit-1-2026-10-01.md").write_text("# v1")
        (d / "caretaker-visit-2-2026-10-02.md").write_text("# v2")
        (d / "caretaker-visit-3-2026-10-03.md").write_text("# v3")
        idx = NoteIndex(str(d))
        idx.scan()
        assert idx.missing_visits() == []

    def test_missing_visits_single_entry(self, tmp_path):
        d = tmp_path / "notes"
        d.mkdir()
        (d / "caretaker-visit-5-2026-10-05.md").write_text("# v5")
        idx = NoteIndex(str(d))
        idx.scan()
        assert idx.missing_visits() == []

    def test_visit_numbers_empty(self, empty_dir):
        idx = NoteIndex(empty_dir)
        idx.scan()
        assert idx.visit_numbers() == []


# --- load_content ---

class TestLoadContent:
    def test_load_content(self, index):
        entry = next(e for e in index.entries if "conventions" in e.filename)
        content = index.load_content(entry)
        assert "accumulates" in content
        assert entry.loaded is True

    def test_load_content_cached(self, index):
        entry = next(e for e in index.entries if "conventions" in e.filename)
        content1 = index.load_content(entry)
        content2 = index.load_content(entry)
        assert content1 == content2

    def test_load_content_nonexistent_file(self, tmp_path):
        d = tmp_path / "notes"
        d.mkdir()
        idx = NoteIndex(str(d))
        # manually create an entry pointing to nonexistent file
        entry = NoteEntry(
            filename="ghost.md",
            path=str(d / "ghost.md"),
            note_type="other",
        )
        content = idx.load_content(entry)
        assert content == ""


# --- edge cases ---

class TestEdgeCases:
    def test_repeated_scan(self, notes_dir):
        idx = NoteIndex(notes_dir)
        idx.scan()
        assert len(idx.entries) == 12
        idx.scan()  # second scan should reset
        assert len(idx.entries) == 12

    def test_filter_before_scan_triggers_scan(self, notes_dir):
        idx = NoteIndex(notes_dir)
        assert idx._scanned is False
        results = idx.filter(type="visit")
        assert idx._scanned is True
        assert len(results) == 3

    def test_summary_before_scan_triggers_scan(self, notes_dir):
        idx = NoteIndex(notes_dir)
        s = idx.summary()
        assert s["total"] == 12

    def test_unicode_filename(self, tmp_path):
        d = tmp_path / "notes"
        d.mkdir()
        (d / "note-日本語-2026-10-16.md").write_text("# test\n")
        idx = NoteIndex(str(d))
        idx.scan()
        assert len(idx.entries) == 1

    def test_empty_file(self, tmp_path):
        d = tmp_path / "notes"
        d.mkdir()
        (d / "empty-note.md").write_text("")
        idx = NoteIndex(str(d))
        idx.scan()
        assert len(idx.entries) == 1
        assert idx.entries[0].first_line == ""

    def test_binary_content_handled(self, tmp_path):
        d = tmp_path / "notes"
        d.mkdir()
        path = d / "binary-note.md"
        path.write_bytes(b"\xff\xfe invalid utf-8 \x00\x01")
        idx = NoteIndex(str(d))
        idx.scan()
        assert len(idx.entries) == 1
