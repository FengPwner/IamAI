#!/usr/bin/env python3
"""Tests for cadence_drift — 38 test cases."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.cadence_drift import (  # noqa: E402
    DriftReport,
    classify_drift,
    compute_drift,
    compute_stability,
    count_jitter,
    detect_trend,
    extract_intervals_from_strokes,
    load_intervals_from_jsonl,
    load_intervals_from_state,
)


# ---------------------------------------------------------------------------
# classify_drift
# ---------------------------------------------------------------------------

class TestClassifyDrift(unittest.TestCase):
    """Drift classification boundaries."""

    def test_zero_drift_is_tight(self):
        self.assertEqual(classify_drift(0.0), "tight")

    def test_small_positive_drift(self):
        self.assertEqual(classify_drift(3.5), "tight")

    def test_small_negative_drift(self):
        self.assertEqual(classify_drift(-4.9), "tight")

    def test_exactly_five_pct(self):
        self.assertEqual(classify_drift(5.0), "warm")

    def test_warm_range(self):
        self.assertEqual(classify_drift(12.0), "warm")
        self.assertEqual(classify_drift(-19.9), "warm")

    def test_exactly_twenty_pct(self):
        self.assertEqual(classify_drift(20.0), "hot")

    def test_hot_range(self):
        self.assertEqual(classify_drift(50.0), "hot")
        self.assertEqual(classify_drift(-25.0), "hot")

    def test_very_large_drift(self):
        self.assertEqual(classify_drift(500.0), "hot")


# ---------------------------------------------------------------------------
# compute_stability
# ---------------------------------------------------------------------------

class TestComputeStability(unittest.TestCase):
    """Coefficient of variation."""

    def test_empty_list(self):
        self.assertEqual(compute_stability([]), 0.0)

    def test_single_element(self):
        self.assertEqual(compute_stability([15.0]), 0.0)

    def test_identical_intervals(self):
        # Perfect stability: all values the same → CV = 0
        self.assertAlmostEqual(compute_stability([15.0] * 10), 0.0)

    def test_low_variance(self):
        intervals = [14.9, 15.0, 15.1, 15.0, 14.8, 15.2]
        cv = compute_stability(intervals)
        self.assertGreater(cv, 0)
        self.assertLess(cv, 0.05)

    def test_high_variance(self):
        intervals = [5.0, 25.0, 5.0, 25.0, 5.0, 25.0]
        cv = compute_stability(intervals)
        self.assertGreater(cv, 0.5)

    def test_known_value(self):
        # [10, 20, 30] → mean=20, var=66.67, sd=8.165, CV=0.4082
        cv = compute_stability([10.0, 20.0, 30.0])
        self.assertAlmostEqual(cv, 0.4082, places=3)


# ---------------------------------------------------------------------------
# count_jitter
# ---------------------------------------------------------------------------

class TestCountJitter(unittest.TestCase):
    """Jitter detection — intervals deviating >2× from target."""

    def test_no_jitter(self):
        intervals = [14.0, 15.0, 16.0, 15.5, 14.5]
        self.assertEqual(count_jitter(intervals, 15.0), 0)

    def test_too_fast(self):
        # 7.0 < 15/2 = 7.5 → jitter
        intervals = [7.0, 15.0, 15.0]
        self.assertEqual(count_jitter(intervals, 15.0), 1)

    def test_too_slow(self):
        # 31.0 > 15*2 = 30 → jitter
        intervals = [15.0, 31.0, 15.0]
        self.assertEqual(count_jitter(intervals, 15.0), 1)

    def test_boundary_not_jitter(self):
        # Exactly at boundary: 7.5 and 30.0 are NOT jitter (not < or >)
        intervals = [7.5, 30.0]
        self.assertEqual(count_jitter(intervals, 15.0), 0)

    def test_all_jitter(self):
        intervals = [2.0, 50.0, 1.0, 100.0]
        self.assertEqual(count_jitter(intervals, 15.0), 4)

    def test_zero_target(self):
        self.assertEqual(count_jitter([10.0, 20.0], 0), 0)

    def test_empty_intervals(self):
        self.assertEqual(count_jitter([], 15.0), 0)


# ---------------------------------------------------------------------------
# extract_intervals_from_strokes
# ---------------------------------------------------------------------------

class TestExtractIntervals(unittest.TestCase):
    """Interval extraction from stroke dicts."""

    def test_basic_extraction(self):
        strokes = [
            {"at": "2026-11-09T12:00:00+00:00"},
            {"at": "2026-11-09T12:00:15+00:00"},
            {"at": "2026-11-09T12:00:30+00:00"},
        ]
        intervals = extract_intervals_from_strokes(strokes)
        self.assertEqual(len(intervals), 2)
        self.assertAlmostEqual(intervals[0], 15.0)
        self.assertAlmostEqual(intervals[1], 15.0)

    def test_unsorted_input(self):
        """Function should sort by timestamp before computing intervals."""
        strokes = [
            {"at": "2026-11-09T12:00:30+00:00"},
            {"at": "2026-11-09T12:00:00+00:00"},
            {"at": "2026-11-09T12:00:15+00:00"},
        ]
        intervals = extract_intervals_from_strokes(strokes)
        self.assertEqual(len(intervals), 2)
        self.assertAlmostEqual(intervals[0], 15.0)

    def test_empty_strokes(self):
        self.assertEqual(extract_intervals_from_strokes([]), [])

    def test_single_stroke(self):
        self.assertEqual(extract_intervals_from_strokes([{"at": "2026-11-09T12:00:00+00:00"}]), [])

    def test_missing_at_field(self):
        strokes = [{"text": "hello"}, {"at": "2026-11-09T12:00:15+00:00"}]
        # First one has no "at", so only one valid timestamp → 0 intervals
        intervals = extract_intervals_from_strokes(strokes)
        self.assertEqual(len(intervals), 0)

    def test_malformed_timestamp(self):
        strokes = [
            {"at": "not-a-date"},
            {"at": "2026-11-09T12:00:15+00:00"},
        ]
        intervals = extract_intervals_from_strokes(strokes)
        self.assertEqual(len(intervals), 0)

    def test_z_suffix(self):
        strokes = [
            {"at": "2026-11-09T12:00:00Z"},
            {"at": "2026-11-09T12:00:15Z"},
        ]
        intervals = extract_intervals_from_strokes(strokes)
        self.assertEqual(len(intervals), 1)
        self.assertAlmostEqual(intervals[0], 15.0)


# ---------------------------------------------------------------------------
# compute_drift
# ---------------------------------------------------------------------------

class TestComputeDrift(unittest.TestCase):
    """Core drift computation."""

    def test_empty_intervals(self):
        report = compute_drift([])
        self.assertEqual(report.sample_size, 0)
        self.assertEqual(report.drift_class, "tight")

    def test_perfect_cadence(self):
        intervals = [15.0] * 100
        report = compute_drift(intervals, target=15, window=60)
        self.assertEqual(report.sample_size, 60)
        self.assertAlmostEqual(report.mean_interval_s, 15.0)
        self.assertAlmostEqual(report.drift_pct, 0.0)
        self.assertEqual(report.drift_class, "tight")
        self.assertAlmostEqual(report.stability, 0.0)

    def test_slow_cadence(self):
        intervals = [18.0] * 60
        report = compute_drift(intervals, target=15)
        self.assertAlmostEqual(report.drift_pct, 20.0)
        self.assertEqual(report.drift_class, "hot")

    def test_fast_cadence(self):
        intervals = [12.0] * 60
        report = compute_drift(intervals, target=15)
        self.assertAlmostEqual(report.drift_pct, -20.0)
        self.assertEqual(report.drift_class, "hot")

    def test_window_truncation(self):
        """Only the most recent `window` intervals should be used."""
        old = [100.0] * 100  # very slow
        recent = [15.0] * 60  # perfect
        all_intervals = old + recent
        report = compute_drift(all_intervals, target=15, window=60)
        self.assertAlmostEqual(report.mean_interval_s, 15.0)
        self.assertEqual(report.drift_class, "tight")

    def test_jitter_detection_in_report(self):
        intervals = [15.0] * 55 + [2.0, 50.0, 1.0, 100.0, 15.0]
        report = compute_drift(intervals, target=15, window=60)
        self.assertGreaterEqual(report.jitter_count, 3)

    def test_frozen_dataclass(self):
        report = compute_drift([15.0] * 10)
        with self.assertRaises(AttributeError):
            report.drift_pct = 999  # type: ignore

    def test_to_dict(self):
        report = compute_drift([15.0] * 10)
        d = report.to_dict()
        self.assertIn("drift_pct", d)
        self.assertIn("drift_class", d)
        self.assertIn("stability", d)
        self.assertIsInstance(d, dict)

    def test_summary_no_data(self):
        report = compute_drift([])
        self.assertIn("no intervals", report.summary())

    def test_summary_with_data(self):
        report = compute_drift([15.0] * 20)
        s = report.summary()
        self.assertIn("tight", s)
        self.assertIn("15.0s", s)

    def test_median_odd_count(self):
        intervals = [10.0, 15.0, 20.0]
        report = compute_drift(intervals, target=15, window=10)
        self.assertAlmostEqual(report.median_interval_s, 15.0)

    def test_median_even_count(self):
        intervals = [10.0, 20.0, 30.0, 40.0]
        report = compute_drift(intervals, target=15, window=10)
        self.assertAlmostEqual(report.median_interval_s, 25.0)


# ---------------------------------------------------------------------------
# detect_trend
# ---------------------------------------------------------------------------

class TestDetectTrend(unittest.TestCase):
    """Cadence trend detection."""

    def test_insufficient_data(self):
        self.assertEqual(detect_trend([15.0] * 10), "insufficient_data")

    def test_stable_trend(self):
        intervals = [15.0] * 100
        self.assertEqual(detect_trend(intervals, chunk_size=20), "stable")

    def test_degrading_trend(self):
        first = [15.0] * 30
        last = [25.0] * 30
        self.assertEqual(detect_trend(first + last, chunk_size=20), "degrading")

    def test_improving_trend(self):
        first = [30.0] * 30
        last = [15.0] * 30
        self.assertEqual(detect_trend(first + last, chunk_size=20), "improving")

    def test_small_change_is_stable(self):
        first = [15.0] * 30
        last = [15.5] * 30  # ~3% change
        self.assertEqual(detect_trend(first + last, chunk_size=20), "stable")


# ---------------------------------------------------------------------------
# File loaders
# ---------------------------------------------------------------------------

class TestLoadFromState(unittest.TestCase):
    """Load intervals from writer state JSON."""

    def test_load_valid_state(self):
        data = {
            "history": [
                {"at": "2026-11-09T12:00:00+00:00", "kind": "thought"},
                {"at": "2026-11-09T12:00:15+00:00", "kind": "devlog"},
                {"at": "2026-11-09T12:00:30+00:00", "kind": "garden"},
            ]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            tmp = f.name
        try:
            intervals = load_intervals_from_state(Path(tmp))
            self.assertEqual(len(intervals), 2)
            self.assertAlmostEqual(intervals[0], 15.0)
        finally:
            os.unlink(tmp)

    def test_load_nonexistent(self):
        intervals = load_intervals_from_state(Path("/tmp/nonexistent_state_98765.json"))
        self.assertEqual(intervals, [])

    def test_load_bad_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            tmp = f.name
        try:
            intervals = load_intervals_from_state(Path(tmp))
            self.assertEqual(intervals, [])
        finally:
            os.unlink(tmp)

    def test_load_empty_history(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"history": []}, f)
            tmp = f.name
        try:
            intervals = load_intervals_from_state(Path(tmp))
            self.assertEqual(intervals, [])
        finally:
            os.unlink(tmp)


class TestLoadFromJsonl(unittest.TestCase):
    """Load intervals from strokes JSONL."""

    def test_load_valid_jsonl(self):
        lines = [
            {"at": "2026-11-09T12:00:00+00:00", "kind": "thought"},
            {"at": "2026-11-09T12:00:15+00:00", "kind": "note"},
            {"at": "2026-11-09T12:00:30+00:00", "kind": "metrics"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
            tmp = f.name
        try:
            intervals = load_intervals_from_jsonl(Path(tmp))
            self.assertEqual(len(intervals), 2)
        finally:
            os.unlink(tmp)

    def test_load_skips_bad_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"at": "2026-11-09T12:00:00+00:00"}\n')
            f.write('NOT JSON\n')
            f.write('{"at": "2026-11-09T12:00:15+00:00"}\n')
            tmp = f.name
        try:
            intervals = load_intervals_from_jsonl(Path(tmp))
            self.assertEqual(len(intervals), 1)
            self.assertAlmostEqual(intervals[0], 15.0)
        finally:
            os.unlink(tmp)

    def test_load_nonexistent_jsonl(self):
        intervals = load_intervals_from_jsonl(Path("/tmp/nonexistent_strokes_12345.jsonl"))
        self.assertEqual(intervals, [])


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    """End-to-end scenarios."""

    def test_realistic_writer_pattern(self):
        """Simulate a writer running at ~15s cadence with some noise."""
        import random
        random.seed(42)
        intervals = [15.0 + random.gauss(0, 0.5) for _ in range(200)]
        report = compute_drift(intervals, target=15, window=60)
        self.assertEqual(report.sample_size, 60)
        self.assertEqual(report.drift_class, "tight")
        self.assertLess(abs(report.drift_pct), 5)
        self.assertLess(report.stability, 0.1)

    def test_degrading_writer(self):
        """Writer starts healthy, then slows down."""
        healthy = [15.0 + random.gauss(0, 0.3) for random in [__import__('random')]] * 100
        # Oops, can't use random like that. Let me fix.
        import random
        random.seed(7)
        healthy = [15.0 + random.gauss(0, 0.3) for _ in range(100)]
        degrading = [15.0 + i * 0.5 + random.gauss(0, 0.3) for i in range(100)]
        all_intervals = healthy + degrading
        report = compute_drift(all_intervals, target=15, window=60)
        # Last 60 are from the degrading phase → drift should be positive
        self.assertGreater(report.drift_pct, 0)
        trend = detect_trend(all_intervals, chunk_size=40)
        self.assertEqual(trend, "degrading")

    def test_after_restart_recovery(self):
        """After a restart, intervals start large then settle."""
        import random
        random.seed(99)
        # First few intervals are huge (restart overhead)
        recovery = [120.0, 60.0, 30.0, 20.0]
        settled = [15.0 + random.gauss(0, 0.2) for _ in range(100)]
        all_intervals = recovery + settled
        report = compute_drift(all_intervals, target=15, window=60)
        # Last 60 are all settled → tight
        self.assertEqual(report.drift_class, "tight")


if __name__ == "__main__":
    unittest.main()
