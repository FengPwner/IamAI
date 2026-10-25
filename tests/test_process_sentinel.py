"""Tests for snippets/process_sentinel.py — detect managed process liveness."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from process_sentinel import ProcessSentinel  # noqa: E402


# ---------------------------------------------------------------------------
# PID file reading
# ---------------------------------------------------------------------------


def test_read_pid_from_simple_file(tmp_path):
    pid_file = tmp_path / "test.pid"
    pid_file.write_text("12345\n")
    s = ProcessSentinel(pid_file)
    assert s.read_pid() == 12345


def test_read_pid_with_name_suffix(tmp_path):
    pid_file = tmp_path / "test.pid"
    pid_file.write_text("12345 writer_loop\n")
    s = ProcessSentinel(pid_file)
    assert s.read_pid() == 12345


def test_read_pid_missing_file():
    s = ProcessSentinel("/tmp/definitely_does_not_exist_xyz.pid")
    assert s.read_pid() is None


def test_read_pid_empty_file(tmp_path):
    pid_file = tmp_path / "test.pid"
    pid_file.write_text("")
    s = ProcessSentinel(pid_file)
    assert s.read_pid() is None


def test_read_pid_garbage_file(tmp_path):
    pid_file = tmp_path / "test.pid"
    pid_file.write_text("not-a-number\n")
    s = ProcessSentinel(pid_file)
    assert s.read_pid() is None


def test_read_pid_whitespace_only(tmp_path):
    pid_file = tmp_path / "test.pid"
    pid_file.write_text("   \n  \n")
    s = ProcessSentinel(pid_file)
    assert s.read_pid() is None


# ---------------------------------------------------------------------------
# check() verdicts
# ---------------------------------------------------------------------------


def test_check_no_pid_file():
    s = ProcessSentinel("/tmp/definitely_does_not_exist_xyz.pid")
    assert s.check() == "no_pid"


def test_check_gone_pid(tmp_path):
    pid_file = tmp_path / "test.pid"
    # use a PID that almost certainly doesn't exist
    pid_file.write_text("99999999\n")
    s = ProcessSentinel(pid_file)
    assert s.check() == "gone"


def test_check_self_is_alive(tmp_path):
    """Current process should be detected as alive."""
    pid_file = tmp_path / "self.pid"
    pid_file.write_text(f"{os.getpid()}\n")
    s = ProcessSentinel(pid_file, expected_name="python")
    assert s.check() == "alive"


def test_check_self_alive_no_name(tmp_path):
    """Alive check without expected_name should also work."""
    pid_file = tmp_path / "self.pid"
    pid_file.write_text(f"{os.getpid()}\n")
    s = ProcessSentinel(pid_file)
    assert s.check() == "alive"


def test_check_replaced_pid(tmp_path):
    """PID exists but cmdline doesn't match expected_name."""
    pid_file = tmp_path / "test.pid"
    # PID 1 is always init/systemd — won't match our sentinel name
    pid_file.write_text("1\n")
    s = ProcessSentinel(pid_file, expected_name="definitely_not_init_xyz")
    verdict = s.check()
    # PID 1 should be "replaced" (alive but wrong name)
    assert verdict == "replaced"


# ---------------------------------------------------------------------------
# report()
# ---------------------------------------------------------------------------


def test_report_structure(tmp_path):
    pid_file = tmp_path / "test.pid"
    pid_file.write_text("99999999\n")
    s = ProcessSentinel(pid_file, expected_name="writer_loop")
    r = s.report()
    assert r["pid_file"] == str(pid_file)
    assert r["pid"] == 99999999
    assert r["expected_name"] == "writer_loop"
    assert r["verdict"] == "gone"


def test_report_no_pid():
    s = ProcessSentinel("/tmp/definitely_does_not_exist_xyz.pid")
    r = s.report()
    assert r["pid"] is None
    assert r["verdict"] == "no_pid"


def test_report_self_alive(tmp_path):
    pid_file = tmp_path / "self.pid"
    pid_file.write_text(f"{os.getpid()}\n")
    s = ProcessSentinel(pid_file, expected_name="python")
    r = s.report()
    assert r["pid"] == os.getpid()
    assert r["verdict"] == "alive"
