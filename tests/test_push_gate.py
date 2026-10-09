#!/usr/bin/env python3
"""Tests for tools/push_gate.py — push safety checker.

Covers: fetch failures, up-to-date, ahead, behind, diverged, unknown,
JSON output, and CLI exit codes. Mocks subprocess.run to avoid real
git operations.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import push_gate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_subprocess(responses):
    """Return a side_effect function for subprocess.run.

    `responses` maps a tuple of command-prefix args to (returncode, stdout).
    The first matching prefix wins. Unmatched commands get (128, '').
    """
    def effect(cmd, **kwargs):
        for key, (rc, out) in responses.items():
            key_list = list(key)
            if cmd[: len(key_list)] == key_list:
                m = MagicMock()
                m.returncode = rc
                m.stdout = out
                return m
        m = MagicMock()
        m.returncode = 128
        m.stdout = ""
        return m

    return effect


# ---------------------------------------------------------------------------
# Unit tests — low-level helpers
# ---------------------------------------------------------------------------


class TestLocalHead:
    def test_returns_sha(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "rev-parse", "HEAD"): (0, "abc123"),
        })):
            assert push_gate.local_head() == "abc123"

    def test_returns_none_on_failure(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "rev-parse", "HEAD"): (128, ""),
        })):
            assert push_gate.local_head() is None


class TestRemoteHead:
    def test_returns_sha(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "rev-parse", "origin/main"): (0, "def456"),
        })):
            assert push_gate.remote_head("origin", "main") == "def456"

    def test_returns_none_when_remote_missing(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "rev-parse", "origin/main"): (128, ""),
        })):
            assert push_gate.remote_head("origin", "main") is None


class TestIsAncestor:
    def test_true(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "merge-base", "--is-ancestor"): (0, ""),
        })):
            assert push_gate.is_ancestor("aaa", "bbb") is True

    def test_false(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "merge-base", "--is-ancestor"): (1, ""),
        })):
            assert push_gate.is_ancestor("aaa", "bbb") is False


class TestFetch:
    def test_success(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "fetch"): (0, ""),
        })):
            ok, msg = push_gate.fetch()
        assert ok is True

    def test_failure(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "fetch"): (128, "timeout"),
        })):
            ok, msg = push_gate.fetch()
        assert ok is False
        assert "fetch failed" in msg


# ---------------------------------------------------------------------------
# Integration-level tests — check_push_gate
# ---------------------------------------------------------------------------


class TestCheckPushGate:

    def test_fetch_failure_returns_unknown(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "fetch"): (1, "fatal: could not connect"),
        })):
            report = push_gate.check_push_gate()
        assert report["safe_to_push"] is False
        assert report["status"] == "unknown"
        assert "fetch failed" in report["message"]

    def test_up_to_date(self):
        sha = "abc123"
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "fetch"): (0, ""),
            ("git", "rev-parse", "HEAD"): (0, sha),
            ("git", "rev-parse", "origin/main"): (0, sha),
        })):
            report = push_gate.check_push_gate()
        assert report["safe_to_push"] is True
        assert report["status"] == "up_to_date"
        assert report["behind_count"] == 0
        assert report["ahead_count"] == 0

    def test_ahead_safe_to_push(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "fetch"): (0, ""),
            ("git", "rev-parse", "HEAD"): (0, "local_sha"),
            ("git", "rev-parse", "origin/main"): (0, "remote_sha"),
            ("git", "rev-list", "--count", "remote_sha..local_sha"): (0, "3"),
            ("git", "rev-list", "--count", "local_sha..remote_sha"): (0, "0"),
        })):
            report = push_gate.check_push_gate()
        assert report["safe_to_push"] is True
        assert report["status"] == "ahead"
        assert report["ahead_count"] == 3
        assert report["behind_count"] == 0

    def test_behind_needs_pull(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "fetch"): (0, ""),
            ("git", "rev-parse", "HEAD"): (0, "local_sha"),
            ("git", "rev-parse", "origin/main"): (0, "remote_sha"),
            ("git", "rev-list", "--count", "remote_sha..local_sha"): (0, "0"),
            ("git", "rev-list", "--count", "local_sha..remote_sha"): (0, "5"),
        })):
            report = push_gate.check_push_gate()
        assert report["safe_to_push"] is False
        assert report["status"] == "behind"
        assert report["behind_count"] == 5

    def test_diverged(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "fetch"): (0, ""),
            ("git", "rev-parse", "HEAD"): (0, "local_sha"),
            ("git", "rev-parse", "origin/main"): (0, "remote_sha"),
            ("git", "rev-list", "--count", "remote_sha..local_sha"): (0, "2"),
            ("git", "rev-list", "--count", "local_sha..remote_sha"): (0, "3"),
        })):
            report = push_gate.check_push_gate()
        assert report["safe_to_push"] is False
        assert report["status"] == "diverged"
        assert report["ahead_count"] == 2
        assert report["behind_count"] == 3

    def test_no_fetch_skips_fetch(self):
        sha = "same"
        # fetch returns failure, but should never be called
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "fetch"): (99, "should not be called"),
            ("git", "rev-parse", "HEAD"): (0, sha),
            ("git", "rev-parse", "origin/main"): (0, sha),
        })):
            report = push_gate.check_push_gate(fetch_first=False)
        assert report["safe_to_push"] is True
        assert report["status"] == "up_to_date"

    def test_cannot_resolve_local(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "fetch"): (0, ""),
            ("git", "rev-parse", "HEAD"): (128, ""),
            ("git", "rev-parse", "origin/main"): (0, "remote_sha"),
        })):
            report = push_gate.check_push_gate()
        assert report["safe_to_push"] is False
        assert report["status"] == "unknown"

    def test_cannot_resolve_remote(self):
        with patch("subprocess.run", side_effect=_mock_subprocess({
            ("git", "fetch"): (0, ""),
            ("git", "rev-parse", "HEAD"): (0, "local_sha"),
            ("git", "rev-parse", "origin/main"): (128, ""),
        })):
            report = push_gate.check_push_gate()
        assert report["safe_to_push"] is False
        assert report["status"] == "unknown"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCLI:

    def test_safe_exit_0(self):
        with patch("push_gate.check_push_gate", return_value={
            "safe_to_push": True,
            "status": "ahead",
            "message": "3 ahead",
            "local_sha": "a",
            "remote_sha": "b",
            "ahead_count": 3,
            "behind_count": 0,
        }):
            with patch("sys.argv", ["push_gate.py"]):
                assert push_gate.main() == 0

    def test_unsafe_exit_1(self):
        with patch("push_gate.check_push_gate", return_value={
            "safe_to_push": False,
            "status": "behind",
            "message": "5 behind",
            "local_sha": "a",
            "remote_sha": "b",
            "ahead_count": 0,
            "behind_count": 5,
        }):
            with patch("sys.argv", ["push_gate.py"]):
                assert push_gate.main() == 1

    def test_json_output(self, capsys):
        report = {
            "safe_to_push": True,
            "status": "up_to_date",
            "message": "ok",
            "local_sha": "a",
            "remote_sha": "a",
            "ahead_count": 0,
            "behind_count": 0,
        }
        with patch("push_gate.check_push_gate", return_value=report):
            with patch("sys.argv", ["push_gate.py", "--json"]):
                push_gate.main()
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["status"] == "up_to_date"
