#!/usr/bin/env python3
"""Tests for repo_immune_response.py.

exercises the score computation, grading, trend analysis, snapshot
structure, JSONL recording, and human summary. uses synthetic data
for pure-logic unit tests and the live repo for integration checks.

run:
    python3 -m pytest tools/test_repo_immune_response.py -v
    python3 tools/test_repo_immune_response.py
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import repo_immune_response as rir  # noqa: E402


class TestComputeScore(unittest.TestCase):
    """test the immune score computation."""

    def test_instant_resolution(self):
        """0 seconds → perfect score 100."""
        self.assertEqual(rir.compute_score(0), 100)

    def test_five_minutes(self):
        """300s (5 min) → score 90."""
        self.assertEqual(rir.compute_score(300), 90)

    def test_ten_minutes(self):
        """600s (10 min) → score 80."""
        self.assertEqual(rir.compute_score(600), 80)

    def test_thirty_minutes(self):
        """1800s (30 min) → score 40."""
        self.assertEqual(rir.compute_score(1800), 40)

    def test_fifty_minutes(self):
        """3000s (50 min) → score 0 (floored)."""
        self.assertEqual(rir.compute_score(3000), 0)

    def test_one_hour(self):
        """3600s → score 0 (well past the floor)."""
        self.assertEqual(rir.compute_score(3600), 0)

    def test_none_input(self):
        """None → score 0."""
        self.assertEqual(rir.compute_score(None), 0)

    def test_negative_input(self):
        """negative → score 0."""
        self.assertEqual(rir.compute_score(-100), 0)

    def test_one_minute(self):
        """60s → score 98."""
        self.assertEqual(rir.compute_score(60), 98)

    def test_fifteen_minutes(self):
        """900s → score 70."""
        self.assertEqual(rir.compute_score(900), 70)


class TestGrade(unittest.TestCase):
    """test the qualitative grading."""

    def test_robust(self):
        self.assertEqual(rir.grade(100), "robust")
        self.assertEqual(rir.grade(80), "robust")

    def test_adequate(self):
        self.assertEqual(rir.grade(79), "adequate")
        self.assertEqual(rir.grade(60), "adequate")

    def test_sluggish(self):
        self.assertEqual(rir.grade(59), "sluggish")
        self.assertEqual(rir.grade(40), "sluggish")

    def test_immunocompromised(self):
        self.assertEqual(rir.grade(39), "immunocompromised")
        self.assertEqual(rir.grade(0), "immunocompromised")


class TestClassifyResolution(unittest.TestCase):
    """test the combined classify_resolution function."""

    def test_fast_resolution(self):
        score, label = rir.classify_resolution(120)
        self.assertEqual(score, 96)
        self.assertEqual(label, "robust")

    def test_slow_resolution(self):
        score, label = rir.classify_resolution(2400)
        self.assertEqual(score, 20)
        self.assertEqual(label, "immunocompromised")

    def test_no_anomaly(self):
        score, label = rir.classify_resolution(0)
        self.assertEqual(score, 100)
        self.assertEqual(label, "robust")


class TestTrend(unittest.TestCase):
    """test the trend analysis over a history of snapshots."""

    def test_improving(self):
        history = [
            {"immune_score": 40},
            {"immune_score": 45},
            {"immune_score": 50},
            {"immune_score": 80},
            {"immune_score": 85},
            {"immune_score": 90},
        ]
        self.assertEqual(rir.trend(history), "improving")

    def test_declining(self):
        history = [
            {"immune_score": 95},
            {"immune_score": 90},
            {"immune_score": 85},
            {"immune_score": 50},
            {"immune_score": 45},
            {"immune_score": 40},
        ]
        self.assertEqual(rir.trend(history), "declining")

    def test_stable(self):
        history = [
            {"immune_score": 82},
            {"immune_score": 80},
            {"immune_score": 81},
            {"immune_score": 79},
            {"immune_score": 80},
            {"immune_score": 81},
        ]
        self.assertEqual(rir.trend(history), "stable")

    def test_insufficient_data(self):
        self.assertEqual(rir.trend([]), "insufficient_data")
        self.assertEqual(rir.trend([{"immune_score": 80}]), "insufficient_data")

    def test_two_entries_improving(self):
        history = [{"immune_score": 50}, {"immune_score": 90}]
        self.assertEqual(rir.trend(history), "improving")

    def test_two_entries_declining(self):
        history = [{"immune_score": 90}, {"immune_score": 50}]
        self.assertEqual(rir.trend(history), "declining")


class TestRecord(unittest.TestCase):
    """test JSONL recording and history reading."""

    def test_record_and_read(self):
        with tempfile.TemporaryDirectory() as td:
            sf = Path(td) / "test_immune.jsonl"
            snap = {
                "timestamp": "2026-10-29T21:00:00+0000",
                "immune_score": 85,
                "grade": "robust",
                "active_anomalies": 0,
            }
            rir.record(snap, state_file=sf)
            rir.record(snap, state_file=sf)
            history = rir.read_history(state_file=sf)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["immune_score"], 85)

    def test_read_empty(self):
        with tempfile.TemporaryDirectory() as td:
            sf = Path(td) / "nonexistent.jsonl"
            self.assertEqual(rir.read_history(state_file=sf), [])

    def test_read_malformed_lines(self):
        with tempfile.TemporaryDirectory() as td:
            sf = Path(td) / "mixed.jsonl"
            sf.write_text(
                '{"immune_score": 80}\n'
                "bad json line\n"
                '{"immune_score": 70}\n',
                encoding="utf-8",
            )
            history = rir.read_history(state_file=sf)
            self.assertEqual(len(history), 2)

    def test_read_last_n(self):
        with tempfile.TemporaryDirectory() as td:
            sf = Path(td) / "long.jsonl"
            for i in range(25):
                rir.record({"seq": i, "immune_score": i * 4}, state_file=sf)
            history = rir.read_history(state_file=sf, last_n=5)
            self.assertEqual(len(history), 5)
            self.assertEqual(history[-1]["seq"], 24)


class TestHumanSummary(unittest.TestCase):
    """test human-readable output formatting."""

    def test_no_anomalies(self):
        snap = {
            "immune_score": 100,
            "grade": "robust",
            "active_anomalies": 0,
            "worst_resolution_s": 0,
        }
        summary = rir.human_summary(snap)
        self.assertIn("100/100", summary)
        self.assertIn("no active anomalies", summary)

    def test_with_anomalies_seconds(self):
        snap = {
            "immune_score": 95,
            "grade": "robust",
            "active_anomalies": 2,
            "worst_resolution_s": 45,
        }
        summary = rir.human_summary(snap)
        self.assertIn("2 active anomaly", summary)
        self.assertIn("45s", summary)

    def test_with_anomalies_minutes(self):
        snap = {
            "immune_score": 70,
            "grade": "adequate",
            "active_anomalies": 1,
            "worst_resolution_s": 900,
        }
        summary = rir.human_summary(snap)
        self.assertIn("15m", summary)

    def test_with_anomalies_hours(self):
        snap = {
            "immune_score": 10,
            "grade": "immunocompromised",
            "active_anomalies": 3,
            "worst_resolution_s": 7200,
        }
        summary = rir.human_summary(snap)
        self.assertIn("2h", summary)
        self.assertIn("immunocompromised", summary)


class TestSnapshot(unittest.TestCase):
    """integration test: snapshot should always return a valid dict."""

    def test_snapshot_structure(self):
        repo = Path(__file__).resolve().parent.parent
        snap = rir.snapshot(repo=repo)
        required_keys = [
            "timestamp",
            "uncommitted_age_s",
            "unpushed_age_s",
            "writer_gap_s",
            "active_anomalies",
            "worst_resolution_s",
            "immune_score",
            "grade",
        ]
        for key in required_keys:
            self.assertIn(key, snap, f"missing key: {key}")
        self.assertIn(snap["grade"], ("robust", "adequate", "sluggish", "immunocompromised"))
        self.assertIsInstance(snap["immune_score"], int)
        self.assertGreaterEqual(snap["immune_score"], 0)
        self.assertLessEqual(snap["immune_score"], 100)

    def test_detect_uncommitted_age_returns_int(self):
        repo = Path(__file__).resolve().parent.parent
        age = rir.detect_uncommitted_age(repo=repo)
        self.assertIsInstance(age, int)
        self.assertGreaterEqual(age, 0)

    def test_detect_unpushed_age_returns_int(self):
        repo = Path(__file__).resolve().parent.parent
        age = rir.detect_unpushed_age(repo=repo)
        self.assertIsInstance(age, int)
        self.assertGreaterEqual(age, 0)

    def test_detect_process_gaps_returns_int(self):
        gap = rir.detect_process_gaps()
        self.assertIsInstance(gap, int)
        self.assertGreaterEqual(gap, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
