"""Tests for iamai.commit_interval — commit regularity measurement.

30 tests covering:
  - interval computation (sorted, unsorted, edge cases)
  - mean and std_dev helpers
  - regularity score (perfect, good, bad, edge)
  - health labels (all four tiers + boundaries)
  - longest gap
  - burst detection (none, some, threshold tuning)
  - full interval_report integration
  - interval_summary formatting
"""

import pytest
from datetime import datetime, timedelta, timezone

from iamai.commit_interval import (
    compute_intervals,
    mean,
    std_dev,
    regularity_score,
    health_label,
    longest_gap,
    burst_count,
    interval_report,
    interval_summary,
)


# ── fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def perfect_clock():
    """Commits exactly every 600 seconds."""
    base = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
    return [base + timedelta(seconds=600 * i) for i in range(20)]


@pytest.fixture
def jittery_clock():
    """Commits roughly every 600s but with ±60s jitter."""
    import random
    random.seed(42)
    base = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
    offsets = [600 + random.randint(-60, 60) for _ in range(19)]
    ts = [base]
    for off in offsets:
        ts.append(ts[-1] + timedelta(seconds=off))
    return ts


@pytest.fixture
def burst_then_gap():
    """5 rapid commits, then a 2-hour gap, then 5 more rapid commits."""
    base = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
    rapid1 = [base + timedelta(seconds=10 * i) for i in range(5)]
    after_gap = rapid1[-1] + timedelta(hours=2)
    rapid2 = [after_gap + timedelta(seconds=10 * i) for i in range(5)]
    return rapid1 + rapid2


@pytest.fixture
def single_commit():
    return [datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)]


@pytest.fixture
def empty_list():
    return []


# ── compute_intervals ────────────────────────────────────────────

class TestComputeIntervals:
    def test_perfect_clock_gives_uniform_intervals(self, perfect_clock):
        ivs = compute_intervals(perfect_clock)
        assert len(ivs) == 19
        assert all(iv == 600.0 for iv in ivs)

    def test_unsorted_input_is_sorted(self):
        ts = [
            datetime(2026, 10, 18, 12, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 10, 18, 12, 20, 0, tzinfo=timezone.utc),
        ]
        ivs = compute_intervals(ts)
        assert ivs == [600.0, 600.0]

    def test_single_timestamp_returns_empty(self, single_commit):
        assert compute_intervals(single_commit) == []

    def test_empty_list_returns_empty(self, empty_list):
        assert compute_intervals(empty_list) == []

    def test_two_timestamps_one_interval(self):
        ts = [
            datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 10, 18, 12, 5, 0, tzinfo=timezone.utc),
        ]
        ivs = compute_intervals(ts)
        assert ivs == [300.0]

    def test_burst_then_gap_intervals(self, burst_then_gap):
        ivs = compute_intervals(burst_then_gap)
        assert len(ivs) == 9
        # first 4 intervals are 10s each (rapid)
        assert ivs[:4] == [10.0, 10.0, 10.0, 10.0]
        # fifth interval is the 2-hour gap
        assert ivs[4] == 7200.0
        # last 4 are 10s again
        assert ivs[5:] == [10.0, 10.0, 10.0, 10.0]


# ── mean and std_dev ─────────────────────────────────────────────

class TestStatsHelpers:
    def test_mean_of_uniform(self):
        assert mean([100, 100, 100]) == 100.0

    def test_mean_of_empty(self):
        assert mean([]) == 0.0

    def test_mean_of_varied(self):
        assert mean([10, 20, 30]) == pytest.approx(20.0)

    def test_std_dev_of_uniform_is_zero(self):
        assert std_dev([5, 5, 5, 5]) == 0.0

    def test_std_dev_of_empty(self):
        assert std_dev([]) == 0.0

    def test_std_dev_of_single(self):
        assert std_dev([42]) == 0.0

    def test_std_dev_known_value(self):
        # population std of [2, 4, 4, 4, 5, 5, 7, 9] = 2.0
        assert std_dev([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(2.0)


# ── regularity_score ─────────────────────────────────────────────

class TestRegularityScore:
    def test_perfect_regularity(self, perfect_clock):
        ivs = compute_intervals(perfect_clock)
        assert regularity_score(ivs) == pytest.approx(1.0)

    def test_jittery_is_high_but_not_perfect(self, jittery_clock):
        ivs = compute_intervals(jittery_clock)
        reg = regularity_score(ivs)
        assert 0.6 < reg < 1.0

    def test_burst_then_gap_is_low(self, burst_then_gap):
        ivs = compute_intervals(burst_then_gap)
        reg = regularity_score(ivs)
        assert reg < 0.35

    def test_empty_intervals_returns_zero(self):
        assert regularity_score([]) == 0.0

    def test_zero_mean_returns_zero(self):
        # all intervals are 0 (duplicate timestamps)
        assert regularity_score([0.0, 0.0, 0.0]) == 0.0


# ── health_label ──────────────────────────────────────────────────

class TestHealthLabel:
    def test_metronome(self):
        assert health_label(1.0) == "metronome"
        assert health_label(0.85) == "metronome"

    def test_steady(self):
        assert health_label(0.84) == "steady"
        assert health_label(0.60) == "steady"

    def test_irregular(self):
        assert health_label(0.59) == "irregular"
        assert health_label(0.35) == "irregular"

    def test_erratic(self):
        assert health_label(0.34) == "erratic"
        assert health_label(0.0) == "erratic"


# ── longest_gap ──────────────────────────────────────────────────

class TestLongestGap:
    def test_uniform(self, perfect_clock):
        ivs = compute_intervals(perfect_clock)
        assert longest_gap(ivs) == 600.0

    def test_burst_then_gap(self, burst_then_gap):
        ivs = compute_intervals(burst_then_gap)
        assert longest_gap(ivs) == 7200.0

    def test_empty(self):
        assert longest_gap([]) == 0.0


# ── burst_count ──────────────────────────────────────────────────

class TestBurstCount:
    def test_no_bursts_in_perfect_clock(self, perfect_clock):
        ivs = compute_intervals(perfect_clock)
        assert burst_count(ivs, threshold=30.0) == 0

    def test_all_bursts_in_rapid_fire(self, burst_then_gap):
        ivs = compute_intervals(burst_then_gap)
        # 4 rapid + 4 rapid = 8 burst pairs (10s each, < 30s threshold)
        assert burst_count(ivs, threshold=30.0) == 8

    def test_custom_threshold(self, perfect_clock):
        ivs = compute_intervals(perfect_clock)
        # threshold=601 makes every 600s interval a "burst"
        assert burst_count(ivs, threshold=601.0) == 19
        # threshold=599 makes none a burst
        assert burst_count(ivs, threshold=599.0) == 0

    def test_empty_intervals(self):
        assert burst_count([]) == 0


# ── interval_report (integration) ────────────────────────────────

class TestIntervalReport:
    def test_perfect_clock_report(self, perfect_clock):
        r = interval_report(perfect_clock)
        assert r["count"] == 20
        assert r["intervals"] == 19
        assert r["mean_interval"] == 600.0
        assert r["std_interval"] == 0.0
        assert r["cv"] == 0.0
        assert r["regularity"] == 1.0
        assert r["label"] == "metronome"
        assert r["longest_gap"] == 600.0
        assert r["bursts"] == 0

    def test_burst_then_gap_report(self, burst_then_gap):
        r = interval_report(burst_then_gap)
        assert r["count"] == 10
        assert r["label"] == "erratic"
        assert r["longest_gap"] == 7200.0
        assert r["bursts"] == 8

    def test_single_timestamp_report(self, single_commit):
        r = interval_report(single_commit)
        assert r["count"] == 1
        assert r["intervals"] == 0
        assert r["label"] == "erratic"

    def test_empty_report(self, empty_list):
        r = interval_report(empty_list)
        assert r["count"] == 0
        assert r["regularity"] == 0.0

    def test_custom_burst_threshold(self, burst_then_gap):
        r = interval_report(burst_then_gap, burst_threshold=15.0)
        # 10s intervals still count as bursts at 15s threshold
        assert r["bursts"] == 8

    def test_report_keys(self, perfect_clock):
        r = interval_report(perfect_clock)
        expected_keys = {
            "count", "intervals", "mean_interval", "std_interval",
            "cv", "regularity", "label", "longest_gap", "bursts",
        }
        assert set(r.keys()) == expected_keys


# ── interval_summary ─────────────────────────────────────────────

class TestIntervalSummary:
    def test_summary_contains_key_info(self, perfect_clock):
        r = interval_report(perfect_clock)
        s = interval_summary(r)
        assert "20 commits" in s
        assert "metronome" in s
        assert "600s" in s

    def test_summary_for_erratic(self, burst_then_gap):
        r = interval_report(burst_then_gap)
        s = interval_summary(r)
        assert "erratic" in s
        assert "7200s" in s
        assert "8 burst" in s

    def test_summary_for_empty(self, empty_list):
        r = interval_report(empty_list)
        s = interval_summary(r)
        assert "0 commits" in s
