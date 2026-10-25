"""Tests for iamai.restart_cost — restart cost analysis module."""

import pytest

from iamai.restart_cost import (
    _baseline_cadence,
    analyse_restart,
    catchup_time,
    recovery_ratio,
    silence_gap,
    strokes_lost,
)


# ---------------------------------------------------------------------------
# _baseline_cadence
# ---------------------------------------------------------------------------

class TestBaselineCadence:
    def test_empty_list(self):
        assert _baseline_cadence([]) == 0.0

    def test_single_element(self):
        assert _baseline_cadence([100.0]) == 0.0

    def test_two_elements(self):
        assert _baseline_cadence([100.0, 200.0]) == 100.0

    def test_regular_intervals(self):
        ts = [0, 10, 20, 30, 40, 50]
        assert _baseline_cadence(ts) == 10.0

    def test_median_not_mean(self):
        # intervals: 10, 10, 10, 100 — median = 10, mean = 32.5
        ts = [0, 10, 20, 30, 130]
        assert _baseline_cadence(ts, sample=5) == 10.0

    def test_sample_window(self):
        ts = [0, 1, 2, 3, 4, 100, 200, 300]
        # last 5+1 = [2, 3, 4, 100, 200, 300], intervals: 1,1,96,100,100
        # sorted: 1,1,96,100,100 → median = 96
        result = _baseline_cadence(ts, sample=5)
        assert result == 96.0


# ---------------------------------------------------------------------------
# silence_gap
# ---------------------------------------------------------------------------

class TestSilenceGap:
    def test_normal_gap(self):
        assert silence_gap(100.0, 500.0) == 400.0

    def test_zero_gap(self):
        assert silence_gap(100.0, 100.0) == 0.0

    def test_negative_clamped(self):
        assert silence_gap(500.0, 100.0) == 0.0

    def test_none_pre(self):
        assert silence_gap(None, 500.0) == 0.0

    def test_none_post(self):
        assert silence_gap(100.0, None) == 0.0

    def test_both_none(self):
        assert silence_gap(None, None) == 0.0


# ---------------------------------------------------------------------------
# strokes_lost
# ---------------------------------------------------------------------------

class TestStrokesLost:
    def test_normal(self):
        assert strokes_lost(600.0, 60.0) == 10.0

    def test_zero_cadence(self):
        assert strokes_lost(600.0, 0.0) == 0.0

    def test_negative_cadence(self):
        assert strokes_lost(600.0, -1.0) == 0.0

    def test_fractional(self):
        assert strokes_lost(90.0, 60.0) == 1.5

    def test_zero_gap(self):
        assert strokes_lost(0.0, 60.0) == 0.0


# ---------------------------------------------------------------------------
# recovery_ratio
# ---------------------------------------------------------------------------

class TestRecoveryRatio:
    def test_normal_pace(self):
        # cadence = 60s, window = 300s → expect 5 strokes
        # produce exactly 5 strokes at 60s intervals
        post = [1000, 1060, 1120, 1180, 1240]
        ratio = recovery_ratio(post, 300.0, 60.0)
        assert ratio == 1.0

    def test_sprinting(self):
        # cadence = 60s, window = 300s → expect 5, produce 10
        post = [1000 + i * 30 for i in range(10)]
        ratio = recovery_ratio(post, 300.0, 60.0)
        assert ratio == 2.0

    def test_warming_up(self):
        # cadence = 60s, window = 300s → expect 5, produce 2
        post = [1000, 1200]
        ratio = recovery_ratio(post, 300.0, 60.0)
        assert ratio == 0.4

    def test_empty_post(self):
        assert recovery_ratio([], 300.0, 60.0) == 0.0

    def test_zero_cadence(self):
        assert recovery_ratio([1000, 1060], 300.0, 0.0) == 0.0

    def test_zero_window(self):
        assert recovery_ratio([1000, 1060], 0.0, 60.0) == 0.0


# ---------------------------------------------------------------------------
# catchup_time
# ---------------------------------------------------------------------------

class TestCatchupTime:
    def test_immediate_catchup(self):
        # first interval is already within tolerance
        post = [1000, 1060, 1120]
        result = catchup_time(post, 60.0, tolerance=1.5)
        assert result == 60.0  # first interval = 60s, within 90s threshold

    def test_delayed_catchup(self):
        # intervals: 200, 200, 60 → catches up at stroke 3
        post = [1000, 1200, 1400, 1460]
        result = catchup_time(post, 60.0, tolerance=1.5)
        assert result == 460.0  # 1460 - 1000

    def test_never_catches_up(self):
        # all intervals are 200s, baseline 60s, threshold 90s
        post = [1000, 1200, 1400, 1600]
        result = catchup_time(post, 60.0, tolerance=1.5)
        assert result == 0.0

    def test_empty_list(self):
        assert catchup_time([], 60.0) == 0.0

    def test_single_element(self):
        assert catchup_time([1000], 60.0) == 0.0

    def test_zero_cadence(self):
        assert catchup_time([1000, 1060], 0.0) == 0.0


# ---------------------------------------------------------------------------
# analyse_restart (integration)
# ---------------------------------------------------------------------------

class TestAnalyseRestart:
    def test_typical_restart(self):
        pre = [1000, 1060, 1120, 1180, 1240]  # cadence ~60s
        restart = 1500
        post = [2100, 2160, 2220, 2280, 2340]  # resumed at same cadence

        report = analyse_restart(pre, post, restart)
        assert report["silence_gap"] == 860.0  # 2100 - 1240
        assert report["strokes_lost"] > 0
        assert report["baseline_cadence"] == 60.0
        assert report["last_pre"] == 1240
        assert report["first_post"] == 2100

    def test_no_pre_data(self):
        post = [2000, 2060, 2120]
        report = analyse_restart([], post, 1900)
        assert report["silence_gap"] == 0.0
        assert report["strokes_lost"] == 0.0
        assert report["baseline_cadence"] == 0.0

    def test_no_post_data(self):
        pre = [1000, 1060, 1120]
        report = analyse_restart(pre, [], 1200)
        assert report["silence_gap"] == 0.0
        assert report["recovery_ratio"] == 0.0
        assert report["catchup_time"] == 0.0

    def test_both_empty(self):
        report = analyse_restart([], [], 1000)
        assert report["silence_gap"] == 0.0
        assert report["strokes_lost"] == 0.0
        assert report["recovery_ratio"] == 0.0

    def test_recovery_window(self):
        pre = [0, 60, 120, 180, 240]  # 60s cadence
        post = [600 + i * 30 for i in range(20)]  # sprinting at 30s
        report = analyse_restart(pre, post, 500, recovery_window=300)
        # in 300s window from 600: strokes at 600,630,...,900 = 11 strokes
        # expected: 300/60 = 5
        assert report["recovery_ratio"] == 2.2  # 11/5
