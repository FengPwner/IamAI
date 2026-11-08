"""Tests for iamai.heartbeat_regularity — measuring writing rhythm health.

Each test constructs stroke sequences with known timing patterns and
verifies the rhythm metrics are computed correctly.  No file I/O
needed — all timestamps are synthetic.
"""

import math

import pytest

from iamai.heartbeat_regularity import (
    HeartbeatMonitor,
    StrokeEvent,
    regularity_report,
)


# --- helpers ---


def _make_monitor(timestamps, expected_interval=15.0, **kwargs):
    """Build a monitor pre-loaded with the given timestamps."""
    m = HeartbeatMonitor(expected_interval=expected_interval, **kwargs)
    m.record_strokes(timestamps)
    return m


def _perfect_cadence(n, interval=15.0, start=0.0):
    """Generate n perfectly spaced timestamps."""
    return [start + i * interval for i in range(n)]


# --- StrokeEvent ---


class TestStrokeEvent:
    def test_frozen(self):
        e = StrokeEvent(timestamp=100.0)
        with pytest.raises(AttributeError):
            e.timestamp = 200.0

    def test_negative_timestamp_rejected(self):
        with pytest.raises(ValueError):
            StrokeEvent(timestamp=-1.0)

    def test_zero_timestamp_ok(self):
        e = StrokeEvent(timestamp=0.0)
        assert e.timestamp == 0.0


# --- basic recording ---


class TestRecording:
    def test_stroke_count_empty(self):
        m = HeartbeatMonitor()
        assert m.stroke_count == 0

    def test_record_single(self):
        m = HeartbeatMonitor()
        m.record_stroke(100.0)
        assert m.stroke_count == 1

    def test_record_strokes_batch(self):
        m = HeartbeatMonitor()
        m.record_strokes([100.0, 115.0, 130.0])
        assert m.stroke_count == 3

    def test_record_preserves_order(self):
        """Strokes recorded out of order should still produce correct intervals."""
        m = HeartbeatMonitor()
        m.record_strokes([130.0, 100.0, 115.0])
        ivs = m.intervals()
        assert ivs == [15.0, 15.0]


# --- intervals ---


class TestIntervals:
    def test_no_strokes(self):
        m = HeartbeatMonitor()
        assert m.intervals() == []

    def test_one_stroke(self):
        m = HeartbeatMonitor()
        m.record_stroke(100.0)
        assert m.intervals() == []

    def test_two_strokes(self):
        m = _make_monitor([100.0, 120.0])
        assert m.intervals() == [20.0]

    def test_perfect_cadence(self):
        m = _make_monitor(_perfect_cadence(10))
        ivs = m.intervals()
        assert len(ivs) == 9
        assert all(iv == 15.0 for iv in ivs)


# --- coefficient of variation ---


class TestCV:
    def test_no_data(self):
        m = HeartbeatMonitor()
        assert m.coefficient_of_variation() is None

    def test_one_stroke(self):
        m = HeartbeatMonitor()
        m.record_stroke(100.0)
        assert m.coefficient_of_variation() is None

    def test_perfect_cadence_cv_zero(self):
        m = _make_monitor(_perfect_cadence(20))
        assert m.coefficient_of_variation() == pytest.approx(0.0)

    def test_moderate_variation(self):
        """Alternating 10s and 20s gaps → mean=15, stddev=5, CV=1/3."""
        ts = [0.0]
        for i in range(10):
            ts.append(ts[-1] + (10.0 if i % 2 == 0 else 20.0))
        m = _make_monitor(ts)
        cv = m.coefficient_of_variation()
        assert cv == pytest.approx(5.0 / 15.0, abs=0.01)

    def test_identical_timestamps(self):
        """All strokes at same time → all intervals zero → CV = inf."""
        m = _make_monitor([100.0, 100.0, 100.0])
        cv = m.coefficient_of_variation()
        # mean=0 → CV is inf
        assert cv == float("inf")


# --- regularity score ---


class TestRegularityScore:
    def test_no_data(self):
        m = HeartbeatMonitor()
        assert m.regularity_score() is None

    def test_perfect_cadence_score_one(self):
        m = _make_monitor(_perfect_cadence(50))
        assert m.regularity_score() == pytest.approx(1.0)

    def test_score_decreases_with_variation(self):
        m_perfect = _make_monitor(_perfect_cadence(20))
        ts_noisy = [0.0]
        import random
        random.seed(42)
        for _ in range(19):
            ts_noisy.append(ts_noisy[-1] + random.uniform(5.0, 25.0))
        m_noisy = _make_monitor(ts_noisy)
        assert m_perfect.regularity_score() > m_noisy.regularity_score()

    def test_score_clamped_to_zero(self):
        """CV > 2.0 should clamp score to 0."""
        # Mostly 15s gaps with one massive outlier → CV >> 2.0
        ts = [0.0]
        for _ in range(9):
            ts.append(ts[-1] + 15.0)
        ts.append(ts[-1] + 5000.0)
        m = _make_monitor(ts, expected_interval=15.0)
        cv = m.coefficient_of_variation()
        assert cv > 2.0, f"expected CV > 2.0, got {cv}"
        assert m.regularity_score() == 0.0

    def test_score_clamped_to_one(self):
        """CV = 0 → score = 1.0."""
        m = _make_monitor(_perfect_cadence(10))
        assert m.regularity_score() == 1.0


# --- burst detection ---


class TestBurstCount:
    def test_no_bursts_perfect_cadence(self):
        m = _make_monitor(_perfect_cadence(20))
        assert m.burst_count() == 0

    def test_single_burst(self):
        """Three strokes within 7.5s of each other = one burst."""
        ts = [0.0, 3.0, 6.0, 100.0, 115.0, 130.0]
        m = _make_monitor(ts, expected_interval=15.0)
        assert m.burst_count() == 1

    def test_two_bursts(self):
        ts = [0.0, 2.0, 4.0, 100.0, 200.0, 202.0, 204.0, 300.0]
        m = _make_monitor(ts, expected_interval=15.0)
        assert m.burst_count() == 2

    def test_no_burst_with_two_close(self):
        """Only 2 close strokes doesn't count as burst (need ≥3)."""
        ts = [0.0, 3.0, 100.0, 115.0]
        m = _make_monitor(ts, expected_interval=15.0)
        assert m.burst_count() == 0

    def test_fewer_than_three_strokes(self):
        m = _make_monitor([0.0, 1.0])
        assert m.burst_count() == 0

    def test_empty(self):
        m = HeartbeatMonitor()
        assert m.burst_count() == 0


# --- silence metrics ---


class TestSilence:
    def test_longest_silence_empty(self):
        m = HeartbeatMonitor()
        assert m.longest_silence() is None

    def test_longest_silence_perfect(self):
        m = _make_monitor(_perfect_cadence(10))
        assert m.longest_silence() == pytest.approx(15.0)

    def test_longest_silence_with_gap(self):
        ts = [0.0, 15.0, 30.0, 300.0, 315.0]
        m = _make_monitor(ts)
        assert m.longest_silence() == pytest.approx(270.0)

    def test_silence_ratio_empty(self):
        m = HeartbeatMonitor()
        assert m.silence_ratio() is None

    def test_silence_ratio_perfect(self):
        m = _make_monitor(_perfect_cadence(10), expected_interval=15.0)
        assert m.silence_ratio() == pytest.approx(1.0)

    def test_silence_ratio_with_stall(self):
        ts = [0.0, 15.0, 30.0, 500.0, 515.0]
        m = _make_monitor(ts, expected_interval=15.0)
        assert m.silence_ratio() == pytest.approx(470.0 / 15.0, abs=0.1)


# --- rhythm grade ---


class TestRhythmGrade:
    def test_no_data(self):
        m = HeartbeatMonitor()
        assert m.rhythm_grade() is None

    def test_healthy(self):
        m = _make_monitor(_perfect_cadence(50))
        assert m.rhythm_grade() == "healthy"

    def test_wobbly(self):
        """CV around 0.33 → wobbly."""
        ts = [0.0]
        for i in range(20):
            ts.append(ts[-1] + (10.0 if i % 2 == 0 else 20.0))
        m = _make_monitor(ts, expected_interval=15.0)
        assert m.rhythm_grade() == "wobbly"

    def test_stalled_by_silence(self):
        """Huge silence overrides CV → stalled."""
        ts = [0.0, 15.0, 30.0, 10000.0, 10015.0]
        m = _make_monitor(ts, expected_interval=15.0, stall_multiplier=20.0)
        assert m.rhythm_grade() == "stalled"

    def test_stalled_by_cv(self):
        """CV > 2.0 → stalled even without huge silence."""
        # Nine 5s gaps and one 500s gap → CV ≈ 2.6, silence_ratio = 33.3
        # Use stall_multiplier=100 so silence_ratio(33.3) doesn't trigger stalled
        ts = [0.0]
        for _ in range(9):
            ts.append(ts[-1] + 5.0)
        ts.append(ts[-1] + 500.0)
        m = _make_monitor(ts, expected_interval=15.0, stall_multiplier=100.0)
        cv = m.coefficient_of_variation()
        assert cv > 2.0, f"expected CV > 2.0, got {cv}"
        # silence_ratio should not trigger stalled (33.3 < 100)
        assert m.silence_ratio() < m.stall_multiplier
        assert m.rhythm_grade() == "stalled"

    def test_custom_stall_multiplier(self):
        ts = [0.0, 15.0, 30.0, 200.0, 215.0]
        m_strict = _make_monitor(ts, expected_interval=15.0, stall_multiplier=5.0)
        m_loose = _make_monitor(ts, expected_interval=15.0, stall_multiplier=100.0)
        # 170/15 = 11.3 → stalled with strict (5) but not loose (100)
        assert m_strict.rhythm_grade() == "stalled"
        assert m_loose.rhythm_grade() != "stalled"


# --- summary ---


class TestSummary:
    def test_summary_keys(self):
        m = _make_monitor(_perfect_cadence(10))
        s = m.summary()
        expected_keys = {
            "stroke_count", "expected_interval", "cv", "regularity",
            "bursts", "longest_silence", "silence_ratio", "grade",
        }
        assert set(s.keys()) == expected_keys

    def test_summary_empty(self):
        m = HeartbeatMonitor()
        s = m.summary()
        assert s["stroke_count"] == 0
        assert s["cv"] is None
        assert s["regularity"] is None
        assert s["grade"] is None


# --- regularity_report ---


class TestReport:
    def test_empty(self):
        m = HeartbeatMonitor()
        r = regularity_report(m)
        assert "not enough data" in r

    def test_one_stroke(self):
        m = HeartbeatMonitor()
        m.record_stroke(100.0)
        r = regularity_report(m)
        assert "not enough data" in r

    def test_healthy_report(self):
        m = _make_monitor(_perfect_cadence(50))
        r = regularity_report(m)
        assert "healthy" in r
        assert "1.00" in r  # perfect regularity

    def test_report_contains_metrics(self):
        m = _make_monitor(_perfect_cadence(20))
        r = regularity_report(m)
        assert "regularity" in r
        assert "cv" in r
        assert "strokes" in r
        assert "burst" in r
        assert "silence" in r

    def test_report_with_bursts(self):
        ts = [0.0, 2.0, 4.0, 100.0, 115.0, 130.0, 145.0]
        m = _make_monitor(ts, expected_interval=15.0)
        r = regularity_report(m)
        assert "1 burst" in r
