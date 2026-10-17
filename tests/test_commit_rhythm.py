"""Tests for iamai.commit_rhythm — commit cadence health classifier."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iamai.commit_rhythm import (
    CommitRhythm,
    git_commit_gaps,
    rhythm_status,
)


# ── CommitRhythm.classify ────────────────────────────────────────────


class TestClassify:
    """Core classification logic."""

    @pytest.fixture
    def cr(self):
        return CommitRhythm(target_interval=600, window=5)

    # -- steady --

    def test_steady_perfect(self, cr):
        assert cr.classify([600, 600, 600, 600, 600]) == "steady"

    def test_steady_within_tolerance(self, cr):
        assert cr.classify([580, 620, 590, 610, 605]) == "steady"

    def test_steady_at_boundary(self, cr):
        # 779 < 780 (1.3 * 600) → still steady
        assert cr.classify([779, 779, 779, 779, 779]) == "steady"

    def test_steady_short_list(self, cr):
        assert cr.classify([600]) == "steady"

    def test_steady_two_gaps(self, cr):
        assert cr.classify([600, 610]) == "steady"

    # -- drifting --

    def test_drifting_one_outlier(self, cr):
        assert cr.classify([600, 600, 800, 600, 600]) == "drifting"

    def test_drifting_at_threshold(self, cr):
        # exactly 780 = 1.3 * 600 → >= drift_threshold → drifting
        assert cr.classify([780, 600, 600, 600, 600]) == "drifting"

    def test_drifting_multiple(self, cr):
        assert cr.classify([800, 900, 600, 600, 600]) == "drifting"

    # -- broken --

    def test_broken_double_interval(self, cr):
        assert cr.classify([600, 600, 1200, 600, 600]) == "broken"

    def test_broken_at_threshold(self, cr):
        # exactly 1200 = 2.0 * 600 → >= broken_threshold → broken
        assert cr.classify([1200, 600, 600, 600, 600]) == "broken"

    def test_broken_extreme(self, cr):
        assert cr.classify([600, 600, 600, 600, 5000]) == "broken"

    def test_broken_overrides_drifting(self, cr):
        # one drifting gap + one broken gap → broken wins
        assert cr.classify([800, 600, 600, 600, 1500]) == "broken"

    # -- silent --

    def test_silent_empty(self, cr):
        assert cr.classify([]) == "silent"

    # -- window trimming --

    def test_window_trims_oldest(self, cr):
        # 10 gaps but window=5: only last 5 matter
        gaps = [5000, 5000, 5000, 5000, 5000, 600, 600, 600, 600, 600]
        assert cr.classify(gaps) == "steady"

    def test_window_one(self):
        cr1 = CommitRhythm(target_interval=600, window=1)
        assert cr1.classify([600, 600, 1500]) == "broken"  # last gap = 1500

    def test_window_larger_than_input(self, cr):
        assert cr.classify([600]) == "steady"


# ── CommitRhythm thresholds ──────────────────────────────────────────


class TestThresholds:
    """Threshold properties."""

    def test_drift_threshold(self):
        cr = CommitRhythm(target_interval=100, window=3)
        assert cr.drift_threshold == 130.0

    def test_broken_threshold(self):
        cr = CommitRhythm(target_interval=100, window=3)
        assert cr.broken_threshold == 200.0

    def test_custom_interval(self):
        cr = CommitRhythm(target_interval=30, window=3)
        assert cr.drift_threshold == 39.0
        assert cr.broken_threshold == 60.0
        assert cr.classify([30, 30, 30]) == "steady"
        assert cr.classify([30, 40, 30]) == "drifting"
        assert cr.classify([30, 60, 30]) == "broken"


# ── CommitRhythm.describe ────────────────────────────────────────────


class TestDescribe:
    """Human-readable descriptions."""

    @pytest.fixture
    def cr(self):
        return CommitRhythm(target_interval=600, window=3)

    def test_describe_steady(self, cr):
        desc = cr.describe([610, 590, 605])
        assert "steady" in desc
        assert "3/3" in desc
        assert "600s" in desc

    def test_describe_drifting(self, cr):
        desc = cr.describe([600, 800, 600])
        assert "drifting" in desc
        assert "2/3" in desc

    def test_describe_broken(self, cr):
        desc = cr.describe([600, 600, 1500])
        assert "broken" in desc

    def test_describe_silent(self, cr):
        desc = cr.describe([])
        assert "silent" in desc
        assert "no commits" in desc

    def test_describe_partial_steady(self, cr):
        # window=3, but 5 gaps → only last 3 count
        desc = cr.describe([5000, 5000, 600, 600, 600])
        assert "steady" in desc
        assert "3/3" in desc


# ── git_commit_gaps ──────────────────────────────────────────────────


class TestGitCommitGaps:
    """Reading commit timestamps from git."""

    def test_normal_output(self, tmp_path):
        # git log outputs newest-first
        fake_output = "1700001200\n1700000600\n1700000000\n"
        with patch("iamai.commit_rhythm.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fake_output)
            gaps = git_commit_gaps(repo_root=tmp_path, count=5)
        # reversed to chronological: [1700000000, 1700000600, 1700001200]
        # gaps: [600, 600]
        assert gaps == [600, 600]

    def test_empty_repo(self, tmp_path):
        with patch("iamai.commit_rhythm.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            gaps = git_commit_gaps(repo_root=tmp_path, count=5)
        assert gaps == []

    def test_single_commit(self, tmp_path):
        with patch("iamai.commit_rhythm.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="1700000000\n")
            gaps = git_commit_gaps(repo_root=tmp_path, count=5)
        assert gaps == []

    def test_git_failure(self, tmp_path):
        with patch("iamai.commit_rhythm.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="")
            gaps = git_commit_gaps(repo_root=tmp_path, count=5)
        assert gaps == []

    def test_timeout(self, tmp_path):
        with patch("iamai.commit_rhythm.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=10)
            gaps = git_commit_gaps(repo_root=tmp_path, count=5)
        assert gaps == []

    def test_large_gap(self, tmp_path):
        # two commits 3600s apart, newest first (git log order)
        fake_output = "1700003600\n1700000000\n"
        with patch("iamai.commit_rhythm.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fake_output)
            gaps = git_commit_gaps(repo_root=tmp_path, count=5)
        assert gaps == [3600]

    def test_count_parameter(self, tmp_path):
        with patch("iamai.commit_rhythm.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="1700000000\n1700000600\n")
            git_commit_gaps(repo_root=tmp_path, count=3)
        # count=3 → max_count=4
        args = mock_run.call_args
        assert "--max-count=4" in args[0][0]


# ── rhythm_status ────────────────────────────────────────────────────


class TestRhythmStatus:
    """End-to-end status string."""

    def test_steady_status(self, tmp_path):
        fake_output = "\n".join(
            str(1700000000 + i * 600) for i in range(7)
        ) + "\n"
        with patch("iamai.commit_rhythm.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fake_output)
            status = rhythm_status(target_interval=600, window=5, repo_root=tmp_path)
        assert "steady" in status

    def test_silent_status(self, tmp_path):
        with patch("iamai.commit_rhythm.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            status = rhythm_status(target_interval=600, window=5, repo_root=tmp_path)
        assert "silent" in status

    def test_broken_status(self, tmp_path):
        # timestamps with one 3600s gap
        ts = [1700000000, 1700000600, 1700001200, 1700001800, 1700005400, 1700006000, 1700006600]
        fake_output = "\n".join(str(t) for t in reversed(ts)) + "\n"
        with patch("iamai.commit_rhythm.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fake_output)
            status = rhythm_status(target_interval=600, window=5, repo_root=tmp_path)
        assert "broken" in status


# ── Edge cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    """Boundary and edge cases."""

    def test_zero_target_interval(self):
        cr = CommitRhythm(target_interval=0, window=3)
        # any positive gap >= 0 * 2.0 = 0 → broken
        assert cr.classify([1]) == "broken"

    def test_very_small_interval(self):
        cr = CommitRhythm(target_interval=1, window=3)
        assert cr.classify([1, 1, 1]) == "steady"
        assert cr.classify([2, 1, 1]) == "broken"

    def test_negative_gap_clamped(self):
        # negative gaps (clock skew) shouldn't crash
        cr = CommitRhythm(target_interval=600, window=3)
        assert cr.classify([-10, 600, 600]) == "steady"

    def test_float_gaps(self):
        cr = CommitRhythm(target_interval=600, window=3)
        assert cr.classify([600.5, 599.3, 600.1]) == "steady"

    def test_large_window_small_input(self):
        cr = CommitRhythm(target_interval=600, window=100)
        assert cr.classify([600]) == "steady"

    def test_dataclass_frozen(self):
        cr = CommitRhythm(target_interval=600, window=5)
        with pytest.raises(AttributeError):
            cr.target_interval = 300  # type: ignore[misc]

    def test_oserror_in_git(self, tmp_path):
        with patch("iamai.commit_rhythm.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("git not found")
            gaps = git_commit_gaps(repo_root=tmp_path, count=5)
        assert gaps == []
