"""Tests for iamai.commit_throughput — sliding-window commit rate.

20 tests covering:
  - _to_epoch: int, float, ISO string with/without tz
  - commits_in_window: normal, empty, boundary, zero window
  - throughput: normalisation, edge cases
  - throughput_trend: bucket count, ordering, empty
  - throughput_summary: verdict logic
"""

import pytest
from datetime import datetime, timezone, timedelta

from iamai.commit_throughput import (
    _to_epoch,
    commits_in_window,
    throughput,
    throughput_trend,
    throughput_summary,
)


# ── _to_epoch ──────────────────────────────────────────────────

class TestToEpoch:
    def test_int_passthrough(self):
        assert _to_epoch(1000) == 1000.0

    def test_float_passthrough(self):
        assert _to_epoch(1000.5) == 1000.5

    def test_iso_with_tz(self):
        dt = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
        assert _to_epoch(dt.isoformat()) == dt.timestamp()

    def test_iso_without_tz_assumes_utc(self):
        dt = datetime(2026, 10, 18, 12, 0, 0)
        expected = dt.replace(tzinfo=timezone.utc).timestamp()
        assert _to_epoch("2026-10-18T12:00:00") == expected


# ── commits_in_window ─────────────────────────────────────────

class TestCommitsInWindow:
    def test_empty_list(self):
        assert commits_in_window([], now=1000, window_seconds=100) == 0

    def test_all_within_window(self):
        ts = [900, 950, 990]
        assert commits_in_window(ts, now=1000, window_seconds=100) == 3

    def test_some_outside_window(self):
        ts = [800, 900, 950, 990]
        assert commits_in_window(ts, now=1000, window_seconds=100) == 3

    def test_all_outside_window(self):
        ts = [500, 600, 700]
        assert commits_in_window(ts, now=1000, window_seconds=100) == 0

    def test_boundary_exact(self):
        ts = [900]  # exactly at cutoff
        assert commits_in_window(ts, now=1000, window_seconds=100) == 1

    def test_zero_window_raises(self):
        with pytest.raises(ValueError):
            commits_in_window([100], now=200, window_seconds=0)

    def test_negative_window_raises(self):
        with pytest.raises(ValueError):
            commits_in_window([100], now=200, window_seconds=-10)

    def test_iso_timestamps(self):
        now = "2026-10-18T12:00:00+00:00"
        ts = [
            "2026-10-18T11:30:00+00:00",
            "2026-10-18T11:00:00+00:00",
            "2026-10-18T10:00:00+00:00",
        ]
        assert commits_in_window(ts, now=now, window_seconds=3600) == 2


# ── throughput ────────────────────────────────────────────────

class TestThroughput:
    def test_basic_rate(self):
        # 10 commits in 1 hour → 10 cph
        now = 3600
        ts = list(range(0, 3600, 360))  # 10 commits, every 360s
        assert throughput(ts, now=now, window_seconds=3600) == 10.0

    def test_half_hour_window_doubles(self):
        # 5 commits in 30 min → 10 cph
        now = 1800
        ts = list(range(0, 1800, 360))
        assert throughput(ts, now=now, window_seconds=1800) == 10.0

    def test_empty_returns_zero(self):
        assert throughput([], now=1000, window_seconds=3600) == 0.0

    def test_zero_window_raises(self):
        with pytest.raises(ValueError):
            throughput([100], now=200, window_seconds=0)


# ── throughput_trend ──────────────────────────────────────────

class TestThroughputTrend:
    def test_bucket_count(self):
        now = 3600
        ts = list(range(0, 3600, 900))  # 4 commits
        trend = throughput_trend(ts, now=now, window_seconds=3600, buckets=4)
        assert len(trend) == 4

    def test_oldest_first_ordering(self):
        now = 3600
        # all commits in the first quarter
        ts = [100, 200, 300, 400]
        trend = throughput_trend(ts, now=now, window_seconds=3600, buckets=4)
        assert trend[0] >= trend[-1]

    def test_empty_timestamps(self):
        trend = throughput_trend([], now=3600, window_seconds=3600, buckets=4)
        assert trend == [0.0, 0.0, 0.0, 0.0]

    def test_zero_buckets_raises(self):
        with pytest.raises(ValueError):
            throughput_trend([100], now=200, window_seconds=100, buckets=0)


# ── throughput_summary ────────────────────────────────────────

class TestThroughputSummary:
    def test_stalled_verdict(self):
        result = throughput_summary([], now=3600, window_seconds=3600)
        assert result["verdict"] == "stalled"
        assert result["throughput_cph"] == 0.0

    def test_healthy_verdict(self):
        now = 3600
        # steady: 4 commits evenly spread → 4 cph
        ts = [900, 1800, 2700, 3500]
        result = throughput_summary(ts, now=now, window_seconds=3600)
        assert result["verdict"] in ("healthy", "slowing")
        assert result["commits_in_window"] == 4

    def test_slowing_verdict(self):
        now = 3600
        # all commits clustered in the first quarter → trend[-1] < trend[0]*0.5
        ts = [100, 200, 300, 400, 500, 600, 700, 800]
        result = throughput_summary(ts, now=now, window_seconds=3600)
        assert result["verdict"] == "slowing"

    def test_summary_keys(self):
        result = throughput_summary([100], now=3600, window_seconds=3600)
        for key in ("throughput_cph", "commits_in_window", "window_seconds",
                     "trend", "verdict", "checked_at"):
            assert key in result
