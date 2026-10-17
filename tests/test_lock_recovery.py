"""Tests for iamai.lock_recovery — staged lock recovery state machine."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.lock_recovery import (
    stage_detect,
    stage_clear,
    stage_probe,
    stage_drain,
    stage_push,
    run_recovery,
    recovery_summary,
    _ok,
    _failed,
    _skipped,
)


# ---------------------------------------------------------------------------
# Helper result constructors
# ---------------------------------------------------------------------------


class TestResultHelpers:
    """Unit tests for _ok, _failed, _skipped."""

    def test_ok_returns_correct_shape(self):
        result = _ok("detect", "found lock", "clear")
        assert result == {
            "stage": "detect",
            "status": "ok",
            "detail": "found lock",
            "next": "clear",
        }

    def test_failed_returns_no_next(self):
        result = _failed("clear", "permission denied")
        assert result["status"] == "failed"
        assert result["next"] is None

    def test_skipped_has_next(self):
        result = _skipped("probe", "no lock to probe", "drain")
        assert result["status"] == "skipped"
        assert result["next"] == "drain"


# ---------------------------------------------------------------------------
# stage_detect
# ---------------------------------------------------------------------------


class TestStageDetect:
    """Tests for the detect stage."""

    def test_no_lock_is_ok_no_next(self, tmp_path: Path):
        """No lock means nothing to recover."""
        (tmp_path / ".git").mkdir(parents=True)
        result = stage_detect(tmp_path)
        assert result["status"] == "ok"
        assert result["next"] is None
        assert "no lock" in result["detail"]

    @patch("iamai.lock_recovery.detect_lock")
    def test_stale_lock_is_ok_with_next(self, mock_detect, tmp_path: Path):
        """Stale lock means we should proceed to clear."""
        mock_detect.return_value = {
            "locked": True,
            "path": tmp_path / ".git" / "index.lock",
            "age_seconds": 3600.0,
            "holder_pid": None,
            "stale": True,
        }
        result = stage_detect(tmp_path)
        assert result["status"] == "ok"
        assert result["next"] == "clear"
        assert "stale" in result["detail"]

    @patch("iamai.lock_recovery.detect_lock")
    def test_live_lock_is_failed(self, mock_detect, tmp_path: Path):
        """Lock held by live process means manual intervention needed."""
        mock_detect.return_value = {
            "locked": True,
            "path": tmp_path / ".git" / "index.lock",
            "age_seconds": 10.0,
            "holder_pid": 12345,
            "stale": False,
        }
        result = stage_detect(tmp_path)
        assert result["status"] == "failed"
        assert "12345" in result["detail"]


# ---------------------------------------------------------------------------
# stage_clear
# ---------------------------------------------------------------------------


class TestStageClear:
    """Tests for the clear stage."""

    @patch("iamai.lock_recovery.clear_stale_lock")
    def test_successful_clear(self, mock_clear, tmp_path: Path):
        """Successfully removing a lock."""
        mock_clear.return_value = {
            "removed": True,
            "reason": "stale lock removed (age 3600s)",
        }
        result = stage_clear(tmp_path)
        assert result["status"] == "ok"
        assert result["next"] == "probe"
        assert "removed" in result["detail"]

    @patch("iamai.lock_recovery.clear_stale_lock")
    def test_no_lock_to_clear(self, mock_clear, tmp_path: Path):
        """If no lock exists, clear is skipped."""
        mock_clear.return_value = {
            "removed": False,
            "reason": "no lock present",
        }
        result = stage_clear(tmp_path)
        assert result["status"] == "skipped"
        assert result["next"] == "probe"

    @patch("iamai.lock_recovery.clear_stale_lock")
    def test_clear_failure(self, mock_clear, tmp_path: Path):
        """If clear fails (e.g. permission), stage fails."""
        mock_clear.return_value = {
            "removed": False,
            "reason": "failed to remove: Permission denied",
        }
        result = stage_clear(tmp_path)
        assert result["status"] == "failed"
        assert result["next"] is None


# ---------------------------------------------------------------------------
# stage_probe
# ---------------------------------------------------------------------------


class TestStageProbe:
    """Tests for the probe stage."""

    @patch("iamai.lock_recovery.subprocess.run")
    def test_probe_success(self, mock_run, tmp_path: Path):
        """git status succeeds → probe ok."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = stage_probe(tmp_path)
        assert result["status"] == "ok"
        assert result["next"] == "drain"

    @patch("iamai.lock_recovery.subprocess.run")
    def test_probe_failure(self, mock_run, tmp_path: Path):
        """git status fails → probe failed."""
        mock_run.return_value = MagicMock(
            returncode=128, stdout="", stderr="fatal: not a git repository"
        )
        result = stage_probe(tmp_path)
        assert result["status"] == "failed"
        assert "not a git repository" in result["detail"]

    @patch("iamai.lock_recovery.subprocess.run")
    def test_probe_timeout(self, mock_run, tmp_path: Path):
        """git status hangs → probe failed."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=10)
        result = stage_probe(tmp_path, timeout=10)
        assert result["status"] == "failed"
        assert "timed out" in result["detail"]


# ---------------------------------------------------------------------------
# stage_drain
# ---------------------------------------------------------------------------


class TestStageDrain:
    """Tests for the drain stage."""

    @patch("iamai.lock_recovery.subprocess.run")
    def test_nothing_to_commit(self, mock_run, tmp_path: Path):
        """Empty working tree → drain skipped."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = stage_drain(tmp_path)
        assert result["status"] == "skipped"
        assert "nothing to commit" in result["detail"]

    @patch("iamai.lock_recovery.subprocess.run")
    def test_successful_commit(self, mock_run, tmp_path: Path):
        """Modified files → drain ok."""
        # First call: git status (has changes)
        # Second call: git add
        # Third call: git commit
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="M file.txt\n", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]
        result = stage_drain(tmp_path, message="test commit")
        assert result["status"] == "ok"
        assert result["next"] == "push"
        assert "1 file(s)" in result["detail"]

    @patch("iamai.lock_recovery.subprocess.run")
    def test_commit_failure(self, mock_run, tmp_path: Path):
        """git commit fails → drain failed."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="M file.txt\n", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="error: commit failed"),
        ]
        result = stage_drain(tmp_path)
        assert result["status"] == "failed"
        assert "commit failed" in result["detail"]


# ---------------------------------------------------------------------------
# stage_push
# ---------------------------------------------------------------------------


class TestStagePush:
    """Tests for the push stage."""

    @patch("iamai.lock_recovery.subprocess.run")
    def test_push_success(self, mock_run, tmp_path: Path):
        """git push succeeds → push ok."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = stage_push(tmp_path)
        assert result["status"] == "ok"
        assert result["next"] is None

    @patch("iamai.lock_recovery.subprocess.run")
    def test_push_already_uptodate(self, mock_run, tmp_path: Path):
        """Everything up-to-date → push skipped."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr="Everything up-to-date\n"
        )
        result = stage_push(tmp_path)
        assert result["status"] == "skipped"

    @patch("iamai.lock_recovery.subprocess.run")
    def test_push_failure(self, mock_run, tmp_path: Path):
        """git push fails → push failed."""
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: failed to push"
        )
        result = stage_push(tmp_path)
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# run_recovery (integration)
# ---------------------------------------------------------------------------


class TestRunRecovery:
    """Integration tests for the full recovery pipeline."""

    @patch("iamai.lock_recovery.stage_push")
    @patch("iamai.lock_recovery.stage_drain")
    @patch("iamai.lock_recovery.stage_probe")
    @patch("iamai.lock_recovery.stage_clear")
    @patch("iamai.lock_recovery.stage_detect")
    def test_full_recovery_success(
        self, mock_detect, mock_clear, mock_probe, mock_drain, mock_push, tmp_path
    ):
        """All stages succeed → verdict=recovered."""
        mock_detect.return_value = _ok("detect", "stale lock", "clear")
        mock_clear.return_value = _ok("clear", "removed", "probe")
        mock_probe.return_value = _ok("probe", "git ok", "drain")
        mock_drain.return_value = _ok("drain", "committed 5 files", "push")
        mock_push.return_value = _ok("push", "pushed", None)

        result = run_recovery(tmp_path)
        assert result["verdict"] == "recovered"
        assert result["failed_stage"] is None
        assert len(result["results"]) == 5

    @patch("iamai.lock_recovery.stage_push")
    @patch("iamai.lock_recovery.stage_drain")
    @patch("iamai.lock_recovery.stage_probe")
    @patch("iamai.lock_recovery.stage_clear")
    @patch("iamai.lock_recovery.stage_detect")
    def test_recovery_fails_at_probe(
        self, mock_detect, mock_clear, mock_probe, mock_drain, mock_push, tmp_path
    ):
        """Probe fails → pipeline stops, verdict=failed."""
        mock_detect.return_value = _ok("detect", "stale lock", "clear")
        mock_clear.return_value = _ok("clear", "removed", "probe")
        mock_probe.return_value = _failed("probe", "git broken")

        result = run_recovery(tmp_path)
        assert result["verdict"] == "failed"
        assert result["failed_stage"] == "probe"
        assert len(result["results"]) == 3  # detect, clear, probe

    @patch("iamai.lock_recovery.stage_detect")
    def test_no_lock_is_clean(self, mock_detect, tmp_path):
        """No lock to begin with → verdict=clean (all ok/skipped)."""
        mock_detect.return_value = _ok("detect", "no lock", None)
        result = run_recovery(tmp_path)
        assert result["verdict"] == "clean"
        assert len(result["results"]) == 1


# ---------------------------------------------------------------------------
# recovery_summary
# ---------------------------------------------------------------------------


class TestRecoverySummary:
    """Tests for the summary formatter."""

    def test_successful_summary(self):
        recovery = {
            "results": [
                _ok("detect", "x", "clear"),
                _ok("clear", "y", "probe"),
                _ok("probe", "z", "drain"),
                _ok("drain", "w", "push"),
                _ok("push", "v", None),
            ],
            "verdict": "recovered",
            "failed_stage": None,
        }
        summary = recovery_summary(recovery)
        assert "detect=ok" in summary
        assert "recovered" in summary

    def test_failed_summary(self):
        recovery = {
            "results": [
                _ok("detect", "x", "clear"),
                _ok("clear", "y", "probe"),
                _failed("probe", "git broken"),
            ],
            "verdict": "failed",
            "failed_stage": "probe",
        }
        summary = recovery_summary(recovery)
        assert "probe=failed" in summary
        assert "stopped at probe" in summary
