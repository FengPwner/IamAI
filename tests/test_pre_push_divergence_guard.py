"""Tests for tools/pre_push_divergence_guard.py — pre-push divergence guard."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(REPO / "tools"))

import pre_push_divergence_guard as pg


# ---------------------------------------------------------------------------
# GuardReport
# ---------------------------------------------------------------------------

class TestGuardReport:
    def test_default_verdict_unknown(self):
        r = pg.GuardReport()
        assert r.verdict == "unknown"

    def test_to_dict(self):
        r = pg.GuardReport(verdict="safe", remote="origin", branch="main", ahead_count=3)
        d = r.to_dict()
        assert d["verdict"] == "safe"
        assert d["ahead_count"] == 3
        assert "merge_base" in d

    def test_to_json(self):
        r = pg.GuardReport(verdict="diverged", ahead_count=2, behind_count=1)
        j = json.loads(r.to_json())
        assert j["verdict"] == "diverged"
        assert j["ahead_count"] == 2
        assert j["behind_count"] == 1

    def test_defaults(self):
        r = pg.GuardReport()
        assert r.remote == "origin"
        assert r.branch == "main"
        assert r.local_sha == ""
        assert r.remote_sha == ""
        assert r.ahead_count == 0
        assert r.behind_count == 0
        assert r.dirty_files == 0
        assert r.error == ""


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestCheckRemoteReachable:
    def test_reachable(self):
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch.object(pg, "_run", return_value=mock_result):
            ok, err = pg.check_remote_reachable("origin")
            assert ok is True
            assert err == ""

    def test_unreachable(self):
        mock_result = MagicMock(returncode=128, stdout="", stderr="fatal: Could not read")
        with patch.object(pg, "_run", return_value=mock_result):
            ok, err = pg.check_remote_reachable("origin")
            assert ok is False
            assert "Could not read" in err

    def test_timeout(self):
        with patch.object(pg, "_run", side_effect=subprocess.TimeoutExpired("git", 10)):
            ok, err = pg.check_remote_reachable("origin")
            assert ok is False
            assert "timed out" in err


class TestGetLocalSha:
    def test_success(self):
        mock_result = MagicMock(returncode=0, stdout="abc123def456\n")
        with patch.object(pg, "_run", return_value=mock_result):
            sha = pg.get_local_sha("main")
            assert sha == "abc123def456"

    def test_failure(self):
        mock_result = MagicMock(returncode=128, stdout="", stderr="fatal")
        with patch.object(pg, "_run", return_value=mock_result):
            sha = pg.get_local_sha("nonexistent")
            assert sha == ""


class TestGetRemoteSha:
    def test_success(self):
        mock_result = MagicMock(returncode=0, stdout="789xyz012abc\n")
        with patch.object(pg, "_run", return_value=mock_result):
            sha = pg.get_remote_sha("origin", "main")
            assert sha == "789xyz012abc"

    def test_failure(self):
        mock_result = MagicMock(returncode=128, stdout="")
        with patch.object(pg, "_run", return_value=mock_result):
            sha = pg.get_remote_sha("origin", "main")
            assert sha == ""


class TestGetMergeBase:
    def test_success(self):
        mock_result = MagicMock(returncode=0, stdout="base123\n")
        with patch.object(pg, "_run", return_value=mock_result):
            base = pg.get_merge_base("aaa", "bbb")
            assert base == "base123"

    def test_no_common_ancestor(self):
        mock_result = MagicMock(returncode=1, stdout="")
        with patch.object(pg, "_run", return_value=mock_result):
            base = pg.get_merge_base("aaa", "bbb")
            assert base == ""


class TestCountAheadBehind:
    def test_ahead_only(self):
        mock_result = MagicMock(returncode=0, stdout="3\t0\n")
        with patch.object(pg, "_run", return_value=mock_result):
            ahead, behind = pg.count_ahead_behind("local", "remote")
            assert ahead == 3
            assert behind == 0

    def test_behind_only(self):
        mock_result = MagicMock(returncode=0, stdout="0\t5\n")
        with patch.object(pg, "_run", return_value=mock_result):
            ahead, behind = pg.count_ahead_behind("local", "remote")
            assert ahead == 0
            assert behind == 5

    def test_diverged(self):
        mock_result = MagicMock(returncode=0, stdout="2\t4\n")
        with patch.object(pg, "_run", return_value=mock_result):
            ahead, behind = pg.count_ahead_behind("local", "remote")
            assert ahead == 2
            assert behind == 4

    def test_failure_returns_zeros(self):
        mock_result = MagicMock(returncode=128, stdout="")
        with patch.object(pg, "_run", return_value=mock_result):
            ahead, behind = pg.count_ahead_behind("bad", "sha")
            assert ahead == 0
            assert behind == 0


class TestCountDirtyFiles:
    def test_clean(self):
        mock_result = MagicMock(returncode=0, stdout="")
        with patch.object(pg, "_run", return_value=mock_result):
            assert pg.count_dirty_files() == 0

    def test_dirty(self):
        mock_result = MagicMock(returncode=0, stdout=" M file1.py\n M file2.py\n?? new.py\n")
        with patch.object(pg, "_run", return_value=mock_result):
            assert pg.count_dirty_files() == 3

    def test_staged_only(self):
        mock_result = MagicMock(returncode=0, stdout="M  staged.py\n")
        with patch.object(pg, "_run", return_value=mock_result):
            assert pg.count_dirty_files() == 1


# ---------------------------------------------------------------------------
# run_guard integration
# ---------------------------------------------------------------------------

class TestRunGuard:
    def test_offline_when_remote_unreachable(self):
        with patch.object(pg, "check_remote_reachable", return_value=(False, "timeout")):
            report = pg.run_guard()
            assert report.verdict == "offline"
            assert "timeout" in report.error

    def test_offline_when_local_sha_missing(self):
        with patch.object(pg, "check_remote_reachable", return_value=(True, "")), \
             patch.object(pg, "get_local_sha", return_value=""):
            report = pg.run_guard()
            assert report.verdict == "offline"

    def test_offline_when_remote_sha_missing(self):
        with patch.object(pg, "check_remote_reachable", return_value=(True, "")), \
             patch.object(pg, "get_local_sha", return_value="aaa"), \
             patch.object(pg, "get_remote_sha", return_value=""):
            report = pg.run_guard()
            assert report.verdict == "offline"

    def test_safe_when_equal(self):
        with patch.object(pg, "check_remote_reachable", return_value=(True, "")), \
             patch.object(pg, "get_local_sha", return_value="aaa"), \
             patch.object(pg, "get_remote_sha", return_value="aaa"), \
             patch.object(pg, "count_dirty_files", return_value=0):
            report = pg.run_guard()
            assert report.verdict == "safe"
            assert report.ahead_count == 0
            assert report.behind_count == 0

    def test_diverged(self):
        with patch.object(pg, "check_remote_reachable", return_value=(True, "")), \
             patch.object(pg, "get_local_sha", return_value="aaa"), \
             patch.object(pg, "get_remote_sha", return_value="bbb"), \
             patch.object(pg, "get_merge_base", return_value="ccc"), \
             patch.object(pg, "count_ahead_behind", return_value=(2, 1)), \
             patch.object(pg, "count_dirty_files", return_value=0):
            report = pg.run_guard()
            assert report.verdict == "diverged"
            assert report.ahead_count == 2
            assert report.behind_count == 1

    def test_behind(self):
        with patch.object(pg, "check_remote_reachable", return_value=(True, "")), \
             patch.object(pg, "get_local_sha", return_value="aaa"), \
             patch.object(pg, "get_remote_sha", return_value="bbb"), \
             patch.object(pg, "get_merge_base", return_value="ccc"), \
             patch.object(pg, "count_ahead_behind", return_value=(0, 3)), \
             patch.object(pg, "count_dirty_files", return_value=0):
            report = pg.run_guard()
            assert report.verdict == "behind"
            assert report.behind_count == 3

    def test_dirty_overrides_safe(self):
        """Even if branches are in sync, dirty files change the verdict."""
        with patch.object(pg, "check_remote_reachable", return_value=(True, "")), \
             patch.object(pg, "get_local_sha", return_value="aaa"), \
             patch.object(pg, "get_remote_sha", return_value="aaa"), \
             patch.object(pg, "count_dirty_files", return_value=5):
            report = pg.run_guard()
            assert report.verdict == "dirty"
            assert report.dirty_files == 5

    def test_dirty_overrides_diverged(self):
        """Dirty takes priority over diverged verdict."""
        with patch.object(pg, "check_remote_reachable", return_value=(True, "")), \
             patch.object(pg, "get_local_sha", return_value="aaa"), \
             patch.object(pg, "get_remote_sha", return_value="bbb"), \
             patch.object(pg, "get_merge_base", return_value="ccc"), \
             patch.object(pg, "count_ahead_behind", return_value=(2, 1)), \
             patch.object(pg, "count_dirty_files", return_value=1):
            report = pg.run_guard()
            assert report.verdict == "dirty"


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_basic_format(self):
        r = pg.GuardReport(verdict="safe", local_sha="abc1234567", remote_sha="def7654321")
        text = pg.format_report(r)
        assert "verdict:   safe" in text
        assert "abc1234567" in text
        assert "def7654321" in text

    def test_error_shown(self):
        r = pg.GuardReport(verdict="offline", error="connection refused")
        text = pg.format_report(r)
        assert "connection refused" in text

    def test_short_sha(self):
        r = pg.GuardReport(local_sha="abcdefghijklmnop")
        text = pg.format_report(r)
        assert "abcdefghij" in text  # first 10 chars
