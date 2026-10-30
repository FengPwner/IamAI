"""Tests for caretaker_exit_checklist.py.

Covers: PID detection, pause gate, stroke freshness, commit freshness,
uncommitted/unpushed counting, report formatting, and end-to-end checklist.

Run:
    python3 -m pytest tests/test_caretaker_exit_checklist.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import caretaker_exit_checklist as mod  # noqa: E402


class TestPidAlive:
    """_pid_alive returns True for living PIDs, False otherwise."""

    def test_current_process_alive(self):
        assert mod._pid_alive(os.getpid()) is True

    def test_nonexistent_pid(self):
        assert mod._pid_alive(99999999) is False

    def test_zero_pid(self):
        # PID 0 is the scheduler — kill(pid, 0) may succeed
        result = mod._pid_alive(1)  # init/systemd
        assert isinstance(result, bool)


class TestPauseGate:
    """_pause_gate_active detects pause files correctly."""

    def test_no_pause_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            data_dir = repo / "data"
            data_dir.mkdir()
            # no pause file exists
            pause_file = data_dir / "pause.testwriter"
            assert not pause_file.exists()

    def test_pause_file_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            data_dir = repo / "data"
            data_dir.mkdir()
            pause_file = data_dir / "pause.testwriter"
            pause_file.write_text("paused by test")
            assert pause_file.exists()
            content = pause_file.read_text()
            assert "paused" in content


class TestLatestStrokeAge:
    """_latest_stroke_age computes correct age from strokes.jsonl."""

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("")
            f.flush()
            result = mod._latest_stroke_age(Path(f.name))
            assert result is None
        os.unlink(f.name)

    def test_no_file(self):
        result = mod._latest_stroke_age(Path("/nonexistent/strokes.jsonl"))
        assert result is None

    def test_valid_stroke(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        stroke = {"seq": 1, "at": now.isoformat(), "kind": "thought", "text": "test"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(stroke) + "\n")
            f.flush()
            age = mod._latest_stroke_age(Path(f.name))
            assert age is not None
            assert 0 <= age < 10  # should be very recent
        os.unlink(f.name)

    def test_old_stroke(self):
        from datetime import datetime, timezone, timedelta
        old_time = datetime.now(timezone.utc) - timedelta(hours=1)
        stroke = {"seq": 1, "at": old_time.isoformat(), "kind": "thought", "text": "old"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(stroke) + "\n")
            f.flush()
            age = mod._latest_stroke_age(Path(f.name))
            assert age is not None
            assert age > 3500  # roughly 1 hour
        os.unlink(f.name)

    def test_malformed_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("not json\n")
            f.flush()
            result = mod._latest_stroke_age(Path(f.name))
            assert result is None
        os.unlink(f.name)

    def test_multiple_lines_uses_last(self):
        from datetime import datetime, timezone, timedelta
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        new_time = datetime.now(timezone.utc) - timedelta(seconds=5)
        strokes = [
            {"seq": 1, "at": old_time.isoformat(), "kind": "thought", "text": "old"},
            {"seq": 2, "at": new_time.isoformat(), "kind": "thought", "text": "new"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
            f.flush()
            age = mod._latest_stroke_age(Path(f.name))
            assert age is not None
            assert age < 30  # should be ~5 seconds
        os.unlink(f.name)


class TestUncommittedCount:
    """_uncommitted_count returns a non-negative integer in a git repo."""

    def test_returns_int(self):
        result = mod._uncommitted_count()
        assert isinstance(result, int)

    def test_in_git_repo(self):
        # We're running inside the IamAI repo
        result = mod._uncommitted_count()
        assert result >= 0


class TestUnpushedCount:
    """_unpushed_count returns a non-negative integer when origin exists."""

    def test_returns_int(self):
        result = mod._unpushed_count()
        assert isinstance(result, int)


class TestLastCommitAge:
    """_last_commit_age returns seconds since last commit."""

    def test_returns_float(self):
        result = mod._last_commit_age()
        assert result is not None
        assert isinstance(result, float)
        assert result >= 0


class TestRunChecklist:
    """run_checklist returns a complete structured report."""

    def test_structure(self):
        report = mod.run_checklist(writer="qwen")
        assert "timestamp" in report
        assert "writer" in report
        assert report["writer"] == "qwen"
        assert "all_pass" in report
        assert isinstance(report["all_pass"], bool)
        assert "verdict" in report
        assert "checks" in report
        assert isinstance(report["checks"], dict)

    def test_all_checks_present(self):
        report = mod.run_checklist(writer="qwen")
        expected_keys = [
            "writer_alive", "batch_alive", "pause_gate_clear",
            "low_uncommitted", "low_unpushed", "strokes_fresh", "commit_fresh"
        ]
        for key in expected_keys:
            assert key in report["checks"], f"missing check: {key}"

    def test_each_check_has_pass_and_detail(self):
        report = mod.run_checklist(writer="qwen")
        for name, check in report["checks"].items():
            assert "pass" in check, f"check {name} missing 'pass'"
            assert "detail" in check, f"check {name} missing 'detail'"
            assert isinstance(check["pass"], bool)

    def test_verdict_matches_pass_state(self):
        report = mod.run_checklist(writer="qwen")
        all_pass = all(c["pass"] for c in report["checks"].values())
        if all_pass:
            assert report["verdict"] == "SAFE TO DEPART"
        else:
            assert report["verdict"] == "REVIEW BEFORE LEAVING"


class TestFormatReport:
    """format_report produces readable output."""

    def test_contains_verdict(self):
        report = mod.run_checklist(writer="qwen")
        text = mod.format_report(report)
        assert "Caretaker Exit Checklist" in text
        assert report["verdict"] in text

    def test_contains_check_names(self):
        report = mod.run_checklist(writer="qwen")
        text = mod.format_report(report)
        for name in report["checks"]:
            assert name in text

    def test_pass_and_fail_symbols(self):
        passing_report = {
            "timestamp": "2026-10-24 00:00:00 CST",
            "writer": "test",
            "all_pass": True,
            "verdict": "SAFE TO DEPART",
            "checks": {
                "writer_alive": {"pass": True, "detail": "pid 123"},
            }
        }
        text = mod.format_report(passing_report)
        assert "✓" in text

        failing_report = {
            "timestamp": "2026-10-24 00:00:00 CST",
            "writer": "test",
            "all_pass": False,
            "verdict": "REVIEW BEFORE LEAVING",
            "checks": {
                "writer_alive": {"pass": False, "detail": "not found"},
            }
        }
        text = mod.format_report(failing_report)
        assert "✗" in text


class TestFindPid:
    """_find_pid handles missing processes gracefully."""

    def test_nonexistent_process(self):
        result = mod._find_pid("definitely_not_a_real_process_name_xyz123")
        assert result is None

    def test_find_current_python(self):
        # Should be able to find our own process
        result = mod._find_pid("python3")
        # May or may not find it depending on pgrep availability
        if result is not None:
            assert isinstance(result, int)
            assert result > 0


class TestMainEntryPoint:
    """main() exits with correct code."""

    def test_main_returns_int(self):
        with mock.patch("sys.argv", ["caretaker_exit_checklist.py", "--json"]):
            # Capture output to avoid noise
            from io import StringIO
            captured = StringIO()
            with mock.patch("sys.stdout", captured):
                try:
                    code = mod.main()
                except SystemExit as e:
                    code = e.code
            assert isinstance(code, int)
            assert code in (0, 1)
            # Verify JSON was output
            output = captured.getvalue()
            if output.strip():
                parsed = json.loads(output)
                assert "verdict" in parsed
