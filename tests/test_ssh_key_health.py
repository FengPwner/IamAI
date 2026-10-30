"""Tests for iamai.ssh_key_health — push health monitor.

the ssh key health module must correctly classify three failure modes:
  1. key missing (RED)
  2. key exists but not registered (AMBER)
  3. key exists and registered (GREEN)

these tests use mocking to avoid real network calls and filesystem
side effects. each test isolates one state transition.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iamai.ssh_key_health import (
    HealthReport,
    HealthState,
    _count_unpushed,
    _extract_fingerprint,
    _key_exists,
    _probe_github,
    format_health_report,
    ssh_health_check,
)


# ---------------------------------------------------------------------------
# _key_exists
# ---------------------------------------------------------------------------


class TestKeyExists:
    def test_returns_true_for_existing_file(self, tmp_path: Path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake key content")
        assert _key_exists(key) is True

    def test_returns_false_for_missing_file(self, tmp_path: Path):
        key = tmp_path / "nonexistent"
        assert _key_exists(key) is False

    def test_returns_false_for_directory(self, tmp_path: Path):
        d = tmp_path / "id_ed25519"
        d.mkdir()
        assert _key_exists(d) is False


# ---------------------------------------------------------------------------
# _extract_fingerprint
# ---------------------------------------------------------------------------


class TestExtractFingerprint:
    def test_returns_none_when_pub_missing(self, tmp_path: Path):
        key = tmp_path / "id_ed25519"
        key.write_text("private")
        # no .pub file
        assert _extract_fingerprint(key) is None

    def test_parses_fingerprint_from_ssh_keygen(self, tmp_path: Path):
        key = tmp_path / "id_ed25519"
        key.write_text("private")
        pub = tmp_path / "id_ed25519.pub"
        pub.write_text("ssh-ed25519 AAAA... user@host")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "256 SHA256:abcdef123456 user@host (ED25519)\n"

        with patch("iamai.ssh_key_health.subprocess.run", return_value=mock_result):
            fp = _extract_fingerprint(key)

        assert fp == "SHA256:abcdef123456"

    def test_returns_none_on_ssh_keygen_failure(self, tmp_path: Path):
        key = tmp_path / "id_ed25519"
        key.write_text("private")
        pub = tmp_path / "id_ed25519.pub"
        pub.write_text("corrupt")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("iamai.ssh_key_health.subprocess.run", return_value=mock_result):
            fp = _extract_fingerprint(key)

        assert fp is None


# ---------------------------------------------------------------------------
# _probe_github
# ---------------------------------------------------------------------------


class TestProbeGithub:
    def test_success_when_authenticated(self, tmp_path: Path):
        key = tmp_path / "id_ed25519"
        key.write_text("private")

        mock_result = MagicMock()
        mock_result.stderr = ""
        mock_result.stdout = "Hi FengPwner! You've successfully authenticated.\n"

        with patch("iamai.ssh_key_health.subprocess.run", return_value=mock_result):
            success, msg = _probe_github(key)

        assert success is True
        assert "Hi FengPwner!" in msg

    def test_failure_on_permission_denied(self, tmp_path: Path):
        key = tmp_path / "id_ed25519"
        key.write_text("private")

        mock_result = MagicMock()
        mock_result.stderr = "git@github.com: Permission denied (publickey).\n"
        mock_result.stdout = ""

        with patch("iamai.ssh_key_health.subprocess.run", return_value=mock_result):
            success, msg = _probe_github(key)

        assert success is False
        assert "permission denied" in msg

    def test_failure_on_timeout(self, tmp_path: Path):
        key = tmp_path / "id_ed25519"
        key.write_text("private")

        import subprocess
        with patch(
            "iamai.ssh_key_health.subprocess.run",
            side_effect=subprocess.TimeoutExpired("ssh", 10),
        ):
            success, msg = _probe_github(key)

        assert success is False
        assert msg == "connection timeout"


# ---------------------------------------------------------------------------
# _count_unpushed
# ---------------------------------------------------------------------------


class TestCountUnpushed:
    def test_returns_count_on_success(self, tmp_path: Path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "41\n"

        with patch("iamai.ssh_key_health.subprocess.run", return_value=mock_result):
            count = _count_unpushed(tmp_path)

        assert count == 41

    def test_returns_minus_one_on_failure(self, tmp_path: Path):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""

        with patch("iamai.ssh_key_health.subprocess.run", return_value=mock_result):
            count = _count_unpushed(tmp_path)

        assert count == -1


# ---------------------------------------------------------------------------
# ssh_health_check (integration)
# ---------------------------------------------------------------------------


class TestSshHealthCheck:
    def test_red_when_key_missing(self, tmp_path: Path):
        missing_key = tmp_path / "nonexistent_key"
        report = ssh_health_check(key_path=missing_key, repo_path=tmp_path)

        assert report.state == HealthState.RED
        assert "missing" in report.reason.lower()

    def test_amber_when_key_exists_but_rejected(self, tmp_path: Path):
        key = tmp_path / "id_ed25519"
        key.write_text("private key content")
        pub = tmp_path / "id_ed25519.pub"
        pub.write_text("ssh-ed25519 AAAA... user@host")

        # mock fingerprint extraction
        fp_result = MagicMock()
        fp_result.returncode = 0
        fp_result.stdout = "256 SHA256:testfp123 user@host (ED25519)\n"

        # mock github probe — rejected
        probe_result = MagicMock()
        probe_result.stderr = "git@github.com: Permission denied (publickey).\n"
        probe_result.stdout = ""

        # mock unpushed count
        count_result = MagicMock()
        count_result.returncode = 0
        count_result.stdout = "41\n"

        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd)
            if "ssh-keygen" in cmd_str:
                return fp_result
            if "ssh" in cmd_str and "github.com" in cmd_str:
                return probe_result
            if "rev-list" in cmd_str:
                return count_result
            return MagicMock(returncode=1, stdout="")

        with patch("iamai.ssh_key_health.subprocess.run", side_effect=side_effect):
            report = ssh_health_check(key_path=key, repo_path=tmp_path)

        assert report.state == HealthState.AMBER
        assert report.fingerprint == "SHA256:testfp123"
        assert report.unpushed_count == 41
        assert "rejected" in report.reason.lower()

    def test_green_when_authenticated(self, tmp_path: Path):
        key = tmp_path / "id_ed25519"
        key.write_text("private key content")
        pub = tmp_path / "id_ed25519.pub"
        pub.write_text("ssh-ed25519 AAAA... user@host")

        fp_result = MagicMock()
        fp_result.returncode = 0
        fp_result.stdout = "256 SHA256:greenfp user@host (ED25519)\n"

        probe_result = MagicMock()
        probe_result.stderr = ""
        probe_result.stdout = "Hi FengPwner! You've successfully authenticated.\n"

        count_result = MagicMock()
        count_result.returncode = 0
        count_result.stdout = "0\n"

        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd)
            if "ssh-keygen" in cmd_str:
                return fp_result
            if "ssh" in cmd_str and "github.com" in cmd_str:
                return probe_result
            if "rev-list" in cmd_str:
                return count_result
            return MagicMock(returncode=1, stdout="")

        with patch("iamai.ssh_key_health.subprocess.run", side_effect=side_effect):
            report = ssh_health_check(key_path=key, repo_path=tmp_path)

        assert report.state == HealthState.GREEN
        assert report.unpushed_count == 0


# ---------------------------------------------------------------------------
# format_health_report
# ---------------------------------------------------------------------------


class TestFormatHealthReport:
    def test_formats_amber_report(self, tmp_path: Path):
        report = HealthReport(
            state=HealthState.AMBER,
            key_path=tmp_path / "id_ed25519",
            fingerprint="SHA256:abc123",
            reason="key exists but github rejected it",
            unpushed_count=41,
        )
        line = format_health_report(report)

        assert "[AMBER]" in line
        assert "SHA256:abc123" in line
        assert "unpushed=41" in line

    def test_formats_red_report_without_fingerprint(self, tmp_path: Path):
        report = HealthReport(
            state=HealthState.RED,
            key_path=tmp_path / "missing_key",
            reason="key file missing",
            unpushed_count=0,
        )
        line = format_health_report(report)

        assert "[RED]" in line
        assert "fingerprint=none" in line
        assert "key file missing" in line

    def test_formats_green_report(self, tmp_path: Path):
        report = HealthReport(
            state=HealthState.GREEN,
            key_path=tmp_path / "id_ed25519",
            fingerprint="SHA256:good",
            reason="authenticated: Hi user!",
            unpushed_count=0,
        )
        line = format_health_report(report)

        assert "[GREEN]" in line
        assert "unpushed=0" in line
