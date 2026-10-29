#!/usr/bin/env python3
"""tests for snippets/preflight.py — push preflight checks."""

import subprocess
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "snippets"))
import preflight


class TestCheckSshConnectivity:
    def test_success(self):
        mock_result = MagicMock()
        mock_result.stdout = "Hi FengPwner/IamAI! You've successfully authenticated"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            r = preflight.check_ssh_connectivity()
        assert r["ok"] is True
        assert "authenticated" in r["detail"]

    def test_host_key_verification_failed(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Host key verification failed."
        with patch("subprocess.run", return_value=mock_result):
            r = preflight.check_ssh_connectivity()
        assert r["ok"] is False
        assert "host key" in r["detail"].lower()

    def test_permission_denied(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Permission denied (publickey)."
        with patch("subprocess.run", return_value=mock_result):
            r = preflight.check_ssh_connectivity()
        assert r["ok"] is False
        assert "deploy key" in r["detail"].lower()

    def test_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 15)):
            r = preflight.check_ssh_connectivity()
        assert r["ok"] is False
        assert "timed out" in r["detail"].lower()

    def test_ssh_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            r = preflight.check_ssh_connectivity()
        assert r["ok"] is False
        assert "not found" in r["detail"].lower()


class TestCheckUncommitted:
    def test_clean_tree(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            r = preflight.check_uncommitted()
        assert r["ok"] is True
        assert r["count"] == 0

    def test_dirty_tree(self):
        mock_result = MagicMock()
        mock_result.stdout = " M file1.txt\n M file2.txt\n?? new.txt\n"
        with patch("subprocess.run", return_value=mock_result):
            r = preflight.check_uncommitted()
        assert r["ok"] is False
        assert r["count"] == 3

    def test_git_failure(self):
        with patch("subprocess.run", side_effect=Exception("git error")):
            r = preflight.check_uncommitted()
        assert r["ok"] is False
        assert "failed" in r["detail"].lower()


class TestCheckUnpushed:
    def test_up_to_date(self):
        mock_result = MagicMock()
        mock_result.stdout = "0\n"
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            r = preflight.check_unpushed()
        assert r["ok"] is True
        assert r["count"] == 0

    def test_few_unpushed(self):
        mock_result = MagicMock()
        mock_result.stdout = "3\n"
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            r = preflight.check_unpushed()
        assert r["ok"] is True
        assert r["count"] == 3

    def test_backlog_growing(self):
        mock_result = MagicMock()
        mock_result.stdout = "15\n"
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            r = preflight.check_unpushed()
        assert r["ok"] is False
        assert r["count"] == 15


class TestRunPreflight:
    def test_all_pass(self, capsys):
        with patch.object(preflight, "check_ssh_connectivity", return_value={"name": "ssh", "ok": True, "detail": "ok"}):
            with patch.object(preflight, "check_uncommitted", return_value={"name": "uncommitted", "ok": True, "detail": "clean"}):
                with patch.object(preflight, "check_unpushed", return_value={"name": "unpushed", "ok": True, "detail": "synced"}):
                    assert preflight.run_preflight() is True

    def test_one_fail(self, capsys):
        with patch.object(preflight, "check_ssh_connectivity", return_value={"name": "ssh", "ok": False, "detail": "blocked"}):
            with patch.object(preflight, "check_uncommitted", return_value={"name": "uncommitted", "ok": True, "detail": "clean"}):
                with patch.object(preflight, "check_unpushed", return_value={"name": "unpushed", "ok": True, "detail": "synced"}):
                    assert preflight.run_preflight() is False

    def test_fix_mode_retries_ssh(self, capsys):
        call_count = {"n": 0}

        def ssh_check():
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"name": "ssh", "ok": False, "detail": "missing"}
            return {"name": "ssh", "ok": True, "detail": "fixed"}

        with patch.object(preflight, "check_ssh_connectivity", side_effect=ssh_check):
            with patch.object(preflight, "check_uncommitted", return_value={"name": "uncommitted", "ok": True, "detail": "clean"}):
                with patch.object(preflight, "check_unpushed", return_value={"name": "unpushed", "ok": True, "detail": "synced"}):
                    with patch.object(preflight, "try_fix_ssh", return_value=True):
                        result = preflight.run_preflight(fix=True)
                        assert result is True
