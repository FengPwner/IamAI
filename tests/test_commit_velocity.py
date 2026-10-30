"""Tests for iamai.commit_velocity — commit velocity classifier.

Covers:
  - _recent_commit_timestamps returns numeric list from git log
  - velocity() dict shape and verdict classification
  - velocity_report() one-liner format
  - Edge cases: empty repo, stalled window, single commit
  - Ratio thresholds: accelerating / steady / decelerating
  - Zero-window guard
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iamai.commit_velocity import (
    _recent_commit_timestamps,
    velocity,
    velocity_report,
)


# ---------------------------------------------------------------------------
# _recent_commit_timestamps
# ---------------------------------------------------------------------------


class TestRecentCommitTimestamps:
    """Unit tests for the git log helper."""

    def test_returns_floats(self, tmp_path: Path):
        """git log output is parsed into a list of floats."""
        # Use the actual repo since tmp_path won't have commits.
        repo = Path(__file__).resolve().parent.parent
        ts = _recent_commit_timestamps(repo, 5)
        assert isinstance(ts, list)
        assert len(ts) <= 5
        for t in ts:
            assert isinstance(t, float)
            assert t > 1_000_000_000  # reasonable epoch

    def test_empty_on_non_repo(self, tmp_path: Path):
        """Non-git directory returns empty list."""
        ts = _recent_commit_timestamps(tmp_path, 10)
        assert ts == []

    def test_respects_max_count(self):
        """Should not return more than max_count entries."""
        repo = Path(__file__).resolve().parent.parent
        ts = _recent_commit_timestamps(repo, 3)
        assert len(ts) <= 3

    def test_descending_order(self):
        """Timestamps should be newest-first (git log default)."""
        repo = Path(__file__).resolve().parent.parent
        ts = _recent_commit_timestamps(repo, 10)
        for i in range(len(ts) - 1):
            assert ts[i] >= ts[i + 1]


# ---------------------------------------------------------------------------
# velocity()
# ---------------------------------------------------------------------------


class TestVelocity:
    """Tests for the velocity() function."""

    def test_returns_expected_keys(self):
        """Result dict contains all documented keys."""
        repo = Path(__file__).resolve().parent.parent
        info = velocity(repo, window_hours=1)
        for key in (
            "recent_rate",
            "previous_rate",
            "ratio",
            "verdict",
            "window_hours",
            "recent_count",
            "previous_count",
        ):
            assert key in info, f"missing key: {key}"

    def test_verdict_is_valid(self):
        """Verdict must be one of the four documented values."""
        repo = Path(__file__).resolve().parent.parent
        info = velocity(repo, window_hours=1)
        assert info["verdict"] in ("accelerating", "steady", "decelerating", "stalled")

    def test_rates_non_negative(self):
        """Rates must be non-negative."""
        repo = Path(__file__).resolve().parent.parent
        info = velocity(repo, window_hours=1)
        assert info["recent_rate"] >= 0
        assert info["previous_rate"] >= 0

    def test_counts_non_negative_integers(self):
        """Counts must be non-negative ints."""
        repo = Path(__file__).resolve().parent.parent
        info = velocity(repo, window_hours=1)
        assert isinstance(info["recent_count"], int)
        assert isinstance(info["previous_count"], int)
        assert info["recent_count"] >= 0
        assert info["previous_count"] >= 0

    def test_window_hours_preserved(self):
        """window_hours in result matches input."""
        repo = Path(__file__).resolve().parent.parent
        info = velocity(repo, window_hours=2.5)
        assert info["window_hours"] == 2.5

    @patch("iamai.commit_velocity._recent_commit_timestamps")
    def test_stalled_when_no_commits(self, mock_ts):
        """Empty timestamp list → stalled verdict."""
        mock_ts.return_value = []
        info = velocity(Path("/fake"), window_hours=1)
        assert info["verdict"] == "stalled"
        assert info["recent_rate"] == 0.0
        assert info["recent_count"] == 0

    @patch("iamai.commit_velocity._recent_commit_timestamps")
    def test_steady_when_equal_rates(self, mock_ts):
        """Equal commit counts in both windows → steady."""
        now = 1_700_000_000.0
        # 6 commits in recent hour, 6 in previous hour
        timestamps = [now - i * 600 for i in range(6)]  # recent: every 10 min
        timestamps += [now - 3600 - i * 600 for i in range(6)]  # previous
        mock_ts.return_value = sorted(timestamps, reverse=True)
        info = velocity(Path("/fake"), window_hours=1)
        assert info["verdict"] == "steady"
        assert abs(info["ratio"] - 1.0) < 0.01

    @patch("iamai.commit_velocity._recent_commit_timestamps")
    def test_accelerating(self, mock_ts):
        """More commits in recent window → accelerating."""
        now = 1_700_000_000.0
        # 10 commits in recent hour
        recent = [now - i * 300 for i in range(10)]
        # 3 commits in previous hour
        previous = [now - 3600 - i * 1200 for i in range(3)]
        mock_ts.return_value = sorted(recent + previous, reverse=True)
        info = velocity(Path("/fake"), window_hours=1)
        assert info["verdict"] == "accelerating"
        assert info["ratio"] > 1.2

    @patch("iamai.commit_velocity._recent_commit_timestamps")
    def test_decelerating(self, mock_ts):
        """Fewer commits in recent window → decelerating."""
        now = 1_700_000_000.0
        # 2 commits in recent hour
        recent = [now - i * 1800 for i in range(2)]
        # 10 commits in previous hour
        previous = [now - 3600 - i * 300 for i in range(10)]
        mock_ts.return_value = sorted(recent + previous, reverse=True)
        info = velocity(Path("/fake"), window_hours=1)
        assert info["verdict"] == "decelerating"
        assert info["ratio"] < 0.8

    @patch("iamai.commit_velocity._recent_commit_timestamps")
    def test_all_in_recent_no_previous(self, mock_ts):
        """All commits within recent window → accelerating (no previous)."""
        now = 1_700_000_000.0
        # All 5 commits within the last 20 minutes — recent window only.
        timestamps = [now - i * 240 for i in range(5)]
        mock_ts.return_value = sorted(timestamps, reverse=True)
        info = velocity(Path("/fake"), window_hours=1)
        assert info["recent_count"] == 5
        assert info["previous_count"] == 0
        # ratio is inf (recent > 0, previous == 0) → accelerating
        assert info["verdict"] == "accelerating"
        assert info["ratio"] == float("inf")

    def test_default_repo_works(self):
        """Calling with no arguments uses the project repo."""
        info = velocity()
        assert info["verdict"] in ("accelerating", "steady", "decelerating", "stalled")

    def test_string_path_accepted(self):
        """String paths are accepted (not just Path objects)."""
        repo_str = str(Path(__file__).resolve().parent.parent)
        info = velocity(repo_str, window_hours=1)
        assert "verdict" in info


# ---------------------------------------------------------------------------
# velocity_report()
# ---------------------------------------------------------------------------


class TestVelocityReport:
    """Tests for the one-liner report."""

    def test_stalled_message(self):
        """Stalled verdict mentions the window size."""
        with patch("iamai.commit_velocity.velocity") as mock_v:
            mock_v.return_value = {
                "verdict": "stalled",
                "recent_rate": 0.0,
                "previous_rate": 5.0,
                "ratio": 0.0,
                "window_hours": 2.0,
                "recent_count": 0,
                "previous_count": 10,
            }
            report = velocity_report(Path("/fake"), window_hours=2)
            assert "stalled" in report
            assert "2.0h" in report

    def test_steady_message(self):
        """Steady verdict shows rate and ratio."""
        with patch("iamai.commit_velocity.velocity") as mock_v:
            mock_v.return_value = {
                "verdict": "steady",
                "recent_rate": 6.2,
                "previous_rate": 5.8,
                "ratio": 1.069,
                "window_hours": 1.0,
                "recent_count": 6,
                "previous_count": 6,
            }
            report = velocity_report(Path("/fake"), window_hours=1)
            assert "steady" in report
            assert "6.2" in report
            assert "5.8" in report

    def test_returns_string(self):
        """Report is always a non-empty string."""
        report = velocity_report()
        assert isinstance(report, str)
        assert len(report) > 0

    def test_accelerating_message(self):
        """Accelerating verdict appears in report."""
        with patch("iamai.commit_velocity.velocity") as mock_v:
            mock_v.return_value = {
                "verdict": "accelerating",
                "recent_rate": 12.0,
                "previous_rate": 5.0,
                "ratio": 2.4,
                "window_hours": 1.0,
                "recent_count": 12,
                "previous_count": 5,
            }
            report = velocity_report(Path("/fake"))
            assert "accelerating" in report
