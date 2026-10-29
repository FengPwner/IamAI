"""Tests for iamai/push_retry.py — resilient git push with back-off."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.push_retry import (
    PushResult,
    check_known_hosts,
    check_ssh_key,
    preflight_ok,
    git_push,
    ensure_pushed,
)


# ---------------------------------------------------------------------------
# PushResult
# ---------------------------------------------------------------------------

class TestPushResult:
    def test_ok_true_is_truthy(self):
        r = PushResult(ok=True, attempts=1, message="pushed")
        assert bool(r) is True

    def test_ok_false_is_falsy(self):
        r = PushResult(ok=False, attempts=3, message="failed")
        assert bool(r) is False

    def test_repr(self):
        r = PushResult(ok=True, attempts=1, message="pushed")
        assert "pushed" in repr(r)
        assert "ok=True" in repr(r)

    def test_attempts_field(self):
        r = PushResult(ok=False, attempts=5, message="timeout")
        assert r.attempts == 5


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

class TestCheckSshKey:
    def test_missing_file(self, tmp_path):
        assert check_ssh_key(str(tmp_path / "nonexistent")) is False

    def test_empty_file(self, tmp_path):
        k = tmp_path / "key"
        k.write_text("")
        assert check_ssh_key(str(k)) is False

    def test_valid_key(self, tmp_path):
        k = tmp_path / "key"
        k.write_text("ssh-ed25519 AAAA...")
        assert check_ssh_key(str(k)) is True


class TestCheckKnownHosts:
    def test_missing_known_hosts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert check_known_hosts("github.com") is False

    def test_host_present(self, tmp_path, monkeypatch):
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "known_hosts").write_text("github.com ssh-ed25519 AAAA\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert check_known_hosts("github.com") is True

    def test_host_absent(self, tmp_path, monkeypatch):
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "known_hosts").write_text("gitlab.com ssh-ed25519 BBBB\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert check_known_hosts("github.com") is False


class TestPreflight:
    def test_both_ok(self, tmp_path, monkeypatch):
        k = tmp_path / "key"
        k.write_text("ssh-ed25519 AAAA")
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "known_hosts").write_text("github.com ssh-ed25519 AAAA\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert preflight_ok(ssh_key=str(k)) is True

    def test_key_missing(self, tmp_path, monkeypatch):
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "known_hosts").write_text("github.com ssh-ed25519 AAAA\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert preflight_ok(ssh_key=str(tmp_path / "missing")) is False


# ---------------------------------------------------------------------------
# git_push — mocked subprocess
# ---------------------------------------------------------------------------

class TestGitPush:
    @patch("iamai.push_retry._run_git")
    def test_first_attempt_success(self, mock_run):
        mock_run.return_value = (0, "")
        r = git_push(repo="/tmp/fake", max_retries=3)
        assert r.ok is True
        assert r.attempts == 1

    @patch("iamai.push_retry.time.sleep")
    @patch("iamai.push_retry._run_git")
    def test_retry_then_success(self, mock_run, mock_sleep):
        mock_run.side_effect = [
            (1, "Connection reset by peer"),
            (0, ""),
        ]
        r = git_push(repo="/tmp/fake", max_retries=3, base_delay=0.1, jitter=0.0)
        assert r.ok is True
        assert r.attempts == 2

    @patch("iamai.push_retry.time.sleep")
    @patch("iamai.push_retry._run_git")
    def test_all_retries_fail(self, mock_run, mock_sleep):
        mock_run.return_value = (1, "Host key verification failed")
        r = git_push(repo="/tmp/fake", max_retries=2, base_delay=0.1, jitter=0.0)
        assert r.ok is False
        assert r.attempts == 2
        assert "failed" in r.message

    @patch("iamai.push_retry._pull_rebase_recovery")
    @patch("iamai.push_retry._run_git")
    def test_non_fast_forward_triggers_recovery(self, mock_run, mock_recovery):
        mock_run.side_effect = [
            (1, "[rejected] non-fast-forward"),
            (0, ""),
        ]
        r = git_push(repo="/tmp/fake", max_retries=3)
        assert r.ok is True
        mock_recovery.assert_called_once()

    @patch("iamai.push_retry.time.sleep")
    @patch("iamai.push_retry._run_git")
    def test_backoff_delay_doubles(self, mock_run, mock_sleep):
        mock_run.return_value = (1, "Connection refused")
        git_push(repo="/tmp/fake", max_retries=3, base_delay=1.0, jitter=0.0)
        # Two sleeps: ~1s then ~2s (jitter=0 so exact)
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert len(delays) == 2
        assert delays[0] == pytest.approx(1.0, abs=0.1)
        assert delays[1] == pytest.approx(2.0, abs=0.1)


# ---------------------------------------------------------------------------
# ensure_pushed
# ---------------------------------------------------------------------------

class TestEnsurePushed:
    @patch("iamai.push_retry.preflight_ok", return_value=False)
    def test_preflight_failure_skips_push(self, mock_pf):
        r = ensure_pushed(repo="/tmp/fake")
        assert r.ok is False
        assert "pre-flight" in r.message

    @patch("iamai.push_retry.git_push")
    @patch("iamai.push_retry.preflight_ok", return_value=True)
    def test_preflight_ok_calls_push(self, mock_pf, mock_push):
        mock_push.return_value = PushResult(ok=True, attempts=1, message="pushed")
        r = ensure_pushed(repo="/tmp/fake")
        assert r.ok is True
        mock_push.assert_called_once()
