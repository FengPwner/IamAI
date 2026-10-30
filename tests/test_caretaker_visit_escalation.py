"""test_caretaker_visit_escalation.py — verify escalation scoring logic.

Tests the three public functions: escalation_score, needs_escalation,
and escalation_report.  Pure logic, no filesystem dependencies.
"""

import sys
import unittest

sys.path.insert(0, ".")
from iamai.caretaker_visit_escalation import (
    escalation_score,
    escalation_report,
    needs_escalation,
)


class TestEscalationScore(unittest.TestCase):
    """Test escalation_score with various action patterns."""

    def test_empty_list(self):
        result = escalation_score([])
        self.assertEqual(result["level"], "stable")
        self.assertEqual(result["streak"], 0)
        self.assertIsNone(result["action"])
        self.assertEqual(result["total"], 0)

    def test_single_action(self):
        result = escalation_score(["restart"])
        self.assertEqual(result["level"], "stable")
        self.assertEqual(result["streak"], 1)
        self.assertEqual(result["action"], "restart")

    def test_two_same_actions(self):
        result = escalation_score(["commit", "restart", "restart"])
        self.assertEqual(result["level"], "repeating")
        self.assertEqual(result["streak"], 2)
        self.assertEqual(result["action"], "restart")

    def test_four_same_actions_is_stuck(self):
        actions = ["commit", "restart", "restart", "restart", "restart"]
        result = escalation_score(actions)
        self.assertEqual(result["level"], "stuck")
        self.assertEqual(result["streak"], 4)

    def test_six_same_actions_is_escalate(self):
        actions = ["restart"] * 6
        result = escalation_score(actions)
        self.assertEqual(result["level"], "escalate")
        self.assertEqual(result["streak"], 6)
        self.assertIn("human intervention", result["summary"])

    def test_varied_actions_is_stable(self):
        actions = ["restart", "commit", "push", "noop", "fix"]
        result = escalation_score(actions)
        self.assertEqual(result["level"], "stable")
        self.assertEqual(result["streak"], 1)
        self.assertEqual(result["action"], "fix")

    def test_streak_broken_by_different_action(self):
        actions = ["restart", "restart", "restart", "commit", "push"]
        result = escalation_score(actions)
        self.assertEqual(result["level"], "stable")
        self.assertEqual(result["streak"], 1)

    def test_summary_for_stable(self):
        result = escalation_score(["commit", "restart"])
        self.assertIn("varied", result["summary"])

    def test_summary_for_repeating(self):
        result = escalation_score(["restart", "restart"])
        self.assertIn("repeating", result["summary"])

    def test_total_count(self):
        actions = ["a", "b", "c", "d", "e"]
        result = escalation_score(actions)
        self.assertEqual(result["total"], 5)


class TestNeedsEscalation(unittest.TestCase):
    """Test the quick boolean check."""

    def test_empty_returns_false(self):
        self.assertFalse(needs_escalation([]))

    def test_below_threshold_returns_false(self):
        actions = ["restart"] * 5
        self.assertFalse(needs_escalation(actions))

    def test_at_threshold_returns_true(self):
        actions = ["restart"] * 6
        self.assertTrue(needs_escalation(actions))

    def test_above_threshold_returns_true(self):
        actions = ["restart"] * 10
        self.assertTrue(needs_escalation(actions))

    def test_custom_threshold(self):
        actions = ["commit"] * 4
        self.assertTrue(needs_escalation(actions, threshold=4))
        self.assertFalse(needs_escalation(actions, threshold=5))

    def test_streak_broken_does_not_trigger(self):
        actions = ["restart"] * 6 + ["commit"]
        self.assertFalse(needs_escalation(actions))


class TestEscalationReport(unittest.TestCase):
    """Test the full report with history."""

    def test_empty_history(self):
        result = escalation_report([])
        self.assertEqual(result["history"], [])
        self.assertEqual(result["level"], "stable")

    def test_history_length_matches_actions(self):
        actions = ["restart", "commit", "commit", "restart"]
        result = escalation_report(actions)
        self.assertEqual(len(result["history"]), 4)

    def test_history_streaks(self):
        actions = ["restart", "restart", "commit", "commit", "commit"]
        result = escalation_report(actions)
        streaks = [h["streak"] for h in result["history"]]
        self.assertEqual(streaks, [1, 2, 1, 2, 3])

    def test_report_includes_score_fields(self):
        result = escalation_report(["restart", "restart", "restart"])
        self.assertIn("level", result)
        self.assertIn("streak", result)
        self.assertIn("action", result)
        self.assertIn("summary", result)


if __name__ == "__main__":
    unittest.main()
