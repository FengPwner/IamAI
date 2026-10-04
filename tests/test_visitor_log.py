"""Tests for iamai.visitor_log — the caretaker visit ledger.

The visitor log is append-only JSONL. Tests cover: entry creation,
serialization round-trip, file append, reading back, and summary stats.
All file operations use tmp_path to avoid touching the real log.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iamai.visitor_log import (
    VisitEntry,
    append_entry,
    read_entries,
    summarize,
)


# --- VisitEntry dataclass ---------------------------------------------------


def test_entry_defaults():
    e = VisitEntry(
        timestamp="2026-10-05T04:00:00Z",
        visitor="qwen",
        writer_status="dead",
        batch_status="dead",
        uncommitted_files=9,
    )
    assert e.actions_taken == []
    assert e.outcome == "ok"
    assert e.note == ""


def test_entry_with_actions():
    e = VisitEntry(
        timestamp="2026-10-05T04:00:00Z",
        visitor="qwen",
        writer_status="dead",
        batch_status="running",
        uncommitted_files=3,
        actions_taken=["catch-up commit", "rebase", "push"],
        outcome="ok",
        note="fourteenth reclamation",
    )
    assert len(e.actions_taken) == 3
    assert e.outcome == "ok"
    assert "fourteenth" in e.note


# --- Serialization round-trip -----------------------------------------------


def test_to_json_and_back():
    e = VisitEntry(
        timestamp="2026-10-05T04:00:00Z",
        visitor="qwen",
        writer_status="running",
        batch_status="running",
        uncommitted_files=0,
        actions_taken=["push"],
        outcome="ok",
        note="clean push",
    )
    line = e.to_json()
    restored = VisitEntry.from_json(line)
    assert restored.timestamp == e.timestamp
    assert restored.visitor == e.visitor
    assert restored.actions_taken == e.actions_taken
    assert restored.note == e.note


def test_to_json_is_single_line():
    e = VisitEntry(
        timestamp="2026-10-05T04:00:00Z",
        visitor="caretaker",
        writer_status="dead",
        batch_status="dead",
        uncommitted_files=5,
    )
    line = e.to_json()
    assert "\n" not in line
    # Verify it's valid JSON
    parsed = json.loads(line)
    assert parsed["visitor"] == "caretaker"


def test_from_json_handles_unicode():
    line = '{"timestamp":"2026-10-05T04:00:00Z","visitor":"guoban","writer_status":"running","batch_status":"running","uncommitted_files":0,"actions_taken":[],"outcome":"ok","note":"夜班记录"}'
    e = VisitEntry.from_json(line)
    assert e.note == "夜班记录"
    assert e.visitor == "guoban"


# --- now() factory -----------------------------------------------------------


def test_now_creates_entry_with_utc_timestamp():
    e = VisitEntry.now(
        visitor="qwen",
        writer_status="dead",
        batch_status="dead",
        uncommitted_files=9,
        actions_taken=["restart", "commit", "push"],
        outcome="ok",
        note="dawn visit",
    )
    assert e.timestamp.endswith("Z")
    assert "T" in e.timestamp
    assert e.visitor == "qwen"
    assert e.actions_taken == ["restart", "commit", "push"]


def test_now_defaults_actions_to_empty_list():
    e = VisitEntry.now(
        visitor="qwen",
        writer_status="running",
        batch_status="running",
        uncommitted_files=0,
    )
    assert e.actions_taken == []
    assert e.outcome == "ok"


# --- File operations ---------------------------------------------------------


def test_append_creates_file(tmp_path):
    log = tmp_path / "visitor_log.jsonl"
    e = VisitEntry.now(visitor="test", writer_status="dead", batch_status="dead", uncommitted_files=1)
    result = append_entry(e, path=log)
    assert result == log
    assert log.exists()
    lines = log.read_text().strip().split("\n")
    assert len(lines) == 1


def test_append_accumulates_entries(tmp_path):
    log = tmp_path / "visitor_log.jsonl"
    for i in range(5):
        e = VisitEntry.now(
            visitor=f"caretaker-{i}",
            writer_status="dead",
            batch_status="dead",
            uncommitted_files=i,
        )
        append_entry(e, path=log)
    lines = log.read_text().strip().split("\n")
    assert len(lines) == 5


def test_read_entries_empty_when_missing(tmp_path):
    log = tmp_path / "nonexistent.jsonl"
    assert read_entries(path=log) == []


def test_read_entries_round_trip(tmp_path):
    log = tmp_path / "visitor_log.jsonl"
    entries_written = []
    for i in range(3):
        e = VisitEntry(
            timestamp=f"2026-10-05T0{i}:00:00Z",
            visitor=f"v{i}",
            writer_status="dead",
            batch_status="dead",
            uncommitted_files=i,
            actions_taken=["restart"],
            outcome="ok",
            note=f"visit {i}",
        )
        entries_written.append(e)
        append_entry(e, path=log)

    entries_read = read_entries(path=log)
    assert len(entries_read) == 3
    for written, read in zip(entries_written, entries_read):
        assert written.timestamp == read.timestamp
        assert written.visitor == read.visitor
        assert written.note == read.note


# --- Summarize ---------------------------------------------------------------


def test_summarize_empty():
    s = summarize([])
    assert s["total"] == 0
    assert s["by_outcome"] == {}
    assert s["last_visitor"] is None


def test_summarize_counts_outcomes(tmp_path):
    entries = [
        VisitEntry("2026-10-05T01:00:00Z", "a", "dead", "dead", 5, outcome="ok"),
        VisitEntry("2026-10-05T02:00:00Z", "b", "dead", "dead", 3, outcome="partial"),
        VisitEntry("2026-10-05T03:00:00Z", "a", "running", "dead", 0, outcome="ok"),
        VisitEntry("2026-10-05T04:00:00Z", "c", "dead", "dead", 9, outcome="failed"),
    ]
    s = summarize(entries)
    assert s["total"] == 4
    assert s["by_outcome"] == {"ok": 2, "partial": 1, "failed": 1}
    assert s["last_visitor"] == "c"
    assert s["last_time"] == "2026-10-05T04:00:00Z"


def test_summarize_single_entry():
    entries = [
        VisitEntry("2026-10-05T04:00:00Z", "qwen", "dead", "dead", 9,
                    actions_taken=["restart", "push"], outcome="ok", note="dawn"),
    ]
    s = summarize(entries)
    assert s["total"] == 1
    assert s["by_outcome"] == {"ok": 1}
    assert s["last_visitor"] == "qwen"
