"""Tests for iamai.uptime_tracker module."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

from iamai.uptime_tracker import (
    _file_age_seconds,
    _is_alive,
    _read_pid,
    format_duration,
    is_fresh,
    process_uptime,
    uptime_summary,
)


class TestReadPid:
    def test_valid_pid(self, tmp_path):
        pf = tmp_path / "test.pid"
        pf.write_text("12345\n", encoding="utf-8")
        assert _read_pid(pf) == 12345

    def test_missing_file(self, tmp_path):
        pf = tmp_path / "missing.pid"
        assert _read_pid(pf) is None

    def test_garbage_content(self, tmp_path):
        pf = tmp_path / "bad.pid"
        pf.write_text("not_a_number", encoding="utf-8")
        assert _read_pid(pf) is None

    def test_empty_file(self, tmp_path):
        pf = tmp_path / "empty.pid"
        pf.write_text("", encoding="utf-8")
        assert _read_pid(pf) is None

    def test_whitespace_pid(self, tmp_path):
        pf = tmp_path / "ws.pid"
        pf.write_text("  999  \n", encoding="utf-8")
        assert _read_pid(pf) == 999


class TestIsAlive:
    def test_current_process_alive(self):
        assert _is_alive(os.getpid()) is True

    def test_dead_pid(self):
        # PID 999999 is extremely unlikely to exist
        assert _is_alive(999999) is False

    def test_pid_zero(self):
        # PID 0 is the kernel scheduler — kill(pid, 0) succeeds on Linux
        # but we don't care about the result, just that it doesn't crash
        _is_alive(0)


class TestFileAgeSeconds:
    def test_existing_file(self, tmp_path):
        pf = tmp_path / "age.pid"
        pf.write_text("1", encoding="utf-8")
        age = _file_age_seconds(pf)
        assert age is not None
        assert 0 <= age < 5  # just created

    def test_missing_file(self, tmp_path):
        pf = tmp_path / "nope.pid"
        assert _file_age_seconds(pf) is None


class TestFormatDuration:
    def test_none(self):
        assert format_duration(None) == "n/a"

    def test_negative(self):
        assert format_duration(-10) == "n/a"

    def test_seconds_only(self):
        assert format_duration(45) == "45s"

    def test_zero(self):
        assert format_duration(0) == "0s"

    def test_minutes_and_seconds(self):
        assert format_duration(90) == "1m30s"

    def test_exact_minutes(self):
        assert format_duration(300) == "5m"

    def test_hours_and_minutes(self):
        assert format_duration(7200) == "2h0m"

    def test_hours_minutes_seconds(self):
        # 2h15m30s → truncated to hours+minutes
        assert format_duration(8130) == "2h15m"

    def test_large_value(self):
        # 100 hours
        assert format_duration(360000) == "100h0m"


class TestProcessUptime:
    def test_no_pid_files(self):
        """When PID files don't exist, everything is None/False."""
        with mock.patch("iamai.uptime_tracker._pid_file") as mock_pf:
            mock_pf.return_value = Path("/tmp/nonexistent-test-pid-file-xyz")
            info = process_uptime("nonexistent-test")
            assert info["writer_alive"] is False
            assert info["batch_alive"] is False
            assert info["writer_pid"] is None
            assert info["batch_pid"] is None
            assert info["writer_uptime_seconds"] is None
            assert info["batch_uptime_seconds"] is None

    def test_all_keys_present(self):
        """Ensure the returned dict has all expected keys."""
        info = process_uptime("qwen")
        expected_keys = {
            "writer_pid", "batch_pid",
            "writer_alive", "batch_alive",
            "writer_uptime_seconds", "batch_uptime_seconds",
        }
        assert set(info.keys()) == expected_keys


class TestUptimeSummary:
    def test_contains_writer_and_batch(self):
        s = uptime_summary("qwen")
        assert "writer:" in s
        assert "batch:" in s

    def test_status_indication(self):
        s = uptime_summary("qwen")
        # Should contain some alive/down indication
        assert any(phrase in s for phrase in ["alive", "DOWN"])


class TestIsFresh:
    def test_no_uptime_means_fresh(self):
        """If we can't read uptime, assume fresh (just restarted or dead)."""
        with mock.patch("iamai.uptime_tracker.process_uptime") as mock_pu:
            mock_pu.return_value = {
                "writer_uptime_seconds": None,
                "writer_alive": False,
                "batch_alive": False,
                "writer_pid": None,
                "batch_pid": None,
                "batch_uptime_seconds": None,
            }
            assert is_fresh("test", threshold_seconds=120) is True

    def test_short_uptime_is_fresh(self):
        with mock.patch("iamai.uptime_tracker.process_uptime") as mock_pu:
            mock_pu.return_value = {
                "writer_uptime_seconds": 30.0,
                "writer_alive": True,
                "batch_alive": True,
                "writer_pid": 100,
                "batch_pid": 101,
                "batch_uptime_seconds": 30.0,
            }
            assert is_fresh("test", threshold_seconds=120) is True

    def test_long_uptime_not_fresh(self):
        with mock.patch("iamai.uptime_tracker.process_uptime") as mock_pu:
            mock_pu.return_value = {
                "writer_uptime_seconds": 3600.0,
                "writer_alive": True,
                "batch_alive": True,
                "writer_pid": 100,
                "batch_pid": 101,
                "batch_uptime_seconds": 3600.0,
            }
            assert is_fresh("test", threshold_seconds=120) is False

    def test_exactly_at_threshold(self):
        with mock.patch("iamai.uptime_tracker.process_uptime") as mock_pu:
            mock_pu.return_value = {
                "writer_uptime_seconds": 120.0,
                "writer_alive": True,
                "batch_alive": True,
                "writer_pid": 100,
                "batch_pid": 101,
                "batch_uptime_seconds": 120.0,
            }
            # uptime == threshold → not fresh (not < threshold)
            assert is_fresh("test", threshold_seconds=120) is False
