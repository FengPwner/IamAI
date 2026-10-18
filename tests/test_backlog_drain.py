"""Tests for iamai.backlog_drain — backlog consumption rate tracking."""

from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.backlog_drain import (
    Snapshot,
    classify,
    drain_rate,
    drain_report,
    snapshot,
)


# ---------------------------------------------------------------------------
# snapshot()
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_returns_dict_with_count_and_at(self, tmp_path: Path):
        # fake git repo
        (tmp_path / ".git").mkdir()
        with patch("iamai.backlog_drain.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = " M file1.py\n M file2.py\n"
            s = snapshot(tmp_path, at=1000.0)
        assert s["count"] == 2
        assert s["at"] == 1000.0

    def test_empty_working_tree(self, tmp_path: Path):
        with patch("iamai.backlog_drain.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            s = snapshot(tmp_path)
        assert s["count"] == 0

    def test_git_error_returns_negative_one(self, tmp_path: Path):
        with patch("iamai.backlog_drain.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128
            mock_run.return_value.stdout = ""
            s = snapshot(tmp_path)
        assert s["count"] == -1

    def test_subprocess_exception(self, tmp_path: Path):
        with patch("iamai.backlog_drain.subprocess.run", side_effect=OSError):
            s = snapshot(tmp_path)
        assert s["count"] == -1

    def test_default_timestamp_is_recent(self, tmp_path: Path):
        with patch("iamai.backlog_drain.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            s = snapshot(tmp_path)
        assert s["at"] > 0


# ---------------------------------------------------------------------------
# drain_rate()
# ---------------------------------------------------------------------------

class TestDrainRate:
    def test_empty_list(self):
        assert drain_rate([]) == 0.0

    def test_single_snapshot(self):
        assert drain_rate([{"count": 5, "at": 0.0}]) == 0.0

    def test_perfect_drain(self):
        """Backlog shrinking at 2 files/minute."""
        snapshots = [
            {"count": 20, "at": 0.0},
            {"count": 18, "at": 60.0},   # -2 fpm
            {"count": 16, "at": 120.0},  # -2 fpm
        ]
        rate = drain_rate(snapshots)
        assert rate == pytest.approx(-2.0, abs=0.01)

    def test_perfect_growth(self):
        """Backlog growing at 3 files/minute."""
        snapshots = [
            {"count": 0, "at": 0.0},
            {"count": 3, "at": 60.0},
            {"count": 6, "at": 120.0},
        ]
        rate = drain_rate(snapshots)
        assert rate == pytest.approx(3.0, abs=0.01)

    def test_steady(self):
        """Backlog unchanged."""
        snapshots = [
            {"count": 9, "at": 0.0},
            {"count": 9, "at": 60.0},
            {"count": 9, "at": 120.0},
        ]
        assert drain_rate(snapshots) == pytest.approx(0.0, abs=0.01)

    def test_excludes_negative_counts(self):
        """Git errors (count=-1) are filtered out."""
        snapshots = [
            {"count": 10, "at": 0.0},
            {"count": -1, "at": 30.0},   # git error, skipped
            {"count": 8, "at": 60.0},
        ]
        rate = drain_rate(snapshots)
        assert rate == pytest.approx(-2.0, abs=0.01)

    def test_all_same_timestamp(self):
        """Zero time span → 0.0."""
        snapshots = [
            {"count": 5, "at": 100.0},
            {"count": 10, "at": 100.0},
        ]
        assert drain_rate(snapshots) == 0.0

    def test_noisy_drain(self):
        """Imperfect but generally draining — regression smooths it."""
        snapshots = [
            {"count": 30, "at": 0.0},
            {"count": 28, "at": 60.0},
            {"count": 31, "at": 120.0},   # hiccup
            {"count": 25, "at": 180.0},
            {"count": 22, "at": 240.0},
        ]
        rate = drain_rate(snapshots)
        # Overall trend is negative
        assert rate < 0

    def test_two_snapshots_sufficient(self):
        snapshots = [
            {"count": 10, "at": 0.0},
            {"count": 5, "at": 60.0},
        ]
        assert drain_rate(snapshots) == pytest.approx(-5.0, abs=0.01)


# ---------------------------------------------------------------------------
# classify()
# ---------------------------------------------------------------------------

class TestClassify:
    def test_draining(self):
        assert classify(-1.5) == "draining"
        assert classify(-10.0) == "draining"

    def test_steady(self):
        assert classify(0.0) == "steady"
        assert classify(-1.0) == "steady"
        assert classify(1.0) == "steady"
        assert classify(0.5) == "steady"

    def test_growing(self):
        assert classify(1.1) == "growing"
        assert classify(5.0) == "growing"


# ---------------------------------------------------------------------------
# drain_report()
# ---------------------------------------------------------------------------

class TestDrainReport:
    def test_basic_report(self, tmp_path: Path):
        snapshots = [
            {"count": 30, "at": 0.0},
            {"count": 10, "at": 600.0},
        ]
        with patch("iamai.backlog_drain.snapshot", return_value={"count": 10, "at": 600.0}):
            report = drain_report(tmp_path, snapshots)
        assert "draining" in report
        assert "10 files pending" in report

    def test_growing_report(self, tmp_path: Path):
        snapshots = [
            {"count": 0, "at": 0.0},
            {"count": 15, "at": 300.0},
        ]
        with patch("iamai.backlog_drain.snapshot", return_value={"count": 15, "at": 300.0}):
            report = drain_report(tmp_path, snapshots)
        assert "growing" in report
        assert "15 files pending" in report

    def test_empty_history(self, tmp_path: Path):
        with patch("iamai.backlog_drain.snapshot", return_value={"count": 5, "at": 0.0}):
            report = drain_report(tmp_path, [])
        assert "steady" in report
        assert "5 files pending" in report
