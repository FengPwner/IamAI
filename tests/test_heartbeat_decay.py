"""Tests for iamai.heartbeat_decay — writer heartbeat health monitoring."""

import pytest

from iamai.heartbeat_decay import (
    HeartbeatMonitor,
    acceleration,
    decay_score,
    intervals,
    max_gap_ratio,
    mean_interval,
    verdict,
)


# ---------------------------------------------------------------------------
# intervals
# ---------------------------------------------------------------------------


class TestIntervals:
    def test_empty(self):
        assert intervals([]) == []

    def test_single_timestamp(self):
        assert intervals([1000.0]) == []

    def test_two_timestamps(self):
        assert intervals([1000.0, 1200.0]) == [200.0]

    def test_multiple_even_spaced(self):
        ts = [0.0, 200.0, 400.0, 600.0]
        assert intervals(ts) == [200.0, 200.0, 200.0]

    def test_multiple_uneven(self):
        ts = [0.0, 100.0, 400.0]
        assert intervals(ts) == [100.0, 300.0]

    def test_unsorted_input(self):
        ts = [600.0, 200.0, 0.0, 400.0]
        assert intervals(ts) == [200.0, 200.0, 200.0]

    def test_iso_strings(self):
        ts = [
            "2026-10-20T00:00:00+08:00",
            "2026-10-20T00:05:00+08:00",
            "2026-10-20T00:10:00+08:00",
        ]
        ivs = intervals(ts)
        assert len(ivs) == 2
        assert abs(ivs[0] - 300.0) < 0.01
        assert abs(ivs[1] - 300.0) < 0.01


# ---------------------------------------------------------------------------
# mean_interval
# ---------------------------------------------------------------------------


class TestMeanInterval:
    def test_empty(self):
        assert mean_interval([]) == 0.0

    def test_single(self):
        assert mean_interval([100.0]) == 0.0

    def test_even_spaced(self):
        ts = [0.0, 200.0, 400.0, 600.0]
        assert mean_interval(ts) == 200.0

    def test_window_limits(self):
        # 5 intervals: 100, 200, 300, 400, 500 — window=2 → last 2: (400+500)/2
        ts = [0.0, 100.0, 300.0, 600.0, 1000.0, 1500.0]
        result = mean_interval(ts, window=2)
        assert abs(result - 450.0) < 0.01

    def test_window_larger_than_data(self):
        ts = [0.0, 200.0, 400.0]
        assert mean_interval(ts, window=100) == 200.0


# ---------------------------------------------------------------------------
# decay_score
# ---------------------------------------------------------------------------


class TestDecayScore:
    def test_empty(self):
        assert decay_score([], baseline=200.0) == 0.0

    def test_single(self):
        assert decay_score([100.0], baseline=200.0) == 0.0

    def test_perfect_pace(self):
        ts = [0.0, 200.0, 400.0, 600.0, 800.0]
        score = decay_score(ts, baseline=200.0, window=10)
        assert abs(score - 1.0) < 0.01

    def test_slowing_down(self):
        # Intervals: 200, 200, 300, 400 — recent mean ≈ 300
        ts = [0.0, 200.0, 400.0, 700.0, 1100.0]
        score = decay_score(ts, baseline=200.0, window=10)
        assert score > 1.0

    def test_speeding_up(self):
        # Intervals: 400, 300, 200, 100 — recent mean ≈ 250
        ts = [0.0, 400.0, 700.0, 900.0, 1000.0]
        score = decay_score(ts, baseline=200.0, window=10)
        # mean interval is 250, baseline 200 → score 1.25
        assert score > 1.0

    def test_zero_baseline(self):
        assert decay_score([0.0, 100.0], baseline=0.0) == 0.0

    def test_negative_baseline(self):
        assert decay_score([0.0, 100.0], baseline=-1.0) == 0.0


# ---------------------------------------------------------------------------
# acceleration
# ---------------------------------------------------------------------------


class TestAcceleration:
    def test_insufficient_data(self):
        assert acceleration([0.0, 100.0], window=12) is None

    def test_steady_pace(self):
        # 25 intervals all = 200s → acceleration ≈ 0
        ts = [i * 200.0 for i in range(26)]
        accel = acceleration(ts, window=12)
        assert accel is not None
        assert abs(accel) < 0.01

    def test_decelerating(self):
        # First half intervals ~100, second half ~300
        ts = [0.0]
        for _ in range(12):
            ts.append(ts[-1] + 100.0)
        for _ in range(12):
            ts.append(ts[-1] + 300.0)
        accel = acceleration(ts, window=12)
        assert accel is not None
        assert accel > 0  # positive = decelerating

    def test_recovering(self):
        # First half intervals ~300, second half ~100
        ts = [0.0]
        for _ in range(12):
            ts.append(ts[-1] + 300.0)
        for _ in range(12):
            ts.append(ts[-1] + 100.0)
        accel = acceleration(ts, window=12)
        assert accel is not None
        assert accel < 0  # negative = recovering


# ---------------------------------------------------------------------------
# max_gap_ratio
# ---------------------------------------------------------------------------


class TestMaxGapRatio:
    def test_empty(self):
        assert max_gap_ratio([], baseline=200.0) == 0.0

    def test_single(self):
        assert max_gap_ratio([100.0], baseline=200.0) == 0.0

    def test_perfect(self):
        ts = [0.0, 200.0, 400.0, 600.0]
        assert max_gap_ratio(ts, baseline=200.0) == 1.0

    def test_one_spike(self):
        ts = [0.0, 200.0, 400.0, 1400.0]
        # max gap = 1000, baseline = 200 → ratio = 5.0
        assert max_gap_ratio(ts, baseline=200.0) == 5.0

    def test_zero_baseline(self):
        assert max_gap_ratio([0.0, 100.0], baseline=0.0) == 0.0

    def test_window_limits(self):
        # 4 intervals: 1000, 200, 200, 200 — window=3 → only last 3: max=200
        ts = [0.0, 1000.0, 1200.0, 1400.0, 1600.0]
        assert max_gap_ratio(ts, baseline=200.0, window=3) == 1.0


# ---------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------


class TestVerdict:
    def test_steady_low(self):
        assert verdict(0.5) == "steady"

    def test_steady_one(self):
        assert verdict(1.0) == "steady"

    def test_steady_boundary(self):
        assert verdict(1.14) == "steady"

    def test_drifting(self):
        assert verdict(1.15) == "drifting"

    def test_drifting_mid(self):
        assert verdict(1.3) == "drifting"

    def test_slowing(self):
        assert verdict(1.4) == "slowing"

    def test_slowing_mid(self):
        assert verdict(1.7) == "slowing"

    def test_stalling(self):
        assert verdict(2.0) == "stalling"

    def test_stalling_high(self):
        assert verdict(5.0) == "stalling"


# ---------------------------------------------------------------------------
# HeartbeatMonitor
# ---------------------------------------------------------------------------


class TestHeartbeatMonitor:
    def test_healthy_run(self):
        monitor = HeartbeatMonitor(baseline_interval=200.0, window=5)
        # 10 evenly spaced timestamps
        ts = [i * 200.0 for i in range(10)]
        report = monitor.analyse(ts)
        assert report["verdict"] == "steady"
        assert abs(report["decay_score"] - 1.0) < 0.01
        assert report["sample_count"] == 10
        assert report["baseline"] == 200.0

    def test_stalling_run(self):
        monitor = HeartbeatMonitor(baseline_interval=200.0, window=5)
        # Intervals grow: 200, 200, 500, 800, 1200, 1500, ...
        ts = [0.0, 200.0, 400.0, 900.0, 1700.0, 2900.0, 4400.0]
        report = monitor.analyse(ts)
        assert report["decay_score"] > 2.0
        assert report["verdict"] == "stalling"

    def test_empty_input(self):
        monitor = HeartbeatMonitor(baseline_interval=200.0)
        report = monitor.analyse([])
        assert report["decay_score"] == 0.0
        assert report["sample_count"] == 0
        assert report["acceleration"] is None

    def test_report_keys(self):
        monitor = HeartbeatMonitor()
        ts = [i * 100.0 for i in range(30)]
        report = monitor.analyse(ts)
        expected_keys = {
            "decay_score",
            "acceleration",
            "max_gap_ratio",
            "verdict",
            "mean_interval",
            "sample_count",
            "baseline",
        }
        assert set(report.keys()) == expected_keys

    def test_iso_string_timestamps(self):
        monitor = HeartbeatMonitor(baseline_interval=300.0, window=3)
        ts = [
            "2026-10-20T00:00:00+08:00",
            "2026-10-20T00:05:00+08:00",
            "2026-10-20T00:10:00+08:00",
            "2026-10-20T00:15:00+08:00",
        ]
        report = monitor.analyse(ts)
        assert report["verdict"] == "steady"
        assert abs(report["mean_interval"] - 300.0) < 0.01
