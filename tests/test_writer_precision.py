#!/usr/bin/env python3
"""Tests for writer_precision — measuring language exactness and clarity."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_precision import (  # noqa: E402
    AMBIGUOUS_PRONOUNS,
    APPROXIMATION_PHRASES,
    APPROXIMATION_WORDS,
    HEDGE_PHRASES,
    HEDGE_WORDS,
    PRECISION_CLASSES,
    SIGNAL_WEIGHTS,
    VAGUE_QUANTIFIER_PHRASES,
    VAGUE_QUANTIFIERS,
    _classify_precision,
    _count_approximations,
    _count_specific_numbers,
    _empty_metrics,
    _empty_stroke_metrics,
    _extract_nouns,
    _first_word,
    _get_stroke_text,
    _split_sentences,
    _split_words,
    analyze_precision,
    analyze_stroke_precision,
    classify_trend,
    compute_ambiguous_pronoun_rate,
    compute_hedge_density,
    compute_numerical_precision,
    compute_precision_metrics,
    compute_precision_trend,
    compute_vague_quantifier_rate,
    format_precision_report,
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
        words = _split_words("It's precise, I think.")
        self.assertIn("it's", words)
        self.assertIn("precise", words)

    def test_empty(self):
        self.assertEqual(_split_words(""), [])

    def test_multiple_spaces(self):
        words = _split_words("hello   world")
        self.assertEqual(words, ["hello", "world"])

    def test_numbers_excluded(self):
        words = _split_words("test 42 hello")
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
        sents = _split_sentences("Exact! Precise! Clear!")
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
# Helper: _first_word
# ---------------------------------------------------------------------------


class TestFirstWord(unittest.TestCase):
    """Test _first_word helper."""

    def test_basic(self):
        self.assertEqual(_first_word("Hello world"), "hello")

    def test_punctuation(self):
        self.assertEqual(_first_word("It's a test"), "it's")

    def test_empty(self):
        self.assertEqual(_first_word(""), "")


# ---------------------------------------------------------------------------
# Helper: _extract_nouns
# ---------------------------------------------------------------------------


class TestExtractNouns(unittest.TestCase):
    """Test _extract_nouns helper."""

    def test_basic_nouns(self):
        nouns = _extract_nouns("The system processes requests quickly")
        self.assertIn("system", nouns)
        self.assertIn("processes", nouns)
        self.assertIn("requests", nouns)

    def test_filters_function_words(self):
        nouns = _extract_nouns("that this with from have been")
        self.assertEqual(len(nouns), 0)

    def test_short_words_excluded(self):
        nouns = _extract_nouns("the cat is on mat")
        # "cat" and "mat" are 3 chars, excluded by len > 3 rule
        self.assertNotIn("cat", nouns)
        self.assertNotIn("mat", nouns)


# ---------------------------------------------------------------------------
# Signal 1: Hedge density
# ---------------------------------------------------------------------------


class TestComputeHedgeDensity(unittest.TestCase):
    """Test compute_hedge_density function."""

    def test_no_hedges(self):
        text = "The function returns exactly 42 items."
        result = compute_hedge_density(text)
        self.assertEqual(result, 0.0)

    def test_some_hedges(self):
        text = "Perhaps the system might possibly work correctly."
        result = compute_hedge_density(text)
        self.assertGreater(result, 0.0)
        # hedges found in a short sentence with hedge words
        self.assertGreater(result, 20.0)

    def test_many_hedges(self):
        text = "Perhaps maybe possibly probably likely the system works somewhat."
        result = compute_hedge_density(text)
        self.assertGreater(result, 50.0)

    def test_empty(self):
        self.assertEqual(compute_hedge_density(""), 0.0)

    def test_multi_word_hedges(self):
        text = "It kind of works sort of well in a way."
        result = compute_hedge_density(text)
        self.assertGreater(result, 0.0)

    def test_technical_prose_low_hedges(self):
        text = ("The function accepts a list of integers and returns "
                "their sum. Input must contain at least one element. "
                "Output is always a single integer value.")
        result = compute_hedge_density(text)
        self.assertLess(result, 2.0)


# ---------------------------------------------------------------------------
# Signal 2: Vague quantifier rate
# ---------------------------------------------------------------------------


class TestComputeVagueQuantifierRate(unittest.TestCase):
    """Test compute_vague_quantifier_rate function."""

    def test_no_vague_quantifiers(self):
        text = "The system has 42 active users and 7 pending requests."
        result = compute_vague_quantifier_rate(text)
        self.assertEqual(result, 0.0)

    def test_some_vague_quantifiers(self):
        text = "Many users have several pending requests."
        result = compute_vague_quantifier_rate(text)
        self.assertGreater(result, 0.0)

    def test_multi_word_quantifiers(self):
        text = "A lot of users have quite a bit of pending work."
        result = compute_vague_quantifier_rate(text)
        self.assertGreater(result, 0.0)

    def test_empty(self):
        self.assertEqual(compute_vague_quantifier_rate(""), 0.0)

    def test_precise_numbers(self):
        text = "42 users submitted 128 requests in 3 hours."
        result = compute_vague_quantifier_rate(text)
        self.assertEqual(result, 0.0)


# ---------------------------------------------------------------------------
# Signal 3: Ambiguous pronoun rate
# ---------------------------------------------------------------------------


class TestComputeAmbiguousPronounRate(unittest.TestCase):
    """Test compute_ambiguous_pronoun_rate function."""

    def test_no_ambiguous_pronouns(self):
        text = "The system works. The function returns data. Users enjoy speed."
        result = compute_ambiguous_pronoun_rate(text)
        self.assertEqual(result, 0.0)

    def test_ambiguous_first_sentence(self):
        text = "It is important to test code. The function works well."
        result = compute_ambiguous_pronoun_rate(text)
        self.assertGreater(result, 0.0)

    def test_clear_antecedent(self):
        text = "The system crashed. It needed a restart."
        result = compute_ambiguous_pronoun_rate(text)
        # "system" in prev sentence serves as antecedent
        self.assertEqual(result, 0.0)

    def test_empty(self):
        self.assertEqual(compute_ambiguous_pronoun_rate(""), 0.0)

    def test_multiple_ambiguous(self):
        text = "It matters. This proves the point. That shows the truth."
        result = compute_ambiguous_pronoun_rate(text)
        self.assertGreater(result, 0.0)


# ---------------------------------------------------------------------------
# Signal 4: Numerical precision
# ---------------------------------------------------------------------------


class TestComputeNumericalPrecision(unittest.TestCase):
    """Test compute_numerical_precision function."""

    def test_all_specific(self):
        text = "42 users completed 128 requests in 3.7 seconds."
        result = compute_numerical_precision(text)
        self.assertEqual(result, 1.0)

    def test_all_approximate(self):
        text = "About roughly approximately many users completed requests."
        result = compute_numerical_precision(text)
        self.assertEqual(result, 0.0)

    def test_mixed(self):
        text = "About 42 users completed roughly 100 requests."
        result = compute_numerical_precision(text)
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)

    def test_no_numbers(self):
        text = "The system works perfectly without any numbers."
        result = compute_numerical_precision(text)
        # Neutral score when no numerical content
        self.assertEqual(result, 0.5)

    def test_empty(self):
        result = compute_numerical_precision("")
        self.assertEqual(result, 0.5)

    def test_percentages(self):
        text = "95% of users completed requests in 3 seconds."
        result = compute_numerical_precision(text)
        self.assertGreater(result, 0.5)

    def test_approximation_phrases(self):
        text = "In the ballpark of 50 users on the order of 100 requests."
        result = compute_numerical_precision(text)
        self.assertLess(result, 1.0)


class TestCountSpecificNumbers(unittest.TestCase):
    """Test _count_specific_numbers helper."""

    def test_integers(self):
        self.assertEqual(_count_specific_numbers("42 items"), 1)

    def test_decimals(self):
        self.assertEqual(_count_specific_numbers("3.7 seconds"), 1)

    def test_percentages(self):
        self.assertEqual(_count_specific_numbers("95% confidence"), 1)

    def test_multiple(self):
        text = "42 users and 128 requests"
        self.assertEqual(_count_specific_numbers(text), 2)

    def test_none(self):
        self.assertEqual(_count_specific_numbers("no numbers here"), 0)


class TestCountApproximations(unittest.TestCase):
    """Test _count_approximations helper."""

    def test_single_words(self):
        self.assertEqual(_count_approximations("about 42"), 1)

    def test_phrases(self):
        self.assertEqual(_count_approximations("in the ballpark of"), 1)

    def test_multiple(self):
        self.assertEqual(_count_approximations("roughly about"), 2)

    def test_none(self):
        self.assertEqual(_count_approximations("exactly 42"), 0)


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


class TestAnalyzeStrokePrecision(unittest.TestCase):
    """Test analyze_stroke_precision function."""

    def test_precise_stroke(self):
        text = "42 users completed 128 requests in 3.7 seconds."
        result = analyze_stroke_precision(text)
        self.assertIn("precision_index", result)
        self.assertIn("precision_class", result)
        self.assertGreater(result["precision_index"], 0.0)
        self.assertEqual(result["hedge_density"], 0.0)

    def test_imprecise_stroke(self):
        text = "Perhaps many users might possibly have some sort of issues."
        result = analyze_stroke_precision(text)
        self.assertGreater(result["hedge_density"], 0.0)
        self.assertGreater(result["vague_quantifier_rate"], 0.0)

    def test_empty_stroke(self):
        result = analyze_stroke_precision("")
        self.assertEqual(result["precision_index"], 0.0)
        self.assertEqual(result["precision_class"], "nebulous")

    def test_dict_stroke(self):
        result = analyze_stroke_precision({"text": "42 items processed."})
        self.assertIn("precision_index", result)
        self.assertGreater(result["precision_index"], 0.0)

    def test_return_keys(self):
        result = analyze_stroke_precision("The system works well.")
        expected_keys = {
            "hedge_density", "vague_quantifier_rate",
            "ambiguous_pronoun_rate", "numerical_precision",
            "precision_index", "precision_class",
        }
        self.assertEqual(set(result.keys()), expected_keys)


class TestEmptyStrokeMetrics(unittest.TestCase):
    """Test _empty_stroke_metrics."""

    def test_keys(self):
        result = _empty_stroke_metrics()
        self.assertIn("precision_index", result)
        self.assertIn("precision_class", result)
        self.assertEqual(result["precision_index"], 0.0)
        self.assertEqual(result["precision_class"], "nebulous")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassifyPrecision(unittest.TestCase):
    """Test _classify_precision function."""

    def test_surgical(self):
        self.assertEqual(_classify_precision(0.80), "surgical")
        self.assertEqual(_classify_precision(0.75), "surgical")

    def test_exact(self):
        self.assertEqual(_classify_precision(0.60), "exact")
        self.assertEqual(_classify_precision(0.55), "exact")

    def test_measured(self):
        self.assertEqual(_classify_precision(0.40), "measured")
        self.assertEqual(_classify_precision(0.35), "measured")

    def test_fuzzy(self):
        self.assertEqual(_classify_precision(0.25), "fuzzy")
        self.assertEqual(_classify_precision(0.20), "fuzzy")

    def test_nebulous(self):
        self.assertEqual(_classify_precision(0.10), "nebulous")
        self.assertEqual(_classify_precision(0.00), "nebulous")


# ---------------------------------------------------------------------------
# Session-level aggregation
# ---------------------------------------------------------------------------


class TestComputePrecisionMetrics(unittest.TestCase):
    """Test compute_precision_metrics function."""

    def test_empty_strokes(self):
        result = compute_precision_metrics([])
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["precision_index"], 0.0)

    def test_single_stroke(self):
        strokes = ["42 users completed 128 requests."]
        result = compute_precision_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 1)
        self.assertGreater(result["precision_index"], 0.0)

    def test_multiple_strokes(self):
        strokes = [
            "42 users completed requests.",
            "Perhaps some users might have issues.",
            "The system processes 128 items per second.",
        ]
        result = compute_precision_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 3)
        self.assertIn("class_distribution", result)

    def test_window_size(self):
        strokes = ["stroke " + str(i) for i in range(100)]
        result = compute_precision_metrics(strokes, window_size=10)
        self.assertLessEqual(result["strokes_analyzed"], 10)

    def test_blank_strokes_skipped(self):
        strokes = ["Good content here.", "", "   ", "More content."]
        result = compute_precision_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 2)

    def test_return_keys(self):
        result = compute_precision_metrics(["test stroke"])
        expected_keys = {
            "strokes_analyzed", "total_words", "precision_index",
            "precision_class", "hedge_density", "vague_quantifier_rate",
            "ambiguous_pronoun_rate", "numerical_precision",
            "class_distribution", "stroke_indices",
        }
        self.assertEqual(set(result.keys()), expected_keys)


class TestEmptyMetrics(unittest.TestCase):
    """Test _empty_metrics."""

    def test_values(self):
        result = _empty_metrics()
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["total_words"], 0)
        self.assertEqual(result["precision_index"], 0.0)
        self.assertEqual(result["precision_class"], "nebulous")
        self.assertEqual(result["class_distribution"], {})


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


class TestComputePrecisionTrend(unittest.TestCase):
    """Test compute_precision_trend function."""

    def test_too_few_strokes(self):
        result = compute_precision_trend(["one", "two"])
        self.assertEqual(result["trend"], "stable")

    def test_sharpening(self):
        # Early: imprecise, Late: precise
        early = ["Perhaps maybe possibly some issues exist."] * 5
        late = ["42 users completed 128 requests in 3.7 seconds."] * 5
        result = compute_precision_trend(early + late)
        self.assertEqual(result["trend"], "sharpening")

    def test_blurring(self):
        # Early: precise, Late: imprecise
        early = ["42 users completed 128 requests in 3.7 seconds."] * 5
        late = ["Perhaps maybe possibly some issues exist."] * 5
        result = compute_precision_trend(early + late)
        self.assertEqual(result["trend"], "blurring")

    def test_stable(self):
        strokes = ["The system works correctly."] * 10
        result = compute_precision_trend(strokes)
        self.assertEqual(result["trend"], "stable")


class TestClassifyTrend(unittest.TestCase):
    """Test classify_trend function."""

    def test_sharpening(self):
        self.assertEqual(classify_trend(0.10), "sharpening")
        self.assertEqual(classify_trend(0.06), "sharpening")

    def test_blurring(self):
        self.assertEqual(classify_trend(-0.10), "blurring")
        self.assertEqual(classify_trend(-0.06), "blurring")

    def test_stable(self):
        self.assertEqual(classify_trend(0.00), "stable")
        self.assertEqual(classify_trend(0.04), "stable")
        self.assertEqual(classify_trend(-0.04), "stable")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestFormatPrecisionReport(unittest.TestCase):
    """Test format_precision_report function."""

    def test_basic_report(self):
        metrics = compute_precision_metrics([
            "42 users completed 128 requests in 3.7 seconds.",
        ])
        report = format_precision_report(metrics)
        self.assertIn("Writer Precision", report)
        self.assertIn("precision_index", report.lower().replace(" ", "_").replace(":", ""))

    def test_empty_report(self):
        metrics = _empty_metrics()
        report = format_precision_report(metrics)
        self.assertIn("nebulous", report)

    def test_all_classes_in_report(self):
        for cls in ("surgical", "exact", "measured", "fuzzy", "nebulous"):
            metrics = _empty_metrics()
            metrics["precision_class"] = cls
            report = format_precision_report(metrics)
            self.assertIn(cls, report)


# ---------------------------------------------------------------------------
# Standalone analysis
# ---------------------------------------------------------------------------


class TestAnalyzePrecision(unittest.TestCase):
    """Test analyze_precision function."""

    def test_nonexistent_file(self):
        result = analyze_precision(strokes_path="/nonexistent/path.jsonl")
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["precision_index"], 0.0)


# ---------------------------------------------------------------------------
# Constants integrity
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    """Test that constant definitions are well-formed."""

    def test_hedge_words_not_empty(self):
        self.assertGreater(len(HEDGE_WORDS), 20)

    def test_hedge_phrases_not_empty(self):
        self.assertGreater(len(HEDGE_PHRASES), 10)

    def test_vague_quantifiers_not_empty(self):
        self.assertGreater(len(VAGUE_QUANTIFIERS), 5)

    def test_vague_quantifier_phrases_not_empty(self):
        self.assertGreater(len(VAGUE_QUANTIFIER_PHRASES), 5)

    def test_approximation_words_not_empty(self):
        self.assertGreater(len(APPROXIMATION_WORDS), 5)

    def test_approximation_phrases_not_empty(self):
        self.assertGreater(len(APPROXIMATION_PHRASES), 5)

    def test_ambiguous_pronouns_not_empty(self):
        self.assertGreater(len(AMBIGUOUS_PRONOUNS), 5)

    def test_precision_classes_complete(self):
        labels = [label for _, label in PRECISION_CLASSES]
        self.assertEqual(labels, ["surgical", "exact", "measured", "fuzzy", "nebulous"])

    def test_signal_weights_sum_to_one(self):
        total = sum(SIGNAL_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=5)


# ---------------------------------------------------------------------------
# Integration: realistic prose samples
# ---------------------------------------------------------------------------


class TestRealisticProse(unittest.TestCase):
    """Test with realistic prose samples at different precision levels."""

    def test_surgical_prose(self):
        text = (
            "The function processes exactly 42 requests per second. "
            "Error rate is 0.3%. Response time averages 127 milliseconds. "
            "Memory usage stays below 256 megabytes under load."
        )
        result = analyze_stroke_precision(text)
        self.assertGreaterEqual(result["precision_index"], 0.55)
        self.assertEqual(result["hedge_density"], 0.0)

    def test_nebulous_prose(self):
        text = (
            "Perhaps the system might sort of handle many requests. "
            "It seems like probably a lot of users could possibly "
            "experience somewhat various issues sometimes."
        )
        result = analyze_stroke_precision(text)
        self.assertLess(result["precision_index"], 0.55)
        self.assertGreater(result["hedge_density"], 5.0)

    def test_mixed_prose(self):
        text = (
            "The server handles 100 requests per second. "
            "Some users might experience delays. "
            "About 15% of requests fail occasionally."
        )
        result = analyze_stroke_precision(text)
        self.assertGreater(result["precision_index"], 0.0)
        self.assertLess(result["precision_index"], 1.0)


if __name__ == "__main__":
    unittest.main()
