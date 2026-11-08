"""Tests for iamai.restart_smoothness module."""

import pytest

from iamai.restart_smoothness import RestartSmoothness, smoothness_report


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_strokes(start, interval, count, jitter=None):
    """Generate a sequence of stroke timestamps with optional jitter."""
    import random

    if jitter is not None:
        random.seed(42)
    times = []
    t = start
    for _ in range(count):
        times.append(t)
        delta = interval
        if jitter:
            delta += random.uniform(-jitter, jitter)
        t += max(0.1, delta)
    return times


@pytest.fixture
def clean_restart():
    """10 strokes, then 120s gap (restart), then 20 clean strokes at 15s."""
    pre = _make_strokes(1000.0, 15.0, 10)
    # restart gap: 120 seconds after last pre-restart stroke
    post_start = pre[-1] + 120.0
    post = _make_strokes(post_start, 15.0, 20)
    return pre + post


@pytest.fixture
def slow_restart():
    """10 strokes, then 600s gap, then 10 strokes with high jitter."""
    pre = _make_strokes(1000.0, 15.0, 10)
    post_start = pre[-1] + 600.0
    post = _make_strokes(post_start, 15.0, 10, jitter=8.0)
    return pre + post


@pytest.fixture
def fast_restart():
    """10 strokes, then 18s gap, then 30 tight strokes at 15s."""
    pre = _make_strokes(1000.0, 15.0, 10)
    post_start = pre[-1] + 18.0
    post = _make_strokes(post_start, 15.0, 30, jitter=0.5)
    return pre + post


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


class TestRestartDetection:
    def test_detects_largest_gap(self, clean_restart):
        rs = RestartSmoothness(clean_restart, expected_interval=15.0)
        assert rs.post_stroke_count == 20

    def test_no_restart_in_uniform_sequence(self):
        strokes = _make_strokes(0.0, 15.0, 50)
        rs = RestartSmoothness(strokes, expected_interval=15.0)
        # no gap > 30s, so entire sequence is "post"
        assert rs.post_stroke_count == 50

    def test_explicit_restart_time(self):
        strokes = _make_strokes(0.0, 15.0, 20)
        restart_at = strokes[9] + 60.0
        post_strokes = [t for t in strokes if t >= restart_at]
        rs = RestartSmoothness(strokes, expected_interval=15.0, restart_time=restart_at)
        assert rs.post_stroke_count == len(post_strokes)

    def test_empty_sequence(self):
        rs = RestartSmoothness([], expected_interval=15.0)
        assert rs.post_stroke_count == 0
        assert rs.warmup_s == float("inf")

    def test_single_stroke(self):
        rs = RestartSmoothness([1000.0], expected_interval=15.0)
        assert rs.post_stroke_count == 1


# ---------------------------------------------------------------------------
# Warmup
# ---------------------------------------------------------------------------


class TestWarmup:
    def test_fast_restart_warmup(self, fast_restart):
        rs = RestartSmoothness(fast_restart, expected_interval=15.0)
        # gap is 18s, first stroke at post_start which is ~18s after last pre
        # warmup is measured from restart_time (inferred as pre_last + interval)
        assert rs.warmup_s < 30.0

    def test_first_stroke_ok_fast(self, fast_restart):
        rs = RestartSmoothness(fast_restart, expected_interval=15.0)
        assert rs.first_stroke_ok is True

    def test_slow_restart_warmup(self, slow_restart):
        rs = RestartSmoothness(slow_restart, expected_interval=15.0)
        assert rs.gap_loss_s > 500.0


# ---------------------------------------------------------------------------
# Settle
# ---------------------------------------------------------------------------


class TestSettle:
    def test_clean_settles_quickly(self, clean_restart):
        rs = RestartSmoothness(clean_restart, expected_interval=15.0)
        assert rs.settle_strokes <= 5

    def test_noisy_takes_longer(self, slow_restart):
        rs = RestartSmoothness(slow_restart, expected_interval=15.0)
        assert rs.settle_strokes >= 1

    def test_single_post_stroke(self):
        rs = RestartSmoothness([1000.0, 2000.0], expected_interval=15.0)
        assert rs.settle_strokes <= 1


# ---------------------------------------------------------------------------
# Gap loss
# ---------------------------------------------------------------------------


class TestGapLoss:
    def test_clean_restart_loss(self, clean_restart):
        rs = RestartSmoothness(clean_restart, expected_interval=15.0)
        # gap is ~120s, expected 15s, so loss ~105s
        assert 90.0 < rs.gap_loss_s < 130.0

    def test_fast_restart_loss(self, fast_restart):
        rs = RestartSmoothness(fast_restart, expected_interval=15.0)
        # gap is ~18s, expected 15s, so loss ~3s
        assert rs.gap_loss_s < 10.0

    def test_no_pre_restart_data(self):
        strokes = _make_strokes(0.0, 15.0, 10)
        rs = RestartSmoothness(strokes, expected_interval=15.0)
        assert rs.gap_loss_s == 0.0


# ---------------------------------------------------------------------------
# Grade
# ---------------------------------------------------------------------------


class TestGrade:
    def test_fast_restart_is_smooth(self, fast_restart):
        rs = RestartSmoothness(fast_restart, expected_interval=15.0)
        assert rs.grade in ("smooth", "acceptable")

    def test_slow_restart_is_rough_or_worse(self, slow_restart):
        rs = RestartSmoothness(slow_restart, expected_interval=15.0)
        assert rs.grade in ("rough", "slow", "painful")

    def test_grade_is_valid_string(self, clean_restart):
        rs = RestartSmoothness(clean_restart, expected_interval=15.0)
        assert rs.grade in ("smooth", "acceptable", "rough", "slow", "painful")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_keys(self, clean_restart):
        rs = RestartSmoothness(clean_restart, expected_interval=15.0)
        s = rs.summary()
        expected_keys = {
            "warmup_s", "first_stroke_ok", "settle_strokes", "gap_loss_s",
            "post_stroke_count", "post_interval_mean", "post_interval_jitter",
            "grade",
        }
        assert set(s.keys()) == expected_keys

    def test_summary_types(self, clean_restart):
        rs = RestartSmoothness(clean_restart, expected_interval=15.0)
        s = rs.summary()
        assert isinstance(s["warmup_s"], float)
        assert isinstance(s["first_stroke_ok"], bool)
        assert isinstance(s["settle_strokes"], int)
        assert isinstance(s["gap_loss_s"], float)
        assert isinstance(s["post_stroke_count"], int)
        assert isinstance(s["grade"], str)

    def test_empty_summary(self):
        rs = RestartSmoothness([], expected_interval=15.0)
        s = rs.summary()
        assert s["warmup_s"] == float("inf")
        assert s["post_stroke_count"] == 0


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestReport:
    def test_report_format(self, clean_restart):
        report = smoothness_report(clean_restart, expected_interval=15.0)
        assert "restart:" in report
        assert "warmup" in report
        assert "settled" in report
        assert "gap loss" in report

    def test_report_with_explicit_restart(self):
        strokes = _make_strokes(0.0, 15.0, 20)
        report = smoothness_report(strokes, expected_interval=15.0, restart_time=strokes[10])
        assert "restart:" in report

    def test_report_empty(self):
        report = smoothness_report([], expected_interval=15.0)
        assert "restart:" in report
        assert "inf" in report


# ---------------------------------------------------------------------------
# Interval metrics
# ---------------------------------------------------------------------------


class TestIntervalMetrics:
    def test_post_interval_mean_clean(self, clean_restart):
        rs = RestartSmoothness(clean_restart, expected_interval=15.0)
        # clean strokes at 15s → mean should be close to 15
        assert 14.0 < rs.post_interval_mean < 16.0

    def test_post_interval_jitter_clean(self, clean_restart):
        rs = RestartSmoothness(clean_restart, expected_interval=15.0)
        # clean strokes → low jitter
        assert rs.post_interval_jitter < 0.1

    def test_insufficient_data(self):
        rs = RestartSmoothness([1000.0], expected_interval=15.0)
        assert rs.post_interval_mean == float("inf")
        assert rs.post_interval_jitter == float("inf")
