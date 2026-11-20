#!/usr/bin/env python3
"""Tests for stroke_silence_taxonomy.py — 22 tests across 4 classes."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ensure tools/ is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stroke_silence_taxonomy import (
    classify_gap,
    compute_gaps,
    load_strokes,
    analyze,
    TaxonomyResult,
    CATEGORIES,
)


class TestClassifyGap(unittest.TestCase):
    """Test the gap classification boundaries."""

    def test_zero_gap_is_breath(self):
        self.assertEqual(classify_gap(0, 15), "breath")

    def test_negative_gap_is_breath(self):
        """Clock jitter should be treated as normal."""
        self.assertEqual(classify_gap(-5, 15), "breath")

    def test_exact_cadence_is_breath(self):
        self.assertEqual(classify_gap(15, 15), "breath")

    def test_double_cadence_is_breath(self):
        """Boundary: exactly 2x is still breath."""
        self.assertEqual(classify_gap(30, 15), "breath")

    def test_just_over_2x_is_pause(self):
        self.assertEqual(classify_gap(31, 15), "pause")

    def test_10x_boundary_is_pause(self):
        """Boundary: exactly 10x is still pause."""
        self.assertEqual(classify_gap(150, 15), "pause")

    def test_just_over_10x_is_gap(self):
        self.assertEqual(classify_gap(151, 15), "gap")

    def test_100x_boundary_is_gap(self):
        """Boundary: exactly 100x is still gap."""
        self.assertEqual(classify_gap(1500, 15), "gap")

    def test_just_over_100x_is_stall(self):
        self.assertEqual(classify_gap(1501, 15), "stall")

    def test_1000x_boundary_is_stall(self):
        """Boundary: exactly 1000x is still stall."""
        self.assertEqual(classify_gap(15000, 15), "stall")

    def test_over_1000x_is_graveyard(self):
        self.assertEqual(classify_gap(15001, 15), "graveyard")

    def test_massive_gap_is_graveyard(self):
        self.assertEqual(classify_gap(140393, 15), "graveyard")

    def test_zero_expected_cadence(self):
        """Zero expected cadence makes everything a graveyard."""
        self.assertEqual(classify_gap(1, 0), "graveyard")


class TestComputeGaps(unittest.TestCase):
    """Test inter-stroke gap computation."""

    def test_empty_list(self):
        self.assertEqual(compute_gaps([]), [])

    def test_single_timestamp(self):
        ts = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        self.assertEqual(compute_gaps(ts), [])

    def test_uniform_gaps(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [base + timedelta(seconds=15 * i) for i in range(5)]
        gaps = compute_gaps(ts)
        self.assertEqual(len(gaps), 4)
        self.assertTrue(all(g == 15.0 for g in gaps))

    def test_mixed_gaps(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [
            base,
            base + timedelta(seconds=15),
            base + timedelta(seconds=300),
            base + timedelta(seconds=315),
        ]
        gaps = compute_gaps(ts)
        self.assertEqual(len(gaps), 3)
        self.assertAlmostEqual(gaps[0], 15.0)
        self.assertAlmostEqual(gaps[1], 285.0)
        self.assertAlmostEqual(gaps[2], 15.0)


class TestLoadStrokes(unittest.TestCase):
    """Test JSONL loading with edge cases."""

    def test_nonexistent_file(self):
        result = load_strokes(Path("/nonexistent/strokes.jsonl"))
        self.assertEqual(result, [])

    def test_valid_jsonl(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write('{"seq":1,"at":"2026-01-01T00:00:00+00:00"}\n')
            f.write('{"seq":2,"at":"2026-01-01T00:00:15+00:00"}\n')
            f.write('{"seq":3,"at":"2026-01-01T00:00:30+00:00"}\n')
            path = Path(f.name)
        try:
            ts = load_strokes(path)
            self.assertEqual(len(ts), 3)
        finally:
            path.unlink()

    def test_malformed_lines_skipped(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write('{"seq":1,"at":"2026-01-01T00:00:00+00:00"}\n')
            f.write('not json at all\n')
            f.write('{"seq":3,"at":"2026-01-01T00:00:30+00:00"}\n')
            path = Path(f.name)
        try:
            ts = load_strokes(path)
            self.assertEqual(len(ts), 2)
        finally:
            path.unlink()

    def test_timestamps_sorted(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            # write out of order
            f.write('{"seq":3,"at":"2026-01-01T00:00:30+00:00"}\n')
            f.write('{"seq":1,"at":"2026-01-01T00:00:00+00:00"}\n')
            f.write('{"seq":2,"at":"2026-01-01T00:00:15+00:00"}\n')
            path = Path(f.name)
        try:
            ts = load_strokes(path)
            self.assertEqual(len(ts), 3)
            # should be sorted
            for i in range(1, len(ts)):
                self.assertGreaterEqual(ts[i], ts[i - 1])
        finally:
            path.unlink()


class TestAnalyze(unittest.TestCase):
    """Test the full analysis pipeline."""

    def test_all_breath_gaps(self):
        """Perfect cadence: all gaps at 15s."""
        gaps = [15.0] * 100
        result = analyze(gaps, 15.0, total_strokes=101)
        self.assertEqual(result.verdict, "healthy")
        self.assertEqual(result.distribution["breath"]["count"], 100)
        self.assertAlmostEqual(result.silence_ratio, 0.0)
        self.assertEqual(result.recovery_count, 0)

    def test_mixed_with_stall(self):
        """Mostly breath but one big stall."""
        gaps = [15.0] * 50 + [3600.0] + [15.0] * 50
        result = analyze(gaps, 15.0, total_strokes=102)
        self.assertEqual(result.distribution["stall"]["count"], 1)
        self.assertEqual(result.recovery_count, 1)
        self.assertGreater(result.silence_ratio, 0)

    def test_mostly_silence_is_stalled(self):
        """When most time is in stalls, verdict should be stalled."""
        gaps = [15.0] * 10 + [50000.0, 50000.0]
        result = analyze(gaps, 15.0, total_strokes=13)
        self.assertEqual(result.verdict, "stalled")

    def test_degraded_zone(self):
        """Some silence but not terrible."""
        # 80 breath gaps (1200s) + 2 pause-category gaps (150s each = 300s)
        # silence_ratio = 300 / 1500 = 0.20 → degraded
        gaps = [15.0] * 80 + [150.0, 150.0]
        result = analyze(gaps, 15.0, total_strokes=83)
        self.assertEqual(result.verdict, "degraded")

    def test_empty_gaps(self):
        """No gaps: should handle gracefully."""
        result = analyze([], 15.0, total_strokes=1)
        self.assertEqual(result.total_gaps, 0)
        self.assertEqual(result.worst_gap_sec, 0.0)

    def test_recovery_counting(self):
        """Recovery = transition from non-breath back to breath."""
        # breath, pause, breath, gap, breath
        gaps = [15.0, 100.0, 15.0, 1000.0, 15.0]
        result = analyze(gaps, 15.0, total_strokes=6)
        self.assertEqual(result.recovery_count, 2)

    def test_worst_gap_category(self):
        gaps = [15.0, 15.0, 140393.0]
        result = analyze(gaps, 15.0, total_strokes=4)
        self.assertEqual(result.worst_gap_category, "graveyard")
        self.assertAlmostEqual(result.worst_gap_sec, 140393.0)

    def test_median_breath(self):
        gaps = [10.0, 15.0, 20.0, 100.0, 12.0]
        result = analyze(gaps, 15.0, total_strokes=6)
        # breath values: 10, 15, 20, 12 -> sorted: 10, 12, 15, 20
        # median at index 2 = 15
        self.assertAlmostEqual(result.median_breath, 15.0)

    def test_all_categories_present(self):
        """Ensure all five categories appear in the result."""
        gaps = [15.0, 50.0, 500.0, 5000.0, 50000.0]
        result = analyze(gaps, 15.0, total_strokes=6)
        for cat in CATEGORIES:
            self.assertIn(cat, result.distribution)

    def test_graveyard_only(self):
        """A single enormous gap dominates everything."""
        gaps = [140393.0]
        result = analyze(gaps, 15.0, total_strokes=2)
        self.assertEqual(result.distribution["graveyard"]["count"], 1)
        self.assertGreater(result.silence_ratio, 0.99)
        self.assertEqual(result.verdict, "stalled")


if __name__ == "__main__":
    unittest.main()
