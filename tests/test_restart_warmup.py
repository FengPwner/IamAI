"""Tests for iamai.restart_warmup module."""

import pytest

from iamai.restart_warmup import (
    DEFAULT_BUFFER_SIZE,
    RestartWarmup,
    WarmupReport,
    WarmupSample,
    classify_quality,
    _linear_slope,
    _median_sorted,
    THRESHOLD_INSTANT,
    THRESHOLD_FAST,
    THRESHOLD_NORMAL,
    THRESHOLD_SLOW,
)


# ── classify_quality ──────────────────────────────────────────


class TestClassifyQuality:
    def test_instant(self):
        assert classify_quality(0.0) == "instant"
        assert classify_quality(4.9) == "instant"

    def test_fast(self):
        assert classify_quality(5.0) == "fast"
        assert classify_quality(29.9) == "fast"

    def test_normal(self):
        assert classify_quality(30.0) == "normal"
        assert classify_quality(119.9) == "normal"

    def test_slow(self):
        assert classify_quality(120.0) == "slow"
        assert classify_quality(599.9) == "slow"

    def test_degraded(self):
        assert classify_quality(600.0) == "degraded"
        assert classify_quality(9999.0) == "degraded"

    def test_boundary_exact(self):
        assert classify_quality(THRESHOLD_INSTANT) == "fast"
        assert classify_quality(THRESHOLD_FAST) == "normal"
        assert classify_quality(THRESHOLD_NORMAL) == "slow"
        assert classify_quality(THRESHOLD_SLOW) == "degraded"


# ── WarmupSample ──────────────────────────────────────────────


class TestWarmupSample:
    def test_latency(self):
        s = WarmupSample(restart_ts=100.0, stroke_ts=112.0, pid=42)
        assert s.latency == 12.0

    def test_frozen(self):
        s = WarmupSample(restart_ts=100.0, stroke_ts=112.0)
        with pytest.raises(AttributeError):
            s.restart_ts = 200.0  # type: ignore

    def test_pid_optional(self):
        s = WarmupSample(restart_ts=100.0, stroke_ts=105.0)
        assert s.pid is None
        assert s.latency == 5.0


# ── RestartWarmup: recording ─────────────────────────────────


class TestRecording:
    def test_basic_match(self):
        w = RestartWarmup()
        w.record_restart(ts=1000.0, pid=42)
        sample = w.record_first_stroke(ts=1012.0, pid=42)
        assert sample is not None
        assert sample.latency == 12.0
        assert sample.pid == 42

    def test_unmatched_stroke_returns_none(self):
        w = RestartWarmup()
        assert w.record_first_stroke(ts=1000.0, pid=99) is None

    def test_pidless_match(self):
        w = RestartWarmup()
        w.record_restart(ts=500.0)
        sample = w.record_first_stroke(ts=506.0)
        assert sample is not None
        assert sample.latency == 6.0

    def test_clock_skew_rejected(self):
        w = RestartWarmup()
        w.record_restart(ts=1000.0, pid=1)
        sample = w.record_first_stroke(ts=999.0, pid=1)
        assert sample is None

    def test_multiple_restarts_same_pid(self):
        w = RestartWarmup()
        w.record_restart(ts=100.0, pid=1)
        w.record_restart(ts=200.0, pid=1)
        sample = w.record_first_stroke(ts=210.0, pid=1)
        assert sample is not None
        assert sample.latency == 10.0  # matched to latest restart

    def test_different_pids(self):
        w = RestartWarmup()
        w.record_restart(ts=100.0, pid=1)
        w.record_restart(ts=200.0, pid=2)
        s2 = w.record_first_stroke(ts=210.0, pid=2)
        s1 = w.record_first_stroke(ts=115.0, pid=1)
        assert s2 is not None
        assert s2.latency == 10.0
        assert s1 is not None
        assert s1.latency == 15.0

    def test_sample_count(self):
        w = RestartWarmup()
        assert w.sample_count() == 0
        w.record_restart(ts=100.0, pid=1)
        w.record_first_stroke(ts=110.0, pid=1)
        assert w.sample_count() == 1

    def test_add_sample_direct(self):
        w = RestartWarmup()
        s = w.add_sample(restart_ts=100.0, stroke_ts=115.0, pid=7)
        assert s.latency == 15.0
        assert w.sample_count() == 1


# ── RestartWarmup: queries ────────────────────────────────────


class TestQueries:
    def _make_tracker_with_samples(self, latencies):
        w = RestartWarmup()
        for i, lat in enumerate(latencies):
            w.add_sample(
                restart_ts=float(i * 1000),
                stroke_ts=float(i * 1000 + lat),
            )
        return w

    def test_last_latency_empty(self):
        w = RestartWarmup()
        assert w.last_latency() is None

    def test_last_latency(self):
        w = self._make_tracker_with_samples([5.0, 10.0, 15.0])
        assert w.last_latency() == 15.0

    def test_quality_empty(self):
        w = RestartWarmup()
        assert w.quality() == "unknown"

    def test_quality(self):
        w = self._make_tracker_with_samples([8.0])
        assert w.quality() == "fast"

    def test_trend_insufficient_data(self):
        w = self._make_tracker_with_samples([5.0, 10.0])
        assert w.trend() == "insufficient_data"

    def test_trend_stable(self):
        w = self._make_tracker_with_samples([10.0, 10.5, 10.0, 10.5, 10.0])
        assert w.trend() == "stable"

    def test_trend_improving(self):
        w = self._make_tracker_with_samples([50.0, 40.0, 30.0, 20.0, 10.0])
        assert w.trend() == "improving"

    def test_trend_degrading(self):
        w = self._make_tracker_with_samples([10.0, 20.0, 30.0, 40.0, 50.0])
        assert w.trend() == "degrading"

    def test_statistics_empty(self):
        w = RestartWarmup()
        stats = w.statistics()
        assert stats["samples"] == 0
        assert stats["mean"] is None

    def test_statistics(self):
        w = self._make_tracker_with_samples([10.0, 20.0, 30.0])
        stats = w.statistics()
        assert stats["samples"] == 3
        assert stats["mean"] == pytest.approx(20.0)
        assert stats["median"] == pytest.approx(20.0)
        assert stats["min"] == pytest.approx(10.0)
        assert stats["max"] == pytest.approx(30.0)

    def test_statistics_even_count(self):
        w = self._make_tracker_with_samples([10.0, 20.0, 30.0, 40.0])
        stats = w.statistics()
        assert stats["median"] == pytest.approx(25.0)


# ── RestartWarmup: report ─────────────────────────────────────


class TestReport:
    def test_report_empty(self):
        w = RestartWarmup()
        r = w.report()
        assert isinstance(r, WarmupReport)
        assert r.samples == 0
        assert r.quality == "unknown"
        assert r.trend == "insufficient_data"
        assert r.one_liner() == "no warmup data"

    def test_report_with_data(self):
        w = RestartWarmup()
        for lat in [5.0, 10.0, 15.0, 12.0, 8.0]:
            w.add_sample(restart_ts=100.0, stroke_ts=100.0 + lat)
        r = w.report()
        assert r.samples == 5
        assert r.last_latency_s == pytest.approx(8.0)
        assert r.quality == "fast"
        assert "warmup:" in r.one_liner()

    def test_report_frozen(self):
        w = RestartWarmup()
        w.add_sample(restart_ts=100.0, stroke_ts=110.0)
        r = w.report()
        with pytest.raises(AttributeError):
            r.samples = 99  # type: ignore

    def test_summary_string(self):
        w = RestartWarmup()
        w.add_sample(restart_ts=100.0, stroke_ts=108.0)
        s = w.summary()
        assert "warmup:" in s
        assert "fast" in s


# ── RestartWarmup: buffer management ──────────────────────────


class TestBuffer:
    def test_ring_buffer_cap(self):
        w = RestartWarmup(buffer_size=5)
        for i in range(20):
            w.add_sample(restart_ts=float(i * 100), stroke_ts=float(i * 100 + 10))
        assert w.sample_count() == 5
        # oldest kept should be sample #15
        assert w.last_latency() == 10.0

    def test_clear(self):
        w = RestartWarmup()
        w.record_restart(ts=100.0, pid=1)
        w.add_sample(restart_ts=200.0, stroke_ts=210.0)
        w.clear()
        assert w.sample_count() == 0
        assert w.last_latency() is None
        # pending restart should also be cleared
        assert w.record_first_stroke(ts=300.0, pid=1) is None


# ── RestartWarmup: ingest_events ──────────────────────────────


class TestIngest:
    def test_ingest_basic(self):
        w = RestartWarmup()
        events = [
            {"event": "restart", "ts": 1000.0, "pid": 42},
            {"event": "first_stroke", "ts": 1012.0, "pid": 42},
            {"event": "restart", "ts": 2000.0, "pid": 43},
            {"event": "first_stroke", "ts": 2005.0, "pid": 43},
        ]
        added = w.ingest_events(events)
        assert added == 2
        assert w.sample_count() == 2

    def test_ingest_unmatched(self):
        w = RestartWarmup()
        events = [
            {"event": "first_stroke", "ts": 1000.0, "pid": 42},
        ]
        added = w.ingest_events(events)
        assert added == 0

    def test_ingest_empty_list(self):
        w = RestartWarmup()
        assert w.ingest_events([]) == 0

    def test_ingest_with_string_ts(self):
        w = RestartWarmup()
        events = [
            {"event": "restart", "ts": "1000.0", "pid": 42},
            {"event": "first_stroke", "ts": "1010.0", "pid": 42},
        ]
        added = w.ingest_events(events)
        assert added == 1
        assert w.last_latency() == pytest.approx(10.0)


# ── helper functions ──────────────────────────────────────────


class TestHelpers:
    def test_linear_slope_flat(self):
        assert _linear_slope([5.0, 5.0, 5.0, 5.0]) == pytest.approx(0.0)

    def test_linear_slope_positive(self):
        slope = _linear_slope([1.0, 2.0, 3.0, 4.0, 5.0])
        assert slope == pytest.approx(1.0)

    def test_linear_slope_negative(self):
        slope = _linear_slope([5.0, 4.0, 3.0, 2.0, 1.0])
        assert slope == pytest.approx(-1.0)

    def test_linear_slope_single(self):
        assert _linear_slope([42.0]) == 0.0

    def test_linear_slope_empty(self):
        assert _linear_slope([]) == 0.0

    def test_median_sorted_odd(self):
        assert _median_sorted([1.0, 2.0, 3.0]) == 2.0

    def test_median_sorted_even(self):
        assert _median_sorted([1.0, 2.0, 3.0, 4.0]) == 2.5

    def test_median_sorted_single(self):
        assert _median_sorted([7.0]) == 7.0

    def test_median_sorted_empty(self):
        assert _median_sorted([]) == 0.0


# ── edge cases ────────────────────────────────────────────────


class TestEdgeCases:
    def test_zero_latency(self):
        w = RestartWarmup()
        w.record_restart(ts=100.0, pid=1)
        sample = w.record_first_stroke(ts=100.0, pid=1)
        assert sample is not None
        assert sample.latency == 0.0
        assert w.quality() == "instant"

    def test_very_large_latency(self):
        w = RestartWarmup()
        w.add_sample(restart_ts=0.0, stroke_ts=86400.0)
        assert w.quality() == "degraded"
        assert w.last_latency() == 86400.0

    def test_default_buffer_size(self):
        assert DEFAULT_BUFFER_SIZE == 500

    def test_trend_window_larger_than_data(self):
        w = RestartWarmup()
        for lat in [10.0, 10.0, 10.0]:
            w.add_sample(restart_ts=100.0, stroke_ts=100.0 + lat)
        assert w.trend(window=100) == "stable"

    def test_pidless_then_pid(self):
        w = RestartWarmup()
        w.record_restart(ts=100.0)
        w.record_restart(ts=200.0, pid=5)
        # pid=5 matches the pid=200 restart
        s = w.record_first_stroke(ts=205.0, pid=5)
        assert s is not None
        assert s.latency == 5.0
