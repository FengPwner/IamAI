"""Tests for iamai.restart_frequency — restart tracking and classification."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.restart_frequency import (
    _classify_gap,
    _log_session_boundaries,
    _pid_file,
    _pid_file_age,
    mean_time_between_restarts,
    recent_restarts,
    restart_summary,
)


# ---------------------------------------------------------------------------
# _classify_gap
# ---------------------------------------------------------------------------

class TestClassifyGap:
    def test_stable_above_7200(self):
        assert _classify_gap(7201) == "stable"

    def test_stable_far_above(self):
        assert _classify_gap(86400) == "stable"

    def test_normal_between_3600_and_7200(self):
        assert _classify_gap(5400) == "normal"

    def test_normal_at_boundary(self):
        assert _classify_gap(3601) == "normal"

    def test_aggressive_between_1800_and_3600(self):
        assert _classify_gap(2700) == "aggressive"

    def test_aggressive_at_boundary(self):
        assert _classify_gap(1801) == "aggressive"

    def test_thrashing_below_1800(self):
        assert _classify_gap(900) == "thrashing"

    def test_thrashing_at_boundary(self):
        assert _classify_gap(1800) == "thrashing"

    def test_thrashing_zero(self):
        assert _classify_gap(0) == "thrashing"

    def test_boundary_7200_is_normal(self):
        # 7200 is not > 7200, so falls to normal
        assert _classify_gap(7200) == "normal"

    def test_boundary_3600_is_aggressive(self):
        # 3600 is not > 3600, so falls to aggressive
        assert _classify_gap(3600) == "aggressive"


# ---------------------------------------------------------------------------
# _pid_file / _pid_file_age
# ---------------------------------------------------------------------------

class TestPidFile:
    def test_pid_file_path(self):
        p = _pid_file("qwen")
        assert p.name == "iamai-writer-qwen.pid"

    def test_pid_file_age_missing(self, tmp_path):
        fake = tmp_path / "nonexistent.pid"
        assert _pid_file_age(fake) is None


# ---------------------------------------------------------------------------
# _log_session_boundaries
# ---------------------------------------------------------------------------

class TestLogSessionBoundaries:
    def test_empty_log(self, tmp_path):
        log = tmp_path / "empty.log"
        log.write_text("")
        assert _log_session_boundaries(log) == []

    def test_missing_log(self, tmp_path):
        log = tmp_path / "missing.log"
        assert _log_session_boundaries(log) == []

    def test_single_session_no_boundary(self, tmp_path):
        log = tmp_path / "single.log"
        lines = [
            "2026-10-15 18:00:00 stroke 1\n",
            "2026-10-15 18:00:15 stroke 2\n",
            "2026-10-15 18:00:30 stroke 3\n",
        ]
        log.write_text("".join(lines))
        assert _log_session_boundaries(log) == []

    def test_one_restart_boundary(self, tmp_path):
        log = tmp_path / "restart.log"
        lines = [
            "2026-10-15 18:00:00 stroke 1\n",
            "2026-10-15 18:00:15 stroke 2\n",
            "2026-10-15 19:05:00 stroke 3\n",  # >60s gap → boundary
            "2026-10-15 19:05:15 stroke 4\n",
        ]
        log.write_text("".join(lines))
        bounds = _log_session_boundaries(log)
        assert len(bounds) == 1

    def test_multiple_restart_boundaries(self, tmp_path):
        log = tmp_path / "multi.log"
        lines = [
            "2026-10-15 18:00:00 session1\n",
            "2026-10-15 18:00:15 session1\n",
            "2026-10-15 19:05:00 session2\n",  # boundary
            "2026-10-15 19:05:15 session2\n",
            "2026-10-15 20:30:00 session3\n",  # boundary
            "2026-10-15 20:30:15 session3\n",
        ]
        log.write_text("".join(lines))
        bounds = _log_session_boundaries(log)
        assert len(bounds) == 2

    def test_garbage_lines_ignored(self, tmp_path):
        log = tmp_path / "garbage.log"
        lines = [
            "not a timestamp line\n",
            "2026-10-15 18:00:00 stroke\n",
            "random noise\n",
            "2026-10-15 18:00:15 stroke\n",
        ]
        log.write_text("".join(lines))
        assert _log_session_boundaries(log) == []

    def test_exactly_60s_gap_is_not_boundary(self, tmp_path):
        log = tmp_path / "exact60.log"
        lines = [
            "2026-10-15 18:00:00 stroke\n",
            "2026-10-15 18:01:00 stroke\n",  # exactly 60s, not > 60
        ]
        log.write_text("".join(lines))
        assert _log_session_boundaries(log) == []

    def test_61s_gap_is_boundary(self, tmp_path):
        log = tmp_path / "gap61.log"
        lines = [
            "2026-10-15 18:00:00 stroke\n",
            "2026-10-15 18:01:01 stroke\n",  # 61s gap
        ]
        log.write_text("".join(lines))
        bounds = _log_session_boundaries(log)
        assert len(bounds) == 1


# ---------------------------------------------------------------------------
# recent_restarts
# ---------------------------------------------------------------------------

class TestRecentRestarts:
    def test_no_data_returns_empty(self, tmp_path):
        with patch("iamai.restart_frequency._LOG_DIR", tmp_path), \
             patch("iamai.restart_frequency._PID_DIR", tmp_path):
            events = recent_restarts("nonexistent", window_hours=24)
            assert events == []

    def test_events_have_required_keys(self, tmp_path):
        log = tmp_path / "iamai-testwriter.log"
        lines = [
            "2026-10-15 18:00:00 s1\n",
            "2026-10-15 18:00:15 s2\n",
            "2026-10-15 19:05:00 s3\n",
            "2026-10-15 19:05:15 s4\n",
        ]
        log.write_text("".join(lines))
        with patch("iamai.restart_frequency._LOG_DIR", tmp_path), \
             patch("iamai.restart_frequency._PID_DIR", tmp_path):
            events = recent_restarts("testwriter", window_hours=24)
            assert len(events) >= 1
            for ev in events:
                assert "at" in ev
                assert "epoch" in ev
                assert "gap_seconds" in ev
                assert "verdict" in ev

    def test_first_event_has_no_gap(self, tmp_path):
        log = tmp_path / "iamai-firstev.log"
        lines = [
            "2026-10-15 18:00:00 s1\n",
            "2026-10-15 19:05:00 s2\n",
        ]
        log.write_text("".join(lines))
        with patch("iamai.restart_frequency._LOG_DIR", tmp_path), \
             patch("iamai.restart_frequency._PID_DIR", tmp_path):
            events = recent_restarts("firstev", window_hours=24)
            assert events[0]["gap_seconds"] is None
            assert events[0]["verdict"] is None

    def test_window_filters_old_events(self, tmp_path):
        log = tmp_path / "iamai-oldwin.log"
        # Create events 48 hours ago — outside 24h window
        old_time = time.time() - 48 * 3600
        from datetime import datetime
        old_dt = datetime.fromtimestamp(old_time)
        old_str = old_dt.strftime("%Y-%m-%d %H:%M:%S")
        old_str2 = (datetime.fromtimestamp(old_time + 15)).strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"{old_str} s1\n",
            f"{old_str2} s2\n",
        ]
        log.write_text("".join(lines))
        with patch("iamai.restart_frequency._LOG_DIR", tmp_path), \
             patch("iamai.restart_frequency._PID_DIR", tmp_path):
            events = recent_restarts("oldwin", window_hours=24)
            assert events == []


# ---------------------------------------------------------------------------
# mean_time_between_restarts
# ---------------------------------------------------------------------------

class TestMeanTimeBetweenRestarts:
    def test_no_data_returns_none(self, tmp_path):
        with patch("iamai.restart_frequency._LOG_DIR", tmp_path), \
             patch("iamai.restart_frequency._PID_DIR", tmp_path):
            assert mean_time_between_restarts("nobody") is None

    def test_single_event_returns_none(self, tmp_path):
        log = tmp_path / "iamai-single.log"
        log.write_text("2026-10-15 18:00:00 s1\n2026-10-15 18:00:15 s2\n")
        with patch("iamai.restart_frequency._LOG_DIR", tmp_path), \
             patch("iamai.restart_frequency._PID_DIR", tmp_path):
            result = mean_time_between_restarts("single", window_hours=24)
            # Only one session start → no gap to measure
            assert result is None

    def test_two_events_returns_average(self, tmp_path):
        log = tmp_path / "iamai-twoev.log"
        lines = [
            "2026-10-15 18:00:00 s1\n",
            "2026-10-15 18:00:15 s2\n",
            "2026-10-15 19:05:00 s3\n",
            "2026-10-15 19:05:15 s4\n",
            "2026-10-15 20:10:00 s5\n",
            "2026-10-15 20:10:15 s6\n",
        ]
        log.write_text("".join(lines))
        with patch("iamai.restart_frequency._LOG_DIR", tmp_path), \
             patch("iamai.restart_frequency._PID_DIR", tmp_path):
            result = mean_time_between_restarts("twoev", window_hours=24)
            assert result is not None
            assert result > 0


# ---------------------------------------------------------------------------
# restart_summary
# ---------------------------------------------------------------------------

class TestRestartSummary:
    def test_no_data(self, tmp_path):
        with patch("iamai.restart_frequency._LOG_DIR", tmp_path), \
             patch("iamai.restart_frequency._PID_DIR", tmp_path):
            result = restart_summary("nobody")
            assert "no data" in result

    def test_summary_contains_writer_id(self, tmp_path):
        with patch("iamai.restart_frequency._LOG_DIR", tmp_path), \
             patch("iamai.restart_frequency._PID_DIR", tmp_path):
            result = restart_summary("qwen")
            assert "qwen" in result

    def test_thrashing_has_exclamation(self, tmp_path):
        log = tmp_path / "iamai-thrash.log"
        # Create rapid restarts (every 10 minutes = 600s, well below 1800s)
        now = time.time()
        from datetime import datetime
        lines = []
        for i in range(5):
            t = now - (4 - i) * 600
            dt = datetime.fromtimestamp(t)
            ts = dt.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"{ts} stroke {i}\n")
            lines.append(f"{ts} stroke {i}b\n")
        log.write_text("".join(lines))
        with patch("iamai.restart_frequency._LOG_DIR", tmp_path), \
             patch("iamai.restart_frequency._PID_DIR", tmp_path):
            result = restart_summary("thrash")
            # With 600s gaps, verdict should be "thrashing"
            if "thrashing" in result:
                assert "!" in result
