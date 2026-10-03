"""Tests for iamai.watchdog: can the repo tell whether its processes are alive?

The heartbeat module reads stroke timestamps to detect a stalled writer.
The watchdog reads pidfiles and git status to detect *why* it stalled —
reclaimed process, hung process, or just a gap between strokes. These
tests pin down the pidfile and git-status arithmetic so the watchdog
never lies about what it sees.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.watchdog import (
    ProcessStatus,
    WatchdogReport,
    _read_pid,
    _pid_alive,
    check_process,
    _count_uncommitted,
    _count_unpushed,
    watchdog,
    as_text,
)


# --- _read_pid: the pidfile contract ------------------------------------


def test_read_pid_returns_none_for_missing_file(tmp_path):
    assert _read_pid(tmp_path / "nonexistent.pid") is None


def test_read_pid_parses_a_clean_pidfile(tmp_path):
    pf = tmp_path / "test.pid"
    pf.write_text("12345\n", encoding="utf-8")
    assert _read_pid(pf) == 12345


def test_read_pid_handles_empty_file(tmp_path):
    pf = tmp_path / "empty.pid"
    pf.write_text("", encoding="utf-8")
    assert _read_pid(pf) is None


def test_read_pid_handles_garbage(tmp_path):
    pf = tmp_path / "bad.pid"
    pf.write_text("not-a-number", encoding="utf-8")
    assert _read_pid(pf) is None


def test_read_pid_strips_whitespace(tmp_path):
    pf = tmp_path / "ws.pid"
    pf.write_text("  999  \n", encoding="utf-8")
    assert _read_pid(pf) == 999


# --- check_process: pidfile + liveness ----------------------------------


def test_check_process_no_pidfile_reports_not_alive(tmp_path):
    status = check_process("writer", tmp_path / "missing.pid")
    assert status.alive is False
    assert status.pid is None
    assert status.stale_pidfile is False


def test_check_process_live_pid_reports_alive(tmp_path):
    pf = tmp_path / "live.pid"
    pf.write_text(str(os.getpid()), encoding="utf-8")  # this process is alive
    status = check_process("writer", pf)
    assert status.alive is True
    assert status.pid == os.getpid()
    assert status.stale_pidfile is False


def test_check_process_dead_pid_is_stale(tmp_path):
    pf = tmp_path / "dead.pid"
    pf.write_text("1", encoding="utf-8")  # PID 1 may or may not be alive
    # Use a PID that is almost certainly not running
    pf.write_text("4194303", encoding="utf-8")  # max PID on most Linux systems
    status = check_process("batch", pf)
    # On the off chance PID 4194303 exists, skip the stale check
    if not status.alive:
        assert status.stale_pidfile is True
        assert status.pid == 4194303


# --- _count_uncommitted / _count_unpushed: git plumbing -----------------


def test_count_uncommitted_outside_a_repo_returns_zero(tmp_path):
    assert _count_uncommitted(tmp_path) == 0


def test_count_uncommitted_in_a_clean_repo_returns_zero(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test"],
        cwd=tmp_path, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True,
    )
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, capture_output=True,
    )
    assert _count_uncommitted(tmp_path) == 0


def test_count_uncommitted_detects_dirty_files(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test"],
        cwd=tmp_path, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True,
    )
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, capture_output=True,
    )
    (tmp_path / "file.txt").write_text("changed", encoding="utf-8")
    assert _count_uncommitted(tmp_path) >= 1


def test_count_unpushed_outside_a_repo_returns_zero(tmp_path):
    assert _count_unpushed(tmp_path) == 0


# --- WatchdogReport: aggregation logic -----------------------------------


def test_report_all_alive_when_every_process_lives(tmp_path):
    pf1 = tmp_path / "iamai-writer-test.pid"
    pf2 = tmp_path / "iamai-batch-test.pid"
    pf1.write_text(str(os.getpid()), encoding="utf-8")
    pf2.write_text(str(os.getpid()), encoding="utf-8")
    report = watchdog(writer_id="test", pid_dir=tmp_path, repo=tmp_path)
    assert all(p.pid is not None for p in report.processes)
    assert report.all_alive is True


def test_report_needs_restart_when_any_process_dead(tmp_path):
    report = WatchdogReport(
        processes=[
            ProcessStatus("writer", pid=1, alive=True, pidfile="w.pid"),
            ProcessStatus("batch", pid=None, alive=False, pidfile="b.pid"),
        ],
        uncommitted_files=0,
        unpushed_commits=0,
    )
    assert report.all_alive is False
    assert report.needs_restart is True


def test_report_no_restart_when_all_alive(tmp_path):
    report = WatchdogReport(
        processes=[
            ProcessStatus("writer", pid=1, alive=True, pidfile="w.pid"),
            ProcessStatus("batch", pid=2, alive=True, pidfile="b.pid"),
        ],
    )
    assert report.all_alive is True
    assert report.needs_restart is False


def test_report_needs_push_when_unpushed_gt_zero():
    report = WatchdogReport(unpushed_commits=3)
    assert report.needs_push is True


def test_report_no_push_needed_when_zero_unpushed():
    report = WatchdogReport(unpushed_commits=0)
    assert report.needs_push is False


def test_as_dict_includes_computed_properties():
    report = WatchdogReport(
        processes=[
            ProcessStatus("writer", pid=1, alive=True, pidfile="w.pid"),
        ],
        uncommitted_files=2,
        unpushed_commits=1,
    )
    d = report.as_dict()
    assert d["all_alive"] is True
    assert d["any_stale_pidfile"] is False
    assert d["uncommitted_files"] == 2


# --- as_text: human-readable rendering -----------------------------------


def test_as_text_says_alive_when_everything_runs():
    report = WatchdogReport(
        processes=[
            ProcessStatus("writer", pid=100, alive=True, pidfile="w.pid"),
            ProcessStatus("batch", pid=200, alive=True, pidfile="b.pid"),
        ],
    )
    text = as_text(report)
    assert "ALIVE" in text
    assert "NEEDS ATTENTION" not in text


def test_as_text_says_needs_attention_when_dead():
    report = WatchdogReport(
        processes=[
            ProcessStatus("writer", pid=None, alive=False, pidfile="w.pid"),
        ],
    )
    text = as_text(report)
    assert "NEEDS ATTENTION" in text
    assert "restart needed" in text


def test_as_text_mentions_push_when_unpushed():
    report = WatchdogReport(unpushed_commits=5)
    text = as_text(report)
    assert "push needed" in text


def test_as_text_shows_stale_pidfile():
    report = WatchdogReport(
        processes=[
            ProcessStatus("writer", pid=999, alive=False, pidfile="w.pid", stale_pidfile=True),
        ],
    )
    text = as_text(report)
    assert "DEAD" in text
    assert "stale" in text


# --- full watchdog integration -------------------------------------------


def test_watchdog_finds_nothing_in_empty_dir(tmp_path):
    report = watchdog(writer_id="nobody", pid_dir=tmp_path, repo=tmp_path)
    assert len(report.processes) == 2
    assert report.processes[0].name == "writer"
    assert report.processes[1].name == "batch"
    assert report.all_alive is False
    assert report.needs_restart is True
