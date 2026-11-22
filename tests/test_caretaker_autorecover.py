#!/usr/bin/env python3
"""Tests for tools/caretaker_autorecover.py — 22 tests.

Covers: probe (alive/dead/missing pid), death recording, restart,
push recovery, full autorecover flow, dry run, probe-only, edge cases.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

# allow importing from tools/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from caretaker_autorecover import (
    RecoveryReport,
    _read_pid,
    _is_alive,
    probe,
    _record_deaths,
    _restart,
    autorecover,
)


class TestRecoveryReport(unittest.TestCase):
    """Tests for the RecoveryReport dataclass."""

    def test_recovered_all_alive_no_push(self):
        r = RecoveryReport(writer_alive=True, batch_alive=True)
        self.assertTrue(r.recovered)

    def test_not_recovered_writer_dead(self):
        r = RecoveryReport(writer_alive=False, batch_alive=True)
        self.assertFalse(r.recovered)

    def test_not_recovered_batch_dead(self):
        r = RecoveryReport(writer_alive=True, batch_alive=False)
        self.assertFalse(r.recovered)

    def test_not_recovered_push_failed(self):
        r = RecoveryReport(
            writer_alive=True,
            batch_alive=True,
            push_attempted=True,
            push_result={"ok": False, "error": "network"},
        )
        self.assertFalse(r.recovered)

    def test_recovered_push_succeeded(self):
        r = RecoveryReport(
            writer_alive=True,
            batch_alive=True,
            push_attempted=True,
            push_result={"ok": True},
        )
        self.assertTrue(r.recovered)

    def test_not_recovered_has_errors(self):
        r = RecoveryReport(
            writer_alive=True,
            batch_alive=True,
            errors=["something went wrong"],
        )
        self.assertFalse(r.recovered)

    def test_to_dict(self):
        r = RecoveryReport(writer_alive=True, batch_alive=True)
        d = r.to_dict()
        self.assertIn("writer_alive", d)
        self.assertIn("batch_alive", d)
        self.assertTrue(d["writer_alive"])

    def test_recovered_push_skipped(self):
        """Push not attempted and both alive → recovered."""
        r = RecoveryReport(
            writer_alive=True,
            batch_alive=True,
            push_attempted=False,
        )
        self.assertTrue(r.recovered)


class TestReadPid(unittest.TestCase):
    """Tests for _read_pid helper."""

    def test_valid_pid(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            f.write("12345\n")
            f.flush()
            self.assertEqual(_read_pid(Path(f.name)), 12345)
        os.unlink(f.name)

    def test_missing_file(self):
        self.assertIsNone(_read_pid(Path("/nonexistent/pidfile.pid")))

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            f.write("")
            f.flush()
            self.assertIsNone(_read_pid(Path(f.name)))
        os.unlink(f.name)

    def test_non_numeric(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            f.write("not-a-pid\n")
            f.flush()
            self.assertIsNone(_read_pid(Path(f.name)))
        os.unlink(f.name)


class TestIsAlive(unittest.TestCase):
    """Tests for _is_alive helper."""

    def test_none_pid(self):
        self.assertFalse(_is_alive(None))

    def test_nonexistent_pid(self):
        # pid 99999999 almost certainly does not exist
        self.assertFalse(_is_alive(99999999))

    def test_current_process_alive(self):
        self.assertTrue(_is_alive(os.getpid()))


class TestProbe(unittest.TestCase):
    """Tests for the probe() function."""

    def test_both_alive(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as wf, \
             tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as bf:
            wf.write(str(os.getpid())); wf.flush()
            bf.write(str(os.getpid())); bf.flush()
            result = probe(Path(wf.name), Path(bf.name))
            self.assertTrue(result["writer_alive"])
            self.assertTrue(result["batch_alive"])
        os.unlink(wf.name)
        os.unlink(bf.name)

    def test_both_dead(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as wf, \
             tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as bf:
            wf.write("99999999"); wf.flush()
            bf.write("99999998"); bf.flush()
            result = probe(Path(wf.name), Path(bf.name))
            self.assertFalse(result["writer_alive"])
            self.assertFalse(result["batch_alive"])
        os.unlink(wf.name)
        os.unlink(bf.name)

    def test_missing_pid_files(self):
        result = probe(Path("/no/writer.pid"), Path("/no/batch.pid"))
        self.assertFalse(result["writer_alive"])
        self.assertFalse(result["batch_alive"])
        self.assertIsNone(result["writer_pid"])
        self.assertIsNone(result["batch_pid"])


class TestRecordDeaths(unittest.TestCase):
    """Tests for _record_deaths — recording death events."""

    @patch("caretaker_autorecover.REPO", Path("/fake/repo"))
    def test_both_dead_records_two(self):
        mock_record = MagicMock()
        with patch.dict(sys.modules, {"process_death_clock": MagicMock(record_death=mock_record)}):
            dead = _record_deaths(False, False, 100, 200)
        self.assertEqual(dead, ["writer", "batch"])
        self.assertEqual(mock_record.call_count, 2)

    @patch("caretaker_autorecover.REPO", Path("/fake/repo"))
    def test_only_writer_dead(self):
        mock_record = MagicMock()
        with patch.dict(sys.modules, {"process_death_clock": MagicMock(record_death=mock_record)}):
            dead = _record_deaths(False, True, 100, None)
        self.assertEqual(dead, ["writer"])
        self.assertEqual(mock_record.call_count, 1)

    @patch("caretaker_autorecover.REPO", Path("/fake/repo"))
    def test_both_alive_records_none(self):
        mock_record = MagicMock()
        with patch.dict(sys.modules, {"process_death_clock": MagicMock(record_death=mock_record)}):
            dead = _record_deaths(True, True, 100, 200)
        self.assertEqual(dead, [])
        mock_record.assert_not_called()

    @patch("caretaker_autorecover.REPO", Path("/fake/repo"))
    def test_import_failure_returns_empty(self):
        """If process_death_clock is not importable, return empty list."""
        with patch.dict(sys.modules, {"process_death_clock": None}):
            dead = _record_deaths(False, False, 100, 200)
        self.assertEqual(dead, [])


class TestRestart(unittest.TestCase):
    """Tests for _restart — running run_both.sh."""

    @patch("subprocess.run")
    def test_successful_restart(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="writer pid 1234: up\nbatch  pid 1235: up\n",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tools_dir = Path(tmpdir) / "tools"
            tools_dir.mkdir()
            (tools_dir / "run_both.sh").write_text("#!/bin/bash\necho ok")
            ok, output = _restart(Path(tmpdir))
        self.assertTrue(ok)
        self.assertIn("up", output)

    @patch("subprocess.run")
    def test_failed_restart(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="error: cannot start",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tools_dir = Path(tmpdir) / "tools"
            tools_dir.mkdir()
            (tools_dir / "run_both.sh").write_text("#!/bin/bash\nexit 1")
            ok, output = _restart(Path(tmpdir))
        self.assertFalse(ok)

    def test_missing_run_both(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ok, output = _restart(Path(tmpdir))
        self.assertFalse(ok)
        self.assertIn("not found", output)

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired("bash", 30))
    def test_timeout(self, mock_run):
        with tempfile.TemporaryDirectory() as tmpdir:
            tools_dir = Path(tmpdir) / "tools"
            tools_dir.mkdir()
            (tools_dir / "run_both.sh").write_text("#!/bin/bash\nsleep 999")
            ok, output = _restart(Path(tmpdir), timeout=1)
        self.assertFalse(ok)
        self.assertIn("timed out", output)


class TestAutorecover(unittest.TestCase):
    """Integration tests for the full autorecover() flow."""

    def test_probe_only_both_alive(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as wf, \
             tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as bf:
            wf.write(str(os.getpid())); wf.flush()
            bf.write(str(os.getpid())); bf.flush()
            report = autorecover(
                probe_only=True,
                writer_pid_path=Path(wf.name),
                batch_pid_path=Path(bf.name),
            )
            self.assertTrue(report.writer_alive)
            self.assertTrue(report.batch_alive)
            self.assertFalse(report.restart_attempted)
            self.assertFalse(report.push_attempted)
        os.unlink(wf.name)
        os.unlink(bf.name)

    def test_probe_only_dead_returns_dead(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as wf, \
             tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as bf:
            wf.write("99999999"); wf.flush()
            bf.write("99999998"); bf.flush()
            report = autorecover(
                probe_only=True,
                writer_pid_path=Path(wf.name),
                batch_pid_path=Path(bf.name),
            )
            self.assertFalse(report.writer_alive)
            self.assertFalse(report.batch_alive)
            self.assertFalse(report.restart_attempted)
        os.unlink(wf.name)
        os.unlink(bf.name)

    @patch("caretaker_autorecover._recover_push", return_value={"ok": True, "steps": []})
    @patch("caretaker_autorecover._restart", return_value=(True, "ok"))
    @patch("caretaker_autorecover._record_deaths", return_value=["writer", "batch"])
    @patch("caretaker_autorecover.probe")
    def test_full_recovery_dead_to_alive(self, mock_probe, mock_deaths, mock_restart, mock_push):
        # first call: dead; second call (after restart): alive
        mock_probe.side_effect = [
            {"writer_alive": False, "batch_alive": False, "writer_pid": 100, "batch_pid": 200, "batch_alive_val": False},
            {"writer_alive": True, "batch_alive": True, "writer_pid": 300, "batch_pid": 400, "batch_alive_val": True},
        ]
        report = autorecover()
        self.assertTrue(report.recovered)
        self.assertTrue(report.restart_attempted)
        self.assertTrue(report.restart_ok)
        self.assertEqual(report.deaths_recorded, ["writer", "batch"])
        self.assertTrue(report.push_attempted)
        mock_deaths.assert_called_once()
        mock_restart.assert_called_once()
        mock_push.assert_called_once()

    @patch("caretaker_autorecover._recover_push", return_value={"ok": True, "steps": []})
    @patch("caretaker_autorecover._restart")
    @patch("caretaker_autorecover._record_deaths")
    @patch("caretaker_autorecover.probe")
    def test_already_alive_skips_restart(self, mock_probe, mock_deaths, mock_restart, mock_push):
        mock_probe.return_value = {
            "writer_alive": True, "batch_alive": True,
            "writer_pid": 100, "batch_pid": 200, "batch_alive_val": True,
        }
        report = autorecover()
        self.assertTrue(report.recovered)
        self.assertFalse(report.restart_attempted)
        mock_deaths.assert_not_called()
        mock_restart.assert_not_called()
        # push is still attempted (there might be unpushed commits)
        self.assertTrue(report.push_attempted)

    @patch("caretaker_autorecover._recover_push", return_value={"ok": True, "steps": []})
    @patch("caretaker_autorecover._restart", return_value=(False, "failed to start"))
    @patch("caretaker_autorecover._record_deaths", return_value=["writer"])
    @patch("caretaker_autorecover.probe")
    def test_restart_failure_reports_error(self, mock_probe, mock_deaths, mock_restart, mock_push):
        mock_probe.side_effect = [
            {"writer_alive": False, "batch_alive": True, "writer_pid": 100, "batch_pid": 200, "batch_alive_val": True},
            {"writer_alive": False, "batch_alive": True, "writer_pid": 100, "batch_pid": 200, "batch_alive_val": True},
        ]
        report = autorecover()
        self.assertFalse(report.recovered)
        self.assertTrue(report.restart_attempted)
        self.assertFalse(report.restart_ok)
        self.assertTrue(len(report.errors) > 0)

    @patch("caretaker_autorecover._recover_push", return_value={"ok": False, "error": "network", "steps": []})
    @patch("caretaker_autorecover.probe")
    def test_push_failure_reports_error(self, mock_probe, mock_push):
        mock_probe.return_value = {
            "writer_alive": True, "batch_alive": True,
            "writer_pid": 100, "batch_pid": 200, "batch_alive_val": True,
        }
        report = autorecover()
        self.assertFalse(report.recovered)
        self.assertFalse(report.restart_attempted)
        self.assertTrue(report.push_attempted)
        self.assertTrue(len(report.errors) > 0)
        self.assertIn("push failed", report.errors[0])

    @patch("caretaker_autorecover._recover_push", return_value={"ok": True, "steps": ["[dry-run] would run guarded_push"]})
    def test_dry_run_no_restart(self, mock_push):
        """Dry run with alive processes: no restart, push returns dry-run result."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as wf, \
             tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as bf:
            wf.write(str(os.getpid())); wf.flush()
            bf.write(str(os.getpid())); bf.flush()
            report = autorecover(
                dry_run=True,
                writer_pid_path=Path(wf.name),
                batch_pid_path=Path(bf.name),
            )
            self.assertFalse(report.restart_attempted)
            self.assertTrue(report.push_result["ok"])
        os.unlink(wf.name)
        os.unlink(bf.name)


if __name__ == "__main__":
    unittest.main()
