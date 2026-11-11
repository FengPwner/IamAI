#!/usr/bin/env python3
"""Tests for writer_momentum — 42 test cases."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_momentum import (  # noqa: E402
    _classify,
    _recent_file_set,
    _stroke_files,
    _thread_id,
    analyze_writer_momentum,
    classify_trend,
    compute_momentum_metrics,
    compute_momentum_trend,
    format_momentum_report,
)


# ---------------------------------------------------------------------------
# Helper: _stroke_files
# ---------------------------------------------------------------------------

class TestStrokeFiles(unittest.TestCase):
    """Test _stroke_files helper."""

    def test_empty_stroke(self):
        self.assertEqual(_stroke_files({}), set())

    def test_list_of_strings(self):
        stroke = {"files": ["a.py", "b.py"]}
        self.assertEqual(_stroke_files(stroke), {"a.py", "b.py"})

    def test_list_of_paths(self):
        stroke = {"files": [Path("a.py"), Path("b.py")]}
        result = _stroke_files(stroke)
        self.assertEqual(result, {"a.py", "b.py"})

    def test_non_list_files(self):
        stroke = {"files": "not a list"}
        self.assertEqual(_stroke_files(stroke), set())

    def test_mixed_types(self):
        stroke = {"files": ["a.py", Path("b.py"), 42]}
        result = _stroke_files(stroke)
        self.assertEqual(result, {"a.py", "b.py"})

    def test_empty_strings(self):
        stroke = {"files": ["", "  "]}
        self.assertEqual(_stroke_files(stroke), set())

    def test_duplicate_paths(self):
        stroke = {"files": ["a.py", "a.py"]}
        self.assertEqual(_stroke_files(stroke), {"a.py"})


# ---------------------------------------------------------------------------
# Helper: _recent_file_set
# ---------------------------------------------------------------------------

class TestRecentFileSet(unittest.TestCase):
    """Test _recent_file_set helper."""

    def test_empty_strokes(self):
        self.assertEqual(_recent_file_set([], 0, 3), set())

    def test_lookback_larger_than_available(self):
        strokes = [{"files": ["a.py"]}]
        result = _recent_file_set(strokes, 1, 5)
        self.assertEqual(result, {"a.py"})

    def test_exact_lookback(self):
        strokes = [
            {"files": ["a.py"]},
            {"files": ["b.py"]},
            {"files": ["c.py"]},
        ]
        result = _recent_file_set(strokes, 3, 2)
        # Lookback 2 from index 3 → strokes[1] and strokes[2]
        self.assertEqual(result, {"b.py", "c.py"})

    def test_index_zero(self):
        strokes = [{"files": ["a.py"]}, {"files": ["b.py"]}]
        result = _recent_file_set(strokes, 0, 3)
        self.assertEqual(result, set())


# ---------------------------------------------------------------------------
# Helper: _thread_id
# ---------------------------------------------------------------------------

class TestThreadId(unittest.TestCase):
    """Test _thread_id helper."""

    def test_empty_sets(self):
        self.assertFalse(_thread_id(set(), set()))

    def test_one_empty(self):
        self.assertFalse(_thread_id({"a.py"}, set()))

    def test_direct_overlap(self):
        self.assertTrue(_thread_id({"a.py", "b.py"}, {"a.py", "c.py"}))

    def test_no_overlap(self):
        self.assertFalse(_thread_id({"a.py"}, {"b.py"}))

    def test_identical_sets(self):
        self.assertTrue(_thread_id({"a.py"}, {"a.py"}))


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify(unittest.TestCase):
    """Test _classify boundary conditions."""

    def test_rolling_high(self):
        self.assertEqual(_classify(1.0), "rolling")

    def test_rolling_boundary(self):
        self.assertEqual(_classify(0.70), "rolling")

    def test_cruising_high(self):
        self.assertEqual(_classify(0.69), "cruising")

    def test_cruising_boundary(self):
        self.assertEqual(_classify(0.50), "cruising")

    def test_stuttering_high(self):
        self.assertEqual(_classify(0.49), "stuttering")

    def test_stuttering_boundary(self):
        self.assertEqual(_classify(0.30), "stuttering")

    def test_restarting_high(self):
        self.assertEqual(_classify(0.29), "restarting")

    def test_restarting_zero(self):
        self.assertEqual(_classify(0.0), "restarting")


# ---------------------------------------------------------------------------
# compute_momentum_metrics
# ---------------------------------------------------------------------------

class TestComputeMomentumMetrics(unittest.TestCase):
    """Test compute_momentum_metrics with various stroke patterns."""

    def test_empty_strokes(self):
        m = compute_momentum_metrics([])
        self.assertEqual(m["strokes_analyzed"], 0)
        self.assertEqual(m["momentum_class"], "restarting")
        self.assertEqual(m["momentum_score"], 0.0)

    def test_single_stroke_with_files(self):
        m = compute_momentum_metrics([{"files": ["a.py"]}])
        self.assertEqual(m["strokes_analyzed"], 1)
        self.assertEqual(m["depth_per_thread"], 1.0)

    def test_single_stroke_empty(self):
        m = compute_momentum_metrics([{"files": []}])
        self.assertEqual(m["strokes_analyzed"], 1)
        self.assertEqual(m["fresh_start_rate"], 1.0)

    def test_perfect_continuation(self):
        """All strokes touch the same file — maximum continuation."""
        strokes = [{"files": ["a.py"]} for _ in range(10)]
        m = compute_momentum_metrics(strokes)
        self.assertEqual(m["continuation_ratio"], 1.0)
        self.assertEqual(m["build_on_rate"], 1.0)
        self.assertEqual(m["depth_per_thread"], 10.0)
        self.assertEqual(m["momentum_class"], "rolling")

    def test_all_fresh_starts(self):
        """Every stroke touches completely new files."""
        strokes = [{"files": [f"file_{i}.py"]} for i in range(10)]
        m = compute_momentum_metrics(strokes)
        self.assertEqual(m["continuation_ratio"], 0.0)
        self.assertEqual(m["fresh_start_rate"], 1.0)
        self.assertEqual(m["momentum_class"], "restarting")

    def test_alternating_pattern(self):
        """Alternating between two files — moderate momentum."""
        strokes = [
            {"files": ["a.py"]},
            {"files": ["b.py"]},
            {"files": ["a.py"]},
            {"files": ["b.py"]},
            {"files": ["a.py"]},
            {"files": ["b.py"]},
        ]
        m = compute_momentum_metrics(strokes)
        # With lookback=3, a.py at index 2 overlaps with a.py at index 0 → build-on
        # But no direct continuation (prev file is always different)
        self.assertGreater(m["build_on_rate"], 0.0)
        self.assertEqual(m["continuation_ratio"], 0.0)

    def test_mixed_pattern(self):
        """Some continuation, some fresh starts."""
        strokes = [
            {"files": ["a.py"]},
            {"files": ["a.py", "b.py"]},  # continues a.py
            {"files": ["b.py"]},           # continues b.py
            {"files": ["c.py"]},           # fresh start
            {"files": ["c.py", "d.py"]},  # continues c.py
            {"files": ["d.py"]},           # continues d.py
        ]
        m = compute_momentum_metrics(strokes)
        self.assertGreater(m["continuation_ratio"], 0.0)
        self.assertLess(m["continuation_ratio"], 1.0)
        self.assertGreater(m["fresh_start_rate"], 0.0)

    def test_window_size_limits_analysis(self):
        """Only the last window_size strokes are analyzed."""
        strokes = [{"files": [f"old_{i}.py"]} for i in range(50)]
        strokes += [{"files": ["new.py"]} for _ in range(10)]
        m = compute_momentum_metrics(strokes, window_size=10)
        self.assertEqual(m["strokes_analyzed"], 10)

    def test_lookback_one(self):
        """With lookback=1, build-on only checks the immediately previous stroke."""
        strokes = [
            {"files": ["a.py"]},
            {"files": ["b.py"]},
            {"files": ["a.py"]},  # doesn't overlap with prev (b.py), so no build-on
        ]
        m = compute_momentum_metrics(strokes, lookback=1)
        self.assertEqual(m["build_on_rate"], 0.0)

    def test_lookback_two(self):
        """With lookback=2, a.py at index 2 overlaps with a.py at index 0."""
        strokes = [
            {"files": ["a.py"]},
            {"files": ["b.py"]},
            {"files": ["a.py"]},
        ]
        m = compute_momentum_metrics(strokes, lookback=2)
        self.assertEqual(m["build_on_rate"], 0.5)  # 1 out of 2 pairs

    def test_two_strokes_continuation(self):
        """Simple two-stroke continuation."""
        strokes = [
            {"files": ["a.py", "b.py"]},
            {"files": ["b.py", "c.py"]},
        ]
        m = compute_momentum_metrics(strokes)
        self.assertEqual(m["continuation_ratio"], 1.0)
        self.assertEqual(m["build_on_rate"], 1.0)
        self.assertEqual(m["threads_count"], 1)

    def test_thread_counting(self):
        """Correctly counts threads when switching files."""
        strokes = [
            {"files": ["a.py"]},
            {"files": ["a.py"]},
            {"files": ["b.py"]},  # new thread
            {"files": ["b.py"]},
            {"files": ["c.py"]},  # new thread
        ]
        m = compute_momentum_metrics(strokes)
        self.assertEqual(m["threads_count"], 3)
        self.assertAlmostEqual(m["depth_per_thread"], 5 / 3, places=3)

    def test_depth_norm_capped(self):
        """Depth normalization caps at 10 strokes per thread."""
        # 20 strokes all on same file → depth=20, but norm capped at 1.0
        strokes = [{"files": ["a.py"]} for _ in range(20)]
        m = compute_momentum_metrics(strokes)
        # Score should not exceed 1.0
        self.assertLessEqual(m["momentum_score"], 1.0)

    def test_score_clamped_to_zero_one(self):
        """Score is always within [0, 1]."""
        for i in range(20):
            strokes = [{"files": [f"f_{i}_{j}.py"]} for j in range(i + 2)]
            m = compute_momentum_metrics(strokes)
            self.assertGreaterEqual(m["momentum_score"], 0.0)
            self.assertLessEqual(m["momentum_score"], 1.0)


# ---------------------------------------------------------------------------
# analyze_writer_momentum
# ---------------------------------------------------------------------------

class TestAnalyzeWriterMomentum(unittest.TestCase):
    """Test analyze_writer_momentum with file I/O."""

    def test_nonexistent_file(self):
        m = analyze_writer_momentum("/tmp/nonexistent_strokes_xyz.jsonl")
        self.assertEqual(m["strokes_analyzed"], 0)
        self.assertEqual(m["momentum_class"], "restarting")

    def test_valid_jsonl(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for i in range(5):
                f.write(json.dumps({"seq": i, "files": ["a.py"]}) + "\n")
            f.flush()
            m = analyze_writer_momentum(f.name)
        self.assertEqual(m["strokes_analyzed"], 5)
        Path(f.name).unlink()

    def test_malformed_lines_skipped(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write('{"seq": 0, "files": ["a.py"]}\n')
            f.write("not valid json\n")
            f.write('{"seq": 2, "files": ["a.py"]}\n')
            f.flush()
            m = analyze_writer_momentum(f.name)
        self.assertEqual(m["strokes_analyzed"], 2)
        Path(f.name).unlink()

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write("")
            f.flush()
            m = analyze_writer_momentum(f.name)
        self.assertEqual(m["strokes_analyzed"], 0)
        Path(f.name).unlink()


# ---------------------------------------------------------------------------
# format_momentum_report
# ---------------------------------------------------------------------------

class TestFormatMomentumReport(unittest.TestCase):
    """Test format_momentum_report output."""

    def test_contains_header(self):
        m = compute_momentum_metrics([])
        report = format_momentum_report(m)
        self.assertIn("Writer Momentum Report", report)

    def test_contains_class(self):
        m = compute_momentum_metrics([{"files": ["a.py"]} for _ in range(5)])
        report = format_momentum_report(m)
        self.assertIn("Momentum class:", report)

    def test_contains_score(self):
        m = compute_momentum_metrics([])
        report = format_momentum_report(m)
        self.assertIn("Momentum score:", report)

    def test_multiline(self):
        m = compute_momentum_metrics([])
        report = format_momentum_report(m)
        self.assertGreater(len(report.split("\n")), 5)


# ---------------------------------------------------------------------------
# compute_momentum_trend & classify_trend
# ---------------------------------------------------------------------------

class TestMomentumTrend(unittest.TestCase):
    """Test trend analysis across snapshots."""

    def test_insufficient_data_empty(self):
        t = compute_momentum_trend([])
        self.assertEqual(t["direction"], "insufficient_data")

    def test_insufficient_data_one(self):
        t = compute_momentum_trend([{"momentum_score": 0.5}])
        self.assertEqual(t["direction"], "insufficient_data")

    def test_increasing(self):
        snapshots = [
            {"momentum_score": 0.3},
            {"momentum_score": 0.5},
            {"momentum_score": 0.7},
        ]
        t = compute_momentum_trend(snapshots)
        self.assertEqual(t["direction"], "increasing")
        self.assertAlmostEqual(t["delta"], 0.4, places=3)

    def test_decreasing(self):
        snapshots = [
            {"momentum_score": 0.8},
            {"momentum_score": 0.6},
            {"momentum_score": 0.3},
        ]
        t = compute_momentum_trend(snapshots)
        self.assertEqual(t["direction"], "decreasing")
        self.assertAlmostEqual(t["delta"], -0.5, places=3)

    def test_stable(self):
        snapshots = [
            {"momentum_score": 0.5},
            {"momentum_score": 0.52},
            {"momentum_score": 0.51},
        ]
        t = compute_momentum_trend(snapshots)
        self.assertEqual(t["direction"], "stable")

    def test_classify_trend_shortcut(self):
        snapshots = [
            {"momentum_score": 0.2},
            {"momentum_score": 0.8},
        ]
        self.assertEqual(classify_trend(snapshots), "increasing")

    def test_classify_trend_decreasing(self):
        snapshots = [
            {"momentum_score": 0.9},
            {"momentum_score": 0.3},
        ]
        self.assertEqual(classify_trend(snapshots), "decreasing")

    def test_trend_delta_positive(self):
        snapshots = [
            {"momentum_score": 0.4},
            {"momentum_score": 0.6},
        ]
        t = compute_momentum_trend(snapshots)
        self.assertGreater(t["delta"], 0)

    def test_trend_preserves_first_last(self):
        snapshots = [
            {"momentum_score": 0.1},
            {"momentum_score": 0.5},
            {"momentum_score": 0.9},
        ]
        t = compute_momentum_trend(snapshots)
        self.assertEqual(t["first_score"], 0.1)
        self.assertEqual(t["last_score"], 0.9)


if __name__ == "__main__":
    unittest.main()
