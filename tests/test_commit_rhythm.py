"""Tests for iamai.commit_rhythm — commit spacing pattern analysis."""

import pytest
from datetime import datetime, timedelta, timezone

from iamai.commit_rhythm import (
    analyze_rhythm,
    classify_pattern,
    interval_stats,
    rhythm_score,
)


TZ_CST = timezone(timedelta(hours=8))


def _ts_list(base: datetime, interval_s: float, count: int) -> list[datetime]:
    """Generate evenly spaced timestamps."""
    return [base + timedelta(seconds=interval_s * i) for i in range(count)]


def _base() -> datetime:
    return datetime(2026, 10, 24, 1, 0, 0, tzinfo=TZ_CST)


# ── rhythm_score ────────────────────────────────────────────────────────


class TestRhythmScore:
    def test_perfect_cadence(self):
        ivs = [600.0, 600.0, 600.0, 600.0]
        assert rhythm_score(ivs, target_interval_seconds=600) == 1.0

    def test_empty_intervals(self):
        assert rhythm_score([], target_interval_seconds=600) == 0.0

    def test_single_interval_on_target(self):
        assert rhythm_score([600.0], target_interval_seconds=600) == 1.0

    def test_single_interval_off_target(self):
        score = rhythm_score([300.0], target_interval_seconds=600)
        assert 0.0 < score < 1.0

    def test_wide_deviation_scores_zero(self):
        # Every interval is 2× target → deviation = 1.0 → score = 0.0
        ivs = [1200.0, 1200.0, 1200.0]
        assert rhythm_score(ivs, target_interval_seconds=600) == 0.0

    def test_moderate_deviation(self):
        # 10% off target → score ≈ 0.9
        ivs = [660.0, 660.0, 660.0]
        score = rhythm_score(ivs, target_interval_seconds=600)
        assert 0.85 < score < 0.95

    def test_mixed_over_and_under(self):
        # Some over, some under — average deviation matters
        ivs = [500.0, 700.0]  # both 100s off → avg deviation = 100/600 ≈ 0.167
        score = rhythm_score(ivs, target_interval_seconds=600)
        assert 0.8 < score < 0.85


# ── classify_pattern ────────────────────────────────────────────────────


class TestClassifyPattern:
    def test_steady(self):
        ivs = [600.0, 605.0, 595.0, 600.0, 602.0]
        assert classify_pattern(ivs, target_interval_seconds=600) == "steady"

    def test_empty_is_stalled(self):
        assert classify_pattern([], target_interval_seconds=600) == "stalled"

    def test_stalled_by_huge_gap(self):
        # One gap > 10× target (6000s)
        ivs = [600.0, 600.0, 7000.0, 600.0]
        assert classify_pattern(ivs, target_interval_seconds=600) == "stalled"

    def test_bursty_high_variance(self):
        # Very uneven intervals → high CV
        ivs = [60.0, 60.0, 60.0, 3000.0, 60.0, 60.0, 2500.0]
        assert classify_pattern(ivs, target_interval_seconds=600) == "bursty"

    def test_drifting_increasing(self):
        # Intervals slowly increasing → strong positive correlation
        ivs = [400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0]
        assert classify_pattern(ivs, target_interval_seconds=600) == "drifting"

    def test_drifting_decreasing(self):
        # Intervals slowly decreasing → strong negative correlation
        ivs = [1000.0, 900.0, 800.0, 700.0, 600.0, 500.0, 400.0]
        assert classify_pattern(ivs, target_interval_seconds=600) == "drifting"

    def test_stalled_takes_priority_over_bursty(self):
        # Both stalled and bursty conditions present → stalled wins
        ivs = [60.0, 60.0, 8000.0, 60.0, 60.0]
        assert classify_pattern(ivs, target_interval_seconds=600) == "stalled"


# ── interval_stats ──────────────────────────────────────────────────────


class TestIntervalStats:
    def test_basic_stats(self):
        ivs = [100.0, 200.0, 300.0]
        stats = interval_stats(ivs)
        assert stats["count"] == 3
        assert stats["mean"] == 200.0
        assert stats["median"] == 200.0
        assert stats["min"] == 100.0
        assert stats["max"] == 300.0
        assert stats["stdev"] == 100.0

    def test_single_value(self):
        stats = interval_stats([42.0])
        assert stats["count"] == 1
        assert stats["mean"] == 42.0
        assert stats["stdev"] == 0.0

    def test_empty(self):
        stats = interval_stats([])
        assert stats["count"] == 0
        assert stats["mean"] == 0.0

    def test_identical_values(self):
        ivs = [600.0, 600.0, 600.0]
        stats = interval_stats(ivs)
        assert stats["stdev"] == 0.0
        assert stats["min"] == stats["max"] == 600.0


# ── analyze_rhythm (integration) ────────────────────────────────────────


class TestAnalyzeRhythm:
    def test_perfect_steady_run(self):
        ts = _ts_list(_base(), 600, 10)
        result = analyze_rhythm(ts, target_interval_seconds=600)
        assert result["score"] == 1.0
        assert result["pattern"] == "steady"
        assert result["intervals"]["count"] == 9
        assert result["cv"] == 0.0
        assert abs(result["trend"]) < 0.01

    def test_stalled_detection(self):
        ts = _ts_list(_base(), 600, 5)
        # Insert a huge gap
        ts.append(ts[-1] + timedelta(seconds=8000))
        ts.append(ts[-1] + timedelta(seconds=600))
        result = analyze_rhythm(ts, target_interval_seconds=600)
        assert result["pattern"] == "stalled"
        assert result["score"] < 0.5

    def test_bursty_pattern(self):
        # Alternating short and long gaps
        base = _base()
        ts = [base]
        for _ in range(5):
            ts.append(ts[-1] + timedelta(seconds=60))   # burst
            ts.append(ts[-1] + timedelta(seconds=2000))  # silence
        result = analyze_rhythm(ts, target_interval_seconds=600)
        assert result["pattern"] in ("bursty", "stalled")
        assert result["cv"] > 0.5

    def test_drifting_cadence(self):
        base = _base()
        ts = [base]
        gap = 300.0
        for _ in range(10):
            gap += 50.0
            ts.append(ts[-1] + timedelta(seconds=gap))
        result = analyze_rhythm(ts, target_interval_seconds=600)
        assert result["trend"] > 0.5  # increasing intervals

    def test_unsorted_input(self):
        """Timestamps need not arrive sorted."""
        ts = _ts_list(_base(), 600, 5)
        ts_shuffled = [ts[2], ts[0], ts[4], ts[1], ts[3]]
        result = analyze_rhythm(ts_shuffled, target_interval_seconds=600)
        assert result["score"] == 1.0
        assert result["pattern"] == "steady"

    def test_single_timestamp(self):
        result = analyze_rhythm([_base()], target_interval_seconds=600)
        assert result["score"] == 0.0
        assert result["intervals"]["count"] == 0

    def test_empty_timestamps(self):
        result = analyze_rhythm([], target_interval_seconds=600)
        assert result["score"] == 0.0
        assert result["pattern"] == "stalled"

    def test_iso_string_input(self):
        ts = [
            "2026-10-24T01:00:00+08:00",
            "2026-10-24T01:10:00+08:00",
            "2026-10-24T01:20:00+08:00",
            "2026-10-24T01:30:00+08:00",
        ]
        result = analyze_rhythm(ts, target_interval_seconds=600)
        assert result["score"] == 1.0
        assert result["pattern"] == "steady"

    def test_custom_target_interval(self):
        ts = _ts_list(_base(), 300, 8)
        result = analyze_rhythm(ts, target_interval_seconds=300)
        assert result["score"] == 1.0
        assert result["pattern"] == "steady"

    def test_realistic_overnight_scenario(self):
        """Simulate overnight: steady → stall → recovery → steady."""
        base = _base()
        ts = _ts_list(base, 600, 20)           # 20 steady commits
        ts.append(ts[-1] + timedelta(seconds=7200))  # 2h stall
        ts.extend(_ts_list(ts[-1], 600, 10))   # recovery
        result = analyze_rhythm(ts, target_interval_seconds=600)
        assert result["pattern"] == "stalled"
        assert result["score"] < 0.8
        assert result["intervals"]["max"] == 7200.0

    def test_result_keys_complete(self):
        ts = _ts_list(_base(), 600, 5)
        result = analyze_rhythm(ts, target_interval_seconds=600)
        assert set(result.keys()) == {"score", "pattern", "intervals", "cv", "trend"}
        assert set(result["intervals"].keys()) == {
            "count", "mean", "median", "stdev", "min", "max"
        }
