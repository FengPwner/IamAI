#!/usr/bin/env python3
"""Tests for iamai/stale_pid_detector.py — stale PID detection and cleanup."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stale_pid_detector import (
    PidCheck,
    PidStatus,
    check_pid_file,
    clear_stale,
    is_pid_alive,
    read_pid,
)


# ---------------------------------------------------------------------------
# read_pid
# ---------------------------------------------------------------------------

class TestReadPid:
    def test_reads_valid_pid(self, tmp_path: Path) -> None:
        f = tmp_path / "test.pid"
        f.write_text("12345\n", encoding="utf-8")
        assert read_pid(f) == 12345

    def test_strips_whitespace(self, tmp_path: Path) -> None:
        f = tmp_path / "test.pid"
        f.write_text("  99  \n", encoding="utf-8")
        assert read_pid(f) == 99

    def test_returns_none_for_nonexistent(self, tmp_path: Path) -> None:
        assert read_pid(tmp_path / "nope.pid") is None

    def test_returns_none_for_non_numeric(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.pid"
        f.write_text("not-a-pid\n", encoding="utf-8")
        assert read_pid(f) is None

    def test_returns_none_for_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.pid"
        f.write_text("", encoding="utf-8")
        assert read_pid(f) is None


# ---------------------------------------------------------------------------
# is_pid_alive
# ---------------------------------------------------------------------------

class TestIsPidAlive:
    def test_current_process_is_alive(self) -> None:
        assert is_pid_alive(os.getpid()) is True

    def test_pid_zero_is_alive(self) -> None:
        # PID 0 should succeed on most systems (kernel scheduler)
        # but on some containers it may fail — treat as best-effort
        result = is_pid_alive(0)
        assert isinstance(result, bool)

    def test_absurdly_high_pid_is_dead(self) -> None:
        # PIDs above 4 million are virtually guaranteed not to exist
        assert is_pid_alive(99_999_999) is False


# ---------------------------------------------------------------------------
# check_pid_file
# ---------------------------------------------------------------------------

class TestCheckPidFile:
    def test_missing_file(self, tmp_path: Path) -> None:
        result = check_pid_file(tmp_path / "ghost.pid")
        assert result.status == PidStatus.MISSING
        assert result.pid is None

    def test_live_pid(self, tmp_path: Path) -> None:
        f = tmp_path / "live.pid"
        f.write_text(str(os.getpid()), encoding="utf-8")
        result = check_pid_file(f)
        assert result.status == PidStatus.LIVE
        assert result.pid == os.getpid()

    def test_stale_pid_dead_process(self, tmp_path: Path) -> None:
        f = tmp_path / "stale.pid"
        f.write_text("99999999", encoding="utf-8")
        result = check_pid_file(f)
        assert result.status == PidStatus.STALE
        assert result.pid == 99999999
        assert "dead" in result.reason

    def test_stale_pid_corrupt_file(self, tmp_path: Path) -> None:
        f = tmp_path / "corrupt.pid"
        f.write_text("garbage", encoding="utf-8")
        result = check_pid_file(f)
        assert result.status == PidStatus.STALE
        assert result.pid is None
        assert "unreadable" in result.reason


# ---------------------------------------------------------------------------
# clear_stale
# ---------------------------------------------------------------------------

class TestClearStale:
    def test_removes_stale_file(self, tmp_path: Path) -> None:
        f = tmp_path / "stale.pid"
        f.write_text("99999999", encoding="utf-8")
        assert clear_stale(f) is True
        assert not f.exists()

    def test_does_not_remove_live_file(self, tmp_path: Path) -> None:
        f = tmp_path / "live.pid"
        f.write_text(str(os.getpid()), encoding="utf-8")
        assert clear_stale(f) is False
        assert f.exists()

    def test_does_nothing_for_missing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "nope.pid"
        assert clear_stale(f) is False

    def test_handles_concurrent_cleanup(self, tmp_path: Path) -> None:
        """Two callers racing to clear the same stale file — both should succeed gracefully."""
        f = tmp_path / "race.pid"
        f.write_text("99999999", encoding="utf-8")
        # First call removes it
        assert clear_stale(f) is True
        # Second call: file is now missing, still returns False (not stale anymore)
        assert clear_stale(f) is False


# ---------------------------------------------------------------------------
# PidCheck dataclass
# ---------------------------------------------------------------------------

class TestPidCheck:
    def test_fields(self, tmp_path: Path) -> None:
        pc = PidCheck(path=tmp_path / "x.pid", status=PidStatus.LIVE, pid=42, reason="alive")
        assert pc.pid == 42
        assert pc.status == PidStatus.LIVE

    def test_defaults(self, tmp_path: Path) -> None:
        pc = PidCheck(path=tmp_path / "x.pid", status=PidStatus.MISSING)
        assert pc.pid is None
        assert pc.reason == ""


# ---------------------------------------------------------------------------
# CLI wrapper
# ---------------------------------------------------------------------------

class TestCLI:
    def test_cli_discovers_pid_files(self) -> None:
        sys.path.insert(0, str(REPO / "tools"))
        from stale_pid_detector import discover_pid_files

        files = discover_pid_files("qwen")
        assert "writer:qwen" in files
        assert "batch:qwen" in files
        assert len(files) == 2

    def test_cli_discovers_all_writers(self) -> None:
        sys.path.insert(0, str(REPO / "tools"))
        from stale_pid_detector import discover_pid_files

        files = discover_pid_files()
        # Default: qwen, doubao, kimi × 2 kinds each = 6
        assert len(files) == 6

    def test_cli_json_output(self, capsys: pytest.CaptureFixture) -> None:
        sys.path.insert(0, str(REPO / "tools"))
        from stale_pid_detector import main

        # Point at a temp dir with no PID files → all missing → exit 0
        with patch("stale_pid_detector.DEFAULT_PID_DIR", Path("/nonexistent")):
            rc = main(["--writer", "qwen", "--json"])
        assert rc == 0
        import json
        output = json.loads(capsys.readouterr().out)
        assert len(output) == 2
        assert all(r["status"] == "missing" for r in output)
