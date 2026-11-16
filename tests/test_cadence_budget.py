"""Tests for iamai.cadence_budget — cadence cycle budget tracker.

written by Qwen, caretaker visit 669, 2026-11-17.
"""

import time
import unittest

from iamai.cadence_budget import (
    BudgetSnapshot,
    budget_snapshot,
    cycle_report,
    project_completion,
)


class TestBudgetSnapshot(unittest.TestCase):
    """BudgetSnapshot dataclass properties."""

    def test_fresh_cycle(self):
        snap = BudgetSnapshot(interval=600, cycle_start=1000, now=1050)
        self.assertAlmostEqual(snap.elapsed, 50.0)
        self.assertAlmostEqual(snap.remaining, 550.0)
        self.assertAlmostEqual(snap.fraction_used, 50 / 600)
        self.assertFalse(snap.is_overdue)
        self.assertAlmostEqual(snap.overdue_by, 0.0)
        self.assertEqual(snap.pace_label, "fresh")

    def test_mid_cycle(self):
        snap = BudgetSnapshot(interval=600, cycle_start=1000, now=1350)
        self.assertAlmostEqual(snap.fraction_used, 350 / 600)
        self.assertEqual(snap.pace_label, "mid-cycle")

    def test_approaching_deadline(self):
        snap = BudgetSnapshot(interval=600, cycle_start=1000, now=1500)
        self.assertAlmostEqual(snap.fraction_used, 500 / 600)
        self.assertEqual(snap.pace_label, "approaching")

    def test_overdue(self):
        snap = BudgetSnapshot(interval=600, cycle_start=1000, now=1700)
        self.assertTrue(snap.is_overdue)
        self.assertAlmostEqual(snap.overdue_by, 100.0)
        self.assertAlmostEqual(snap.remaining, 0.0)
        self.assertEqual(snap.pace_label, "overdue")

    def test_zero_interval(self):
        snap = BudgetSnapshot(interval=0, cycle_start=1000, now=1050)
        self.assertAlmostEqual(snap.fraction_used, 1.0)

    def test_stroke_deficit(self):
        snap = BudgetSnapshot(
            interval=600, cycle_start=1000, now=1300,
            strokes_in_cycle=3, expected_strokes=10,
        )
        self.assertEqual(snap.stroke_deficit, 7)

    def test_no_deficit_when_ahead(self):
        snap = BudgetSnapshot(
            interval=600, cycle_start=1000, now=1300,
            strokes_in_cycle=15, expected_strokes=10,
        )
        self.assertEqual(snap.stroke_deficit, 0)

    def test_elapsed_clamped_to_zero(self):
        # now < cycle_start (clock skew)
        snap = BudgetSnapshot(interval=600, cycle_start=2000, now=1000)
        self.assertAlmostEqual(snap.elapsed, 0.0)
        self.assertAlmostEqual(snap.remaining, 600.0)


class TestBudgetSnapshotFactory(unittest.TestCase):
    """budget_snapshot() factory function."""

    def test_defaults_now(self):
        before = time.time()
        snap = budget_snapshot(interval=600, cycle_start=before - 100)
        after = time.time()
        self.assertGreaterEqual(snap.now, before)
        self.assertLessEqual(snap.now, after)

    def test_explicit_now(self):
        snap = budget_snapshot(600, 1000, now=1200)
        self.assertAlmostEqual(snap.elapsed, 200.0)

    def test_expected_strokes_from_rate(self):
        snap = budget_snapshot(
            interval=600, cycle_start=1000, now=1300,
            strokes_in_cycle=5, stroke_rate=0.05,  # 1 stroke per 20s
        )
        # 300s elapsed * 0.05 = 15 expected
        self.assertEqual(snap.expected_strokes, 15)
        self.assertEqual(snap.stroke_deficit, 10)

    def test_zero_rate_gives_zero_expected(self):
        snap = budget_snapshot(600, 1000, now=1300, stroke_rate=0.0)
        self.assertEqual(snap.expected_strokes, 0)


class TestProjectCompletion(unittest.TestCase):
    """project_completion() — ETA and on-time prediction."""

    def test_insufficient_data(self):
        eta, on_time = project_completion(600, 1000, [1050], now=1100)
        # falls back to deadline
        self.assertAlmostEqual(eta, 1600.0)
        self.assertTrue(on_time)

    def test_no_strokes(self):
        eta, on_time = project_completion(600, 1000, [], now=1100)
        self.assertAlmostEqual(eta, 1600.0)
        self.assertTrue(on_time)

    def test_regular_strokes_on_time(self):
        # strokes every 15s, cycle started at 1000, now=1500
        stroke_times = [1000 + 15 * i for i in range(34)]  # 34 strokes
        eta, on_time = project_completion(600, 1000, stroke_times, now=1500)
        # median gap = 15s, need 1 more stroke -> eta = 1515
        self.assertAlmostEqual(eta, 1515.0)
        self.assertTrue(on_time)  # 1515 < 1600

    def test_slow_strokes_may_miss(self):
        # strokes every 120s, cycle 600s, now at 550s into cycle
        stroke_times = [1000 + 120 * i for i in range(5)]  # 5 strokes
        eta, on_time = project_completion(600, 1000, stroke_times, now=1550)
        # median gap = 120s, need 1 more -> eta = 1670
        self.assertAlmostEqual(eta, 1670.0)
        self.assertFalse(on_time)  # 1670 > 1600

    def test_median_gap_robust_to_outlier(self):
        # mostly 20s gaps with one 200s outlier
        times = [1000, 1020, 1040, 1060, 1260, 1280, 1300]
        eta, on_time = project_completion(600, 1000, times, now=1300)
        # sorted gaps: [20,20,20,20,20,200] -> median index 3 -> 20
        self.assertAlmostEqual(eta, 1320.0)
        self.assertTrue(on_time)

    def test_zero_gap_fallback(self):
        # duplicate timestamps -> zero gaps
        times = [1000, 1000, 1000, 1000]
        eta, on_time = project_completion(600, 1000, times, now=1100)
        # median_gap clamped to 1.0
        self.assertAlmostEqual(eta, 1101.0)
        self.assertTrue(on_time)


class TestCycleReport(unittest.TestCase):
    """cycle_report() — human-readable one-liner."""

    def test_fresh_report(self):
        report = cycle_report(600, 1000, now=1050)
        self.assertIn("fresh", report)
        self.assertIn("50s/600s", report)

    def test_overdue_report(self):
        report = cycle_report(600, 1000, now=1700)
        self.assertIn("OVERDUE", report)
        self.assertIn("overdue", report)

    def test_deficit_report(self):
        report = cycle_report(
            600, 1000, now=1300,
            strokes_in_cycle=2, stroke_rate=0.05,
        )
        self.assertIn("deficit", report)

    def test_no_deficit_no_deficit_word(self):
        report = cycle_report(
            600, 1000, now=1300,
            strokes_in_cycle=50, stroke_rate=0.05,
        )
        self.assertNotIn("deficit", report)

    def test_report_has_percentage(self):
        report = cycle_report(600, 1000, now=1300)
        self.assertIn("%", report)


if __name__ == "__main__":
    unittest.main()
