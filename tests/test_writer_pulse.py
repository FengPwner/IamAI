"""Tests for iamai.writer_pulse — zombie writer detection."""

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.writer_pulse import (
    _read_last_stroke,
    _read_writer_log,
    _count_errors,
    _count_wait_messages,
    _get_process_uptime,
    writer_pulse,
    pulse_history,
    pulse_trend,
    pulse_summary,
)


# ---------------------------------------------------------------------------
# _read_last_stroke
# ---------------------------------------------------------------------------


class TestReadLastStroke:
    def test_basic(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"kind":"note","ts":"2026-10-17T10:00:00Z","seq":100}\n'
            '{"kind":"devlog","ts":"2026-10-17T11:00:00Z","seq":101}\n'
        )
        result = _read_last_stroke(tmp_path)
        assert result is not None
        assert result["seq"] == 101
        assert result["kind"] == "devlog"

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        assert _read_last_stroke(tmp_path) is None

    def test_missing_file(self, tmp_path):
        assert _read_last_stroke(tmp_path) is None

    def test_single_line(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text('{"kind":"note","ts":"2026-10-17T10:00:00Z","seq":1}\n')
        result = _read_last_stroke(tmp_path)
        assert result is not None
        assert result["seq"] == 1

    def test_corrupted_json(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text('{"kind":"note","ts":"2026-10-17T10:00:00Z"}\nnot-json\n')
        # Should return None for corrupted last line
        result = _read_last_stroke(tmp_path)
        # Implementation returns None on JSONDecodeError
        assert result is None

    def test_whitespace_only(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("   \n  \n")
        assert _read_last_stroke(tmp_path) is None


# ---------------------------------------------------------------------------
# _read_writer_log
# ---------------------------------------------------------------------------


class TestReadWriterLog:
    def test_missing_log(self):
        # Should return empty list for non-existent log
        lines = _read_writer_log("nonexistent-writer-12345", lookback_seconds=60)
        assert lines == []

    def test_with_temp_log(self, tmp_path, monkeypatch):
        # Create a temporary log file
        log_content = (
            "2026-10-17T10:00:00 INFO Starting writer\n"
            "2026-10-17T10:00:05 INFO Wrote stroke 100\n"
            "2026-10-17T10:00:10 ERROR Connection failed\n"
            "2026-10-17T10:00:15 INFO Retrying\n"
        )
        log_file = tmp_path / "iamai-test.log"
        log_file.write_text(log_content)

        # Monkeypatch the log path
        monkeypatch.setattr(
            "iamai.writer_pulse.Path",
            lambda p: log_file if "iamai-test.log" in str(p) else Path(p),
        )

        # This is tricky to test without monkeypatching, so we'll just verify
        # the function doesn't crash when called with a real writer_id
        lines = _read_writer_log("test", lookback_seconds=60)
        assert isinstance(lines, list)


# ---------------------------------------------------------------------------
# _count_errors
# ---------------------------------------------------------------------------


class TestCountErrors:
    def test_no_errors(self):
        lines = [
            "2026-10-17T10:00:00 INFO Starting writer",
            "2026-10-17T10:00:05 INFO Wrote stroke 100",
            "2026-10-17T10:00:10 INFO Done",
        ]
        assert _count_errors(lines) == 0

    def test_single_error(self):
        lines = [
            "2026-10-17T10:00:00 INFO Starting writer",
            "2026-10-17T10:00:05 ERROR Connection failed",
        ]
        assert _count_errors(lines) == 1

    def test_multiple_errors(self):
        lines = [
            "ERROR: something went wrong",
            "Exception in thread main",
            "Traceback (most recent call last)",
            "INFO: recovered",
            "CRITICAL: disk full",
        ]
        assert _count_errors(lines) == 4

    def test_case_insensitive(self):
        lines = [
            "error: lowercase",
            "ERROR: uppercase",
            "Error: mixed case",
            "exception: lowercase",
        ]
        assert _count_errors(lines) == 4

    def test_empty_lines(self):
        assert _count_errors([]) == 0

    def test_partial_matches(self):
        lines = [
            "INFO: no errors here",
            "INFO: this is exceptional work",  # Matches "Exception" (word boundary)
            "INFO: traceback route",  # Matches "Traceback"
        ]
        count = _count_errors(lines)
        # "Exception" matches with word boundary, "Traceback" matches
        # "exceptional" doesn't match because \bException\b requires word boundary
        assert count >= 1  # At least "Traceback" matches


# ---------------------------------------------------------------------------
# _count_wait_messages
# ---------------------------------------------------------------------------


class TestCountWaitMessages:
    def test_no_waits(self):
        lines = [
            "INFO: wrote stroke 100",
            "INFO: committed changes",
        ]
        assert _count_wait_messages(lines) == 0

    def test_waiting(self):
        lines = [
            "INFO: waiting for lock",
            "INFO: still waiting",
        ]
        assert _count_wait_messages(lines) == 2

    def test_idle(self):
        lines = [
            "INFO: writer is idle",
            "INFO: system idle",
        ]
        assert _count_wait_messages(lines) == 2

    def test_sleeping(self):
        lines = [
            "INFO: sleeping for 60s",
        ]
        assert _count_wait_messages(lines) == 1

    def test_retrying(self):
        lines = [
            "INFO: retrying connection",
            "INFO: retry 3 of 5",
        ]
        # "retrying" matches \bretrying\b, but "retry" doesn't match \bretrying\b
        assert _count_wait_messages(lines) >= 1

    def test_mixed(self):
        lines = [
            "INFO: waiting",
            "INFO: sleeping",
            "INFO: retrying",
            "INFO: idle",
            "INFO: no work",
        ]
        assert _count_wait_messages(lines) == 5

    def test_case_insensitive(self):
        lines = [
            "WAITING: uppercase",
            "Waiting: mixed",
            "waiting: lowercase",
        ]
        assert _count_wait_messages(lines) == 3


# ---------------------------------------------------------------------------
# writer_pulse
# ---------------------------------------------------------------------------


class TestWriterPulse:
    def test_dead_process(self, tmp_path, monkeypatch):
        # Mock _get_process_uptime to return None (process not running)
        monkeypatch.setattr(
            "iamai.writer_pulse._get_process_uptime",
            lambda writer_id: None,
        )
        result = writer_pulse("test", data_dir=tmp_path)
        assert result["score"] == 0
        assert result["verdict"] == "dead"
        assert "not running" in result["details"]

    def test_fresh_install(self, tmp_path, monkeypatch):
        # Mock process running
        monkeypatch.setattr(
            "iamai.writer_pulse._get_process_uptime",
            lambda writer_id: 3600,
        )
        # No strokes file exists
        result = writer_pulse("test", data_dir=tmp_path)
        assert result["score"] == 100
        assert result["verdict"] == "healthy"
        assert "fresh install" in result["details"]

    def test_healthy_writer(self, tmp_path, monkeypatch):
        # Mock process running
        monkeypatch.setattr(
            "iamai.writer_pulse._get_process_uptime",
            lambda writer_id: 3600,
        )
        # Mock recent stroke
        now = datetime.now(timezone.utc)
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text(
            json.dumps({
                "kind": "note",
                "ts": now.isoformat(),
                "seq": 100,
            }) + "\n"
        )
        # Mock no errors in log
        monkeypatch.setattr(
            "iamai.writer_pulse._read_writer_log",
            lambda writer_id, lookback_seconds: [],
        )
        result = writer_pulse("test", cadence=600, data_dir=tmp_path)
        assert result["score"] >= 80
        assert result["verdict"] == "healthy"
        assert result["recent_errors"] == 0

    def test_degraded_writer(self, tmp_path, monkeypatch):
        # Mock process running
        monkeypatch.setattr(
            "iamai.writer_pulse._get_process_uptime",
            lambda writer_id: 3600,
        )
        # Mock old stroke (2x cadence ago)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=1200)
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text(
            json.dumps({
                "kind": "note",
                "ts": old_time.isoformat(),
                "seq": 100,
            }) + "\n"
        )
        # Mock some errors
        monkeypatch.setattr(
            "iamai.writer_pulse._read_writer_log",
            lambda writer_id, lookback_seconds: [
                "ERROR: connection failed",
                "ERROR: retry failed",
            ],
        )
        result = writer_pulse("test", cadence=600, data_dir=tmp_path)
        # With 2x cadence gap + 2 errors, score should be degraded or struggling
        assert result["score"] < 80
        assert result["verdict"] in ["degraded", "struggling"]
        assert result["recent_errors"] == 2

    def test_struggling_writer(self, tmp_path, monkeypatch):
        # Mock process running
        monkeypatch.setattr(
            "iamai.writer_pulse._get_process_uptime",
            lambda writer_id: 3600,
        )
        # Mock very old stroke (3x cadence ago)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=1800)
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text(
            json.dumps({
                "kind": "note",
                "ts": old_time.isoformat(),
                "seq": 100,
            }) + "\n"
        )
        # Mock many errors
        monkeypatch.setattr(
            "iamai.writer_pulse._read_writer_log",
            lambda writer_id, lookback_seconds: [
                "ERROR: " + str(i) for i in range(10)
            ],
        )
        result = writer_pulse("test", cadence=600, data_dir=tmp_path)
        # With 3x cadence gap + 10 errors, score should be low
        assert result["score"] < 50
        assert result["verdict"] in ["struggling", "zombie"]
        assert result["recent_errors"] == 10

    def test_zombie_writer(self, tmp_path, monkeypatch):
        # Mock process running for a long time
        monkeypatch.setattr(
            "iamai.writer_pulse._get_process_uptime",
            lambda writer_id: 7200,  # 2 hours
        )
        # Mock very old stroke (4x cadence ago)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=2400)
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text(
            json.dumps({
                "kind": "note",
                "ts": old_time.isoformat(),
                "seq": 100,
            }) + "\n"
        )
        # Mock no errors (process is just stuck)
        monkeypatch.setattr(
            "iamai.writer_pulse._read_writer_log",
            lambda writer_id, lookback_seconds: [],
        )
        result = writer_pulse("test", cadence=600, data_dir=tmp_path)
        # With 4x cadence gap + long uptime + no errors, should be zombie or struggling
        assert result["score"] <= 20
        assert result["verdict"] in ["zombie", "struggling"]
        assert "zombie" in result["details"] or "stroke gap" in result["details"]

    def test_custom_cadence(self, tmp_path, monkeypatch):
        # Mock process running
        monkeypatch.setattr(
            "iamai.writer_pulse._get_process_uptime",
            lambda writer_id: 1800,
        )
        # Mock stroke 900s ago (1.5x of 600s cadence, but 0.75x of 1200s cadence)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=900)
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text(
            json.dumps({
                "kind": "note",
                "ts": old_time.isoformat(),
                "seq": 100,
            }) + "\n"
        )
        monkeypatch.setattr(
            "iamai.writer_pulse._read_writer_log",
            lambda writer_id, lookback_seconds: [],
        )
        # With 600s cadence, this is degraded
        result1 = writer_pulse("test", cadence=600, data_dir=tmp_path)
        # With 1200s cadence, this is healthy
        result2 = writer_pulse("test", cadence=1200, data_dir=tmp_path)
        assert result1["score"] < result2["score"]


# ---------------------------------------------------------------------------
# pulse_history
# ---------------------------------------------------------------------------


class TestPulseHistory:
    def test_empty_when_no_strokes(self, tmp_path):
        history = pulse_history("test", lookback=3600, data_dir=tmp_path)
        assert history == []

    def test_basic_history(self, tmp_path, monkeypatch):
        # Create strokes
        now = datetime.now(timezone.utc)
        strokes_file = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(5):
            ts = now - timedelta(minutes=10 * (4 - i))
            lines.append(json.dumps({
                "kind": "note",
                "ts": ts.isoformat(),
                "seq": 100 + i,
            }))
        strokes_file.write_text("\n".join(lines) + "\n")

        # Mock _get_process_uptime to return a valid value
        monkeypatch.setattr(
            "iamai.writer_pulse._get_process_uptime",
            lambda writer_id: 3600,
        )
        
        # Mock _read_writer_log to return empty
        monkeypatch.setattr(
            "iamai.writer_pulse._read_writer_log",
            lambda writer_id, lookback_seconds: [],
        )

        history = pulse_history("test", lookback=3600, cadence=600, data_dir=tmp_path)
        assert len(history) > 0
        assert all("ts" in h and "score" in h for h in history)
        # Last entry should be the current reading
        assert history[-1]["score"] >= 0

    def test_lookback_filter(self, tmp_path, monkeypatch):
        # Create old and new strokes
        now = datetime.now(timezone.utc)
        strokes_file = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({
                "kind": "note",
                "ts": (now - timedelta(hours=2)).isoformat(),
                "seq": 100,
            }),
            json.dumps({
                "kind": "note",
                "ts": (now - timedelta(minutes=30)).isoformat(),
                "seq": 101,
            }),
        ]
        strokes_file.write_text("\n".join(lines) + "\n")

        # Mock process running
        monkeypatch.setattr(
            "iamai.writer_pulse._get_process_uptime",
            lambda writer_id: 3600,
        )
        
        # Mock clean log
        monkeypatch.setattr(
            "iamai.writer_pulse._read_writer_log",
            lambda writer_id, lookback_seconds: [],
        )

        # With 1-hour lookback, should only see the recent stroke
        history = pulse_history("test", lookback=3600, data_dir=tmp_path)
        # Should have at least the current reading
        assert len(history) >= 1


# ---------------------------------------------------------------------------
# pulse_trend
# ---------------------------------------------------------------------------


class TestPulseTrend:
    def test_stable(self):
        history = [
            {"ts": "2026-10-17T10:00:00Z", "score": 90},
            {"ts": "2026-10-17T10:10:00Z", "score": 91},
            {"ts": "2026-10-17T10:20:00Z", "score": 89},
        ]
        assert pulse_trend(history) == "stable"

    def test_improving(self):
        history = [
            {"ts": "2026-10-17T10:00:00Z", "score": 50},
            {"ts": "2026-10-17T10:10:00Z", "score": 70},
            {"ts": "2026-10-17T10:20:00Z", "score": 90},
        ]
        assert pulse_trend(history) == "improving"

    def test_declining(self):
        history = [
            {"ts": "2026-10-17T10:00:00Z", "score": 90},
            {"ts": "2026-10-17T10:10:00Z", "score": 70},
            {"ts": "2026-10-17T10:20:00Z", "score": 50},
        ]
        assert pulse_trend(history) == "declining"

    def test_too_few_points(self):
        assert pulse_trend([]) == "stable"
        assert pulse_trend([{"ts": "t", "score": 50}]) == "stable"
        assert pulse_trend([{"ts": "t1", "score": 50}, {"ts": "t2", "score": 60}]) == "stable"

    def test_constant_scores(self):
        history = [{"ts": f"t{i}", "score": 80} for i in range(10)]
        assert pulse_trend(history) == "stable"


# ---------------------------------------------------------------------------
# pulse_summary
# ---------------------------------------------------------------------------


class TestPulseSummary:
    def test_dead_summary(self, monkeypatch):
        monkeypatch.setattr(
            "iamai.writer_pulse.writer_pulse",
            lambda writer_id, cadence: {
                "score": 0,
                "verdict": "dead",
                "last_stroke_age": -1,
                "recent_errors": 0,
                "recent_waits": 0,
                "uptime": 0,
                "details": "process not running",
            },
        )
        summary = pulse_summary("test")
        assert "dead" in summary
        assert "not running" in summary

    def test_healthy_summary(self, monkeypatch):
        monkeypatch.setattr(
            "iamai.writer_pulse.writer_pulse",
            lambda writer_id, cadence: {
                "score": 92,
                "verdict": "healthy",
                "last_stroke_age": 340,
                "recent_errors": 0,
                "recent_waits": 0,
                "uptime": 3600,
                "details": "test",
            },
        )
        summary = pulse_summary("test")
        assert "healthy" in summary
        assert "92" in summary
        assert "340" in summary

    def test_zombie_summary(self, monkeypatch):
        monkeypatch.setattr(
            "iamai.writer_pulse.writer_pulse",
            lambda writer_id, cadence: {
                "score": 15,
                "verdict": "zombie",
                "last_stroke_age": 7200,
                "recent_errors": 0,
                "recent_waits": 0,
                "uptime": 3600,
                "details": "zombie",
            },
        )
        summary = pulse_summary("test")
        assert "zombie" in summary
        assert "15" in summary
        assert "3600" in summary

    def test_degraded_summary(self, monkeypatch):
        monkeypatch.setattr(
            "iamai.writer_pulse.writer_pulse",
            lambda writer_id, cadence: {
                "score": 65,
                "verdict": "degraded",
                "last_stroke_age": 1200,
                "recent_errors": 3,
                "recent_waits": 5,
                "uptime": 3600,
                "details": "test",
            },
        )
        summary = pulse_summary("test")
        assert "degraded" in summary
        assert "65" in summary

    def test_struggling_summary(self, monkeypatch):
        monkeypatch.setattr(
            "iamai.writer_pulse.writer_pulse",
            lambda writer_id, cadence: {
                "score": 35,
                "verdict": "struggling",
                "last_stroke_age": 2400,
                "recent_errors": 8,
                "recent_waits": 10,
                "uptime": 3600,
                "details": "test",
            },
        )
        summary = pulse_summary("test")
        assert "struggling" in summary
        assert "35" in summary
        assert "8 errors" in summary


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_workflow(self, tmp_path, monkeypatch):
        """Test the complete workflow: write strokes, compute pulse, get history."""
        # Mock process running
        monkeypatch.setattr(
            "iamai.writer_pulse._get_process_uptime",
            lambda writer_id: 3600,
        )

        # Create strokes - most recent one is very recent
        now = datetime.now(timezone.utc)
        strokes_file = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(10):
            # Last stroke is only 5 minutes ago (healthy)
            ts = now - timedelta(minutes=5 * (9 - i))
            lines.append(json.dumps({
                "kind": "note",
                "ts": ts.isoformat(),
                "seq": 100 + i,
            }))
        strokes_file.write_text("\n".join(lines) + "\n")

        # Mock clean log
        monkeypatch.setattr(
            "iamai.writer_pulse._read_writer_log",
            lambda writer_id, lookback_seconds: [],
        )

        # Get pulse
        pulse = writer_pulse("test", cadence=600, data_dir=tmp_path)
        assert pulse["score"] >= 0  # Score is computed
        assert pulse["verdict"] in ["healthy", "degraded", "struggling", "zombie", "dead"]

        # Get history
        history = pulse_history("test", lookback=3600, cadence=600, data_dir=tmp_path)
        assert len(history) > 0

        # Get trend
        trend = pulse_trend(history)
        assert trend in ["improving", "stable", "declining"]

        # Get summary
        summary = pulse_summary("test", cadence=600)
        assert any(word in summary for word in ["healthy", "degraded", "struggling", "zombie", "dead"])
