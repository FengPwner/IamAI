#!/usr/bin/env python3
"""
test_stroke_temporal_density.py — Tests for stroke temporal density analysis.

Covers:
  - ISO timestamp parsing (valid, malformed, timezone-aware, naive)
  - Window segmentation (empty, single, multi-window, gaps)
  - Density computation (rate arithmetic, zero windows)
  - Peak detection
  - Classification boundaries (prolific/steady/thinning/silent)
  - Cliff detection (threshold, no-cliff, multi-cliff)
  - Trend calculation (positive, negative, flat, insufficient data)
  - Kind distribution counting
  - End-to-end report generation
  - Edge cases (single stroke, two strokes, all-same-timestamp)
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

# Ensure tools directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stroke_temporal_density as std


class TestParseIso(unittest.TestCase):
    """Test ISO 8601 timestamp parsing."""

    def test_valid_utc(self):
        result = std.parse_iso("2026-11-20T05:00:00+00:00")
        self.assertIsNotNone(result)
        # Verify it round-trips back to the same datetime
        dt = datetime.fromtimestamp(result, tz=timezone.utc)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 11)
        self.assertEqual(dt.day, 20)
        self.assertEqual(dt.hour, 5)

    def test_valid_with_z(self):
        result = std.parse_iso("2026-11-20T05:00:00Z")
        self.assertIsNotNone(result)

    def test_valid_positive_offset(self):
        result = std.parse_iso("2026-11-20T13:00:00+08:00")
        self.assertIsNotNone(result)

    def test_naive_assumed_utc(self):
        result = std.parse_iso("2026-11-20T05:00:00")
        self.assertIsNotNone(result)

    def test_empty_string(self):
        self.assertIsNone(std.parse_iso(""))

    def test_none_input(self):
        self.assertIsNone(std.parse_iso(None))

    def test_garbage(self):
        self.assertIsNone(std.parse_iso("not a timestamp"))

    def test_partial_date(self):
        self.assertIsNone(std.parse_iso("2026-11"))


class TestSegmentWindows(unittest.TestCase):
    """Test time window segmentation."""

    def test_empty_strokes(self):
        result = std.segment_windows([], 600)
        self.assertEqual(result, [])

    def test_single_stroke(self):
        strokes = [(1000.0, "devlog", "text", 1)]
        result = std.segment_windows(strokes, 600)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][2], 1)  # count

    def test_multiple_same_window(self):
        strokes = [
            (1000.0, "devlog", "a", 1),
            (1005.0, "note", "b", 2),
            (1010.0, "thought", "c", 3),
        ]
        result = std.segment_windows(strokes, 600)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][2], 3)

    def test_spans_two_windows(self):
        strokes = [
            (1000.0, "devlog", "a", 1),
            (1700.0, "note", "b", 2),  # second window starts at 1600
        ]
        result = std.segment_windows(strokes, 600)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][2], 1)  # first window
        self.assertEqual(result[1][2], 1)  # second window

    def test_gap_creates_empty_windows(self):
        strokes = [
            (1000.0, "devlog", "a", 1),
            (3000.0, "note", "b", 2),  # big gap
        ]
        result = std.segment_windows(strokes, 600)
        # windows: [1000-1600], [1600-2200], [2200-2800], [2800-3400]
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0][2], 1)
        self.assertEqual(result[1][2], 0)  # empty
        self.assertEqual(result[2][2], 0)  # empty
        self.assertEqual(result[3][2], 1)

    def test_all_same_timestamp(self):
        strokes = [(500.0, "a", "x", i) for i in range(10)]
        result = std.segment_windows(strokes, 600)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][2], 10)


class TestComputeDensity(unittest.TestCase):
    """Test strokes-per-minute calculation."""

    def test_basic_rate(self):
        # 6 strokes in a 600-second (10-minute) window = 0.6 spm
        windows = [(1000.0, 1600.0, 6, [])]
        result = std.compute_density(windows, 600)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0][1], 0.6, places=3)

    def test_empty_window(self):
        windows = [(1000.0, 1600.0, 0, [])]
        result = std.compute_density(windows, 600)
        self.assertAlmostEqual(result[0][1], 0.0)

    def test_small_window(self):
        # 3 strokes in 60 seconds = 3.0 spm
        windows = [(1000.0, 1060.0, 3, [])]
        result = std.compute_density(windows, 60)
        self.assertAlmostEqual(result[0][1], 3.0, places=3)

    def test_zero_window_size(self):
        # Edge case: zero-width window should not divide by zero
        windows = [(1000.0, 1000.0, 5, [])]
        result = std.compute_density(windows, 0)
        self.assertEqual(result[0][1], 0)

    def test_multiple_windows(self):
        windows = [
            (1000.0, 1600.0, 10, []),  # 1.0 spm
            (1600.0, 2200.0, 5, []),   # 0.5 spm
            (2200.0, 2800.0, 0, []),   # 0.0 spm
        ]
        result = std.compute_density(windows, 600)
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(result[0][1], 1.0, places=3)
        self.assertAlmostEqual(result[1][1], 0.5, places=3)
        self.assertAlmostEqual(result[2][1], 0.0, places=3)


class TestFindPeakDensity(unittest.TestCase):
    """Test peak density detection."""

    def test_basic(self):
        densities = [(1000, 0.5, 5), (1600, 1.2, 12), (2200, 0.8, 8)]
        self.assertAlmostEqual(std.find_peak_density(densities), 1.2)

    def test_empty(self):
        self.assertEqual(std.find_peak_density([]), 0.0)

    def test_single(self):
        self.assertAlmostEqual(std.find_peak_density([(1000, 0.3, 3)]), 0.3)

    def test_all_zero(self):
        densities = [(1000, 0.0, 0), (1600, 0.0, 0)]
        self.assertEqual(std.find_peak_density(densities), 0.0)


class TestClassifyDensity(unittest.TestCase):
    """Test writer state classification based on density ratio."""

    def test_prolific(self):
        # ratio = 0.9 > 0.8
        self.assertEqual(std.classify_density(0.9, 1.0), "prolific")

    def test_prolific_boundary(self):
        # ratio = 0.81 > 0.8
        self.assertEqual(std.classify_density(0.81, 1.0), "prolific")

    def test_steady(self):
        # ratio = 0.6, in [0.4, 0.8]
        self.assertEqual(std.classify_density(0.6, 1.0), "steady")

    def test_steady_lower_boundary(self):
        # ratio = 0.41 > 0.4
        self.assertEqual(std.classify_density(0.41, 1.0), "steady")

    def test_thinning(self):
        # ratio = 0.25, in [0.1, 0.4]
        self.assertEqual(std.classify_density(0.25, 1.0), "thinning")

    def test_thinning_lower_boundary(self):
        # ratio = 0.11 > 0.1
        self.assertEqual(std.classify_density(0.11, 1.0), "thinning")

    def test_silent(self):
        # ratio = 0.05 < 0.1
        self.assertEqual(std.classify_density(0.05, 1.0), "silent")

    def test_silent_zero(self):
        self.assertEqual(std.classify_density(0.0, 1.0), "silent")

    def test_peak_zero(self):
        # No historical peak → silent
        self.assertEqual(std.classify_density(0.5, 0.0), "silent")

    def test_both_zero(self):
        self.assertEqual(std.classify_density(0.0, 0.0), "silent")

    def test_exact_boundary_08(self):
        # ratio = 0.8 → not > 0.8, so steady
        self.assertEqual(std.classify_density(0.8, 1.0), "steady")

    def test_exact_boundary_04(self):
        # ratio = 0.4 → not > 0.4, so thinning
        self.assertEqual(std.classify_density(0.4, 1.0), "thinning")

    def test_exact_boundary_01(self):
        # ratio = 0.1 → not > 0.1, so silent
        self.assertEqual(std.classify_density(0.1, 1.0), "silent")


class TestDetectCliff(unittest.TestCase):
    """Test density cliff detection (>50% drop between consecutive windows)."""

    def test_no_cliff_stable(self):
        densities = [(1000, 1.0, 10), (1600, 0.9, 9), (2200, 0.85, 8)]
        cliffs = std.detect_cliff(densities)
        self.assertEqual(len(cliffs), 0)

    def test_single_cliff(self):
        densities = [(1000, 1.0, 10), (1600, 0.3, 3)]
        cliffs = std.detect_cliff(densities)
        self.assertEqual(len(cliffs), 1)
        self.assertEqual(cliffs[0][0], 1)  # window index
        self.assertAlmostEqual(cliffs[0][1], 1.0)  # from
        self.assertAlmostEqual(cliffs[0][2], 0.3)  # to
        self.assertAlmostEqual(cliffs[0][3], 0.7)  # drop ratio

    def test_no_cliff_exactly_50(self):
        # drop = 0.5, threshold = 0.5 → not > threshold
        densities = [(1000, 1.0, 10), (1600, 0.5, 5)]
        cliffs = std.detect_cliff(densities)
        self.assertEqual(len(cliffs), 0)

    def test_cliff_just_above_threshold(self):
        densities = [(1000, 1.0, 10), (1600, 0.49, 4)]
        cliffs = std.detect_cliff(densities)
        self.assertEqual(len(cliffs), 1)

    def test_multiple_cliffs(self):
        densities = [
            (1000, 2.0, 20),
            (1600, 0.5, 5),   # cliff: 75% drop
            (2200, 0.4, 4),   # no cliff
            (2800, 0.1, 1),   # cliff: 75% drop
        ]
        cliffs = std.detect_cliff(densities)
        self.assertEqual(len(cliffs), 2)

    def test_from_zero_no_crash(self):
        # Previous window has 0 density — should not divide by zero
        densities = [(1000, 0.0, 0), (1600, 0.5, 5)]
        cliffs = std.detect_cliff(densities)
        self.assertEqual(len(cliffs), 0)

    def test_custom_threshold(self):
        densities = [(1000, 1.0, 10), (1600, 0.8, 8)]
        # With 30% threshold, 20% drop is not a cliff
        cliffs = std.detect_cliff(densities, threshold=0.3)
        self.assertEqual(len(cliffs), 0)
        # With 15% threshold, 20% drop IS a cliff
        cliffs = std.detect_cliff(densities, threshold=0.15)
        self.assertEqual(len(cliffs), 1)

    def test_empty(self):
        self.assertEqual(std.detect_cliff([]), [])

    def test_single_window(self):
        self.assertEqual(std.detect_cliff([(1000, 1.0, 10)]), [])


class TestDensityTrend(unittest.TestCase):
    """Test linear trend computation over density series."""

    def test_flat_trend(self):
        densities = [(i * 600, 1.0, 10) for i in range(10)]
        slope, r_sq = std.density_trend(densities)
        self.assertAlmostEqual(slope, 0.0, places=4)

    def test_declining_trend(self):
        densities = [(i * 600, 2.0 - i * 0.2, 10 - i) for i in range(10)]
        slope, r_sq = std.density_trend(densities)
        self.assertLess(slope, 0)
        self.assertGreater(r_sq, 0.9)  # strong linear trend

    def test_increasing_trend(self):
        densities = [(i * 600, 0.1 + i * 0.1, i) for i in range(10)]
        slope, r_sq = std.density_trend(densities)
        self.assertGreater(slope, 0)

    def test_insufficient_data_two_points(self):
        densities = [(1000, 1.0, 10), (1600, 0.5, 5)]
        slope, r_sq = std.density_trend(densities)
        self.assertEqual(slope, 0.0)
        self.assertEqual(r_sq, 0.0)

    def test_insufficient_data_empty(self):
        slope, r_sq = std.density_trend([])
        self.assertEqual(slope, 0.0)

    def test_three_points_minimum(self):
        densities = [(1000, 1.0, 10), (1600, 0.8, 8), (2200, 0.6, 6)]
        slope, r_sq = std.density_trend(densities)
        self.assertLess(slope, 0)

    def test_constant_x_no_crash(self):
        # All windows at same x (shouldn't happen but defensive)
        densities = [(1000, 1.0, 10)]
        slope, r_sq = std.density_trend(densities)
        self.assertEqual(slope, 0.0)


class TestKindDistribution(unittest.TestCase):
    """Test stroke kind counting within a window."""

    def test_basic(self):
        strokes = [
            (1000, "devlog", "a", 1),
            (1001, "note", "b", 2),
            (1002, "devlog", "c", 3),
            (1003, "thought", "d", 4),
            (1004, "devlog", "e", 5),
        ]
        dist = std.kind_distribution(strokes)
        self.assertEqual(dist["devlog"], 3)
        self.assertEqual(dist["note"], 1)
        self.assertEqual(dist["thought"], 1)

    def test_empty(self):
        self.assertEqual(std.kind_distribution([]), {})

    def test_single_kind(self):
        strokes = [(1000, "snippet", f"x{i}", i) for i in range(7)]
        dist = std.kind_distribution(strokes)
        self.assertEqual(dist, {"snippet": 7})


class TestLoadStrokes(unittest.TestCase):
    """Test JSONL file loading with temporary files."""

    def test_load_valid_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"at": "2026-11-20T05:00:00Z", "kind": "devlog", "text": "hello", "seq": 1}) + "\n")
            f.write(json.dumps({"at": "2026-11-20T05:01:00Z", "kind": "note", "text": "world", "seq": 2}) + "\n")
            tmp = f.name
        try:
            strokes = std.load_strokes(Path(tmp))
            self.assertIsNotNone(strokes)
            self.assertEqual(len(strokes), 2)
            self.assertEqual(strokes[0][1], "devlog")
            self.assertEqual(strokes[1][1], "note")
        finally:
            os.unlink(tmp)

    def test_load_missing_file(self):
        result = std.load_strokes(Path("/nonexistent/path/strokes.jsonl"))
        self.assertIsNone(result)

    def test_load_malformed_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("this is not json\n")
            f.write(json.dumps({"at": "2026-11-20T05:00:00Z", "kind": "devlog", "text": "ok", "seq": 1}) + "\n")
            f.write("{broken json\n")
            tmp = f.name
        try:
            strokes = std.load_strokes(Path(tmp))
            self.assertIsNotNone(strokes)
            self.assertEqual(len(strokes), 1)
        finally:
            os.unlink(tmp)

    def test_load_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            tmp = f.name
        try:
            strokes = std.load_strokes(Path(tmp))
            self.assertIsNotNone(strokes)
            self.assertEqual(len(strokes), 0)
        finally:
            os.unlink(tmp)

    def test_load_skips_missing_timestamp(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"kind": "devlog", "text": "no ts"}) + "\n")
            f.write(json.dumps({"at": "2026-11-20T05:00:00Z", "kind": "note", "text": "has ts", "seq": 1}) + "\n")
            tmp = f.name
        try:
            strokes = std.load_strokes(Path(tmp))
            self.assertEqual(len(strokes), 1)
            self.assertEqual(strokes[0][1], "note")
        finally:
            os.unlink(tmp)

    def test_load_sorts_by_timestamp(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"at": "2026-11-20T06:00:00Z", "kind": "b", "text": "later", "seq": 2}) + "\n")
            f.write(json.dumps({"at": "2026-11-20T05:00:00Z", "kind": "a", "text": "earlier", "seq": 1}) + "\n")
            tmp = f.name
        try:
            strokes = std.load_strokes(Path(tmp))
            self.assertEqual(strokes[0][1], "a")
            self.assertEqual(strokes[1][1], "b")
        finally:
            os.unlink(tmp)


class TestEndToEnd(unittest.TestCase):
    """Integration test: generate synthetic strokes and verify full pipeline."""

    def _make_strokes(self, base_ts, count, interval_s, kind="devlog"):
        return [(base_ts + i * interval_s, kind, f"stroke {i}", i + 1)
                for i in range(count)]

    def test_steady_writer(self):
        # 40 strokes over 400 seconds at 10s intervals
        strokes = self._make_strokes(1000.0, 40, 10)
        windows = std.segment_windows(strokes, 60)
        densities = std.compute_density(windows, 60)
        peak = std.find_peak_density(densities)

        # Each 60-second window should have ~6 strokes = 6 spm
        self.assertGreater(peak, 0)
        state = std.classify_density(densities[-1][1], peak)
        # Steady or prolific (density is consistent)
        self.assertIn(state, ("prolific", "steady"))

    def test_degrading_writer(self):
        # First half: 1 stroke/5s, second half: 1 stroke/50s
        strokes = []
        ts = 1000.0
        for i in range(20):
            strokes.append((ts, "devlog", f"fast {i}", i + 1))
            ts += 5
        for i in range(20):
            strokes.append((ts, "devlog", f"slow {i}", 21 + i))
            ts += 50

        windows = std.segment_windows(strokes, 100)
        densities = std.compute_density(windows, 100)
        cliffs = std.detect_cliff(densities)

        # Should detect at least one cliff where density drops
        self.assertGreater(len(cliffs), 0)

    def test_silent_then_burst(self):
        # 1 stroke, then long gap, then 10 strokes quickly
        strokes = [(1000.0, "devlog", "lonely", 1)]
        for i in range(10):
            strokes.append((5000.0 + i * 5, "note", f"burst {i}", 2 + i))

        windows = std.segment_windows(strokes, 600)
        densities = std.compute_density(windows, 600)

        # First window has 1 stroke, some empty windows, last has 10
        has_empty = any(d[2] == 0 for d in densities)
        self.assertTrue(has_empty)

        # Last window should have highest density
        last_spm = densities[-1][1]
        peak = std.find_peak_density(densities)
        self.assertAlmostEqual(last_spm, peak, places=3)


class TestFormatReport(unittest.TestCase):
    """Test human-readable report generation."""

    def test_basic_report(self):
        densities = [
            (1763614800.0, 1.0, 10),
            (1763615400.0, 0.8, 8),
            (1763616000.0, 0.5, 5),
        ]
        report = std.format_report(densities, 1.0, [], -0.1, 0.95, 0, 600)
        self.assertIn("Stroke Temporal Density Report", report)
        self.assertIn("Peak density", report)
        self.assertIn("prolific", report)  # first window at 1.0/1.0

    def test_empty_densities(self):
        report = std.format_report([], 0.0, [], 0.0, 0.0, 0, 600)
        self.assertIn("No stroke data", report)

    def test_tail_limits_output(self):
        densities = [(1763614800.0 + i * 600, 0.5, 5) for i in range(50)]
        report = std.format_report(densities, 0.5, [], 0.0, 0.0, 5, 600)
        # Should mention last 5 windows in the recent section
        self.assertIn("Recent windows (last 5)", report)

    def test_report_with_cliffs(self):
        densities = [
            (1763614800.0, 2.0, 20),
            (1763615400.0, 0.5, 5),
        ]
        cliffs = [(1, 2.0, 0.5, 0.75)]
        report = std.format_report(densities, 2.0, cliffs, -0.5, 0.8, 0, 600)
        self.assertIn("cliffs detected: 1", report)


if __name__ == "__main__":
    unittest.main()
