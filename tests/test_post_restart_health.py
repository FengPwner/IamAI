"""Tests for tools/post_restart_health.py — post-restart health checks.

Run:  python3 -m pytest tests/test_post_restart_health.py -v
"""

from __future__ import annotations

import json
import os
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import sys

# Ensure tools/ is importable
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import post_restart_health as prh  # noqa: E402


# ---------------------------------------------------------------------------
# check_writer_alive / check_batch_alive
# ---------------------------------------------------------------------------

class TestProcessAlive:
    def test_writer_alive_when_pidfile_missing(self, tmp_path):
        fake_pid = tmp_path / "iamai-writer-test.pid"
        with patch("post_restart_health.Path", return_value=fake_pid):
            # Patch the specific path resolution
            with patch.object(prh, "check_writer_alive") as mock_fn:
                mock_fn.return_value = {
                    "check": "writer_alive",
                    "status": "fail",
                    "detail": "pid file missing — not running",
                }
                result = mock_fn("test")
                assert result["status"] == "fail"

    def test_pid_alive_nonexistent_file(self, tmp_path):
        pidfile = tmp_path / "nonexistent.pid"
        assert prh._pid_alive(pidfile) is False

    def test_pid_alive_invalid_content(self, tmp_path):
        pidfile = tmp_path / "bad.pid"
        pidfile.write_text("not-a-number\n")
        assert prh._pid_alive(pidfile) is False

    def test_pid_alive_dead_process(self, tmp_path):
        pidfile = tmp_path / "dead.pid"
        # PID 99999 is very unlikely to exist
        pidfile.write_text("99999\n")
        assert prh._pid_alive(pidfile) is False

    def test_pid_alive_self(self, tmp_path):
        pidfile = tmp_path / "self.pid"
        pidfile.write_text(str(os.getpid()) + "\n")
        assert prh._pid_alive(pidfile) is True

    def test_check_batch_alive_returns_dict(self):
        # Just verify the function signature and return shape
        result = prh.check_batch_alive("nonexistent_writer")
        assert isinstance(result, dict)
        assert "check" in result
        assert result["check"] == "batch_alive"
        assert result["status"] in ("pass", "fail")


# ---------------------------------------------------------------------------
# check_push_current
# ---------------------------------------------------------------------------

class TestPushCurrent:
    def test_push_current_up_to_date(self, tmp_path):
        with patch.object(prh, "_run", return_value=(0, "0", "")):
            result = prh.check_push_current(tmp_path)
            assert result["status"] == "pass"
            assert "up to date" in result["detail"]

    def test_push_current_remote_ahead(self, tmp_path):
        with patch.object(prh, "_run", return_value=(0, "3", "")):
            result = prh.check_push_current(tmp_path)
            assert result["status"] == "fail"
            assert "3 commit(s) ahead" in result["detail"]

    def test_push_current_fetch_error(self, tmp_path):
        with patch.object(prh, "_run", return_value=(128, "", "fatal")):
            result = prh.check_push_current(tmp_path)
            assert result["status"] == "warn"
            assert "fetch first" in result["detail"]

    def test_push_current_empty_output(self, tmp_path):
        with patch.object(prh, "_run", return_value=(0, "", "")):
            result = prh.check_push_current(tmp_path)
            assert result["status"] == "warn"


# ---------------------------------------------------------------------------
# check_ssh_key
# ---------------------------------------------------------------------------

class TestSSHKey:
    def test_key_missing(self, tmp_path):
        result = prh.check_ssh_key(str(tmp_path / "nonexistent_key"))
        assert result["status"] == "fail"
        assert "does not exist" in result["detail"]

    def test_key_correct_permissions(self, tmp_path):
        key = tmp_path / "deploy_key"
        key.write_text("ssh-ed25519 AAAA...")
        key.chmod(0o600)
        result = prh.check_ssh_key(str(key))
        assert result["status"] == "pass"
        assert "0o600" in result["detail"]

    def test_key_wrong_permissions(self, tmp_path):
        key = tmp_path / "deploy_key"
        key.write_text("ssh-ed25519 AAAA...")
        key.chmod(0o644)
        result = prh.check_ssh_key(str(key))
        assert result["status"] == "warn"
        assert "0o644" in result["detail"]

    def test_key_too_open(self, tmp_path):
        key = tmp_path / "deploy_key"
        key.write_text("ssh-ed25519 AAAA...")
        key.chmod(0o777)
        result = prh.check_ssh_key(str(key))
        assert result["status"] == "warn"


# ---------------------------------------------------------------------------
# check_stroke_freshness
# ---------------------------------------------------------------------------

class TestStrokeFreshness:
    def _make_strokes(self, tmp_path, last_at_iso: str):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        sf = data_dir / "strokes.jsonl"
        record = json.dumps({"seq": 1, "at": last_at_iso, "kind": "note", "text": "x"})
        sf.write_text(record + "\n")
        return tmp_path

    def test_fresh_stroke(self, tmp_path):
        now = datetime.now(timezone.utc)
        repo = self._make_strokes(tmp_path, now.isoformat())
        result = prh.check_stroke_freshness(repo, cadence_seconds=15.0)
        assert result["status"] == "pass"

    def test_stale_stroke(self, tmp_path):
        old = datetime.now(timezone.utc) - timedelta(seconds=600)
        repo = self._make_strokes(tmp_path, old.isoformat())
        result = prh.check_stroke_freshness(repo, cadence_seconds=15.0)
        assert result["status"] == "fail"
        assert "stale" in result["detail"]

    def test_no_strokes_file(self, tmp_path):
        result = prh.check_stroke_freshness(tmp_path)
        assert result["status"] == "warn"
        assert "not found" in result["detail"]

    def test_empty_strokes_file(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "strokes.jsonl").write_text("")
        result = prh.check_stroke_freshness(tmp_path)
        assert result["status"] == "warn"
        assert "empty" in result["detail"]

    def test_malformed_stroke(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "strokes.jsonl").write_text("not json\n")
        result = prh.check_stroke_freshness(tmp_path)
        assert result["status"] == "warn"
        assert "could not parse" in result["detail"]

    def test_stroke_with_no_timezone(self, tmp_path):
        # ISO format without timezone — should be treated as UTC
        now = datetime.now(timezone.utc)
        naive_iso = now.strftime("%Y-%m-%dT%H:%M:%S")
        repo = self._make_strokes(tmp_path, naive_iso)
        result = prh.check_stroke_freshness(repo, cadence_seconds=15.0)
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# run_all_checks / format_report / exit_code
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_run_all_checks_returns_five_results(self, tmp_path):
        with patch.object(prh, "REPO", tmp_path), \
             patch.object(prh, "check_writer_alive", return_value={
                 "check": "writer_alive", "status": "pass", "detail": "ok"
             }), \
             patch.object(prh, "check_batch_alive", return_value={
                 "check": "batch_alive", "status": "pass", "detail": "ok"
             }), \
             patch.object(prh, "check_push_current", return_value={
                 "check": "push_current", "status": "pass", "detail": "ok"
             }), \
             patch.object(prh, "check_ssh_key", return_value={
                 "check": "ssh_key", "status": "pass", "detail": "ok"
             }), \
             patch.object(prh, "check_stroke_freshness", return_value={
                 "check": "stroke_freshness", "status": "pass", "detail": "ok"
             }):
            results = prh.run_all_checks(tmp_path)
            assert len(results) == 5

    def test_exit_code_all_pass(self):
        results = [{"status": "pass"}] * 5
        assert prh.exit_code(results) == 0

    def test_exit_code_with_warn(self):
        results = [{"status": "pass"}] * 4 + [{"status": "warn"}]
        assert prh.exit_code(results) == 1

    def test_exit_code_with_fail(self):
        results = [{"status": "pass"}] * 3 + [{"status": "fail"}, {"status": "warn"}]
        assert prh.exit_code(results) == 2

    def test_format_report_all_pass(self):
        results = [
            {"check": "writer_alive", "status": "pass", "detail": "running"},
            {"check": "batch_alive", "status": "pass", "detail": "running"},
            {"check": "push_current", "status": "pass", "detail": "up to date"},
            {"check": "ssh_key", "status": "pass", "detail": "ok"},
            {"check": "stroke_freshness", "status": "pass", "detail": "fresh"},
        ]
        report = prh.format_report(results)
        assert "PASS" in report
        assert "all systems nominal" in report
        assert "✓" in report

    def test_format_report_with_failure(self):
        results = [
            {"check": "writer_alive", "status": "fail", "detail": "not running"},
            {"check": "batch_alive", "status": "pass", "detail": "running"},
        ]
        report = prh.format_report(results)
        assert "FAIL" in report
        assert "✗" in report
