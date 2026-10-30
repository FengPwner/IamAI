"""Tests for iamai.commit_lag."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.commit_lag import commit_lag, commit_lag_report, _recent_commit_times


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_times(seconds_ago: list[float]) -> list[datetime]:
    """Build a list of datetimes from relative offsets (newest first)."""
    now = datetime(2026, 10, 15, 2, 0, 0, tzinfo=timezone.utc)
    return [now - timedelta(seconds=s) for s in seconds_ago]


def _mock_git_log(times: list[datetime]):
    """Return a mock for subprocess.check_output that emits ISO timestamps."""
    lines = "\n".join(t.isoformat() for t in times)

    def fake_check_output(cmd, **kwargs):
        return lines.encode("utf-8")

    return fake_check_output


# ---------------------------------------------------------------------------
# _recent_commit_times
# ---------------------------------------------------------------------------

class TestRecentCommitTimes:
    def test_parses_iso_output(self, tmp_path: Path):
        times = _make_times([0, 600, 1200])
        with patch("subprocess.check_output", side_effect=_mock_git_log(times)):
            result = _recent_commit_times(tmp_path, count=3)
        assert len(result) == 3
        assert result[0] > result[1] > result[2]

    def test_empty_on_git_failure(self, tmp_path: Path):
        def fail(*args, **kwargs):
            raise subprocess.CalledProcessError(128, "git")

        with patch("subprocess.check_output", side_effect=fail):
            result = _recent_commit_times(tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# commit_lag
# ---------------------------------------------------------------------------

class TestCommitLag:
    def test_healthy_uniform_gaps(self, tmp_path: Path):
        # 5 commits, 600s apart → median = 600 < 900 threshold
        times = _make_times([0, 600, 1200, 1800, 2400, 3000])
        with patch("subprocess.check_output", side_effect=_mock_git_log(times)):
            info = commit_lag(tmp_path, count=5)

        assert info["healthy"] is True
        assert info["median_gap_s"] == pytest.approx(600.0, abs=1)
        assert info["max_gap_s"] == pytest.approx(600.0, abs=1)
        assert info["commit_count"] == 6
        assert len(info["gaps"]) == 5

    def test_unhealthy_large_median(self, tmp_path: Path):
        # 5 commits, 1200s apart → median = 1200 > 900 threshold
        times = _make_times([0, 1200, 2400, 3600, 4800, 6000])
        with patch("subprocess.check_output", side_effect=_mock_git_log(times)):
            info = commit_lag(tmp_path, count=5, threshold_seconds=900.0)

        assert info["healthy"] is False
        assert info["median_gap_s"] == pytest.approx(1200.0, abs=1)

    def test_custom_threshold(self, tmp_path: Path):
        times = _make_times([0, 300, 600, 900])
        with patch("subprocess.check_output", side_effect=_mock_git_log(times)):
            info = commit_lag(tmp_path, count=3, threshold_seconds=400.0)

        assert info["healthy"] is True
        assert info["median_gap_s"] == pytest.approx(300.0, abs=1)

    def test_too_few_commits(self, tmp_path: Path):
        times = _make_times([0])
        with patch("subprocess.check_output", side_effect=_mock_git_log(times)):
            info = commit_lag(tmp_path, count=5)

        assert info["healthy"] is False
        assert info["median_gap_s"] == float("inf")
        assert info["commit_count"] == 1

    def test_zero_commits(self, tmp_path: Path):
        with patch("subprocess.check_output", side_effect=_mock_git_log([])):
            info = commit_lag(tmp_path, count=5)

        assert info["healthy"] is False
        assert info["gaps"] == []

    def test_uneven_gaps_picks_median(self, tmp_path: Path):
        # gaps: 100, 200, 1000, 200, 100 → sorted: 100, 100, 200, 200, 1000
        # median = 200
        times = _make_times([0, 100, 300, 1300, 1500, 1600])
        with patch("subprocess.check_output", side_effect=_mock_git_log(times)):
            info = commit_lag(tmp_path, count=5, threshold_seconds=900.0)

        assert info["median_gap_s"] == pytest.approx(200.0, abs=1)
        assert info["max_gap_s"] == pytest.approx(1000.0, abs=1)
        assert info["healthy"] is True

    def test_even_count_median(self, tmp_path: Path):
        # 4 commits → 3 gaps: 100, 500, 900 → sorted: 100, 500, 900
        # median (odd count of gaps) = 500
        times = _make_times([0, 100, 600, 1500])
        with patch("subprocess.check_output", side_effect=_mock_git_log(times)):
            info = commit_lag(tmp_path, count=3)

        assert info["median_gap_s"] == pytest.approx(500.0, abs=1)

    def test_even_gap_count_median(self, tmp_path: Path):
        # 3 commits → 2 gaps: 200, 800 → median = (200+800)/2 = 500
        times = _make_times([0, 200, 1000])
        with patch("subprocess.check_output", side_effect=_mock_git_log(times)):
            info = commit_lag(tmp_path, count=2)

        assert info["median_gap_s"] == pytest.approx(500.0, abs=1)


# ---------------------------------------------------------------------------
# commit_lag_report
# ---------------------------------------------------------------------------

class TestCommitLagReport:
    def test_healthy_report(self, tmp_path: Path):
        times = _make_times([0, 600, 1200, 1800])
        with patch("subprocess.check_output", side_effect=_mock_git_log(times)):
            report = commit_lag_report(tmp_path, count=3)

        assert "healthy" in report
        assert "600s" in report

    def test_lagging_report(self, tmp_path: Path):
        times = _make_times([0, 1500, 3000, 4500])
        with patch("subprocess.check_output", side_effect=_mock_git_log(times)):
            report = commit_lag_report(tmp_path, count=3, threshold_seconds=900.0)

        assert "lagging" in report
        assert "1500s" in report

    def test_not_enough_commits(self, tmp_path: Path):
        with patch("subprocess.check_output", side_effect=_mock_git_log([])):
            report = commit_lag_report(tmp_path)

        assert "not enough commits" in report
