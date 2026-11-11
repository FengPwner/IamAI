#!/usr/bin/env python3
"""Tests for writer_prose_rhythm — 83 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_prose_rhythm import (  # noqa: E402
    _classify_rhythm,
    _classify_tempo,
    _get_stroke_text,
    _sentence_lengths,
    _split_sentences,
    _word_count,
    analyze_stroke_rhythm,
    classify_paragraph_momentum,
    classify_rhythm_trend,
    compute_alternation_index,
    compute_quartile_rhythm,
    compute_rhythm_index,
    compute_rhythm_metrics,
    compute_sentence_length_cv,
    format_rhythm_report,
)


# ---------------------------------------------------------------------------
# Helper: _split_sentences
# ---------------------------------------------------------------------------

class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_basic_two_sentences(self):
        result = _split_sentences("Hello world. How are you.")
        self.assertEqual(len(result), 2)

    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_whitespace_only(self):
        self.assertEqual(_split_sentences("   "), [])

    def test_single_sentence_no_period(self):
        result = _split_sentences("just one thought")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "just one thought")

    def test_exclamation_mark(self):
        result = _split_sentences("Wow! That is amazing!")
        self.assertEqual(len(result), 2)

    def test_question_mark(self):
        result = _split_sentences("What happened? Nobody knows.")
        self.assertEqual(len(result), 2)

    def test_multiple_spaces_after_period(self):
        result = _split_sentences("First.  Second.")
        self.assertEqual(len(result), 2)

    def test_newline_split(self):
        result = _split_sentences("Line one.\nLine two.")
        self.assertGreaterEqual(len(result), 2)

    def test_quoted_sentence_start(self):
        result = _split_sentences('He said hello. "She replied."')
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# Helper: _word_count
# ---------------------------------------------------------------------------

class TestWordCount(unittest.TestCase):
    """Test _word_count helper."""

    def test_simple(self):
        self.assertEqual(_word_count("hello world"), 2)

    def test_empty(self):
        self.assertEqual(_word_count(""), 0)

    def test_with_punctuation(self):
        self.assertEqual(_word_count("foo, bar! baz."), 3)

    def test_contraction(self):
        # "don't" should count as one word
        self.assertEqual(_word_count("I don't know"), 3)

    def test_numbers(self):
        self.assertEqual(_word_count("stroke 42 done"), 3)


# ---------------------------------------------------------------------------
# Helper: _sentence_lengths
# ---------------------------------------------------------------------------

class TestSentenceLengths(unittest.TestCase):
    """Test _sentence_lengths helper."""

    def test_two_sentences(self):
        lengths = _sentence_lengths("Short one. A much longer sentence here.")
        self.assertEqual(len(lengths), 2)
        self.assertLess(lengths[0], lengths[1])

    def test_empty(self):
        self.assertEqual(_sentence_lengths(""), [])

    def test_single(self):
        lengths = _sentence_lengths("Just one sentence here.")
        self.assertEqual(lengths, [4])


# ---------------------------------------------------------------------------
# Helper: _get_stroke_text
# ---------------------------------------------------------------------------

class TestGetStrokeText(unittest.TestCase):
    """Test _get_stroke_text helper."""

    def test_dict_with_text(self):
        self.assertEqual(_get_stroke_text({"text": "hello"}), "hello")

    def test_dict_with_content(self):
        self.assertEqual(_get_stroke_text({"content": "world"}), "world")

    def test_dict_empty(self):
        self.assertEqual(_get_stroke_text({}), "")

    def test_object_with_text(self):
        class S:
            text = "from object"
            content = ""
        self.assertEqual(_get_stroke_text(S()), "from object")

    def test_none_text(self):
        self.assertEqual(_get_stroke_text({"text": None}), "")


# ---------------------------------------------------------------------------
# Core: compute_sentence_length_cv
# ---------------------------------------------------------------------------

class TestSentenceLengthCV(unittest.TestCase):
    """Test sentence length coefficient of variation."""

    def test_identical_lengths(self):
        self.assertEqual(compute_sentence_length_cv([10, 10, 10, 10]), 0.0)

    def test_single_sentence(self):
        self.assertEqual(compute_sentence_length_cv([10]), 0.0)

    def test_empty(self):
        self.assertEqual(compute_sentence_length_cv([]), 0.0)

    def test_high_variation(self):
        cv = compute_sentence_length_cv([2, 20, 3, 25])
        self.assertGreater(cv, 0.7)

    def test_moderate_variation(self):
        cv = compute_sentence_length_cv([10, 12, 8, 14, 9])
        self.assertGreater(cv, 0.1)
        self.assertLess(cv, 0.5)

    def test_returns_float(self):
        result = compute_sentence_length_cv([5, 10, 15])
        self.assertIsInstance(result, float)


# ---------------------------------------------------------------------------
# Core: compute_alternation_index
# ---------------------------------------------------------------------------

class TestAlternationIndex(unittest.TestCase):
    """Test alternation index computation."""

    def test_perfect_alternation(self):
        # Alternating above and below median (which is 10)
        lengths = [5, 15, 5, 15, 5, 15]
        alt = compute_alternation_index(lengths)
        self.assertGreater(alt, 0.8)

    def test_no_alternation(self):
        # All above median then all below — only one crossing
        lengths = [20, 20, 20, 5, 5, 5]
        alt = compute_alternation_index(lengths)
        self.assertLess(alt, 0.3)

    def test_single_sentence(self):
        self.assertEqual(compute_alternation_index([10]), 0.0)

    def test_empty(self):
        self.assertEqual(compute_alternation_index([]), 0.0)

    def test_returns_float(self):
        result = compute_alternation_index([5, 10, 15, 8])
        self.assertIsInstance(result, float)

    def test_bounded_zero_one(self):
        alt = compute_alternation_index([3, 7, 12, 5, 20, 8])
        self.assertGreaterEqual(alt, 0.0)
        self.assertLessEqual(alt, 1.0)


# ---------------------------------------------------------------------------
# Core: classify_paragraph_momentum
# ---------------------------------------------------------------------------

class TestClassifyParagraphMomentum(unittest.TestCase):
    """Test paragraph momentum classification."""

    def test_accelerating(self):
        # Sentences getting longer
        result = classify_paragraph_momentum([3, 6, 10, 15, 22])
        self.assertEqual(result, "accelerating")

    def test_decelerating(self):
        # Sentences getting shorter
        result = classify_paragraph_momentum([22, 15, 10, 6, 3])
        self.assertEqual(result, "decelerating")

    def test_steady(self):
        # Similar lengths
        result = classify_paragraph_momentum([10, 11, 10, 9, 10])
        self.assertEqual(result, "steady")

    def test_irregular(self):
        # High volatility with a slight upward trend — low R²
        result = classify_paragraph_momentum([3, 15, 5, 20, 8, 18, 6, 25])
        self.assertEqual(result, "irregular")

    def test_short_input(self):
        self.assertEqual(classify_paragraph_momentum([10, 5]), "steady")

    def test_single(self):
        self.assertEqual(classify_paragraph_momentum([10]), "steady")

    def test_empty(self):
        self.assertEqual(classify_paragraph_momentum([]), "steady")


# ---------------------------------------------------------------------------
# Core: compute_rhythm_index
# ---------------------------------------------------------------------------

class TestComputeRhythmIndex(unittest.TestCase):
    """Test composite rhythm index."""

    def test_high_cv_good_alternation(self):
        idx = compute_rhythm_index(0.6, 0.5)
        self.assertGreater(idx, 0.4)

    def test_zero_cv(self):
        idx = compute_rhythm_index(0.0, 0.0)
        self.assertLess(idx, 0.3)

    def test_with_momentum(self):
        mom = {"accelerating": 0.4, "decelerating": 0.3, "steady": 0.3}
        idx = compute_rhythm_index(0.6, 0.5, mom)
        self.assertGreater(idx, 0.4)

    def test_all_steady_momentum(self):
        mom = {"steady": 1.0}
        idx_low = compute_rhythm_index(0.6, 0.5, mom)
        mom2 = {"accelerating": 0.5, "decelerating": 0.5}
        idx_high = compute_rhythm_index(0.6, 0.5, mom2)
        self.assertGreater(idx_high, idx_low)

    def test_bounded(self):
        idx = compute_rhythm_index(0.6, 0.5)
        self.assertGreaterEqual(idx, 0.0)
        self.assertLessEqual(idx, 1.0)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

class TestClassifyRhythm(unittest.TestCase):
    """Test _classify_rhythm."""

    def test_varied(self):
        self.assertEqual(_classify_rhythm(0.70), "varied")

    def test_measured(self):
        self.assertEqual(_classify_rhythm(0.50), "measured")

    def test_monotone(self):
        self.assertEqual(_classify_rhythm(0.30), "monotone")

    def test_erratic(self):
        self.assertEqual(_classify_rhythm(0.10), "erratic")

    def test_boundary_varied(self):
        self.assertEqual(_classify_rhythm(0.65), "varied")

    def test_boundary_measured(self):
        self.assertEqual(_classify_rhythm(0.45), "measured")

    def test_boundary_monotone(self):
        self.assertEqual(_classify_rhythm(0.25), "monotone")


class TestClassifyTempo(unittest.TestCase):
    """Test _classify_tempo."""

    def test_staccato(self):
        self.assertEqual(_classify_tempo(5), "staccato")

    def test_conversational(self):
        self.assertEqual(_classify_tempo(12), "conversational")

    def test_measured(self):
        self.assertEqual(_classify_tempo(22), "measured")

    def test_labyrinthine(self):
        self.assertEqual(_classify_tempo(35), "labyrinthine")

    def test_boundary_staccato(self):
        self.assertEqual(_classify_tempo(7.9), "staccato")

    def test_boundary_conversational(self):
        self.assertEqual(_classify_tempo(8), "conversational")


# ---------------------------------------------------------------------------
# Session-level: compute_quartile_rhythm
# ---------------------------------------------------------------------------

class TestComputeQuartileRhythm(unittest.TestCase):
    """Test quartile rhythm computation."""

    def test_four_strokes(self):
        lengths = [[10, 5], [8, 12], [6, 15], [20, 3]]
        result = compute_quartile_rhythm(lengths)
        self.assertIn("q1", result)
        self.assertIn("q2", result)
        self.assertIn("q3", result)
        self.assertIn("q4", result)

    def test_empty(self):
        result = compute_quartile_rhythm([])
        self.assertEqual(result["q1"], 0.0)

    def test_single_stroke(self):
        result = compute_quartile_rhythm([[5, 10, 15]])
        self.assertIsInstance(result["q1"], float)


# ---------------------------------------------------------------------------
# Session-level: classify_rhythm_trend
# ---------------------------------------------------------------------------

class TestClassifyRhythmTrend(unittest.TestCase):
    """Test rhythm trend classification."""

    def test_improving(self):
        q = {"q1": 0.2, "q2": 0.3, "q3": 0.4, "q4": 0.5}
        self.assertEqual(classify_rhythm_trend(q), "improving")

    def test_degrading(self):
        q = {"q1": 0.6, "q2": 0.5, "q3": 0.4, "q4": 0.3}
        self.assertEqual(classify_rhythm_trend(q), "degrading")

    def test_stable(self):
        q = {"q1": 0.4, "q2": 0.4, "q3": 0.4, "q4": 0.4}
        self.assertEqual(classify_rhythm_trend(q), "stable")

    def test_arc(self):
        q = {"q1": 0.3, "q2": 0.5, "q3": 0.6, "q4": 0.4}
        self.assertEqual(classify_rhythm_trend(q), "arc")

    def test_inverted_arc(self):
        q = {"q1": 0.6, "q2": 0.4, "q3": 0.3, "q4": 0.5}
        self.assertEqual(classify_rhythm_trend(q), "inverted_arc")


# ---------------------------------------------------------------------------
# Per-stroke: analyze_stroke_rhythm
# ---------------------------------------------------------------------------

class TestAnalyzeStrokeRhythm(unittest.TestCase):
    """Test per-stroke rhythm analysis."""

    def test_normal_stroke(self):
        stroke = {"text": "Short sentence. A somewhat longer sentence follows this one."}
        result = analyze_stroke_rhythm(stroke)
        self.assertEqual(result["sentence_count"], 2)
        self.assertIn("cv", result)
        self.assertIn("alternation", result)
        self.assertIn("momentum", result)

    def test_empty_stroke(self):
        result = analyze_stroke_rhythm({"text": ""})
        self.assertEqual(result["sentence_count"], 0)
        self.assertEqual(result["cv"], 0.0)

    def test_object_stroke(self):
        class S:
            text = "First. Second sentence here."
            content = ""
        result = analyze_stroke_rhythm(S())
        self.assertGreaterEqual(result["sentence_count"], 1)


# ---------------------------------------------------------------------------
# Session-level: compute_rhythm_metrics
# ---------------------------------------------------------------------------

class TestComputeRhythmMetrics(unittest.TestCase):
    """Test full session rhythm metrics."""

    def test_basic_session(self):
        strokes = [
            {"text": "Short. A longer sentence here now."},
            {"text": "Brief one. Then something considerably more verbose and elaborate."},
            {"text": "Quick. Followed by a much more extended thought on the matter."},
            {"text": "Done. The final stroke wraps up with considerably more words."},
        ]
        result = compute_rhythm_metrics(strokes)
        self.assertIn("rhythm_index", result)
        self.assertIn("rhythm_class", result)
        self.assertIn("tempo", result)
        self.assertIn("tempo_class", result)
        self.assertGreater(result["stroke_count"], 0)
        self.assertGreater(result["total_sentences"], 0)

    def test_empty_strokes(self):
        result = compute_rhythm_metrics([])
        self.assertEqual(result["rhythm_index"], 0.0)
        self.assertEqual(result["rhythm_class"], "erratic")
        self.assertEqual(result["stroke_count"], 0)

    def test_all_empty_text(self):
        strokes = [{"text": ""}, {"text": ""}]
        result = compute_rhythm_metrics(strokes)
        self.assertEqual(result["total_sentences"], 0)

    def test_rhythm_class_valid(self):
        strokes = [
            {"text": "The quick brown fox jumped. Short. A longer one."},
        ]
        result = compute_rhythm_metrics(strokes)
        self.assertIn(result["rhythm_class"], ["varied", "measured", "monotone", "erratic"])

    def test_tempo_class_valid(self):
        strokes = [{"text": "One. Two. Three. Four. Five. Six. Seven. Eight."}]
        result = compute_rhythm_metrics(strokes)
        self.assertIn(result["tempo_class"], ["staccato", "conversational", "measured", "labyrinthine"])

    def test_quartile_keys(self):
        strokes = [{"text": f"Sentence {i}. Another one here."} for i in range(8)]
        result = compute_rhythm_metrics(strokes)
        self.assertEqual(set(result["quartile_rhythm"].keys()), {"q1", "q2", "q3", "q4"})

    def test_momentum_distribution_present(self):
        strokes = [
            {"text": "Short. Medium length sentence. A much longer sentence that goes on."},
        ]
        result = compute_rhythm_metrics(strokes)
        self.assertIsInstance(result["momentum_distribution"], dict)


# ---------------------------------------------------------------------------
# Reporting: format_rhythm_report
# ---------------------------------------------------------------------------

class TestFormatRhythmReport(unittest.TestCase):
    """Test report formatting."""

    def test_basic_report(self):
        metrics = compute_rhythm_metrics([
            {"text": "Hello world. How are you doing today."},
            {"text": "Fine thanks. And yourself my friend."},
        ])
        report = format_rhythm_report(metrics)
        self.assertIn("Prose Rhythm Report", report)
        self.assertIn("rhythm_index:", report)
        self.assertIn("tempo:", report)

    def test_empty_report(self):
        metrics = compute_rhythm_metrics([])
        report = format_rhythm_report(metrics)
        self.assertIn("rhythm_index:", report)


# ---------------------------------------------------------------------------
# Integration: varied vs monotone text
# ---------------------------------------------------------------------------

class TestRhythmIntegration(unittest.TestCase):
    """Integration tests comparing varied vs monotone writing."""

    def test_varied_text_has_higher_cv(self):
        varied = [
            {"text": "No. Perhaps. The implications are far more complex than one might initially assume."},
            {"text": "Why? Consider the evidence. A thorough examination reveals unexpected patterns."},
        ]
        monotone = [
            {"text": "The cat sat on mat. The dog ran in park. The bird flew to tree."},
            {"text": "The fish swam in pond. The frog sat on log. The bee flew to hive."},
        ]
        v_metrics = compute_rhythm_metrics(varied)
        m_metrics = compute_rhythm_metrics(monotone)
        self.assertGreater(v_metrics["sentence_length_cv"], m_metrics["sentence_length_cv"])

    def test_report_is_string(self):
        metrics = compute_rhythm_metrics([{"text": "Test sentence."}])
        report = format_rhythm_report(metrics)
        self.assertIsInstance(report, str)


if __name__ == "__main__":
    unittest.main()
