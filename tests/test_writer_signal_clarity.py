#!/usr/bin/env python3
"""Tests for writer_signal_clarity — 60 test cases."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_signal_clarity import (  # noqa: E402
    _classify,
    _empty_metrics,
    _extract_template,
    _is_filler_stroke,
    _is_near_duplicate,
    _jaccard_distance,
    _jaccard_similarity,
    _tokenize,
    analyze_signal_clarity,
    classify_trend,
    compute_clarity_metrics,
    compute_clarity_trend,
    format_clarity_report,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestTokenize(unittest.TestCase):
    """Test _tokenize helper."""

    def test_basic_sentence(self):
        tokens = _tokenize("Hello World")
        self.assertEqual(tokens, {"hello", "world"})

    def test_empty_string(self):
        self.assertEqual(_tokenize(""), set())

    def test_punctuation_stripped(self):
        tokens = _tokenize("hello, world! foo-bar.")
        self.assertIn("hello", tokens)
        self.assertIn("world", tokens)
        self.assertIn("foo", tokens)
        self.assertIn("bar", tokens)

    def test_numbers_included(self):
        tokens = _tokenize("stroke 42 done")
        self.assertIn("42", tokens)
        self.assertIn("stroke", tokens)

    def test_repeated_words_deduped(self):
        tokens = _tokenize("go go go")
        self.assertEqual(tokens, {"go"})

    def test_unicode(self):
        tokens = _tokenize("café résumé")
        self.assertIn("café", tokens)  # \w+ handles unicode word chars
        self.assertIn("résumé", tokens)

    def test_mixed_case(self):
        tokens = _tokenize("Hello HELLO hello")
        self.assertEqual(tokens, {"hello"})


class TestJaccardSimilarity(unittest.TestCase):
    """Test _jaccard_similarity helper."""

    def test_identical_sets(self):
        a = {"hello", "world"}
        self.assertAlmostEqual(_jaccard_similarity(a, a), 1.0)

    def test_disjoint_sets(self):
        a = {"hello"}
        b = {"world"}
        self.assertAlmostEqual(_jaccard_similarity(a, b), 0.0)

    def test_partial_overlap(self):
        a = {"a", "b", "c"}
        b = {"b", "c", "d"}
        # intersection = {b, c} = 2, union = {a, b, c, d} = 4
        self.assertAlmostEqual(_jaccard_similarity(a, b), 0.5)

    def test_both_empty(self):
        self.assertAlmostEqual(_jaccard_similarity(set(), set()), 1.0)

    def test_one_empty(self):
        self.assertAlmostEqual(_jaccard_similarity({"a"}, set()), 0.0)

    def test_subset(self):
        a = {"a", "b"}
        b = {"a", "b", "c"}
        # intersection = 2, union = 3
        self.assertAlmostEqual(_jaccard_similarity(a, b), 2 / 3)


class TestJaccardDistance(unittest.TestCase):
    """Test _jaccard_distance helper."""

    def test_identical(self):
        a = {"x", "y"}
        self.assertAlmostEqual(_jaccard_distance(a, a), 0.0)

    def test_disjoint(self):
        self.assertAlmostEqual(_jaccard_distance({"a"}, {"b"}), 1.0)

    def test_complement_of_similarity(self):
        a = {"a", "b", "c"}
        b = {"b", "c", "d"}
        sim = _jaccard_similarity(a, b)
        dist = _jaccard_distance(a, b)
        self.assertAlmostEqual(sim + dist, 1.0)


class TestExtractTemplate(unittest.TestCase):
    """Test _extract_template helper."""

    def test_replaces_numbers(self):
        t = _extract_template("stroke 42 has 3.14 items")
        self.assertNotIn("42", t)
        self.assertIn("<N>", t)

    def test_replaces_hash(self):
        t = _extract_template("commit abc1234 pushed")
        self.assertIn("<HASH>", t)
        self.assertNotIn("abc1234", t)

    def test_replaces_timestamp(self):
        t = _extract_template("at 2026-11-11T10:04:37+00:00 done")
        self.assertIn("<TS>", t)

    def test_replaces_file_path(self):
        t = _extract_template("modified writer.py done")
        self.assertIn("<PATH>", t)

    def test_structural_equivalence(self):
        """Two strokes differing only in variable values share a template."""
        a = _extract_template("chunk_text.py is already in the pool of 9 modules")
        b = _extract_template("parse_kv.py is already in the pool of 9 modules")
        self.assertEqual(a, b)

    def test_empty_string(self):
        self.assertEqual(_extract_template(""), "")


class TestIsNearDuplicate(unittest.TestCase):
    """Test _is_near_duplicate helper."""

    def test_identical(self):
        tokens = {"a", "b", "c"}
        self.assertTrue(_is_near_duplicate(tokens, tokens))

    def test_high_overlap(self):
        a = {"a", "b", "c", "d", "e"}
        b = {"a", "b", "c", "d", "f"}
        # Jaccard = 4/6 ≈ 0.667
        self.assertFalse(_is_near_duplicate(a, b, 0.80))
        self.assertTrue(_is_near_duplicate(a, b, 0.60))

    def test_low_overlap(self):
        a = {"a", "b"}
        b = {"c", "d"}
        self.assertFalse(_is_near_duplicate(a, b))

    def test_custom_threshold(self):
        a = {"a", "b", "c"}
        b = {"a", "b", "d"}
        # Jaccard = 2/4 = 0.5
        self.assertTrue(_is_near_duplicate(a, b, 0.50))
        self.assertFalse(_is_near_duplicate(a, b, 0.51))


class TestIsFillerStroke(unittest.TestCase):
    """Test _is_filler_stroke classification."""

    def test_unique_stroke_not_filler(self):
        stroke = {"text": "the quick brown fox jumps over the lazy dog"}
        recent = [_tokenize("completely different content here today")]
        tc = {}
        self.assertFalse(_is_filler_stroke(stroke, recent, tc))

    def test_near_duplicate_is_filler(self):
        text = "the module was added successfully with all tests passing"
        stroke = {"text": text}
        recent = [_tokenize(text)]
        tc = {}
        self.assertTrue(_is_filler_stroke(stroke, recent, tc))

    def test_template_loop_is_filler(self):
        stroke = {"text": "chunk_text.py is already in the pool of 9 modules"}
        recent = []
        template = _extract_template(stroke["text"])
        tc = {template: 5}  # seen 5 times already
        self.assertTrue(_is_filler_stroke(stroke, recent, tc, template_repeat_threshold=3))

    def test_short_stroke_matching_recent(self):
        stroke = {"text": "done already"}
        recent = [_tokenize("done already completely")]
        tc = {}
        # Short stroke (2 tokens) with 2/3 ≈ 0.67 overlap against recent
        self.assertTrue(_is_filler_stroke(stroke, recent, tc))

    def test_short_unique_stroke_not_filler(self):
        stroke = {"text": "xyz"}
        recent = [_tokenize("completely different long text")]
        tc = {}
        self.assertFalse(_is_filler_stroke(stroke, recent, tc))

    def test_empty_stroke_not_filler(self):
        stroke = {"text": ""}
        recent = [_tokenize("something here")]
        tc = {}
        # Empty tokens, no overlap detected
        self.assertFalse(_is_filler_stroke(stroke, recent, tc))


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------

class TestComputeClarityMetrics(unittest.TestCase):
    """Test compute_clarity_metrics."""

    def test_empty_strokes(self):
        m = compute_clarity_metrics([])
        self.assertEqual(m["strokes_analyzed"], 0)
        self.assertEqual(m["clarity_class"], "noise")

    def test_single_stroke(self):
        strokes = [{"text": "unique content about testing"}]
        m = compute_clarity_metrics(strokes)
        self.assertEqual(m["strokes_analyzed"], 1)
        self.assertEqual(m["duplicate_count"], 0)
        self.assertEqual(m["filler_ratio"], 0.0)

    def test_all_unique_strokes(self):
        strokes = [
            {"text": "alpha bravo charlie delta echo"},
            {"text": "foxtrot golf hotel india juliet"},
            {"text": "kilo lima mike november oscar"},
            {"text": "papa quebec romeo sierra tango"},
            {"text": "uniform victor whiskey xray yankee"},
        ]
        m = compute_clarity_metrics(strokes)
        self.assertEqual(m["duplicate_count"], 0)
        self.assertGreater(m["uniqueness_ratio"], 0.8)
        self.assertGreater(m["clarity_score"], 0.5)

    def test_all_duplicate_strokes(self):
        text = "the module was added and all tests passed successfully"
        strokes = [{"text": text} for _ in range(10)]
        m = compute_clarity_metrics(strokes)
        self.assertGreater(m["duplicate_count"], 0)
        self.assertLess(m["uniqueness_ratio"], 0.5)
        self.assertGreater(m["filler_ratio"], 0.5)

    def test_template_loop_detected(self):
        modules = ["chunk_text", "parse_kv", "retry", "bloom_filter",
                   "circuit_breaker", "debounce", "fuse", "jitter"]
        strokes = [
            {"text": f"{mod}.py is already in the pool of 9 modules nothing new to add there"}
            for mod in modules
        ]
        m = compute_clarity_metrics(strokes, template_repeat_threshold=3)
        self.assertGreater(m["filler_ratio"], 0.5)

    def test_mixed_signal(self):
        strokes = [
            {"text": "completely unique observation about the system architecture"},
            {"text": "added new module for detecting signal clarity patterns"},
            {"text": "completely unique observation about the system architecture"},  # dup
            {"text": "fresh insight about testing methodology and coverage gaps"},
            {"text": "another distinct thought about repository health metrics"},
        ]
        m = compute_clarity_metrics(strokes)
        self.assertGreater(m["duplicate_count"], 0)
        self.assertLess(m["filler_ratio"], 1.0)

    def test_window_size_limits_analysis(self):
        strokes = [{"text": f"unique stroke number {i} with different content"}
                    for i in range(100)]
        m = compute_clarity_metrics(strokes, window_size=10)
        self.assertEqual(m["strokes_analyzed"], 10)

    def test_information_delta_high(self):
        strokes = [
            {"text": "alpha bravo charlie"},
            {"text": "delta echo foxtrot"},
            {"text": "golf hotel india"},
        ]
        m = compute_clarity_metrics(strokes)
        self.assertGreater(m["information_delta"], 0.8)

    def test_information_delta_low(self):
        base = "the quick brown fox jumps over the lazy dog and"
        strokes = [
            {"text": base + " runs"},
            {"text": base + " walks"},
            {"text": base + " sleeps"},
        ]
        m = compute_clarity_metrics(strokes)
        self.assertLess(m["information_delta"], 0.5)

    def test_classification_broadcast(self):
        # Each stroke must be genuinely unique, not just a number swap
        topics = [
            "quantum entanglement reshapes our understanding of locality",
            "medieval monks preserved knowledge through illuminated manuscripts",
            "coral reefs support twenty five percent of marine biodiversity",
            "jazz improvisation mirrors conversation in call and response",
            "glacial retreat reveals archaeological artifacts frozen for millennia",
            "neural plasticity allows adult brains to rewire after injury",
            "desert plants evolved crassulacean acid metabolism to conserve water",
            "the printing press democratized access to written knowledge",
            "mycorrhizal networks let trees share nutrients underground",
            "supernova explosions seed the cosmos with heavy elements",
            "viking longships combined sail and oar for versatile navigation",
            "bioluminescence helps deep sea creatures find mates in darkness",
            "the fibonacci sequence appears in sunflower seed spirals",
            "plate tectonics recycles earth crust over hundreds of millions years",
            "fermentation transforms raw ingredients through microbial metabolism",
            "radio telescopes detect hydrogen emission across the galaxy",
            "origami mathematics inspires deployable space structures",
            "symbiotic clownfish and anemones defend each other from predators",
            "the rossetta stone unlocked three scripts of ancient egyptian writing",
            "tidal energy converters harness gravitational moon earth interaction",
        ]
        strokes = [{"text": t} for t in topics]
        m = compute_clarity_metrics(strokes)
        self.assertIn(m["clarity_class"], ["broadcast", "communicator"])

    def test_classification_noise(self):
        strokes = [{"text": "same exact text repeated over and over again"}
                    for _ in range(20)]
        m = compute_clarity_metrics(strokes)
        self.assertIn(m["clarity_class"], ["repeater", "noise"])


class TestClassify(unittest.TestCase):
    """Test _classify helper."""

    def test_broadcast(self):
        self.assertEqual(_classify(0.75), "broadcast")
        self.assertEqual(_classify(0.99), "broadcast")

    def test_communicator(self):
        self.assertEqual(_classify(0.50), "communicator")
        self.assertEqual(_classify(0.74), "communicator")

    def test_repeater(self):
        self.assertEqual(_classify(0.25), "repeater")
        self.assertEqual(_classify(0.49), "repeater")

    def test_noise(self):
        self.assertEqual(_classify(0.0), "noise")
        self.assertEqual(_classify(0.24), "noise")

    def test_boundary_values(self):
        self.assertEqual(_classify(0.75), "broadcast")
        self.assertEqual(_classify(0.50), "communicator")
        self.assertEqual(_classify(0.25), "repeater")
        self.assertEqual(_classify(0.2499), "noise")


class TestEmptyMetrics(unittest.TestCase):
    """Test _empty_metrics helper."""

    def test_all_zeros(self):
        m = _empty_metrics()
        self.assertEqual(m["clarity_score"], 0.0)
        self.assertEqual(m["strokes_analyzed"], 0)
        self.assertEqual(m["clarity_class"], "noise")

    def test_has_all_keys(self):
        m = _empty_metrics()
        expected_keys = [
            "uniqueness_ratio", "template_diversity", "information_delta",
            "filler_ratio", "clarity_score", "clarity_class",
            "strokes_analyzed", "duplicate_count", "filler_count",
            "unique_templates",
        ]
        for k in expected_keys:
            self.assertIn(k, m)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

class TestComputeClarityTrend(unittest.TestCase):
    """Test compute_clarity_trend."""

    def test_short_history(self):
        strokes = [{"text": "only a few strokes here"}]
        snaps = compute_clarity_trend(strokes, window_size=10)
        self.assertEqual(len(snaps), 1)

    def test_multiple_windows(self):
        strokes = [
            {"text": f"unique stroke content number {i} with varied text"}
            for i in range(50)
        ]
        snaps = compute_clarity_trend(strokes, window_size=10, step=10)
        self.assertGreater(len(snaps), 1)

    def test_window_start_included(self):
        strokes = [
            {"text": f"stroke {i} with some unique content here"}
            for i in range(30)
        ]
        snaps = compute_clarity_trend(strokes, window_size=10, step=10)
        for s in snaps:
            self.assertIn("window_start", s)

    def test_exact_window_size(self):
        strokes = [{"text": f"content {i}"} for i in range(10)]
        snaps = compute_clarity_trend(strokes, window_size=10)
        self.assertEqual(len(snaps), 1)


class TestClassifyTrend(unittest.TestCase):
    """Test classify_trend."""

    def test_insufficient_data(self):
        self.assertEqual(classify_trend([]), "insufficient_data")
        self.assertEqual(classify_trend([{"clarity_score": 0.5}]), "insufficient_data")

    def test_improving(self):
        snaps = [
            {"clarity_score": 0.3},
            {"clarity_score": 0.4},
            {"clarity_score": 0.6},
            {"clarity_score": 0.7},
        ]
        self.assertEqual(classify_trend(snaps), "improving")

    def test_degrading(self):
        snaps = [
            {"clarity_score": 0.8},
            {"clarity_score": 0.7},
            {"clarity_score": 0.3},
            {"clarity_score": 0.2},
        ]
        self.assertEqual(classify_trend(snaps), "degrading")

    def test_stable(self):
        snaps = [
            {"clarity_score": 0.50},
            {"clarity_score": 0.52},
            {"clarity_score": 0.51},
            {"clarity_score": 0.50},
        ]
        self.assertEqual(classify_trend(snaps), "stable")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class TestFormatClarityReport(unittest.TestCase):
    """Test format_clarity_report."""

    def test_broadcast_report(self):
        m = _empty_metrics()
        m["clarity_class"] = "broadcast"
        m["clarity_score"] = 0.85
        report = format_clarity_report(m)
        self.assertIn("broadcast", report.lower())
        self.assertIn("unique content", report.lower())

    def test_communicator_report(self):
        m = _empty_metrics()
        m["clarity_class"] = "communicator"
        m["clarity_score"] = 0.60
        report = format_clarity_report(m)
        self.assertIn("communicator", report.lower())

    def test_repeater_report(self):
        m = _empty_metrics()
        m["clarity_class"] = "repeater"
        m["clarity_score"] = 0.35
        report = format_clarity_report(m)
        self.assertIn("repeater", report.lower())
        self.assertIn("near-duplicate", report.lower())

    def test_noise_report(self):
        m = _empty_metrics()
        m["clarity_class"] = "noise"
        report = format_clarity_report(m)
        self.assertIn("intervention", report.lower())

    def test_report_contains_metrics(self):
        m = compute_clarity_metrics([{"text": "sample content here"}])
        report = format_clarity_report(m)
        self.assertIn("Uniqueness ratio", report)
        self.assertIn("Template diversity", report)
        self.assertIn("Information delta", report)
        self.assertIn("Filler ratio", report)


# ---------------------------------------------------------------------------
# Standalone analysis
# ---------------------------------------------------------------------------

class TestAnalyzeSignalClarity(unittest.TestCase):
    """Test analyze_signal_clarity with temp files."""

    def test_missing_file(self):
        m = analyze_signal_clarity("nonexistent_file.jsonl")
        self.assertEqual(m["strokes_analyzed"], 0)
        self.assertEqual(m["clarity_class"], "noise")

    def test_valid_jsonl(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for i in range(25):
                entry = {"text": f"unique stroke content number {i}", "seq": i}
                f.write(json.dumps(entry) + "\n")
            path = f.name
        try:
            m = analyze_signal_clarity(path, window_size=10)
            self.assertEqual(m["strokes_analyzed"], 10)
            self.assertGreater(m["clarity_score"], 0.0)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_malformed_jsonl(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"text": "valid entry"}\n')
            f.write("not valid json\n")
            f.write('{"text": "another valid entry with different words"}\n')
            path = f.name
        try:
            m = analyze_signal_clarity(path)
            # Should skip bad lines and process good ones
            self.assertGreater(m["strokes_analyzed"], 0)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            m = analyze_signal_clarity(path)
            self.assertEqual(m["strokes_analyzed"], 0)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_content_field_fallback(self):
        """Strokes may use 'content' instead of 'text'."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for i in range(5):
                entry = {"content": f"fallback content field number {i}", "seq": i}
                f.write(json.dumps(entry) + "\n")
            path = f.name
        try:
            m = analyze_signal_clarity(path)
            self.assertGreater(m["strokes_analyzed"], 0)
        finally:
            Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_strokes_with_no_text_field(self):
        strokes = [{"seq": 1}, {"seq": 2}, {"seq": 3}]
        m = compute_clarity_metrics(strokes)
        self.assertEqual(m["strokes_analyzed"], 3)
        # All empty → all near-duplicates of each other
        self.assertGreater(m["filler_ratio"], 0.0)

    def test_very_long_strokes(self):
        long_text_a = " ".join(f"word{i}" for i in range(1000))
        long_text_b = " ".join(f"word{i}" for i in range(500, 1500))
        strokes = [{"text": long_text_a}, {"text": long_text_b}]
        m = compute_clarity_metrics(strokes)
        self.assertEqual(m["strokes_analyzed"], 2)
        # Partial overlap
        self.assertGreater(m["information_delta"], 0.0)

    def test_single_token_strokes(self):
        strokes = [{"text": "alpha"}, {"text": "beta"}, {"text": "gamma"}]
        m = compute_clarity_metrics(strokes)
        self.assertEqual(m["strokes_analyzed"], 3)
        # All different single tokens → high uniqueness
        self.assertEqual(m["duplicate_count"], 0)

    def test_identical_consecutive_strokes(self):
        text = "exactly the same content every single time"
        strokes = [{"text": text} for _ in range(5)]
        m = compute_clarity_metrics(strokes)
        self.assertGreater(m["duplicate_count"], 0)
        self.assertGreater(m["filler_count"], 0)

    def test_large_window_larger_than_data(self):
        strokes = [{"text": "only three"}, {"text": "strokes here"}, {"text": "nothing more"}]
        m = compute_clarity_metrics(strokes, window_size=1000)
        self.assertEqual(m["strokes_analyzed"], 3)


if __name__ == "__main__":
    unittest.main()
