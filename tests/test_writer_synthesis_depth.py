#!/usr/bin/env python3
"""Tests for writer_synthesis_depth — 52 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_synthesis_depth import (  # noqa: E402
    _classify,
    _prior_source_set,
    _stroke_cluster,
    _stroke_files,
    _stroke_refs,
    analyze_writer_synthesis,
    classify_trend,
    compute_synthesis_metrics,
    compute_synthesis_trend,
    format_synthesis_report,
)


# ---------------------------------------------------------------------------
# Helper: _stroke_refs
# ---------------------------------------------------------------------------

class TestStrokeRefs(unittest.TestCase):
    """Test _stroke_refs helper."""

    def test_empty_stroke(self):
        self.assertEqual(_stroke_refs({}), set())

    def test_references_list(self):
        stroke = {"references": ["stroke_1", "stroke_2"]}
        self.assertEqual(_stroke_refs(stroke), {"stroke_1", "stroke_2"})

    def test_sources_list(self):
        stroke = {"sources": ["file_a.py", "file_b.py"]}
        self.assertEqual(_stroke_refs(stroke), {"file_a.py", "file_b.py"})

    def test_areas_list(self):
        stroke = {"areas": ["metrics", "testing"]}
        self.assertEqual(_stroke_refs(stroke), {"metrics", "testing"})

    def test_clusters_list(self):
        stroke = {"clusters": ["writer_health", "cadence"]}
        self.assertEqual(_stroke_refs(stroke), {"writer_health", "cadence"})

    def test_refs_key(self):
        stroke = {"refs": ["ref1", "ref2"]}
        self.assertEqual(_stroke_refs(stroke), {"ref1", "ref2"})

    def test_string_reference(self):
        stroke = {"references": "single_ref"}
        self.assertEqual(_stroke_refs(stroke), {"single_ref"})

    def test_int_reference(self):
        stroke = {"references": [1, 2, 3]}
        self.assertEqual(_stroke_refs(stroke), {"1", "2", "3"})

    def test_empty_strings_filtered(self):
        stroke = {"references": ["", "  "]}
        self.assertEqual(_stroke_refs(stroke), set())

    def test_duplicate_refs(self):
        stroke = {"references": ["a", "a"]}
        self.assertEqual(_stroke_refs(stroke), {"a"})

    def test_non_list_ignored(self):
        stroke = {"references": {"not": "a list"}}
        self.assertEqual(_stroke_refs(stroke), set())

    def test_mixed_keys(self):
        stroke = {"references": ["a"], "sources": ["b"], "areas": ["c"]}
        self.assertEqual(_stroke_refs(stroke), {"a", "b", "c"})


# ---------------------------------------------------------------------------
# Helper: _stroke_files
# ---------------------------------------------------------------------------

class TestStrokeFiles(unittest.TestCase):
    """Test _stroke_files helper."""

    def test_empty(self):
        self.assertEqual(_stroke_files({}), set())

    def test_list_of_strings(self):
        stroke = {"files": ["a.py", "b.py"]}
        self.assertEqual(_stroke_files(stroke), {"a.py", "b.py"})

    def test_list_of_paths(self):
        stroke = {"files": [Path("a.py"), Path("b.py")]}
        result = _stroke_files(stroke)
        self.assertEqual(result, {"a.py", "b.py"})

    def test_non_list(self):
        stroke = {"files": "not a list"}
        self.assertEqual(_stroke_files(stroke), set())

    def test_mixed_types(self):
        stroke = {"files": ["a.py", Path("b.py"), 42]}
        result = _stroke_files(stroke)
        self.assertEqual(result, {"a.py", "b.py"})


# ---------------------------------------------------------------------------
# Helper: _stroke_cluster
# ---------------------------------------------------------------------------

class TestStrokeCluster(unittest.TestCase):
    """Test _stroke_cluster helper."""

    def test_empty(self):
        self.assertIsNone(_stroke_cluster({}))

    def test_cluster_key(self):
        self.assertEqual(_stroke_cluster({"cluster": "health"}), "health")

    def test_area_key(self):
        self.assertEqual(_stroke_cluster({"area": "metrics"}), "metrics")

    def test_topic_key(self):
        self.assertEqual(_stroke_cluster({"topic": "cadence"}), "cadence")

    def test_category_key(self):
        self.assertEqual(_stroke_cluster({"category": "tools"}), "tools")

    def test_empty_string(self):
        self.assertIsNone(_stroke_cluster({"cluster": ""}))

    def test_whitespace_only(self):
        self.assertIsNone(_stroke_cluster({"cluster": "  "}))

    def test_non_string(self):
        self.assertIsNone(_stroke_cluster({"cluster": 42}))


# ---------------------------------------------------------------------------
# Helper: _prior_source_set
# ---------------------------------------------------------------------------

class TestPriorSourceSet(unittest.TestCase):
    """Test _prior_source_set helper."""

    def test_empty_strokes(self):
        self.assertEqual(_prior_source_set([], 0, 3), set())

    def test_lookback_larger_than_available(self):
        strokes = [{"files": ["a.py"]}]
        result = _prior_source_set(strokes, 1, 5)
        self.assertEqual(result, {"a.py"})

    def test_exact_lookback(self):
        strokes = [
            {"files": ["a.py"]},
            {"files": ["b.py"]},
            {"files": ["c.py"]},
        ]
        result = _prior_source_set(strokes, 3, 3)
        self.assertEqual(result, {"a.py", "b.py", "c.py"})

    def test_includes_clusters(self):
        strokes = [{"cluster": "health", "files": ["a.py"]}]
        result = _prior_source_set(strokes, 1, 3)
        self.assertIn("cluster:health", result)
        self.assertIn("a.py", result)

    def test_includes_references(self):
        strokes = [{"references": ["ref1", "ref2"]}]
        result = _prior_source_set(strokes, 1, 3)
        self.assertEqual(result, {"ref1", "ref2"})


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify(unittest.TestCase):
    """Test _classify function."""

    def test_deep_synthesizer(self):
        self.assertEqual(_classify(0.70), "deep_synthesizer")
        self.assertEqual(_classify(0.85), "deep_synthesizer")
        self.assertEqual(_classify(1.0), "deep_synthesizer")

    def test_compiler(self):
        self.assertEqual(_classify(0.50), "compiler")
        self.assertEqual(_classify(0.69), "compiler")

    def test_aggregator(self):
        self.assertEqual(_classify(0.30), "aggregator")
        self.assertEqual(_classify(0.49), "aggregator")

    def test_collager(self):
        self.assertEqual(_classify(0.0), "collager")
        self.assertEqual(_classify(0.29), "collager")
        self.assertEqual(_classify(0.15), "collager")


# ---------------------------------------------------------------------------
# Core: compute_synthesis_metrics
# ---------------------------------------------------------------------------

class TestComputeSynthesisMetrics(unittest.TestCase):
    """Test compute_synthesis_metrics."""

    def test_empty_strokes(self):
        m = compute_synthesis_metrics([])
        self.assertEqual(m["strokes_analyzed"], 0)
        self.assertEqual(m["synthesis_class"], "collager")
        self.assertEqual(m["isolation_ratio"], 1.0)

    def test_single_stroke_with_refs(self):
        m = compute_synthesis_metrics([{"references": ["a", "b"]}])
        self.assertEqual(m["strokes_analyzed"], 1)
        self.assertEqual(m["isolation_ratio"], 0.0)

    def test_single_stroke_empty(self):
        m = compute_synthesis_metrics([{}])
        self.assertEqual(m["strokes_analyzed"], 1)
        self.assertEqual(m["isolation_ratio"], 1.0)
        self.assertEqual(m["synthesis_class"], "collager")

    def test_two_strokes_with_file_overlap(self):
        strokes = [
            {"files": ["a.py", "b.py"], "cluster": "tools"},
            {"files": ["a.py", "c.py"], "cluster": "tools"},
        ]
        m = compute_synthesis_metrics(strokes)
        self.assertEqual(m["strokes_analyzed"], 2)
        # Second stroke overlaps file "a.py" with first
        self.assertGreater(m["synthesis_score"], 0.0)

    def test_isolated_strokes(self):
        strokes = [
            {"files": ["a.py"], "cluster": "tools"},
            {"files": ["b.py"], "cluster": "docs"},
            {"files": ["c.py"], "cluster": "tests"},
        ]
        m = compute_synthesis_metrics(strokes)
        # Each stroke is isolated from prior
        self.assertGreater(m["isolation_ratio"], 0.0)

    def test_highly_connected_strokes(self):
        strokes = []
        for i in range(10):
            strokes.append({
                "files": ["shared.py", f"file_{i}.py"],
                "references": [f"ref_{max(0, i-1)}", f"ref_{max(0, i-2)}"],
                "cluster": "core",
            })
        m = compute_synthesis_metrics(strokes)
        self.assertGreater(m["cross_reference_rate"], 0.0)
        self.assertGreater(m["integration_index"], 0.0)

    def test_window_size_truncation(self):
        strokes = [
            {"files": [f"file_{i}.py"]} for i in range(50)
        ]
        m = compute_synthesis_metrics(strokes, window_size=10)
        self.assertEqual(m["strokes_analyzed"], 10)

    def test_lookback_parameter(self):
        strokes = [
            {"files": ["a.py"], "references": ["init"]},
            {"files": ["b.py"]},
            {"files": ["c.py"]},
            {"files": ["a.py"]},  # overlaps with stroke 0
        ]
        m_small = compute_synthesis_metrics(strokes, lookback=1)
        m_large = compute_synthesis_metrics(strokes, lookback=5)
        # Larger lookback should find more potential sources
        self.assertGreaterEqual(m_large["integration_index"], m_small["integration_index"])

    def test_synthesis_density_zero_when_no_prior(self):
        strokes = [{"files": ["a.py"]}, {"files": ["b.py"]}]
        m = compute_synthesis_metrics(strokes)
        # Both strokes have no prior sources to reference
        self.assertEqual(m["synthesis_density"], 0.0)

    def test_all_keys_present(self):
        m = compute_synthesis_metrics([{"files": ["a.py"]}])
        expected_keys = {
            "cross_reference_rate", "integration_index", "synthesis_density",
            "isolation_ratio", "synthesis_score", "synthesis_class",
            "strokes_analyzed", "areas_count",
        }
        self.assertTrue(expected_keys.issubset(set(m.keys())))

    def test_explicit_references_boost_score(self):
        isolated = [
            {"files": [f"f{i}.py"]} for i in range(5)
        ]
        connected = [
            {"files": [f"f{i}.py"], "references": [f"f{max(0,i-1)}.py", f"f{max(0,i-2)}.py"]}
            for i in range(5)
        ]
        m_iso = compute_synthesis_metrics(isolated)
        m_con = compute_synthesis_metrics(connected)
        self.assertGreater(m_con["synthesis_score"], m_iso["synthesis_score"])

    def test_mixed_clusters_increase_density(self):
        strokes = [
            {"files": ["a.py"], "cluster": "tools"},
            {"files": ["b.py"], "cluster": "docs"},
            {"files": ["a.py", "b.py"], "cluster": "tools", "references": ["b.py"]},
            {"files": ["c.py", "a.py"], "cluster": "tests", "references": ["a.py"]},
        ]
        m = compute_synthesis_metrics(strokes, lookback=3)
        self.assertGreater(m["synthesis_density"], 0.0)


# ---------------------------------------------------------------------------
# analyze_writer_synthesis
# ---------------------------------------------------------------------------

class TestAnalyzeWriterSynthesis(unittest.TestCase):
    """Test analyze_writer_synthesis convenience wrapper."""

    def test_returns_report(self):
        strokes = [
            {"files": ["a.py"], "cluster": "tools"},
            {"files": ["b.py"], "cluster": "docs"},
        ]
        result = analyze_writer_synthesis(strokes)
        self.assertIn("report", result)
        self.assertIsInstance(result["report"], str)

    def test_report_contains_metrics(self):
        strokes = [
            {"files": ["a.py"]},
            {"files": ["a.py", "b.py"]},
        ]
        result = analyze_writer_synthesis(strokes)
        report = result["report"]
        self.assertIn("cross_reference_rate", report)
        self.assertIn("integration_index", report)
        self.assertIn("synthesis_density", report)
        self.assertIn("isolation_ratio", report)
        self.assertIn("Synthesis score", report)

    def test_empty_input(self):
        result = analyze_writer_synthesis([])
        self.assertEqual(result["synthesis_class"], "collager")
        self.assertIn("report", result)


# ---------------------------------------------------------------------------
# format_synthesis_report
# ---------------------------------------------------------------------------

class TestFormatSynthesisReport(unittest.TestCase):
    """Test format_synthesis_report."""

    def test_basic_format(self):
        metrics = {
            "strokes_analyzed": 20,
            "areas_count": 15,
            "cross_reference_rate": 0.45,
            "integration_index": 2.3,
            "synthesis_density": 0.38,
            "isolation_ratio": 0.25,
            "synthesis_score": 0.55,
            "synthesis_class": "compiler",
        }
        report = format_synthesis_report(metrics)
        self.assertIn("Writer Synthesis Depth Report", report)
        self.assertIn("20", report)
        self.assertIn("compiler", report)
        self.assertIn("0.5500", report)

    def test_report_multiline(self):
        metrics = {
            "strokes_analyzed": 10,
            "areas_count": 5,
            "cross_reference_rate": 0.5,
            "integration_index": 1.0,
            "synthesis_density": 0.3,
            "isolation_ratio": 0.2,
            "synthesis_score": 0.4,
            "synthesis_class": "aggregator",
        }
        report = format_synthesis_report(metrics)
        lines = report.split("\n")
        self.assertGreater(len(lines), 5)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

class TestComputeSynthesisTrend(unittest.TestCase):
    """Test compute_synthesis_trend."""

    def test_empty(self):
        t = compute_synthesis_trend([])
        self.assertEqual(t["direction"], "insufficient_data")

    def test_single_snapshot(self):
        t = compute_synthesis_trend([{"synthesis_score": 0.5}])
        self.assertEqual(t["direction"], "insufficient_data")

    def test_increasing(self):
        snapshots = [
            {"synthesis_score": 0.3},
            {"synthesis_score": 0.5},
            {"synthesis_score": 0.7},
        ]
        t = compute_synthesis_trend(snapshots)
        self.assertEqual(t["direction"], "increasing")
        self.assertAlmostEqual(t["delta"], 0.4, places=3)

    def test_decreasing(self):
        snapshots = [
            {"synthesis_score": 0.7},
            {"synthesis_score": 0.4},
            {"synthesis_score": 0.2},
        ]
        t = compute_synthesis_trend(snapshots)
        self.assertEqual(t["direction"], "decreasing")
        self.assertAlmostEqual(t["delta"], -0.5, places=3)

    def test_stable(self):
        snapshots = [
            {"synthesis_score": 0.5},
            {"synthesis_score": 0.52},
            {"synthesis_score": 0.49},
        ]
        t = compute_synthesis_trend(snapshots)
        self.assertEqual(t["direction"], "stable")

    def test_snapshot_count(self):
        snapshots = [
            {"synthesis_score": 0.3},
            {"synthesis_score": 0.5},
        ]
        t = compute_synthesis_trend(snapshots)
        self.assertEqual(t["snapshots"], 2)

    def test_first_and_last_score(self):
        snapshots = [
            {"synthesis_score": 0.3},
            {"synthesis_score": 0.5},
            {"synthesis_score": 0.8},
        ]
        t = compute_synthesis_trend(snapshots)
        self.assertEqual(t["first_score"], 0.3)
        self.assertEqual(t["last_score"], 0.8)


class TestClassifyTrend(unittest.TestCase):
    """Test classify_trend convenience function."""

    def test_increasing(self):
        snapshots = [
            {"synthesis_score": 0.2},
            {"synthesis_score": 0.8},
        ]
        self.assertEqual(classify_trend(snapshots), "increasing")

    def test_decreasing(self):
        snapshots = [
            {"synthesis_score": 0.8},
            {"synthesis_score": 0.2},
        ]
        self.assertEqual(classify_trend(snapshots), "decreasing")

    def test_stable(self):
        snapshots = [
            {"synthesis_score": 0.5},
            {"synthesis_score": 0.52},
        ]
        self.assertEqual(classify_trend(snapshots), "stable")

    def test_insufficient(self):
        self.assertEqual(classify_trend([]), "insufficient_data")


# ---------------------------------------------------------------------------
# Edge cases and integration
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Integration and edge case tests."""

    def test_deep_synthesizer_scenario(self):
        """A writer that cross-references heavily should classify as deep_synthesizer."""
        strokes = []
        shared_files = ["core.py", "metrics.py", "notes.md"]
        for i in range(20):
            strokes.append({
                "files": [shared_files[i % 3], f"feature_{i}.py"],
                "references": [f"stroke_{max(0, i-1)}", f"stroke_{max(0, i-2)}", f"stroke_{max(0, i-3)}"],
                "cluster": "core",
            })
        m = compute_synthesis_metrics(strokes, lookback=5)
        self.assertEqual(m["synthesis_class"], "deep_synthesizer")

    def test_collager_scenario(self):
        """A writer with completely isolated strokes should classify as collager."""
        strokes = [
            {"files": [f"unique_{i}.py"], "cluster": f"area_{i}"}
            for i in range(20)
        ]
        m = compute_synthesis_metrics(strokes, lookback=5)
        self.assertEqual(m["synthesis_class"], "collager")

    def test_large_window(self):
        """Large window with few strokes should still work."""
        strokes = [
            {"files": ["a.py"], "references": ["init"]},
            {"files": ["b.py"]},
        ]
        m = compute_synthesis_metrics(strokes, window_size=100)
        self.assertEqual(m["strokes_analyzed"], 2)

    def test_stroke_with_all_key_types(self):
        """Stroke with references, sources, areas, clusters, and files."""
        strokes = [
            {
                "files": ["a.py"],
                "references": ["ref1"],
                "sources": ["src1"],
                "areas": ["area1"],
                "clusters": ["cl1"],
                "cluster": "main",
            },
            {
                "files": ["a.py", "b.py"],
                "references": ["ref1", "ref2"],
                "sources": ["src1", "src2"],
                "areas": ["area1"],
                "clusters": ["cl1", "cl2"],
                "cluster": "main",
            },
        ]
        m = compute_synthesis_metrics(strokes, lookback=3)
        self.assertGreater(m["synthesis_score"], 0.0)
        self.assertGreater(m["areas_count"], 0)


if __name__ == "__main__":
    unittest.main()
