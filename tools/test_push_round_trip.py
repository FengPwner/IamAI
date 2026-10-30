#!/usr/bin/env python3
"""Tests for push_round_trip.py.

exercises the classifier, measure function, JSONL recorder, and history
reader. uses the live repo for integration-style checks and synthetic
data for pure-logic unit tests.

run:
    python3 -m pytest tools/test_push_round_trip.py -v
    python3 tools/test_push_round_trip.py
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import push_round_trip as prt  # noqa: E402


class TestClassify(unittest.TestCase):
    """test the latency classifier."""

    def test_healthy(self):
        code, label = prt.classify(600)
        self.assertEqual(code, 0)
        self.assertEqual(label, "healthy")

    def test_healthy_boundary(self):
        code, label = prt.classify(1199)
        self.assertEqual(code, 0)
        self.assertEqual(label, "healthy")

    def test_nominal(self):
        code, label = prt.classify(1200)
        self.assertEqual(code, 1)
        self.assertEqual(label, "nominal")

    def test_degraded(self):
        code, label = prt.classify(7200)
        self.assertEqual(code, 2)
        self.assertEqual(label, "degraded")

    def test_unknown(self):
        code, label = prt.classify(None)
        self.assertEqual(code, 3)
        self.assertEqual(label, "unknown")


class TestRecord(unittest.TestCase):
    """test the JSONL recording mechanism."""

    def test_record_and_read(self):
        with tempfile.TemporaryDirectory() as td:
            state_file = Path(td) / "test.jsonl"
            report = {
                "timestamp": "2026-10-29T19:00:00+0000",
                "unpushed": 2,
                "oldest_unpushed_age": 900,
                "severity": "healthy",
                "exit_code": 0,
            }
            prt.record(report, state_file=state_file)
            prt.record(report, state_file=state_file)

            history = prt.read_history(state_file=state_file)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["unpushed"], 2)

    def test_read_empty(self):
        with tempfile.TemporaryDirectory() as td:
            state_file = Path(td) / "nonexistent.jsonl"
            history = prt.read_history(state_file=state_file)
            self.assertEqual(history, [])

    def test_read_malformed_lines(self):
        with tempfile.TemporaryDirectory() as td:
            state_file = Path(td) / "mixed.jsonl"
            state_file.write_text(
                '{"ok": true}\n'
                'not valid json\n'
                '{"also_ok": true}\n',
                encoding="utf-8",
            )
            history = prt.read_history(state_file=state_file)
            self.assertEqual(len(history), 2)
            self.assertTrue(history[0].get("ok"))
            self.assertTrue(history[1].get("also_ok"))

    def test_read_last_n(self):
        with tempfile.TemporaryDirectory() as td:
            state_file = Path(td) / "long.jsonl"
            for i in range(20):
                report = {"seq": i}
                prt.record(report, state_file=state_file)
            history = prt.read_history(state_file=state_file, last_n=5)
            self.assertEqual(len(history), 5)
            self.assertEqual(history[-1]["seq"], 19)


class TestHumanSummary(unittest.TestCase):
    """test human-readable output."""

    def test_synced(self):
        report = {"unpushed": 0, "oldest_unpushed_age": 0, "severity": "healthy"}
        summary = prt.human_summary(report)
        self.assertIn("synced", summary)

    def test_unpushed_seconds(self):
        report = {"unpushed": 3, "oldest_unpushed_age": 45, "severity": "healthy"}
        summary = prt.human_summary(report)
        self.assertIn("3 unpushed", summary)
        self.assertIn("45s", summary)

    def test_unpushed_minutes(self):
        report = {"unpushed": 1, "oldest_unpushed_age": 300, "severity": "healthy"}
        summary = prt.human_summary(report)
        self.assertIn("5m", summary)

    def test_unpushed_hours(self):
        report = {"unpushed": 10, "oldest_unpushed_age": 7200, "severity": "degraded"}
        summary = prt.human_summary(report)
        self.assertIn("2h", summary)
        self.assertIn("degraded", summary)


class TestGetUnpushedCommits(unittest.TestCase):
    """integration test using the live repo (read-only)."""

    def test_returns_list(self):
        repo = Path(__file__).resolve().parent.parent
        commits = prt.get_unpushed_commits(repo=repo)
        # may be empty (synced) or non-empty; always a list
        self.assertIsInstance(commits, list)
        if commits:
            self.assertIn("sha", commits[0])
            self.assertIn("timestamp", commits[0])
            self.assertIsInstance(commits[0]["timestamp"], int)


class TestMeasure(unittest.TestCase):
    """integration test: measure should always return a valid report dict."""

    def test_measure_structure(self):
        repo = Path(__file__).resolve().parent.parent
        report = prt.measure(repo=repo)
        self.assertIn("timestamp", report)
        self.assertIn("unpushed", report)
        self.assertIn("severity", report)
        self.assertIn("exit_code", report)
        self.assertIn(report["severity"], ("healthy", "nominal", "degraded", "unknown"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
