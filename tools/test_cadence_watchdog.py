#!/usr/bin/env python3
"""Tests for cadence_watchdog module.

Covers:
  - healthy writer (recent strokes)
  - stalled writer (gap exceeds threshold)
  - unknown state (no data sources available)
  - state file parsing
  - strokes.jsonl fallback
  - process alive detection
  - full health check integration
  - CLI argument handling
  - edge cases (zero interval, stale pid files)
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from cadence_watchdog import (
    CadenceStatus,
    check_cadence,
    check_process_alive,
    full_health_check,
    _get_last_stroke_from_state,
    _get_last_stroke_from_jsonl,
)


class TestCheckCadence(unittest.TestCase):
    """Tests for the main check_cadence function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        Path(self.tmpdir, "data").mkdir()
        self.now = 1700000000.0

    def _write_state(self, writer, last_time):
        state = {"last_stroke_time": last_time, "writer": writer}
        Path(self.tmpdir, "data", f"writer_state.{writer}.json").write_text(
            json.dumps(state)
        )

    def _write_jsonl(self, entries):
        lines = "\n".join(json.dumps(e) for e in entries)
        Path(self.tmpdir, "data", "strokes.jsonl").write_text(lines)

    # --- healthy cases ---

    def test_healthy_writer_recent_stroke(self):
        self._write_state("qwen", self.now - 10)
        status = check_cadence("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertTrue(status.healthy)
        self.assertFalse(status.stalled)
        self.assertAlmostEqual(status.gap_seconds, 10.0, delta=0.5)
        self.assertEqual(status.writer, "qwen")

    def test_healthy_writer_at_threshold_boundary(self):
        # exactly at threshold — should still be healthy (gap <= threshold)
        self._write_state("qwen", self.now - 30)
        status = check_cadence("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertTrue(status.healthy)
        self.assertFalse(status.stalled)

    def test_healthy_with_custom_interval(self):
        self._write_state("qwen", self.now - 50)
        status = check_cadence("qwen", 30.0, 2.0, self.tmpdir, self.now)
        self.assertTrue(status.healthy)
        self.assertEqual(status.threshold_seconds, 60.0)

    # --- stalled cases ---

    def test_stalled_writer(self):
        self._write_state("qwen", self.now - 100)
        status = check_cadence("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertFalse(status.healthy)
        self.assertTrue(status.stalled)
        self.assertGreater(status.gap_seconds, 30)

    def test_stalled_writer_long_gap(self):
        self._write_state("qwen", self.now - 3600)
        status = check_cadence("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertTrue(status.stalled)
        self.assertIn("stalled", status.reason)

    def test_stalled_just_past_threshold(self):
        # 31s gap with 30s threshold — stalled
        self._write_state("qwen", self.now - 31)
        status = check_cadence("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertTrue(status.stalled)

    # --- unknown cases ---

    def test_unknown_no_data_sources(self):
        status = check_cadence("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertFalse(status.healthy)
        self.assertFalse(status.stalled)
        self.assertTrue(status.is_unknown)
        self.assertIsNone(status.gap_seconds)

    def test_unknown_corrupt_state_file(self):
        Path(self.tmpdir, "data", "writer_state.qwen.json").write_text("not json{{{")
        status = check_cadence("qwen", 15.0, 2.0, self.tmpdir, self.now)
        # should fall through to jsonl, then git, then unknown
        self.assertFalse(status.healthy)

    # --- fallback chain ---

    def test_jsonl_fallback_when_no_state(self):
        entries = [
            {"stroke_id": 1, "timestamp": self.now - 500},
            {"stroke_id": 2, "timestamp": self.now - 20},
        ]
        self._write_jsonl(entries)
        status = check_cadence("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertTrue(status.healthy)
        self.assertIn("strokes.jsonl", status.source)
        self.assertEqual(status.strokes_count, 2)

    def test_state_takes_priority_over_jsonl(self):
        self._write_state("qwen", self.now - 10)
        entries = [{"stroke_id": 1, "timestamp": self.now - 5000}]
        self._write_jsonl(entries)
        status = check_cadence("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertTrue(status.healthy)
        self.assertIn("state file", status.source)
        self.assertAlmostEqual(status.gap_seconds, 10.0, delta=0.5)

    def test_jsonl_empty_file(self):
        Path(self.tmpdir, "data", "strokes.jsonl").write_text("")
        status = check_cadence("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertFalse(status.healthy)

    def test_jsonl_missing_timestamp(self):
        entries = [{"stroke_id": 1, "content": "no timestamp here"}]
        self._write_jsonl(entries)
        status = check_cadence("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertFalse(status.healthy)

    # --- dataclass properties ---

    def test_cadence_status_is_unknown_property(self):
        s = CadenceStatus(
            writer="qwen", healthy=False, stalled=False,
            gap_seconds=None, threshold_seconds=30.0,
            stroke_interval=15.0, last_stroke_time=None,
            reason="test",
        )
        self.assertTrue(s.is_unknown)

    def test_cadence_status_healthy_not_unknown(self):
        s = CadenceStatus(
            writer="qwen", healthy=True, stalled=False,
            gap_seconds=10.0, threshold_seconds=30.0,
            stroke_interval=15.0, last_stroke_time=1000.0,
            reason="test",
        )
        self.assertFalse(s.is_unknown)

    # --- edge cases ---

    def test_zero_interval(self):
        self._write_state("qwen", self.now - 1)
        status = check_cadence("qwen", 0.1, 2.0, self.tmpdir, self.now)
        self.assertTrue(status.stalled)  # 1s > 0.2s threshold

    def test_very_large_threshold(self):
        self._write_state("qwen", self.now - 1000)
        status = check_cadence("qwen", 15.0, 1000.0, self.tmpdir, self.now)
        self.assertTrue(status.healthy)  # 1000*15=15000s threshold, 1000s gap is fine

    def test_different_writer_id(self):
        self._write_state("kimi", self.now - 5)
        status = check_cadence("kimi", 15.0, 2.0, self.tmpdir, self.now)
        self.assertTrue(status.healthy)
        self.assertEqual(status.writer, "kimi")

    def test_nonexistent_repo_path(self):
        status = check_cadence("qwen", 15.0, 2.0, "/nonexistent/path", self.now)
        self.assertTrue(status.is_unknown)


class TestGetLastStrokeFromState(unittest.TestCase):
    """Tests for state file parsing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        Path(self.tmpdir, "data").mkdir()

    def test_valid_state_file(self):
        Path(self.tmpdir, "data", "writer_state.qwen.json").write_text(
            json.dumps({"last_stroke_time": 1700000000.0})
        )
        ts, source = _get_last_stroke_from_state(self.tmpdir, "qwen")
        self.assertEqual(ts, 1700000000.0)
        self.assertIn("state file", source)

    def test_alternative_key(self):
        Path(self.tmpdir, "data", "writer_state.qwen.json").write_text(
            json.dumps({"last_write_time": 1699999000.0})
        )
        ts, source = _get_last_stroke_from_state(self.tmpdir, "qwen")
        self.assertEqual(ts, 1699999000.0)

    def test_missing_file(self):
        ts, source = _get_last_stroke_from_state(self.tmpdir, "qwen")
        self.assertIsNone(ts)
        self.assertIn("no state file", source)

    def test_corrupt_json(self):
        Path(self.tmpdir, "data", "writer_state.qwen.json").write_text("{broken")
        ts, source = _get_last_stroke_from_state(self.tmpdir, "qwen")
        self.assertIsNone(ts)
        self.assertIn("parse error", source)

    def test_empty_object(self):
        Path(self.tmpdir, "data", "writer_state.qwen.json").write_text("{}")
        ts, source = _get_last_stroke_from_state(self.tmpdir, "qwen")
        self.assertIsNone(ts)
        self.assertIn("no timestamp", source)


class TestGetLastStrokeFromJsonl(unittest.TestCase):
    """Tests for strokes.jsonl parsing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        Path(self.tmpdir, "data").mkdir()

    def test_valid_jsonl(self):
        lines = "\n".join([
            json.dumps({"stroke_id": 1, "timestamp": 100.0}),
            json.dumps({"stroke_id": 2, "timestamp": 200.0}),
        ])
        Path(self.tmpdir, "data", "strokes.jsonl").write_text(lines)
        ts, count, source = _get_last_stroke_from_jsonl(self.tmpdir)
        self.assertEqual(ts, 200.0)
        self.assertEqual(count, 2)

    def test_alternative_timestamp_keys(self):
        lines = json.dumps({"stroke_id": 1, "time": 300.0})
        Path(self.tmpdir, "data", "strokes.jsonl").write_text(lines)
        ts, count, source = _get_last_stroke_from_jsonl(self.tmpdir)
        self.assertEqual(ts, 300.0)

    def test_missing_file(self):
        ts, count, source = _get_last_stroke_from_jsonl(self.tmpdir)
        self.assertIsNone(ts)
        self.assertEqual(count, 0)

    def test_empty_file(self):
        Path(self.tmpdir, "data", "strokes.jsonl").write_text("")
        ts, count, source = _get_last_stroke_from_jsonl(self.tmpdir)
        self.assertIsNone(ts)
        self.assertEqual(count, 0)

    def test_blank_lines_ignored(self):
        lines = "\n".join([
            json.dumps({"stroke_id": 1, "timestamp": 100.0}),
            "",
            "  ",
            json.dumps({"stroke_id": 2, "timestamp": 200.0}),
        ])
        Path(self.tmpdir, "data", "strokes.jsonl").write_text(lines)
        ts, count, source = _get_last_stroke_from_jsonl(self.tmpdir)
        self.assertEqual(ts, 200.0)
        self.assertEqual(count, 2)


class TestCheckProcessAlive(unittest.TestCase):
    """Tests for process alive detection via pid files."""

    def test_no_pid_files(self):
        result = check_process_alive("nonexistent_writer_xyz")
        self.assertFalse(result["writer_alive"])
        self.assertFalse(result["batch_alive"])

    def test_stale_pid_file(self):
        # write a pid file with a PID that definitely doesn't exist
        pid_file = Path("/tmp/iamai-writer-test_stale.pid")
        pid_file.write_text("999999999")
        try:
            result = check_process_alive("test_stale")
            self.assertFalse(result["writer_alive"])
            self.assertEqual(result["writer_pid"], 999999999)
        finally:
            pid_file.unlink(missing_ok=True)

    def test_corrupt_pid_file(self):
        pid_file = Path("/tmp/iamai-writer-test_corrupt.pid")
        pid_file.write_text("not_a_number")
        try:
            result = check_process_alive("test_corrupt")
            self.assertFalse(result["writer_alive"])
        finally:
            pid_file.unlink(missing_ok=True)

    def test_alive_process_self(self):
        # use our own PID as a guaranteed-alive process
        my_pid = os.getpid()
        pid_file = Path("/tmp/iamai-writer-test_self.pid")
        pid_file.write_text(str(my_pid))
        try:
            result = check_process_alive("test_self")
            self.assertTrue(result["writer_alive"])
            self.assertEqual(result["writer_pid"], my_pid)
        finally:
            pid_file.unlink(missing_ok=True)


class TestFullHealthCheck(unittest.TestCase):
    """Tests for the combined health check."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        Path(self.tmpdir, "data").mkdir()
        self.now = 1700000000.0

    def _write_state(self, writer, last_time):
        state = {"last_stroke_time": last_time}
        Path(self.tmpdir, "data", f"writer_state.{writer}.json").write_text(
            json.dumps(state)
        )

    @patch("cadence_watchdog.check_process_alive")
    def test_healthy_overall(self, mock_process):
        mock_process.return_value = {
            "writer_alive": True, "batch_alive": True,
            "writer_pid": 100, "batch_pid": 101,
        }
        self._write_state("qwen", self.now - 10)
        result = full_health_check("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertEqual(result["overall"], "healthy")
        self.assertEqual(result["recommendation"], "no action needed")

    @patch("cadence_watchdog.check_process_alive")
    def test_stalled_dead_process(self, mock_process):
        mock_process.return_value = {
            "writer_alive": False, "batch_alive": False,
            "writer_pid": None, "batch_pid": None,
        }
        self._write_state("qwen", self.now - 3600)
        result = full_health_check("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertEqual(result["overall"], "stalled")
        self.assertIn("restart", result["recommendation"])

    @patch("cadence_watchdog.check_process_alive")
    def test_stalled_alive_process(self, mock_process):
        mock_process.return_value = {
            "writer_alive": True, "batch_alive": True,
            "writer_pid": 100, "batch_pid": 101,
        }
        self._write_state("qwen", self.now - 3600)
        result = full_health_check("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertEqual(result["overall"], "stalled")
        self.assertIn("deadlock", result["recommendation"])

    @patch("cadence_watchdog.check_process_alive")
    def test_unknown_state(self, mock_process):
        mock_process.return_value = {
            "writer_alive": False, "batch_alive": False,
            "writer_pid": None, "batch_pid": None,
        }
        result = full_health_check("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertEqual(result["overall"], "unknown")

    @patch("cadence_watchdog.check_process_alive")
    def test_healthy_cadence_missing_pid(self, mock_process):
        """Writer producing strokes but pid file missing — still healthy."""
        mock_process.return_value = {
            "writer_alive": False, "batch_alive": False,
            "writer_pid": None, "batch_pid": None,
        }
        self._write_state("qwen", self.now - 10)
        result = full_health_check("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertEqual(result["overall"], "healthy")
        self.assertIn("pid file", result["recommendation"])

    def test_result_structure(self):
        """Ensure all expected keys are present in result."""
        result = full_health_check("qwen", 15.0, 2.0, self.tmpdir, self.now)
        self.assertIn("cadence", result)
        self.assertIn("process", result)
        self.assertIn("overall", result)
        self.assertIn("recommendation", result)
        self.assertIn(result["overall"], ("healthy", "stalled", "unknown"))


if __name__ == "__main__":
    unittest.main()
