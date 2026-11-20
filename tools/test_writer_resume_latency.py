#!/usr/bin/env python3
"""Tests for writer_resume_latency.py"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, mock_open
from datetime import datetime, timezone

# Ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

import writer_resume_latency as wrl


class TestReadState(unittest.TestCase):
    """Test reading writer state from JSON file."""

    def test_returns_none_on_missing_file(self):
        with patch.object(wrl, "STATE_FILE", Path("/nonexistent/state.json")):
            seq, at = wrl.read_state()
            self.assertIsNone(seq)
            self.assertIsNone(at)

    def test_returns_none_on_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            f.flush()
            with patch.object(wrl, "STATE_FILE", Path(f.name)):
                seq, at = wrl.read_state()
                self.assertIsNone(seq)
                self.assertIsNone(at)
            os.unlink(f.name)

    def test_returns_latest_entry(self):
        state = {
            "history": [
                {"seq": 100, "at": "2026-11-20T01:00:00+00:00", "kind": "note"},
                {"seq": 101, "at": "2026-11-20T01:01:00+00:00", "kind": "thought"},
                {"seq": 102, "at": "2026-11-20T01:02:00+00:00", "kind": "snippet"},
            ]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(state, f)
            f.flush()
            with patch.object(wrl, "STATE_FILE", Path(f.name)):
                seq, at = wrl.read_state()
                self.assertEqual(seq, 102)
                self.assertEqual(at, "2026-11-20T01:02:00+00:00")
            os.unlink(f.name)

    def test_returns_none_for_empty_history(self):
        state = {"history": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(state, f)
            f.flush()
            with patch.object(wrl, "STATE_FILE", Path(f.name)):
                seq, at = wrl.read_state()
                self.assertIsNone(seq)
                self.assertIsNone(at)
            os.unlink(f.name)

    def test_handles_missing_history_key(self):
        state = {"other_key": "value"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(state, f)
            f.flush()
            with patch.object(wrl, "STATE_FILE", Path(f.name)):
                seq, at = wrl.read_state()
                self.assertIsNone(seq)
            os.unlink(f.name)


class TestRecordRestart(unittest.TestCase):
    """Test restart epoch recording."""

    def test_records_current_time(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            marker = f.name
        with patch.object(wrl, "RESTART_MARKER", marker):
            before = time.time()
            epoch = wrl.record_restart()
            after = time.time()
            self.assertGreaterEqual(epoch, before)
            self.assertLessEqual(epoch, after)
            # Verify file was written
            content = Path(marker).read_text().strip()
            self.assertAlmostEqual(float(content), epoch, places=2)
        os.unlink(marker)

    def test_record_and_read_roundtrip(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            marker = f.name
        with patch.object(wrl, "RESTART_MARKER", marker):
            recorded = wrl.record_restart()
            read_back = wrl.read_restart_epoch()
            self.assertAlmostEqual(recorded, read_back, places=3)
        os.unlink(marker)


class TestReadRestartEpoch(unittest.TestCase):
    """Test reading restart epoch."""

    def test_returns_none_for_missing_file(self):
        with patch.object(wrl, "RESTART_MARKER", "/nonexistent/marker"):
            self.assertIsNone(wrl.read_restart_epoch())

    def test_returns_none_for_invalid_content(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("not a number")
            f.flush()
            with patch.object(wrl, "RESTART_MARKER", f.name):
                self.assertIsNone(wrl.read_restart_epoch())
            os.unlink(f.name)

    def test_reads_valid_float(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("1700000000.123\n")
            f.flush()
            with patch.object(wrl, "RESTART_MARKER", f.name):
                self.assertAlmostEqual(wrl.read_restart_epoch(), 1700000000.123)
            os.unlink(f.name)


class TestAppendLatency(unittest.TestCase):
    """Test latency log appending."""

    def test_appends_valid_json_line(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            log_path = f.name

        with patch.object(wrl, "LATENCY_LOG", Path(log_path)):
            restart_epoch = 1700000000.0
            record = wrl.append_latency(
                restart_epoch,
                "2026-11-20T01:02:30+00:00",
                15.5,
                102
            )
            self.assertEqual(record["latency_seconds"], 15.5)
            self.assertEqual(record["seq"], 102)
            self.assertIn("restart_at", record)
            self.assertIn("writer_id", record)

            # Verify the line was written
            lines = Path(log_path).read_text().strip().split("\n")
            self.assertEqual(len(lines), 1)
            parsed = json.loads(lines[0])
            self.assertEqual(parsed["seq"], 102)

        os.unlink(log_path)

    def test_appends_multiple_records(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            log_path = f.name

        with patch.object(wrl, "LATENCY_LOG", Path(log_path)):
            wrl.append_latency(1700000000.0, "2026-11-20T01:00:15+00:00", 15.0, 100)
            wrl.append_latency(1700000600.0, "2026-11-20T01:10:12+00:00", 12.0, 150)
            wrl.append_latency(1700001200.0, "2026-11-20T01:20:08+00:00", 8.0, 200)

            lines = Path(log_path).read_text().strip().split("\n")
            self.assertEqual(len(lines), 3)
            last = json.loads(lines[-1])
            self.assertEqual(last["seq"], 200)
            self.assertEqual(last["latency_seconds"], 8.0)

        os.unlink(log_path)


class TestMeasure(unittest.TestCase):
    """Test the measurement loop."""

    def test_detects_new_stroke(self):
        """Simulate writer producing a stroke after restart."""
        call_count = [0]
        base_seq = 100

        def mock_read_state():
            call_count[0] += 1
            if call_count[0] >= 3:
                return base_seq + 1, "2026-11-20T01:02:00+00:00"
            return base_seq, "2026-11-20T01:01:00+00:00"

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write(f"{time.time() - 5}\n")
            f.flush()
            marker = f.name

        with patch.object(wrl, "read_state", side_effect=mock_read_state), \
             patch.object(wrl, "RESTART_MARKER", marker), \
             patch("time.sleep"):  # Don't actually sleep
            latency, seq, stroke_at = wrl.measure(timeout=30)
            self.assertEqual(seq, 101)
            self.assertGreater(latency, 0)
            self.assertEqual(stroke_at, "2026-11-20T01:02:00+00:00")

        os.unlink(marker)

    def test_timeout_raises(self):
        """Writer never produces a stroke → TimeoutError."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write(f"{time.time()}\n")
            f.flush()
            marker = f.name

        with patch.object(wrl, "read_state", return_value=(100, "old")), \
             patch.object(wrl, "RESTART_MARKER", marker), \
             patch("time.sleep"), \
             patch("time.time") as mock_time:
            # Simulate time passing beyond timeout
            mock_time.side_effect = [time.time(), time.time() + 100]
            with self.assertRaises(TimeoutError):
                wrl.measure(timeout=5)

        os.unlink(marker)

    def test_handles_none_baseline(self):
        """Empty history (baseline_seq=None) should still detect first stroke."""
        call_count = [0]

        def mock_read_state():
            call_count[0] += 1
            if call_count[0] >= 2:
                return 1, "2026-11-20T01:00:00+00:00"
            return None, None

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write(f"{time.time() - 3}\n")
            f.flush()
            marker = f.name

        with patch.object(wrl, "read_state", side_effect=mock_read_state), \
             patch.object(wrl, "RESTART_MARKER", marker), \
             patch("time.sleep"):
            latency, seq, _ = wrl.measure(timeout=30)
            self.assertEqual(seq, 1)

        os.unlink(marker)


class TestFormatReport(unittest.TestCase):
    """Test human-readable output formatting."""

    def test_contains_all_fields(self):
        record = {
            "restart_at": "2026-11-20T01:00:00+00:00",
            "first_stroke_at": "2026-11-20T01:00:15+00:00",
            "latency_seconds": 15.3,
            "seq": 42,
            "writer_id": "qwen",
        }
        report = wrl.format_report(record)
        self.assertIn("15.3s", report)
        self.assertIn("2026-11-20T01:00:00+00:00", report)
        self.assertIn("2026-11-20T01:00:15+00:00", report)
        self.assertIn("42", report)
        self.assertIn("qwen", report)

    def test_latency_rounding(self):
        record = {
            "restart_at": "2026-11-20T01:00:00+00:00",
            "first_stroke_at": "2026-11-20T01:00:15+00:00",
            "latency_seconds": 15.0,
            "seq": 1,
            "writer_id": "qwen",
        }
        report = wrl.format_report(record)
        self.assertIn("15.0s", report)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def test_restart_epoch_with_trailing_whitespace(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("  1700000000.5  \n\n")
            f.flush()
            with patch.object(wrl, "RESTART_MARKER", f.name):
                self.assertAlmostEqual(wrl.read_restart_epoch(), 1700000000.5)
            os.unlink(f.name)

    def test_append_latency_rounds_to_two_decimals(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            log_path = f.name

        with patch.object(wrl, "LATENCY_LOG", Path(log_path)):
            record = wrl.append_latency(
                1700000000.0,
                "2026-11-20T01:00:00+00:00",
                12.3456789,
                50
            )
            self.assertEqual(record["latency_seconds"], 12.35)

        os.unlink(log_path)

    def test_state_with_missing_seq_key(self):
        """History entry without 'seq' should be handled gracefully."""
        state = {"history": [{"at": "2026-11-20T01:00:00+00:00", "kind": "note"}]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(state, f)
            f.flush()
            with patch.object(wrl, "STATE_FILE", Path(f.name)):
                seq, at = wrl.read_state()
                self.assertIsNone(seq)
                self.assertEqual(at, "2026-11-20T01:00:00+00:00")
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
