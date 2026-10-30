#!/usr/bin/env python3
"""test_unpushed_count.py — tests for unpushed_count diagnostic.

covers severity classification boundaries, report structure, edge cases,
and live integration against the current repo state.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)

from unpushed_count import classify, count_unpushed, human_summary, measure


class TestClassify(unittest.TestCase):
    """severity classification boundary tests."""

    def test_zero_is_synced(self):
        code, label = classify(0)
        self.assertEqual(code, 0)
        self.assertEqual(label, "synced")

    def test_one_is_nominal(self):
        code, label = classify(1)
        self.assertEqual(code, 1)
        self.assertEqual(label, "nominal")

    def test_five_is_nominal(self):
        code, label = classify(5)
        self.assertEqual(code, 1)
        self.assertEqual(label, "nominal")

    def test_six_is_growing(self):
        code, label = classify(6)
        self.assertEqual(code, 2)
        self.assertEqual(label, "growing")

    def test_twenty_is_growing(self):
        code, label = classify(20)
        self.assertEqual(code, 2)
        self.assertEqual(label, "growing")

    def test_twenty_one_is_backlog(self):
        code, label = classify(21)
        self.assertEqual(code, 3)
        self.assertEqual(label, "backlog")

    def test_hundred_is_backlog(self):
        code, label = classify(100)
        self.assertEqual(code, 3)
        self.assertEqual(label, "backlog")

    def test_large_number_is_backlog(self):
        code, label = classify(99999)
        self.assertEqual(code, 3)
        self.assertEqual(label, "backlog")


class TestHumanSummary(unittest.TestCase):
    """human-readable output formatting."""

    def test_synced_message(self):
        report = {"unpushed": 0, "severity": "synced", "error": None}
        self.assertIn("synced", human_summary(report))

    def test_nominal_message(self):
        report = {"unpushed": 3, "severity": "nominal", "error": None}
        text = human_summary(report)
        self.assertIn("3", text)
        self.assertIn("nominal", text)

    def test_backlog_message(self):
        report = {"unpushed": 39, "severity": "backlog", "error": None}
        text = human_summary(report)
        self.assertIn("39", text)
        self.assertIn("backlog", text)

    def test_error_message(self):
        report = {"unpushed": None, "severity": "unknown", "error": "no remote"}
        text = human_summary(report)
        self.assertIn("cannot determine", text)
        self.assertIn("no remote", text)


class TestMeasure(unittest.TestCase):
    """integration tests against the live repo."""

    def test_measure_returns_dict(self):
        report = measure()
        self.assertIsInstance(report, dict)
        self.assertIn("timestamp", report)
        self.assertIn("unpushed", report)
        self.assertIn("severity", report)
        self.assertIn("exit_code", report)

    def test_measure_has_error_key(self):
        report = measure()
        self.assertIn("error", report)

    def test_measure_unpushed_is_int_or_none(self):
        report = measure()
        self.assertTrue(
            isinstance(report["unpushed"], int) or report["unpushed"] is None
        )

    def test_measure_severity_is_valid(self):
        report = measure()
        valid = {"synced", "nominal", "growing", "backlog", "unknown"}
        self.assertIn(report["severity"], valid)

    def test_measure_exit_code_range(self):
        report = measure()
        self.assertIn(report["exit_code"], range(5))


class TestCountUnpushed(unittest.TestCase):
    """git rev-list integration and edge cases."""

    def test_count_returns_int_or_none(self):
        count, error = count_unpushed()
        if error is None:
            self.assertIsInstance(count, int)
            self.assertGreaterEqual(count, 0)

    def test_nonexistent_repo_returns_none(self):
        count, error = count_unpushed("/nonexistent/path")
        self.assertIsNone(count)
        self.assertIsNotNone(error)

    def test_empty_dir_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            count, error = count_unpushed(tmpdir)
            self.assertIsNone(count)

    def test_live_repo_has_unpushed(self):
        """the current repo is known to have unpushed commits."""
        repo = os.path.dirname(TOOLS)
        count, error = count_unpushed(repo)
        if error is None:
            self.assertGreater(count, 0, "expected unpushed commits in live repo")


class TestJsonOutput(unittest.TestCase):
    """JSON output mode produces valid parseable output."""

    def test_json_mode(self):
        report = measure()
        serialized = json.dumps(report)
        parsed = json.loads(serialized)
        self.assertEqual(parsed["severity"], report["severity"])
        self.assertEqual(parsed["unpushed"], report["unpushed"])


if __name__ == "__main__":
    unittest.main()
