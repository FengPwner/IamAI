#!/usr/bin/env python3
"""Tests for writer_idea_topology — 52 test cases."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_idea_topology import (  # noqa: E402
    _clusters_from_stroke,
    _is_bridge_stroke,
    analyze_writer_topology,
    classify_trend,
    compute_topology_metrics,
    compute_topology_trend,
    format_topology_report,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestClustersFromStroke(unittest.TestCase):
    """Test _clusters_from_stroke helper."""

    def test_empty_stroke(self):
        self.assertEqual(_clusters_from_stroke({}), set())

    def test_no_files_key(self):
        self.assertEqual(_clusters_from_stroke({"text": "hello"}), set())

    def test_files_not_list(self):
        self.assertEqual(_clusters_from_stroke({"files": "single.py"}), set())

    def test_single_file_with_subdir(self):
        stroke = {"files": ["iamai/writer.py"]}
        self.assertEqual(_clusters_from_stroke(stroke), {"iamai"})

    def test_multiple_files_same_cluster(self):
        stroke = {"files": ["iamai/writer.py", "iamai/focus.py"]}
        self.assertEqual(_clusters_from_stroke(stroke), {"iamai"})

    def test_multiple_files_different_clusters(self):
        stroke = {"files": ["iamai/writer.py", "tests/test_writer.py"]}
        self.assertEqual(_clusters_from_stroke(stroke), {"iamai", "tests"})

    def test_root_level_file(self):
        stroke = {"files": ["README.md"]}
        self.assertEqual(_clusters_from_stroke(stroke), {"__root__"})

    def test_mixed_root_and_subdir(self):
        stroke = {"files": ["README.md", "iamai/writer.py"]}
        self.assertEqual(_clusters_from_stroke(stroke), {"__root__", "iamai"})

    def test_deeply_nested_file(self):
        stroke = {"files": ["iamai/metrics/deep/focus.py"]}
        self.assertEqual(_clusters_from_stroke(stroke), {"iamai"})

    def test_path_objects(self):
        stroke = {"files": [Path("iamai/writer.py"), Path("tests/test.py")]}
        result = _clusters_from_stroke(stroke)
        self.assertEqual(result, {"iamai", "tests"})

    def test_empty_file_list(self):
        stroke = {"files": []}
        self.assertEqual(_clusters_from_stroke(stroke), set())


class TestIsBridgeStroke(unittest.TestCase):
    """Test _is_bridge_stroke helper."""

    def test_empty_clusters(self):
        self.assertFalse(_is_bridge_stroke(set()))

    def test_single_cluster(self):
        self.assertFalse(_is_bridge_stroke({"iamai"}))

    def test_two_clusters(self):
        self.assertTrue(_is_bridge_stroke({"iamai", "tests"}))

    def test_three_clusters(self):
        self.assertTrue(_is_bridge_stroke({"iamai", "tests", "docs"}))


# ---------------------------------------------------------------------------
# Core metrics computation
# ---------------------------------------------------------------------------

def _make_stroke(files: list[str], writer: str = "qwen") -> dict:
    """Helper to create a minimal stroke record."""
    return {"files": files, "writer": writer}


class TestComputeTopologyMetricsEmpty(unittest.TestCase):
    """Test compute_topology_metrics with empty input."""

    def test_empty_strokes(self):
        m = compute_topology_metrics([])
        self.assertEqual(m["bridge_ratio"], 0.0)
        self.assertEqual(m["concept_density"], 0.0)
        self.assertEqual(m["cross_pollination_index"], 0.0)
        self.assertEqual(m["idea_isolation_ratio"], 1.0)
        self.assertEqual(m["topology_class"], "archipelago")
        self.assertEqual(m["strokes_analyzed"], 0)

    def test_single_stroke_single_cluster(self):
        m = compute_topology_metrics([_make_stroke(["iamai/a.py"])])
        self.assertEqual(m["bridge_ratio"], 0.0)
        self.assertEqual(m["idea_isolation_ratio"], 1.0)
        self.assertEqual(m["strokes_analyzed"], 1)


class TestBridgeRatio(unittest.TestCase):
    """Test bridge_ratio computation."""

    def test_all_bridges(self):
        strokes = [
            _make_stroke(["iamai/a.py", "tests/test_a.py"]),
            _make_stroke(["docs/README.md", "iamai/b.py"]),
            _make_stroke(["scripts/run.sh", "iamai/c.py"]),
        ]
        m = compute_topology_metrics(strokes)
        self.assertEqual(m["bridge_ratio"], 1.0)

    def test_no_bridges(self):
        strokes = [
            _make_stroke(["iamai/a.py"]),
            _make_stroke(["iamai/b.py"]),
            _make_stroke(["tests/test_a.py"]),
        ]
        m = compute_topology_metrics(strokes)
        self.assertEqual(m["bridge_ratio"], 0.0)

    def test_half_bridges(self):
        strokes = [
            _make_stroke(["iamai/a.py", "tests/test_a.py"]),
            _make_stroke(["iamai/b.py"]),
        ]
        m = compute_topology_metrics(strokes)
        self.assertAlmostEqual(m["bridge_ratio"], 0.5)


class TestConceptDensity(unittest.TestCase):
    """Test concept_density computation."""

    def test_single_cluster_strokes(self):
        strokes = [
            _make_stroke(["iamai/a.py"]),
            _make_stroke(["tests/test_a.py"]),
        ]
        m = compute_topology_metrics(strokes)
        self.assertAlmostEqual(m["concept_density"], 1.0)

    def test_multi_cluster_strokes(self):
        strokes = [
            _make_stroke(["iamai/a.py", "tests/test_a.py", "docs/guide.md"]),
        ]
        m = compute_topology_metrics(strokes)
        self.assertAlmostEqual(m["concept_density"], 3.0)


class TestCrossPollinationIndex(unittest.TestCase):
    """Test cross_pollination_index computation."""

    def test_no_cross_pollination(self):
        # All strokes touch single cluster — no bridges at all
        strokes = [
            _make_stroke(["iamai/a.py"]),
            _make_stroke(["iamai/b.py"]),
            _make_stroke(["iamai/c.py"]),
        ]
        m = compute_topology_metrics(strokes)
        self.assertEqual(m["cross_pollination_index"], 0.0)

    def test_full_cross_pollination(self):
        # Every pair of clusters is bridged
        strokes = [
            _make_stroke(["iamai/a.py", "tests/test_a.py"]),
            _make_stroke(["iamai/b.py", "docs/guide.md"]),
            _make_stroke(["tests/test_b.py", "docs/other.md"]),
        ]
        m = compute_topology_metrics(strokes)
        # 3 clusters, 3 possible pairs, 3 bridged pairs => 1.0
        self.assertEqual(m["cross_pollination_index"], 1.0)


class TestIdeaIsolationRatio(unittest.TestCase):
    """Test idea_isolation_ratio computation."""

    def test_all_isolated(self):
        strokes = [
            _make_stroke(["iamai/a.py"]),
            _make_stroke(["tests/test_a.py"]),
            _make_stroke(["docs/readme.md"]),
        ]
        m = compute_topology_metrics(strokes)
        self.assertEqual(m["idea_isolation_ratio"], 1.0)

    def test_none_isolated(self):
        strokes = [
            _make_stroke(["iamai/a.py", "tests/test_a.py"]),
            _make_stroke(["docs/d.md", "iamai/b.py"]),
            _make_stroke(["scripts/s.sh", "tests/t.py"]),
        ]
        m = compute_topology_metrics(strokes)
        self.assertEqual(m["idea_isolation_ratio"], 0.0)


class TestTopologyClassification(unittest.TestCase):
    """Test topology_class assignment."""

    def test_bridge_builder(self):
        # Many bridges, high cross-pollination
        strokes = [
            _make_stroke(["iamai/a.py", "tests/test_a.py", "docs/g.md"]),
            _make_stroke(["iamai/b.py", "tests/test_b.py", "scripts/s.sh"]),
            _make_stroke(["docs/d.md", "scripts/s2.sh", "notes/n.md"]),
            _make_stroke(["iamai/c.py", "notes/n2.md"]),
            _make_stroke(["tests/t.py", "docs/d2.md"]),
        ]
        m = compute_topology_metrics(strokes)
        # Score should be high with all these bridges
        self.assertIn(m["topology_class"], ["bridge_builder", "networker"])

    def test_archipelago(self):
        # All isolated, single cluster
        strokes = [
            _make_stroke(["iamai/a.py"]),
            _make_stroke(["iamai/b.py"]),
            _make_stroke(["iamai/c.py"]),
            _make_stroke(["iamai/d.py"]),
            _make_stroke(["iamai/e.py"]),
        ]
        m = compute_topology_metrics(strokes)
        self.assertEqual(m["topology_class"], "archipelago")

    def test_deep_diver(self):
        # Mix of single cluster with occasional bridge
        strokes = [
            _make_stroke(["iamai/a.py"]),
            _make_stroke(["iamai/b.py"]),
            _make_stroke(["iamai/c.py"]),
            _make_stroke(["iamai/d.py", "tests/test_d.py"]),
            _make_stroke(["iamai/e.py"]),
            _make_stroke(["iamai/f.py"]),
        ]
        m = compute_topology_metrics(strokes)
        self.assertIn(m["topology_class"], ["deep_diver", "archipelago"])


class TestTopologyScoreComponents(unittest.TestCase):
    """Test the composite score formula weights."""

    def test_score_range(self):
        strokes = [
            _make_stroke(["iamai/a.py", "tests/t.py"]),
            _make_stroke(["iamai/b.py"]),
            _make_stroke(["docs/d.md", "iamai/c.py"]),
        ]
        m = compute_topology_metrics(strokes)
        self.assertGreaterEqual(m["topology_score"], 0.0)
        self.assertLessEqual(m["topology_score"], 1.0)

    def test_window_size_respected(self):
        # Create 50 strokes, window=10 should only use last 10
        strokes = []
        for i in range(40):
            strokes.append(_make_stroke(["iamai/a.py"]))
        for i in range(10):
            strokes.append(_make_stroke(["iamai/x.py", "tests/t.py"]))

        m = compute_topology_metrics(strokes, window_size=10)
        self.assertEqual(m["bridge_ratio"], 1.0)
        self.assertEqual(m["strokes_analyzed"], 10)


# ---------------------------------------------------------------------------
# Writer analysis (integration)
# ---------------------------------------------------------------------------

class TestAnalyzeWriterTopology(unittest.TestCase):
    """Test analyze_writer_topology with temp data files."""

    def _write_strokes(self, tmpdir: str, strokes: list[dict]) -> None:
        path = Path(tmpdir) / "strokes.jsonl"
        with open(path, "w") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")

    def test_missing_strokes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m = analyze_writer_topology(data_dir=tmpdir)
            self.assertIn("error", m)

    def test_basic_analysis(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strokes = [
                {"writer": "qwen", "files": ["iamai/a.py", "tests/t.py"]},
                {"writer": "qwen", "files": ["iamai/b.py"]},
                {"writer": "other", "files": ["docs/d.md"]},
            ]
            self._write_strokes(tmpdir, strokes)
            m = analyze_writer_topology(data_dir=tmpdir, writer="qwen")
            self.assertEqual(m["writer"], "qwen")
            self.assertEqual(m["total_strokes"], 2)
            self.assertEqual(m["strokes_analyzed"], 2)

    def test_filters_by_writer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strokes = [
                {"writer": "qwen", "files": ["iamai/a.py"]},
                {"writer": "kimi", "files": ["docs/d.md", "tests/t.py"]},
            ]
            self._write_strokes(tmpdir, strokes)
            m = analyze_writer_topology(data_dir=tmpdir, writer="qwen")
            self.assertEqual(m["total_strokes"], 1)
            self.assertEqual(m["bridge_ratio"], 0.0)

    def test_malformed_json_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "strokes.jsonl"
            with open(path, "w") as f:
                f.write('{"writer":"qwen","files":["iamai/a.py"]}\n')
                f.write("this is not json\n")
                f.write('{"writer":"qwen","files":["tests/t.py"]}\n')
            m = analyze_writer_topology(data_dir=tmpdir, writer="qwen")
            self.assertEqual(m["total_strokes"], 2)


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

class TestFormatTopologyReport(unittest.TestCase):
    """Test format_topology_report output."""

    def test_error_report(self):
        m = {"error": "strokes.jsonl not found"}
        r = format_topology_report(m)
        self.assertIn("Error", r)

    def test_bridge_builder_report(self):
        m = {
            "writer": "qwen",
            "topology_class": "bridge_builder",
            "topology_score": 0.85,
            "bridge_ratio": 0.7,
            "total_bridges": 14,
            "new_bridges": 5,
            "bridged_pairs": 8,
            "concept_density": 2.3,
            "unique_clusters": 5,
            "cross_pollination_index": 0.9,
            "idea_isolation_ratio": 0.1,
            "strokes_analyzed": 20,
            "total_strokes": 100,
        }
        r = format_topology_report(m)
        self.assertIn("BRIDGE_BUILDER", r)
        self.assertIn("synthesizer", r)

    def test_networker_report(self):
        m = {
            "writer": "qwen",
            "topology_class": "networker",
            "topology_score": 0.6,
            "bridge_ratio": 0.4,
            "total_bridges": 8,
            "new_bridges": 3,
            "bridged_pairs": 4,
            "concept_density": 1.8,
            "unique_clusters": 4,
            "cross_pollination_index": 0.5,
            "idea_isolation_ratio": 0.3,
            "strokes_analyzed": 20,
            "total_strokes": 50,
        }
        r = format_topology_report(m)
        self.assertIn("NETWORKER", r)

    def test_deep_diver_report(self):
        m = {
            "writer": "qwen",
            "topology_class": "deep_diver",
            "topology_score": 0.4,
            "bridge_ratio": 0.2,
            "total_bridges": 4,
            "new_bridges": 1,
            "bridged_pairs": 1,
            "concept_density": 1.2,
            "unique_clusters": 2,
            "cross_pollination_index": 0.2,
            "idea_isolation_ratio": 0.6,
            "strokes_analyzed": 20,
            "total_strokes": 30,
        }
        r = format_topology_report(m)
        self.assertIn("DEEP_DIVER", r)

    def test_archipelago_report(self):
        m = {
            "writer": "qwen",
            "topology_class": "archipelago",
            "topology_score": 0.15,
            "bridge_ratio": 0.0,
            "total_bridges": 0,
            "new_bridges": 0,
            "bridged_pairs": 0,
            "concept_density": 1.0,
            "unique_clusters": 1,
            "cross_pollination_index": 0.0,
            "idea_isolation_ratio": 1.0,
            "strokes_analyzed": 10,
            "total_strokes": 10,
        }
        r = format_topology_report(m)
        self.assertIn("ARCHIPELAGO", r)
        self.assertIn("isolated islands", r)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

class TestComputeTopologyTrend(unittest.TestCase):
    """Test compute_topology_trend sliding window."""

    def test_too_few_strokes(self):
        strokes = [_make_stroke(["iamai/a.py"])]
        snapshots = compute_topology_trend(strokes, window_size=10)
        self.assertEqual(len(snapshots), 1)

    def test_multiple_windows(self):
        strokes = []
        for i in range(30):
            strokes.append(_make_stroke(["iamai/a.py", "tests/t.py"]))
        snapshots = compute_topology_trend(strokes, window_size=10, step=10)
        self.assertGreater(len(snapshots), 1)


class TestClassifyTrend(unittest.TestCase):
    """Test classify_trend from snapshots."""

    def test_insufficient_data(self):
        self.assertEqual(classify_trend([]), "insufficient_data")
        self.assertEqual(classify_trend([{"topology_score": 0.5}]), "insufficient_data")

    def test_increasing(self):
        snapshots = [
            {"topology_score": 0.2},
            {"topology_score": 0.3},
            {"topology_score": 0.6},
            {"topology_score": 0.7},
        ]
        self.assertEqual(classify_trend(snapshots), "increasing")

    def test_decreasing(self):
        snapshots = [
            {"topology_score": 0.8},
            {"topology_score": 0.7},
            {"topology_score": 0.3},
            {"topology_score": 0.2},
        ]
        self.assertEqual(classify_trend(snapshots), "decreasing")

    def test_stable(self):
        snapshots = [
            {"topology_score": 0.5},
            {"topology_score": 0.52},
            {"topology_score": 0.48},
            {"topology_score": 0.51},
        ]
        self.assertEqual(classify_trend(snapshots), "stable")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Edge cases for robustness."""

    def test_stroke_with_empty_files_list(self):
        strokes = [
            _make_stroke([]),
            _make_stroke(["iamai/a.py"]),
        ]
        m = compute_topology_metrics(strokes)
        self.assertEqual(m["strokes_analyzed"], 2)

    def test_all_strokes_empty_files(self):
        strokes = [_make_stroke([]) for _ in range(5)]
        m = compute_topology_metrics(strokes)
        self.assertEqual(m["bridge_ratio"], 0.0)
        self.assertEqual(m["concept_density"], 0.0)

    def test_very_large_window(self):
        strokes = [
            _make_stroke(["iamai/a.py", "tests/t.py"]),
            _make_stroke(["iamai/b.py"]),
        ]
        m = compute_topology_metrics(strokes, window_size=1000)
        # Should just use all available strokes
        self.assertEqual(m["strokes_analyzed"], 2)

    def test_duplicate_clusters_in_stroke(self):
        # Two files in same cluster — still one cluster
        strokes = [_make_stroke(["iamai/a.py", "iamai/b.py", "iamai/c.py"])]
        m = compute_topology_metrics(strokes)
        self.assertEqual(m["unique_clusters"], 1)
        self.assertEqual(m["bridge_ratio"], 0.0)


if __name__ == "__main__":
    unittest.main()
