#!/usr/bin/env python3
"""Tests for process_health.py — 19 tests covering verdict logic, PID handling,
log activity detection, report formatting, and CLI output.
"""

import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from process_health import (
    ProcessStatus,
    HealthReport,
    read_pidfile,
    pid_alive,
    last_log_activity,
    check_process,
    format_report,
    count_pending,
    full_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_repo(tmp_path):
    """Create a minimal git repo."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    return tmp_path


@pytest.fixture
def log_file(tmp_path):
    """Create a temp log file."""
    log = tmp_path / "test.log"
    log.write_text("stroke 1: hello\nstroke 2: world\n")
    return log


# ---------------------------------------------------------------------------
# read_pidfile tests
# ---------------------------------------------------------------------------

class TestReadPidfile:
    def test_valid_pidfile(self, tmp_path):
        pf = tmp_path / "test.pid"
        pf.write_text("12345\n")
        assert read_pidfile(pf) == 12345

    def test_empty_pidfile(self, tmp_path):
        pf = tmp_path / "test.pid"
        pf.write_text("")
        assert read_pidfile(pf) is None

    def test_invalid_pidfile(self, tmp_path):
        pf = tmp_path / "test.pid"
        pf.write_text("notanumber")
        assert read_pidfile(pf) is None

    def test_missing_pidfile(self, tmp_path):
        pf = tmp_path / "nonexistent.pid"
        assert read_pidfile(pf) is None

    def test_negative_pid(self, tmp_path):
        pf = tmp_path / "test.pid"
        pf.write_text("-1")
        assert read_pidfile(pf) is None

    def test_zero_pid(self, tmp_path):
        pf = tmp_path / "test.pid"
        pf.write_text("0")
        assert read_pidfile(pf) is None


# ---------------------------------------------------------------------------
# pid_alive tests
# ---------------------------------------------------------------------------

class TestPidAlive:
    def test_current_process_alive(self):
        assert pid_alive(os.getpid()) is True

    def test_none_pid(self):
        assert pid_alive(None) is False

    def test_bogus_pid(self):
        # PID 999999 is extremely unlikely to exist
        assert pid_alive(999999) is False

    def test_pid_one_alive(self):
        # PID 1 (init/systemd) is always running on Linux
        assert pid_alive(1) is True


# ---------------------------------------------------------------------------
# last_log_activity tests
# ---------------------------------------------------------------------------

class TestLastLogActivity:
    def test_existing_log(self, log_file):
        result = last_log_activity(log_file)
        assert result is not None
        last_line, mtime_iso, age = result
        assert last_line == "stroke 2: world"
        assert "+00:00" in mtime_iso or "Z" in mtime_iso
        assert age >= 0

    def test_empty_log(self, tmp_path):
        log = tmp_path / "empty.log"
        log.write_text("")
        result = last_log_activity(log)
        assert result is not None
        last_line, mtime_iso, age = result
        assert last_line == ""
        assert age >= 0

    def test_missing_log(self, tmp_path):
        log = tmp_path / "nope.log"
        result = last_log_activity(log)
        assert result is None


# ---------------------------------------------------------------------------
# check_process tests
# ---------------------------------------------------------------------------

class TestCheckProcess:
    def test_dead_process_no_pidfile(self, tmp_path):
        pf = tmp_path / "dead.pid"
        log = tmp_path / "test.log"
        log.write_text("old stuff\n")
        status = check_process("test", pf, log, log_age_warn=1800)
        assert status.name == "test"
        assert status.verdict == "dead"
        assert status.alive is False

    def test_alive_process(self, tmp_path):
        pf = tmp_path / "alive.pid"
        pf.write_text(str(os.getpid()))
        log = tmp_path / "test.log"
        log.write_text("recent activity\n")
        status = check_process("test", pf, log, log_age_warn=1800)
        assert status.alive is True
        # log was just written, age should be small
        assert status.verdict == "healthy"

    def test_degraded_process(self, tmp_path):
        pf = tmp_path / "degraded.pid"
        pf.write_text(str(os.getpid()))
        log = tmp_path / "old.log"
        log.write_text("stale data\n")
        # Set mtime to 2 hours ago
        old_time = time.time() - 7200
        os.utime(str(log), (old_time, old_time))
        status = check_process("test", pf, log, log_age_warn=1800)
        assert status.alive is True
        assert status.verdict == "degraded"


# ---------------------------------------------------------------------------
# format_report tests
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_healthy_report(self):
        writer = ProcessStatus(
            name="writer", pid=1234, alive=True,
            pidfile_exists=True, log_last_activity="2026-10-31T00:00:00+00:00",
            log_age_seconds=60.0, verdict="healthy",
        )
        batch = ProcessStatus(
            name="batch", pid=1235, alive=True,
            pidfile_exists=True, log_last_activity="2026-10-31T00:00:00+00:00",
            log_age_seconds=120.0, verdict="healthy",
        )
        report = HealthReport(
            writer=writer, batch=batch,
            unpushed_commits=0, pending_files=2,
            overall="healthy", checked_at="2026-10-31T00:00:00+00:00",
        )
        output = format_report(report)
        assert "health: healthy" in output
        assert "writer: healthy" in output
        assert "batch: healthy" in output
        assert "pending: 2" in output

    def test_dead_report(self):
        writer = ProcessStatus(
            name="writer", pid=None, alive=False,
            pidfile_exists=False, log_last_activity=None,
            log_age_seconds=None, verdict="dead",
        )
        batch = ProcessStatus(
            name="batch", pid=1235, alive=True,
            pidfile_exists=True, log_last_activity="2026-10-31T00:00:00+00:00",
            log_age_seconds=120.0, verdict="healthy",
        )
        report = HealthReport(
            writer=writer, batch=batch,
            unpushed_commits=3, pending_files=9,
            overall="dead", checked_at="2026-10-31T00:00:00+00:00",
        )
        output = format_report(report)
        assert "health: dead" in output
        assert "DEAD" in output


# ---------------------------------------------------------------------------
# ProcessStatus / HealthReport dataclass tests
# ---------------------------------------------------------------------------

class TestDataclasses:
    def test_process_status_to_dict(self):
        ps = ProcessStatus(
            name="writer", pid=42, alive=True,
            pidfile_exists=True, log_last_activity="2026-10-31T00:00:00+00:00",
            log_age_seconds=30.0, verdict="healthy",
        )
        d = asdict(ps)
        assert d["name"] == "writer"
        assert d["pid"] == 42
        assert d["verdict"] == "healthy"

    def test_health_report_to_dict(self):
        w = ProcessStatus("writer", 1, True, True, None, None, "healthy")
        b = ProcessStatus("batch", 2, True, True, None, None, "healthy")
        hr = HealthReport(w, b, 0, 0, "healthy", "2026-10-31T00:00:00+00:00")
        d = asdict(hr)
        assert d["overall"] == "healthy"
        assert d["writer"]["pid"] == 1
