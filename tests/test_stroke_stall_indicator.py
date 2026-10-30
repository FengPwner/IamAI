"""tests for iamai.stroke_stall_indicator"""

import pytest

from iamai.stroke_stall_indicator import (
    DEFAULT_EXPECTED_CADENCE,
    DEFAULT_MAX_CV,
    DEFAULT_MAX_RATIO,
    DEFAULT_MAX_SLOPE,
    DEFAULT_MIN_CV,
    DEFAULT_W_ACCEL,
    DEFAULT_W_CADENCE,
    DEFAULT_W_JITTER,
    DEFAULT_WINDOW,
    StallIndicatorResult,
    StrokeStallIndicator,
    _clamp,
    _classify,
    stall_indicator_summary,
)


# ---------------------------------------------------------------------------
# _clamp()
# ---------------------------------------------------------------------------
class TestClamp:
    def test_within_range(self):
        assert _clamp(0.5, 0.0, 1.0) == 0.5

    def test_below_min(self):
        assert _clamp(-0.5, 0.0, 1.0) == 0.0

    def test_above_max(self):
        assert _clamp(1.5, 0.0, 1.0) == 1.0

    def test_at_boundary(self):
        assert _clamp(0.0, 0.0, 1.0) == 0.0
        assert _clamp(1.0, 0.0, 1.0) == 1.0


# ---------------------------------------------------------------------------
# _classify()
# ---------------------------------------------------------------------------
class TestClassify:
    def test_healthy(self):
        assert _classify(0.0) == "healthy"
        assert _classify(0.10) == "healthy"
        assert _classify(0.24) == "healthy"

    def test_watchful(self):
        assert _classify(0.25) == "watchful"
        assert _classify(0.40) == "watchful"
        assert _classify(0.49) == "watchful"

    def test_warning(self):
        assert _classify(0.50) == "warning"
        assert _classify(0.60) == "warning"
        assert _classify(0.74) == "warning"

    def test_critical(self):
        assert _classify(0.75) == "critical"
        assert _classify(0.90) == "critical"
        assert _classify(1.0) == "critical"


# ---------------------------------------------------------------------------
# StallIndicatorResult
# ---------------------------------------------------------------------------
class TestResult:
    def test_healthy_is_healthy(self):
        r = StallIndicatorResult(score=0.10, tier="healthy")
        assert r.is_healthy is True
        assert r.needs_attention is False

    def test_watchful_not_healthy(self):
        r = StallIndicatorResult(score=0.35, tier="watchful")
        assert r.is_healthy is False
        assert r.needs_attention is False

    def test_warning_needs_attention(self):
        r = StallIndicatorResult(score=0.60, tier="warning")
        assert r.is_healthy is False
        assert r.needs_attention is True

    def test_critical_needs_attention(self):
        r = StallIndicatorResult(score=0.85, tier="critical")
        assert r.is_healthy is False
        assert r.needs_attention is True


# ---------------------------------------------------------------------------
# StrokeStallIndicator.__init__()
# ---------------------------------------------------------------------------
class TestInit:
    def test_defaults(self):
        ind = StrokeStallIndicator()
        assert ind.expected_cadence == DEFAULT_EXPECTED_CADENCE
        assert ind.window == DEFAULT_WINDOW
        assert ind.max_ratio == DEFAULT_MAX_RATIO
        assert ind.max_slope == DEFAULT_MAX_SLOPE
        assert ind.min_cv == DEFAULT_MIN_CV
        assert ind.max_cv == DEFAULT_MAX_CV
        assert ind.w_cadence == DEFAULT_W_CADENCE
        assert ind.w_accel == DEFAULT_W_ACCEL
        assert ind.w_jitter == DEFAULT_W_JITTER

    def test_custom(self):
        ind = StrokeStallIndicator(
            expected_cadence=30, window=10, max_ratio=3.0,
            max_slope=2.0, min_cv=0.2, max_cv=0.8,
            w_cadence=0.4, w_accel=0.4, w_jitter=0.2,
        )
        assert ind.expected_cadence == 30
        assert ind.window == 10
        assert ind.max_ratio == 3.0

    def test_invalid_cadence(self):
        with pytest.raises(ValueError):
            StrokeStallIndicator(expected_cadence=0)
        with pytest.raises(ValueError):
            StrokeStallIndicator(expected_cadence=-5)

    def test_invalid_window(self):
        with pytest.raises(ValueError):
            StrokeStallIndicator(window=1)
        with pytest.raises(ValueError):
            StrokeStallIndicator(window=0)

    def test_invalid_max_ratio(self):
        with pytest.raises(ValueError):
            StrokeStallIndicator(max_ratio=1.0)
        with pytest.raises(ValueError):
            StrokeStallIndicator(max_ratio=0.5)

    def test_invalid_max_slope(self):
        with pytest.raises(ValueError):
            StrokeStallIndicator(max_slope=0)

    def test_invalid_min_cv(self):
        with pytest.raises(ValueError):
            StrokeStallIndicator(min_cv=-0.1)

    def test_invalid_max_cv(self):
        with pytest.raises(ValueError):
            StrokeStallIndicator(min_cv=0.5, max_cv=0.3)

    def test_negative_weight(self):
        with pytest.raises(ValueError):
            StrokeStallIndicator(w_cadence=-0.1)
        with pytest.raises(ValueError):
            StrokeStallIndicator(w_accel=-0.1)
        with pytest.raises(ValueError):
            StrokeStallIndicator(w_jitter=-0.1)


# ---------------------------------------------------------------------------
# StrokeStallIndicator.analyse()
# ---------------------------------------------------------------------------
class TestAnalyse:
    def _make_timestamps(self, intervals, start=1_000_000.0):
        """Build timestamp list from interval list."""
        ts = [start]
        for iv in intervals:
            ts.append(ts[-1] + iv)
        return ts

    def test_perfectly_healthy(self):
        """All intervals exactly 15s → score 0, tier healthy."""
        ts = self._make_timestamps([15] * 25)
        r = StrokeStallIndicator().analyse(ts)
        assert r.score == 0.0
        assert r.tier == "healthy"
        assert r.signals["cadence"] == 0.0
        assert r.signals["acceleration"] == 0.0
        assert r.signals["jitter"] == 0.0
        assert r.n_intervals == 20

    def test_healthy_with_small_jitter(self):
        """Small random jitter around expected cadence → still healthy."""
        import random
        random.seed(42)
        intervals = [15 + random.uniform(-2, 2) for _ in range(30)]
        r = StrokeStallIndicator().analyse(self._make_timestamps(intervals))
        assert r.tier == "healthy"
        assert r.score < 0.25

    def test_watchful_slow_writer(self):
        """Intervals well above expected → watchful or higher."""
        # mean ~40s vs expected 15s → ratio 2.67 → cadence signal ~0.56
        # score = 0.50 * 0.56 = 0.28 → watchful
        intervals = [40] * 25
        r = StrokeStallIndicator().analyse(self._make_timestamps(intervals))
        assert r.tier in ("watchful", "warning")
        assert r.signals["cadence"] > 0

    def test_warning_decelerating(self):
        """Intervals growing steadily → elevated score from acceleration signal."""
        intervals = [10 + i * 2 for i in range(25)]
        r = StrokeStallIndicator().analyse(self._make_timestamps(intervals))
        assert r.signals["acceleration"] > 0
        assert r.tier in ("watchful", "warning", "critical")
        # Score should be meaningfully elevated
        assert r.score >= 0.30

    def test_warning_strong_deceleration(self):
        """Strongly growing intervals → warning tier."""
        intervals = [10 + i * 5 for i in range(25)]
        r = StrokeStallIndicator().analyse(self._make_timestamps(intervals))
        assert r.signals["acceleration"] > 0.5
        assert r.tier in ("warning", "critical")

    def test_critical_stalled(self):
        """Very long AND growing intervals → critical."""
        # mean ~100s >> 15s expected, AND growing → all signals fire
        intervals = [80 + i * 5 for i in range(10)]
        ts = self._make_timestamps(intervals)
        r = StrokeStallIndicator().analyse(ts)
        assert r.tier == "critical"
        assert r.score >= 0.75

    def test_window_truncation(self):
        """Only the most recent `window` intervals are analysed."""
        intervals = [15] * 40 + [60] * 10
        ts = self._make_timestamps(intervals)
        r = StrokeStallIndicator(window=10).analyse(ts)
        assert r.n_intervals == 10
        assert r.mean_interval == 60.0

    def test_too_few_timestamps(self):
        with pytest.raises(ValueError, match="at least 3"):
            StrokeStallIndicator().analyse([1000.0, 1015.0])

    def test_single_timestamp(self):
        with pytest.raises(ValueError, match="at least 3"):
            StrokeStallIndicator().analyse([1000.0])

    def test_empty_timestamps(self):
        with pytest.raises(ValueError, match="at least 3"):
            StrokeStallIndicator().analyse([])

    def test_score_range(self):
        """Score is always in [0, 1]."""
        ts = self._make_timestamps([15] * 20)
        r = StrokeStallIndicator().analyse(ts)
        assert 0.0 <= r.score <= 1.0

    def test_unsorted_timestamps(self):
        """Timestamps need not be pre-sorted."""
        ts = [1000, 1060, 1015, 1030, 1045, 1075, 1090]
        r = StrokeStallIndicator().analyse(ts)
        assert r.n_intervals == 6
        assert r.mean_interval == 15.0

    def test_custom_weights(self):
        """Custom weights change the score."""
        intervals = [25] * 25  # slow writer
        ts = self._make_timestamps(intervals)
        # Cadence-only indicator
        r1 = StrokeStallIndicator(w_cadence=1.0, w_accel=0.0, w_jitter=0.0).analyse(ts)
        # Jitter-only indicator
        r2 = StrokeStallIndicator(w_cadence=0.0, w_accel=0.0, w_jitter=1.0).analyse(ts)
        # With zero jitter (constant intervals), jitter signal = 0
        assert r2.score == 0.0
        # Cadence signal > 0 since mean > expected
        assert r1.score > 0

    def test_signals_dict_keys(self):
        ts = self._make_timestamps([15] * 20)
        r = StrokeStallIndicator().analyse(ts)
        assert set(r.signals.keys()) == {"cadence", "acceleration", "jitter"}

    def test_mixed_degradation(self):
        """Writer starts fast then slows — combined signals."""
        # First half: 15s, second half: 30s → both cadence and accel contribute
        intervals = [15] * 10 + [30] * 10
        ts = self._make_timestamps(intervals)
        r = StrokeStallIndicator().analyse(ts)
        assert r.signals["cadence"] > 0  # mean > expected
        # The step-change creates a positive slope in the window
        assert r.n_intervals == 20


# ---------------------------------------------------------------------------
# stall_indicator_summary()
# ---------------------------------------------------------------------------
class TestSummary:
    def test_format(self):
        ts = [float(i * 15) for i in range(25)]
        s = stall_indicator_summary(ts, expected_cadence=15, window=20)
        assert "stall_indicator:" in s
        assert "healthy" in s
        assert "20 intervals" in s

    def test_critical_summary(self):
        # Long AND growing intervals → critical
        intervals = [150 + i * 10 for i in range(10)]
        ts_base = 1_000_000.0
        ts = [ts_base]
        for iv in intervals:
            ts.append(ts[-1] + iv)
        s = stall_indicator_summary(ts, expected_cadence=15, window=8)
        assert "critical" in s or "warning" in s
        # At minimum the score should be elevated
        assert any(t in s for t in ("warning", "critical"))
