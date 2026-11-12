#!/usr/bin/env python3
"""Tests for writer_pacing — pacing as density-variation signal."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_pacing import (  # noqa: E402
    ENGAGEMENT_PATTERNS,
    _classify_pacing,
    _coefficient_of_variation,
    _get_stroke_text,
    _has_engagement_marker,
    _is_content_word,
    _segment_density,
    _segment_words,
    _split_words,
    analyze_stroke_pacing,
    classify_trend,
    compute_pacing_metrics,
    compute_pacing_trend,
    format_pacing_report,
)


# ---------------------------------------------------------------------------
# Helper: _split_words
# ---------------------------------------------------------------------------


class TestSplitWords(unittest.TestCase):
    """Test _split_words helper."""

    def test_basic(self):
        words = _split_words("Hello world")
        self.assertEqual(words, ["hello", "world"])

    def test_punctuation(self):
        words = _split_words("It's a test, really.")
        self.assertIn("it's", words)
        self.assertIn("really", words)

    def test_empty(self):
        self.assertEqual(_split_words(""), [])

    def test_numbers_ignored(self):
        words = _split_words("test 42 data")
        self.assertEqual(words, ["test", "data"])

    def test_multiple_spaces(self):
        words = _split_words("hello    world")
        self.assertEqual(words, ["hello", "world"])


# ---------------------------------------------------------------------------
# Helper: _get_stroke_text
# ---------------------------------------------------------------------------


class TestGetStrokeText(unittest.TestCase):
    """Test _get_stroke_text helper."""

    def test_string_input(self):
        self.assertEqual(_get_stroke_text("hello"), "hello")

    def test_dict_with_text(self):
        self.assertEqual(_get_stroke_text({"text": "hello"}), "hello")

    def test_dict_with_content(self):
        self.assertEqual(_get_stroke_text({"content": "hello"}), "hello")

    def test_dict_empty(self):
        self.assertEqual(_get_stroke_text({}), "")

    def test_dict_text_priority(self):
        # 'text' takes priority over 'content'
        self.assertEqual(
            _get_stroke_text({"text": "first", "content": "second"}), "first"
        )

    def test_non_string_non_dict(self):
        self.assertEqual(_get_stroke_text(42), "")


# ---------------------------------------------------------------------------
# Helper: _is_content_word
# ---------------------------------------------------------------------------


class TestIsContentWord(unittest.TestCase):
    """Test _is_content_word helper."""

    def test_content_word(self):
        self.assertTrue(_is_content_word("algorithm"))
        self.assertTrue(_is_content_word("running"))
        self.assertTrue(_is_content_word("beautiful"))

    def test_stopword(self):
        self.assertFalse(_is_content_word("the"))
        self.assertFalse(_is_content_word("and"))
        self.assertFalse(_is_content_word("because"))

    def test_short_word(self):
        self.assertFalse(_is_content_word("an"))
        self.assertFalse(_is_content_word("to"))
        self.assertFalse(_is_content_word("it"))

    def test_empty(self):
        self.assertFalse(_is_content_word(""))


# ---------------------------------------------------------------------------
# Helper: _segment_words
# ---------------------------------------------------------------------------


class TestSegmentWords(unittest.TestCase):
    """Test _segment_words helper."""

    def test_basic(self):
        words = list(range(120))
        segments = _segment_words(words, 50)
        self.assertEqual(len(segments), 3)
        self.assertEqual(len(segments[0]), 50)
        self.assertEqual(len(segments[1]), 50)
        self.assertEqual(len(segments[2]), 20)

    def test_empty(self):
        self.assertEqual(_segment_words([], 50), [])

    def test_exact_fit(self):
        words = list(range(100))
        segments = _segment_words(words, 50)
        self.assertEqual(len(segments), 2)
        self.assertEqual(len(segments[0]), 50)
        self.assertEqual(len(segments[1]), 50)

    def test_single_segment(self):
        words = list(range(30))
        segments = _segment_words(words, 50)
        self.assertEqual(len(segments), 1)
        self.assertEqual(len(segments[0]), 30)


# ---------------------------------------------------------------------------
# Helper: _segment_density
# ---------------------------------------------------------------------------


class TestSegmentDensity(unittest.TestCase):
    """Test _segment_density helper."""

    def test_all_content(self):
        words = ["algorithm", "running", "beautiful", "quickly", "system"]
        density = _segment_density(words)
        self.assertGreater(density, 0.8)

    def test_all_stopwords(self):
        words = ["the", "and", "is", "to", "of", "in"]
        density = _segment_density(words)
        self.assertEqual(density, 0.0)

    def test_mixed(self):
        words = ["the", "algorithm", "is", "running", "and", "beautiful"]
        density = _segment_density(words)
        self.assertAlmostEqual(density, 3 / 6, places=2)

    def test_empty(self):
        self.assertEqual(_segment_density([]), 0.0)


# ---------------------------------------------------------------------------
# Helper: _coefficient_of_variation
# ---------------------------------------------------------------------------


class TestCoefficientOfVariation(unittest.TestCase):
    """Test _coefficient_of_variation helper."""

    def test_uniform(self):
        # All same values -> CV = 0
        cv = _coefficient_of_variation([0.5, 0.5, 0.5, 0.5])
        self.assertAlmostEqual(cv, 0.0)

    def test_high_variation(self):
        cv = _coefficient_of_variation([0.1, 0.9, 0.1, 0.9])
        self.assertGreater(cv, 0.5)

    def test_moderate_variation(self):
        cv = _coefficient_of_variation([0.3, 0.35, 0.4, 0.32])
        self.assertGreater(cv, 0.05)
        self.assertLess(cv, 0.3)

    def test_empty(self):
        self.assertEqual(_coefficient_of_variation([]), 0.0)

    def test_single_value(self):
        # Single value -> std = 0 -> CV = 0
        self.assertEqual(_coefficient_of_variation([0.5]), 0.0)

    def test_zeros(self):
        self.assertEqual(_coefficient_of_variation([0.0, 0.0, 0.0]), 0.0)


# ---------------------------------------------------------------------------
# Helper: _has_engagement_marker
# ---------------------------------------------------------------------------


class TestHasEngagementMarker(unittest.TestCase):
    """Test _has_engagement_marker helper."""

    def test_question(self):
        self.assertTrue(_has_engagement_marker("What do you think?"))

    def test_example(self):
        self.assertTrue(_has_engagement_marker("For example, consider this case."))
        self.assertTrue(_has_engagement_marker("For instance, the cat sat."))
        self.assertTrue(_has_engagement_marker("Items such as apples and oranges."))
        self.assertTrue(_has_engagement_marker("We need e.g. more tests."))

    def test_direct_address(self):
        self.assertTrue(_has_engagement_marker("You should try this."))
        self.assertTrue(_has_engagement_marker("Your approach is correct."))

    def test_list_marker(self):
        self.assertTrue(_has_engagement_marker("- First item\n- Second item"))
        self.assertTrue(_has_engagement_marker("1. First step\n2. Second step"))

    def test_quote(self):
        self.assertTrue(_has_engagement_marker('She said "hello world today"'))

    def test_no_marker(self):
        self.assertFalse(_has_engagement_marker("The system processes data efficiently."))

    def test_consider(self):
        self.assertTrue(_has_engagement_marker("Consider the implications."))

    def test_imagine(self):
        self.assertTrue(_has_engagement_marker("Imagine a world without limits."))

    def test_remember(self):
        self.assertTrue(_has_engagement_marker("Remember to check the output."))


# ---------------------------------------------------------------------------
# Classification: _classify_pacing
# ---------------------------------------------------------------------------


class TestClassifyPacing(unittest.TestCase):
    """Test _classify_pacing classification boundaries."""

    def test_riveting(self):
        self.assertEqual(_classify_pacing(0.75, 0.20, 0.25), "riveting")
        self.assertEqual(_classify_pacing(0.90, 0.20, 0.25), "riveting")
        self.assertEqual(_classify_pacing(1.0, 0.20, 0.25), "riveting")

    def test_engaging(self):
        self.assertEqual(_classify_pacing(0.60, 0.20, 0.25), "engaging")
        self.assertEqual(_classify_pacing(0.70, 0.20, 0.25), "engaging")
        self.assertEqual(_classify_pacing(0.74, 0.20, 0.25), "engaging")

    def test_uneven(self):
        self.assertEqual(_classify_pacing(0.45, 0.20, 0.25), "uneven")
        self.assertEqual(_classify_pacing(0.55, 0.20, 0.25), "uneven")
        self.assertEqual(_classify_pacing(0.59, 0.20, 0.25), "uneven")

    def test_monotonous(self):
        self.assertEqual(_classify_pacing(0.30, 0.20, 0.25), "monotonous")
        self.assertEqual(_classify_pacing(0.40, 0.20, 0.25), "monotonous")
        self.assertEqual(_classify_pacing(0.44, 0.20, 0.25), "monotonous")

    def test_monotonous_low_variation(self):
        """Very low CVs should classify as monotonous regardless of index."""
        self.assertEqual(_classify_pacing(0.0, 0.01, 0.02), "monotonous")
        self.assertEqual(_classify_pacing(0.80, 0.01, 0.01), "monotonous")

    def test_erratic(self):
        self.assertEqual(_classify_pacing(0.0, 0.50, 0.45), "erratic")
        self.assertEqual(_classify_pacing(0.15, 0.50, 0.45), "erratic")
        self.assertEqual(_classify_pacing(0.29, 0.50, 0.45), "erratic")

    def test_boundary_values(self):
        # Exactly at boundaries.
        self.assertEqual(_classify_pacing(0.75, 0.20, 0.25), "riveting")
        self.assertEqual(_classify_pacing(0.60, 0.20, 0.25), "engaging")
        self.assertEqual(_classify_pacing(0.45, 0.20, 0.25), "uneven")
        self.assertEqual(_classify_pacing(0.30, 0.20, 0.25), "monotonous")


# ---------------------------------------------------------------------------
# Core: analyze_stroke_pacing
# ---------------------------------------------------------------------------


class TestAnalyzeStrokePacing(unittest.TestCase):
    """Test analyze_stroke_pacing for individual strokes."""

    def test_empty_stroke(self):
        result = analyze_stroke_pacing("")
        self.assertEqual(result["pacing_index"], 0.0)
        self.assertEqual(result["pacing_class"], "monotonous")
        self.assertEqual(result["segments"], [])

    def test_short_stroke(self):
        result = analyze_stroke_pacing("Short text.")
        self.assertEqual(result["pacing_index"], 0.0)
        self.assertEqual(result["segments"], [])

    def test_single_segment(self):
        # Less than segment_size words -> single segment.
        text = "The quick brown fox jumps over the lazy dog. " * 3
        result = analyze_stroke_pacing(text, segment_size=50)
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual(result["pacing_class"], "uneven")

    def test_multi_segment(self):
        # Create text with > 50 words to get multiple segments.
        dense = "algorithm optimization performance benchmark throughput latency " * 20
        result = analyze_stroke_pacing(dense, segment_size=50)
        self.assertGreater(len(result["segments"]), 1)
        self.assertIn(result["pacing_class"], [
            "riveting", "engaging", "uneven", "monotonous", "erratic"
        ])

    def test_varied_text(self):
        # Mix of dense and light segments.
        dense_part = (
            "The distributed consensus algorithm employs a Raft-based "
            "protocol with leader election and log replication across "
            "multiple nodes in the cluster. Each node maintains a state "
            "machine and applies committed entries sequentially. "
        )
        light_part = (
            "Think of it like a team. One person leads. Others follow. "
            "Simple, right? You see this everywhere. "
        )
        text = (dense_part + light_part) * 5
        result = analyze_stroke_pacing(text, segment_size=50)
        # Should detect some variation.
        self.assertGreater(result["density_cv"], 0.0)

    def test_engagement_markers(self):
        text = (
            "What happens when the system fails? Consider this example: "
            "the database crashes. For instance, PostgreSQL might run out "
            "of connections. You should monitor your connection pool. "
            "- Check memory usage. - Review query plans. "
            "Remember: prevention beats cure. " * 10
        )
        result = analyze_stroke_pacing(text, segment_size=50)
        self.assertGreater(result["engagement_fraction"], 0.0)

    def test_dict_stroke(self):
        text = "The system processes data efficiently across nodes. " * 15
        result = analyze_stroke_pacing({"text": text}, segment_size=50)
        self.assertIn("pacing_index", result)
        self.assertIn("pacing_class", result)

    def test_content_key(self):
        text = "Processing data with algorithms for optimization. " * 15
        result = analyze_stroke_pacing({"content": text}, segment_size=50)
        self.assertIn("pacing_index", result)

    def test_monotonous_text(self):
        # Every sentence has similar structure and density.
        sentence = "The system processes input data through the pipeline. "
        text = sentence * 40
        result = analyze_stroke_pacing(text, segment_size=50)
        # Low variation -> monotonous or uneven.
        self.assertIn(result["pacing_class"], [
            "monotonous", "uneven", "erratic"
        ])

    def test_result_keys(self):
        text = "Some varied content here for testing purposes. " * 20
        result = analyze_stroke_pacing(text, segment_size=50)
        expected_keys = {
            "segments", "density_cv", "complexity_cv",
            "transition_smoothness", "engagement_fraction",
            "pacing_index", "pacing_class",
        }
        self.assertEqual(set(result.keys()), expected_keys)


# ---------------------------------------------------------------------------
# Session-level: compute_pacing_metrics
# ---------------------------------------------------------------------------


class TestComputePacingMetrics(unittest.TestCase):
    """Test compute_pacing_metrics over multiple strokes."""

    def test_empty_strokes(self):
        result = compute_pacing_metrics([])
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["pacing_index"], 0.0)
        self.assertEqual(result["pacing_class"], "monotonous")

    def test_single_stroke(self):
        text = "The algorithm processes data efficiently through the pipeline. " * 10
        result = compute_pacing_metrics([text], window_size=10, segment_size=30)
        self.assertEqual(result["strokes_analyzed"], 1)

    def test_multiple_strokes(self):
        strokes = [
            "Dense technical content about algorithms and data structures. " * 10,
            "Simple short sentences. Easy to read. Very clear. " * 10,
            "What do you think? Consider this example for clarity. " * 10,
        ] * 5
        result = compute_pacing_metrics(strokes, window_size=10, segment_size=30)
        self.assertGreater(result["strokes_analyzed"], 0)
        self.assertIn(result["pacing_class"], [
            "riveting", "engaging", "uneven", "monotonous", "erratic"
        ])

    def test_window_size(self):
        strokes = ["Some text here for testing. " * 10] * 100
        result = compute_pacing_metrics(strokes, window_size=20, segment_size=30)
        # Should analyze at most 20 strokes.
        self.assertLessEqual(result["strokes_analyzed"], 20)

    def test_class_distribution(self):
        strokes = [
            "Dense content about systems and algorithms and performance. " * 10,
        ] * 10
        result = compute_pacing_metrics(strokes, window_size=10, segment_size=30)
        dist = result["class_distribution"]
        self.assertIsInstance(dist, dict)
        total = sum(dist.values())
        self.assertEqual(total, result["strokes_analyzed"])

    def test_result_keys(self):
        strokes = ["Text content for analysis. " * 10] * 5
        result = compute_pacing_metrics(strokes, window_size=5, segment_size=20)
        expected_keys = {
            "strokes_analyzed", "strokes_with_segments", "pacing_index",
            "pacing_class", "avg_density_cv", "avg_complexity_cv",
            "avg_transition_smoothness", "avg_engagement_fraction",
            "class_distribution",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_dict_strokes(self):
        strokes = [
            {"text": "Algorithm optimization benchmark test. " * 10},
            {"content": "System performance analysis tool. " * 10},
        ]
        result = compute_pacing_metrics(strokes, window_size=5, segment_size=20)
        self.assertEqual(result["strokes_analyzed"], 2)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


class TestComputePacingTrend(unittest.TestCase):
    """Test compute_pacing_trend for time-series analysis."""

    def test_empty(self):
        self.assertEqual(compute_pacing_trend([]), [])

    def test_single_window(self):
        strokes = ["Some content for analysis. " * 15] * 25
        snapshots = compute_pacing_trend(strokes, window_size=20, step=10, segment_size=20)
        self.assertGreater(len(snapshots), 0)

    def test_window_start_field(self):
        strokes = ["Content here for testing. " * 15] * 50
        snapshots = compute_pacing_trend(strokes, window_size=20, step=10, segment_size=20)
        for snap in snapshots:
            self.assertIn("window_start", snap)

    def test_step_stride(self):
        strokes = ["Data for testing purposes. " * 15] * 60
        snapshots = compute_pacing_trend(strokes, window_size=20, step=20, segment_size=20)
        # With step=20 and 60 strokes, expect ~3 snapshots.
        self.assertGreater(len(snapshots), 0)
        self.assertLessEqual(len(snapshots), 4)


class TestClassifyTrend(unittest.TestCase):
    """Test classify_trend for trend direction."""

    def test_insufficient_data(self):
        self.assertEqual(classify_trend([]), "insufficient_data")
        self.assertEqual(classify_trend([{"pacing_index": 0.5}]), "insufficient_data")

    def test_improving(self):
        snapshots = [
            {"pacing_index": 0.3},
            {"pacing_index": 0.4},
            {"pacing_index": 0.6},
            {"pacing_index": 0.7},
        ]
        self.assertEqual(classify_trend(snapshots), "improving")

    def test_degrading(self):
        snapshots = [
            {"pacing_index": 0.8},
            {"pacing_index": 0.7},
            {"pacing_index": 0.4},
            {"pacing_index": 0.3},
        ]
        self.assertEqual(classify_trend(snapshots), "degrading")

    def test_stable(self):
        snapshots = [
            {"pacing_index": 0.5},
            {"pacing_index": 0.52},
            {"pacing_index": 0.48},
            {"pacing_index": 0.51},
        ]
        self.assertEqual(classify_trend(snapshots), "stable")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


class TestFormatPacingReport(unittest.TestCase):
    """Test format_pacing_report output."""

    def test_basic_report(self):
        metrics = {
            "strokes_analyzed": 50,
            "strokes_with_segments": 45,
            "pacing_index": 0.65,
            "pacing_class": "engaging",
            "avg_density_cv": 0.22,
            "avg_complexity_cv": 0.28,
            "avg_transition_smoothness": 0.75,
            "avg_engagement_fraction": 0.60,
            "class_distribution": {"engaging": 30, "uneven": 15},
        }
        report = format_pacing_report(metrics)
        self.assertIn("Writer Pacing", report)
        self.assertIn("0.6500", report)
        self.assertIn("engaging", report)
        self.assertIn("30", report)
        self.assertIn("15", report)

    def test_monotonous_interpretation(self):
        metrics = {
            "strokes_analyzed": 10,
            "strokes_with_segments": 10,
            "pacing_index": 0.35,
            "pacing_class": "monotonous",
            "avg_density_cv": 0.05,
            "avg_complexity_cv": 0.08,
            "avg_transition_smoothness": 0.90,
            "avg_engagement_fraction": 0.10,
            "class_distribution": {"monotonous": 10},
        }
        report = format_pacing_report(metrics)
        self.assertIn("little density variation", report)

    def test_riveting_interpretation(self):
        metrics = {
            "strokes_analyzed": 20,
            "strokes_with_segments": 20,
            "pacing_index": 0.80,
            "pacing_class": "riveting",
            "avg_density_cv": 0.25,
            "avg_complexity_cv": 0.30,
            "avg_transition_smoothness": 0.80,
            "avg_engagement_fraction": 0.75,
            "class_distribution": {"riveting": 20},
        }
        report = format_pacing_report(metrics)
        self.assertIn("rhythm", report)

    def test_erratic_interpretation(self):
        metrics = {
            "strokes_analyzed": 10,
            "strokes_with_segments": 10,
            "pacing_index": 0.20,
            "pacing_class": "erratic",
            "avg_density_cv": 0.60,
            "avg_complexity_cv": 0.55,
            "avg_transition_smoothness": 0.30,
            "avg_engagement_fraction": 0.40,
            "class_distribution": {"erratic": 10},
        }
        report = format_pacing_report(metrics)
        self.assertIn("Chaotic", report)

    def test_uneven_interpretation(self):
        metrics = {
            "strokes_analyzed": 10,
            "strokes_with_segments": 10,
            "pacing_index": 0.50,
            "pacing_class": "uneven",
            "avg_density_cv": 0.18,
            "avg_complexity_cv": 0.22,
            "avg_transition_smoothness": 0.60,
            "avg_engagement_fraction": 0.45,
            "class_distribution": {"uneven": 10},
        }
        report = format_pacing_report(metrics)
        self.assertIn("inconsistency", report)

    def test_empty_distribution(self):
        metrics = {
            "strokes_analyzed": 0,
            "strokes_with_segments": 0,
            "pacing_index": 0.0,
            "pacing_class": "monotonous",
            "avg_density_cv": 0.0,
            "avg_complexity_cv": 0.0,
            "avg_transition_smoothness": 0.0,
            "avg_engagement_fraction": 0.0,
            "class_distribution": {},
        }
        report = format_pacing_report(metrics)
        self.assertIn("Writer Pacing", report)
        # No "Class distribution:" section when empty.
        self.assertNotIn("Class distribution:", report)


# ---------------------------------------------------------------------------
# Orthogonality verification
# ---------------------------------------------------------------------------


class TestOrthogonality(unittest.TestCase):
    """Verify pacing is distinct from related metrics."""

    def test_same_length_different_pacing(self):
        """Two texts with different variation patterns produce different pacing."""
        # Monotonous: identical sentences repeated, very uniform density.
        mono = "The quick brown fox jumps over the lazy dog near the river bank. " * 40
        mono_result = analyze_stroke_pacing(mono, segment_size=50)

        # Varied: mix of very dense (long technical) and very light (short).
        varied = (
            "Stop. "
            "Cryptographic hash functions transform arbitrary input into "
            "fixed-length deterministic output exhibiting avalanche "
            "properties where minimal perturbation radically alters "
            "resulting digest values. "
            "Go. "
            "Stochastic gradient descent optimizes differentiable "
            "objective functions through iterative parameter updates "
            "proportional to negative gradient estimates computed "
            "from randomly sampled minibatches. "
            "Look. "
            "What happens when convergence stalls? Consider momentum "
            "terms, adaptive learning rates, or batch normalization. "
        ) * 8
        varied_result = analyze_stroke_pacing(varied, segment_size=50)

        # The varied text should have higher density variation.
        self.assertGreater(
            varied_result["density_cv"],
            mono_result["density_cv"],
        )

    def test_high_density_can_be_monotonous(self):
        """High content density doesn't guarantee good pacing."""
        # All high-density, no variation.
        text = "Algorithm optimization benchmark throughput latency performance. " * 30
        result = analyze_stroke_pacing(text, segment_size=50)
        # Should not be 'riveting' despite high density.
        self.assertNotEqual(result["pacing_class"], "riveting")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_very_long_stroke(self):
        text = "Testing pacing analysis with a moderately long text. " * 200
        result = analyze_stroke_pacing(text, segment_size=50)
        self.assertGreater(len(result["segments"]), 1)

    def test_all_punctuation(self):
        text = "... !!! ??? --- " * 20
        result = analyze_stroke_pacing(text, segment_size=50)
        # Should handle gracefully.
        self.assertIn("pacing_index", result)

    def test_non_english(self):
        text = "这是中文文本用于测试分析功能 " * 50
        result = analyze_stroke_pacing(text, segment_size=50)
        # Should not crash; results may vary.
        self.assertIn("pacing_index", result)

    def test_mixed_content(self):
        text = (
            "The API endpoint returns JSON data.\n"
            "- Item one: processing\n"
            "- Item two: analysis\n"
            "1. First step\n"
            "2. Second step\n"
            "What happens next? Consider the implications. "
        ) * 10
        result = analyze_stroke_pacing(text, segment_size=50)
        self.assertGreater(result["engagement_fraction"], 0.0)

    def test_zero_length_segment(self):
        """segment_size of 1 should still work."""
        text = "Word " * 10
        result = analyze_stroke_pacing(text, segment_size=1)
        self.assertGreater(len(result["segments"]), 0)


# ---------------------------------------------------------------------------
# Constants integrity
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    """Verify engagement pattern constants."""

    def test_engagement_patterns_not_empty(self):
        self.assertGreater(len(ENGAGEMENT_PATTERNS), 0)

    def test_engagement_patterns_are_strings(self):
        for p in ENGAGEMENT_PATTERNS:
            self.assertIsInstance(p, str)

    def test_engagement_patterns_compile(self):
        import re
        # All patterns should compile without error.
        for p in ENGAGEMENT_PATTERNS:
            re.compile(p)


if __name__ == "__main__":
    unittest.main()
