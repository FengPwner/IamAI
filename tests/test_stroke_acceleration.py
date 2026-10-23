"""tests for iamai.stroke_acceleration"""

import pytest

from iamai.stroke_acceleration import (
    DEFAULT_EXPECTED_CADENCE,
    DEFAULT_STALL_FACTOR,
    DEFAULT_THRESHOLD,
    DEFAULT_WINDOW,
    AccelerationResult,
    StrokeAccelerator,
    _coefficient_of_variation,
    _compute_intervals,
    _linear_slope,
    acceleration_summary,
)


# ---------------------------------------------------------------------------
# _compute_intervals()
# ---------------------------------------------------------------------------
class TestComputeIntervals:
    def test_basic(self):
        assert _compute_intervals([0, 10, 25]) == [10, 15]

    def test_unsorted_input(self):
        assert _compute_intervals([30, 10, 20]) == [10, 10]

    def test_single_timestamp(self):
        assert _compute_intervals([42]) == []

    def test_empty(self):
        assert _compute_intervals([]) == []

    def test_two_timestamps(self):
        assert _compute_intervals([0, 15]) == [15]

    def test_negative_diff_not_possible_after_sort(self):
        # Even with reversed input, intervals are non-negative
        result = _compute_intervals([100, 50, 0])
        assert all(v >= 0 for v in result)
        assert result == [50, 50]


# ---------------------------------------------------------------------------
# _linear_slope()
# ---------------------------------------------------------------------------
class TestLinearSlope:
    def test_flat(self):
        assert _linear_slope([10, 10, 10, 10]) == 0.0

    def test_increasing(self):
        slope = _linear_slope([10, 20, 30, 40])
        assert slope == pytest.approx(10.0)

    def test_decreasing(self):
        slope = _linear_slope([40, 30, 20, 10])
        assert slope == pytest.approx(-10.0)

    def test_single_value(self):
        assert _linear_slope([42]) == 0.0

    def test_empty(self):
        assert _linear_slope([]) == 0.0

    def test_two_points(self):
        assert _linear_slope([5, 15]) == pytest.approx(10.0)

    def test_noisy_flat(self):
        slope = _linear_slope([10, 11, 9, 10, 10, 11, 9])
        assert abs(slope) < 0.5


# ---------------------------------------------------------------------------
# _coefficient_of_variation()
# ---------------------------------------------------------------------------
class TestCV:
    def test_constant(self):
        assert _coefficient_of_variation([15, 15, 15]) == 0.0

    def test_known_cv(self):
        # mean=10, sample stdev=5 → cv = 0.5
        cv = _coefficient_of_variation([5, 10, 15])
        assert cv == pytest.approx(5.0 / 10, rel=1e-3)

    def test_single_value(self):
        assert _coefficient_of_variation([42]) == 0.0

    def test_zero_mean(self):
        assert _coefficient_of_variation([0, 0, 0]) == 0.0


# ---------------------------------------------------------------------------
# AccelerationResult
# ---------------------------------------------------------------------------
class TestAccelerationResult:
    def test_healthy_steady(self):
        r = AccelerationResult(
            label="steady", slope=0.0, momentum=0.85,
            mean_interval=15.0, median_interval=15.0,
            jitter=0.1, n_intervals=20,
        )
        assert r.is_healthy is True

    def test_healthy_accelerating(self):
        r = AccelerationResult(
            label="accelerating", slope=-1.0, momentum=0.7,
            mean_interval=12.0, median_interval=11.0,
            jitter=0.15, n_intervals=20,
        )
        assert r.is_healthy is True

    def test_unhealthy_decelerating(self):
        r = AccelerationResult(
            label="decelerating", slope=2.0, momentum=0.3,
            mean_interval=25.0, median_interval=22.0,
            jitter=0.4, n_intervals=20,
        )
        assert r.is_healthy is False

    def test_unhealthy_stalled(self):
        r = AccelerationResult(
            label="stalled", slope=0.5, momentum=0.05,
            mean_interval=120.0, median_interval=100.0,
            jitter=0.8, n_intervals=10,
        )
        assert r.is_healthy is False

    def test_low_momentum_steady_is_unhealthy(self):
        r = AccelerationResult(
            label="steady", slope=0.0, momentum=0.3,
            mean_interval=30.0, median_interval=28.0,
            jitter=0.6, n_intervals=15,
        )
        assert r.is_healthy is False


# ---------------------------------------------------------------------------
# StrokeAccelerator.__init__()
# ---------------------------------------------------------------------------
class TestInit:
    def test_defaults(self):
        a = StrokeAccelerator()
        assert a.expected_cadence == DEFAULT_EXPECTED_CADENCE
        assert a.window == DEFAULT_WINDOW
        assert a.threshold == DEFAULT_THRESHOLD
        assert a.stall_factor == DEFAULT_STALL_FACTOR

    def test_custom(self):
        a = StrokeAccelerator(expected_cadence=30, window=10,
                              threshold=1.0, stall_factor=3.0)
        assert a.expected_cadence == 30
        assert a.window == 10

    def test_invalid_cadence(self):
        with pytest.raises(ValueError):
            StrokeAccelerator(expected_cadence=0)
        with pytest.raises(ValueError):
            StrokeAccelerator(expected_cadence=-5)

    def test_invalid_window(self):
        with pytest.raises(ValueError):
            StrokeAccelerator(window=0)

    def test_invalid_threshold(self):
        with pytest.raises(ValueError):
            StrokeAccelerator(threshold=-1)

    def test_invalid_stall_factor(self):
        with pytest.raises(ValueError):
            StrokeAccelerator(stall_factor=0)


# ---------------------------------------------------------------------------
# StrokeAccelerator.analyse()
# ---------------------------------------------------------------------------
class TestAnalyse:
    def _make_timestamps(self, intervals, start=1_000_000.0):
        """Build timestamp list from interval list."""
        ts = [start]
        for iv in intervals:
            ts.append(ts[-1] + iv)
        return ts

    def test_steady_production(self):
        # All intervals exactly 15s → slope 0, momentum 1.0
        ts = self._make_timestamps([15] * 25)
        r = StrokeAccelerator().analyse(ts)
        assert r.label == "steady"
        assert r.slope == 0.0
        assert r.momentum == 1.0
        assert r.mean_interval == 15.0
        assert r.n_intervals == 20  # default window

    def test_accelerating(self):
        # Intervals shrinking: 30, 28, 26, ..., 2 → strong negative slope
        intervals = [30 - i * 1.2 for i in range(25)]
        ts = self._make_timestamps(intervals)
        r = StrokeAccelerator(threshold=0.3).analyse(ts)
        assert r.label == "accelerating"
        assert r.slope < -0.3

    def test_decelerating(self):
        # Intervals growing: 5, 8, 11, 14, ... → positive slope
        intervals = [5 + i * 3 for i in range(25)]
        ts = self._make_timestamps(intervals)
        r = StrokeAccelerator(threshold=0.5).analyse(ts)
        assert r.label == "decelerating"
        assert r.slope > 0.5

    def test_stalled(self):
        # Mean interval way above expected cadence
        ts = self._make_timestamps([120] * 10)  # 120s >> 15s * 4
        r = StrokeAccelerator(expected_cadence=15).analyse(ts)
        assert r.label == "stalled"

    def test_window_truncation(self):
        # 50 intervals but window=10 → only last 10 analysed
        intervals = [15] * 40 + [30] * 10  # last 10 are 30s
        ts = self._make_timestamps(intervals)
        r = StrokeAccelerator(window=10).analyse(ts)
        assert r.n_intervals == 10
        assert r.mean_interval == 30.0

    def test_too_few_timestamps(self):
        with pytest.raises(ValueError, match="at least 2"):
            StrokeAccelerator().analyse([1000.0])

    def test_empty_timestamps(self):
        with pytest.raises(ValueError, match="at least 2"):
            StrokeAccelerator().analyse([])

    def test_jittery_but_steady(self):
        # High jitter but no directional trend
        import random
        random.seed(42)
        intervals = [15 + random.uniform(-5, 5) for _ in range(30)]
        r = StrokeAccelerator(threshold=1.0).analyse(self._make_timestamps(intervals))
        # Slope should be near zero (no trend), label steady
        assert r.label == "steady"
        assert abs(r.slope) < 1.0

    def test_momentum_range(self):
        ts = self._make_timestamps([15] * 20)
        r = StrokeAccelerator().analyse(ts)
        assert 0.0 <= r.momentum <= 1.0

    def test_unsorted_timestamps_ok(self):
        ts = [1000, 1060, 1015, 1030, 1045]
        r = StrokeAccelerator().analyse(ts)
        assert r.n_intervals == 4
        assert r.mean_interval == 15.0


# ---------------------------------------------------------------------------
# acceleration_summary()
# ---------------------------------------------------------------------------
class TestSummary:
    def test_format(self):
        ts = [float(i * 15) for i in range(25)]
        s = acceleration_summary(ts, expected_cadence=15, window=20)
        assert "stroke_accel:" in s
        assert "steady" in s
        assert "momentum" in s
        assert "20 intervals" in s

    def test_stalled_summary(self):
        ts = [float(i * 200) for i in range(10)]
        s = acceleration_summary(ts, expected_cadence=15, window=8)
        assert "stalled" in s
