#!/usr/bin/env python3
"""Tests for writer_readability — readability as access signal."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_readability import (  # noqa: E402
    _classify_readability,
    _count_complex_words,
    _count_hedge_words,
    _count_nominalizations,
    _count_syllables,
    _get_stroke_text,
    _split_sentences,
    _split_words,
    analyze_stroke_readability,
    compute_hedge_ratio,
    compute_nominalization_ratio,
    compute_readability_index,
    compute_readability_metrics,
    compute_sentence_length_score,
    compute_complex_word_ratio,
    format_readability_report,
)


# ---------------------------------------------------------------------------
# Helper: _count_syllables
# ---------------------------------------------------------------------------

class TestCountSyllables(unittest.TestCase):
    """Test _count_syllables helper."""

    def test_one_syllable(self):
        self.assertEqual(_count_syllables("cat"), 1)
        self.assertEqual(_count_syllables("the"), 1)
        self.assertEqual(_count_syllables("run"), 1)

    def test_two_syllables(self):
        self.assertEqual(_count_syllables("running"), 2)
        self.assertEqual(_count_syllables("paper"), 2)

    def test_three_syllables(self):
        self.assertEqual(_count_syllables("beautiful"), 3)
        self.assertEqual(_count_syllables("computer"), 3)

    def test_four_plus_syllables(self):
        self.assertGreaterEqual(_count_syllables("implementation"), 4)
        self.assertGreaterEqual(_count_syllables("understanding"), 3)

    def test_empty_string(self):
        self.assertEqual(_count_syllables(""), 0)

    def test_single_char(self):
        self.assertEqual(_count_syllables("a"), 1)

    def test_silent_e(self):
        # "make" has 1 syllable despite trailing 'e'
        self.assertEqual(_count_syllables("make"), 1)
        # "table" has 2 syllables (le ending after consonant)
        self.assertEqual(_count_syllables("table"), 2)

    def test_double_vowel(self):
        # "rain" has 1 syllable (vowel pair)
        self.assertEqual(_count_syllables("rain"), 1)
        self.assertEqual(_count_syllables("read"), 1)


# ---------------------------------------------------------------------------
# Helper: _split_words
# ---------------------------------------------------------------------------

class TestSplitWords(unittest.TestCase):
    """Test _split_words helper."""

    def test_basic(self):
        result = _split_words("Hello world")
        self.assertEqual(result, ["hello", "world"])

    def test_empty(self):
        self.assertEqual(_split_words(""), [])

    def test_punctuation_stripped(self):
        result = _split_words("Hello, world! How are you?")
        self.assertEqual(len(result), 5)
        for w in result:
            self.assertTrue(w.isalpha() or w.isdigit() or "-" in w,
                            f"word '{w}' should be clean")

    def test_numbers_excluded(self):
        result = _split_words("There are 42 items here.")
        # numbers should be filtered or handled
        self.assertGreaterEqual(len(result), 3)

    def test_hyphenated_words(self):
        result = _split_words("well-known fact")
        self.assertGreaterEqual(len(result), 2)


# ---------------------------------------------------------------------------
# Helper: _split_sentences
# ---------------------------------------------------------------------------

class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_basic(self):
        result = _split_sentences("Hello world. How are you.")
        self.assertEqual(len(result), 2)

    def test_empty(self):
        self.assertEqual(_split_sentences(""), [])

    def test_single_sentence(self):
        result = _split_sentences("just one thought")
        self.assertEqual(len(result), 1)

    def test_multiple_punctuation(self):
        result = _split_sentences("Wow! Really? Yes.")
        self.assertEqual(len(result), 3)


# ---------------------------------------------------------------------------
# Helper: _count_complex_words
# ---------------------------------------------------------------------------

class TestCountComplexWords(unittest.TestCase):
    """Test _count_complex_words — words with 3+ syllables."""

    def test_no_complex(self):
        self.assertEqual(_count_complex_words(["the", "cat", "sat"]), 0)

    def test_all_complex(self):
        self.assertEqual(
            _count_complex_words(["beautiful", "implementation", "understanding"]),
            3
        )

    def test_mixed(self):
        result = _count_complex_words(
            ["the", "implementation", "of", "this", "beautiful", "idea"]
        )
        self.assertEqual(result, 2)

    def test_empty(self):
        self.assertEqual(_count_complex_words([]), 0)


# ---------------------------------------------------------------------------
# Helper: _count_hedge_words
# ---------------------------------------------------------------------------

class TestCountHedgeWords(unittest.TestCase):
    """Test _count_hedge_words."""

    def test_no_hedges(self):
        self.assertEqual(
            _count_hedge_words(["the", "cat", "sat", "on", "the", "mat"]),
            0
        )

    def test_some_hedges(self):
        result = _count_hedge_words(
            ["perhaps", "the", "result", "might", "be", "useful"]
        )
        self.assertEqual(result, 2)

    def test_all_hedges(self):
        result = _count_hedge_words(["perhaps", "maybe", "possibly"])
        self.assertEqual(result, 3)

    def test_empty(self):
        self.assertEqual(_count_hedge_words([]), 0)


# ---------------------------------------------------------------------------
# Helper: _count_nominalizations
# ---------------------------------------------------------------------------

class TestCountNominalizations(unittest.TestCase):
    """Test _count_nominalizations — abstract nouns."""

    def test_none(self):
        self.assertEqual(
            _count_nominalizations(["the", "cat", "ran", "fast"]),
            0
        )

    def test_some(self):
        result = _count_nominalizations(
            ["implementation", "of", "the", "development", "was", "good"]
        )
        self.assertEqual(result, 2)

    def test_various_suffixes(self):
        result = _count_nominalizations(
            ["happiness", "movement", "existence", "clarity"]
        )
        # happiness (-ness), movement (-ment), existence (-ence), clarity (-ity)
        self.assertEqual(result, 4)

    def test_empty(self):
        self.assertEqual(_count_nominalizations([]), 0)

    def test_short_words_not_counted(self):
        # "men" ends in 'n' but shouldn't match -ment
        # "action" is 6 chars so should count
        result = _count_nominalizations(["it", "is", "action"])
        self.assertEqual(result, 1)


# ---------------------------------------------------------------------------
# compute_sentence_length_score
# ---------------------------------------------------------------------------

class TestSentenceLengthScore(unittest.TestCase):
    """Test sentence length appropriateness scoring."""

    def test_ideal_lengths(self):
        # Sentences of 12-20 words should score high
        sentences = [" ".join(["word"] * 15) for _ in range(5)]
        score = compute_sentence_length_score(sentences)
        self.assertGreaterEqual(score, 0.8)

    def test_too_long(self):
        # Very long sentences should score low
        sentences = [" ".join(["word"] * 50) for _ in range(5)]
        score = compute_sentence_length_score(sentences)
        self.assertLess(score, 0.5)

    def test_too_short(self):
        # All one-word sentences should score low
        sentences = ["word"] * 10
        score = compute_sentence_length_score(sentences)
        self.assertLess(score, 0.5)

    def test_mixed_good(self):
        # Mix of short and medium sentences — typical good prose
        sentences = [
            " ".join(["word"] * 8),
            " ".join(["word"] * 18),
            " ".join(["word"] * 5),
            " ".join(["word"] * 15),
        ]
        score = compute_sentence_length_score(sentences)
        self.assertGreater(score, 0.3)

    def test_empty(self):
        self.assertEqual(compute_sentence_length_score([]), 0.0)


# ---------------------------------------------------------------------------
# compute_complex_word_ratio
# ---------------------------------------------------------------------------

class TestComplexWordRatio(unittest.TestCase):
    """Test complex word ratio computation."""

    def test_no_complex(self):
        words = ["the", "cat", "sat", "on", "mat"]
        ratio = compute_complex_word_ratio(words)
        self.assertEqual(ratio, 0.0)

    def test_all_complex(self):
        words = ["beautiful", "implementation", "understanding"]
        ratio = compute_complex_word_ratio(words)
        self.assertEqual(ratio, 1.0)

    def test_half_complex(self):
        words = ["the", "implementation", "is", "beautiful"]
        ratio = compute_complex_word_ratio(words)
        self.assertAlmostEqual(ratio, 0.5, places=2)

    def test_empty(self):
        self.assertEqual(compute_complex_word_ratio([]), 0.0)


# ---------------------------------------------------------------------------
# compute_hedge_ratio
# ---------------------------------------------------------------------------

class TestHedgeRatio(unittest.TestCase):
    """Test hedge word ratio computation."""

    def test_no_hedges(self):
        words = ["the", "result", "is", "clear"]
        self.assertEqual(compute_hedge_ratio(words), 0.0)

    def test_some_hedges(self):
        words = ["perhaps", "the", "result", "might", "be", "useful"]
        ratio = compute_hedge_ratio(words)
        self.assertGreater(ratio, 0.0)
        self.assertLessEqual(ratio, 1.0)

    def test_empty(self):
        self.assertEqual(compute_hedge_ratio([]), 0.0)


# ---------------------------------------------------------------------------
# compute_nominalization_ratio
# ---------------------------------------------------------------------------

class TestNominalizationRatio(unittest.TestCase):
    """Test nominalization ratio computation."""

    def test_none(self):
        words = ["the", "cat", "ran", "fast"]
        self.assertEqual(compute_nominalization_ratio(words), 0.0)

    def test_some(self):
        words = ["the", "implementation", "of", "development", "was", "fast"]
        ratio = compute_nominalization_ratio(words)
        self.assertGreater(ratio, 0.0)
        self.assertLessEqual(ratio, 1.0)

    def test_empty(self):
        self.assertEqual(compute_nominalization_ratio([]), 0.0)


# ---------------------------------------------------------------------------
# compute_readability_index
# ---------------------------------------------------------------------------

class TestReadabilityIndex(unittest.TestCase):
    """Test composite readability index computation."""

    def test_perfect_readability(self):
        # High sentence score, low complex/hedge/nominalization
        index = compute_readability_index(
            sentence_length_score=1.0,
            complex_word_ratio=0.0,
            hedge_ratio=0.0,
            nominalization_ratio=0.0,
        )
        self.assertGreaterEqual(index, 0.8)

    def test_poor_readability(self):
        # Low sentence score, high complex/hedge/nominalization
        index = compute_readability_index(
            sentence_length_score=0.2,
            complex_word_ratio=0.8,
            hedge_ratio=0.5,
            nominalization_ratio=0.6,
        )
        self.assertLess(index, 0.4)

    def test_moderate_readability(self):
        index = compute_readability_index(
            sentence_length_score=0.7,
            complex_word_ratio=0.15,
            hedge_ratio=0.05,
            nominalization_ratio=0.1,
        )
        self.assertGreater(index, 0.3)
        self.assertLess(index, 0.9)

    def test_returns_float(self):
        result = compute_readability_index(0.5, 0.2, 0.1, 0.1)
        self.assertIsInstance(result, float)

    def test_bounded_zero_one(self):
        for _ in range(20):
            import random
            index = compute_readability_index(
                random.random(), random.random(),
                random.random(), random.random(),
            )
            self.assertGreaterEqual(index, 0.0)
            self.assertLessEqual(index, 1.0)


# ---------------------------------------------------------------------------
# _classify_readability
# ---------------------------------------------------------------------------

class TestClassifyReadability(unittest.TestCase):
    """Test readability classification."""

    def test_clear(self):
        self.assertEqual(_classify_readability(0.85), "clear")
        self.assertEqual(_classify_readability(0.80), "clear")

    def test_transparent(self):
        self.assertEqual(_classify_readability(0.79), "transparent")
        self.assertEqual(_classify_readability(0.65), "transparent")

    def test_serviceable(self):
        self.assertEqual(_classify_readability(0.64), "serviceable")
        self.assertEqual(_classify_readability(0.50), "serviceable")

    def test_dense(self):
        self.assertEqual(_classify_readability(0.49), "dense")
        self.assertEqual(_classify_readability(0.35), "dense")

    def test_impenetrable(self):
        self.assertEqual(_classify_readability(0.24), "impenetrable")
        self.assertEqual(_classify_readability(0.0), "impenetrable")

    def test_boundary_values(self):
        self.assertEqual(_classify_readability(0.80), "clear")
        self.assertEqual(_classify_readability(0.65), "transparent")
        self.assertEqual(_classify_readability(0.50), "serviceable")
        self.assertEqual(_classify_readability(0.35), "dense")


# ---------------------------------------------------------------------------
# compute_readability_metrics
# ---------------------------------------------------------------------------

class TestComputeReadabilityMetrics(unittest.TestCase):
    """Test full metrics computation from text samples."""

    def test_basic_text(self):
        texts = [
            "The cat sat on the mat. It was a good day.",
            "The dog ran in the park. Birds flew overhead.",
        ]
        metrics = compute_readability_metrics(texts)
        self.assertIn("readability_index", metrics)
        self.assertIn("readability_class", metrics)
        self.assertIn("sentence_length_score", metrics)
        self.assertIn("complex_word_ratio", metrics)
        self.assertIn("hedge_ratio", metrics)
        self.assertIn("nominalization_ratio", metrics)
        self.assertIn("text_count", metrics)
        self.assertIn("total_sentences", metrics)
        self.assertIn("total_words", metrics)

    def test_simple_text_high_readability(self):
        texts = [
            "The cat sat. The dog ran. The bird sang.",
            "It was a good day. The sun was warm.",
        ]
        metrics = compute_readability_metrics(texts)
        self.assertGreater(metrics["readability_index"], 0.4)

    def test_complex_text_lower_readability(self):
        texts = [
            "The implementation of the comprehensive understanding "
            "of the philosophical conceptualization regarding "
            "epistemological foundations necessitates considerable "
            "deliberation and contemplation.",
        ]
        metrics = compute_readability_metrics(texts)
        # Complex words and nominalizations should lower the score
        self.assertGreater(metrics["complex_word_ratio"], 0.0)
        self.assertGreater(metrics["nominalization_ratio"], 0.0)

    def test_empty_input(self):
        metrics = compute_readability_metrics([])
        self.assertEqual(metrics["readability_index"], 0.0)
        self.assertEqual(metrics["text_count"], 0)

    def test_empty_strings(self):
        metrics = compute_readability_metrics(["", "  ", ""])
        self.assertEqual(metrics["readability_index"], 0.0)

    def test_hedge_text(self):
        texts = [
            "Perhaps the result might possibly be somewhat useful, "
            "although it is rather uncertain whether the findings "
            "may arguably be considered significant.",
        ]
        metrics = compute_readability_metrics(texts)
        self.assertGreater(metrics["hedge_ratio"], 0.0)


# ---------------------------------------------------------------------------
# analyze_stroke_readability
# ---------------------------------------------------------------------------

class TestAnalyzeStrokeReadability(unittest.TestCase):
    """Test per-stroke readability analysis."""

    def test_with_text_field(self):
        stroke = {"text": "The quick brown fox jumped over the lazy dog."}
        result = analyze_stroke_readability(stroke)
        self.assertIn("readability_index", result)
        self.assertIn("readability_class", result)

    def test_with_content_field(self):
        stroke = {"content": "Hello world. This is a test."}
        result = analyze_stroke_readability(stroke)
        self.assertIn("readability_index", result)

    def test_with_body_field(self):
        stroke = {"body": "Simple text here."}
        result = analyze_stroke_readability(stroke)
        self.assertIn("readability_index", result)

    def test_empty_stroke(self):
        stroke = {"text": ""}
        result = analyze_stroke_readability(stroke)
        self.assertEqual(result["readability_index"], 0.0)

    def test_no_text_field(self):
        stroke = {"category": "devlog"}
        result = analyze_stroke_readability(stroke)
        self.assertEqual(result["readability_index"], 0.0)


# ---------------------------------------------------------------------------
# _get_stroke_text
# ---------------------------------------------------------------------------

class TestGetStrokeText(unittest.TestCase):
    """Test _get_stroke_text extraction."""

    def test_text_field(self):
        self.assertEqual(
            _get_stroke_text({"text": "hello"}),
            "hello"
        )

    def test_content_field(self):
        self.assertEqual(
            _get_stroke_text({"content": "hello"}),
            "hello"
        )

    def test_body_field(self):
        self.assertEqual(
            _get_stroke_text({"body": "hello"}),
            "hello"
        )

    def test_empty_dict(self):
        self.assertEqual(_get_stroke_text({}), "")

    def test_priority_text_over_content(self):
        result = _get_stroke_text({"text": "first", "content": "second"})
        self.assertEqual(result, "first")


# ---------------------------------------------------------------------------
# format_readability_report
# ---------------------------------------------------------------------------

class TestFormatReadabilityReport(unittest.TestCase):
    """Test report formatting."""

    def test_basic_format(self):
        metrics = {
            "readability_index": 0.72,
            "readability_class": "transparent",
            "sentence_length_score": 0.80,
            "complex_word_ratio": 0.12,
            "hedge_ratio": 0.03,
            "nominalization_ratio": 0.08,
            "text_count": 10,
            "total_sentences": 45,
            "total_words": 600,
        }
        report = format_readability_report(metrics)
        self.assertIn("Readability Report", report)
        self.assertIn("0.72", report)
        self.assertIn("transparent", report)

    def test_empty_metrics(self):
        metrics = {
            "readability_index": 0.0,
            "readability_class": "impenetrable",
            "sentence_length_score": 0.0,
            "complex_word_ratio": 0.0,
            "hedge_ratio": 0.0,
            "nominalization_ratio": 0.0,
            "text_count": 0,
            "total_sentences": 0,
            "total_words": 0,
        }
        report = format_readability_report(metrics)
        self.assertIn("impenetrable", report)


# ---------------------------------------------------------------------------
# Integration: end-to-end analysis
# ---------------------------------------------------------------------------

class TestReadabilityIntegration(unittest.TestCase):
    """End-to-end integration tests."""

    def test_clear_prose(self):
        texts = [
            "The sun set behind the hills. A cool wind blew across "
            "the field. Birds flew south for the night.",
            "She closed the book and set it on the table. The room "
            "was quiet. Only the clock ticked.",
        ]
        metrics = compute_readability_metrics(texts)
        self.assertGreater(metrics["readability_index"], 0.5)
        self.assertIn(
            metrics["readability_class"],
            ["clear", "transparent", "serviceable"]
        )

    def test_academic_prose(self):
        texts = [
            "The conceptualization of epistemological foundations "
            "necessitates comprehensive understanding of the "
            "philosophical implementation regarding theoretical "
            "developments in the interpretation of methodological "
            "considerations.",
        ]
        metrics = compute_readability_metrics(texts)
        # Academic prose should have more complex words and nominalizations
        self.assertGreater(metrics["complex_word_ratio"], 0.1)
        self.assertGreater(metrics["nominalization_ratio"], 0.0)

    def test_technical_prose(self):
        texts = [
            "The function takes a list of integers and returns the "
            "sum of all even values. It iterates through each element "
            "and checks if the remainder is zero.",
            "We use a hash map to track word frequencies. Each key "
            "is a word and each value is a count.",
        ]
        metrics = compute_readability_metrics(texts)
        # Technical prose should be reasonably readable
        self.assertGreater(metrics["readability_index"], 0.3)


if __name__ == "__main__":
    unittest.main()
