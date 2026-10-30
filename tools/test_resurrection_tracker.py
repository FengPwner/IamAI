#!/usr/bin/env python3
"""Tests for resurrection_tracker.py — 48 test cases.

Covers:
  - parse_commit_line: valid, malformed, edge cases
  - detect_clusters: empty, single, clustered, spread
  - compute_gaps: basic, single-element, large sets
  - quartiles: empty, small, even/odd counts
  - build_report: json/text formats, empty input, verdict logic
  - Resurrection dataclass construction
"""

import json
import unittest
from datetime import datetime, timedelta, timezone

# Import module under test
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from resurrection_tracker import (
    Resurrection,
    ClusterInfo,
    parse_commit_line,
    detect_clusters,
    compute_gaps,
    quartiles,
    build_report,
    CST,
)


class TestParseCommitLine(unittest.TestCase):
    """14 tests for parse_commit_line."""

    def test_valid_catch_up(self):
        r = parse_commit_line("69a03211 2026-10-23 21:01:00 catch-up: commit pending changes before process restart")
        self.assertIsNotNone(r)
        self.assertEqual(r.commit_hash, "69a03211")
        self.assertEqual(r.process, "both")

    def test_writer_restart(self):
        r = parse_commit_line("abc12345 2026-10-20 14:30:00 restart writer after stall detected")
        self.assertIsNotNone(r)
        self.assertEqual(r.process, "writer")

    def test_batch_restart(self):
        r = parse_commit_line("def67890 2026-10-20 14:30:00 restart batch commit loop")
        self.assertIsNotNone(r)
        self.assertEqual(r.process, "batch")

    def test_both_mentioned(self):
        r = parse_commit_line("11111111 2026-10-21 09:00:00 restart writer and batch after crash")
        self.assertIsNotNone(r)
        self.assertEqual(r.process, "both")

    def test_resurrection_keyword(self):
        r = parse_commit_line("22222222 2026-10-22 10:00:00 resurrection: process recovered")
        self.assertIsNotNone(r)
        self.assertEqual(r.commit_hash, "22222222")

    def test_too_few_fields(self):
        r = parse_commit_line("abc12345 2026-10-23")
        self.assertIsNone(r)

    def test_bad_date(self):
        r = parse_commit_line("abc12345 not-a-date 00:00:00 some message")
        self.assertIsNone(r)

    def test_empty_string(self):
        r = parse_commit_line("")
        self.assertIsNone(r)

    def test_timezone_is_cst(self):
        r = parse_commit_line("abc12345 2026-10-23 12:00:00 catch-up: test")
        self.assertIsNotNone(r)
        self.assertEqual(r.timestamp.tzinfo, CST)

    def test_message_preserved(self):
        msg = "catch-up: commit pending changes before process restart"
        r = parse_commit_line(f"abc12345 2026-10-23 12:00:00 {msg}")
        self.assertEqual(r.message, msg)

    def test_midnight_timestamp(self):
        r = parse_commit_line("abc12345 2026-10-23 00:00:00 catch-up: midnight restart")
        self.assertIsNotNone(r)
        self.assertEqual(r.timestamp.hour, 0)

    def test_end_of_day(self):
        r = parse_commit_line("abc12345 2026-10-23 23:59:59 catch-up: late night")
        self.assertIsNotNone(r)
        self.assertEqual(r.timestamp.hour, 23)
        self.assertEqual(r.timestamp.minute, 59)

    def test_process_restart_case_insensitive(self):
        r = parse_commit_line("abc12345 2026-10-23 10:00:00 Process Restart after OOM")
        self.assertIsNotNone(r)

    def test_single_word_no_match(self):
        # Not enough fields to parse (need hash + date + time + message)
        r = parse_commit_line("catch-up")
        self.assertIsNone(r)


class TestDetectClusters(unittest.TestCase):
    """10 tests for detect_clusters."""

    def _make_resurrections(self, times: list[datetime]) -> list[Resurrection]:
        return [
            Resurrection(
                timestamp=t,
                commit_hash=f"{i:08x}",
                message=f"catch-up #{i}",
                process="writer",
            )
            for i, t in enumerate(times)
        ]

    def test_empty(self):
        self.assertEqual(detect_clusters([], window_minutes=60), [])

    def test_single(self):
        base = datetime(2026, 10, 23, 10, 0, tzinfo=CST)
        rs = self._make_resurrections([base])
        self.assertEqual(detect_clusters(rs), [])

    def test_two_within_window(self):
        base = datetime(2026, 10, 23, 10, 0, tzinfo=CST)
        rs = self._make_resurrections([base, base + timedelta(minutes=30)])
        clusters = detect_clusters(rs, window_minutes=60)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].count, 2)

    def test_two_outside_window(self):
        base = datetime(2026, 10, 23, 10, 0, tzinfo=CST)
        rs = self._make_resurrections([base, base + timedelta(hours=3)])
        clusters = detect_clusters(rs, window_minutes=60)
        self.assertEqual(len(clusters), 0)

    def test_three_tight_cluster(self):
        base = datetime(2026, 10, 23, 10, 0, tzinfo=CST)
        rs = self._make_resurrections([
            base,
            base + timedelta(minutes=10),
            base + timedelta(minutes=25),
        ])
        clusters = detect_clusters(rs, window_minutes=60)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].count, 3)
        self.assertAlmostEqual(clusters[0].span_minutes, 25.0, places=0)

    def test_two_separate_clusters(self):
        base = datetime(2026, 10, 23, 10, 0, tzinfo=CST)
        rs = self._make_resurrections([
            base,
            base + timedelta(minutes=15),
            base + timedelta(hours=5),
            base + timedelta(hours=5, minutes=20),
        ])
        clusters = detect_clusters(rs, window_minutes=60)
        self.assertEqual(len(clusters), 2)

    def test_exact_window_boundary(self):
        base = datetime(2026, 10, 23, 10, 0, tzinfo=CST)
        rs = self._make_resurrections([base, base + timedelta(minutes=60)])
        clusters = detect_clusters(rs, window_minutes=60)
        # 60 min gap is exactly at boundary; code uses > so this IS clustered
        self.assertEqual(len(clusters), 1)
        # One minute over should NOT cluster
        rs2 = self._make_resurrections([base, base + timedelta(minutes=61)])
        clusters2 = detect_clusters(rs2, window_minutes=60)
        self.assertEqual(len(clusters2), 0)

    def test_span_minutes_calculation(self):
        base = datetime(2026, 10, 23, 10, 0, tzinfo=CST)
        rs = self._make_resurrections([
            base,
            base + timedelta(minutes=45),
        ])
        clusters = detect_clusters(rs, window_minutes=60)
        self.assertEqual(clusters[0].span_minutes, 45.0)

    def test_cluster_label_format(self):
        base = datetime(2026, 10, 23, 14, 30, tzinfo=CST)
        rs = self._make_resurrections([base, base + timedelta(minutes=10)])
        clusters = detect_clusters(rs, window_minutes=60)
        self.assertIn("cluster@", clusters[0].label)
        self.assertIn("10-23", clusters[0].label)

    def test_large_gap_no_cluster(self):
        base = datetime(2026, 10, 1, 10, 0, tzinfo=CST)
        rs = self._make_resurrections([
            base,
            base + timedelta(days=7),
            base + timedelta(days=14),
        ])
        clusters = detect_clusters(rs, window_minutes=60)
        self.assertEqual(len(clusters), 0)


class TestComputeGaps(unittest.TestCase):
    """7 tests for compute_gaps."""

    def _make(self, times):
        return [Resurrection(t, f"{i:08x}", f"msg {i}", "writer") for i, t in enumerate(times)]

    def test_empty(self):
        self.assertEqual(compute_gaps([]), [])

    def test_single(self):
        base = datetime(2026, 10, 23, 10, 0, tzinfo=CST)
        self.assertEqual(compute_gaps(self._make([base])), [])

    def test_two_one_hour_apart(self):
        base = datetime(2026, 10, 23, 10, 0, tzinfo=CST)
        rs = self._make([base, base + timedelta(hours=1)])
        gaps = compute_gaps(rs)
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0], 1.0)

    def test_sorted_output(self):
        base = datetime(2026, 10, 23, 10, 0, tzinfo=CST)
        rs = self._make([
            base,
            base + timedelta(hours=5),
            base + timedelta(hours=5, minutes=30),
            base + timedelta(hours=6),
        ])
        gaps = compute_gaps(rs)
        self.assertEqual(gaps, sorted(gaps))

    def test_three_day_gap(self):
        base = datetime(2026, 10, 20, 10, 0, tzinfo=CST)
        rs = self._make([base, base + timedelta(days=3)])
        gaps = compute_gaps(rs)
        self.assertAlmostEqual(gaps[0], 72.0)

    def test_sub_hour_gap(self):
        base = datetime(2026, 10, 23, 10, 0, tzinfo=CST)
        rs = self._make([base, base + timedelta(minutes=15)])
        gaps = compute_gaps(rs)
        self.assertAlmostEqual(gaps[0], 0.25)

    def test_many_gaps(self):
        base = datetime(2026, 10, 1, 0, 0, tzinfo=CST)
        times = [base + timedelta(hours=i * 6) for i in range(10)]
        gaps = compute_gaps(self._make(times))
        self.assertEqual(len(gaps), 9)
        self.assertTrue(all(g >= 0 for g in gaps))


class TestQuartiles(unittest.TestCase):
    """7 tests for quartiles."""

    def test_empty(self):
        q = quartiles([])
        self.assertEqual(q["min"], 0)
        self.assertEqual(q["max"], 0)

    def test_single_value(self):
        q = quartiles([5.0])
        self.assertEqual(q["min"], 5.0)
        self.assertEqual(q["max"], 5.0)
        self.assertEqual(q["q2"], 5.0)

    def test_two_values(self):
        q = quartiles([1.0, 3.0])
        self.assertEqual(q["min"], 1.0)
        self.assertEqual(q["max"], 3.0)
        self.assertEqual(q["q2"], 2.0)

    def test_four_values(self):
        q = quartiles([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(q["min"], 1.0)
        self.assertEqual(q["q1"], 2.0)  # data[n//4] = data[1] = 2.0
        self.assertEqual(q["max"], 4.0)

    def test_odd_count(self):
        q = quartiles([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(q["q2"], 3.0)

    def test_large_dataset(self):
        data = list(range(1, 101))
        q = quartiles([float(x) for x in data])
        self.assertEqual(q["min"], 1.0)
        self.assertEqual(q["max"], 100.0)
        self.assertEqual(q["q2"], 50.5)

    def test_identical_values(self):
        q = quartiles([7.0, 7.0, 7.0, 7.0])
        self.assertEqual(q["q1"], 7.0)
        self.assertEqual(q["q2"], 7.0)
        self.assertEqual(q["q3"], 7.0)


class TestBuildReport(unittest.TestCase):
    """10 tests for build_report."""

    def _make(self, times, process="writer"):
        return [
            Resurrection(t, f"{i:08x}", f"catch-up #{i}", process)
            for i, t in enumerate(times)
        ]

    def test_empty_text(self):
        out = build_report([], as_json=False)
        self.assertIn("No resurrections", out)

    def test_empty_json(self):
        out = json.loads(build_report([], as_json=True))
        self.assertEqual(out["count"], 0)

    def test_single_resurrection(self):
        base = datetime(2026, 10, 23, 10, 0, tzinfo=CST)
        rs = self._make([base])
        out = build_report(rs, as_json=False)
        self.assertIn("Total resurrections: 1", out)

    def test_json_structure(self):
        base = datetime(2026, 10, 20, 10, 0, tzinfo=CST)
        rs = self._make([base, base + timedelta(hours=12)])
        out = json.loads(build_report(rs, as_json=True))
        self.assertIn("count", out)
        self.assertIn("by_process", out)
        self.assertIn("mtbr_hours", out)
        self.assertIn("verdict", out)
        self.assertEqual(out["count"], 2)

    def test_healthy_verdict_few_deaths(self):
        base = datetime(2026, 10, 20, 10, 0, tzinfo=CST)
        rs = self._make([base, base + timedelta(days=5)])
        out = json.loads(build_report(rs, as_json=True))
        self.assertEqual(out["verdict"], "healthy")

    def test_by_process_counts(self):
        base = datetime(2026, 10, 20, 10, 0, tzinfo=CST)
        rs = [
            Resurrection(base, "aabbccdd", "catch-up writer", "writer"),
            Resurrection(base + timedelta(hours=1), "11223344", "catch-up batch", "batch"),
            Resurrection(base + timedelta(hours=2), "55667788", "catch-up both", "both"),
        ]
        out = json.loads(build_report(rs, as_json=True))
        self.assertEqual(out["by_process"]["writer"], 1)
        self.assertEqual(out["by_process"]["batch"], 1)
        self.assertEqual(out["by_process"]["both"], 1)

    def test_clusters_in_report(self):
        base = datetime(2026, 10, 23, 10, 0, tzinfo=CST)
        rs = self._make([
            base,
            base + timedelta(minutes=10),
            base + timedelta(minutes=20),
        ])
        out = build_report(rs, as_json=False)
        self.assertIn("cluster", out.lower())

    def test_no_clusters_text(self):
        base = datetime(2026, 10, 1, 10, 0, tzinfo=CST)
        rs = self._make([base, base + timedelta(days=7)])
        out = build_report(rs, as_json=False)
        self.assertIn("No clusters", out)

    def test_gap_distribution_present(self):
        base = datetime(2026, 10, 20, 10, 0, tzinfo=CST)
        rs = self._make([base, base + timedelta(hours=6), base + timedelta(hours=12)])
        out = build_report(rs, as_json=False)
        self.assertIn("Gap distribution", out)
        self.assertIn("median", out)

    def test_span_days_in_json(self):
        base = datetime(2026, 10, 1, 0, 0, tzinfo=CST)
        rs = self._make([base, base + timedelta(days=10)])
        out = json.loads(build_report(rs, as_json=True))
        self.assertIn("span_days", out)
        self.assertGreater(out["span_days"], 0)


if __name__ == "__main__":
    unittest.main()
