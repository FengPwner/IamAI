"""Tests for iamai.process_uptime."""

import os
import time
from pathlib import Path
from unittest.mock import patch, mock_open

import pytest

from iamai.process_uptime import (
    _read_pid,
    _parse_log_timestamps,
    live_uptime,
    session_from_log,
    uptime_summary,
)


# ---------------------------------------------------------------------------
# _read_pid
# ---------------------------------------------------------------------------

class TestReadPid:
    def test_missing_file(self, tmp_path):
        with patch("iamai.process_uptime._PID_DIR", tmp_path):
            assert _read_pid("test_writer") is None

    def test_valid_pid(self, tmp_path):
        pf = tmp_path / "iamai-writer-test_writer.pid"
        pf.write_text("12345\n")
        with patch("iamai.process_uptime._PID_DIR", tmp_path):
            assert _read_pid("test_writer") == 12345

    def test_invalid_pid_text(self, tmp_path):
        pf = tmp_path / "iamai-writer-test_writer.pid"
        pf.write_text("not_a_number\n")
        with patch("iamai.process_uptime._PID_DIR", tmp_path):
            assert _read_pid("test_writer") is None

    def test_zero_pid(self, tmp_path):
        pf = tmp_path / "iamai-writer-test_writer.pid"
        pf.write_text("0\n")
        with patch("iamai.process_uptime._PID_DIR", tmp_path):
            assert _read_pid("test_writer") is None

    def test_negative_pid(self, tmp_path):
        pf = tmp_path / "iamai-writer-test_writer.pid"
        pf.write_text("-1\n")
        with patch("iamai.process_uptime._PID_DIR", tmp_path):
            assert _read_pid("test_writer") is None

    def test_empty_file(self, tmp_path):
        pf = tmp_path / "iamai-writer-test_writer.pid"
        pf.write_text("")
        with patch("iamai.process_uptime._PID_DIR", tmp_path):
            assert _read_pid("test_writer") is None


# ---------------------------------------------------------------------------
# _parse_log_timestamps
# ---------------------------------------------------------------------------

class TestParseLogTimestamps:
    def test_missing_log(self, tmp_path):
        result = _parse_log_timestamps(tmp_path / "nonexistent.log")
        assert result == []

    def test_empty_log(self, tmp_path):
        log = tmp_path / "empty.log"
        log.write_text("")
        assert _parse_log_timestamps(log) == []

    def test_valid_lines(self, tmp_path):
        log = tmp_path / "test.log"
        log.write_text(
            "2026-10-15 16:00:03 [qwen] stroke 1\n"
            "some noise line\n"
            "2026-10-15 16:00:18 [qwen] stroke 2\n"
            "2026-10-15 17:00:00 [qwen] stroke 240\n"
        )
        ts = _parse_log_timestamps(log)
        assert len(ts) == 3
        # first < second < third
        assert ts[0] < ts[1] < ts[2]

    def test_no_timestamped_lines(self, tmp_path):
        log = tmp_path / "noise.log"
        log.write_text("just some noise\nanother line\n")
        assert _parse_log_timestamps(log) == []

    def test_malformed_timestamps(self, tmp_path):
        log = tmp_path / "bad.log"
        log.write_text(
            "2026-13-45 99:99:99 [qwen] bad date\n"
            "2026-10-15 16:00:03 [qwen] good line\n"
        )
        ts = _parse_log_timestamps(log)
        assert len(ts) == 1


# ---------------------------------------------------------------------------
# live_uptime
# ---------------------------------------------------------------------------

class TestLiveUptime:
    def test_no_pid_file(self, tmp_path):
        with patch("iamai.process_uptime._PID_DIR", tmp_path):
            assert live_uptime(writer_id="ghost") is None

    def test_dead_process(self, tmp_path):
        pf = tmp_path / "iamai-writer-dead.pid"
        pf.write_text("99999999\n")
        with patch("iamai.process_uptime._PID_DIR", tmp_path):
            # process 99999999 almost certainly doesn't exist
            result = live_uptime(writer_id="dead")
            # should be None (either /proc missing or kill(0) fails)
            assert result is None

    def test_explicit_pid_none(self):
        # pid=None and no pid file → None
        with patch("iamai.process_uptime._read_pid", return_value=None):
            assert live_uptime(pid=None, writer_id="x") is None

    def test_current_process(self):
        # our own pid is alive — start time should be parseable on Linux
        my_pid = os.getpid()
        result = live_uptime(pid=my_pid)
        if Path("/proc").exists():
            # on Linux with /proc, should get a positive uptime
            assert result is not None
            assert result >= 0
        else:
            # non-Linux — None is acceptable
            assert result is None

    def test_returns_float(self):
        my_pid = os.getpid()
        result = live_uptime(pid=my_pid)
        if result is not None:
            assert isinstance(result, float)


# ---------------------------------------------------------------------------
# session_from_log
# ---------------------------------------------------------------------------

class TestSessionFromLog:
    def test_missing_log(self, tmp_path):
        with patch("iamai.process_uptime._LOG_DIR", tmp_path):
            result = session_from_log(writer_id="ghost")
            assert result is None

    def test_empty_log(self, tmp_path):
        log = tmp_path / "iamai-ghost.log"
        log.write_text("")
        with patch("iamai.process_uptime._LOG_DIR", tmp_path):
            assert session_from_log(writer_id="ghost") is None

    def test_single_line(self, tmp_path):
        log = tmp_path / "iamai-single.log"
        log.write_text("2026-10-15 16:00:03 [qwen] stroke 1\n")
        with patch("iamai.process_uptime._LOG_DIR", tmp_path):
            result = session_from_log(writer_id="single")
            assert result is not None
            assert result["seconds"] == 0.0
            assert result["lines"] == 1

    def test_multi_line_session(self, tmp_path):
        log = tmp_path / "iamai-multi.log"
        log.write_text(
            "2026-10-15 16:00:00 [qwen] stroke 1\n"
            "2026-10-15 16:30:00 [qwen] stroke 120\n"
            "2026-10-15 17:00:00 [qwen] stroke 240\n"
        )
        with patch("iamai.process_uptime._LOG_DIR", tmp_path):
            result = session_from_log(writer_id="multi")
            assert result is not None
            assert result["seconds"] == 3600.0
            assert result["lines"] == 3
            assert result["first"] == "2026-10-15 16:00:00"
            assert result["last"] == "2026-10-15 17:00:00"

    def test_explicit_path(self, tmp_path):
        log = tmp_path / "custom.log"
        log.write_text(
            "2026-10-15 10:00:00 [qwen] start\n"
            "2026-10-15 11:00:00 [qwen] end\n"
        )
        result = session_from_log(log_path=log)
        assert result is not None
        assert result["seconds"] == 3600.0

    def test_no_timestamped_lines(self, tmp_path):
        log = tmp_path / "iamai-noise.log"
        log.write_text("just noise\n")
        with patch("iamai.process_uptime._LOG_DIR", tmp_path):
            assert session_from_log(writer_id="noise") is None

    def test_result_keys(self, tmp_path):
        log = tmp_path / "iamai-keys.log"
        log.write_text("2026-10-15 12:00:00 [qwen] hi\n")
        with patch("iamai.process_uptime._LOG_DIR", tmp_path):
            result = session_from_log(writer_id="keys")
            assert set(result.keys()) == {"first", "last", "seconds", "lines"}


# ---------------------------------------------------------------------------
# uptime_summary
# ---------------------------------------------------------------------------

class TestUptimeSummary:
    def test_both_alive_and_log(self):
        with patch("iamai.process_uptime.live_uptime", return_value=423.0), \
             patch("iamai.process_uptime.session_from_log", return_value={
                 "first": "2026-10-15 16:00:03",
                 "last": "2026-10-15 17:59:58",
                 "seconds": 7195.0,
                 "lines": 480,
             }):
            result = uptime_summary("qwen")
            assert "alive 423s" in result
            assert "7195s" in result
            assert "480 lines" in result

    def test_alive_no_log(self):
        with patch("iamai.process_uptime.live_uptime", return_value=60.0), \
             patch("iamai.process_uptime.session_from_log", return_value=None):
            result = uptime_summary("qwen")
            assert "alive 60s" in result
            assert "no log data" in result

    def test_dead_with_log(self):
        with patch("iamai.process_uptime.live_uptime", return_value=None), \
             patch("iamai.process_uptime.session_from_log", return_value={
                 "first": "2026-10-15 16:00:03",
                 "last": "2026-10-15 17:00:00",
                 "seconds": 3600.0,
                 "lines": 240,
             }):
            result = uptime_summary("qwen")
            assert "dead" in result
            assert "3600s" in result
            assert "240 lines" in result

    def test_no_data(self):
        with patch("iamai.process_uptime.live_uptime", return_value=None), \
             patch("iamai.process_uptime.session_from_log", return_value=None):
            result = uptime_summary("qwen")
            assert "no data" in result

    def test_includes_writer_id(self):
        with patch("iamai.process_uptime.live_uptime", return_value=None), \
             patch("iamai.process_uptime.session_from_log", return_value=None):
            result = uptime_summary("mywriter")
            assert "mywriter" in result
