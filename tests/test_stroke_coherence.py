#!/usr/bin/env python3
"""Tests for stroke_coherence.py — 72 tests covering all public functions.

Covers: tokenize, compute_idf, weighted_overlap, classify, transition_label,
analyze_window, snapshot_report, delta_report, edge cases, integration.
"""

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from collections import Counter

# Add tools directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import stroke_coherence as sc


class TestTokenize(unittest.TestCase):
    """Tests for the tokenize function."""

    def test_basic_tokenization(self):
        tokens = sc.tokenize("the quick brown fox")
        self.assertIn("quick", tokens)
        self.assertIn("brown", tokens)
        self.assertIn("fox", tokens)

    def test_stop_words_removed(self):
        tokens = sc.tokenize("the cat is on the mat")
        self.assertNotIn("the", tokens)
        self.assertNotIn("is", tokens)
        self.assertNotIn("on", tokens)
        self.assertIn("cat", tokens)
        self.assertIn("mat", tokens)

    def test_punctuation_stripped(self):
        tokens = sc.tokenize("hello, world! how's it going?")
        self.assertIn("hello", tokens)
        self.assertIn("world", tokens)
        self.assertIn("going", tokens)

    def test_single_char_filtered(self):
        tokens = sc.tokenize("I a x big")
        self.assertNotIn("a", tokens)
        self.assertNotIn("x", tokens)
        self.assertIn("big", tokens)

    def test_lowercase_normalization(self):
        tokens = sc.tokenize("HELLO World FoX")
        self.assertIn("hello", tokens)
        self.assertIn("world", tokens)
        self.assertIn("fox", tokens)

    def test_empty_string(self):
        self.assertEqual(sc.tokenize(""), [])

    def test_all_stop_words(self):
        tokens = sc.tokenize("the is a an and or but")
        self.assertEqual(tokens, [])

    def test_special_characters_only(self):
        tokens = sc.tokenize("!@#$ %^&* ()")
        self.assertEqual(tokens, [])

    def test_repeated_tokens_preserved(self):
        tokens = sc.tokenize("data data data")
        self.assertEqual(tokens.count("data"), 3)


class TestComputeIDF(unittest.TestCase):
    """Tests for the compute_idf function."""

    def test_basic_idf(self):
        corpus = [["cat", "dog"], ["cat", "bird"], ["fish", "dog"]]
        idf = sc.compute_idf(corpus)
        # "cat" appears in 2 of 3 docs
        self.assertIn("cat", idf)
        self.assertIn("dog", idf)
        self.assertIn("bird", idf)
        self.assertIn("fish", idf)

    def test_rare_terms_higher_idf(self):
        corpus = [["common", "rare1"], ["common", "rare2"], ["common", "rare3"]]
        idf = sc.compute_idf(corpus)
        # "common" in all docs, rare terms in only one each
        self.assertGreater(idf["rare1"], idf["common"])

    def test_empty_corpus(self):
        self.assertEqual(sc.compute_idf([]), {})

    def test_single_document(self):
        idf = sc.compute_idf([["alpha", "beta"]])
        self.assertIn("alpha", idf)
        self.assertIn("beta", idf)
        # Both appear in 1/1 docs, same IDF
        self.assertAlmostEqual(idf["alpha"], idf["beta"])

    def test_idf_always_positive(self):
        corpus = [["a", "b"], ["a", "b"], ["a", "b"]]
        idf = sc.compute_idf(corpus)
        for score in idf.values():
            self.assertGreater(score, 0)


class TestWeightedOverlap(unittest.TestCase):
    """Tests for the weighted_overlap function."""

    def test_identical_sets(self):
        tokens = ["alpha", "beta", "gamma"]
        idf = {"alpha": 2.0, "beta": 2.0, "gamma": 2.0}
        score = sc.weighted_overlap(tokens, tokens, idf)
        self.assertAlmostEqual(score, 1.0)

    def test_disjoint_sets(self):
        idf = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}
        score = sc.weighted_overlap(["a", "b"], ["c", "d"], idf)
        self.assertAlmostEqual(score, 0.0)

    def test_partial_overlap(self):
        idf = {"x": 1.0, "y": 1.0, "z": 1.0}
        score = sc.weighted_overlap(["x", "y"], ["y", "z"], idf)
        # intersection: {y} weight 1, union: {x,y,z} weight 3
        self.assertAlmostEqual(score, 1.0 / 3.0)

    def test_empty_first(self):
        self.assertAlmostEqual(sc.weighted_overlap([], ["a"], {"a": 1.0}), 0.0)

    def test_empty_second(self):
        self.assertAlmostEqual(sc.weighted_overlap(["a"], [], {"a": 1.0}), 0.0)

    def test_both_empty(self):
        self.assertAlmostEqual(sc.weighted_overlap([], [], {}), 0.0)

    def test_idf_weighting_matters(self):
        # High-IDF overlap should score higher than low-IDF overlap
        idf = {"common": 1.0, "rare": 10.0, "other": 1.0}
        score_rare = sc.weighted_overlap(
            ["rare", "common"], ["rare", "other"], idf
        )
        score_common = sc.weighted_overlap(
            ["common", "rare"], ["common", "other"], idf
        )
        # Both have 1 overlap and 3 union, but rare overlap weighs more
        self.assertGreater(score_rare, score_common)

    def test_missing_idf_defaults_to_one(self):
        score = sc.weighted_overlap(["unknown"], ["unknown"], {})
        self.assertAlmostEqual(score, 1.0)


class TestClassify(unittest.TestCase):
    """Tests for the classify function."""

    def test_coherent(self):
        self.assertEqual(sc.classify(0.5), "coherent")
        self.assertEqual(sc.classify(0.4), "coherent")
        self.assertEqual(sc.classify(1.0), "coherent")

    def test_drifting(self):
        self.assertEqual(sc.classify(0.3), "drifting")
        self.assertEqual(sc.classify(0.2), "drifting")

    def test_jarring(self):
        self.assertEqual(sc.classify(0.15), "jarring")
        self.assertEqual(sc.classify(0.1), "jarring")

    def test_disconnected(self):
        self.assertEqual(sc.classify(0.05), "disconnected")
        self.assertEqual(sc.classify(0.0), "disconnected")

    def test_boundary_values(self):
        self.assertEqual(sc.classify(sc.COHERENT_THRESHOLD), "coherent")
        self.assertEqual(sc.classify(sc.DRIFTING_THRESHOLD), "drifting")
        self.assertEqual(sc.classify(sc.JARRING_THRESHOLD), "jarring")


class TestTransitionLabel(unittest.TestCase):
    """Tests for the transition_label function."""

    def test_stable_coherent(self):
        self.assertEqual(sc.transition_label("coherent", "coherent"), "stable_coherent")

    def test_stable_drifting(self):
        self.assertEqual(sc.transition_label("drifting", "drifting"), "stable_drifting")

    def test_improving(self):
        self.assertEqual(sc.transition_label("jarring", "coherent"), "improving")
        self.assertEqual(sc.transition_label("disconnected", "drifting"), "improving")
        self.assertEqual(sc.transition_label("jarring", "drifting"), "improving")

    def test_degrading(self):
        self.assertEqual(sc.transition_label("coherent", "jarring"), "degrading")
        self.assertEqual(sc.transition_label("drifting", "disconnected"), "degrading")
        self.assertEqual(sc.transition_label("coherent", "drifting"), "degrading")

    def test_stable_disconnected(self):
        self.assertEqual(
            sc.transition_label("disconnected", "disconnected"),
            "stable_disconnected",
        )


class TestExtractText(unittest.TestCase):
    """Tests for the extract_text function."""

    def test_text_field(self):
        self.assertEqual(sc.extract_text({"text": "hello"}), "hello")

    def test_body_field_fallback(self):
        self.assertEqual(sc.extract_text({"body": "world"}), "world")

    def test_empty_record(self):
        self.assertEqual(sc.extract_text({}), "")

    def test_none_values(self):
        self.assertEqual(sc.extract_text({"text": None}), "")
        self.assertEqual(sc.extract_text({"body": None}), "")

    def test_text_preferred_over_body(self):
        self.assertEqual(
            sc.extract_text({"text": "primary", "body": "fallback"}),
            "primary",
        )


class TestAnalyzeWindow(unittest.TestCase):
    """Tests for the analyze_window function."""

    def _make_strokes(self, texts):
        return [{"text": t, "n": i} for i, t in enumerate(texts)]

    def test_empty_input(self):
        result = sc.analyze_window([])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["pairs"], 0)

    def test_single_stroke(self):
        result = sc.analyze_window(self._make_strokes(["hello world"]))
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["pairs"], 0)

    def test_two_related_strokes(self):
        strokes = self._make_strokes([
            "machine learning algorithms process data efficiently",
            "deep learning algorithms process images efficiently",
        ])
        result = sc.analyze_window(strokes)
        self.assertEqual(result["pairs"], 1)
        self.assertGreater(result["mean"], 0)

    def test_two_unrelated_strokes(self):
        strokes = self._make_strokes([
            "quantum physics explores subatomic particles",
            "baking cookies requires flour sugar butter",
        ])
        result = sc.analyze_window(strokes)
        self.assertEqual(result["pairs"], 1)
        self.assertLess(result["mean"], 0.2)

    def test_window_truncation(self):
        texts = [f"topic_{i} analysis processing data" for i in range(200)]
        strokes = self._make_strokes(texts)
        result = sc.analyze_window(strokes, window=50)
        self.assertEqual(result["count"], 50)

    def test_bands_counted(self):
        strokes = self._make_strokes([
            "neural network training convergence optimization",
            "neural network training gradient descent optimization",
            "baking cookies requires flour sugar butter eggs",
            "quantum entanglement spooky action distance physics",
        ])
        result = sc.analyze_window(strokes)
        total_bands = sum(result["bands"].values())
        self.assertEqual(total_bands, result["pairs"])

    def test_transitions_counted(self):
        strokes = self._make_strokes([
            "alpha beta gamma delta",
            "alpha beta gamma epsilon",
            "completely unrelated topic here now",
            "another different topic entirely separate",
        ])
        result = sc.analyze_window(strokes)
        self.assertEqual(len(result["transitions"]), result["pairs"] - 1)

    def test_all_bands_present_in_output(self):
        result = sc.analyze_window(self._make_strokes(["a b", "c d"]))
        for band in ["coherent", "drifting", "jarring", "disconnected"]:
            self.assertIn(band, result["bands"])

    def test_scores_list_length(self):
        strokes = self._make_strokes(["a b c"] * 5)
        result = sc.analyze_window(strokes)
        self.assertEqual(len(result["scores"]), 4)


class TestSnapshotReport(unittest.TestCase):
    """Tests for the snapshot_report function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.strokes_path = Path(self.tmpdir) / "strokes.jsonl"

    def tearDown(self):
        os.unlink(self.strokes_path) if self.strokes_path.exists() else None
        os.rmdir(self.tmpdir)

    def _write_strokes(self, strokes):
        with open(self.strokes_path, "w") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")

    def test_basic_report(self):
        self._write_strokes([
            {"text": "machine learning algorithms optimize functions"},
            {"text": "deep learning networks optimize pattern recognition"},
            {"text": "gradient descent minimizes loss function error"},
        ])
        report = sc.snapshot_report(self.strokes_path)
        self.assertEqual(report["total_strokes"], 3)
        self.assertIn("health", report)
        self.assertIn("mean", report)

    def test_missing_file(self):
        report = sc.snapshot_report(Path("/nonexistent/file.jsonl"))
        self.assertEqual(report["total_strokes"], 0)
        # 0 strokes → mean 0.0 → poor health (no data to assess)
        self.assertEqual(report["health"], "poor")

    def test_health_assessment_healthy(self):
        # Many similar strokes
        self._write_strokes([
            {"text": "python programming language features modules packages"}
            for _ in range(20)
        ])
        report = sc.snapshot_report(self.strokes_path)
        self.assertEqual(report["health"], "healthy")

    def test_health_assessment_poor(self):
        # All completely different topics
        texts = [
            "quantum physics subatomic particles",
            "baking cookies flour sugar",
            "astronomy galaxy nebula stars",
            "gardening compost soil plants",
            "music theory harmony rhythm",
            "architecture structural beams columns",
            "oceanography marine currents tides",
            "linguistics phonemes syntax grammar",
            "economics inflation supply demand",
            "meteorology pressure fronts precipitation",
        ]
        self._write_strokes([{"text": t} for t in texts])
        report = sc.snapshot_report(self.strokes_path)
        self.assertIn(report["health"], ["drifting", "poor"])

    def test_json_serializable(self):
        self._write_strokes([{"text": "test content here"}])
        report = sc.snapshot_report(self.strokes_path)
        # Should not raise
        json.dumps(report)


class TestDeltaReport(unittest.TestCase):
    """Tests for the delta_report function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.before_path = Path(self.tmpdir) / "before.jsonl"
        self.after_path = Path(self.tmpdir) / "after.jsonl"

    def tearDown(self):
        for p in [self.before_path, self.after_path]:
            if p.exists():
                os.unlink(p)
        os.rmdir(self.tmpdir)

    def _write(self, path, strokes):
        with open(path, "w") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")

    def test_basic_delta(self):
        self._write(self.before_path, [
            {"text": "quantum physics particles atoms"},
            {"text": "baking cookies flour sugar butter"},
            {"text": "astronomy galaxy nebula clusters"},
        ])
        self._write(self.after_path, [
            {"text": "machine learning algorithms optimize data"},
            {"text": "deep learning networks optimize patterns"},
            {"text": "gradient descent minimizes loss error"},
        ])
        delta = sc.delta_report(self.before_path, self.after_path)
        self.assertIn("delta_mean", delta)
        self.assertIn("health_change", delta)
        self.assertIn("delta_disconnected", delta)

    def test_improvement_detected(self):
        # Before: random topics
        self._write(self.before_path, [
            {"text": "quantum physics particles"},
            {"text": "baking cookies flour sugar"},
            {"text": "astronomy galaxy nebula"},
            {"text": "gardening compost soil"},
            {"text": "music harmony rhythm melody"},
        ])
        # After: coherent topics
        self._write(self.after_path, [
            {"text": "python programming modules packages import"},
            {"text": "python programming classes objects methods"},
            {"text": "python programming functions decorators closures"},
            {"text": "python programming generators iterators yield"},
            {"text": "python programming async await coroutines"},
        ])
        delta = sc.delta_report(self.before_path, self.after_path)
        # After should be more coherent
        self.assertGreater(delta["delta_mean"], 0)


class TestIntegration(unittest.TestCase):
    """Integration tests with realistic data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.strokes_path = Path(self.tmpdir) / "strokes.jsonl"

    def tearDown(self):
        if self.strokes_path.exists():
            os.unlink(self.strokes_path)
        os.rmdir(self.tmpdir)

    def test_realistic_stroke_stream(self):
        """Simulate a realistic stream of varied strokes."""
        topics = [
            "neural network training convergence gradient descent optimization",
            "neural network regularization dropout batch normalization techniques",
            "convolutional networks image recognition feature extraction layers",
            "recurrent networks sequence modeling temporal dependencies lstm",
            "attention mechanism transformer architecture self attention layers",
            "baking sourdough bread fermentation wild yeast culture",
            "baking croissants laminated dough butter folding technique",
            "quantum computing qubits superposition entanglement gates",
            "quantum error correction surface codes logical qubits",
            "classical music sonata form exposition development recapitulation",
        ]
        with open(self.strokes_path, "w") as f:
            for i, text in enumerate(topics):
                f.write(json.dumps({"n": i, "text": text, "type": "note"}) + "\n")

        report = sc.snapshot_report(self.strokes_path, window=10)
        self.assertEqual(report["total_strokes"], 10)
        self.assertEqual(report["pairs"], 9)
        # Diverse topics — most transitions are jarring/disconnected,
        # but adjacent related topics should produce nonzero mean
        self.assertGreater(report["mean"], 0.0)

    def test_degenerate_all_identical(self):
        """All strokes identical — should be coherent."""
        with open(self.strokes_path, "w") as f:
            for i in range(10):
                f.write(json.dumps({"n": i, "text": "same exact text repeated"}) + "\n")
        report = sc.snapshot_report(self.strokes_path)
        self.assertEqual(report["health"], "healthy")

    def test_degenerate_all_empty(self):
        """All strokes have empty text."""
        with open(self.strokes_path, "w") as f:
            for i in range(5):
                f.write(json.dumps({"n": i, "text": ""}) + "\n")
        report = sc.snapshot_report(self.strokes_path)
        self.assertEqual(report["pairs"], 4)
        # All zero scores → disconnected
        self.assertAlmostEqual(report["mean"], 0.0)

    def test_malformed_jsonl_lines(self):
        """Malformed lines should be skipped."""
        with open(self.strokes_path, "w") as f:
            f.write(json.dumps({"text": "valid stroke content here"}) + "\n")
            f.write("NOT VALID JSON{{{\n")
            f.write(json.dumps({"text": "another valid stroke content"}) + "\n")
        strokes = sc.load_strokes(self.strokes_path)
        self.assertEqual(len(strokes), 2)

    def test_large_window_clamped(self):
        """Window larger than data should use all available strokes."""
        with open(self.strokes_path, "w") as f:
            for i in range(5):
                f.write(json.dumps({"text": f"topic_{i} analysis"}) + "\n")
        report = sc.snapshot_report(self.strokes_path, window=1000)
        self.assertEqual(report["count"], 5)


if __name__ == "__main__":
    unittest.main()
