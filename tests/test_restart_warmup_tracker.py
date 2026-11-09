"""Tests for iamai.restart_warmup_tracker — post-restart cadence recovery.

The restart warmup tracker tells us how long the writer takes to find
its rhythm after a cold start.  These tests verify that the measurement
is correct across ideal, degraded, and edge-case inputs.
"""

import pytest

from iamai.restart_warmup_tracker import (
    RestartWarmupTracker,
    WarmupReport,
    warmup_check,
    _classify,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ts(base: float, *gaps: float) -> list:
    """Build a sorted timestamp list from a base and inter-stroke gaps."""
    ts = [base]
    for g in gaps:
        ts.append(ts[-1] + g)
    return ts


# ---------------------------------------------------------------------------
# WarmupReport.grade
# ---------------------------------------------------------------------------

class TestWarmupGrade:
    def test_instant(self):
        r = WarmupReport(0, 15, 0.25, 5, 1.0, 10.0, 2, True, 20)
        assert r.warmup_grade == "INSTANT"

    def test_quick(self):
        r = WarmupReport(0, 15, 0.25, 5, 1.0, 60.0, 5, True, 20)
        assert r.warmup_grade == "QUICK"

    def test_gradual(self):
        r = WarmupReport(0, 15, 0.25, 5, 1.0, 180.0, 12, True, 30)
        assert r.warmup_grade == "GRADUAL"

    def test_slow(self):
        r = WarmupReport(0, 15, 0.25, 5, 1.0, 600.0, 40, True, 50)
        assert r.warmup_grade == "SLOW"

    def test_unsettled(self):
        r = WarmupReport(0, 15, 0.25, 5, 1.0, None, 5, False, 5)
        assert r.warmup_grade == "UNSETTLED"


# ---------------------------------------------------------------------------
# WarmupReport.efficiency
# ---------------------------------------------------------------------------

class TestWarmupEfficiency:
    def test_perfect_efficiency(self):
        # window_size=5, expected=15 → ideal = 75s; warmup_s = 75 → eff = 1.0
        r = WarmupReport(0, 15, 0.25, 5, 1.0, 75.0, 6, True, 20)
        assert r.efficiency == pytest.approx(1.0)

    def test_half_efficiency(self):
        # ideal = 75, actual = 150 → eff = 0.5
        r = WarmupReport(0, 15, 0.25, 5, 1.0, 150.0, 11, True, 20)
        assert r.efficiency == pytest.approx(0.5)

    def test_unsettled_efficiency_zero(self):
        r = WarmupReport(0, 15, 0.25, 5, 1.0, None, 5, False, 5)
        assert r.efficiency == 0.0

    def test_zero_warmup_efficiency(self):
        r = WarmupReport(0, 15, 0.25, 5, 1.0, 0.0, 6, True, 20)
        assert r.efficiency == 0.0

    def test_efficiency_clamped_to_one(self):
        # warmup faster than theoretical minimum → still capped at 1.0
        r = WarmupReport(0, 15, 0.25, 5, 1.0, 10.0, 6, True, 20)
        assert r.efficiency <= 1.0


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_unsettled_none(self):
        assert _classify(None, False) == "UNSETTLED"

    def test_unsettled_with_value(self):
        # settled=False always returns UNSETTLED regardless of value
        assert _classify(10.0, False) == "UNSETTLED"

    def test_instant(self):
        assert _classify(15.0, True) == "INSTANT"

    def test_quick(self):
        assert _classify(45.0, True) == "QUICK"

    def test_gradual(self):
        assert _classify(200.0, True) == "GRADUAL"

    def test_slow(self):
        assert _classify(500.0, True) == "SLOW"

    def test_boundary_instant(self):
        assert _classify(30.0, True) == "QUICK"  # 30 is not < 30

    def test_boundary_quick(self):
        assert _classify(120.0, True) == "GRADUAL"  # 120 is not < 120


# ---------------------------------------------------------------------------
# RestartWarmupTracker — constructor validation
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_negative_cadence(self):
        with pytest.raises(ValueError, match="positive"):
            RestartWarmupTracker(expected_cadence_s=-1)

    def test_zero_cadence(self):
        with pytest.raises(ValueError, match="positive"):
            RestartWarmupTracker(expected_cadence_s=0)

    def test_tolerance_too_high(self):
        with pytest.raises(ValueError, match="tolerance"):
            RestartWarmupTracker(tolerance=1.0)

    def test_tolerance_zero(self):
        with pytest.raises(ValueError, match="tolerance"):
            RestartWarmupTracker(tolerance=0)

    def test_window_too_small(self):
        with pytest.raises(ValueError, match="window_size"):
            RestartWarmupTracker(window_size=1)


# ---------------------------------------------------------------------------
# RestartWarmupTracker.measure — core behaviour
# ---------------------------------------------------------------------------

class TestMeasure:
    """Integration tests for the measure() method."""

    def test_perfect_cadence_settles_instantly(self):
        """Five perfect 15s gaps → settles at the 5th gap end."""
        base = 1000.0
        ts = _make_ts(base, 15, 15, 15, 15, 15, 15, 15)
        tracker = RestartWarmupTracker(expected_cadence_s=15, window_size=5)
        report = tracker.measure(base, ts)

        assert report.settled is True
        # 5 gaps after base → settle at ts[5] = base + 75
        assert report.warmup_s == pytest.approx(75.0)
        assert report.warmup_strokes == 6
        assert report.first_stroke_latency_s == pytest.approx(0.0)
        assert report.warmup_grade == "QUICK"  # 75s < 120s

    def test_first_stroke_latency(self):
        """Writer takes 10s to produce its first stroke."""
        base = 1000.0
        ts = _make_ts(base + 10, 15, 15, 15, 15, 15, 15)
        tracker = RestartWarmupTracker(expected_cadence_s=15, window_size=5)
        report = tracker.measure(base, ts)

        assert report.first_stroke_latency_s == pytest.approx(10.0)
        assert report.settled is True

    def test_slow_warmup_then_settles(self):
        """First 10 gaps are 60s (very slow), then perfect 15s."""
        base = 1000.0
        slow_gaps = [60] * 10
        fast_gaps = [15] * 10
        ts = _make_ts(base, *slow_gaps, *fast_gaps)
        tracker = RestartWarmupTracker(expected_cadence_s=15, window_size=5)
        report = tracker.measure(base, ts)

        assert report.settled is True
        # slow region: gaps 0..9 are 60s → medians of windows 0..4, 1..5, etc. all 60
        # first fast window starts at gap index 10 (the 11th gap)
        # gaps[10:15] = [15,15,15,15,15] → median=15 → settles
        # settle at ts[10 + 5] = ts[15]
        assert report.warmup_s is not None
        assert report.warmup_s > 300  # definitely SLOW territory

    def test_too_few_timestamps(self):
        """Not enough data to evaluate → unsettled."""
        base = 1000.0
        ts = [base + 5, base + 20]
        tracker = RestartWarmupTracker(expected_cadence_s=15, window_size=5)
        report = tracker.measure(base, ts)

        assert report.settled is False
        assert report.warmup_s is None
        assert report.warmup_grade == "UNSETTLED"
        assert report.total_strokes_observed == 2

    def test_empty_timestamps(self):
        """No strokes at all → everything zero/None."""
        tracker = RestartWarmupTracker(expected_cadence_s=15, window_size=5)
        report = tracker.measure(1000.0, [])

        assert report.settled is False
        assert report.warmup_s is None
        assert report.first_stroke_latency_s == 0.0
        assert report.total_strokes_observed == 0

    def test_ignores_pre_restart_timestamps(self):
        """Timestamps before restart_epoch should be filtered out."""
        base = 1000.0
        # Include some timestamps before the restart.
        pre = [base - 100, base - 50, base - 10]
        post = _make_ts(base, 15, 15, 15, 15, 15, 15)
        tracker = RestartWarmupTracker(expected_cadence_s=15, window_size=5)
        report = tracker.measure(base, pre + post)

        assert report.settled is True
        assert report.total_strokes_observed == 7  # only post-restart

    def test_irregular_then_settles(self):
        """Chaotic gaps at first, then a clean run."""
        base = 1000.0
        chaotic = [3, 42, 1, 88, 5, 120, 2, 30]
        clean = [15] * 10
        ts = _make_ts(base, *chaotic, *clean)
        tracker = RestartWarmupTracker(expected_cadence_s=15, window_size=5)
        report = tracker.measure(base, ts)

        assert report.settled is True
        # warmup should be long because of the chaotic prefix
        assert report.warmup_s > 100

    def test_tolerance_boundary(self):
        """Gaps at exactly the tolerance edge should still settle."""
        base = 1000.0
        # tolerance=0.25 → acceptable range [11.25, 18.75]
        edge_gaps = [18.75] * 10  # right at the upper edge
        ts = _make_ts(base, *edge_gaps)
        tracker = RestartWarmupTracker(expected_cadence_s=15, tolerance=0.25, window_size=5)
        report = tracker.measure(base, ts)

        assert report.settled is True

    def test_just_outside_tolerance(self):
        """Gaps just outside tolerance should not settle."""
        base = 1000.0
        # tolerance=0.25 → upper bound = 18.75; 19.0 is outside
        wide_gaps = [19.0] * 10
        ts = _make_ts(base, *wide_gaps)
        tracker = RestartWarmupTracker(expected_cadence_s=15, tolerance=0.25, window_size=5)
        report = tracker.measure(base, ts)

        assert report.settled is False

    def test_unsorted_input_handled(self):
        """Timestamps given out of order should still work."""
        base = 1000.0
        ts = [base + 90, base + 15, base + 45, base + 30, base + 60, base + 75, base + 105]
        tracker = RestartWarmupTracker(expected_cadence_s=15, window_size=5)
        report = tracker.measure(base, ts)

        # After sorting: base, +15, +30, +45, +60, +75, +90, +105
        # All gaps are 15 → should settle
        assert report.settled is True

    def test_window_size_2(self):
        """Minimum window size should work."""
        base = 1000.0
        ts = _make_ts(base, 15, 15, 15, 15)
        tracker = RestartWarmupTracker(expected_cadence_s=15, window_size=2)
        report = tracker.measure(base, ts)

        assert report.settled is True
        # 2 gaps of 15 → median=15 → settles at ts[2] = base+30
        assert report.warmup_s == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# warmup_check convenience function
# ---------------------------------------------------------------------------

class TestWarmupCheck:
    def test_basic(self):
        base = 5000.0
        ts = _make_ts(base, 15, 15, 15, 15, 15, 15)
        report = warmup_check(base, ts, expected_cadence_s=15)
        assert isinstance(report, WarmupReport)
        assert report.settled is True

    def test_custom_tolerance(self):
        base = 5000.0
        ts = _make_ts(base, 19, 19, 19, 19, 19, 19)
        # Default tolerance 0.25 → 19 is outside [11.25, 18.75]
        report_strict = warmup_check(base, ts, expected_cadence_s=15, tolerance=0.25)
        assert report_strict.settled is False

        # Wider tolerance 0.30 → [10.5, 19.5] → 19 fits
        report_loose = warmup_check(base, ts, expected_cadence_s=15, tolerance=0.30)
        assert report_loose.settled is True


# ---------------------------------------------------------------------------
# Realistic scenario
# ---------------------------------------------------------------------------

class TestRealisticScenario:
    def test_typical_cold_start(self):
        """Simulate a realistic cold-start: 5s to first stroke, then
        gradually improving cadence."""
        base = 1_700_000_000.0
        # First stroke at +5s, then gaps improve: 30, 25, 20, 18, 16, 15, 15, ...
        gaps = [30, 25, 20, 18, 16, 15, 15, 15, 15, 15, 15, 15]
        ts = _make_ts(base + 5, *gaps)
        tracker = RestartWarmupTracker(expected_cadence_s=15, window_size=5)
        report = tracker.measure(base, ts)

        assert report.first_stroke_latency_s == pytest.approx(5.0)
        assert report.settled is True
        # warmup includes the latency + the irregular prefix
        assert report.warmup_s > 10
        assert report.total_strokes_observed == 13

    def test_process_restart_with_stall(self):
        """Writer restarts, writes a few strokes, stalls for 60s, then resumes."""
        base = 1_700_000_000.0
        gaps = [15, 15, 15, 60, 15, 15, 15, 15, 15, 15]
        ts = _make_ts(base, *gaps)
        tracker = RestartWarmupTracker(expected_cadence_s=15, window_size=5)
        report = tracker.measure(base, ts)

        # The 60s gap in the middle prevents early windows from settling.
        # Should eventually settle after the stall.
        assert report.settled is True
        # The stall pushes warmup past the stall point.
        assert report.warmup_s > 60
