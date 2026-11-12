#!/usr/bin/env python3
"""Tests for writer_elegance — elegance as the art of simplicity with depth."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_elegance import (  # noqa: E402
    ACTIVE_OPENERS,
    ADVERB_EXCEPTIONS,
    ADVERB_PATTERN,
    FILLER_WORDS,
    PASSIVE_PATTERNS,
    REDUNDANT_MODIFIERS,
    THROAT_CLEARING,
    _classify_elegance,
    _count_pattern_matches,
    _get_content_words,
    _get_stroke_text,
    _split_sentences,
    _split_words,
    analyze_elegance,
    analyze_stroke_elegance,
    classify_trend,
    compute_active_passive_ratio,
    compute_adverb_density,
    compute_elegance_metrics,
    compute_elegance_trend,
    compute_sentence_variety,
    compute_vocabulary_efficiency,
    format_elegance_report,
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

    def test_multiple_spaces(self):
        words = _split_words("hello   world")
        self.assertEqual(words, ["hello", "world"])


# ---------------------------------------------------------------------------
# Helper: _split_sentences
# ---------------------------------------------------------------------------


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_basic(self):
        sents = _split_sentences("Hello world. How are you?")
        self.assertEqual(len(sents), 2)

    def test_abbreviation(self):
        sents = _split_sentences("Dr. Smith arrived. He was late.")
        self.assertEqual(len(sents), 2)

    def test_single_sentence(self):
        sents = _split_sentences("Just one sentence here.")
        self.assertEqual(len(sents), 1)

    def test_empty(self):
        self.assertEqual(_split_sentences(""), [])


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

    def test_dict_with_body(self):
        self.assertEqual(_get_stroke_text({"body": "hello"}), "hello")

    def test_dict_empty(self):
        self.assertEqual(_get_stroke_text({}), "")

    def test_dict_non_string(self):
        self.assertEqual(_get_stroke_text({"text": 42}), "")


# ---------------------------------------------------------------------------
# Helper: _get_content_words
# ---------------------------------------------------------------------------


class TestGetContentWords(unittest.TestCase):
    """Test _get_content_words helper."""

    def test_filters_function_words(self):
        words = ["the", "cat", "is", "on", "the", "mat"]
        content = _get_content_words(words)
        self.assertIn("cat", content)
        self.assertIn("mat", content)
        self.assertNotIn("the", content)
        self.assertNotIn("is", content)

    def test_empty(self):
        self.assertEqual(_get_content_words([]), [])

    def test_all_function_words(self):
        words = ["the", "a", "is", "are", "of", "in"]
        self.assertEqual(_get_content_words(words), [])

    def test_single_char_ignored(self):
        words = ["a", "i", "cat"]
        content = _get_content_words(words)
        self.assertEqual(content, ["cat"])


# ---------------------------------------------------------------------------
# Helper: _classify_elegance
# ---------------------------------------------------------------------------


class TestClassifyElegance(unittest.TestCase):
    """Test _classify_elegance classifier."""

    def test_refined(self):
        self.assertEqual(_classify_elegance(0.80), "refined")
        self.assertEqual(_classify_elegance(0.75), "refined")
        self.assertEqual(_classify_elegance(1.0), "refined")

    def test_polished(self):
        self.assertEqual(_classify_elegance(0.55), "polished")
        self.assertEqual(_classify_elegance(0.65), "polished")
        self.assertEqual(_classify_elegance(0.74), "polished")

    def test_functional(self):
        self.assertEqual(_classify_elegance(0.35), "functional")
        self.assertEqual(_classify_elegance(0.45), "functional")
        self.assertEqual(_classify_elegance(0.54), "functional")

    def test_cluttered(self):
        self.assertEqual(_classify_elegance(0.20), "cluttered")
        self.assertEqual(_classify_elegance(0.30), "cluttered")
        self.assertEqual(_classify_elegance(0.34), "cluttered")

    def test_lead(self):
        self.assertEqual(_classify_elegance(0.0), "lead")
        self.assertEqual(_classify_elegance(0.10), "lead")
        self.assertEqual(_classify_elegance(0.19), "lead")


# ---------------------------------------------------------------------------
# Signal 1: Vocabulary efficiency
# ---------------------------------------------------------------------------


class TestVocabularyEfficiency(unittest.TestCase):
    """Test compute_vocabulary_efficiency."""

    def test_empty_text(self):
        result = compute_vocabulary_efficiency("")
        self.assertEqual(result["total_waste"], 0)
        self.assertAlmostEqual(result["efficiency"], 1.0)

    def test_clean_text(self):
        text = "The server processed the request and returned a response."
        result = compute_vocabulary_efficiency(text)
        self.assertEqual(result["fillers"], 0)
        self.assertEqual(result["redundant_modifiers"], 0)
        self.assertEqual(result["throat_clearing"], 0)
        self.assertAlmostEqual(result["efficiency"], 1.0)

    def test_filler_heavy(self):
        text = "Basically, it is really very important to actually understand this."
        result = compute_vocabulary_efficiency(text)
        self.assertGreater(result["fillers"], 2)
        self.assertLess(result["efficiency"], 1.0)

    def test_redundant_modifiers(self):
        text = "The task was completely finished. It was absolutely essential."
        result = compute_vocabulary_efficiency(text)
        self.assertGreater(result["redundant_modifiers"], 0)

    def test_throat_clearing(self):
        text = "It is important to note that the system works. It should be mentioned that tests pass."
        result = compute_vocabulary_efficiency(text)
        self.assertGreater(result["throat_clearing"], 0)

    def test_efficiency_bounded(self):
        text = "Basically really actually very just quite rather somewhat fairly essentially."
        result = compute_vocabulary_efficiency(text)
        self.assertGreaterEqual(result["efficiency"], 0.0)
        self.assertLessEqual(result["efficiency"], 1.0)

    def test_word_count(self):
        text = "One two three four five."
        result = compute_vocabulary_efficiency(text)
        self.assertEqual(result["word_count"], 5)


# ---------------------------------------------------------------------------
# Signal 2: Sentence variety
# ---------------------------------------------------------------------------


class TestSentenceVariety(unittest.TestCase):
    """Test compute_sentence_variety."""

    def test_empty_text(self):
        result = compute_sentence_variety("")
        self.assertEqual(result["sentence_count"], 0)
        self.assertAlmostEqual(result["variety_score"], 0.0)

    def test_single_sentence(self):
        result = compute_sentence_variety("Just one sentence here.")
        self.assertEqual(result["sentence_count"], 1)
        self.assertAlmostEqual(result["variety_score"], 0.0)

    def test_uniform_sentences(self):
        # All same length → low variety
        text = "The cat sat on mat. The dog ran fast now. The bird flew up high."
        result = compute_sentence_variety(text)
        self.assertLess(result["cv"], 0.3)

    def test_varied_sentences(self):
        text = (
            "The entire system had been designed with careful consideration of every "
            "possible edge case and failure mode that could arise in production. "
            "It worked. "
            "Mostly."
        )
        result = compute_sentence_variety(text)
        self.assertGreater(result["cv"], 0.3)

    def test_opener_diversity_high(self):
        text = "The cat sat. Dogs ran away. Birds flew high. Fish swam deep."
        result = compute_sentence_variety(text)
        self.assertGreater(result["opener_diversity"], 0.5)

    def test_opener_diversity_low(self):
        text = "The cat sat. The cat ran. The cat slept. The cat woke."
        result = compute_sentence_variety(text)
        # All start with "the" → low diversity
        self.assertLessEqual(result["opener_diversity"], 0.5)

    def test_variety_score_bounded(self):
        text = "Short one. A much longer sentence follows this one with many words."
        result = compute_sentence_variety(text)
        self.assertGreaterEqual(result["variety_score"], 0.0)
        self.assertLessEqual(result["variety_score"], 1.0)

    def test_mean_length(self):
        text = "One two. Three four five six."
        result = compute_sentence_variety(text)
        self.assertAlmostEqual(result["mean_length"], 3.0, places=0)


# ---------------------------------------------------------------------------
# Signal 3: Active/passive ratio
# ---------------------------------------------------------------------------


class TestActivePassiveRatio(unittest.TestCase):
    """Test compute_active_passive_ratio."""

    def test_empty_text(self):
        result = compute_active_passive_ratio("")
        self.assertAlmostEqual(result["active_ratio"], 0.5)

    def test_mostly_active(self):
        text = "She wrote the code. He designed the system. They tested the feature."
        result = compute_active_passive_ratio(text)
        self.assertGreater(result["active_count"], 0)

    def test_passive_detection(self):
        text = "The code was written by her. The system was designed by him."
        result = compute_active_passive_ratio(text)
        self.assertGreater(result["passive_count"], 0)

    def test_ratio_bounded(self):
        text = "She wrote code. The code was written. He runs tests."
        result = compute_active_passive_ratio(text)
        self.assertGreaterEqual(result["active_ratio"], 0.0)
        self.assertLessEqual(result["active_ratio"], 1.0)

    def test_word_count(self):
        text = "One two three."
        result = compute_active_passive_ratio(text)
        self.assertEqual(result["word_count"], 3)


# ---------------------------------------------------------------------------
# Signal 4: Adverb density
# ---------------------------------------------------------------------------


class TestAdverbDensity(unittest.TestCase):
    """Test compute_adverb_density."""

    def test_empty_text(self):
        result = compute_adverb_density("")
        self.assertEqual(result["adverb_count"], 0)
        self.assertAlmostEqual(result["density"], 0.0)

    def test_adverb_heavy(self):
        text = "She quickly and silently walked slowly and carefully through the darkly lit room."
        result = compute_adverb_density(text)
        self.assertGreater(result["adverb_count"], 2)
        self.assertGreater(result["density"], 0.0)

    def test_no_adverbs(self):
        text = "The server processed the request and returned a response."
        result = compute_adverb_density(text)
        self.assertEqual(result["adverb_count"], 0)

    def test_exceptions_excluded(self):
        text = "The family was friendly and lovely. It was early and lonely."
        result = compute_adverb_density(text)
        # These are in ADVERB_EXCEPTIONS and should not count
        self.assertEqual(result["adverb_count"], 0)

    def test_density_calculation(self):
        # 10 words, 2 adverbs → density 20.0
        text = "She quickly ran slowly through the big old dark house today."
        result = compute_adverb_density(text)
        self.assertGreater(result["density"], 0.0)

    def test_word_count(self):
        text = "One two three."
        result = compute_adverb_density(text)
        self.assertEqual(result["word_count"], 3)


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


class TestAnalyzeStrokeElegance(unittest.TestCase):
    """Test analyze_stroke_elegance."""

    def test_empty_stroke(self):
        result = analyze_stroke_elegance("")
        self.assertEqual(result["elegance_class"], "lead")
        self.assertAlmostEqual(result["elegance_score"], 0.0)

    def test_dict_stroke(self):
        result = analyze_stroke_elegance({"text": "She wrote the code."})
        self.assertIn("elegance_score", result)
        self.assertIn("elegance_class", result)

    def test_elegant_text(self):
        text = (
            "She wrote the function and tested it. The code ran clean. "
            "No errors surfaced."
        )
        result = analyze_stroke_elegance(text)
        self.assertGreater(result["elegance_score"], 0.0)

    def test_inelegant_text(self):
        text = (
            "Basically, it is really very important to note that the code was "
            "completely finished and was absolutely essential to the process."
        )
        result = analyze_stroke_elegance(text)
        self.assertGreater(result["vocabulary"]["total_waste"], 0)

    def test_structure_keys(self):
        result = analyze_stroke_elegance("Hello world.")
        for key in ("vocabulary", "variety", "voice", "adverbs", "elegance_score", "elegance_class"):
            self.assertIn(key, result)

    def test_whitespace_only(self):
        result = analyze_stroke_elegance("   \n\t  ")
        self.assertEqual(result["elegance_class"], "lead")

    def test_dict_with_content_key(self):
        result = analyze_stroke_elegance({"content": "She wrote the code."})
        self.assertIn("elegance_score", result)

    def test_dict_with_body_key(self):
        result = analyze_stroke_elegance({"body": "The code was written by her."})
        self.assertGreater(result["voice"]["passive_count"], 0)


# ---------------------------------------------------------------------------
# Session-level metrics
# ---------------------------------------------------------------------------


class TestEleganceMetrics(unittest.TestCase):
    """Test compute_elegance_metrics."""

    def test_empty_strokes(self):
        result = compute_elegance_metrics([])
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["elegance_class"], "lead")

    def test_single_stroke(self):
        result = compute_elegance_metrics(["She wrote the code."])
        self.assertEqual(result["strokes_analyzed"], 1)
        self.assertIn("elegance_index", result)

    def test_window_size(self):
        strokes = [f"Sentence number {i} in the sequence." for i in range(100)]
        result = compute_elegance_metrics(strokes, window_size=10)
        self.assertEqual(result["strokes_analyzed"], 10)

    def test_class_distribution(self):
        strokes = [
            "She wrote the function and tested it.",
            "The code was written by the developer.",
            "Basically, it is really very important.",
            "The server processed the request successfully.",
            "He ran the tests. They passed.",
        ]
        result = compute_elegance_metrics(strokes)
        self.assertIsInstance(result["class_distribution"], dict)
        self.assertGreater(len(result["class_distribution"]), 0)

    def test_aggregate_counts(self):
        strokes = [
            "Basically, it is really very important to note that this works.",
            "She quickly wrote the code. The code was written by her.",
        ]
        result = compute_elegance_metrics(strokes)
        self.assertGreater(result["total_fillers"], 0)
        self.assertGreater(result["total_adverbs"], 0)

    def test_active_ratio_aggregation(self):
        strokes = [
            "She wrote the code. He designed the system.",
            "The code was written. The system was designed.",
        ]
        result = compute_elegance_metrics(strokes)
        self.assertGreater(result["total_active"] + result["total_passive"], 0)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


class TestEleganceTrend(unittest.TestCase):
    """Test compute_elegance_trend and classify_trend."""

    def test_empty_strokes(self):
        self.assertEqual(compute_elegance_trend([]), [])

    def test_single_window(self):
        strokes = ["She wrote the code."] * 20
        snapshots = compute_elegance_trend(strokes, window_size=20, step=10)
        self.assertEqual(len(snapshots), 1)

    def test_multiple_windows(self):
        strokes = ["She wrote the code."] * 50
        snapshots = compute_elegance_trend(strokes, window_size=20, step=10)
        self.assertGreater(len(snapshots), 1)

    def test_classify_insufficient_data(self):
        self.assertEqual(classify_trend([]), "insufficient_data")
        self.assertEqual(classify_trend([{"elegance_index": 0.5}]), "insufficient_data")

    def test_classify_refining(self):
        snapshots = [
            {"elegance_index": 0.3},
            {"elegance_index": 0.3},
            {"elegance_index": 0.5},
            {"elegance_index": 0.6},
        ]
        self.assertEqual(classify_trend(snapshots), "refining")

    def test_classify_degrading(self):
        snapshots = [
            {"elegance_index": 0.7},
            {"elegance_index": 0.6},
            {"elegance_index": 0.3},
            {"elegance_index": 0.2},
        ]
        self.assertEqual(classify_trend(snapshots), "degrading")

    def test_classify_stable(self):
        snapshots = [
            {"elegance_index": 0.5},
            {"elegance_index": 0.5},
            {"elegance_index": 0.5},
            {"elegance_index": 0.5},
        ]
        self.assertEqual(classify_trend(snapshots), "stable")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


class TestFormatReport(unittest.TestCase):
    """Test format_elegance_report."""

    def test_empty_report(self):
        from iamai.writer_elegance import _empty_metrics
        report = format_elegance_report(_empty_metrics())
        self.assertIn("Writer Elegance", report)
        self.assertIn("lead", report)

    def test_populated_report(self):
        metrics = compute_elegance_metrics([
            "She wrote the code and tested it.",
            "The code was written by the developer.",
        ])
        report = format_elegance_report(metrics)
        self.assertIn("Elegance index", report)
        self.assertIn("Interpretation", report)

    def test_all_classes_in_report(self):
        """Ensure each class gets an interpretation message."""
        from iamai.writer_elegance import _empty_metrics
        for cls, score in [("refined", 0.8), ("polished", 0.6), ("functional", 0.4), ("cluttered", 0.25), ("lead", 0.1)]:
            metrics = _empty_metrics()
            metrics["elegance_class"] = cls
            metrics["elegance_index"] = score
            report = format_elegance_report(metrics)
            self.assertIn("Interpretation", report)


# ---------------------------------------------------------------------------
# Standalone analysis
# ---------------------------------------------------------------------------


class TestAnalyzeElegance(unittest.TestCase):
    """Test analyze_elegance standalone function."""

    def test_missing_file(self):
        result = analyze_elegance("/nonexistent/path.jsonl")
        self.assertEqual(result["strokes_analyzed"], 0)

    def test_valid_file(self):
        """Test with a temporary strokes file."""
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"text": "She wrote the code and tested it."}\n')
            f.write('{"text": "The code was written by the developer."}\n')
            f.write('{"text": "He ran the tests. They passed."}\n')
            tmp = f.name
        try:
            result = analyze_elegance(tmp, window_size=10)
            self.assertEqual(result["strokes_analyzed"], 3)
            self.assertGreater(result["total_words"], 0)
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# Pattern completeness sanity checks
# ---------------------------------------------------------------------------


class TestPatternSanity(unittest.TestCase):
    """Sanity checks that pattern lists are non-empty and compile."""

    def test_filler_words_exist(self):
        self.assertGreater(len(FILLER_WORDS), 0)

    def test_redundant_modifiers_exist(self):
        self.assertGreater(len(REDUNDANT_MODIFIERS), 0)

    def test_throat_clearing_exist(self):
        self.assertGreater(len(THROAT_CLEARING), 0)

    def test_passive_patterns_exist(self):
        self.assertGreater(len(PASSIVE_PATTERNS), 0)

    def test_active_openers_exist(self):
        self.assertGreater(len(ACTIVE_OPENERS), 0)

    def test_adverb_pattern_compiles(self):
        self.assertIsNotNone(ADVERB_PATTERN)

    def test_adverb_exceptions_nonempty(self):
        self.assertGreater(len(ADVERB_EXCEPTIONS), 0)

    def test_all_patterns_compile(self):
        """Ensure all patterns are valid compiled regexes."""
        import re
        all_patterns = (
            FILLER_WORDS
            + REDUNDANT_MODIFIERS
            + THROAT_CLEARING
            + PASSIVE_PATTERNS
            + ACTIVE_OPENERS
        )
        for pat in all_patterns:
            self.assertIsInstance(pat, re.Pattern)


# ---------------------------------------------------------------------------
# Integration: elegance classification
# ---------------------------------------------------------------------------


class TestEleganceIntegration(unittest.TestCase):
    """Integration tests for elegance classification."""

    def test_elegant_passage(self):
        """Clean, varied, active prose."""
        text = (
            "She wrote the function. It processed the input and returned a "
            "result. The tests passed. No errors surfaced."
        )
        result = analyze_stroke_elegance(text)
        self.assertEqual(result["vocabulary"]["fillers"], 0)
        self.assertGreater(result["elegance_score"], 0.2)

    def test_cluttered_passage(self):
        """Filler-heavy, passive, adverb-laden prose."""
        text = (
            "It is important to note that the code was basically written and "
            "was completely finished by the developer. The tests were run and "
            "were basically passed successfully. It should be mentioned that "
            "the system was actually really very carefully designed."
        )
        result = analyze_stroke_elegance(text)
        self.assertGreater(result["vocabulary"]["total_waste"], 2)
        self.assertGreater(result["adverbs"]["adverb_count"], 0)

    def test_mixed_passage(self):
        """A mix of elegant and inelegant elements."""
        text = (
            "She quickly wrote the function and tested it. The code was "
            "processed by the system. It worked. Basically, the feature "
            "was deployed successfully."
        )
        result = analyze_stroke_elegance(text)
        self.assertGreater(result["elegance_score"], 0.0)
        self.assertIn(result["elegance_class"],
                      ["refined", "polished", "functional", "cluttered", "lead"])


if __name__ == "__main__":
    unittest.main()
