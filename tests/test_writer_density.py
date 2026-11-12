#!/usr/bin/env python3
"""Tests for writer_density — measuring information payload per word."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_density import (  # noqa: E402
    FILLER_PHRASES,
    FUNCTION_WORDS,
    QUALIFIER_WORDS,
    SIGNAL_WEIGHTS,
    _classify_density,
    _content_words,
    _empty_metrics,
    _empty_stroke_metrics,
    _get_stroke_text,
    _sentence_content_set,
    _split_sentences,
    _split_words,
    analyze_density,
    analyze_stroke_density,
    classify_trend,
    compute_density_metrics,
    compute_density_trend,
    compute_filler_density,
    compute_qualifier_stacking,
    compute_redundancy_rate,
    compute_semantic_payload,
    format_density_report,
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
        words = _split_words("It's a test, perhaps.")
        self.assertIn("it's", words)
        self.assertIn("perhaps", words)

    def test_empty(self):
        self.assertEqual(_split_words(""), [])

    def test_multiple_spaces(self):
        words = _split_words("hello   world")
        self.assertEqual(words, ["hello", "world"])

    def test_numbers_excluded(self):
        words = _split_words("test 123 hello")
        self.assertEqual(words, ["test", "hello"])


# ---------------------------------------------------------------------------
# Helper: _split_sentences
# ---------------------------------------------------------------------------


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_basic(self):
        sents = _split_sentences("Hello world. How are you?")
        self.assertEqual(len(sents), 2)

    def test_single_sentence(self):
        sents = _split_sentences("Just one sentence here.")
        self.assertEqual(len(sents), 1)

    def test_empty(self):
        self.assertEqual(_split_sentences(""), [])

    def test_exclamation(self):
        sents = _split_sentences("Wow! Amazing! Great!")
        self.assertEqual(len(sents), 3)


# ---------------------------------------------------------------------------
# Helper: _get_stroke_text
# ---------------------------------------------------------------------------


class TestGetStrokeText(unittest.TestCase):
    """Test _get_stroke_text helper."""

    def test_string_input(self):
        self.assertEqual(_get_stroke_text("hello"), "hello")

    def test_dict_with_text(self):
        self.assertEqual(_get_stroke_text({"text": "hello"}), "hello")

    def test_dict_without_text(self):
        self.assertEqual(_get_stroke_text({"content": "hello"}), "")

    def test_none(self):
        result = _get_stroke_text(None)
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# Helper: _content_words
# ---------------------------------------------------------------------------


class TestContentWords(unittest.TestCase):
    """Test _content_words helper."""

    def test_filters_function_words(self):
        words = ["the", "cat", "is", "running", "very", "fast"]
        content = _content_words(words)
        self.assertIn("cat", content)
        self.assertIn("running", content)
        self.assertIn("fast", content)
        self.assertNotIn("the", content)
        self.assertNotIn("is", content)
        self.assertNotIn("very", content)

    def test_filters_single_chars(self):
        words = ["a", "i", "cat", "x"]
        content = _content_words(words)
        self.assertEqual(content, ["cat"])

    def test_empty(self):
        self.assertEqual(_content_words([]), [])


# ---------------------------------------------------------------------------
# Helper: _sentence_content_set
# ---------------------------------------------------------------------------


class TestSentenceContentSet(unittest.TestCase):
    """Test _sentence_content_set."""

    def test_basic(self):
        result = _sentence_content_set("The quick brown fox")
        self.assertIn("quick", result)
        self.assertIn("brown", result)
        self.assertIn("fox", result)
        self.assertNotIn("the", result)


# ---------------------------------------------------------------------------
# Signal 1: Semantic payload
# ---------------------------------------------------------------------------


class TestSemanticPayload(unittest.TestCase):
    """Test compute_semantic_payload."""

    def test_all_content(self):
        # Words not in FUNCTION_WORDS and length > 1
        text = "philosophy mathematics architecture"
        payload = compute_semantic_payload(text)
        self.assertGreater(payload, 0.8)

    def test_all_function(self):
        text = "the a an is are was were"
        payload = compute_semantic_payload(text)
        self.assertEqual(payload, 0.0)

    def test_mixed(self):
        text = "The cat sat on the mat"
        payload = compute_semantic_payload(text)
        # "cat", "sat", "mat" are content; "the", "on" are function
        self.assertGreater(payload, 0.3)
        self.assertLess(payload, 0.7)

    def test_empty(self):
        self.assertEqual(compute_semantic_payload(""), 0.0)

    def test_range(self):
        text = "Writing dense prose means every word carries meaning forward"
        payload = compute_semantic_payload(text)
        self.assertGreaterEqual(payload, 0.0)
        self.assertLessEqual(payload, 1.0)


# ---------------------------------------------------------------------------
# Signal 2: Redundancy rate
# ---------------------------------------------------------------------------


class TestRedundancyRate(unittest.TestCase):
    """Test compute_redundancy_rate."""

    def test_high_redundancy(self):
        text = (
            "The cat sat on the mat. "
            "The cat was sitting on the mat. "
            "A cat was on a mat sitting."
        )
        rate = compute_redundancy_rate(text)
        self.assertGreater(rate, 0.2)

    def test_low_redundancy(self):
        text = (
            "Quantum computing uses qubits. "
            "Photosynthesis converts light to energy. "
            "Shakespeare wrote thirty-seven plays."
        )
        rate = compute_redundancy_rate(text)
        self.assertLess(rate, 0.2)

    def test_single_sentence(self):
        rate = compute_redundancy_rate("Just one sentence.")
        self.assertEqual(rate, 0.0)

    def test_empty(self):
        self.assertEqual(compute_redundancy_rate(""), 0.0)


# ---------------------------------------------------------------------------
# Signal 3: Qualifier stacking
# ---------------------------------------------------------------------------


class TestQualifierStacking(unittest.TestCase):
    """Test compute_qualifier_stacking."""

    def test_stacked(self):
        text = "The very extremely remarkably profoundly decision was made"
        stacking = compute_qualifier_stacking(text)
        self.assertGreater(stacking, 0.0)

    def test_no_stacking(self):
        text = "The decision was made quickly"
        stacking = compute_qualifier_stacking(text)
        self.assertEqual(stacking, 0.0)

    def test_single_qualifier(self):
        text = "It was very good"
        stacking = compute_qualifier_stacking(text)
        # Single qualifier doesn't count as a stack
        self.assertEqual(stacking, 0.0)

    def test_empty(self):
        self.assertEqual(compute_qualifier_stacking(""), 0.0)

    def test_short_text(self):
        self.assertEqual(compute_qualifier_stacking("hi"), 0.0)

    def test_multiple_stacks(self):
        text = (
            "The very extremely important decision and the "
            "highly remarkably significant event happened"
        )
        stacking = compute_qualifier_stacking(text)
        self.assertGreater(stacking, 0.0)


# ---------------------------------------------------------------------------
# Signal 4: Filler density
# ---------------------------------------------------------------------------


class TestFillerDensity(unittest.TestCase):
    """Test compute_filler_density."""

    def test_with_filler(self):
        text = (
            "It is important to note that the algorithm works well. "
            "At the end of the day, performance matters. "
            "In terms of speed, it is fast."
        )
        filler = compute_filler_density(text)
        self.assertGreater(filler, 0.0)

    def test_no_filler(self):
        text = "The algorithm performs well under load with low latency"
        filler = compute_filler_density(text)
        self.assertEqual(filler, 0.0)

    def test_empty(self):
        self.assertEqual(compute_filler_density(""), 0.0)

    def test_repeated_filler(self):
        text = (
            "In terms of speed it is fast. "
            "In terms of memory it is efficient."
        )
        filler = compute_filler_density(text)
        self.assertGreater(filler, 0.0)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassifyDensity(unittest.TestCase):
    """Test _classify_density."""

    def test_concentrated(self):
        self.assertEqual(_classify_density(0.80), "concentrated")

    def test_dense(self):
        self.assertEqual(_classify_density(0.60), "dense")

    def test_moderate(self):
        self.assertEqual(_classify_density(0.40), "moderate")

    def test_thin(self):
        self.assertEqual(_classify_density(0.25), "thin")

    def test_dilute(self):
        self.assertEqual(_classify_density(0.10), "dilute")

    def test_boundary(self):
        self.assertEqual(_classify_density(0.75), "concentrated")
        self.assertEqual(_classify_density(0.55), "dense")
        self.assertEqual(_classify_density(0.35), "moderate")
        self.assertEqual(_classify_density(0.20), "thin")

    def test_zero(self):
        self.assertEqual(_classify_density(0.0), "dilute")


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


class TestAnalyzeStrokeDensity(unittest.TestCase):
    """Test analyze_stroke_density."""

    def test_dense_text(self):
        text = "Quantum entanglement enables instantaneous correlation across arbitrary distances"
        result = analyze_stroke_density(text)
        self.assertIn("density_index", result)
        self.assertIn("density_class", result)
        self.assertGreater(result["semantic_payload"], 0.5)

    def test_empty_text(self):
        result = analyze_stroke_density("")
        self.assertEqual(result["density_index"], 0.0)
        self.assertEqual(result["density_class"], "dilute")

    def test_dict_stroke(self):
        result = analyze_stroke_density({"text": "Neural networks learn hierarchical representations"})
        self.assertGreater(result["density_index"], 0.0)

    def test_result_keys(self):
        result = analyze_stroke_density("Some text here")
        expected_keys = {
            "semantic_payload", "redundancy_rate", "qualifier_stacking",
            "filler_density", "density_index", "density_class",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_padded_text(self):
        text = (
            "It is important to note that, at the end of the day, "
            "the very extremely important thing is that, in terms of "
            "the actual result, it is what it is."
        )
        result = analyze_stroke_density(text)
        # Should have lower density due to filler and stacking
        self.assertLess(result["density_index"], 0.7)


# ---------------------------------------------------------------------------
# Session-level metrics
# ---------------------------------------------------------------------------


class TestComputeDensityMetrics(unittest.TestCase):
    """Test compute_density_metrics."""

    def test_empty(self):
        result = compute_density_metrics([])
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["density_class"], "dilute")

    def test_single_stroke(self):
        strokes = ["Neural networks learn hierarchical feature representations automatically"]
        result = compute_density_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 1)
        self.assertGreater(result["density_index"], 0.0)

    def test_multiple_strokes(self):
        strokes = [
            "Quantum computing leverages superposition",
            "Photosynthesis converts solar energy to glucose",
            "Topology studies properties invariant under deformation",
        ]
        result = compute_density_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 3)
        self.assertIn("class_distribution", result)
        self.assertIn("stroke_indices", result)
        self.assertEqual(len(result["stroke_indices"]), 3)

    def test_window_size(self):
        strokes = [f"Stroke number {i} about science" for i in range(100)]
        result = compute_density_metrics(strokes, window_size=20)
        self.assertEqual(result["strokes_analyzed"], 20)

    def test_blank_strokes_skipped(self):
        strokes = ["Good content here", "", "  ", "More content here"]
        result = compute_density_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 2)

    def test_dict_strokes(self):
        strokes = [
            {"text": "Algorithm complexity determines runtime performance"},
            {"text": "Data structures organize information efficiently"},
        ]
        result = compute_density_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 2)


# ---------------------------------------------------------------------------
# Empty metrics helpers
# ---------------------------------------------------------------------------


class TestEmptyMetrics(unittest.TestCase):
    """Test _empty_metrics and _empty_stroke_metrics."""

    def test_empty_metrics_keys(self):
        m = _empty_metrics()
        self.assertEqual(m["strokes_analyzed"], 0)
        self.assertEqual(m["density_class"], "dilute")
        self.assertIn("class_distribution", m)

    def test_empty_stroke_keys(self):
        m = _empty_stroke_metrics()
        self.assertEqual(m["density_index"], 0.0)
        self.assertEqual(m["density_class"], "dilute")


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


class TestDensityTrend(unittest.TestCase):
    """Test compute_density_trend and classify_trend."""

    def test_empty(self):
        self.assertEqual(compute_density_trend([]), [])

    def test_snapshots_returned(self):
        strokes = [f"Technical content about {topic}" for topic in
                   ["algorithms", "networks", "databases", "systems",
                    "protocols", "encryption", "compression", "parsing",
                    "compiling", "linking", "loading", "scheduling",
                    "threading", "locking", "caching", "indexing",
                    "sorting", "hashing", "buffering", "streaming"]]
        snapshots = compute_density_trend(strokes, window_size=5, step=5)
        self.assertGreater(len(snapshots), 0)

    def test_classify_insufficient(self):
        self.assertEqual(classify_trend([]), "insufficient_data")
        self.assertEqual(classify_trend([{"density_index": 0.5}]), "insufficient_data")

    def test_classify_stable(self):
        snapshots = [{"density_index": 0.5} for _ in range(4)]
        self.assertEqual(classify_trend(snapshots), "stable")

    def test_classify_concentrating(self):
        snapshots = [
            {"density_index": 0.3},
            {"density_index": 0.3},
            {"density_index": 0.7},
            {"density_index": 0.7},
        ]
        self.assertEqual(classify_trend(snapshots), "concentrating")

    def test_classify_thinning(self):
        snapshots = [
            {"density_index": 0.7},
            {"density_index": 0.7},
            {"density_index": 0.3},
            {"density_index": 0.3},
        ]
        self.assertEqual(classify_trend(snapshots), "thinning")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestFormatDensityReport(unittest.TestCase):
    """Test format_density_report."""

    def test_basic_report(self):
        metrics = compute_density_metrics([
            "Information density measures payload per word",
            "Dense prose makes every word count",
        ])
        report = format_density_report(metrics)
        self.assertIn("Writer Density", report)
        self.assertIn("Strokes analyzed", report)
        self.assertIn("Density index", report)
        self.assertIn("Interpretation", report)

    def test_empty_report(self):
        report = format_density_report(_empty_metrics())
        self.assertIn("Writer Density", report)
        self.assertIn("Strokes analyzed:          0", report)

    def test_all_classes(self):
        for cls_name in ("concentrated", "dense", "moderate", "thin", "dilute"):
            metrics = _empty_metrics()
            metrics["density_class"] = cls_name
            report = format_density_report(metrics)
            self.assertIn("Interpretation", report)


# ---------------------------------------------------------------------------
# Standalone analysis
# ---------------------------------------------------------------------------


class TestAnalyzeDensity(unittest.TestCase):
    """Test analyze_density with non-existent file."""

    def test_missing_file(self):
        result = analyze_density(strokes_path="/tmp/nonexistent_density_test.jsonl")
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["density_class"], "dilute")


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    """Sanity checks for module constants."""

    def test_function_words_not_empty(self):
        self.assertGreater(len(FUNCTION_WORDS), 50)

    def test_filler_phrases_not_empty(self):
        self.assertGreater(len(FILLER_PHRASES), 10)

    def test_qualifier_words_not_empty(self):
        self.assertGreater(len(QUALIFIER_WORDS), 15)

    def test_weights_sum_to_one(self):
        total = sum(SIGNAL_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=5)


# ---------------------------------------------------------------------------
# Integration: dense vs dilute text
# ---------------------------------------------------------------------------


class TestIntegrationDenseVsDilute(unittest.TestCase):
    """Compare dense and dilute texts to verify the metric discriminates."""

    def test_dense_scores_higher(self):
        dense = (
            "Photosynthesis converts solar radiation into chemical energy "
            "stored in glucose molecules via the Calvin cycle"
        )
        dilute = (
            "It is important to note that, at the end of the day, "
            "the very extremely important thing about photosynthesis "
            "is that, in terms of the actual process, it basically "
            "sort of converts light into, you know, energy, as a "
            "matter of fact"
        )
        dense_result = analyze_stroke_density(dense)
        dilute_result = analyze_stroke_density(dilute)
        self.assertGreater(
            dense_result["density_index"],
            dilute_result["density_index"],
        )

    def test_redundant_text_low_score(self):
        redundant = (
            "The algorithm is fast. The algorithm runs quickly. "
            "It is a fast algorithm. Speed is something the algorithm has. "
            "Running fast is what the algorithm does."
        )
        result = analyze_stroke_density(redundant)
        self.assertLess(result["density_index"], 0.65)


if __name__ == "__main__":
    unittest.main()
