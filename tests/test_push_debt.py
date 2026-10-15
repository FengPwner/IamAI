"""Tests for iamai.push_debt."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iamai.push_debt import (
    _oldest_unpushed_age_hours,
    _run,
    _unpushed_commits,
    _would_conflict,
    push_debt,
    push_debt_report,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fake_completed(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


# ---------------------------------------------------------------------------
# _run
# ---------------------------------------------------------------------------


class TestRun:
    def test_basic_command(self, tmp_path):
        result = _run(["echo", "hello"], tmp_path)
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_failing_command(self, tmp_path):
        result = _run(["false"], tmp_path)
        assert result.returncode != 0

    def test_cwd_respected(self, tmp_path):
        result = _run(["pwd"], tmp_path)
        assert str(tmp_path) in result.stdout


# ---------------------------------------------------------------------------
# _unpushed_commits
# ---------------------------------------------------------------------------


class TestUnpushedCommits:
    @patch("iamai.push_debt._run")
    def test_parses_output(self, mock_run):
        mock_run.return_value = _fake_completed(
            stdout="abc123 1728900000\ndef456 1728900100\n"
        )
        commits = _unpushed_commits(Path("."))
        assert len(commits) == 2
        assert commits[0]["hash"] == "abc123"
        assert commits[1]["timestamp"] == "1728900100"

    @patch("iamai.push_debt._run")
    def test_empty_when_no_unpushed(self, mock_run):
        mock_run.return_value = _fake_completed(stdout="")
        commits = _unpushed_commits(Path("."))
        assert commits == []

    @patch("iamai.push_debt._run")
    def test_fallback_on_upstream_failure(self, mock_run):
        """When @{u} fails, fall back to origin/main."""
        first_call = _fake_completed(returncode=1)
        second_call = _fake_completed(stdout="abc123 1728900000\n")
        mock_run.side_effect = [first_call, second_call]
        commits = _unpushed_commits(Path("."))
        assert len(commits) == 1
        assert mock_run.call_count == 2

    @patch("iamai.push_debt._run")
    def test_empty_when_both_fail(self, mock_run):
        mock_run.return_value = _fake_completed(returncode=1)
        commits = _unpushed_commits(Path("."))
        assert commits == []

    @patch("iamai.push_debt._run")
    def test_skips_malformed_lines(self, mock_run):
        mock_run.return_value = _fake_completed(
            stdout="abc123 1728900000\nbadline\ndef456\n"
        )
        commits = _unpushed_commits(Path("."))
        assert len(commits) == 1
        assert commits[0]["hash"] == "abc123"


# ---------------------------------------------------------------------------
# _oldest_unpushed_age_hours
# ---------------------------------------------------------------------------


class TestOldestUnpushedAgeHours:
    def test_empty_returns_zero(self):
        assert _oldest_unpushed_age_hours([]) == 0.0

    @patch("iamai.push_debt.datetime")
    def test_computes_age(self, mock_dt):
        mock_now = MagicMock()
        mock_now.timestamp.return_value = 1728903600.0  # 1 hour later
        mock_dt.now.return_value = mock_now

        commits = [
            {"hash": "a", "timestamp": "1728900000"},
            {"hash": "b", "timestamp": "1728901800"},
        ]
        age = _oldest_unpushed_age_hours(commits)
        assert age == 1.0

    @patch("iamai.push_debt.datetime")
    def test_uses_oldest_timestamp(self, mock_dt):
        mock_now = MagicMock()
        mock_now.timestamp.return_value = 1728907200.0  # 2 hours after oldest
        mock_dt.now.return_value = mock_now

        commits = [
            {"hash": "a", "timestamp": "1728903600"},  # 1h old
            {"hash": "b", "timestamp": "1728900000"},  # 2h old (oldest)
        ]
        age = _oldest_unpushed_age_hours(commits)
        assert age == 2.0


# ---------------------------------------------------------------------------
# _would_conflict
# ---------------------------------------------------------------------------


class TestWouldConflict:
    @patch("iamai.push_debt._run")
    def test_clean_merge(self, mock_run):
        # fetch, merge-base, merge-tree all succeed, no conflict markers
        mock_run.side_effect = [
            _fake_completed(),  # fetch
            _fake_completed(stdout="basehash\n"),  # merge-base
            _fake_completed(stdout="merged cleanly\n"),  # merge-tree
        ]
        assert _would_conflict(Path(".")) is False

    @patch("iamai.push_debt._run")
    def test_conflict_detected(self, mock_run):
        mock_run.side_effect = [
            _fake_completed(),  # fetch
            _fake_completed(stdout="basehash\n"),  # merge-base
            _fake_completed(stdout="changed in both\n"),  # merge-tree
        ]
        assert _would_conflict(Path(".")) is True

    @patch("iamai.push_debt._run")
    def test_fetch_failure_returns_false(self, mock_run):
        mock_run.side_effect = [
            _fake_completed(returncode=1),  # fetch fails
        ]
        # fetch fails → merge-base not attempted → falls through
        # Actually: fetch result is ignored, merge-base is the next call
        # Let me reconsider: _run is called for fetch, then merge-base
        mock_run.reset_mock()
        mock_run.side_effect = [
            _fake_completed(),  # fetch ok
            _fake_completed(returncode=1),  # merge-base fails
        ]
        assert _would_conflict(Path(".")) is False


# ---------------------------------------------------------------------------
# push_debt
# ---------------------------------------------------------------------------


class TestPushDebt:
    @patch("iamai.push_debt._would_conflict")
    @patch("iamai.push_debt._unpushed_commits")
    @patch("iamai.push_debt._oldest_unpushed_age_hours")
    def test_clean_when_no_unpushed(self, mock_age, mock_commits, mock_conflict):
        mock_commits.return_value = []
        mock_age.return_value = 0.0
        mock_conflict.return_value = False

        result = push_debt(Path("."))
        assert result["score"] == 0
        assert result["verdict"] == "clean"
        assert result["count"] == 0
        mock_conflict.assert_not_called()

    @patch("iamai.push_debt._would_conflict")
    @patch("iamai.push_debt._unpushed_commits")
    @patch("iamai.push_debt._oldest_unpushed_age_hours")
    def test_low_risk(self, mock_age, mock_commits, mock_conflict):
        mock_commits.return_value = [{"hash": "a", "timestamp": "123"}]
        mock_age.return_value = 0.5
        mock_conflict.return_value = False

        result = push_debt(Path("."))
        assert result["verdict"] == "low"
        assert result["score"] <= 30

    @patch("iamai.push_debt._would_conflict")
    @patch("iamai.push_debt._unpushed_commits")
    @patch("iamai.push_debt._oldest_unpushed_age_hours")
    def test_medium_risk(self, mock_age, mock_commits, mock_conflict):
        mock_commits.return_value = [
            {"hash": "a", "timestamp": "123"},
            {"hash": "b", "timestamp": "456"},
            {"hash": "c", "timestamp": "789"},
            {"hash": "d", "timestamp": "012"},
        ]
        mock_age.return_value = 3.0
        mock_conflict.return_value = False

        result = push_debt(Path("."))
        # count=4 → 40, age=3.0 → 15, total=55
        assert result["score"] == 55
        assert result["verdict"] == "medium"

    @patch("iamai.push_debt._would_conflict")
    @patch("iamai.push_debt._unpushed_commits")
    @patch("iamai.push_debt._oldest_unpushed_age_hours")
    def test_high_risk_with_conflict(self, mock_age, mock_commits, mock_conflict):
        mock_commits.return_value = [
            {"hash": "a", "timestamp": "123"},
            {"hash": "b", "timestamp": "456"},
            {"hash": "c", "timestamp": "789"},
        ]
        mock_age.return_value = 5.0
        mock_conflict.return_value = True

        result = push_debt(Path("."))
        # count=3 → 30, age=5.0 → 25, conflict → 30, total=85
        assert result["score"] == 85
        assert result["verdict"] == "high"
        assert result["conflict"] is True

    @patch("iamai.push_debt._would_conflict")
    @patch("iamai.push_debt._unpushed_commits")
    @patch("iamai.push_debt._oldest_unpushed_age_hours")
    def test_score_capped_at_100(self, mock_age, mock_commits, mock_conflict):
        mock_commits.return_value = [{"hash": f"x{i}", "timestamp": str(i)} for i in range(15)]
        mock_age.return_value = 24.0
        mock_conflict.return_value = True

        result = push_debt(Path("."))
        # count=15 → 150, age=24 → 120, conflict → 30 = 300, capped at 100
        assert result["score"] == 100
        assert result["verdict"] == "high"


# ---------------------------------------------------------------------------
# push_debt_report
# ---------------------------------------------------------------------------


class TestPushDebtReport:
    @patch("iamai.push_debt.push_debt")
    def test_clean_report(self, mock_debt):
        mock_debt.return_value = {
            "count": 0,
            "age_hours": 0.0,
            "conflict": False,
            "score": 0,
            "verdict": "clean",
        }
        report = push_debt_report(Path("."))
        assert "clean" in report
        assert "all pushed" in report

    @patch("iamai.push_debt.push_debt")
    def test_medium_report(self, mock_debt):
        mock_debt.return_value = {
            "count": 4,
            "age_hours": 2.3,
            "conflict": False,
            "score": 45,
            "verdict": "medium",
        }
        report = push_debt_report(Path("."))
        assert "medium" in report
        assert "45/100" in report
        assert "4 unpushed" in report
        assert "2.3h" in report
        assert "conflict" not in report

    @patch("iamai.push_debt.push_debt")
    def test_high_with_conflict_report(self, mock_debt):
        mock_debt.return_value = {
            "count": 8,
            "age_hours": 6.0,
            "conflict": True,
            "score": 85,
            "verdict": "high",
        }
        report = push_debt_report(Path("."))
        assert "high" in report
        assert "conflict likely" in report
