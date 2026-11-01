"""Tests for iamai.process_liveness — process liveness detector."""

from dataclasses import replace
from unittest.mock import patch, MagicMock

import pytest

from iamai.process_liveness import (
    LivenessReport,
    ProcessInfo,
    _find_process,
    _is_zombie,
    _read_proc_uptime,
    _inspect_process,
    check_liveness,
    liveness_report,
)


# ---------------------------------------------------------------------------
# ProcessInfo / LivenessReport data classes
# ---------------------------------------------------------------------------


class TestProcessInfo:
    def test_defaults(self):
        info = ProcessInfo()
        assert info.alive is False
        assert info.pid is None
        assert info.uptime is None
        assert info.zombie is False
        assert info.cmdline == ""

    def test_alive_process(self):
        info = ProcessInfo(alive=True, pid=1234, uptime=120.5)
        assert info.alive is True
        assert info.pid == 1234
        assert info.uptime == 120.5


class TestLivenessReport:
    def test_to_dict(self):
        report = LivenessReport(
            writer=ProcessInfo(alive=True, pid=100, uptime=60.0),
            batch=ProcessInfo(alive=True, pid=101, uptime=60.0),
            verdict="healthy",
            checked_at=1000.0,
        )
        d = report.to_dict()
        assert d["writer_alive"] is True
        assert d["writer_pid"] == 100
        assert d["batch_alive"] is True
        assert d["batch_pid"] == 101
        assert d["verdict"] == "healthy"
        assert d["checked_at"] == 1000.0

    def test_dead_report(self):
        report = LivenessReport()
        d = report.to_dict()
        assert d["writer_alive"] is False
        assert d["batch_alive"] is False
        assert d["verdict"] == "dead"


# ---------------------------------------------------------------------------
# _find_process()
# ---------------------------------------------------------------------------


class TestFindProcess:
    def test_finds_matching_pid(self):
        ps_output = (
            "USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND\n"
            "root      1234  0.1  0.2  30228 25148 ?        Ss   01:04   0:00 python3 tools/writer_loop.py --writer qwen\n"
            "root      5678  0.0  0.1  22200 16820 ?        Ss   01:04   0:00 python3 tools/commit_batch.py --watch\n"
        )
        with patch("iamai.process_liveness.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ps_output)
            pid = _find_process("writer_loop.py")
        assert pid == 1234

    def test_returns_none_when_not_found(self):
        ps_output = (
            "USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND\n"
            "root         1  0.0  0.3  36052 28864 ?        Ss   00:44   0:00 /usr/bin/python3 /usr/bin/supervisord\n"
        )
        with patch("iamai.process_liveness.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ps_output)
            pid = _find_process("writer_loop.py")
        assert pid is None

    def test_ignores_grep_lines(self):
        ps_output = (
            "USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND\n"
            "root      9999  0.0  0.0   5000  1000 ?        S    01:00   0:00 grep writer_loop.py\n"
        )
        with patch("iamai.process_liveness.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ps_output)
            pid = _find_process("writer_loop.py")
        assert pid is None

    def test_ps_not_found_returns_none(self):
        with patch("iamai.process_liveness.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError
            pid = _find_process("writer_loop.py")
        assert pid is None

    def test_ps_timeout_returns_none(self):
        import subprocess
        with patch("iamai.process_liveness.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="ps", timeout=5)
            pid = _find_process("writer_loop.py")
        assert pid is None

    def test_nonzero_return_returns_none(self):
        with patch("iamai.process_liveness.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            pid = _find_process("writer_loop.py")
        assert pid is None


# ---------------------------------------------------------------------------
# _is_zombie()
# ---------------------------------------------------------------------------


class TestIsZombie:
    def test_zombie_state(self, tmp_path):
        stat_content = "1234 (python3) Z 1 1234 1234 0 -1 4194304 100 0 0 0 10 5 0 0 20 0 1 0 100 30228 6287 18446744073709551615 0 0 0 0 0 0 0 0 0 0 0 0 17 0 0 0 0 0 0"
        stat_file = tmp_path / "stat"
        stat_file.write_text(stat_content)
        with patch("iamai.process_liveness.Path") as mock_path:
            mock_path.return_value = stat_file
            assert _is_zombie(1234) is True

    def test_running_state(self, tmp_path):
        stat_content = "1234 (python3) S 1 1234 1234 0 -1 4194304 100 0 0 0 10 5 0 0 20 0 1 0 100 30228 6287 18446744073709551615 0 0 0 0 0 0 0 0 0 0 0 0 17 0 0 0 0 0 0"
        stat_file = tmp_path / "stat"
        stat_file.write_text(stat_content)
        with patch("iamai.process_liveness.Path") as mock_path:
            mock_path.return_value = stat_file
            assert _is_zombie(1234) is False

    def test_nonexistent_pid(self):
        with patch("iamai.process_liveness.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            assert _is_zombie(99999) is False


# ---------------------------------------------------------------------------
# _inspect_process()
# ---------------------------------------------------------------------------


class TestInspectProcess:
    def test_process_not_found(self):
        with patch("iamai.process_liveness._find_process", return_value=None):
            info = _inspect_process("nonexistent.py")
        assert info.alive is False
        assert info.pid is None

    def test_process_found(self):
        with patch("iamai.process_liveness._find_process", return_value=1234), \
             patch("iamai.process_liveness._is_zombie", return_value=False), \
             patch("iamai.process_liveness._read_proc_uptime", return_value=300.0), \
             patch("iamai.process_liveness.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            mock_path.return_value.read_text.return_value = "python3\x00tools/writer_loop.py\x00--writer\x00qwen\x00"
            info = _inspect_process("writer_loop.py")
        assert info.alive is True
        assert info.pid == 1234
        assert info.uptime == 300.0
        assert info.zombie is False


# ---------------------------------------------------------------------------
# check_liveness()
# ---------------------------------------------------------------------------


class TestCheckLiveness:
    def test_healthy(self):
        writer = ProcessInfo(alive=True, pid=100, uptime=120.0)
        batch = ProcessInfo(alive=True, pid=101, uptime=120.0)
        with patch("iamai.process_liveness._inspect_process", side_effect=[writer, batch]):
            report = check_liveness()
        assert report.verdict == "healthy"
        assert report.writer.alive is True
        assert report.batch.alive is True
        assert report.checked_at > 0

    def test_dead(self):
        dead = ProcessInfo()
        with patch("iamai.process_liveness._inspect_process", return_value=dead):
            report = check_liveness()
        assert report.verdict == "dead"

    def test_degraded_writer_only(self):
        writer = ProcessInfo(alive=True, pid=100, uptime=60.0)
        batch = ProcessInfo()
        with patch("iamai.process_liveness._inspect_process", side_effect=[writer, batch]):
            report = check_liveness()
        assert report.verdict == "degraded"

    def test_degraded_batch_only(self):
        writer = ProcessInfo()
        batch = ProcessInfo(alive=True, pid=101, uptime=60.0)
        with patch("iamai.process_liveness._inspect_process", side_effect=[writer, batch]):
            report = check_liveness()
        assert report.verdict == "degraded"

    def test_zombie_counts_as_dead(self):
        writer = ProcessInfo(alive=True, pid=100, zombie=True)
        batch = ProcessInfo(alive=True, pid=101, zombie=True)
        with patch("iamai.process_liveness._inspect_process", side_effect=[writer, batch]):
            report = check_liveness()
        assert report.verdict == "dead"

    def test_zombie_one_is_degraded(self):
        writer = ProcessInfo(alive=True, pid=100, uptime=60.0)
        batch = ProcessInfo(alive=True, pid=101, zombie=True)
        with patch("iamai.process_liveness._inspect_process", side_effect=[writer, batch]):
            report = check_liveness()
        assert report.verdict == "degraded"

    def test_custom_patterns(self):
        with patch("iamai.process_liveness._inspect_process") as mock_inspect:
            mock_inspect.return_value = ProcessInfo()
            check_liveness(writer_pattern="custom_writer.py", batch_pattern="custom_batch.py")
        assert mock_inspect.call_count == 2
        assert mock_inspect.call_args_list[0].args[0] == "custom_writer.py"
        assert mock_inspect.call_args_list[1].args[0] == "custom_batch.py"


# ---------------------------------------------------------------------------
# liveness_report()
# ---------------------------------------------------------------------------


class TestLivenessReportFormatting:
    def test_healthy_format(self):
        report = LivenessReport(
            writer=ProcessInfo(alive=True, pid=10195, uptime=312.0),
            batch=ProcessInfo(alive=True, pid=10196, uptime=312.0),
            verdict="healthy",
        )
        text = liveness_report(report)
        assert "healthy" in text
        assert "writer: pid 10195" in text
        assert "batch: pid 10196" in text
        assert "up" in text

    def test_dead_format(self):
        report = LivenessReport(verdict="dead")
        text = liveness_report(report)
        assert "dead" in text
        assert "writer: NOT running" in text
        assert "batch: NOT running" in text

    def test_zombie_format(self):
        report = LivenessReport(
            writer=ProcessInfo(alive=True, pid=999, zombie=True),
            batch=ProcessInfo(),
            verdict="degraded",
        )
        text = liveness_report(report)
        assert "ZOMBIE" in text

    def test_uptime_minutes(self):
        report = LivenessReport(
            writer=ProcessInfo(alive=True, pid=100, uptime=1800.0),
            batch=ProcessInfo(alive=True, pid=101, uptime=1800.0),
            verdict="healthy",
        )
        text = liveness_report(report)
        assert "30.0m" in text

    def test_uptime_hours(self):
        report = LivenessReport(
            writer=ProcessInfo(alive=True, pid=100, uptime=7200.0),
            batch=ProcessInfo(alive=True, pid=101, uptime=7200.0),
            verdict="healthy",
        )
        text = liveness_report(report)
        assert "2.0h" in text

    def test_uptime_seconds(self):
        report = LivenessReport(
            writer=ProcessInfo(alive=True, pid=100, uptime=45.0),
            batch=ProcessInfo(alive=True, pid=101, uptime=45.0),
            verdict="healthy",
        )
        text = liveness_report(report)
        assert "45s" in text
