#!/usr/bin/env python3
"""Tests for writer_irony_density — 90+ test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_irony_density import (  # noqa: E402
    VERBAL_IRONY_PATTERNS,
    LITOTES_PATTERNS,
    RHETORICAL_NEGATION_PATTERNS,
    UNDERSTATEMENT_PATTERNS,
    SOCRATIC_QUESTION_PATTERNS,
    WriterIronyDensity,
)


class TestWriterIronyDensityInit(unittest.TestCase):
    """Test WriterIronyDensity initialization."""

    def test_init_default(self):
        wid = WriterIronyDensity()
        self.assertIsNotNone(wid.verbal_irony)
        self.assertIsNotNone(wid.litotes)
        self.assertIsNotNone(wid.rhetorical_negation)
        self.assertIsNotNone(wid.understatement)
        self.assertIsNotNone(wid.socratic_questioning)

    def test_init_compiled_patterns(self):
        wid = WriterIronyDensity()
        self.assertEqual(len(wid.verbal_irony), len(VERBAL_IRONY_PATTERNS))
        self.assertEqual(len(wid.litotes), len(LITOTES_PATTERNS))
        self.assertEqual(len(wid.rhetorical_negation), len(RHETORICAL_NEGATION_PATTERNS))
        self.assertEqual(len(wid.understatement), len(UNDERSTATEMENT_PATTERNS))
        self.assertEqual(len(wid.socratic_questioning), len(SOCRATIC_QUESTION_PATTERNS))


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        wid = WriterIronyDensity()
        self.assertEqual(wid._split_sentences(""), [])

    def test_single_sentence(self):
        wid = WriterIronyDensity()
        result = wid._split_sentences("Oh great, another meeting.")
        self.assertEqual(len(result), 1)

    def test_multiple_sentences(self):
        wid = WriterIronyDensity()
        result = wid._split_sentences("Hello world. How are you. Fine thanks.")
        self.assertEqual(len(result), 3)

    def test_exclamation_question(self):
        wid = WriterIronyDensity()
        result = wid._split_sentences("Really! Are you sure? Yes.")
        self.assertEqual(len(result), 3)

    def test_trailing_punctuation(self):
        wid = WriterIronyDensity()
        result = wid._split_sentences("What?!")
        self.assertEqual(len(result), 1)


class TestVerbalIronyRate(unittest.TestCase):
    """Test measure_verbal_irony_rate."""

    def test_empty_text(self):
        wid = WriterIronyDensity()
        self.assertEqual(wid.measure_verbal_irony_rate(""), 0.0)

    def test_no_irony(self):
        wid = WriterIronyDensity()
        text = "The report was filed on time. All tasks were completed."
        self.assertEqual(wid.measure_verbal_irony_rate(text), 0.0)

    def test_oh_great(self):
        wid = WriterIronyDensity()
        text = "Oh great, another Monday morning meeting."
        self.assertGreater(wid.measure_verbal_irony_rate(text), 0.0)

    def test_what_a_brilliant_idea(self):
        wid = WriterIronyDensity()
        text = "What a brilliant idea to schedule a meeting during lunch."
        self.assertGreater(wid.measure_verbal_irony_rate(text), 0.0)

    def test_that_went_well(self):
        wid = WriterIronyDensity()
        text = "That went well, I suppose."
        self.assertGreater(wid.measure_verbal_irony_rate(text), 0.0)

    def test_big_surprise(self):
        wid = WriterIronyDensity()
        text = "Big surprise, the server crashed again."
        self.assertGreater(wid.measure_verbal_irony_rate(text), 0.0)

    def test_who_would_have_thought(self):
        wid = WriterIronyDensity()
        text = "Who would have thought that cutting tests would cause bugs."
        self.assertGreater(wid.measure_verbal_irony_rate(text), 0.0)

    def test_high_irony_rate(self):
        wid = WriterIronyDensity()
        text = "Oh great, a meeting. What a brilliant idea. That went well. Big surprise."
        rate = wid.measure_verbal_irony_rate(text)
        self.assertGreater(rate, 0.5)

    def test_case_insensitive(self):
        wid = WriterIronyDensity()
        text = "OH GREAT, another problem."
        self.assertGreater(wid.measure_verbal_irony_rate(text), 0.0)


class TestLitotesDensity(unittest.TestCase):
    """Test measure_litotes_density."""

    def test_empty_text(self):
        wid = WriterIronyDensity()
        self.assertEqual(wid.measure_litotes_density(""), 0.0)

    def test_no_litotes(self):
        wid = WriterIronyDensity()
        text = "The weather is pleasant today."
        self.assertEqual(wid.measure_litotes_density(text), 0.0)

    def test_not_bad(self):
        wid = WriterIronyDensity()
        text = "The results were not bad, considering the circumstances."
        self.assertGreater(wid.measure_litotes_density(text), 0.0)

    def test_no_small_feat(self):
        wid = WriterIronyDensity()
        text = "Completing this project in a week was no small feat."
        self.assertGreater(wid.measure_litotes_density(text), 0.0)

    def test_not_exactly_genius(self):
        wid = WriterIronyDensity()
        text = "That decision was not exactly a genius move."
        self.assertGreater(wid.measure_litotes_density(text), 0.0)

    def test_not_impossible(self):
        wid = WriterIronyDensity()
        text = "It's not impossible to fix this bug before Friday."
        self.assertGreater(wid.measure_litotes_density(text), 0.0)

    def test_not_unreasonable(self):
        wid = WriterIronyDensity()
        text = "The request was not unreasonable."
        self.assertGreater(wid.measure_litotes_density(text), 0.0)

    def test_not_without(self):
        wid = WriterIronyDensity()
        text = "The approach is not without its merits."
        self.assertGreater(wid.measure_litotes_density(text), 0.0)

    def test_hardly_a(self):
        wid = WriterIronyDensity()
        text = "That was hardly a triumph of engineering."
        self.assertGreater(wid.measure_litotes_density(text), 0.0)

    def test_nothing_if_not(self):
        wid = WriterIronyDensity()
        text = "He was nothing if not persistent."
        self.assertGreater(wid.measure_litotes_density(text), 0.0)


class TestRhetoricalNegationRate(unittest.TestCase):
    """Test measure_rhetorical_negation_rate."""

    def test_empty_text(self):
        wid = WriterIronyDensity()
        self.assertEqual(wid.measure_rhetorical_negation_rate(""), 0.0)

    def test_no_rhetorical_negation(self):
        wid = WriterIronyDensity()
        text = "The system works as designed."
        self.assertEqual(wid.measure_rhetorical_negation_rate(text), 0.0)

    def test_im_not_saying(self):
        wid = WriterIronyDensity()
        text = "I'm not saying it was a mistake, but the results speak for themselves."
        self.assertGreater(wid.measure_rhetorical_negation_rate(text), 0.0)

    def test_far_be_it(self):
        wid = WriterIronyDensity()
        text = "Far be it from me to question the architecture decisions."
        self.assertGreater(wid.measure_rhetorical_negation_rate(text), 0.0)

    def test_not_that_anyone_asked(self):
        wid = WriterIronyDensity()
        text = "Not that anyone asked, but the deployment pipeline needs work."
        self.assertGreater(wid.measure_rhetorical_negation_rate(text), 0.0)

    def test_i_dont_want_to_say(self):
        wid = WriterIronyDensity()
        text = "I don't want to say disaster, but the metrics tell a story."
        self.assertGreater(wid.measure_rhetorical_negation_rate(text), 0.0)

    def test_not_to_mention(self):
        wid = WriterIronyDensity()
        text = "The code needs refactoring, not to mention the test coverage."
        self.assertGreater(wid.measure_rhetorical_negation_rate(text), 0.0)

    def test_needless_to_say(self):
        wid = WriterIronyDensity()
        text = "Needless to say, the deadline was not met."
        self.assertGreater(wid.measure_rhetorical_negation_rate(text), 0.0)

    def test_not_pretend(self):
        wid = WriterIronyDensity()
        text = "Let's not pretend this was expected."
        self.assertGreater(wid.measure_rhetorical_negation_rate(text), 0.0)

    def test_without_wishing(self):
        wid = WriterIronyDensity()
        text = "Without wishing to offend, the design could be improved."
        self.assertGreater(wid.measure_rhetorical_negation_rate(text), 0.0)


class TestUnderstatementRatio(unittest.TestCase):
    """Test measure_understatement_ratio."""

    def test_empty_text(self):
        wid = WriterIronyDensity()
        self.assertEqual(wid.measure_understatement_ratio(""), 0.0)

    def test_no_understatement(self):
        wid = WriterIronyDensity()
        text = "The earthquake destroyed the building completely."
        self.assertEqual(wid.measure_understatement_ratio(text), 0.0)

    def test_bit_of_a_problem(self):
        wid = WriterIronyDensity()
        text = "We have a bit of a problem with the database migration."
        self.assertGreater(wid.measure_understatement_ratio(text), 0.0)

    def test_slightly_concerning(self):
        wid = WriterIronyDensity()
        text = "The error rate is slightly concerning."
        self.assertGreater(wid.measure_understatement_ratio(text), 0.0)

    def test_somewhat_inconvenient(self):
        wid = WriterIronyDensity()
        text = "The outage was somewhat inconvenient for users."
        self.assertGreater(wid.measure_understatement_ratio(text), 0.0)

    def test_mildly_disappointing(self):
        wid = WriterIronyDensity()
        text = "The launch results were mildly disappointing."
        self.assertGreater(wid.measure_understatement_ratio(text), 0.0)

    def test_slight_setback(self):
        wid = WriterIronyDensity()
        text = "Losing the primary database was a slight setback."
        self.assertGreater(wid.measure_understatement_ratio(text), 0.0)

    def test_nothing_major(self):
        wid = WriterIronyDensity()
        text = "Just a few crashes, nothing major."
        self.assertGreater(wid.measure_understatement_ratio(text), 0.0)

    def test_could_be_worse(self):
        wid = WriterIronyDensity()
        text = "Well, it could be worse."
        self.assertGreater(wid.measure_understatement_ratio(text), 0.0)

    def test_just_those_things(self):
        wid = WriterIronyDensity()
        text = "Data loss is just one of those things."
        self.assertGreater(wid.measure_understatement_ratio(text), 0.0)


class TestSocraticQuestioningRate(unittest.TestCase):
    """Test measure_socratic_questioning_rate."""

    def test_empty_text(self):
        wid = WriterIronyDensity()
        self.assertEqual(wid.measure_socratic_questioning_rate(""), 0.0)

    def test_genuine_question(self):
        wid = WriterIronyDensity()
        text = "What time is the meeting scheduled for?"
        self.assertEqual(wid.measure_socratic_questioning_rate(text), 0.0)

    def test_who_could_have_predicted(self):
        wid = WriterIronyDensity()
        text = "Who could have predicted that skipping tests would cause bugs?"
        self.assertGreater(wid.measure_socratic_questioning_rate(text), 0.0)

    def test_do_we_really_think(self):
        wid = WriterIronyDensity()
        text = "Do we really think deploying on Friday is wise?"
        self.assertGreater(wid.measure_socratic_questioning_rate(text), 0.0)

    def test_why_would_anyone(self):
        wid = WriterIronyDensity()
        text = "Why would anyone do that in production?"
        self.assertGreater(wid.measure_socratic_questioning_rate(text), 0.0)

    def test_how_is_that_possible(self):
        wid = WriterIronyDensity()
        text = "How is that even possible after three rounds of review?"
        self.assertGreater(wid.measure_socratic_questioning_rate(text), 0.0)

    def test_are_we_sure(self):
        wid = WriterIronyDensity()
        text = "Are we sure about that architectural decision?"
        self.assertGreater(wid.measure_socratic_questioning_rate(text), 0.0)

    def test_is_that_really(self):
        wid = WriterIronyDensity()
        text = "Is that really how we're handling authentication?"
        self.assertGreater(wid.measure_socratic_questioning_rate(text), 0.0)

    def test_anyone_else_noticing(self):
        wid = WriterIronyDensity()
        text = "Anyone else noticing this?"
        self.assertGreater(wid.measure_socratic_questioning_rate(text), 0.0)


class TestComputeIronyIndex(unittest.TestCase):
    """Test compute_irony_index."""

    def test_all_zeros(self):
        wid = WriterIronyDensity()
        self.assertEqual(wid.compute_irony_index(0, 0, 0, 0, 0), 0.0)

    def test_all_ones(self):
        wid = WriterIronyDensity()
        result = wid.compute_irony_index(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertAlmostEqual(result, 1.0)

    def test_weights_sum_to_one(self):
        wid = WriterIronyDensity()
        result = wid.compute_irony_index(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertAlmostEqual(result, 1.0)

    def test_verbal_only(self):
        wid = WriterIronyDensity()
        result = wid.compute_irony_index(1.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.25)

    def test_litotes_only(self):
        wid = WriterIronyDensity()
        result = wid.compute_irony_index(0.0, 1.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.20)

    def test_rhetorical_only(self):
        wid = WriterIronyDensity()
        result = wid.compute_irony_index(0.0, 0.0, 1.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.20)

    def test_understatement_only(self):
        wid = WriterIronyDensity()
        result = wid.compute_irony_index(0.0, 0.0, 0.0, 1.0, 0.0)
        self.assertAlmostEqual(result, 0.20)

    def test_socratic_only(self):
        wid = WriterIronyDensity()
        result = wid.compute_irony_index(0.0, 0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(result, 0.15)

    def test_mixed_values(self):
        wid = WriterIronyDensity()
        result = wid.compute_irony_index(0.5, 0.3, 0.2, 0.4, 0.1)
        expected = 0.5 * 0.25 + 0.3 * 0.20 + 0.2 * 0.20 + 0.4 * 0.20 + 0.1 * 0.15
        self.assertAlmostEqual(result, expected)


class TestClassify(unittest.TestCase):
    """Test classify method."""

    def test_satirical(self):
        wid = WriterIronyDensity()
        self.assertEqual(wid.classify(0.45), "satirical")
        self.assertEqual(wid.classify(0.50), "satirical")
        self.assertEqual(wid.classify(1.0), "satirical")

    def test_wry(self):
        wid = WriterIronyDensity()
        self.assertEqual(wid.classify(0.30), "wry")
        self.assertEqual(wid.classify(0.35), "wry")
        self.assertEqual(wid.classify(0.44), "wry")

    def test_dry(self):
        wid = WriterIronyDensity()
        self.assertEqual(wid.classify(0.15), "dry")
        self.assertEqual(wid.classify(0.20), "dry")
        self.assertEqual(wid.classify(0.29), "dry")

    def test_sincere(self):
        wid = WriterIronyDensity()
        self.assertEqual(wid.classify(0.05), "sincere")
        self.assertEqual(wid.classify(0.10), "sincere")
        self.assertEqual(wid.classify(0.14), "sincere")

    def test_literal(self):
        wid = WriterIronyDensity()
        self.assertEqual(wid.classify(0.0), "literal")
        self.assertEqual(wid.classify(0.01), "literal")
        self.assertEqual(wid.classify(0.04), "literal")


class TestMeasure(unittest.TestCase):
    """Test the measure method (integration)."""

    def test_empty_text(self):
        wid = WriterIronyDensity()
        result = wid.measure("")
        self.assertEqual(result["verbal_irony_rate"], 0.0)
        self.assertEqual(result["litotes_density"], 0.0)
        self.assertEqual(result["rhetorical_negation_rate"], 0.0)
        self.assertEqual(result["understatement_ratio"], 0.0)
        self.assertEqual(result["socratic_questioning_rate"], 0.0)
        self.assertEqual(result["irony_index"], 0.0)
        self.assertEqual(result["classification"], "literal")

    def test_satirical_text(self):
        wid = WriterIronyDensity()
        text = """Oh great, another meeting. What a brilliant idea to
        schedule it at lunch. I'm not saying it was a waste, but far
        be it from me to suggest we could have emailed. Not exactly a
        masterpiece of productivity. Slightly concerning that we spent
        forty minutes on font choice. And you think that's a good use
        of time? It's fine. Who could have predicted this?"""
        result = wid.measure(text)
        self.assertGreater(result["irony_index"], 0.0)
        self.assertIn(result["classification"], ["satirical", "wry", "dry"])

    def test_literal_text(self):
        wid = WriterIronyDensity()
        text = """The quarterly report was submitted on time. Revenue
        increased by eight percent. The team completed all tasks.
        Customer satisfaction scores remained stable."""
        result = wid.measure(text)
        self.assertEqual(result["irony_index"], 0.0)
        self.assertEqual(result["classification"], "literal")

    def test_result_keys(self):
        wid = WriterIronyDensity()
        result = wid.measure("Some text here.")
        expected_keys = {
            "verbal_irony_rate", "litotes_density",
            "rhetorical_negation_rate", "understatement_ratio",
            "socratic_questioning_rate", "irony_index", "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_result_rounding(self):
        wid = WriterIronyDensity()
        text = "Oh great, not bad. I'm not saying it was slightly concerning."
        result = wid.measure(text)
        for key in ["verbal_irony_rate", "litotes_density",
                     "rhetorical_negation_rate", "understatement_ratio",
                     "socratic_questioning_rate", "irony_index"]:
            val = result[key]
            self.assertEqual(val, round(val, 4))

    def test_single_sentence(self):
        wid = WriterIronyDensity()
        result = wid.measure("Oh great.")
        self.assertGreater(result["verbal_irony_rate"], 0.0)

    def test_high_irony_classification(self):
        wid = WriterIronyDensity()
        text = """Oh great, what a brilliant idea. I'm not saying it was
        a disaster, but far be it from me to suggest otherwise. Not
        exactly a triumph. Slightly concerning, mildly disappointing,
        a bit of a problem. Who could have predicted this? And you
        think that's wise? Do we really think this is sound?"""
        result = wid.measure(text)
        self.assertIn(result["classification"], ["satirical", "wry", "dry"])


class TestPatternCoverage(unittest.TestCase):
    """Test that patterns actually match expected strings."""

    def test_verbal_irony_patterns_match(self):
        test_cases = [
            "oh great, another problem",
            "what a brilliant idea to do that",
            "that went well",
            "big surprise there",
            "who would have thought",
        ]
        for text in test_cases:
            matched = any(p.search(text) for p in VERBAL_IRONY_PATTERNS)
            self.assertTrue(matched, f"Pattern should match: {text!r}")

    def test_litotes_patterns_match(self):
        test_cases = [
            "not bad at all",
            "no small feat",
            "not exactly a genius",
            "it's not impossible",
            "not unreasonable",
        ]
        for text in test_cases:
            matched = any(p.search(text) for p in LITOTES_PATTERNS)
            self.assertTrue(matched, f"Pattern should match: {text!r}")

    def test_rhetorical_negation_patterns_match(self):
        test_cases = [
            "I'm not saying it was wrong",
            "not that anyone asked",
            "far be it from me to suggest",
            "I don't want to say failure",
            "needless to say",
        ]
        for text in test_cases:
            matched = any(p.search(text) for p in RHETORICAL_NEGATION_PATTERNS)
            self.assertTrue(matched, f"Pattern should match: {text!r}")

    def test_understatement_patterns_match(self):
        test_cases = [
            "a bit of a problem",
            "slightly concerning trend",
            "somewhat inconvenient",
            "mildly disappointing results",
            "nothing major",
        ]
        for text in test_cases:
            matched = any(p.search(text) for p in UNDERSTATEMENT_PATTERNS)
            self.assertTrue(matched, f"Pattern should match: {text!r}")

    def test_socratic_patterns_match(self):
        test_cases = [
            "who could have predicted this",
            "do we really think this works",
            "why would anyone do that",
            "how is that even possible",
            "are we sure about that",
        ]
        for text in test_cases:
            matched = any(p.search(text) for p in SOCRATIC_QUESTION_PATTERNS)
            self.assertTrue(matched, f"Pattern should match: {text!r}")

    def test_literal_text_no_matches(self):
        literal = "The system processed 1000 requests per second."
        all_patterns = (
            VERBAL_IRONY_PATTERNS + LITOTES_PATTERNS +
            RHETORICAL_NEGATION_PATTERNS + UNDERSTATEMENT_PATTERNS +
            SOCRATIC_QUESTION_PATTERNS
        )
        for p in all_patterns:
            self.assertIsNone(
                p.search(literal),
                f"Pattern {p.pattern!r} should not match literal text"
            )


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_single_word(self):
        wid = WriterIronyDensity()
        result = wid.measure("Hello")
        self.assertEqual(result["irony_index"], 0.0)

    def test_only_punctuation(self):
        wid = WriterIronyDensity()
        result = wid.measure("...!!! ???...")
        self.assertEqual(result["irony_index"], 0.0)

    def test_repeated_sentences(self):
        wid = WriterIronyDensity()
        text = "Oh great. " * 20
        result = wid.measure(text)
        self.assertGreater(result["verbal_irony_rate"], 0.0)

    def test_mixed_content(self):
        wid = WriterIronyDensity()
        text = """The system works well. Oh great, another alert.
        Revenue increased. Not bad for a first attempt. The deployment
        succeeded. I'm not saying it was perfect. Tests passed."""
        result = wid.measure(text)
        self.assertGreater(result["irony_index"], 0.0)
        self.assertIn(result["classification"], ["wry", "dry", "sincere"])

    def test_very_long_text(self):
        wid = WriterIronyDensity()
        text = "The server responded normally. " * 500
        result = wid.measure(text)
        self.assertEqual(result["irony_index"], 0.0)

    def test_unicode_text(self):
        wid = WriterIronyDensity()
        text = "The café served excellent coffee. Not bad at all."
        result = wid.measure(text)
        self.assertIsInstance(result["irony_index"], float)


if __name__ == "__main__":
    unittest.main()
