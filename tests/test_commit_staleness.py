"""Tests for iamai.commit_staleness — commit freshness assessment."""

import subprocess
import time
from unittest.mock import patch, MagicMock

import pytest

from iamai.commit_staleness import (
    Freshness,
    FreshnessLevel,
    assess_freshness,
    _last_commit_epoch,
    _dirty_file_count,
)


# ---------------------------------------------------------------------------
# FreshnessLevel enum
# ---------------------------------------------------------------------------

class TestFreshnessLevel:
    def test_all_levels_exist(self):
        assert FreshnessLevel.FRESH.value == "FRESH"
        assert FreshnessLevel.AGING.value == "AGING"
        assert FreshnessLevel.STALE.value == "STALE"
        assert FreshnessLevel.ROTTEN.value == "ROTTEN"

    def test_level_count(self):
        assert len(FreshnessLevel) == 4


# ---------------------------------------------------------------------------
# Freshness dataclass
# ---------------------------------------------------------------------------

class TestFreshness:
    def test_str_format(self):
        f = Freshness(
            level=FreshnessLevel.FRESH,
            age_seconds=120,
            missed_cycles=0.2,
            debt_files=3,
        )
        s = str(f)
        assert "FRESH" in s
        assert "120s" in s
        assert "0.2cycles" in s
        assert "3files" in s

    def test_needs_attention_false_for_fresh(self):
        f = Freshness(FreshnessLevel.FRESH, 100, 0.1, 0)
        assert f.needs_attention is False

    def test_needs_attention_false_for_aging(self):
        f = Freshness(FreshnessLevel.AGING, 700, 1.2, 1)
        assert f.needs_attention is False

    def test_needs_attention_true_for_stale(self):
        f = Freshness(FreshnessLevel.STALE, 1500, 2.5, 5)
        assert f.needs_attention is True

    def test_needs_attention_true_for_rotten(self):
        f = Freshness(FreshnessLevel.ROTTEN, 3600, 6.0, 10)
        assert f.needs_attention is True

    def test_frozen(self):
        f = Freshness(FreshnessLevel.FRESH, 100, 0.1, 0)
        with pytest.raises(AttributeError):
            f.age_seconds = 200

    def test_last_commit_epoch_default_none(self):
        f = Freshness(FreshnessLevel.FRESH, 100, 0.1, 0)
        assert f.last_commit_epoch is None

    def test_last_commit_epoch_set(self):
        f = Freshness(FreshnessLevel.FRESH, 100, 0.1, 0, last_commit_epoch=1000.0)
        assert f.last_commit_epoch == 1000.0


# ---------------------------------------------------------------------------
# _last_commit_epoch
# ---------------------------------------------------------------------------

class TestLastCommitEpoch:
    def test_returns_float_on_success(self):
        with patch("iamai.commit_staleness.subprocess.check_output") as mock_co:
            mock_co.return_value = b"1700000000\n"
            result = _last_commit_epoch("/fake/repo")
            assert result == 1700000000.0
            mock_co.assert_called_once()

    def test_returns_none_on_calledprocesserror(self):
        with patch("iamai.commit_staleness.subprocess.check_output") as mock_co:
            mock_co.side_effect = subprocess.CalledProcessError(1, "git")
            assert _last_commit_epoch("/fake/repo") is None

    def test_returns_none_on_valueerror(self):
        with patch("iamai.commit_staleness.subprocess.check_output") as mock_co:
            mock_co.return_value = b"not-a-number\n"
            assert _last_commit_epoch("/fake/repo") is None

    def test_returns_none_on_filenotfounderror(self):
        with patch("iamai.commit_staleness.subprocess.check_output") as mock_co:
            mock_co.side_effect = FileNotFoundError("git not found")
            assert _last_commit_epoch("/fake/repo") is None

    def test_strips_whitespace(self):
        with patch("iamai.commit_staleness.subprocess.check_output") as mock_co:
            mock_co.return_value = b"  1700000000  \n"
            assert _last_commit_epoch("/fake/repo") == 1700000000.0


# ---------------------------------------------------------------------------
# _dirty_file_count
# ---------------------------------------------------------------------------

class TestDirtyFileCount:
    def test_counts_lines(self):
        with patch("iamai.commit_staleness.subprocess.check_output") as mock_co:
            mock_co.return_value = b" M file1.py\n M file2.py\n?? new.py\n"
            assert _dirty_file_count("/fake/repo") == 3

    def test_empty_when_clean(self):
        with patch("iamai.commit_staleness.subprocess.check_output") as mock_co:
            mock_co.return_value = b""
            assert _dirty_file_count("/fake/repo") == 0

    def test_zero_on_error(self):
        with patch("iamai.commit_staleness.subprocess.check_output") as mock_co:
            mock_co.side_effect = subprocess.CalledProcessError(1, "git")
            assert _dirty_file_count("/fake/repo") == 0

    def test_zero_on_git_missing(self):
        with patch("iamai.commit_staleness.subprocess.check_output") as mock_co:
            mock_co.side_effect = FileNotFoundError()
            assert _dirty_file_count("/fake/repo") == 0

    def test_ignores_blank_lines(self):
        with patch("iamai.commit_staleness.subprocess.check_output") as mock_co:
            mock_co.return_value = b" M file1.py\n\n\n"
            assert _dirty_file_count("/fake/repo") == 1


# ---------------------------------------------------------------------------
# assess_freshness — classification
# ---------------------------------------------------------------------------

class TestAssessFreshness:
    def _assess(self, commit_epoch, now, interval=600, dirty=0):
        with patch("iamai.commit_staleness._last_commit_epoch", return_value=commit_epoch), \
             patch("iamai.commit_staleness._dirty_file_count", return_value=dirty):
            return assess_freshness(batch_interval=interval, repo="/fake", now=now)

    def test_fresh_when_just_committed(self):
        f = self._assess(commit_epoch=1000, now=1100)
        assert f.level == FreshnessLevel.FRESH
        assert f.age_seconds == 100
        assert f.missed_cycles == pytest.approx(100 / 600)

    def test_fresh_at_boundary(self):
        # Exactly at 1× interval → AGING (not FRESH, since < is strict)
        f = self._assess(commit_epoch=1000, now=1600)
        assert f.level == FreshnessLevel.AGING

    def test_aging_one_cycle_behind(self):
        f = self._assess(commit_epoch=1000, now=1900)
        assert f.level == FreshnessLevel.AGING

    def test_stale_at_two_cycles(self):
        f = self._assess(commit_epoch=1000, now=2200)
        assert f.level == FreshnessLevel.STALE

    def test_stale_three_cycles(self):
        f = self._assess(commit_epoch=1000, now=2800)
        assert f.level == FreshnessLevel.STALE

    def test_rotten_at_four_cycles(self):
        f = self._assess(commit_epoch=1000, now=3400)
        assert f.level == FreshnessLevel.ROTTEN

    def test_rotten_ten_cycles(self):
        f = self._assess(commit_epoch=1000, now=7000)
        assert f.level == FreshnessLevel.ROTTEN

    def test_custom_interval(self):
        # 300s interval, 400s gap → 1.33 cycles → AGING
        f = self._assess(commit_epoch=1000, now=1400, interval=300)
        assert f.level == FreshnessLevel.AGING
        assert f.missed_cycles == pytest.approx(400 / 300)

    def test_debt_files_included(self):
        f = self._assess(commit_epoch=1000, now=1100, dirty=7)
        assert f.debt_files == 7

    def test_no_commits_returns_rotten(self):
        with patch("iamai.commit_staleness._last_commit_epoch", return_value=None), \
             patch("iamai.commit_staleness._dirty_file_count", return_value=2):
            f = assess_freshness(batch_interval=600, repo="/fake", now=5000)
            assert f.level == FreshnessLevel.ROTTEN
            assert f.last_commit_epoch is None
            assert f.debt_files == 2

    def test_zero_interval_avoids_division(self):
        # batch_interval=0 should not crash; age/0 → inf → ROTTEN
        f = self._assess(commit_epoch=1000, now=1001, interval=0)
        assert f.level == FreshnessLevel.ROTTEN
        assert f.missed_cycles == float("inf")

    def test_missed_cycles_calculation(self):
        f = self._assess(commit_epoch=1000, now=2500, interval=600)
        assert f.missed_cycles == pytest.approx(1500 / 600)

    def test_now_defaults_to_time_time(self):
        with patch("iamai.commit_staleness._last_commit_epoch", return_value=time.time() - 50), \
             patch("iamai.commit_staleness._dirty_file_count", return_value=0):
            f = assess_freshness(batch_interval=600, repo="/fake")
            assert f.level == FreshnessLevel.FRESH


# ---------------------------------------------------------------------------
# assess_freshness — edge cases
# ---------------------------------------------------------------------------

class TestAssessFreshnessEdges:
    def test_very_large_gap(self):
        with patch("iamai.commit_staleness._last_commit_epoch", return_value=0), \
             patch("iamai.commit_staleness._dirty_file_count", return_value=100):
            f = assess_freshness(batch_interval=600, repo="/fake", now=1_000_000)
            assert f.level == FreshnessLevel.ROTTEN
            assert f.age_seconds == 1_000_000

    def test_commit_in_future(self):
        # Commit timestamp is ahead of now — negative age, still FRESH (< 1 cycle)
        with patch("iamai.commit_staleness._last_commit_epoch", return_value=2000), \
             patch("iamai.commit_staleness._dirty_file_count", return_value=0):
            f = assess_freshness(batch_interval=600, repo="/fake", now=1000)
            assert f.level == FreshnessLevel.FRESH
            assert f.age_seconds == -1000

    def test_exactly_fresh_boundary_minus_epsilon(self):
        # 599s with 600s interval → FRESH
        with patch("iamai.commit_staleness._last_commit_epoch", return_value=1000), \
             patch("iamai.commit_staleness._dirty_file_count", return_value=0):
            f = assess_freshness(batch_interval=600, repo="/fake", now=1599)
            assert f.level == FreshnessLevel.FRESH

    def test_exactly_stale_boundary(self):
        # 1200s with 600s interval → exactly 2.0 → STALE
        with patch("iamai.commit_staleness._last_commit_epoch", return_value=1000), \
             patch("iamai.commit_staleness._dirty_file_count", return_value=0):
            f = assess_freshness(batch_interval=600, repo="/fake", now=2200)
            assert f.level == FreshnessLevel.STALE

    def test_exactly_rotten_boundary(self):
        # 2400s with 600s interval → exactly 4.0 → ROTTEN
        with patch("iamai.commit_staleness._last_commit_epoch", return_value=1000), \
             patch("iamai.commit_staleness._dirty_file_count", return_value=0):
            f = assess_freshness(batch_interval=600, repo="/fake", now=3400)
            assert f.level == FreshnessLevel.ROTTEN
