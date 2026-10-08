"""Tests for tools/process_uptime.py — process uptime monitoring."""

import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, mock_open

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import process_uptime as pu


# ---------------------------------------------------------------------------
# format_duration
# ---------------------------------------------------------------------------

class TestFormatDuration:
    def test_seconds(self):
        assert pu.format_duration(0) == "0s"
        assert pu.format_duration(45) == "45s"

    def test_minutes(self):
        assert pu.format_duration(90) == "1.5m"
        assert pu.format_duration(300) == "5.0m"

    def test_hours(self):
        assert pu.format_duration(3661) == "1h1m"
        assert pu.format_duration(7200) == "2h0m"

    def test_days(self):
        assert pu.format_duration(90000) == "1d1h"
        assert pu.format_duration(172800) == "2d0h"


# ---------------------------------------------------------------------------
# process_start_time — with mocked /proc
# ---------------------------------------------------------------------------

class TestProcessStartTime:
    def test_missing_proc(self, tmp_path):
        """Non-existent PID returns None."""
        with patch.object(pu, "Path") as mock_path_cls:
            mock_path_cls.return_value = tmp_path / "nonexistent" / "stat"
            # Actually just call with a PID that doesn't exist
            result = pu.process_start_time(999999999)
            assert result is None

    def test_reads_real_proc(self):
        """If /proc/self/stat exists, we should get a valid start time."""
        pid = os.getpid()
        start = pu.process_start_time(pid)
        if Path(f"/proc/{pid}/stat").exists():
            assert start is not None
            assert isinstance(start, float)
            # Start time should be within the last hour
            assert time.time() - start < 3600
        else:
            # CI without /proc
            assert start is None


# ---------------------------------------------------------------------------
# uptime_seconds
# ---------------------------------------------------------------------------

class TestUptimeSeconds:
    def test_self_uptime(self):
        """Current process should have small positive uptime."""
        pid = os.getpid()
        up = pu.uptime_seconds(pid)
        if Path(f"/proc/{pid}/stat").exists():
            assert up is not None
            assert 0 <= up < 3600
        else:
            assert up is None

    def test_dead_pid(self):
        """Non-existent PID returns None."""
        assert pu.uptime_seconds(999999999) is None


# ---------------------------------------------------------------------------
# check_process
# ---------------------------------------------------------------------------

class TestCheckProcess:
    def test_missing_pidfile(self, tmp_path):
        """No pidfile → not running."""
        with patch.object(pu.writer, "pid_file", return_value=tmp_path / "nope.pid"):
            result = pu.check_process(None, "writer", 60)
        assert result["running"] is False
        assert result["healthy"] is False
        assert result["uptime_str"] == "not running"

    def test_stale_pidfile(self, tmp_path):
        """Pidfile points to dead process → stale."""
        pf = tmp_path / "writer.pid"
        pf.write_text("999999999\n")
        with patch.object(pu.writer, "pid_file", return_value=pf):
            result = pu.check_process(None, "writer", 60)
        assert result["running"] is False
        assert result["healthy"] is False

    def test_healthy_process(self, tmp_path):
        """Mock a running process with sufficient uptime."""
        pf = tmp_path / "writer.pid"
        pf.write_text(str(os.getpid()) + "\n")
        with patch.object(pu.writer, "pid_file", return_value=pf):
            with patch.object(pu, "uptime_seconds", return_value=300.0):
                result = pu.check_process(None, "writer", 60)
        assert result["running"] is True
        assert result["healthy"] is True
        assert result["uptime"] == 300.0

    def test_unhealthy_young_process(self, tmp_path):
        """Mock a running process that is too young."""
        pf = tmp_path / "writer.pid"
        pf.write_text(str(os.getpid()) + "\n")
        with patch.object(pu.writer, "pid_file", return_value=pf):
            with patch.object(pu, "uptime_seconds", return_value=10.0):
                result = pu.check_process(None, "writer", 60)
        assert result["running"] is True
        assert result["healthy"] is False


# ---------------------------------------------------------------------------
# main — integration smoke test
# ---------------------------------------------------------------------------

class TestMain:
    def test_json_output(self, capsys, tmp_path):
        """--json should produce valid JSON."""
        pf_w = tmp_path / "w.pid"
        pf_b = tmp_path / "b.pid"
        pf_w.write_text("999999998\n")
        pf_b.write_text("999999997\n")
        with patch.object(pu.writer, "pid_file", return_value=pf_w), \
             patch.object(pu.writer, "batch_pid_file", return_value=pf_b), \
             patch("sys.argv", ["process_uptime.py", "--json"]):
            rc = pu.main()
        captured = capsys.readouterr()
        import json
        data = json.loads(captured.out)
        assert len(data) == 2
        assert data[0]["role"] == "writer"
        assert data[1]["role"] == "batch"
        assert rc == 1  # stale PIDs → unhealthy → exit 1
