#!/usr/bin/env python3
"""Tests for writer_resilience_score module."""

import pytest
import sys
import os
import json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_resilience_score import (
    ResilienceResult,
    measure_resilience,
    _parse_timestamps,
    _compute_intervals,
    _recovery_speed_score,
    _consistency_score,
    _streak_durability_score,
    _bounce_back_score,
    _burnout_resistance_score,
    _classify,
    DEFAULT_CADENCE,
    DEFAULT_WEIGHTS,
)


# ── helpers ─────────────────────────────────────────────────────


def _make_strokes(count: int, start: float = 1000.0, interval: float = 900.0, jitter: float = 0.0) -> list[dict]:
    """Generate synthetic stroke records with optional jitter."""
    import random
    strokes = []
    t = start
    for i in range(count):
        jitter_val = random.uniform(-jitter, jitter) if jitter > 0 else 0.0
        strokes.append({"at": t, "seq": i, "kind": "thought"})
        t += interval + jitter_val
    return strokes


def _make_iso_strokes(count: int, interval_minutes: int = 15) -> list[dict]:
    """Generate stroke records with ISO 8601 timestamps."""
    base = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
    strokes = []
    for i in range(count):
        ts = base + timedelta(minutes=interval_minutes * i)
        strokes.append({"at": ts.isoformat(), "seq": i, "kind": "note"})
    return strokes


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_list(self):
        r = measure_resilience([])
        assert r.resilience_index == 0.0
        assert r.classification == "fragile"
        assert r.sample_count == 0

    def test_single_stroke(self):
        r = measure_resilience([{"at": 1000.0}])
        assert r.resilience_index == 0.0
        assert r.classification == "fragile"

    def test_two_strokes(self):
        r = measure_resilience([{"at": 1000.0}, {"at": 1900.0}])
        assert r.resilience_index == 0.0
        assert r.sample_count == 2

    def test_no_timestamp_key(self):
        r = measure_resilience([{"seq": 1}, {"seq": 2}])
        assert r.sample_count == 0
        assert r.classification == "fragile"

    def test_garbage_timestamps(self):
        r = measure_resilience([{"at": "not-a-date"}, {"at": None}])
        assert r.sample_count == 0


# ── timestamp parsing ───────────────────────────────────────────


class TestTimestampParsing:
    def test_numeric_timestamps(self):
        ts = _parse_timestamps([1000.0, 2000.0, 1500.0])
        assert ts == [1000.0, 1500.0, 2000.0]

    def test_iso_strings(self):
        ts = _parse_timestamps([
            "2026-11-01T12:00:00+00:00",
            "2026-11-01T12:15:00+00:00",
        ])
        assert len(ts) == 2
        assert ts[1] - ts[0] == 900.0

    def test_iso_with_z_suffix(self):
        ts = _parse_timestamps(["2026-11-01T12:00:00Z"])
        assert len(ts) == 1

    def test_dict_with_at_key(self):
        ts = _parse_timestamps([{"at": 1000.0}, {"at": 2000.0}])
        assert ts == [1000.0, 2000.0]

    def test_dict_with_at_ts_key(self):
        ts = _parse_timestamps([{"at_ts": 1000.0}, {"at_ts": 2000.0}])
        assert ts == [1000.0, 2000.0]

    def test_dict_with_timestamp_key(self):
        ts = _parse_timestamps([{"timestamp": 1000.0}])
        assert ts == [1000.0]

    def test_mixed_formats(self):
        ts = _parse_timestamps([
            {"at": 1000.0},
            "2026-11-01T12:00:00+00:00",
        ])
        assert len(ts) == 2

    def test_unsorted_input(self):
        ts = _parse_timestamps([{"at": 3000.0}, {"at": 1000.0}, {"at": 2000.0}])
        assert ts == [1000.0, 2000.0, 3000.0]

    def test_invalid_string_skipped(self):
        ts = _parse_timestamps([{"at": "garbage"}, {"at": 1000.0}])
        assert ts == [1000.0]


# ── interval computation ───────────────────────────────────────


class TestIntervals:
    def test_basic_intervals(self):
        iv = _compute_intervals([1000.0, 1900.0, 2800.0])
        assert iv == [900.0, 900.0]

    def test_filters_absurd_gaps(self):
        iv = _compute_intervals([1000.0, 2000.0, 100000.0])
        assert len(iv) == 1
        assert iv[0] == 1000.0

    def test_single_timestamp(self):
        iv = _compute_intervals([1000.0])
        assert iv == []

    def test_zero_gaps_filtered(self):
        iv = _compute_intervals([1000.0, 1000.0, 2000.0])
        assert iv == [1000.0]

    def test_negative_gaps_filtered(self):
        iv = _compute_intervals([1000.0, 500.0, 2000.0])
        # After sorting in _parse_timestamps this wouldn't happen,
        # but _compute_intervals itself filters negatives
        assert len(iv) == 1


# ── perfect cadence (ideal resilience) ─────────────────────────


class TestPerfectCadence:
    def test_perfect_15min_cadence_50_strokes(self):
        strokes = _make_strokes(50, interval=900.0)
        r = measure_resilience(strokes)
        assert r.resilience_index >= 0.85
        assert r.classification in ("robust", "antifragile")

    def test_perfect_15min_cadence_200_strokes(self):
        strokes = _make_strokes(200, interval=900.0)
        r = measure_resilience(strokes)
        assert r.classification == "antifragile"
        assert r.consistency >= 0.9
        assert r.total_gaps == 0

    def test_perfect_iso_strokes(self):
        strokes = _make_iso_strokes(100, interval_minutes=15)
        r = measure_resilience(strokes)
        assert r.resilience_index >= 0.80
        assert r.total_gaps == 0


# ── recovery speed ──────────────────────────────────────────────


class TestRecoverySpeed:
    def test_fast_recovery(self):
        # Gap of 2500s followed by quick 900s intervals
        intervals = [900.0, 900.0, 2500.0, 900.0, 900.0, 900.0]
        score, gaps, recovered, mean_gap = _recovery_speed_score(
            intervals, 900.0, 2.0
        )
        assert gaps == 1
        # recovery takes the gap itself + the next normal interval
        assert score >= 0.3

    def test_slow_recovery(self):
        # Long gaps followed by more long gaps
        intervals = [900.0, 5000.0, 4000.0, 3000.0, 900.0]
        score, gaps, recovered, mean_gap = _recovery_speed_score(
            intervals, 900.0, 2.0
        )
        assert gaps >= 1
        assert score < 0.5

    def test_no_gaps_perfect_recovery(self):
        intervals = [900.0] * 20
        score, gaps, recovered, mean_gap = _recovery_speed_score(
            intervals, 900.0, 2.0
        )
        assert score == 1.0
        assert gaps == 0

    def test_empty_intervals(self):
        score, gaps, recovered, mean_gap = _recovery_speed_score([], 900.0, 2.0)
        assert score == 0.0
        assert gaps == 0


# ── consistency ─────────────────────────────────────────────────


class TestConsistency:
    def test_perfect_consistency(self):
        intervals = [900.0] * 50
        score, mean_iv, cv = _consistency_score(intervals, 900.0)
        assert score == 1.0
        assert cv == 0.0
        assert mean_iv == 900.0

    def test_high_variance(self):
        intervals = [100.0, 5000.0, 200.0, 8000.0, 50.0, 3000.0]
        score, mean_iv, cv = _consistency_score(intervals, 900.0)
        assert score < 0.5
        assert cv > 1.0

    def test_moderate_jitter(self):
        intervals = [850.0, 950.0, 880.0, 920.0, 870.0, 930.0]
        score, mean_iv, cv = _consistency_score(intervals, 900.0)
        assert score >= 0.7
        assert cv < 0.1

    def test_wrong_cadence_penalty(self):
        # Consistent but at 3000s instead of 900s
        intervals = [3000.0] * 30
        score, mean_iv, cv = _consistency_score(intervals, 900.0)
        assert score < 1.0  # penalty for wrong rate

    def test_empty_intervals(self):
        score, mean_iv, cv = _consistency_score([], 900.0)
        assert score == 0.0

    def test_single_interval(self):
        score, mean_iv, cv = _consistency_score([900.0], 900.0)
        assert score == 0.0  # need at least 2


# ── streak durability ──────────────────────────────────────────


class TestStreakDurability:
    def test_one_long_streak(self):
        intervals = [900.0] * 100
        total_time = 100 * 900.0
        score, longest = _streak_durability_score(intervals, 900.0, 2.0, total_time)
        assert score >= 0.8
        assert longest == 100

    def test_broken_streaks(self):
        intervals = [900.0] * 10 + [5000.0] + [900.0] * 10 + [5000.0] + [900.0] * 10
        total_time = sum(intervals)
        score, longest = _streak_durability_score(intervals, 900.0, 2.0, total_time)
        assert longest == 10

    def test_no_streaks(self):
        intervals = [5000.0] * 20
        total_time = sum(intervals)
        score, longest = _streak_durability_score(intervals, 900.0, 2.0, total_time)
        assert score == 0.0
        assert longest == 0

    def test_empty(self):
        score, longest = _streak_durability_score([], 900.0, 2.0, 0.0)
        assert score == 0.0
        assert longest == 0


# ── bounce-back rate ───────────────────────────────────────────


class TestBounceBack:
    def test_perfect_bounce(self):
        score = _bounce_back_score([], 900.0, 2.0, 5, 5)
        assert score == 1.0

    def test_no_gaps_perfect(self):
        score = _bounce_back_score([], 900.0, 2.0, 0, 0)
        assert score == 1.0

    def test_partial_recovery(self):
        score = _bounce_back_score([], 900.0, 2.0, 10, 5)
        assert 0.3 <= score <= 0.6  # 50% recovery rate

    def test_poor_recovery(self):
        score = _bounce_back_score([], 900.0, 2.0, 10, 1)
        assert score <= 0.2

    def test_mostly_recovered(self):
        score = _bounce_back_score([], 900.0, 2.0, 10, 9)
        assert score >= 0.8


# ── burnout resistance ─────────────────────────────────────────


class TestBurnoutResistance:
    def test_healthy_pace(self):
        intervals = [900.0] * 50
        score, declining = _burnout_resistance_score(intervals, 900.0)
        assert score == 1.0
        assert declining == 0

    def test_declining_output(self):
        # Intervals getting longer over time (slowing down)
        intervals = [900.0] * 10 + [1500.0] * 10 + [2500.0] * 10 + [4000.0] * 10
        score, declining = _burnout_resistance_score(intervals, 900.0)
        assert declining > 0
        assert score < 1.0

    def test_too_few_intervals(self):
        score, declining = _burnout_resistance_score([900.0] * 5, 900.0)
        assert score == 1.0  # not enough data
        assert declining == 0

    def test_all_slow(self):
        intervals = [5000.0] * 30
        score, declining = _burnout_resistance_score(intervals, 900.0)
        assert score == 0.0
        assert declining > 0


# ── classification ──────────────────────────────────────────────


class TestClassification:
    def test_fragile(self):
        assert _classify(0.0) == "fragile"
        assert _classify(0.10) == "fragile"
        assert _classify(0.19) == "fragile"

    def test_recovering(self):
        assert _classify(0.20) == "recovering"
        assert _classify(0.30) == "recovering"
        assert _classify(0.39) == "recovering"

    def test_stable(self):
        assert _classify(0.40) == "stable"
        assert _classify(0.55) == "stable"
        assert _classify(0.64) == "stable"

    def test_robust(self):
        assert _classify(0.65) == "robust"
        assert _classify(0.75) == "robust"
        assert _classify(0.84) == "robust"

    def test_antifragile(self):
        assert _classify(0.85) == "antifragile"
        assert _classify(0.95) == "antifragile"
        assert _classify(1.0) == "antifragile"


# ── composite integration ───────────────────────────────────────


class TestCompositeIntegration:
    def test_all_dimensions_weighted(self):
        strokes = _make_strokes(100, interval=900.0)
        r = measure_resilience(strokes)
        expected = (
            r.recovery_speed * DEFAULT_WEIGHTS["recovery_speed"]
            + r.consistency * DEFAULT_WEIGHTS["consistency"]
            + r.streak_durability * DEFAULT_WEIGHTS["streak_durability"]
            + r.bounce_back_rate * DEFAULT_WEIGHTS["bounce_back_rate"]
            + r.burnout_resistance * DEFAULT_WEIGHTS["burnout_resistance"]
        )
        assert abs(r.resilience_index - expected) < 0.01

    def test_custom_weights(self):
        strokes = _make_strokes(50, interval=900.0)
        weights = {
            "recovery_speed": 0.50,
            "consistency": 0.50,
            "streak_durability": 0.0,
            "bounce_back_rate": 0.0,
            "burnout_resistance": 0.0,
        }
        r = measure_resilience(strokes, weights=weights)
        expected = (
            r.recovery_speed * 0.50 + r.consistency * 0.50
        )
        assert abs(r.resilience_index - expected) < 0.01

    def test_index_clamped_zero_to_one(self):
        # Even with extreme inputs, index stays in [0, 1]
        strokes = _make_strokes(500, interval=100.0)
        r = measure_resilience(strokes, cadence=900.0)
        assert 0.0 <= r.resilience_index <= 1.0


# ── realistic scenarios ─────────────────────────────────────────


class TestRealisticScenarios:
    def test_writer_with_occasional_pauses(self):
        """Writer mostly on cadence but takes a few breaks."""
        strokes = []
        t = 1000.0
        for i in range(80):
            strokes.append({"at": t})
            if i % 20 == 19:
                t += 3000.0  # occasional longer gap
            else:
                t += 900.0
        r = measure_resilience(strokes)
        assert r.classification in ("stable", "robust")
        assert r.total_gaps > 0

    def test_writer_with_overnight_gap(self):
        """Writer active during day, silent overnight."""
        base = 1000.0
        strokes = []
        for day in range(5):
            day_start = base + day * 86400
            for i in range(48):  # 48 strokes per day at 15min
                strokes.append({"at": day_start + i * 900.0})
        r = measure_resilience(strokes)
        assert r.total_gaps >= 4  # overnight gaps
        assert r.sample_count == 240

    def test_writer_burnout_pattern(self):
        """Writer gradually slowing down."""
        strokes = []
        t = 1000.0
        for i in range(100):
            strokes.append({"at": t})
            # Intervals increase linearly (slowing down)
            t += 900.0 + i * 50.0
        r = measure_resilience(strokes)
        assert r.burnout_resistance < 1.0
        assert r.declining_windows > 0

    def test_writer_fragile_bursts(self):
        """Writer produces in short bursts with long gaps."""
        strokes = []
        t = 1000.0
        for burst in range(10):
            for i in range(5):
                strokes.append({"at": t})
                t += 900.0
            t += 15000.0  # long gap between bursts
        r = measure_resilience(strokes)
        assert r.total_gaps >= 9
        assert r.resilience_index < 0.5


# ── result serialization ───────────────────────────────────────


class TestSerialization:
    def test_to_dict(self):
        strokes = _make_strokes(30, interval=900.0)
        r = measure_resilience(strokes)
        d = r.to_dict()
        assert isinstance(d, dict)
        assert "resilience_index" in d
        assert "classification" in d
        assert "recovery_speed" in d
        assert "consistency" in d
        assert "sample_count" in d

    def test_to_json(self):
        strokes = _make_strokes(30, interval=900.0)
        r = measure_resilience(strokes)
        j = r.to_json()
        parsed = json.loads(j)
        assert parsed["classification"] == r.classification
        assert parsed["sample_count"] == r.sample_count

    def test_json_roundtrip(self):
        strokes = _make_strokes(50, interval=900.0)
        r = measure_resilience(strokes)
        j = r.to_json()
        parsed = json.loads(j)
        assert parsed["resilience_index"] == r.resilience_index


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_all_same_timestamp(self):
        strokes = [{"at": 1000.0}] * 10
        r = measure_resilience(strokes)
        assert r.sample_count == 10
        # Same timestamps → zero intervals → low consistency/streak
        # but recovery and bounce default to 1.0 (nothing to recover from)
        assert r.resilience_index < 0.5

    def test_very_large_cadence(self):
        strokes = _make_strokes(30, interval=900.0)
        r = measure_resilience(strokes, cadence=86400.0)
        # Everything is a gap relative to 1-day cadence
        assert r.sample_count == 30

    def test_very_small_cadence(self):
        strokes = _make_strokes(30, interval=900.0)
        r = measure_resilience(strokes, cadence=1.0)
        # Everything is a gap relative to 1-second cadence
        assert r.sample_count == 30

    def test_duplicate_timestamps(self):
        strokes = [{"at": 1000.0}, {"at": 1000.0}, {"at": 2000.0}, {"at": 2000.0}]
        r = measure_resilience(strokes)
        assert r.sample_count == 4

    def test_integer_timestamps(self):
        strokes = [1000, 2000, 3000, 4000, 5000]
        r = measure_resilience(strokes)
        assert r.sample_count == 5

    def test_result_fields_complete(self):
        strokes = _make_strokes(50, interval=900.0)
        r = measure_resilience(strokes)
        expected_fields = [
            "resilience_index", "classification", "recovery_speed",
            "consistency", "streak_durability", "bounce_back_rate",
            "burnout_resistance", "longest_streak_intervals",
            "total_gaps", "recovered_gaps", "declining_windows",
            "sample_count", "mean_gap_duration", "mean_interval",
            "interval_cv",
        ]
        for field in expected_fields:
            assert hasattr(r, field), f"Missing field: {field}"


# ── weight validation ───────────────────────────────────────────


class TestWeights:
    def test_default_weights_sum_to_one(self):
        total = sum(DEFAULT_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_partial_weights_merged(self):
        strokes = _make_strokes(30, interval=900.0)
        # Only override one weight; others stay default
        r = measure_resilience(strokes, weights={"recovery_speed": 0.10})
        assert r.resilience_index >= 0.0

    def test_zero_all_weights(self):
        strokes = _make_strokes(30, interval=900.0)
        weights = {k: 0.0 for k in DEFAULT_WEIGHTS}
        r = measure_resilience(strokes, weights=weights)
        assert r.resilience_index == 0.0


# ── boundary conditions ─────────────────────────────────────────


class TestBoundaryConditions:
    def test_exact_cadence_threshold(self):
        """Intervals exactly at cadence × multiplier boundary."""
        threshold = 900.0 * 2.0  # 1800.0
        intervals = [900.0, 1800.0, 900.0, 1800.0, 900.0]
        score, gaps, recovered, mean_gap = _recovery_speed_score(
            intervals, 900.0, 2.0
        )
        # 1800.0 is not > 1800.0, so no gaps
        assert gaps == 0

    def test_one_over_threshold(self):
        threshold = 900.0 * 2.0
        intervals = [900.0, 1800.1, 900.0]
        score, gaps, recovered, mean_gap = _recovery_speed_score(
            intervals, 900.0, 2.0
        )
        assert gaps == 1

    def test_resilience_index_never_negative(self):
        """Extreme weights shouldn't produce negative index."""
        strokes = _make_strokes(20, interval=10000.0)
        weights = {k: 0.0 for k in DEFAULT_WEIGHTS}
        r = measure_resilience(strokes, weights=weights)
        assert r.resilience_index >= 0.0

    def test_resilience_index_never_over_one(self):
        strokes = _make_strokes(500, interval=900.0)
        weights = {k: 2.0 for k in DEFAULT_WEIGHTS}
        r = measure_resilience(strokes, weights=weights)
        assert r.resilience_index <= 1.0

    def test_very_long_history(self):
        """1000 strokes should not cause performance issues."""
        strokes = _make_strokes(1000, interval=900.0)
        r = measure_resilience(strokes)
        assert r.sample_count == 1000
        assert r.resilience_index >= 0.0

    def test_streak_bonus_capped(self):
        """Streak bonus shouldn't push dimension score above 1.0."""
        intervals = [900.0] * 200
        total_time = 200 * 900.0
        score, longest = _streak_durability_score(intervals, 900.0, 2.0, total_time)
        assert score <= 1.0
        assert longest == 200
