"""Tests for iamai.writer_streak module.

Covers edge cases (empty, all-True, all-False), streak counting,
resilience arithmetic, and verdict classification.
"""

import unittest

from iamai.writer_streak import (
    current_streak,
    longest_streak,
    streak_stats,
    streak_verdict,
)


class TestCurrentStreak(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(current_streak([]), 0)

    def test_single_true(self):
        self.assertEqual(current_streak([True]), 1)

    def test_single_false(self):
        self.assertEqual(current_streak([False]), 0)

    def test_trailing_successes(self):
        self.assertEqual(current_streak([False, True, True, True]), 3)

    def test_trailing_failure(self):
        self.assertEqual(current_streak([True, True, False]), 0)

    def test_all_true(self):
        self.assertEqual(current_streak([True] * 10), 10)

    def test_all_false(self):
        self.assertEqual(current_streak([False] * 5), 0)

    def test_alternating(self):
        self.assertEqual(current_streak([True, False, True, False]), 0)

    def test_long_streak(self):
        self.assertEqual(current_streak([False] + [True] * 100), 100)


class TestLongestStreak(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(longest_streak([]), 0)

    def test_all_true(self):
        self.assertEqual(longest_streak([True] * 7), 7)

    def test_all_false(self):
        self.assertEqual(longest_streak([False] * 4), 0)

    def test_middle_streak_longest(self):
        # streaks: 2, 5, 1 -> longest is 5
        self.assertEqual(
            longest_streak([True, True, False, True, True, True, True, True, False, True]),
            5,
        )

    def test_first_streak_longest(self):
        self.assertEqual(
            longest_streak([True, True, True, True, False, True, True]), 4
        )

    def test_last_streak_longest(self):
        self.assertEqual(
            longest_streak([True, False, True, True, True, True]), 4
        )

    def test_single_element(self):
        self.assertEqual(longest_streak([True]), 1)
        self.assertEqual(longest_streak([False]), 0)


class TestStreakStats(unittest.TestCase):
    def test_empty(self):
        stats = streak_stats([])
        self.assertEqual(stats["current"], 0)
        self.assertEqual(stats["longest"], 0)
        self.assertEqual(stats["total_ticks"], 0)
        self.assertEqual(stats["successes"], 0)
        self.assertEqual(stats["failures"], 0)
        self.assertEqual(stats["success_rate"], 0.0)
        self.assertEqual(stats["resilience"], 1.0)  # no data = assume healthy
        self.assertEqual(stats["streaks"], [])

    def test_all_success(self):
        stats = streak_stats([True] * 5)
        self.assertEqual(stats["current"], 5)
        self.assertEqual(stats["longest"], 5)
        self.assertEqual(stats["total_ticks"], 5)
        self.assertEqual(stats["successes"], 5)
        self.assertEqual(stats["failures"], 0)
        self.assertEqual(stats["success_rate"], 1.0)
        self.assertEqual(stats["resilience"], 1.0)
        self.assertEqual(stats["streaks"], [5])

    def test_all_failure(self):
        stats = streak_stats([False] * 3)
        self.assertEqual(stats["current"], 0)
        self.assertEqual(stats["longest"], 0)
        self.assertEqual(stats["failures"], 3)
        self.assertEqual(stats["success_rate"], 0.0)
        self.assertEqual(stats["resilience"], 0.0)
        self.assertEqual(stats["streaks"], [])

    def test_mixed(self):
        outcomes = [True, True, True, False, True, True, True, True, True]
        stats = streak_stats(outcomes)
        self.assertEqual(stats["current"], 5)
        self.assertEqual(stats["longest"], 5)
        self.assertEqual(stats["total_ticks"], 9)
        self.assertEqual(stats["successes"], 8)
        self.assertEqual(stats["failures"], 1)
        self.assertAlmostEqual(stats["success_rate"], 0.8889, places=4)
        self.assertEqual(stats["resilience"], 1.0)  # current == longest
        self.assertEqual(stats["streaks"], [3, 5])

    def test_resilience_low(self):
        # Long historical streak, short current one
        outcomes = [True] * 100 + [False] + [True, True]
        stats = streak_stats(outcomes)
        self.assertEqual(stats["current"], 2)
        self.assertEqual(stats["longest"], 100)
        self.assertEqual(stats["resilience"], 0.02)

    def test_multiple_streaks(self):
        outcomes = [True, True, False, True, True, True, False, True]
        stats = streak_stats(outcomes)
        self.assertEqual(stats["streaks"], [2, 3, 1])
        self.assertEqual(stats["current"], 1)
        self.assertEqual(stats["longest"], 3)

    def test_alternating(self):
        outcomes = [True, False, True, False, True, False]
        stats = streak_stats(outcomes)
        self.assertEqual(stats["current"], 0)
        self.assertEqual(stats["longest"], 1)
        self.assertEqual(stats["streaks"], [1, 1, 1])
        self.assertEqual(stats["success_rate"], 0.5)


class TestStreakVerdict(unittest.TestCase):
    def test_dead(self):
        self.assertEqual(
            streak_verdict({"current": 0, "longest": 0, "failures": 5}), "dead"
        )

    def test_solid_high_resilience(self):
        self.assertEqual(
            streak_verdict({"current": 50, "longest": 60, "failures": 2, "resilience": 0.833}),
            "solid",
        )

    def test_recovering_low_resilience(self):
        self.assertEqual(
            streak_verdict({"current": 3, "longest": 100, "failures": 10, "resilience": 0.03}),
            "recovering",
        )

    def test_fragile_zero_current(self):
        self.assertEqual(
            streak_verdict({"current": 0, "longest": 50, "failures": 3, "resilience": 0.0}),
            "fragile",
        )

    def test_empty_stats(self):
        self.assertEqual(streak_verdict({}), "dead")

    def test_solid_exactly_at_threshold(self):
        self.assertEqual(
            streak_verdict({"current": 10, "longest": 10, "failures": 0, "resilience": 1.0}),
            "solid",
        )

    def test_recovering_below_threshold(self):
        self.assertEqual(
            streak_verdict({"current": 5, "longest": 10, "failures": 1, "resilience": 0.5}),
            "recovering",
        )

    def test_custom_threshold(self):
        # With threshold=3, a streak of 5 is solid
        self.assertEqual(
            streak_verdict({"current": 5, "longest": 5, "failures": 0, "resilience": 1.0},
                           healthy_threshold=3),
            "solid",
        )


if __name__ == "__main__":
    unittest.main()
