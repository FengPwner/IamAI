#!/usr/bin/env python3
"""Tests for writer_clarity — measuring structural parseability."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_clarity import (  # noqa: E402
    ANAPHORIC_PRONOUNS,
    CLARITY_CLASSES,
    GARDEN_PATH_PATTERNS,
    PP_ATTACHMENT_PATTERNS,
    PREPOSITIONS,
    RELATIVE_PRONOUNS,
    SIGNAL_WEIGHTS,
    SUBORDINATORS,
    _classify_clarity,
    _empty_metrics,
    _empty_stroke_metrics,
    _find_pronoun_distances,
    _get_stroke_text,
    _measure_clause_depth,
    _split_sentences,
    _split_words,
    _trend_interpretation,
    analyze_clarity,
    analyze_stroke_clarity,
    classify_trend,
    compute_attachment_ambiguity_rate,
    compute_clarity_metrics,
    compute_clarity_trend,
    compute_garden_path_rate,
    compute_max_nested_depth,
    compute_nested_depth,
    compute_pronoun_distance,
    count_attachment_ambiguities,
    count_garden_paths,
    format_clarity_report,
)


# ---------------------------------------------------------------------------
# Helper: _split_words
# ---------------------------------------------------------------------------

class TestSplitWords(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_split_words("Hello World"), ["hello", "world"])

    def test_punctuation(self):
        self.assertEqual(
            _split_words("The cat, which sat."), ["the", "cat", "which", "sat"]
        )

    def test_empty(self):
        self.assertEqual(_split_words(""), [])

    def test_numbers_stripped(self):
        # Numbers are not alpha, so they're stripped
        result = _split_words("test 42 words")
        self.assertIn("test", result)
        self.assertIn("words", result)


# ---------------------------------------------------------------------------
# Helper: _split_sentences
# ---------------------------------------------------------------------------

class TestSplitSentences(unittest.TestCase):
    def test_basic(self):
        result = _split_sentences("Hello world. Goodbye world.")
        self.assertEqual(len(result), 2)

    def test_exclamation(self):
        result = _split_sentences("Wow! Amazing.")
        self.assertEqual(len(result), 2)

    def test_empty(self):
        self.assertEqual(_split_sentences(""), [])

    def test_single(self):
        result = _split_sentences("Just one sentence here.")
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# Helper: _get_stroke_text
# ---------------------------------------------------------------------------

class TestGetStrokeText(unittest.TestCase):
    def test_string(self):
        self.assertEqual(_get_stroke_text("hello"), "hello")

    def test_dict_text(self):
        self.assertEqual(_get_stroke_text({"text": "hi"}), "hi")

    def test_dict_content(self):
        self.assertEqual(_get_stroke_text({"content": "hi"}), "hi")

    def test_none(self):
        self.assertEqual(_get_stroke_text(None), "")

    def test_object(self):
        class Obj:
            def __str__(self):
                return "obj"
        self.assertEqual(_get_stroke_text(Obj()), "obj")


# ---------------------------------------------------------------------------
# Signal 1: Attachment ambiguity
# ---------------------------------------------------------------------------

class TestAttachmentAmbiguity(unittest.TestCase):
    def test_clear_text(self):
        text = "The cat sat on the mat."
        count = count_attachment_ambiguities(text)
        self.assertEqual(count, 0)

    def test_ambiguous_pp_chain(self):
        text = "The report of the committee on the budget was detailed."
        count = count_attachment_ambiguities(text)
        self.assertGreaterEqual(count, 1)

    def test_rate_clear(self):
        text = "The dog ran quickly. The cat slept soundly. Birds sang loudly."
        rate = compute_attachment_ambiguity_rate(text)
        self.assertGreater(rate, 0.5)

    def test_rate_empty(self):
        self.assertEqual(compute_attachment_ambiguity_rate(""), 1.0)

    def test_rate_short(self):
        self.assertEqual(compute_attachment_ambiguity_rate("Hi"), 1.0)

    def test_rate_bounded(self):
        text = "The report of the committee on the budget of the department on the policy was clear."
        rate = compute_attachment_ambiguity_rate(text)
        self.assertGreaterEqual(rate, 0.0)
        self.assertLessEqual(rate, 1.0)


# ---------------------------------------------------------------------------
# Signal 2: Garden path
# ---------------------------------------------------------------------------

class TestGardenPath(unittest.TestCase):
    def test_normal_sentences(self):
        text = "The cat sat on the mat. The dog ran in the park."
        count = count_garden_paths(text)
        self.assertEqual(count, 0)

    def test_garden_path_detected(self):
        text = "The old man the boats with great skill."
        count = count_garden_paths(text)
        self.assertGreaterEqual(count, 1)

    def test_rate_normal(self):
        text = "She walked to the store. He read a book. They ate lunch."
        rate = compute_garden_path_rate(text)
        self.assertGreater(rate, 0.8)

    def test_rate_empty(self):
        self.assertEqual(compute_garden_path_rate(""), 1.0)

    def test_rate_bounded(self):
        text = "The old man the boats. The cotton clothing is made of grows in Egypt."
        rate = compute_garden_path_rate(text)
        self.assertGreaterEqual(rate, 0.0)
        self.assertLessEqual(rate, 1.0)


# ---------------------------------------------------------------------------
# Signal 3: Pronoun distance
# ---------------------------------------------------------------------------

class TestPronounDistance(unittest.TestCase):
    def test_close_pronoun(self):
        text = "The cat sat. It purred."
        distances = _find_pronoun_distances(text)
        if distances:
            self.assertLessEqual(distances[0], 5)

    def test_no_pronouns(self):
        text = "Cats sleep all day."
        distances = _find_pronoun_distances(text)
        self.assertEqual(len(distances), 0)

    def test_distance_score_no_pronouns(self):
        text = "Cats sleep all day."
        score = compute_pronoun_distance(text)
        self.assertEqual(score, 1.0)

    def test_distance_score_close(self):
        text = "The manager reviewed the proposal. She approved it."
        score = compute_pronoun_distance(text)
        self.assertGreater(score, 0.3)

    def test_distance_score_distant(self):
        text = (
            "The application processed the request and the database "
            "server returned an error code because the connection pool "
            "was exhausted and it crashed."
        )
        score = compute_pronoun_distance(text)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_distance_bounded(self):
        text = "The report was long. It covered many topics. They were interesting."
        score = compute_pronoun_distance(text)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


# ---------------------------------------------------------------------------
# Signal 4: Nested clause depth
# ---------------------------------------------------------------------------

class TestNestedDepth(unittest.TestCase):
    def test_flat(self):
        depth = _measure_clause_depth("The cat sat on the mat.")
        self.assertEqual(depth, 1)

    def test_one_embed(self):
        depth = _measure_clause_depth(
            "The cat that the dog chased sat on the mat."
        )
        self.assertGreaterEqual(depth, 2)

    def test_two_embed(self):
        depth = _measure_clause_depth(
            "The cat that the dog that the rat bit chased sat."
        )
        self.assertGreaterEqual(depth, 3)

    def test_compute_nested_flat(self):
        text = "The cat sat. The dog ran. The bird flew."
        score = compute_nested_depth(text)
        self.assertGreater(score, 0.8)

    def test_compute_nested_deep(self):
        text = (
            "The manager who hired the developer who wrote the code "
            "that caused the crash that brought down the server left."
        )
        score = compute_nested_depth(text)
        self.assertLess(score, 0.6)

    def test_empty(self):
        self.assertEqual(compute_nested_depth(""), 1.0)

    def test_max_depth(self):
        text = "Simple. The cat that the dog chased sat. Also simple."
        max_d = compute_max_nested_depth(text)
        self.assertGreaterEqual(max_d, 2)

    def test_max_depth_empty(self):
        self.assertEqual(compute_max_nested_depth(""), 0)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassification(unittest.TestCase):
    def test_crystalline(self):
        self.assertEqual(_classify_clarity(0.9), "crystalline")

    def test_lucid(self):
        self.assertEqual(_classify_clarity(0.7), "lucid")

    def test_serviceable(self):
        self.assertEqual(_classify_clarity(0.5), "serviceable")

    def test_murky(self):
        self.assertEqual(_classify_clarity(0.3), "murky")

    def test_opaque(self):
        self.assertEqual(_classify_clarity(0.1), "opaque")

    def test_boundary_crystalline(self):
        self.assertEqual(_classify_clarity(0.8), "crystalline")

    def test_boundary_lucid(self):
        self.assertEqual(_classify_clarity(0.6), "lucid")

    def test_boundary_serviceable(self):
        self.assertEqual(_classify_clarity(0.4), "serviceable")

    def test_boundary_murky(self):
        self.assertEqual(_classify_clarity(0.2), "murky")

    def test_boundary_opaque(self):
        self.assertEqual(_classify_clarity(0.0), "opaque")


# ---------------------------------------------------------------------------
# Composite metrics
# ---------------------------------------------------------------------------

class TestCompositeMetrics(unittest.TestCase):
    def test_empty_text(self):
        m = compute_clarity_metrics("")
        self.assertEqual(m["clarity_index"], 1.0)
        self.assertEqual(m["clarity_class"], "crystalline")
        self.assertEqual(m["word_count"], 0)

    def test_clear_text(self):
        text = "The cat sat on the mat. The dog ran in the park. She smiled."
        m = compute_clarity_metrics(text)
        self.assertGreater(m["clarity_index"], 0.5)
        self.assertIn(m["clarity_class"], [
            "crystalline", "lucid", "serviceable"
        ])
        self.assertGreater(m["word_count"], 0)
        self.assertGreater(m["sentence_count"], 0)

    def test_weights_override(self):
        text = "The report of the committee on the budget was detailed."
        w = {"attachment": 1.0, "garden_path": 0.0,
             "pronoun_distance": 0.0, "nested_depth": 0.0}
        m = compute_clarity_metrics(text, weights=w)
        # With only attachment weight, the index equals attachment_rate
        self.assertAlmostEqual(m["clarity_index"], m["attachment_rate"], places=3)

    def test_metrics_keys(self):
        m = compute_clarity_metrics("Hello world.")
        expected_keys = {
            "attachment_rate", "garden_path_rate", "pronoun_distance",
            "nested_depth", "max_depth", "clarity_index", "clarity_class",
            "word_count", "sentence_count",
        }
        self.assertTrue(expected_keys.issubset(m.keys()))


# ---------------------------------------------------------------------------
# Stroke analysis
# ---------------------------------------------------------------------------

class TestStrokeAnalysis(unittest.TestCase):
    def test_empty_stroke(self):
        m = analyze_stroke_clarity("")
        self.assertEqual(m["clarity_index"], 1.0)

    def test_string_stroke(self):
        m = analyze_stroke_clarity("The cat sat on the mat.")
        self.assertIn("clarity_index", m)
        self.assertIn("clarity_class", m)

    def test_dict_stroke(self):
        m = analyze_stroke_clarity({"text": "Simple sentence here."})
        self.assertIn("clarity_index", m)

    def test_stroke_keys(self):
        m = analyze_stroke_clarity("Some text.")
        expected_keys = {
            "attachment_rate", "garden_path_rate", "pronoun_distance",
            "nested_depth", "clarity_index", "clarity_class",
        }
        self.assertTrue(expected_keys.issubset(m.keys()))


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

class TestTrend(unittest.TestCase):
    def test_empty(self):
        t = compute_clarity_trend([])
        self.assertEqual(t["trend"], "no_data")

    def test_single(self):
        t = compute_clarity_trend([{"clarity_index": 0.7}])
        self.assertEqual(t["trend"], "single_snapshot")

    def test_improving(self):
        snapshots = [
            {"clarity_index": 0.4},
            {"clarity_index": 0.6},
            {"clarity_index": 0.8},
        ]
        t = compute_clarity_trend(snapshots)
        self.assertEqual(t["trend"], "improving")
        self.assertGreater(t["delta"], 0)

    def test_declining(self):
        snapshots = [
            {"clarity_index": 0.8},
            {"clarity_index": 0.5},
            {"clarity_index": 0.3},
        ]
        t = compute_clarity_trend(snapshots)
        self.assertEqual(t["trend"], "declining")
        self.assertLess(t["delta"], 0)

    def test_stable(self):
        snapshots = [
            {"clarity_index": 0.65},
            {"clarity_index": 0.66},
            {"clarity_index": 0.65},
        ]
        t = compute_clarity_trend(snapshots)
        self.assertEqual(t["trend"], "stable")

    def test_two_snapshots(self):
        t = compute_clarity_trend([
            {"clarity_index": 0.5},
            {"clarity_index": 0.8},
        ])
        self.assertEqual(t["trend"], "improving")
        self.assertEqual(t["count"], 2)


# ---------------------------------------------------------------------------
# classify_trend
# ---------------------------------------------------------------------------

class TestClassifyTrend(unittest.TestCase):
    def test_stable(self):
        self.assertEqual(classify_trend(0.01), "stable")

    def test_improving(self):
        self.assertEqual(classify_trend(0.2), "improving")

    def test_declining(self):
        self.assertEqual(classify_trend(-0.2), "declining")

    def test_boundary_stable(self):
        self.assertEqual(classify_trend(0.04), "stable")
        self.assertEqual(classify_trend(-0.04), "stable")


# ---------------------------------------------------------------------------
# Trend interpretation
# ---------------------------------------------------------------------------

class TestTrendInterpretation(unittest.TestCase):
    def test_improving(self):
        interp = _trend_interpretation("improving", 0.15)
        self.assertIn("improved", interp)

    def test_declining(self):
        interp = _trend_interpretation("declining", -0.10)
        self.assertIn("declined", interp)

    def test_stable(self):
        interp = _trend_interpretation("stable", 0.0)
        self.assertIn("stable", interp)

    def test_unknown(self):
        self.assertEqual(_trend_interpretation("unknown", 0.0), "")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

class TestReport(unittest.TestCase):
    def test_format(self):
        m = compute_clarity_metrics(
            "The cat sat on the mat. The dog ran quickly."
        )
        report = format_clarity_report(m)
        self.assertIn("clarity:", report)
        self.assertIn("index:", report)
        self.assertIn("attachment", report)
        self.assertIn("garden path", report)
        self.assertIn("pronoun distance", report)
        self.assertIn("nested depth", report)

    def test_analyze_clarity_has_report(self):
        m = analyze_clarity("Simple text here.")
        self.assertIn("report", m)
        self.assertIn("clarity:", m["report"])


# ---------------------------------------------------------------------------
# Empty/default metrics
# ---------------------------------------------------------------------------

class TestEmptyMetrics(unittest.TestCase):
    def test_empty_metrics(self):
        m = _empty_metrics()
        self.assertEqual(m["clarity_index"], 1.0)
        self.assertEqual(m["clarity_class"], "crystalline")
        self.assertEqual(m["word_count"], 0)
        self.assertEqual(m["sentence_count"], 0)

    def test_empty_stroke_metrics(self):
        m = _empty_stroke_metrics()
        self.assertEqual(m["clarity_index"], 1.0)
        self.assertEqual(m["clarity_class"], "crystalline")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_weights_sum_to_one(self):
        total = sum(SIGNAL_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_prepositions_nonempty(self):
        self.assertGreater(len(PREPOSITIONS), 10)

    def test_pronouns_nonempty(self):
        self.assertGreater(len(ANAPHORIC_PRONOUNS), 5)

    def test_relative_pronouns_nonempty(self):
        self.assertGreater(len(RELATIVE_PRONOUNS), 3)

    def test_subordinators_nonempty(self):
        self.assertGreater(len(SUBORDINATORS), 10)

    def test_garden_path_patterns_nonempty(self):
        self.assertGreater(len(GARDEN_PATH_PATTERNS), 0)

    def test_pp_patterns_nonempty(self):
        self.assertGreater(len(PP_ATTACHMENT_PATTERNS), 0)

    def test_clarity_classes_ordered(self):
        thresholds = [t for t, _ in CLARITY_CLASSES]
        self.assertEqual(thresholds, sorted(thresholds, reverse=True))


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    def test_clear_prose_scores_high(self):
        text = (
            "The developer wrote clean code. She tested every function. "
            "The tests passed. The build succeeded. She deployed to production."
        )
        m = compute_clarity_metrics(text)
        self.assertGreater(m["clarity_index"], 0.6)
        self.assertIn(m["clarity_class"], ["crystalline", "lucid"])

    def test_complex_prose_scores_lower(self):
        text = (
            "The report of the committee on the budget of the department "
            "on the policy regarding the implementation of the new system "
            "that the manager who hired the developer who wrote the code "
            "that caused the crash recommended was finally approved."
        )
        m = compute_clarity_metrics(text)
        self.assertLess(m["clarity_index"], 0.7)

    def test_full_pipeline(self):
        text = (
            "The cat sat on the mat. The dog ran through the park. "
            "She smiled at the children who played in the garden."
        )
        m = analyze_clarity(text)
        self.assertIn("report", m)
        self.assertIn("clarity_index", m)
        self.assertGreater(m["word_count"], 0)
        self.assertGreater(m["sentence_count"], 0)

    def test_consistent_results(self):
        text = "The cat sat on the mat. It purred."
        m1 = compute_clarity_metrics(text)
        m2 = compute_clarity_metrics(text)
        self.assertEqual(m1["clarity_index"], m2["clarity_index"])


if __name__ == "__main__":
    unittest.main()
