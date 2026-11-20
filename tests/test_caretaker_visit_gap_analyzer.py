#!/usr/bin/env python3
"""tests for caretaker_visit_gap_analyzer.py — 18 tests covering gap logic,
classification, trend detection, and edge cases."""

import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from caretaker_visit_gap_analyzer import (
    Visit,
    GapReport,
    compute_gaps,
    _gap_hours,
    _linear_regression,
    classify_trend,
    classify_reliability,
    analyze_gaps,
    format_report,
)


def _make_visit(number: int, hours_offset: float) -> Visit:
    """Helper: create a Visit at a fixed offset from epoch."""
    base = datetime(2026, 11, 1, tzinfo=timezone.utc)
    return Visit(
        number=number,
        timestamp=base + timedelta(hours=hours_offset),
        commit_hash=f"abc{number:03d}",
        message=f"caretaker visit {number}",
    )


class TestComputeGaps(unittest.TestCase):
    """Test the gap computation logic."""

    def test_two_visits(self):
        v = [_make_visit(1, 0), _make_visit(2, 3)]
        gaps = compute_gaps(v)
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0].total_seconds() / 3600, 3.0)

    def test_multiple_visits(self):
        v = [_make_visit(i, i * 2) for i in range(1, 6)]
        gaps = compute_gaps(v)
        self.assertEqual(len(gaps), 4)
        for g in gaps:
            self.assertAlmostEqual(g.total_seconds() / 3600, 2.0)

    def test_single_visit(self):
        v = [_make_visit(1, 0)]
        gaps = compute_gaps(v)
        self.assertEqual(gaps, [])

    def test_irregular_gaps(self):
        v = [
            _make_visit(1, 0),
            _make_visit(2, 1),
            _make_visit(3, 5),
            _make_visit(4, 6),
        ]
        gaps = compute_gaps(v)
        hours = _gap_hours(gaps)
        self.assertAlmostEqual(hours, [1.0, 4.0, 1.0])


class TestGapHours(unittest.TestCase):
    """Test timedelta-to-hours conversion."""

    def test_conversion(self):
        gaps = [timedelta(hours=2), timedelta(minutes=30), timedelta(days=1)]
        hours = _gap_hours(gaps)
        self.assertAlmostEqual(hours, [2.0, 0.5, 24.0])

    def test_empty(self):
        self.assertEqual(_gap_hours([]), [])


class TestLinearRegression(unittest.TestCase):
    """Test the OLS slope computation."""

    def test_positive_slope(self):
        xs = [0, 1, 2, 3, 4]
        ys = [1, 3, 5, 7, 9]  # slope = 2
        slope = _linear_regression(xs, ys)
        self.assertAlmostEqual(slope, 2.0)

    def test_negative_slope(self):
        xs = [0, 1, 2, 3, 4]
        ys = [10, 8, 6, 4, 2]  # slope = -2
        slope = _linear_regression(xs, ys)
        self.assertAlmostEqual(slope, -2.0)

    def test_flat(self):
        xs = [0, 1, 2, 3]
        ys = [5, 5, 5, 5]
        slope = _linear_regression(xs, ys)
        self.assertAlmostEqual(slope, 0.0)

    def test_insufficient_data(self):
        self.assertAlmostEqual(_linear_regression([1], [2]), 0.0)
        self.assertAlmostEqual(_linear_regression([], []), 0.0)


class TestClassifyTrend(unittest.TestCase):
    """Test trend classification from slope values."""

    def test_more_frequent(self):
        self.assertEqual(classify_trend(-0.05), "more_frequent")

    def test_less_frequent(self):
        self.assertEqual(classify_trend(0.05), "less_frequent")

    def test_stable(self):
        self.assertEqual(classify_trend(0.001), "stable")

    def test_custom_threshold(self):
        self.assertEqual(classify_trend(-0.1, threshold=0.2), "stable")
        self.assertEqual(classify_trend(-0.3, threshold=0.2), "more_frequent")


class TestClassifyReliability(unittest.TestCase):
    """Test reliability classification from gap statistics."""

    def test_reliable(self):
        self.assertEqual(classify_reliability(1.0, 8.0), "reliable")

    def test_attentive(self):
        self.assertEqual(classify_reliability(4.0, 20.0), "attentive")

    def test_sporadic(self):
        self.assertEqual(classify_reliability(12.0, 48.0), "sporadic")

    def test_absent(self):
        self.assertEqual(classify_reliability(48.0, 200.0), "absent")

    def test_boundary_reliable(self):
        # median < 2, max < 12 → reliable
        self.assertEqual(classify_reliability(1.99, 11.99), "reliable")

    def test_boundary_attentive(self):
        # median 2+, max < 24 → attentive
        self.assertEqual(classify_reliability(2.0, 12.0), "attentive")


class TestAnalyzeGaps(unittest.TestCase):
    """Integration test for the full analysis pipeline."""

    def test_basic_report(self):
        visits = [_make_visit(i, i * 4) for i in range(1, 11)]
        report = analyze_gaps(visits)
        self.assertEqual(report.total_visits, 10)
        self.assertAlmostEqual(report.gap_mean_hours, 4.0)
        self.assertAlmostEqual(report.gap_median_hours, 4.0)
        self.assertAlmostEqual(report.gap_min_hours, 4.0)
        self.assertAlmostEqual(report.gap_max_hours, 4.0)
        self.assertIn(report.reliability, ["reliable", "attentive", "sporadic", "absent"])

    def test_insufficient_data(self):
        with self.assertRaises(ValueError):
            analyze_gaps([_make_visit(1, 0)])

    def test_longest_gap_record(self):
        visits = [
            _make_visit(1, 0),
            _make_visit(2, 1),
            _make_visit(3, 2),
            _make_visit(4, 20),  # big gap here
            _make_visit(5, 21),
        ]
        report = analyze_gaps(visits)
        self.assertIn("visit 3", report.longest_gap_record)
        self.assertIn("visit 4", report.longest_gap_record)

    def test_visits_per_day(self):
        # 10 visits over 36 hours = 10 / 1.5 days ≈ 6.67/day
        visits = [_make_visit(i, i * 4) for i in range(1, 11)]
        report = analyze_gaps(visits)
        self.assertAlmostEqual(report.visits_per_day, 6.67, places=1)


class TestFormatReport(unittest.TestCase):
    """Test that the human-readable output is well-formed."""

    def test_contains_key_fields(self):
        visits = [_make_visit(i, i * 2) for i in range(1, 6)]
        report = analyze_gaps(visits)
        text = format_report(report)
        self.assertIn("caretaker visit gap analysis", text)
        self.assertIn("gap min", text)
        self.assertIn("reliability", text)
        self.assertIn("trend", text)


if __name__ == "__main__":
    unittest.main()
