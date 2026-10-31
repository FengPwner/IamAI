#!/usr/bin/env python3
"""Tests for push_blockage_analyzer.py"""

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from push_blockage_analyzer import (
    PushCheckResult,
    PushDiagnosis,
    check_remote_url,
    check_ssh_key_present,
    check_ssh_key_permissions,
    check_ssh_auth,
    check_push_debt,
    determine_severity,
    diagnose,
    format_human,
    run_cmd,
    CLEAR,
    WARNING,
    BLOCKED,
    CRITICAL,
    PUSH_DEBT_WARNING,
    PUSH_DEBT_BLOCKED,
    PUSH_AGE_CRITICAL_HOURS,
)


# --- PushCheckResult ---

class TestPushCheckResult:
    def test_passed_result(self):
        r = PushCheckResult(name="test", passed=True, detail="all good")
        assert r.name == "test"
        assert r.passed is True
        assert r.detail == "all good"
        assert r.fix is None

    def test_failed_with_fix(self):
        r = PushCheckResult(
            name="auth",
            passed=False,
            detail="permission denied",
            fix="register deploy key",
        )
        assert r.passed is False
        assert r.fix == "register deploy key"

    def test_to_dict(self):
        r = PushCheckResult(name="x", passed=True, detail="ok", fix=None)
        d = r.to_dict()
        assert d == {"name": "x", "passed": True, "detail": "ok", "fix": None}

    def test_to_dict_with_fix(self):
        r = PushCheckResult(name="x", passed=False, detail="bad", fix="do this")
        d = r.to_dict()
        assert d["fix"] == "do this"


# --- PushDiagnosis ---

class TestPushDiagnosis:
    def test_to_dict(self):
        checks = [PushCheckResult(name="a", passed=True, detail="ok")]
        diag = PushDiagnosis(
            severity=CLEAR,
            checks=checks,
            unpushed_count=0,
            oldest_unpushed_age_hours=None,
            remote_url="git@github.com:test/test.git",
            timestamp="2026-10-27T10:00:00+00:00",
        )
        d = diag.to_dict()
        assert d["severity"] == "clear"
        assert d["unpushed_count"] == 0
        assert d["remote_url"] == "git@github.com:test/test.git"
        assert len(d["checks"]) == 1

    def test_to_dict_with_age(self):
        diag = PushDiagnosis(
            severity=WARNING,
            checks=[],
            unpushed_count=25,
            oldest_unpushed_age_hours=3.5,
            remote_url="git@github.com:x/y.git",
            timestamp="2026-10-27T10:00:00+00:00",
        )
        d = diag.to_dict()
        assert d["oldest_unpushed_age_hours"] == 3.5


# --- run_cmd ---

class TestRunCmd:
    def test_successful_command(self):
        code, out, err = run_cmd(["echo", "hello"])
        assert code == 0
        assert out == "hello"

    def test_failing_command(self):
        code, out, err = run_cmd(["false"])
        assert code != 0

    def test_command_not_found(self):
        code, out, err = run_cmd(["nonexistent_command_xyz"])
        assert code == -2
        assert "not found" in err

    def test_timeout(self):
        code, out, err = run_cmd(["sleep", "30"], timeout=1)
        assert code == -1
        assert "timed out" in err


# --- check_remote_url ---

class TestCheckRemoteUrl:
    @patch("push_blockage_analyzer.run_cmd")
    def test_valid_remote(self, mock_run):
        mock_run.return_value = (0, "git@github.com:FengPwner/IamAI.git", "")
        result = check_remote_url("/fake/repo")
        assert result.passed is True
        assert "FengPwner/IamAI" in result.detail

    @patch("push_blockage_analyzer.run_cmd")
    def test_no_remote(self, mock_run):
        mock_run.return_value = (1, "", "fatal: No such remote")
        result = check_remote_url("/fake/repo")
        assert result.passed is False
        assert "no origin remote" in result.detail
        assert result.fix is not None

    @patch("push_blockage_analyzer.run_cmd")
    def test_empty_remote(self, mock_run):
        mock_run.return_value = (0, "", "")
        result = check_remote_url("/fake/repo")
        assert result.passed is False
        assert "empty" in result.detail


# --- check_ssh_key_present ---

class TestCheckSshKeyPresent:
    @patch("push_blockage_analyzer.Path.exists", autospec=True)
    def test_key_found(self, mock_exists):
        # Simulate config file doesn't exist, but id_ed25519 does
        # (selective mock: the old all-True mock made the module read a
        # config that does not exist and crash with FileNotFoundError)
        mock_exists.side_effect = lambda self: str(self).endswith("id_ed25519")
        result = check_ssh_key_present("/fake/repo")
        assert result.passed is True

    def test_returns_push_check_result(self):
        result = check_ssh_key_present("/fake/repo")
        assert isinstance(result, PushCheckResult)
        assert result.name == "ssh_key_present"


# --- check_ssh_key_permissions ---

class TestCheckSshKeyPermissions:
    def test_returns_push_check_result(self):
        result = check_ssh_key_permissions("/fake/repo")
        assert isinstance(result, PushCheckResult)
        assert result.name == "ssh_key_permissions"


# --- check_ssh_auth ---

class TestCheckSshAuth:
    @patch("push_blockage_analyzer.run_cmd")
    def test_successful_auth(self, mock_run):
        mock_run.return_value = (1, "", "Hi FengPwner! You've successfully authenticated")
        result = check_ssh_auth("/fake/repo")
        assert result.passed is True
        assert "successful" in result.detail.lower()

    @patch("push_blockage_analyzer.run_cmd")
    def test_permission_denied(self, mock_run):
        mock_run.return_value = (255, "", "git@github.com: Permission denied (publickey)")
        result = check_ssh_auth("/fake/repo")
        assert result.passed is False
        assert "permission denied" in result.detail.lower()
        assert "deploy key" in result.fix.lower()

    @patch("push_blockage_analyzer.run_cmd")
    def test_timeout(self, mock_run):
        mock_run.return_value = (-1, "", "command timed out")
        result = check_ssh_auth("/fake/repo")
        assert result.passed is False
        assert "timed out" in result.detail.lower()


# --- check_push_debt ---

class TestCheckPushDebt:
    @patch("push_blockage_analyzer.run_cmd")
    def test_no_unpushed(self, mock_run):
        mock_run.return_value = (0, "", "")
        result, count, age = check_push_debt("/fake/repo")
        assert result.passed is True
        assert count == 0

    @patch("push_blockage_analyzer.run_cmd")
    def test_few_unpushed(self, mock_run):
        commits = "\n".join([f"abc{i} commit {i}" for i in range(5)])
        mock_run.return_value = (0, commits, "")
        result, count, age = check_push_debt("/fake/repo")
        assert result.passed is True
        assert count == 5

    @patch("push_blockage_analyzer.run_cmd")
    def test_many_unpushed(self, mock_run):
        commits = "\n".join([f"abc{i} commit {i}" for i in range(60)])
        mock_run.return_value = (0, commits, "")
        result, count, age = check_push_debt("/fake/repo")
        assert result.passed is False
        assert count == 60
        assert "60" in result.detail

    @patch("push_blockage_analyzer.run_cmd")
    def test_no_tracking_ref(self, mock_run):
        def side_effect(cmd, cwd=None, timeout=10):
            if "origin/main..HEAD" in cmd:
                return (128, "", "fatal: no upstream")
            return (0, "42", "")
        mock_run.side_effect = side_effect
        result, count, age = check_push_debt("/fake/repo")
        assert result.passed is False
        assert "cannot determine" in result.detail


# --- determine_severity ---

class TestDetermineSeverity:
    def test_clear_when_all_pass(self):
        checks = [
            PushCheckResult(name="remote_url", passed=True, detail="ok"),
            PushCheckResult(name="ssh_key_present", passed=True, detail="ok"),
            PushCheckResult(name="ssh_key_permissions", passed=True, detail="ok"),
            PushCheckResult(name="ssh_auth", passed=True, detail="ok"),
            PushCheckResult(name="push_debt", passed=True, detail="ok"),
        ]
        assert determine_severity(checks, 0, None) == CLEAR

    def test_blocked_on_auth_failure(self):
        checks = [
            PushCheckResult(name="ssh_auth", passed=False, detail="denied"),
        ]
        assert determine_severity(checks, 10, 2.0) == BLOCKED

    def test_blocked_on_missing_key(self):
        checks = [
            PushCheckResult(name="ssh_key_present", passed=False, detail="missing"),
        ]
        assert determine_severity(checks, 5, None) == BLOCKED

    def test_critical_on_long_blockage(self):
        checks = [
            PushCheckResult(name="ssh_auth", passed=False, detail="denied"),
        ]
        assert determine_severity(checks, 100, 48.0) == CRITICAL

    def test_warning_on_debt_without_auth_failure(self):
        checks = [
            PushCheckResult(name="ssh_auth", passed=True, detail="ok"),
        ]
        assert determine_severity(checks, 30, 5.0) == WARNING

    def test_clear_low_debt_all_pass(self):
        checks = [
            PushCheckResult(name="ssh_auth", passed=True, detail="ok"),
        ]
        assert determine_severity(checks, 3, 0.5) == CLEAR


# --- format_human ---

class TestFormatHuman:
    def test_clear_report(self):
        diag = PushDiagnosis(
            severity=CLEAR,
            checks=[PushCheckResult(name="test", passed=True, detail="ok")],
            unpushed_count=0,
            oldest_unpushed_age_hours=None,
            remote_url="git@github.com:test/test.git",
            timestamp="2026-10-27T10:00:00+00:00",
        )
        report = format_human(diag)
        assert "✅" in report
        assert "CLEAR" in report
        assert "All checks passed" in report

    def test_blocked_report(self):
        diag = PushDiagnosis(
            severity=BLOCKED,
            checks=[
                PushCheckResult(
                    name="ssh_auth",
                    passed=False,
                    detail="permission denied",
                    fix="register deploy key",
                ),
            ],
            unpushed_count=50,
            oldest_unpushed_age_hours=12.0,
            remote_url="git@github.com:test/test.git",
            timestamp="2026-10-27T10:00:00+00:00",
        )
        report = format_human(diag)
        assert "🚫" in report
        assert "BLOCKED" in report
        assert "register deploy key" in report
        assert "50" in report

    def test_critical_report(self):
        diag = PushDiagnosis(
            severity=CRITICAL,
            checks=[
                PushCheckResult(name="ssh_auth", passed=False, detail="denied", fix="fix it"),
            ],
            unpushed_count=100,
            oldest_unpushed_age_hours=72.0,
            remote_url="git@github.com:test/test.git",
            timestamp="2026-10-27T10:00:00+00:00",
        )
        report = format_human(diag)
        assert "🔴" in report
        assert "CRITICAL" in report
        assert "72.0h" in report

    def test_warning_shows_icon(self):
        diag = PushDiagnosis(
            severity=WARNING,
            checks=[],
            unpushed_count=20,
            oldest_unpushed_age_hours=None,
            remote_url="git@github.com:test/test.git",
            timestamp="2026-10-27T10:00:00+00:00",
        )
        report = format_human(diag)
        assert "⚠️" in report

    def test_failed_checks_listed(self):
        diag = PushDiagnosis(
            severity=BLOCKED,
            checks=[
                PushCheckResult(name="a", passed=True, detail="ok"),
                PushCheckResult(name="b", passed=False, detail="bad", fix="fix b"),
                PushCheckResult(name="c", passed=False, detail="worse", fix="fix c"),
            ],
            unpushed_count=10,
            oldest_unpushed_age_hours=None,
            remote_url="test",
            timestamp="now",
        )
        report = format_human(diag)
        assert "2 check(s) failed" in report
        assert "fix b" in report
        assert "fix c" in report


# --- constants ---

class TestConstants:
    def test_thresholds(self):
        assert PUSH_DEBT_WARNING < PUSH_DEBT_BLOCKED
        assert PUSH_AGE_CRITICAL_HOURS > 0

    def test_severity_levels(self):
        assert CLEAR == "clear"
        assert WARNING == "warning"
        assert BLOCKED == "blocked"
        assert CRITICAL == "critical"
