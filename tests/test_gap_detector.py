"""tests for snippets/gap_detector.py.

covers:
- empty input
- single stroke (no gap possible)
- all gaps below threshold
- one gap exactly at threshold (included)
- multiple gaps in sequence
- unix epoch timestamps
"""

import json
import os
import tempfile
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "snippets"))
from gap_detector import detect_gaps, summarize, _parse_ts


def _write_jsonl(lines):
    """helper: write a list of dicts as JSONL, return path."""
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for record in lines:
            f.write(json.dumps(record) + "\n")
        return f.name


class TestDetectGaps(unittest.TestCase):

    def test_empty_file(self):
        path = _write_jsonl([])
        try:
            self.assertEqual(detect_gaps(path), [])
        finally:
            os.remove(path)

    def test_single_stroke(self):
        path = _write_jsonl([{"ts": "2026-10-04T00:00:00Z", "n": 1}])
        try:
            self.assertEqual(detect_gaps(path), [])
        finally:
            os.remove(path)

    def test_no_gaps_above_threshold(self):
        path = _write_jsonl([
            {"ts": "2026-10-04T00:00:00Z", "n": 1},
            {"ts": "2026-10-04T00:00:15Z", "n": 2},
            {"ts": "2026-10-04T00:00:30Z", "n": 3},
        ])
        try:
            self.assertEqual(detect_gaps(path, threshold_s=60), [])
        finally:
            os.remove(path)

    def test_gap_exactly_at_threshold(self):
        path = _write_jsonl([
            {"ts": "2026-10-04T00:00:00Z", "n": 1},
            {"ts": "2026-10-04T00:05:00Z", "n": 2},
        ])
        try:
            gaps = detect_gaps(path, threshold_s=300)
            self.assertEqual(len(gaps), 1)
            self.assertEqual(gaps[0]["gap_s"], 300.0)
            self.assertEqual(gaps[0]["before_n"], 1)
            self.assertEqual(gaps[0]["after_n"], 2)
        finally:
            os.remove(path)

    def test_gap_below_threshold_excluded(self):
        path = _write_jsonl([
            {"ts": "2026-10-04T00:00:00Z", "n": 1},
            {"ts": "2026-10-04T00:04:59Z", "n": 2},
        ])
        try:
            gaps = detect_gaps(path, threshold_s=300)
            self.assertEqual(len(gaps), 0)
        finally:
            os.remove(path)

    def test_multiple_gaps(self):
        path = _write_jsonl([
            {"ts": "2026-10-04T00:00:00Z", "n": 1},
            {"ts": "2026-10-04T00:00:15Z", "n": 2},
            {"ts": "2026-10-04T00:10:00Z", "n": 3},  # gap: 585s
            {"ts": "2026-10-04T00:10:15Z", "n": 4},
            {"ts": "2026-10-04T00:20:00Z", "n": 5},  # gap: 585s
        ])
        try:
            gaps = detect_gaps(path, threshold_s=300)
            self.assertEqual(len(gaps), 2)
            self.assertEqual(gaps[0]["before_n"], 2)
            self.assertEqual(gaps[0]["after_n"], 3)
            self.assertEqual(gaps[1]["before_n"], 4)
            self.assertEqual(gaps[1]["after_n"], 5)
        finally:
            os.remove(path)

    def test_unix_epoch_timestamps(self):
        path = _write_jsonl([
            {"ts": 1728000000, "n": 1},     # 2024-10-04 00:00:00 UTC
            {"ts": 1728000015, "n": 2},     # +15s
            {"ts": 1728001200, "n": 3},     # +1200s (gap)
        ])
        try:
            gaps = detect_gaps(path, threshold_s=300)
            self.assertEqual(len(gaps), 1)
            self.assertEqual(gaps[0]["gap_s"], 1185.0)
        finally:
            os.remove(path)

    def test_blank_lines_skipped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"ts": "2026-10-04T00:00:00Z", "n": 1}) + "\n")
            f.write("\n")  # blank
            f.write(json.dumps({"ts": "2026-10-04T00:10:00Z", "n": 2}) + "\n")
            path = f.name
        try:
            gaps = detect_gaps(path, threshold_s=300)
            self.assertEqual(len(gaps), 1)
        finally:
            os.remove(path)


class TestSummarize(unittest.TestCase):

    def test_no_gaps(self):
        self.assertEqual(summarize([]), "no gaps detected.")

    def test_one_gap(self):
        gaps = [{
            "before_n": 100, "after_n": 101,
            "before_ts": "2026-10-04T00:00:00+00:00",
            "after_ts": "2026-10-04T00:16:40+00:00",
            "gap_s": 1000.0,
        }]
        result = summarize(gaps)
        self.assertIn("1 gap(s) found", result)
        self.assertIn("1000.0s", result)

    def test_picks_longest(self):
        gaps = [
            {"before_n": 1, "after_n": 2, "gap_s": 100.0,
             "before_ts": "x", "after_ts": "y"},
            {"before_n": 5, "after_n": 6, "gap_s": 500.0,
             "before_ts": "x", "after_ts": "y"},
            {"before_n": 3, "after_n": 4, "gap_s": 200.0,
             "before_ts": "x", "after_ts": "y"},
        ]
        result = summarize(gaps)
        self.assertIn("500.0s", result)
        self.assertIn("stroke 5 and 6", result)


class TestParseTs(unittest.TestCase):

    def test_iso_with_z(self):
        dt = _parse_ts("2026-10-04T00:00:00Z")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 10)
        self.assertEqual(dt.day, 4)

    def test_unix_epoch(self):
        dt = _parse_ts(1728000000)
        self.assertEqual(dt.year, 2024)

    def test_iso_with_offset(self):
        dt = _parse_ts("2026-10-04T08:00:00+08:00")
        self.assertEqual(dt.hour, 8)


if __name__ == "__main__":
    unittest.main()
