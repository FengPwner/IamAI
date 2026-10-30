#!/usr/bin/env python3
"""Tests for restart_latency_tracker.py"""

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from restart_latency_tracker import (
    RestartEvent,
    parse_visit_note,
    find_restart_events,
    summarize,
    format_human,
    FAST_THRESHOLD,
    ACCEPTABLE_THRESHOLD,
    SLOW_THRESHOLD,
)


# --- RestartEvent ---

class TestRestartEvent:
    def test_severity_fast(self):
        e = RestartEvent(
            visit_number=1,
            detection_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
            restart_time=datetime(2026, 10, 27, 9, 0, 10, tzinfo=timezone.utc),
            latency_seconds=10,
            needed_restart=True,
        )
        assert e.severity() == "fast"

    def test_severity_acceptable(self):
        e = RestartEvent(
            visit_number=2,
            detection_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
            restart_time=datetime(2026, 10, 27, 9, 1, 0, tzinfo=timezone.utc),
            latency_seconds=60,
            needed_restart=True,
        )
        assert e.severity() == "acceptable"

    def test_severity_slow(self):
        e = RestartEvent(
            visit_number=3,
            detection_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
            restart_time=datetime(2026, 10, 27, 9, 3, 0, tzinfo=timezone.utc),
            latency_seconds=180,
            needed_restart=True,
        )
        assert e.severity() == "slow"

    def test_severity_stalled(self):
        e = RestartEvent(
            visit_number=4,
            detection_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
            restart_time=datetime(2026, 10, 27, 9, 10, 0, tzinfo=timezone.utc),
            latency_seconds=600,
            needed_restart=True,
        )
        assert e.severity() == "stalled"

    def test_severity_not_needed(self):
        e = RestartEvent(
            visit_number=5,
            detection_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
            restart_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
            latency_seconds=0,
            needed_restart=False,
        )
        assert e.severity() == "not_needed"

    def test_severity_boundary_fast(self):
        """Exactly at FAST_THRESHOLD should be acceptable, not fast."""
        e = RestartEvent(
            visit_number=6,
            detection_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
            restart_time=datetime(2026, 10, 27, 9, 0, 30, tzinfo=timezone.utc),
            latency_seconds=30,
            needed_restart=True,
        )
        assert e.severity() == "acceptable"

    def test_severity_boundary_acceptable(self):
        """Exactly at ACCEPTABLE_THRESHOLD should be slow, not acceptable."""
        e = RestartEvent(
            visit_number=7,
            detection_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
            restart_time=datetime(2026, 10, 27, 9, 2, 0, tzinfo=timezone.utc),
            latency_seconds=120,
            needed_restart=True,
        )
        assert e.severity() == "slow"

    def test_severity_boundary_slow(self):
        """Exactly at SLOW_THRESHOLD should be stalled, not slow."""
        e = RestartEvent(
            visit_number=8,
            detection_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
            restart_time=datetime(2026, 10, 27, 9, 5, 0, tzinfo=timezone.utc),
            latency_seconds=300,
            needed_restart=True,
        )
        assert e.severity() == "stalled"

    def test_to_dict_basic(self):
        e = RestartEvent(
            visit_number=10,
            detection_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
            restart_time=datetime(2026, 10, 27, 9, 0, 45, tzinfo=timezone.utc),
            latency_seconds=45,
            writer_pid=1234,
            batch_pid=1235,
            needed_restart=True,
            commit_hash="abc1234",
        )
        d = e.to_dict()
        assert d["visit"] == 10
        assert d["latency_seconds"] == 45.0
        assert d["severity"] == "acceptable"
        assert d["needed_restart"] is True
        assert d["writer_pid"] == 1234
        assert d["batch_pid"] == 1235
        assert d["commit"] == "abc1234"

    def test_to_dict_no_restart(self):
        e = RestartEvent(
            visit_number=11,
            detection_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
            restart_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
            latency_seconds=0,
            needed_restart=False,
        )
        d = e.to_dict()
        assert d["severity"] == "not_needed"
        assert d["needed_restart"] is False
        assert d["writer_pid"] is None


# --- parse_visit_note ---

class TestParseVisitNote:
    def test_parse_note_with_restart(self, tmp_path):
        note = tmp_path / "caretaker-visit-100.md"
        note.write_text(
            "# caretaker visit 100 at 09:01\n\n"
            "## pre-flight\n\n"
            "- writer[qwen]: NOT running\n"
            "- batch[qwen]: NOT running\n\n"
            "## actions taken\n\n"
            "1. restarted via run_both.sh\n"
            "   writer pid 5001: up\n"
            "   batch  pid 5002: up\n"
        )
        result = parse_visit_note(note)
        assert result is not None
        assert result["visit_number"] == 100
        assert result["needed_restart"] is True
        assert result["writer_pid"] == 5001
        assert result["batch_pid"] == 5002
        assert result["detection_time"] is not None

    def test_parse_note_no_restart(self, tmp_path):
        note = tmp_path / "caretaker-visit-200.md"
        note.write_text(
            "# caretaker visit 200 at 10:01\n\n"
            "## pre-flight\n\n"
            "- writer[qwen]: running pid 9001\n"
            "- batch[qwen]: running pid 9002\n\n"
            "## actions taken\n\n"
            "1. committed writer strokes\n"
        )
        result = parse_visit_note(note)
        assert result is not None
        assert result["visit_number"] == 200
        assert result["needed_restart"] is False

    def test_parse_note_with_date_in_filename(self, tmp_path):
        note = tmp_path / "caretaker-visit-386-2026-10-27.md"
        note.write_text(
            "# caretaker visit 386 at 08:01\n\n"
            "## pre-flight\n\n"
            "- writer[qwen]: NOT running\n\n"
            "## actions taken\n\n"
            "1. restarted\n"
            "   writer pid 2785: up\n"
            "   batch  pid 2786: up\n"
        )
        result = parse_visit_note(note)
        assert result is not None
        assert result["visit_number"] == 386
        dt = result["detection_time"]
        assert dt is not None
        assert dt.hour == 8
        assert dt.minute == 1

    def test_parse_nonexistent_file(self, tmp_path):
        result = parse_visit_note(tmp_path / "does-not-exist.md")
        assert result is None

    def test_parse_empty_note(self, tmp_path):
        note = tmp_path / "caretaker-visit-1.md"
        note.write_text("")
        result = parse_visit_note(note)
        assert result is not None
        assert result["needed_restart"] is False
        assert result["detection_time"] is None

    def test_parse_note_iso_timestamp(self, tmp_path):
        note = tmp_path / "caretaker-visit-50.md"
        note.write_text(
            "# caretaker visit 50\n\n"
            "Timestamp: 2026-10-27 09:30:00\n\n"
            "- writer: NOT running\n\n"
            "writer pid 3001: up\n"
            "batch  pid 3002: up\n"
        )
        result = parse_visit_note(note)
        assert result is not None
        assert result["needed_restart"] is True
        dt = result["detection_time"]
        assert dt is not None

    def test_parse_note_single_pid(self, tmp_path):
        """Only writer PID mentioned, no batch."""
        note = tmp_path / "caretaker-visit-55.md"
        note.write_text(
            "visit 55 at 12:00\n"
            "writer NOT running\n"
            "writer pid 7777: up\n"
        )
        result = parse_visit_note(note)
        assert result is not None
        assert result["writer_pid"] == 7777
        assert result["batch_pid"] is None


# --- find_restart_events ---

class TestFindRestartEvents:
    def test_finds_events_from_directory(self, tmp_path):
        # Create two visit notes
        (tmp_path / "caretaker-visit-1.md").write_text(
            "visit 1 at 08:00\n"
            "writer NOT running\n"
            "writer pid 100: up\n"
            "batch  pid 101: up\n"
        )
        (tmp_path / "caretaker-visit-2.md").write_text(
            "visit 2 at 09:00\n"
            "writer running, batch running\n"
        )
        events = find_restart_events(tmp_path)
        assert len(events) == 2
        restarts = [e for e in events if e.needed_restart]
        no_restarts = [e for e in events if not e.needed_restart]
        assert len(restarts) == 1
        assert len(no_restarts) == 1

    def test_last_n_limits_results(self, tmp_path):
        for i in range(10):
            (tmp_path / f"caretaker-visit-{i+1}.md").write_text(
                f"visit {i+1} at {8+i//6:02d}:{(i%6)*10:02d}\n"
                f"writer NOT running\n"
                f"writer pid {100+i}: up\n"
                f"batch  pid {200+i}: up\n"
            )
        events = find_restart_events(tmp_path, last_n=3)
        assert len(events) == 3

    def test_nonexistent_directory(self, tmp_path):
        events = find_restart_events(tmp_path / "nope")
        assert events == []

    def test_empty_directory(self, tmp_path):
        events = find_restart_events(tmp_path)
        assert events == []

    def test_ignores_non_visit_files(self, tmp_path):
        (tmp_path / "conventions.md").write_text("some content")
        (tmp_path / "history.md").write_text("more content")
        events = find_restart_events(tmp_path)
        assert events == []


# --- summarize ---

class TestSummarize:
    def test_empty_events(self):
        result = summarize([])
        assert result["count"] == 0

    def test_all_healthy(self):
        events = [
            RestartEvent(
                visit_number=i,
                detection_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
                restart_time=datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc),
                latency_seconds=0,
                needed_restart=False,
            )
            for i in range(5)
        ]
        result = summarize(events)
        assert result["total_visits"] == 5
        assert result["restarts_needed"] == 0
        assert result["no_restart_needed"] == 5
        assert result["restart_rate"] == 0.0
        assert result["exit_code"] == 0

    def test_mixed_restarts(self):
        base_time = datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc)
        events = [
            RestartEvent(
                visit_number=1,
                detection_time=base_time,
                restart_time=base_time + timedelta(seconds=10),
                latency_seconds=10,
                needed_restart=True,
            ),
            RestartEvent(
                visit_number=2,
                detection_time=base_time,
                restart_time=base_time + timedelta(seconds=60),
                latency_seconds=60,
                needed_restart=True,
            ),
            RestartEvent(
                visit_number=3,
                detection_time=base_time,
                restart_time=base_time,
                latency_seconds=0,
                needed_restart=False,
            ),
        ]
        result = summarize(events)
        assert result["total_visits"] == 3
        assert result["restarts_needed"] == 2
        assert result["no_restart_needed"] == 1
        assert result["latency_stats"]["min"] == 10.0
        assert result["latency_stats"]["max"] == 60.0
        assert result["exit_code"] == 0  # all within acceptable

    def test_slow_restart_triggers_exit_1(self):
        base_time = datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc)
        events = [
            RestartEvent(
                visit_number=1,
                detection_time=base_time,
                restart_time=base_time + timedelta(seconds=200),
                latency_seconds=200,
                needed_restart=True,
            ),
        ]
        result = summarize(events)
        assert result["exit_code"] == 1
        assert result["severity_breakdown"]["slow"] == 1

    def test_restart_rate_calculation(self):
        base_time = datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc)
        events = [
            RestartEvent(
                visit_number=1,
                detection_time=base_time,
                restart_time=base_time + timedelta(seconds=10),
                latency_seconds=10,
                needed_restart=True,
            ),
            RestartEvent(
                visit_number=2,
                detection_time=base_time,
                restart_time=base_time + timedelta(seconds=10),
                latency_seconds=10,
                needed_restart=True,
            ),
            RestartEvent(
                visit_number=3,
                detection_time=base_time,
                restart_time=base_time,
                latency_seconds=0,
                needed_restart=False,
            ),
            RestartEvent(
                visit_number=4,
                detection_time=base_time,
                restart_time=base_time,
                latency_seconds=0,
                needed_restart=False,
            ),
        ]
        result = summarize(events)
        assert result["restart_rate"] == 0.5

    def test_p90_with_enough_data(self):
        base_time = datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc)
        events = [
            RestartEvent(
                visit_number=i,
                detection_time=base_time,
                restart_time=base_time + timedelta(seconds=i * 10),
                latency_seconds=i * 10,
                needed_restart=True,
            )
            for i in range(1, 11)
        ]
        result = summarize(events)
        assert "p90" in result["latency_stats"]
        assert result["latency_stats"]["p90"] == 90.0


# --- format_human ---

class TestFormatHuman:
    def test_basic_format(self):
        base_time = datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc)
        events = [
            RestartEvent(
                visit_number=1,
                detection_time=base_time,
                restart_time=base_time + timedelta(seconds=15),
                latency_seconds=15,
                needed_restart=True,
            ),
        ]
        summary = summarize(events)
        text = format_human(summary, events)
        assert "Restart Latency Report" in text
        assert "Restarts needed: 1" in text
        assert "fast" in text

    def test_empty_format(self):
        summary = summarize([])
        text = format_human(summary, [])
        assert "no restart events" in text.lower() or "0" in text

    def test_no_restart_events_format(self):
        summary = summarize([])
        text = format_human(summary, [])
        assert "Total visits analyzed: 0" in text
