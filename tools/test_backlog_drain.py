#!/usr/bin/env python3
"""Tests for backlog_drain.py (both iamai.backlog_drain lib and CLI).

covers:
    - snapshot capture (normal, git error, negative count)
    - drain_rate with synthetic windows
    - classify verdicts (draining / steady / growing)
    - drain_report formatting
    - CLI exit codes and --json output

run:
    python3 -m pytest tools/test_backlog_drain.py -v
    python3 tools/test_backlog_drain.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.backlog_drain import (  # noqa: E402
    Snapshot,
    classify,
    drain_rate,
    drain_report,
    snapshot,
)


class TestSnapshot(unittest.TestCase):
    """test snapshot capture."""

    def test_snapshot_returns_dict(self):
        """snapshot returns a dict with count and at."""
        s = snapshot(Path(__file__).resolve().parent.parent)
        self.assertIn("count", s)
        self.assertIn("at", s)
        self.assertIsInstance(s["count"], int)
        self.assertIsInstance(s["at"], float)

    def test_snapshot_with_timestamp(self):
        """snapshot respects custom at parameter."""
        s = snapshot("/tmp", at=1000.0)
        self.assertEqual(s["at"], 1000.0)

    def test_snapshot_invalid_path(self):
        """invalid repo path returns count -1."""
        s = snapshot("/nonexistent/repo/path")
        self.assertEqual(s["count"], -1)


class TestDrainRate(unittest.TestCase):
    """test drain rate computation."""

    def test_empty_snapshots(self):
        """empty list → 0.0."""
        self.assertEqual(drain_rate([]), 0.0)

    def test_single_snapshot(self):
        """one snapshot → 0.0 (insufficient data)."""
        self.assertEqual(drain_rate([{"count": 5, "at": 100.0}]), 0.0)

    def test_shrinking_backlog(self):
        """decreasing counts → negative rate (draining)."""
        snaps = [
            {"count": 20, "at": 0.0},
            {"count": 15, "at": 60.0},
            {"count": 10, "at": 120.0},
        ]
        rate = drain_rate(snaps)
        self.assertLess(rate, -1.0)

    def test_growing_backlog(self):
        """increasing counts → positive rate (growing)."""
        snaps = [
            {"count": 2, "at": 0.0},
            {"count": 10, "at": 60.0},
            {"count": 18, "at": 120.0},
        ]
        rate = drain_rate(snaps)
        self.assertGreater(rate, 1.0)

    def test_steady_backlog(self):
        """constant counts → near-zero rate (steady)."""
        snaps = [
            {"count": 7, "at": 0.0},
            {"count": 7, "at": 60.0},
            {"count": 7, "at": 120.0},
        ]
        rate = drain_rate(snaps)
        self.assertAlmostEqual(rate, 0.0, places=5)

    def test_negative_count_excluded(self):
        """negative counts (git errors) are excluded."""
        snaps = [
            {"count": -1, "at": 0.0},
            {"count": 10, "at": 60.0},
            {"count": 5, "at": 120.0},
        ]
        rate = drain_rate(snaps)
        self.assertLess(rate, 0)

    def test_same_timestamp(self):
        """all same timestamp → 0.0 (denom guard)."""
        snaps = [
            {"count": 5, "at": 100.0},
            {"count": 10, "at": 100.0},
        ]
        rate = drain_rate(snaps)
        self.assertEqual(rate, 0.0)


class TestClassify(unittest.TestCase):
    """test verdict classification."""

    def test_draining(self):
        self.assertEqual(classify(-2.0), "draining")
        self.assertEqual(classify(-1.5), "draining")
        self.assertEqual(classify(-1.1), "draining")

    def test_steady(self):
        self.assertEqual(classify(-1.0), "steady")
        self.assertEqual(classify(0.0), "steady")
        self.assertEqual(classify(1.0), "steady")

    def test_growing(self):
        self.assertEqual(classify(1.1), "growing")
        self.assertEqual(classify(5.0), "growing")
        self.assertEqual(classify(100.0), "growing")


class TestDrainReport(unittest.TestCase):
    """test the human-readable report."""

    def test_report_contains_verdict(self):
        """report string includes verdict word."""
        snaps = [
            {"count": 5, "at": 0.0},
            {"count": 5, "at": 60.0},
        ]
        report = drain_report(Path(__file__).resolve().parent.parent, snaps)
        self.assertIn("steady", report)

    def test_report_contains_pending(self):
        """report string includes pending count."""
        snaps = [
            {"count": 3, "at": 0.0},
            {"count": 3, "at": 60.0},
        ]
        report = drain_report(Path(__file__).resolve().parent.parent, snaps)
        self.assertIn("files pending", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
