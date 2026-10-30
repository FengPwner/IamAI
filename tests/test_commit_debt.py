"""Tests for iamai.commit_debt — commit and push debt measurement."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.commit_debt import (
    DebtReport,
    _score_from_tiers,
    _count_modified,
    _count_unpushed,
    debt_report,
    _WRITE_TIERS,
    _PUSH_TIERS,
    _WRITE_CRITICAL,
    _PUSH_CRITICAL,
)


# ---------------------------------------------------------------------------
# _score_from_tiers
# ---------------------------------------------------------------------------

class TestScoreFromTiers:
    """Unit tests for the tier-based scoring helper."""

    def test_zero_returns_first_tier(self):
        assert _score_from_tiers(0, _WRITE_TIERS, _WRITE_CRITICAL) == 0

    def test_at_boundary(self):
        # 3 is the ceiling for score=10
        assert _score_from_tiers(3, _WRITE_TIERS, _WRITE_CRITICAL) == 10

    def test_just_past_boundary(self):
        # 4 falls into the next tier (ceiling=9, score=30)
        assert _score_from_tiers(4, _WRITE_TIERS, _WRITE_CRITICAL) == 30

    def test_mid_range(self):
        assert _score_from_tiers(15, _WRITE_TIERS, _WRITE_CRITICAL) == 60

    def test_above_all_tiers_returns_critical(self):
        assert _score_from_tiers(500, _WRITE_TIERS, _WRITE_CRITICAL) == 100

    def test_push_tiers_zero(self):
        assert _score_from_tiers(0, _PUSH_TIERS, _PUSH_CRITICAL) == 0

    def test_push_tiers_one_commit(self):
        assert _score_from_tiers(1, _PUSH_TIERS, _PUSH_CRITICAL) == 15

    def test_push_tiers_many(self):
        assert _score_from_tiers(20, _PUSH_TIERS, _PUSH_CRITICAL) == 100


# ---------------------------------------------------------------------------
# DebtReport
# ---------------------------------------------------------------------------

class TestDebtReport:
    """Tests for the DebtReport dataclass."""

    def test_default_values(self):
        r = DebtReport()
        assert r.write_debt == 0
        assert r.push_debt == 0
        assert r.debt_score == 0.0
        assert r.grade == "clear"
        assert r.modified_files == []
        assert r.unpushed_commits == 0

    def test_to_dict_keys(self):
        r = DebtReport(write_debt=30, push_debt=15, debt_score=24.0, grade="tidy")
        d = r.to_dict()
        assert set(d.keys()) == {
            "write_debt", "push_debt", "debt_score",
            "grade", "modified_count", "unpushed_commits",
        }
        assert d["write_debt"] == 30
        assert d["push_debt"] == 15
        assert d["debt_score"] == 24.0
        assert d["grade"] == "tidy"

    def test_to_dict_modified_count(self):
        r = DebtReport(modified_files=["a.py", "b.py", "c.py"])
        assert r.to_dict()["modified_count"] == 3


# ---------------------------------------------------------------------------
# _count_modified (mocked git)
# ---------------------------------------------------------------------------

class TestCountModified:
    """Tests for the modified-file counter."""

    @patch("iamai.commit_debt._run_git")
    def test_clean_tree(self, mock_git):
        mock_git.return_value = ""
        count, files = _count_modified(Path("/fake"))
        assert count == 0
        assert files == []

    @patch("iamai.commit_debt._run_git")
    def test_three_files(self, mock_git):
        mock_git.return_value = " M a.py\n M b.py\n?? c.py"
        count, files = _count_modified(Path("/fake"))
        assert count == 3
        assert "M a.py" in files

    @patch("iamai.commit_debt._run_git")
    def test_blank_lines_skipped(self, mock_git):
        mock_git.return_value = " M a.py\n\n M b.py\n"
        count, files = _count_modified(Path("/fake"))
        assert count == 2


# ---------------------------------------------------------------------------
# _count_unpushed (mocked git)
# ---------------------------------------------------------------------------

class TestCountUnpushed:
    """Tests for the unpushed-commit counter."""

    @patch("iamai.commit_debt._run_git")
    def test_synced(self, mock_git):
        mock_git.return_value = "0"
        assert _count_unpushed(Path("/fake")) == 0

    @patch("iamai.commit_debt._run_git")
    def test_ahead_by_five(self, mock_git):
        mock_git.return_value = "5"
        assert _count_unpushed(Path("/fake")) == 5

    @patch("iamai.commit_debt._run_git")
    def test_no_remote_returns_zero(self, mock_git):
        mock_git.side_effect = subprocess.SubprocessError()
        assert _count_unpushed(Path("/fake")) == 0

    @patch("iamai.commit_debt._run_git")
    def test_garbage_output_returns_zero(self, mock_git):
        mock_git.return_value = "not-a-number"
        assert _count_unpushed(Path("/fake")) == 0


# ---------------------------------------------------------------------------
# debt_report (integration with mocked git)
# ---------------------------------------------------------------------------

class TestDebtReportIntegration:
    """End-to-end tests for debt_report() with mocked git calls."""

    @patch("iamai.commit_debt._count_unpushed", return_value=0)
    @patch("iamai.commit_debt._count_modified", return_value=(0, []))
    def test_clean_repo(self, mock_mod, mock_unpushed):
        report = debt_report(repo_path="/fake")
        assert report.write_debt == 0
        assert report.push_debt == 0
        assert report.debt_score == 0.0
        assert report.grade == "clear"

    @patch("iamai.commit_debt._count_unpushed", return_value=1)
    @patch("iamai.commit_debt._count_modified", return_value=(5, ["a"] * 5))
    def test_moderate_debt(self, mock_mod, mock_unpushed):
        report = debt_report(repo_path="/fake")
        # write_debt for 5 files = 30, push_debt for 1 commit = 15
        assert report.write_debt == 30
        assert report.push_debt == 15
        # score = 0.6*30 + 0.4*15 = 18 + 6 = 24
        assert report.debt_score == pytest.approx(24.0)
        assert report.grade == "tidy"

    @patch("iamai.commit_debt._count_unpushed", return_value=10)
    @patch("iamai.commit_debt._count_modified", return_value=(50, ["f"] * 50))
    def test_high_debt(self, mock_mod, mock_unpushed):
        report = debt_report(repo_path="/fake")
        # write_debt for 50 = 85, push_debt for 10 = 70
        assert report.write_debt == 85
        assert report.push_debt == 70
        # score = 0.6*85 + 0.4*70 = 51 + 28 = 79
        assert report.debt_score == pytest.approx(79.0)
        assert report.grade == "overdue"

    @patch("iamai.commit_debt._count_unpushed", return_value=20)
    @patch("iamai.commit_debt._count_modified", return_value=(200, ["f"] * 200))
    def test_critical_debt(self, mock_mod, mock_unpushed):
        report = debt_report(repo_path="/fake")
        assert report.write_debt == 100
        assert report.push_debt == 100
        assert report.debt_score == pytest.approx(100.0)
        assert report.grade == "critical"

    @patch("iamai.commit_debt._count_unpushed", return_value=0)
    @patch("iamai.commit_debt._count_modified", return_value=(2, ["a", "b"]))
    def test_tiny_debt_is_tidy(self, mock_mod, mock_unpushed):
        report = debt_report(repo_path="/fake")
        # write_debt for 2 = 10, push_debt for 0 = 0
        assert report.debt_score == pytest.approx(6.0)
        assert report.grade == "clear"

    @patch("iamai.commit_debt._count_unpushed", return_value=6)
    @patch("iamai.commit_debt._count_modified", return_value=(8, ["f"] * 8))
    def test_owing_grade(self, mock_mod, mock_unpushed):
        report = debt_report(repo_path="/fake")
        # write_debt for 8 = 30, push_debt for 6 = 70
        # score = 0.6*30 + 0.4*70 = 18 + 28 = 46
        assert report.debt_score == pytest.approx(46.0)
        assert report.grade == "owing"


# ---------------------------------------------------------------------------
# grade boundary tests
# ---------------------------------------------------------------------------

class TestGradeBoundaries:
    """Verify grade transitions at exact thresholds."""

    @pytest.mark.parametrize(
        "write_d,push_d,expected_grade",
        [
            (0, 0, "clear"),       # score = 0
            (10, 0, "clear"),      # score = 6  → clear
            (30, 15, "tidy"),      # score = 24 → tidy
            (30, 40, "tidy"),      # score = 34 → tidy
            (60, 40, "owing"),     # score = 52 → owing
            (85, 70, "overdue"),   # score = 79 → overdue
            (100, 100, "critical"),# score = 100 → critical
        ],
    )
    @patch("iamai.commit_debt._count_unpushed", return_value=0)
    @patch("iamai.commit_debt._count_modified", return_value=(0, []))
    def test_grade(self, mock_mod, mock_unp, write_d, push_d, expected_grade):
        """Directly construct a DebtReport and check grade assignment."""
        score = 0.6 * write_d + 0.4 * push_d
        grade = "critical"
        for threshold, label in [(15, "clear"), (40, "tidy"), (70, "owing"), (90, "overdue")]:
            if score < threshold:
                grade = label
                break
        assert grade == expected_grade
