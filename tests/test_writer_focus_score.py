#!/usr/bin/env python3
"""Tests for writer_focus_score — 55 test cases."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_focus_score import (  # noqa: E402
    _are_files_related,
    _file_cluster,
    _stroke_files,
    analyze_writer_focus,
    compute_focus_metrics,
    format_focus_report,
)


# ---------------------------------------------------------------------------
# Helper functions
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


class TestFileCluster(unittest.TestCase):
    """Test _file_cluster helper."""

    def test_simple_path(self):
        self.assertEqual(_file_cluster("iamai/writer.py"), "iamai")

    def test_nested_path(self):
        self.assertEqual(_file_cluster("iamai/metrics/focus.py"), "iamai")

    def test_single_component(self):
        self.assertEqual(_file_cluster("README.md"), "README.md")

    def test_root_path(self):
        self.assertEqual(_file_cluster(""), "root")


class TestAreFilesRelated(unittest.TestCase):
    """Test _are_files_related helper."""

    def test_empty_sets(self):
        self.assertFalse(_are_files_related(set(), set()))

    def test_one_empty(self):
        self.assertFalse(_are_files_related({"a.py"}, set()))

    def test_direct_overlap(self):
        self.assertTrue(_are_files_related({"a.py"}, {"a.py", "b.py"}))

    def test_cluster_overlap(self):
        self.assertTrue(_are_files_related(
            {"iamai/writer.py"},
            {"iamai/focus.py"}
        ))

    def test_no_overlap(self):
        self.assertFalse(_are_files_related(
            {"iamai/writer.py"},
            {"tests/test_writer.py"}
        ))


# ---------------------------------------------------------------------------
# compute_focus_metrics — edge cases
# ---------------------------------------------------------------------------

class TestComputeFocusMetricsEdge(unittest.TestCase):
    """Edge cases for compute_focus_metrics."""

    def test_empty_strokes(self):
        result = compute_focus_metrics([])
        self.assertEqual(result["thread_length"], 0)
        self.assertEqual(result["context_switch_rate"], 1.0)
        self.assertEqual(result["coherence_score"], 0.0)
        self.assertEqual(result["focus_class"], "scattered")

    def test_single_stroke(self):
        strokes = [{"files": ["iamai/writer.py"]}]
        result = compute_focus_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 1)
        self.assertIn("focus_class", result)

    def test_two_strokes_related(self):
        strokes = [
            {"files": ["iamai/writer.py"]},
            {"files": ["iamai/focus.py"]},
        ]
        result = compute_focus_metrics(strokes)
        self.assertEqual(result["context_switches"], 0)
        self.assertGreater(result["coherence_score"], 0)

    def test_two_strokes_unrelated(self):
        strokes = [
            {"files": ["iamai/writer.py"]},
            {"files": ["tests/test_other.py"]},
        ]
        result = compute_focus_metrics(strokes)
        self.assertEqual(result["context_switches"], 1)
        self.assertEqual(result["coherence_score"], 0.0)


# ---------------------------------------------------------------------------
# compute_focus_metrics — thread detection
# ---------------------------------------------------------------------------

class TestComputeFocusMetricsThreads(unittest.TestCase):
    """Test thread detection logic."""

    def test_single_thread(self):
        """All strokes in same cluster = one thread."""
        strokes = [
            {"files": ["iamai/writer.py"]},
            {"files": ["iamai/focus.py"]},
            {"files": ["iamai/stamina.py"]},
        ]
        result = compute_focus_metrics(strokes)
        self.assertEqual(result["thread_length"], 3.0)
        self.assertEqual(result["context_switches"], 0)

    def test_multiple_threads(self):
        """Strokes switch between clusters."""
        strokes = [
            {"files": ["iamai/writer.py"]},
            {"files": ["iamai/focus.py"]},
            {"files": ["tests/test_writer.py"]},
            {"files": ["tests/test_focus.py"]},
        ]
        result = compute_focus_metrics(strokes)
        self.assertEqual(result["context_switches"], 1)
        self.assertEqual(result["thread_length"], 2.0)

    def test_frequent_switches(self):
        """Every stroke switches context."""
        strokes = [
            {"files": ["iamai/writer.py"]},
            {"files": ["tests/test_writer.py"]},
            {"files": ["docs/README.md"]},
            {"files": ["tools/run.py"]},
        ]
        result = compute_focus_metrics(strokes)
        self.assertEqual(result["context_switches"], 3)
        self.assertEqual(result["thread_length"], 1.0)

    def test_long_thread(self):
        """Long sustained thread."""
        strokes = [{"files": [f"iamai/module{i}.py"]} for i in range(15)]
        result = compute_focus_metrics(strokes)
        self.assertEqual(result["thread_length"], 15.0)
        self.assertEqual(result["context_switches"], 0)


# ---------------------------------------------------------------------------
# compute_focus_metrics — classification
# ---------------------------------------------------------------------------

class TestComputeFocusMetricsClassification(unittest.TestCase):
    """Test focus classification."""

    def test_laser_focus(self):
        """All strokes in same cluster."""
        strokes = [{"files": [f"iamai/module{i}.py"]} for i in range(20)]
        result = compute_focus_metrics(strokes)
        self.assertEqual(result["focus_class"], "laser")
        self.assertGreaterEqual(result["focus_score"], 0.80)

    def test_focused_work(self):
        """Mostly same cluster with occasional switches."""
        strokes = [{"files": [f"iamai/module{i}.py"]} for i in range(15)]
        strokes.extend([{"files": [f"tests/test{i}.py"]} for i in range(3)])
        strokes.extend([{"files": [f"iamai/other{i}.py"]} for i in range(2)])
        result = compute_focus_metrics(strokes)
        self.assertIn(result["focus_class"], ["focused", "laser"])

    def test_drifting(self):
        """Moderate focus with frequent switches."""
        strokes = []
        for i in range(10):
            strokes.append({"files": [f"iamai/module{i}.py"]})
            if i % 3 == 0:
                strokes.append({"files": [f"tests/test{i}.py"]})
        result = compute_focus_metrics(strokes)
        self.assertIn(result["focus_class"], ["drifting", "focused"])

    def test_scattered(self):
        """Every stroke in different cluster."""
        clusters = ["iamai", "tests", "docs", "tools", "scripts", "data"]
        strokes = [
            {"files": [f"{clusters[i % len(clusters)]}/file{i}.py"]}
            for i in range(20)
        ]
        result = compute_focus_metrics(strokes)
        self.assertIn(result["focus_class"], ["scattered", "drifting"])


# ---------------------------------------------------------------------------
# compute_focus_metrics — metrics validation
# ---------------------------------------------------------------------------

class TestComputeFocusMetricsValidation(unittest.TestCase):
    """Validate metric calculations."""

    def test_coherence_score_range(self):
        strokes = [{"files": [f"iamai/module{i}.py"]} for i in range(10)]
        result = compute_focus_metrics(strokes)
        self.assertGreaterEqual(result["coherence_score"], 0.0)
        self.assertLessEqual(result["coherence_score"], 1.0)

    def test_fragmentation_index_range(self):
        strokes = [{"files": [f"iamai/module{i}.py"]} for i in range(10)]
        result = compute_focus_metrics(strokes)
        self.assertGreaterEqual(result["fragmentation_index"], 0.0)
        self.assertLessEqual(result["fragmentation_index"], 1.0)

    def test_focus_score_range(self):
        strokes = [{"files": [f"iamai/module{i}.py"]} for i in range(10)]
        result = compute_focus_metrics(strokes)
        self.assertGreaterEqual(result["focus_score"], 0.0)
        self.assertLessEqual(result["focus_score"], 1.0)

    def test_context_switch_rate_range(self):
        strokes = [{"files": [f"iamai/module{i}.py"]} for i in range(10)]
        result = compute_focus_metrics(strokes)
        self.assertGreaterEqual(result["context_switch_rate"], 0.0)
        self.assertLessEqual(result["context_switch_rate"], 1.0)


# ---------------------------------------------------------------------------
# analyze_writer_focus
# ---------------------------------------------------------------------------

class TestAnalyzeWriterFocus(unittest.TestCase):
    """Test analyze_writer_focus integration."""

    def test_missing_strokes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = analyze_writer_focus(data_dir=tmpdir)
            self.assertIn("error", result)
            self.assertEqual(result["focus_class"], "scattered")

    def test_empty_strokes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strokes_path = Path(tmpdir) / "strokes.jsonl"
            strokes_path.write_text("")
            result = analyze_writer_focus(data_dir=tmpdir)
            self.assertEqual(result["strokes_analyzed"], 0)

    def test_with_strokes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strokes_path = Path(tmpdir) / "strokes.jsonl"
            with open(strokes_path, "w") as f:
                for i in range(10):
                    stroke = {
                        "writer": "qwen",
                        "files": [f"iamai/module{i}.py"],
                        "timestamp": f"2024-01-01T00:{i:02d}:00",
                    }
                    f.write(json.dumps(stroke) + "\n")
            
            result = analyze_writer_focus(data_dir=tmpdir, writer="qwen")
            self.assertEqual(result["writer"], "qwen")
            self.assertEqual(result["total_strokes"], 10)
            self.assertIn("focus_class", result)

    def test_wrong_writer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strokes_path = Path(tmpdir) / "strokes.jsonl"
            with open(strokes_path, "w") as f:
                stroke = {"writer": "other", "files": ["a.py"]}
                f.write(json.dumps(stroke) + "\n")
            
            result = analyze_writer_focus(data_dir=tmpdir, writer="qwen")
            self.assertEqual(result["total_strokes"], 0)


# ---------------------------------------------------------------------------
# format_focus_report
# ---------------------------------------------------------------------------

class TestFormatFocusReport(unittest.TestCase):
    """Test format_focus_report."""

    def test_error_report(self):
        result = format_focus_report({"error": "test error"})
        self.assertIn("Error", result)
        self.assertIn("test error", result)

    def test_laser_report(self):
        metrics = {
            "writer": "qwen",
            "focus_class": "laser",
            "focus_score": 0.85,
            "thread_length": 12.5,
            "context_switches": 1,
            "context_switch_rate": 0.05,
            "coherence_score": 0.92,
            "fragmentation_index": 0.15,
            "distinct_clusters": 2,
            "strokes_analyzed": 20,
            "total_strokes": 100,
        }
        result = format_focus_report(metrics)
        self.assertIn("LASER", result)
        self.assertIn("qwen", result)
        self.assertIn("0.850", result)

    def test_scattered_report(self):
        metrics = {
            "writer": "qwen",
            "focus_class": "scattered",
            "focus_score": 0.25,
            "thread_length": 1.5,
            "context_switches": 15,
            "context_switch_rate": 0.75,
            "coherence_score": 0.20,
            "fragmentation_index": 0.85,
            "distinct_clusters": 12,
            "strokes_analyzed": 20,
            "total_strokes": 100,
        }
        result = format_focus_report(metrics)
        self.assertIn("SCATTERED", result)
        self.assertIn("highly fragmented", result)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    """Integration tests with realistic data."""

    def test_realistic_focused_session(self):
        """Simulate a focused writing session."""
        strokes = []
        # Working on writer module
        for i in range(8):
            strokes.append({"files": [f"iamai/writer_part{i}.py"]})
        # Quick test update
        strokes.append({"files": ["tests/test_writer.py"]})
        # Back to writer
        for i in range(5):
            strokes.append({"files": [f"iamai/writer_extra{i}.py"]})
        
        result = compute_focus_metrics(strokes)
        self.assertGreater(result["focus_score"], 0.60)
        self.assertIn(result["focus_class"], ["focused", "laser"])

    def test_realistic_scattered_session(self):
        """Simulate a scattered session with lots of context switching."""
        strokes = []
        areas = ["iamai", "tests", "docs", "tools", "scripts"]
        for i in range(20):
            area = areas[i % len(areas)]
            strokes.append({"files": [f"{area}/file{i}.py"]})
        
        result = compute_focus_metrics(strokes)
        self.assertLess(result["focus_score"], 0.60)
        self.assertGreater(result["context_switch_rate"], 0.50)


if __name__ == "__main__":
    unittest.main()
