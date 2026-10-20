"""Tests for iamai.commit_rhythm_score — commit cadence quality analyser.

25 tests covering:
  - scoring helper functions (interval, jitter, burst, geometric mean)
  - statistics (median, mean, std)
  - interval extraction from timestamps
  - full analysis pipeline with mocked git data
  - edge cases (empty repo, single commit, identical timestamps)
  - grade boundaries and summary formatting
"""

import math
import pytest
from unittest.mock import patch, MagicMock
from iamai.commit_rhythm_score import (
    CommitRhythm,
    RhythmReport,
    _interval_score,
    _jitter_score,
    _burst_score,
    _geometric_mean,
    DEFAULT_TARGET,
    BURST_THRESHOLD,
    MAX_JITTER_CV,
)


# ---------------------------------------------------------------------------
# Helper: build a CommitRhythm with no real git calls
# ---------------------------------------------------------------------------
def _make_cr(repo_path=None, target=600):
    return CommitRhythm(repo_path or "/tmp/fake", target)


def _mock_timestamps(ts_list):
    """Patch _fetch_timestamps to return a fixed list."""
    return patch.object(
        CommitRhythm, "_fetch_timestamps", return_value=ts_list
    )


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------
class TestIntervalScore:
    def test_perfect_match_is_100(self):
        assert _interval_score(600, 600) == 100.0

    def test_half_target_is_50(self):
        assert _interval_score(300, 600) == 50.0

    def test_double_target_is_50(self):
        assert _interval_score(1200, 600) == 50.0

    def test_zero_median_is_zero(self):
        assert _interval_score(0, 600) == 0.0

    def test_zero_target_is_zero(self):
        assert _interval_score(600, 0) == 0.0

    def test_symmetric(self):
        # 300 vs 600 and 600 vs 300 should give the same score
        assert _interval_score(300, 600) == _interval_score(600, 300)


class TestJitterScore:
    def test_zero_jitter_is_100(self):
        assert _jitter_score(0.0) == 100.0

    def test_max_jitter_is_zero(self):
        assert _jitter_score(MAX_JITTER_CV) == 0.0

    def test_half_jitter_is_50(self):
        score = _jitter_score(0.5)
        assert abs(score - 50.0) < 0.01

    def test_negative_cv_is_zero(self):
        assert _jitter_score(-0.1) == 0.0

    def test_above_max_clamped(self):
        assert _jitter_score(2.0) == 0.0


class TestBurstScore:
    def test_no_bursts_is_100(self):
        assert _burst_score(0, 30) == 100.0

    def test_all_bursts_is_zero(self):
        # burst_frac = 1.0 → (1 - 2) → clamped to 0
        assert _burst_score(30, 30) == 0.0

    def test_half_bursts_is_zero(self):
        # burst_frac = 0.5 → (1 - 1) = 0
        assert _burst_score(15, 30) == 0.0

    def test_quarter_bursts(self):
        # burst_frac = 0.25 → (1 - 0.5) * 100 = 50
        score = _burst_score(7, 28)
        expected = (1.0 - (7 / 28) * 2) * 100.0
        assert abs(score - expected) < 0.01

    def test_zero_intervals_is_100(self):
        assert _burst_score(0, 0) == 100.0


class TestGeometricMean:
    def test_equal_values(self):
        assert abs(_geometric_mean([5, 5, 5]) - 5.0) < 1e-9

    def test_simple_case(self):
        # gmean(4, 9) = 6
        assert abs(_geometric_mean([4, 9]) - 6.0) < 0.001

    def test_zero_in_list(self):
        assert _geometric_mean([0, 10, 10]) == 0.0

    def test_empty_list(self):
        assert _geometric_mean([]) == 0.0

    def test_single_value(self):
        assert abs(_geometric_mean([42]) - 42.0) < 1e-9


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
class TestStatistics:
    def test_median_odd(self):
        assert CommitRhythm._median([3, 1, 2]) == 2.0

    def test_median_even(self):
        assert CommitRhythm._median([4, 1, 3, 2]) == 2.5

    def test_median_empty(self):
        assert CommitRhythm._median([]) == 0.0

    def test_mean_basic(self):
        assert CommitRhythm._mean([10, 20, 30]) == 20.0

    def test_mean_empty(self):
        assert CommitRhythm._mean([]) == 0.0

    def test_std_uniform_is_zero(self):
        assert CommitRhythm._std([5, 5, 5], 5.0) == 0.0

    def test_std_known_value(self):
        # sample std of [2, 4, 4, 4, 5, 5, 7, 9]: mean=5, variance=32/7≈4.571, std≈2.138
        vals = [2, 4, 4, 4, 5, 5, 7, 9]
        mean = sum(vals) / len(vals)
        std = CommitRhythm._std(vals, mean)
        assert abs(std - 2.138) < 0.01

    def test_std_single_value(self):
        assert CommitRhythm._std([7], 7.0) == 0.0


# ---------------------------------------------------------------------------
# Interval extraction
# ---------------------------------------------------------------------------
class TestIntervals:
    def test_descending_timestamps(self):
        cr = _make_cr()
        ts = [1000, 700, 400, 100]  # descending (newest first)
        intervals = cr._intervals(ts)
        assert intervals == [300, 300, 300]

    def test_with_zero_gap(self):
        cr = _make_cr()
        ts = [1000, 1000, 500]
        intervals = cr._intervals(ts)
        # Zero gap is skipped
        assert intervals == [500]

    def test_single_timestamp(self):
        cr = _make_cr()
        assert cr._intervals([1000]) == []

    def test_empty(self):
        cr = _make_cr()
        assert cr._intervals([]) == []


# ---------------------------------------------------------------------------
# Full analysis
# ---------------------------------------------------------------------------
class TestAnalyse:
    def test_perfect_cadence(self):
        """30 commits, exactly 600s apart → score 100."""
        n = 31  # 31 timestamps → 30 intervals
        ts = [1_000_000 + i * 600 for i in range(n)]
        ts.reverse()  # newest first
        cr = _make_cr()
        with _mock_timestamps(ts):
            report = cr.analyse(n=30)
        assert abs(report.total - 100.0) < 1e-9
        assert report.grade == "A"
        assert report.n_intervals == 30
        assert report.burst_count == 0

    def test_bursty_cadence(self):
        """Alternating 100s and 1100s intervals → low score."""
        base = 1_000_000
        ts = [base]
        for i in range(30):
            gap = 100 if i % 2 == 0 else 1100
            ts.append(ts[-1] + gap)
        ts.reverse()
        cr = _make_cr()
        with _mock_timestamps(ts):
            report = cr.analyse(n=30)
        # Many bursts (100s < 200s threshold), jitter is high
        assert report.burst_count > 10
        assert report.total < 50

    def test_empty_repo(self):
        """No commits → zero report."""
        cr = _make_cr()
        with _mock_timestamps([]):
            report = cr.analyse(n=30)
        assert report.total == 0.0
        assert report.n_commits == 0
        assert report.grade == "F"

    def test_single_commit(self):
        """One commit → no intervals → zero report."""
        cr = _make_cr()
        with _mock_timestamps([1_000_000]):
            report = cr.analyse(n=30)
        assert report.n_intervals == 0
        assert report.total == 0.0

    def test_slow_cadence_penalised(self):
        """Median interval = 1200s (double target) → interval_score = 50."""
        ts = [1_000_000 + i * 1200 for i in range(31)]
        ts.reverse()
        cr = _make_cr()
        with _mock_timestamps(ts):
            report = cr.analyse(n=30)
        assert report.interval_score == 50.0
        assert report.burst_count == 0

    def test_grade_boundaries(self):
        """Verify grade mapping via direct RhythmReport construction."""
        for score, grade in [(95, "A"), (75, "B"), (55, "C"), (35, "D"), (15, "F")]:
            r = RhythmReport(total=float(score))
            assert r.grade == grade

    def test_summary_format(self):
        r = RhythmReport(
            total=78.0,
            median_interval=612.0,
            jitter_cv=0.18,
            burst_count=2,
            n_intervals=30,
        )
        s = r.summary
        assert "78/100" in s
        assert "(B)" in s
        assert "median=612s" in s
        assert "bursts=2/30" in s

    def test_custom_target(self):
        """Target = 300s, intervals = 300s → perfect score."""
        ts = [1_000_000 + i * 300 for i in range(11)]
        ts.reverse()
        cr = _make_cr(target=300)
        with _mock_timestamps(ts):
            report = cr.analyse(n=10)
        assert abs(report.total - 100.0) < 1e-9

    def test_jitter_cv_calculation(self):
        """Verify CV = std/mean for a known dataset."""
        # Intervals: [500, 600, 700] → mean=600, std=100, cv=100/600≈0.1667
        base = 1_000_000
        ts = [base, base + 500, base + 1100, base + 1800]
        ts.reverse()
        cr = _make_cr()
        with _mock_timestamps(ts):
            report = cr.analyse(n=3)
        assert abs(report.jitter_cv - (100 / 600)) < 0.01
